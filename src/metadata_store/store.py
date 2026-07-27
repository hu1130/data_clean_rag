"""Business metadata persistence for the route-A production architecture.

Route A keeps vector search in a dedicated vector DB, while MySQL stores
business metadata, processing runs, file reports, and chunk audit records.
SQLite is provided only as a local/test-compatible implementation of the same
write path.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


JsonDict = Dict[str, Any]


def _json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)


def _json_loads(value: Any) -> Any:
    if value in (None, ""):
        return {}
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _file_key(metadata: JsonDict) -> str:
    return (
        metadata.get("file_key")
        or metadata.get("source_file")
        or metadata.get("filename")
        or "inline"
    )


def _stats_count(stats: JsonDict, key: str) -> int:
    summary = (stats.get("processing_report") or {}).get("summary") or {}
    return _as_int(stats.get(key, summary.get(key, 0)), 0)


def _files_from_stats(stats: JsonDict, chunks: Optional[List[JsonDict]]) -> List[JsonDict]:
    report = stats.get("processing_report") or {}
    files = report.get("files") or []
    if files:
        return [dict(item) for item in files]

    derived: Dict[str, JsonDict] = {}
    for item in chunks or []:
        metadata = dict(item.get("metadata") or {})
        key = _file_key(metadata)
        record = derived.setdefault(
            key,
            {
                "file": key,
                "file_key": key,
                "filename": metadata.get("filename", key),
                "source_file": metadata.get("source_file"),
                "file_type": metadata.get("file_type"),
                "file_hash": metadata.get("file_hash") or metadata.get("content_hash"),
                "content_hash": metadata.get("content_hash") or metadata.get("file_hash"),
                "file_size_bytes": metadata.get("file_size_bytes"),
                "input_documents": 0,
                "chunks": 0,
                "rejected_documents": 0,
                "rejection_reasons": {},
                "document_part_counts": {},
            },
        )
        record["chunks"] += 1
    return list(derived.values())


def _chunk_rows(run_id: str, chunks: Optional[List[JsonDict]]) -> Iterable[JsonDict]:
    for index, item in enumerate(chunks or []):
        metadata = dict(item.get("metadata") or {})
        text = item.get("text") or ""
        chunk_id = metadata.get("chunk_id") or metadata.get("child_id")
        if not chunk_id:
            chunk_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"data-clean-rag-chunk:{run_id}:{index}:{text[:200]}"))

        yield {
            "chunk_id": str(chunk_id),
            "run_id": run_id,
            "parent_id": metadata.get("parent_id"),
            "file_key": _file_key(metadata),
            "filename": metadata.get("filename"),
            "parent_type": metadata.get("parent_type"),
            "parent_heading_path": metadata.get("parent_heading_path") or metadata.get("heading_path"),
            "chunk_index": _as_int(metadata.get("chunk_index"), index),
            "child_index": _as_int(metadata.get("child_index"), index),
            "child_count": _as_int(metadata.get("child_count") or metadata.get("total_chunks"), 1),
            "text_preview": text[:800],
            "metadata_json": _json_dumps(metadata),
            "created_at": time.time(),
        }


class BaseMetadataStore(ABC):
    """Interface for processing metadata persistence."""

    enabled = True
    store_type = "base"

    def __init__(self, *, fail_on_error: bool = True):
        self.fail_on_error = fail_on_error

    @abstractmethod
    def connect(self) -> "BaseMetadataStore":
        raise NotImplementedError

    @abstractmethod
    def close(self):
        raise NotImplementedError

    @abstractmethod
    def record_processing_run(
        self,
        stats: JsonDict,
        chunks: Optional[List[JsonDict]] = None,
        *,
        status: str = "completed",
        run_id: Optional[str] = None,
    ) -> Optional[str]:
        raise NotImplementedError

    @abstractmethod
    def get_recent_runs(self, limit: int = 20) -> List[JsonDict]:
        raise NotImplementedError

    @abstractmethod
    def get_run(self, run_id: str) -> Optional[JsonDict]:
        raise NotImplementedError

    def health(self) -> JsonDict:
        return {
            "enabled": self.enabled,
            "type": self.store_type,
            "status": "ready",
            "fail_on_error": self.fail_on_error,
        }


class DisabledMetadataStore(BaseMetadataStore):
    enabled = False
    store_type = "disabled"

    def __init__(self, config: Optional[JsonDict] = None):
        super().__init__(fail_on_error=False)
        self.config = dict(config or {})

    def connect(self) -> "DisabledMetadataStore":
        return self

    def close(self):
        return None

    def record_processing_run(
        self,
        stats: JsonDict,
        chunks: Optional[List[JsonDict]] = None,
        *,
        status: str = "completed",
        run_id: Optional[str] = None,
    ) -> Optional[str]:
        return None

    def get_recent_runs(self, limit: int = 20) -> List[JsonDict]:
        return []

    def get_run(self, run_id: str) -> Optional[JsonDict]:
        return None

    def health(self) -> JsonDict:
        return {
            "enabled": False,
            "type": "disabled",
            "status": "disabled",
            "fail_on_error": False,
        }


class _RelationalMetadataStore(BaseMetadataStore):
    """Shared write/query logic for relational metadata stores."""

    def _record_common(
        self,
        stats: JsonDict,
        chunks: Optional[List[JsonDict]],
        *,
        status: str,
        run_id: Optional[str],
    ) -> str:
        self.connect()
        actual_run_id = run_id or str(uuid.uuid4())
        now = time.time()
        processing_report = stats.get("processing_report") or {}
        quality_summary = stats.get("quality_summary") or processing_report.get("quality_summary") or {}

        self._upsert_processing_run(
            {
                "run_id": actual_run_id,
                "status": status,
                "started_at": stats.get("started_at", now),
                "finished_at": stats.get("finished_at", now),
                "input_count": _stats_count(stats, "input_count"),
                "cleaned_count": _stats_count(stats, "cleaned_count"),
                "filtered_count": _stats_count(stats, "filtered_count"),
                "deduped_count": _stats_count(stats, "deduped_count"),
                "chunked_count": _stats_count(stats, "chunked_count"),
                "stored_count": _stats_count(stats, "stored_count"),
                "quality_summary_json": _json_dumps(quality_summary),
                "processing_report_json": _json_dumps(processing_report),
                "metadata_json": _json_dumps(
                    {
                        "vector_db": processing_report.get("vector_db"),
                        "embedding": processing_report.get("embedding"),
                        "reranker": processing_report.get("reranker"),
                    }
                ),
            }
        )

        for file_record in _files_from_stats(stats, chunks):
            self._upsert_file(file_record, now)

        for chunk_record in _chunk_rows(actual_run_id, chunks):
            self._upsert_chunk(chunk_record)

        self._commit()
        return actual_run_id

    def _decode_run(self, row: Optional[JsonDict]) -> Optional[JsonDict]:
        if not row:
            return None
        decoded = dict(row)
        decoded["quality_summary"] = _json_loads(decoded.pop("quality_summary_json", None))
        decoded["processing_report"] = _json_loads(decoded.pop("processing_report_json", None))
        decoded["metadata"] = _json_loads(decoded.pop("metadata_json", None))
        return decoded

    def _decode_chunk(self, row: JsonDict) -> JsonDict:
        decoded = dict(row)
        decoded["metadata"] = _json_loads(decoded.pop("metadata_json", None))
        return decoded

    @abstractmethod
    def _upsert_processing_run(self, row: JsonDict):
        raise NotImplementedError

    @abstractmethod
    def _upsert_file(self, record: JsonDict, now: float):
        raise NotImplementedError

    @abstractmethod
    def _upsert_chunk(self, row: JsonDict):
        raise NotImplementedError

    @abstractmethod
    def _commit(self):
        raise NotImplementedError


class SQLiteMetadataStore(_RelationalMetadataStore):
    """SQLite implementation used for local validation and unit tests."""

    store_type = "sqlite"

    def __init__(self, path: str, *, fail_on_error: bool = True):
        super().__init__(fail_on_error=fail_on_error)
        self.path = path
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self) -> "SQLiteMetadataStore":
        if self._conn:
            return self
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()
        return self

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def health(self) -> JsonDict:
        return {
            **super().health(),
            "path": self.path,
            "status": "connected" if self._conn else "not_connected",
        }

    def _execute(self, sql: str, params: tuple = ()):
        if not self._conn:
            raise RuntimeError("SQLite metadata store is not connected")
        return self._conn.execute(sql, params)

    def _init_schema(self):
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS metadata_processing_runs (
                run_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                started_at REAL,
                finished_at REAL,
                input_count INTEGER DEFAULT 0,
                cleaned_count INTEGER DEFAULT 0,
                filtered_count INTEGER DEFAULT 0,
                deduped_count INTEGER DEFAULT 0,
                chunked_count INTEGER DEFAULT 0,
                stored_count INTEGER DEFAULT 0,
                quality_summary_json TEXT,
                processing_report_json TEXT,
                metadata_json TEXT
            )
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS metadata_files (
                file_key TEXT PRIMARY KEY,
                filename TEXT,
                source_file TEXT,
                file_type TEXT,
                file_hash TEXT,
                content_hash TEXT,
                file_size_bytes INTEGER,
                document_count INTEGER DEFAULT 0,
                chunk_count INTEGER DEFAULT 0,
                status TEXT,
                first_seen_at REAL,
                updated_at REAL,
                last_processed_at REAL,
                metadata_json TEXT
            )
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS metadata_chunks (
                chunk_id TEXT PRIMARY KEY,
                run_id TEXT,
                parent_id TEXT,
                file_key TEXT,
                filename TEXT,
                parent_type TEXT,
                parent_heading_path TEXT,
                chunk_index INTEGER DEFAULT 0,
                child_index INTEGER DEFAULT 0,
                child_count INTEGER DEFAULT 1,
                text_preview TEXT,
                metadata_json TEXT,
                created_at REAL
            )
            """
        )
        self._execute("CREATE INDEX IF NOT EXISTS idx_metadata_chunks_run_id ON metadata_chunks(run_id)")
        self._execute("CREATE INDEX IF NOT EXISTS idx_metadata_chunks_file_key ON metadata_chunks(file_key)")
        self._execute("CREATE INDEX IF NOT EXISTS idx_metadata_chunks_parent_id ON metadata_chunks(parent_id)")
        self._commit()

    def _commit(self):
        if self._conn:
            self._conn.commit()

    def record_processing_run(
        self,
        stats: JsonDict,
        chunks: Optional[List[JsonDict]] = None,
        *,
        status: str = "completed",
        run_id: Optional[str] = None,
    ) -> Optional[str]:
        return self._record_common(stats, chunks, status=status, run_id=run_id)

    def _upsert_processing_run(self, row: JsonDict):
        self._execute(
            """
            INSERT INTO metadata_processing_runs (
                run_id, status, started_at, finished_at, input_count, cleaned_count,
                filtered_count, deduped_count, chunked_count, stored_count,
                quality_summary_json, processing_report_json, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                status=excluded.status,
                started_at=excluded.started_at,
                finished_at=excluded.finished_at,
                input_count=excluded.input_count,
                cleaned_count=excluded.cleaned_count,
                filtered_count=excluded.filtered_count,
                deduped_count=excluded.deduped_count,
                chunked_count=excluded.chunked_count,
                stored_count=excluded.stored_count,
                quality_summary_json=excluded.quality_summary_json,
                processing_report_json=excluded.processing_report_json,
                metadata_json=excluded.metadata_json
            """,
            (
                row["run_id"],
                row["status"],
                row["started_at"],
                row["finished_at"],
                row["input_count"],
                row["cleaned_count"],
                row["filtered_count"],
                row["deduped_count"],
                row["chunked_count"],
                row["stored_count"],
                row["quality_summary_json"],
                row["processing_report_json"],
                row["metadata_json"],
            ),
        )

    def _upsert_file(self, record: JsonDict, now: float):
        file_key = record.get("file_key") or record.get("file") or record.get("filename") or "inline"
        self._execute(
            """
            INSERT INTO metadata_files (
                file_key, filename, source_file, file_type, file_hash, content_hash,
                file_size_bytes, document_count, chunk_count, status, first_seen_at,
                updated_at, last_processed_at, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(file_key) DO UPDATE SET
                filename=excluded.filename,
                source_file=excluded.source_file,
                file_type=excluded.file_type,
                file_hash=excluded.file_hash,
                content_hash=excluded.content_hash,
                file_size_bytes=excluded.file_size_bytes,
                document_count=excluded.document_count,
                chunk_count=excluded.chunk_count,
                status=excluded.status,
                updated_at=excluded.updated_at,
                last_processed_at=excluded.last_processed_at,
                metadata_json=excluded.metadata_json
            """,
            (
                file_key,
                record.get("filename", file_key),
                record.get("source_file"),
                record.get("file_type"),
                record.get("file_hash") or record.get("content_hash"),
                record.get("content_hash") or record.get("file_hash"),
                record.get("file_size_bytes"),
                _as_int(record.get("input_documents", record.get("document_count", 0))),
                _as_int(record.get("chunks", record.get("chunk_count", 0))),
                record.get("status", "processed"),
                now,
                now,
                now,
                _json_dumps(record),
            ),
        )

    def _upsert_chunk(self, row: JsonDict):
        self._execute(
            """
            INSERT INTO metadata_chunks (
                chunk_id, run_id, parent_id, file_key, filename, parent_type,
                parent_heading_path, chunk_index, child_index, child_count,
                text_preview, metadata_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chunk_id) DO UPDATE SET
                run_id=excluded.run_id,
                parent_id=excluded.parent_id,
                file_key=excluded.file_key,
                filename=excluded.filename,
                parent_type=excluded.parent_type,
                parent_heading_path=excluded.parent_heading_path,
                chunk_index=excluded.chunk_index,
                child_index=excluded.child_index,
                child_count=excluded.child_count,
                text_preview=excluded.text_preview,
                metadata_json=excluded.metadata_json,
                created_at=excluded.created_at
            """,
            (
                row["chunk_id"],
                row["run_id"],
                row["parent_id"],
                row["file_key"],
                row["filename"],
                row["parent_type"],
                row["parent_heading_path"],
                row["chunk_index"],
                row["child_index"],
                row["child_count"],
                row["text_preview"],
                row["metadata_json"],
                row["created_at"],
            ),
        )

    def get_recent_runs(self, limit: int = 20) -> List[JsonDict]:
        self.connect()
        cursor = self._execute(
            """
            SELECT *
            FROM metadata_processing_runs
            ORDER BY finished_at DESC
            LIMIT ?
            """,
            (_as_int(limit, 20),),
        )
        return [self._decode_run(dict(row)) for row in cursor.fetchall()]

    def get_run(self, run_id: str) -> Optional[JsonDict]:
        self.connect()
        cursor = self._execute("SELECT * FROM metadata_processing_runs WHERE run_id = ?", (run_id,))
        run = self._decode_run(dict(cursor.fetchone() or {}))
        if not run:
            return None
        chunk_cursor = self._execute(
            """
            SELECT *
            FROM metadata_chunks
            WHERE run_id = ?
            ORDER BY chunk_index, child_index
            """,
            (run_id,),
        )
        run["chunks"] = [self._decode_chunk(dict(row)) for row in chunk_cursor.fetchall()]
        return run


