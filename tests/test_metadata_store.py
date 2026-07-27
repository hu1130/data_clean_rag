import tempfile
import unittest
from pathlib import Path

import yaml

from src.metadata_store import DisabledMetadataStore, SQLiteMetadataStore, create_metadata_store
from src.pipeline import DataPipeline


class MetadataStoreTests(unittest.TestCase):
    def test_disabled_factory_returns_noop_store(self):
        store = create_metadata_store({"enabled": False})

        self.assertIsInstance(store, DisabledMetadataStore)
        self.assertFalse(store.enabled)
        self.assertEqual(store.get_recent_runs(), [])

    def test_sqlite_metadata_store_records_run_files_and_chunks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "metadata.sqlite3"
            store = SQLiteMetadataStore(str(db_path)).connect()

            stats = {
                "input_count": 1,
                "cleaned_count": 1,
                "filtered_count": 1,
                "deduped_count": 1,
                "chunked_count": 1,
                "stored_count": 1,
                "quality_summary": {"scored_count": 1, "rejected_count": 0},
                "processing_report": {
                    "summary": {
                        "input_count": 1,
                        "cleaned_count": 1,
                        "filtered_count": 1,
                        "deduped_count": 1,
                        "chunked_count": 1,
                        "stored_count": 1,
                    },
                    "files": [
                        {
                            "file_key": "alpha.md",
                            "filename": "alpha.md",
                            "file_type": ".md",
                            "file_hash": "hash-alpha",
                            "content_hash": "hash-alpha",
                            "input_documents": 1,
                            "chunks": 1,
                        }
                    ],
                },
            }
            chunks = [
                {
                    "text": "alpha metadata storage chunk",
                    "metadata": {
                        "chunk_id": "chunk-1",
                        "parent_id": "parent-1",
                        "file_key": "alpha.md",
                        "filename": "alpha.md",
                        "parent_type": "section",
                        "parent_heading_path": "Guide > Alpha",
                        "chunk_index": 0,
                        "child_index": 0,
                        "child_count": 1,
                    },
                }
            ]

            run_id = store.record_processing_run(stats, chunks, run_id="run-1")
            recent = store.get_recent_runs()
            detail = store.get_run(run_id)
            store.close()

            self.assertEqual(run_id, "run-1")
            self.assertEqual(recent[0]["run_id"], "run-1")
            self.assertEqual(recent[0]["stored_count"], 1)
            self.assertEqual(detail["chunks"][0]["chunk_id"], "chunk-1")
            self.assertEqual(detail["chunks"][0]["metadata"]["filename"], "alpha.md")

    def test_pipeline_records_metadata_run_when_enabled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = yaml.safe_load(Path("config.dev.yaml").read_text(encoding="utf-8"))
            config["metadata_db"] = {
                "enabled": True,
                "type": "sqlite",
                "fail_on_error": True,
                "sqlite": {"path": str(Path(temp_dir) / "metadata.sqlite3")},
            }
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")

            pipeline = DataPipeline(str(config_path))
            pipeline.init_vector_db("memory")
            try:
                stats = pipeline.process_texts(
                    ["alpha beta metadata storage document"],
                    source_metadata=[
                        {
                            "file_key": "alpha.md",
                            "filename": "alpha.md",
                            "file_type": ".md",
                            "file_hash": "hash-alpha",
                            "content_hash": "hash-alpha",
                        }
                    ],
                )
                run = pipeline.metadata_store.get_run(stats["metadata_run_id"])
            finally:
                pipeline.close()

            self.assertEqual(stats["stored_count"], 1)
            self.assertIn("metadata_store", stats["processing_report"])
            self.assertEqual(run["run_id"], stats["metadata_run_id"])
            self.assertEqual(len(run["chunks"]), 1)
            self.assertEqual(run["chunks"][0]["metadata"]["filename"], "alpha.md")


if __name__ == "__main__":
    unittest.main()
