import tempfile
import unittest
from pathlib import Path

from src.ingestion import (
    ProcessingManifest,
    SQLiteProcessingManifest,
    compute_content_hash,
    create_processing_manifest,
)
from src.io import load_documents_from_bytes
from src.pipeline import DataPipeline


class IncrementalIngestionTests(unittest.TestCase):
    def test_manifest_persists_processed_file_hash(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path = Path(temp_dir) / "manifest.json"
            content_hash = compute_content_hash(b"alpha")

            manifest = ProcessingManifest(str(manifest_path))
            manifest.mark_processed(
                file_key="alpha.txt",
                content_hash=content_hash,
                filename="alpha.txt",
                file_type=".txt",
                size_bytes=5,
                document_count=1,
                chunk_count=1,
                chunk_ids=["chunk-1"],
            )
            manifest.save()

            reloaded = ProcessingManifest(str(manifest_path))
            self.assertTrue(reloaded.is_unchanged("alpha.txt", content_hash))
            self.assertEqual(reloaded.get("alpha.txt")["chunk_ids"], ["chunk-1"])

    def test_sqlite_manifest_persists_processed_file_hash(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path = Path(temp_dir) / "manifest.sqlite3"
            content_hash = compute_content_hash(b"alpha")

            manifest = SQLiteProcessingManifest(str(manifest_path))
            manifest.mark_processed(
                file_key="alpha.txt",
                content_hash=content_hash,
                filename="alpha.txt",
                file_type=".txt",
                size_bytes=5,
                document_count=1,
                chunk_count=1,
                chunk_ids=["chunk-1"],
                stats={"input_documents": 1},
            )

            reloaded = SQLiteProcessingManifest(str(manifest_path))
            record = reloaded.get("alpha.txt")
            self.assertTrue(reloaded.is_unchanged("alpha.txt", content_hash))
            self.assertEqual(record["chunk_ids"], ["chunk-1"])
            self.assertEqual(record["stats"]["input_documents"], 1)
            self.assertEqual(reloaded.to_dict()["backend"], "sqlite")

    def test_manifest_factory_selects_backend_by_extension(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            json_manifest = create_processing_manifest(str(Path(temp_dir) / "manifest.json"))
            sqlite_manifest = create_processing_manifest(str(Path(temp_dir) / "manifest.sqlite3"))

            self.assertIsInstance(json_manifest, ProcessingManifest)
            self.assertIsInstance(sqlite_manifest, SQLiteProcessingManifest)

    def test_loader_adds_file_hash_metadata(self):
        content = b"alpha document with enough content"

        texts, metadatas = load_documents_from_bytes("alpha.txt", content)

        self.assertEqual(texts, ["alpha document with enough content"])
        self.assertEqual(metadatas[0]["file_hash"], compute_content_hash(content))
        self.assertEqual(metadatas[0]["content_hash"], compute_content_hash(content))
        self.assertEqual(metadatas[0]["file_size_bytes"], len(content))
        self.assertEqual(metadatas[0]["file_key"], "alpha.txt")

    def test_pipeline_reports_stable_chunk_ids_for_hashed_files(self):
        pipeline = DataPipeline("config.dev.yaml")
        pipeline.init_vector_db()
        metadata = {
            "filename": "alpha.txt",
            "file_key": "alpha.txt",
            "file_type": ".txt",
            "file_hash": "abc123",
            "content_hash": "abc123",
        }

        stats = pipeline.process_texts(
            ["alpha document with enough content for incremental ingestion"],
            source_metadata=[metadata],
        )

        file_report = stats["processing_report"]["files"][0]
        chunk_id = file_report["chunk_ids"][0]
        self.assertEqual(stats["stored_count"], 1)
        self.assertEqual(file_report["file_key"], "alpha.txt")
        self.assertEqual(file_report["file_hash"], "abc123")
        self.assertEqual(pipeline.vector_db.ids, [chunk_id])

        preview = pipeline.prepare_texts(
            ["alpha document with enough content for incremental ingestion"],
            source_metadata=[metadata],
            mutate_dedup=False,
        )
        self.assertEqual(preview["chunks"][0]["metadata"]["chunk_id"], chunk_id)


if __name__ == "__main__":
    unittest.main()
