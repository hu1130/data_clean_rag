"""Incremental ingestion manifest utilities."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional


MANIFEST_VERSION = 1
SQLITE_EXTENSIONS = {".sqlite", ".sqlite3", ".db"}


def compute_content_hash(content: bytes) -> str:
    """Return a stable sha256 hash for file content."""
    return hashlib.sha256(content).hexdigest()


def file_key_for(filename: str, source_file: Optional[str] = None) -> str:
    """Return the stable key used to track a source file in the manifest."""
    return source_file or filename or "inline"


class ProcessingManifest:
    """Small JSON manifest used to skip unchanged files."""

    def __init__(self, path: str = "data/manifest.json"):
        self.path = Path(path)
        self.data = self._load()

    def _load(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {"version": MANIFEST_VERSION, "files": {}}

        with self.path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)

        if not isinstance(data, dict):
            return {"version": MANIFEST_VERSION, "files": {}}

        data.setdefault("version", MANIFEST_VERSION)
        data.setdefault("files", {})
        return data

    @property
    def files(self) -> Dict[str, Dict[str, Any]]:
        return self.data.setdefault("files", {})

    def get(self, file_key: str) -> Optional[Dict[str, Any]]:
        record = self.files.get(file_key)
        return dict(record) if isinstance(record, dict) else None

    def is_unchanged(self, file_key: str, content_hash: str) -> bool:
        record = self.get(file_key)
        if not record:
            return False
        return (
            record.get("status") == "processed"
            and record.get("content_hash") == content_hash
        )

    def mark_processed(
        self,
        *,
        file_key: str,
        content_hash: str,
        filename: str,
        file_type: Optional[str],
        size_bytes: int,
        document_count: int,
        chunk_count: int,
        chunk_ids: Optional[List[str]] = None,
        source_file: Optional[str] = None,
        stats: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        record = {
            "file_key": file_key,
            "filename": filename,
            "source_file": source_file,
            "file_type": file_type,
            "content_hash": content_hash,
            "size_bytes": size_bytes,
            "document_count": document_count,
            "chunk_count": chunk_count,
            "chunk_ids": list(chunk_ids or []),
            "status": "processed",
            "processed_at": time.time(),
        }
        if stats is not None:
            record["stats"] = stats

        self.files[file_key] = record
        return dict(record)

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_name(
            f".{self.path.name}.{os.getpid()}.{int(time.time() * 1000)}.tmp"
        )
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(self.data, handle, ensure_ascii=False, indent=2)
        temp_path.replace(self.path)

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.data)


class SQLiteProcessingManifest:
    """SQLite-backed manifest for safer long-running incremental ingestion."""

    def __init__(self, path: str = "data/manifest.sqlite3", timeout: float = 30.0):
        self.path = Path(path)
        self.timeout = timeout
        self._ensure_schema()

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.path), timeout=self.timeout)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    @contextmanager
    def _session(self):
        """Yield a connection, commit on success, roll back on error, always close."""
        connection = self._connect()
        try:
            yield connection
        except Exception:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            connection.close()

    def _ensure_schema(self):
        with self._session() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS files (
                    file_key TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    source_file TEXT,
                    file_type TEXT,
                    content_hash TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    document_count INTEGER NOT NULL DEFAULT 0,
                    chunk_count INTEGER NOT NULL DEFAULT 0,
                    chunk_ids TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL,
                    processed_at REAL NOT NULL,
                    stats TEXT
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_files_content_hash ON files(content_hash)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_files_status ON files(status)"
            )

    def get(self, file_key: str) -> Optional[Dict[str, Any]]:
        with self._session() as connection:
            row = connection.execute(
                "SELECT * FROM files WHERE file_key = ?",
                (file_key,),
            ).fetchone()

        if row is None:
            return None
        return self._row_to_record(row)

    def is_unchanged(self, file_key: str, content_hash: str) -> bool:
        record = self.get(file_key)
        if not record:
            return False
        return (
            record.get("status") == "processed"
            and record.get("content_hash") == content_hash
        )

    def mark_processed(
        self,
        *,
        file_key: str,
        content_hash: str,
        filename: str,
        file_type: Optional[str],
        size_bytes: int,
        document_count: int,
        chunk_count: int,
        chunk_ids: Optional[List[str]] = None,
        source_file: Optional[str] = None,
        stats: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        processed_at = time.time()
        record = {
            "file_key": file_key,
            "filename": filename,
            "source_file": source_file,
            "file_type": file_type,
            "content_hash": content_hash,
            "size_bytes": size_bytes,
            "document_count": document_count,
            "chunk_count": chunk_count,
            "chunk_ids": list(chunk_ids or []),
            "status": "processed",
            "processed_at": processed_at,
        }
        if stats is not None:
            record["stats"] = stats

        with self._session() as connection:
            connection.execute(
                """
                INSERT INTO files (
                    file_key, filename, source_file, file_type, content_hash,
                    size_bytes, document_count, chunk_count, chunk_ids,
                    status, processed_at, stats
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(file_key) DO UPDATE SET
                    filename = excluded.filename,
                    source_file = excluded.source_file,
                    file_type = excluded.file_type,
                    content_hash = excluded.content_hash,
                    size_bytes = excluded.size_bytes,
                    document_count = excluded.document_count,
                    chunk_count = excluded.chunk_count,
                    chunk_ids = excluded.chunk_ids,
                    status = excluded.status,
                    processed_at = excluded.processed_at,
                    stats = excluded.stats
                """,
                (
                    file_key,
                    filename,
                    source_file,
                    file_type,
                    content_hash,
                    size_bytes,
                    document_count,
                    chunk_count,
                    json.dumps(list(chunk_ids or []), ensure_ascii=False),
                    "processed",
                    processed_at,
                    json.dumps(stats, ensure_ascii=False) if stats is not None else None,
                ),
            )

        return dict(record)

    def save(self):
        self._ensure_schema()

    def to_dict(self) -> Dict[str, Any]:
        with self._session() as connection:
            rows = connection.execute("SELECT * FROM files ORDER BY file_key").fetchall()
        return {
            "version": MANIFEST_VERSION,
            "backend": "sqlite",
            "files": {
                row["file_key"]: self._row_to_record(row)
                for row in rows
            },
        }

    def _row_to_record(self, row: sqlite3.Row) -> Dict[str, Any]:
        stats = row["stats"]
        return {
            "file_key": row["file_key"],
            "filename": row["filename"],
            "source_file": row["source_file"],
            "file_type": row["file_type"],
            "content_hash": row["content_hash"],
            "size_bytes": row["size_bytes"],
            "document_count": row["document_count"],
            "chunk_count": row["chunk_count"],
            "chunk_ids": json.loads(row["chunk_ids"] or "[]"),
            "status": row["status"],
            "processed_at": row["processed_at"],
            "stats": json.loads(stats) if stats else None,
        }


def create_processing_manifest(
    path: str = "data/manifest.sqlite3",
    backend: str = "auto",
):
    """Create a JSON or SQLite manifest based on backend or file extension."""
    normalized_backend = (backend or "auto").lower()
    suffix = Path(path).suffix.lower()
    if normalized_backend == "auto":
        normalized_backend = "sqlite" if suffix in SQLITE_EXTENSIONS else "json"

    if normalized_backend == "sqlite":
        return SQLiteProcessingManifest(path)
    if normalized_backend == "json":
        return ProcessingManifest(path)
    raise ValueError(f"Unsupported manifest backend: {backend}")