class MySQLMetadataStore(_RelationalMetadataStore):
    """MySQL implementation for route-A production metadata persistence."""

    store_type = "mysql"

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 3306,
        database: str = "data_clean_rag",
        user: str = "root",
        password: str = "",
        charset: str = "utf8mb4",
        connect_timeout: int = 10,
        fail_on_error: bool = True,
    ):
        super().__init__(fail_on_error=fail_on_error)
        self.host = host
        self.port = int(port)
        self.database = database
        self.user = user
        self.password = password or ""
        self.charset = charset
        self.connect_timeout = int(connect_timeout)
        self._conn = None

    def connect(self) -> "MySQLMetadataStore":
        if self._conn:
            return self
        try:
            import pymysql
            from pymysql.cursors import DictCursor
        except ImportError as exc:
            raise ImportError(
                "metadata_db.type=mysql requires PyMySQL. "
                "Install it with: python -m pip install PyMySQL"
            ) from exc

        self._conn = pymysql.connect(
            host=self.host,
            port=self.port,
            database=self.database,
            user=self.user,
            password=self.password,
            charset=self.charset,
            connect_timeout=self.connect_timeout,
            autocommit=False,
            cursorclass=DictCursor,
        )
        self._init_schema()
        return self

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def health(self) -> JsonDict:
        return {
            **super().health(),
            "host": self.host,
            "port": self.port,
            "database": self.database,
            "user": self.user,
            "status": "connected" if self._conn else "not_connected",
        }

    def _execute(self, sql: str, params: tuple = ()):
        if not self._conn:
            raise RuntimeError("MySQL metadata store is not connected")
        with self._conn.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor

    def _fetchall(self, sql: str, params: tuple = ()) -> List[JsonDict]:
        if not self._conn:
            raise RuntimeError("MySQL metadata store is not connected")
        with self._conn.cursor() as cursor:
            cursor.execute(sql, params)
            return list(cursor.fetchall())

    def _fetchone(self, sql: str, params: tuple = ()) -> Optional[JsonDict]:
        if not self._conn:
            raise RuntimeError("MySQL metadata store is not connected")
        with self._conn.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchone()

    def _init_schema(self):
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS metadata_processing_runs (
                run_id VARCHAR(128) PRIMARY KEY,
                status VARCHAR(32) NOT NULL,
                started_at DOUBLE,
                finished_at DOUBLE,
                input_count INT DEFAULT 0,
                cleaned_count INT DEFAULT 0,
                filtered_count INT DEFAULT 0,
                deduped_count INT DEFAULT 0,
                chunked_count INT DEFAULT 0,
                stored_count INT DEFAULT 0,
                quality_summary_json LONGTEXT,
                processing_report_json LONGTEXT,
                metadata_json LONGTEXT
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS metadata_files (
                file_key VARCHAR(512) PRIMARY KEY,
                filename VARCHAR(512),
                source_file VARCHAR(1024),
                file_type VARCHAR(64),
                file_hash VARCHAR(128),
                content_hash VARCHAR(128),
                file_size_bytes BIGINT,
                document_count INT DEFAULT 0,
                chunk_count INT DEFAULT 0,
                status VARCHAR(32),
                first_seen_at DOUBLE,
                updated_at DOUBLE,
                last_processed_at DOUBLE,
                metadata_json LONGTEXT
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS metadata_chunks (
                chunk_id VARCHAR(128) PRIMARY KEY,
                run_id VARCHAR(128),
                parent_id VARCHAR(128),
                file_key VARCHAR(512),
                filename VARCHAR(512),
                parent_type VARCHAR(64),
                parent_heading_path VARCHAR(1024),
                chunk_index INT DEFAULT 0,
                child_index INT DEFAULT 0,
                child_count INT DEFAULT 1,
                text_preview TEXT,
                metadata_json LONGTEXT,
                created_at DOUBLE,
                KEY idx_metadata_chunks_run_id (run_id),
                KEY idx_metadata_chunks_file_key (file_key),
                KEY idx_metadata_chunks_parent_id (parent_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        self._commit()

    def _commit(self):
        if self._conn:
            self._conn.commit()

    def record_processing_run(
        self,
        stats: JsonDict,
        chunks: Optional[List[JsonDict]] = None,
        *,
        status: str = "completed",
        run_id: Optional[str] = None,
    ) -> Optional[str]:
        return self._record_common(stats, chunks, status=status, run_id=run_id)

    def _upsert_processing_run(self, row: JsonDict):
        self._execute(
            """
            INSERT INTO metadata_processing_runs (
                run_id, status, started_at, finished_at, input_count, cleaned_count,
                filtered_count, deduped_count, chunked_count, stored_count,
                quality_summary_json, processing_report_json, metadata_json
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                status=VALUES(status),
                started_at=VALUES(started_at),
                finished_at=VALUES(finished_at),
                input_count=VALUES(input_count),
                cleaned_count=VALUES(cleaned_count),
                filtered_count=VALUES(filtered_count),
                deduped_count=VALUES(deduped_count),
                chunked_count=VALUES(chunked_count),
                stored_count=VALUES(stored_count),
                quality_summary_json=VALUES(quality_summary_json),
                processing_report_json=VALUES(processing_report_json),
                metadata_json=VALUES(metadata_json)
            """,
            (
                row["run_id"],
                row["status"],
                row["started_at"],
                row["finished_at"],
                row["input_count"],
                row["cleaned_count"],
                row["filtered_count"],
                row["deduped_count"],
                row["chunked_count"],
                row["stored_count"],
                row["quality_summary_json"],
                row["processing_report_json"],
                row["metadata_json"],
            ),
        )

    def _upsert_file(self, record: JsonDict, now: float):
        file_key = record.get("file_key") or record.get("file") or record.get("filename") or "inline"
        self._execute(
            """
            INSERT INTO metadata_files (
                file_key, filename, source_file, file_type, file_hash, content_hash,
                file_size_bytes, document_count, chunk_count, status, first_seen_at,
                updated_at, last_processed_at, metadata_json
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                filename=VALUES(filename),
                source_file=VALUES(source_file),
                file_type=VALUES(file_type),
                file_hash=VALUES(file_hash),
                content_hash=VALUES(content_hash),
                file_size_bytes=VALUES(file_size_bytes),
                document_count=VALUES(document_count),
                chunk_count=VALUES(chunk_count),
                status=VALUES(status),
                updated_at=VALUES(updated_at),
                last_processed_at=VALUES(last_processed_at),
                metadata_json=VALUES(metadata_json)
            """,
            (
                file_key,
                record.get("filename", file_key),
                record.get("source_file"),
                record.get("file_type"),
                record.get("file_hash") or record.get("content_hash"),
                record.get("content_hash") or record.get("file_hash"),
                record.get("file_size_bytes"),
                _as_int(record.get("input_documents", record.get("document_count", 0))),
                _as_int(record.get("chunks", record.get("chunk_count", 0))),
                record.get("status", "processed"),
                now,
                now,
                now,
                _json_dumps(record),
            ),
        )

    def _upsert_chunk(self, row: JsonDict):
        self._execute(
            """
            INSERT INTO metadata_chunks (
                chunk_id, run_id, parent_id, file_key, filename, parent_type,
                parent_heading_path, chunk_index, child_index, child_count,
                text_preview, metadata_json, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                run_id=VALUES(run_id),
                parent_id=VALUES(parent_id),
                file_key=VALUES(file_key),
                filename=VALUES(filename),
                parent_type=VALUES(parent_type),
                parent_heading_path=VALUES(parent_heading_path),
                chunk_index=VALUES(chunk_index),
                child_index=VALUES(child_index),
                child_count=VALUES(child_count),
                text_preview=VALUES(text_preview),
                metadata_json=VALUES(metadata_json),
                created_at=VALUES(created_at)
            """,
            (
                row["chunk_id"],
                row["run_id"],
                row["parent_id"],
                row["file_key"],
                row["filename"],
                row["parent_type"],
                row["parent_heading_path"],
                row["chunk_index"],
                row["child_index"],
                row["child_count"],
                row["text_preview"],
                row["metadata_json"],
                row["created_at"],
            ),
        )

    def get_recent_runs(self, limit: int = 20) -> List[JsonDict]:
        self.connect()
        rows = self._fetchall(
            """
            SELECT *
            FROM metadata_processing_runs
            ORDER BY finished_at DESC
            LIMIT %s
            """,
            (_as_int(limit, 20),),
        )
        return [self._decode_run(row) for row in rows]

    def get_run(self, run_id: str) -> Optional[JsonDict]:
        self.connect()
        run = self._decode_run(
            self._fetchone("SELECT * FROM metadata_processing_runs WHERE run_id = %s", (run_id,))
        )
        if not run:
            return None
        rows = self._fetchall(
            """
            SELECT *
            FROM metadata_chunks
            WHERE run_id = %s
            ORDER BY chunk_index, child_index
            """,
            (run_id,),
        )
        run["chunks"] = [self._decode_chunk(row) for row in rows]
        return run


def create_metadata_store(config: Optional[JsonDict]) -> BaseMetadataStore:
    """Create and connect a metadata store from config."""
    config = dict(config or {})
    if not config.get("enabled", False):
        return DisabledMetadataStore(config)

    store_type = str(config.get("type") or "mysql").lower()
    fail_on_error = bool(config.get("fail_on_error", True))

    if store_type == "sqlite":
        sqlite_config = dict(config.get("sqlite") or {})
        store = SQLiteMetadataStore(
            path=sqlite_config.get("path", "data/metadata.sqlite3"),
            fail_on_error=fail_on_error,
        )
        return store.connect()

    if store_type == "mysql":
        mysql_config = dict(config.get("mysql") or {})
        password = mysql_config.get("password")
        password_env = mysql_config.get("password_env")
        if password is None and password_env:
            password = os.environ.get(str(password_env), "")

        store = MySQLMetadataStore(
            host=mysql_config.get("host", "127.0.0.1"),
            port=_as_int(mysql_config.get("port"), 3306),
            database=mysql_config.get("database", "data_clean_rag"),
            user=mysql_config.get("user", "root"),
            password=password or "",
            charset=mysql_config.get("charset", "utf8mb4"),
            connect_timeout=_as_int(mysql_config.get("connect_timeout"), 10),
            fail_on_error=fail_on_error,
        )
        return store.connect()

    raise ValueError(f"Unsupported metadata_db.type: {store_type}")
