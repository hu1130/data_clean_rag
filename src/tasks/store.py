"""Persistent task status storage."""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional


TERMINAL_TASK_STATUSES = {"succeeded", "failed", "interrupted", "cancelled"}


class SQLiteTaskStore:
    """SQLite-backed task status store for API background jobs."""

    def __init__(self, path: str = "data/tasks.sqlite3", timeout: float = 30.0):
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
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    action TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    stats TEXT,
                    error TEXT,
                    progress TEXT NOT NULL DEFAULT '{}',
                    message TEXT NOT NULL DEFAULT '',
                    payload TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 1,
                    available_at REAL NOT NULL DEFAULT 0,
                    locked_by TEXT,
                    locked_at REAL
                )
                """
            )
            self._ensure_column(connection, "payload", "TEXT")
            self._ensure_column(connection, "attempts", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(connection, "max_attempts", "INTEGER NOT NULL DEFAULT 1")
            self._ensure_column(connection, "available_at", "REAL NOT NULL DEFAULT 0")
            self._ensure_column(connection, "locked_by", "TEXT")
            self._ensure_column(connection, "locked_at", "REAL")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at DESC)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_tasks_available ON tasks(status, available_at, created_at)"
            )

    def _ensure_column(self, connection, column_name: str, definition: str):
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(tasks)").fetchall()
        }
        if column_name not in columns:
            connection.execute(f"ALTER TABLE tasks ADD COLUMN {column_name} {definition}")

    def save_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        normalized = self._normalize_task(task)
        with self._session() as connection:
            connection.execute(
                """
                INSERT INTO tasks (
                    task_id, action, status, created_at, updated_at,
                    stats, error, progress, message, payload, attempts,
                    max_attempts, available_at, locked_by, locked_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    action = excluded.action,
                    status = excluded.status,
                    created_at = excluded.created_at,
                    updated_at = excluded.updated_at,
                    stats = excluded.stats,
                    error = excluded.error,
                    progress = excluded.progress,
                    message = excluded.message,
                    payload = excluded.payload,
                    attempts = excluded.attempts,
                    max_attempts = excluded.max_attempts,
                    available_at = excluded.available_at,
                    locked_by = excluded.locked_by,
                    locked_at = excluded.locked_at
                """,
                self._task_to_row(normalized),
            )
        return normalized

    def update_task(self, task_id: str, **updates: Any) -> Optional[Dict[str, Any]]:
        task = self.get_task(task_id)
        if task is None:
            return None
        task.update(updates)
        task["updated_at"] = updates.get("updated_at", time.time())
        return self.save_task(task)

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._session() as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_task(row)

    def list_tasks(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._session() as connection:
            rows = connection.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_task(row) for row in rows]

    def claim_next(self, worker_id: str, lease_timeout_seconds: int = 3600) -> Optional[Dict[str, Any]]:
        now = time.time()
        stale_before = now - lease_timeout_seconds
        with self._session() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM tasks
                WHERE (
                    status = 'pending'
                    AND available_at <= ?
                ) OR (
                    status = 'running'
                    AND locked_at IS NOT NULL
                    AND locked_at <= ?
                    AND attempts < max_attempts
                )
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (now, stale_before),
            ).fetchone()
            if row is None:
                connection.commit()
                return None

            attempts = int(row["attempts"] or 0) + 1
            connection.execute(
                """
                UPDATE tasks
                SET status = 'running',
                    updated_at = ?,
                    attempts = ?,
                    locked_by = ?,
                    locked_at = ?,
                    progress = ?
                WHERE task_id = ?
                """,
                (
                    now,
                    attempts,
                    worker_id,
                    now,
                    json.dumps(
                        {
                            "stage": "running",
                            "percent": 1,
                            "message": "Task started",
                        },
                        ensure_ascii=False,
                    ),
                    row["task_id"],
                ),
            )
            updated = connection.execute(
                "SELECT * FROM tasks WHERE task_id = ?",
                (row["task_id"],),
            ).fetchone()
            connection.commit()

        return self._row_to_task(updated)

    def requeue_incomplete(
        self,
        message: str = "Task requeued after service restart",
        interrupt_without_payload: bool = True,
    ) -> int:
        now = time.time()
        progress = json.dumps(
            {
                "stage": "pending",
                "percent": 0,
                "message": message,
            },
            ensure_ascii=False,
        )
        with self._session() as connection:
            cursor = connection.execute(
                """
                UPDATE tasks
                SET status = 'pending',
                    updated_at = ?,
                    error = NULL,
                    progress = ?,
                    message = ?,
                    locked_by = NULL,
                    locked_at = NULL,
                    available_at = ?
                WHERE status IN ('pending', 'running')
                    AND payload IS NOT NULL
                    AND attempts < max_attempts
                """,
                (now, progress, message, now),
            )
            changed = cursor.rowcount
            if interrupt_without_payload:
                interrupted_message = "Task interrupted by service restart and cannot be resumed"
                interrupted_progress = json.dumps(
                    {
                        "stage": "interrupted",
                        "percent": 0,
                        "message": interrupted_message,
                    },
                    ensure_ascii=False,
                )
                interrupted = connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'interrupted',
                        updated_at = ?,
                        error = ?,
                        progress = ?,
                        message = ?,
                        locked_by = NULL,
                        locked_at = NULL
                    WHERE status IN ('pending', 'running')
                        AND (payload IS NULL OR attempts >= max_attempts)
                    """,
                    (now, interrupted_message, interrupted_progress, interrupted_message),
                )
                changed += interrupted.rowcount
            return changed

    def mark_incomplete_interrupted(self, message: str = "Task interrupted by service restart") -> int:
        now = time.time()
        with self._session() as connection:
            cursor = connection.execute(
                """
                UPDATE tasks
                SET status = 'interrupted',
                    updated_at = ?,
                    error = ?,
                    progress = ?,
                    message = ?,
                    locked_by = NULL,
                    locked_at = NULL
                WHERE status IN ('pending', 'running')
                    AND (payload IS NULL OR attempts >= max_attempts)
                """,
                (
                    now,
                    message,
                    json.dumps(
                        {
                            "stage": "interrupted",
                            "percent": 0,
                            "message": message,
                        },
                        ensure_ascii=False,
                    ),
                    message,
                ),
            )
            return cursor.rowcount

    def prune(self, max_history: int = 100):
        if max_history <= 0:
            return
        with self._session() as connection:
            connection.execute(
                """
                DELETE FROM tasks
                WHERE task_id IN (
                    SELECT task_id FROM tasks
                    WHERE status IN ('succeeded', 'failed', 'interrupted', 'cancelled')
                    ORDER BY created_at DESC
                    LIMIT -1 OFFSET ?
                )
                """,
                (max_history,),
            )

    def _normalize_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        now = time.time()
        return {
            "task_id": task["task_id"],
            "action": task.get("action", "unknown"),
            "status": task.get("status", "pending"),
            "created_at": float(task.get("created_at", now)),
            "updated_at": float(task.get("updated_at", now)),
            "stats": task.get("stats"),
            "error": task.get("error"),
            "progress": task.get("progress") or {},
            "message": task.get("message", ""),
            "payload": task.get("payload"),
            "attempts": int(task.get("attempts", 0)),
            "max_attempts": int(task.get("max_attempts", 1)),
            "available_at": float(task.get("available_at", 0)),
            "locked_by": task.get("locked_by"),
            "locked_at": task.get("locked_at"),
        }

    def _task_to_row(self, task: Dict[str, Any]):
        return (
            task["task_id"],
            task["action"],
            task["status"],
            task["created_at"],
            task["updated_at"],
            json.dumps(task["stats"], ensure_ascii=False) if task.get("stats") is not None else None,
            task.get("error"),
            json.dumps(task.get("progress") or {}, ensure_ascii=False),
            task.get("message", ""),
            json.dumps(task.get("payload"), ensure_ascii=False) if task.get("payload") is not None else None,
            task.get("attempts", 0),
            task.get("max_attempts", 1),
            task.get("available_at", 0),
            task.get("locked_by"),
            task.get("locked_at"),
        )

    def _row_to_task(self, row: sqlite3.Row) -> Dict[str, Any]:
        stats = row["stats"]
        progress = row["progress"]
        payload = row["payload"]
        return {
            "task_id": row["task_id"],
            "action": row["action"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "stats": json.loads(stats) if stats else None,
            "error": row["error"],
            "progress": json.loads(progress) if progress else {},
            "message": row["message"] or "",
            "payload": json.loads(payload) if payload else None,
            "attempts": row["attempts"],
            "max_attempts": row["max_attempts"],
            "available_at": row["available_at"],
            "locked_by": row["locked_by"],
            "locked_at": row["locked_at"],
        }
