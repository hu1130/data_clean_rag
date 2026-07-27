import tempfile
import time
import unittest
from pathlib import Path

from src.tasks import SQLiteTaskStore


class SQLiteTaskStoreTests(unittest.TestCase):
    def test_task_store_persists_task_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store_path = Path(temp_dir) / "tasks.sqlite3"
            store = SQLiteTaskStore(str(store_path))
            now = time.time()
            store.save_task({
                "task_id": "task-1",
                "action": "process_file",
                "status": "running",
                "created_at": now,
                "updated_at": now,
                "stats": None,
                "error": None,
                "progress": {"stage": "embedding", "percent": 80},
                "message": "embedding",
                "payload": {"texts": ["alpha"]},
                "attempts": 1,
                "max_attempts": 2,
            })

            reloaded = SQLiteTaskStore(str(store_path))
            task = reloaded.get_task("task-1")

            self.assertEqual(task["status"], "running")
            self.assertEqual(task["progress"]["stage"], "embedding")
            self.assertEqual(task["message"], "embedding")
            self.assertEqual(task["payload"]["texts"], ["alpha"])
            self.assertEqual(task["attempts"], 1)

    def test_task_store_marks_incomplete_tasks_interrupted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteTaskStore(str(Path(temp_dir) / "tasks.sqlite3"))
            now = time.time()
            store.save_task({
                "task_id": "task-running",
                "action": "process_file",
                "status": "running",
                "created_at": now,
                "updated_at": now,
                "progress": {"stage": "running", "percent": 5},
            })
            store.save_task({
                "task_id": "task-done",
                "action": "process_file",
                "status": "succeeded",
                "created_at": now + 1,
                "updated_at": now + 1,
                "stats": {"stored_count": 1},
            })

            changed = store.mark_incomplete_interrupted()

            self.assertEqual(changed, 1)
            self.assertEqual(store.get_task("task-running")["status"], "interrupted")
            self.assertEqual(store.get_task("task-done")["status"], "succeeded")

    def test_task_store_requeues_payload_tasks_after_restart(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteTaskStore(str(Path(temp_dir) / "tasks.sqlite3"))
            now = time.time()
            store.save_task({
                "task_id": "task-resume",
                "action": "process_texts",
                "status": "running",
                "created_at": now,
                "updated_at": now,
                "payload": {"texts": ["alpha"]},
                "attempts": 0,
                "max_attempts": 2,
            })

            changed = store.requeue_incomplete()
            task = store.get_task("task-resume")

            self.assertEqual(changed, 1)
            self.assertEqual(task["status"], "pending")
            self.assertIsNone(task["locked_by"])
            self.assertEqual(task["payload"]["texts"], ["alpha"])

    def test_task_store_claims_next_pending_task(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteTaskStore(str(Path(temp_dir) / "tasks.sqlite3"))
            now = time.time()
            store.save_task({
                "task_id": "task-claim",
                "action": "process_texts",
                "status": "pending",
                "created_at": now,
                "updated_at": now,
                "payload": {"texts": ["alpha"]},
                "attempts": 0,
                "max_attempts": 2,
                "available_at": now,
            })

            claimed = store.claim_next("worker-1")

            self.assertEqual(claimed["task_id"], "task-claim")
            self.assertEqual(claimed["status"], "running")
            self.assertEqual(claimed["attempts"], 1)
            self.assertEqual(claimed["locked_by"], "worker-1")

    def test_task_store_prunes_terminal_history(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteTaskStore(str(Path(temp_dir) / "tasks.sqlite3"))
            now = time.time()
            for index in range(5):
                store.save_task({
                    "task_id": f"task-{index}",
                    "action": "process_texts",
                    "status": "succeeded",
                    "created_at": now + index,
                    "updated_at": now + index,
                })

            store.prune(max_history=2)
            tasks = store.list_tasks(limit=10)

            self.assertEqual([task["task_id"] for task in tasks], ["task-4", "task-3"])


if __name__ == "__main__":
    unittest.main()
