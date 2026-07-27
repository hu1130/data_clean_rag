import unittest
import tempfile
from pathlib import Path

from src.io import LoaderOptions, get_loader_diagnostics, load_documents_from_bytes
import src.io.loaders as loaders
from src.pipeline import DataPipeline
from src.vector_db.adapters import SQLiteVectorDBAdapter


class LoaderTests(unittest.TestCase):
    def test_loader_diagnostics_reports_supported_formats_and_ocr_shape(self):
        diagnostics = get_loader_diagnostics()

        self.assertIn(".pdf", diagnostics["supported_extensions"])
        self.assertIn(".docx", diagnostics["supported_extensions"])
        self.assertIn(".xlsx", diagnostics["supported_extensions"])
        self.assertIn(".png", diagnostics["supported_extensions"])
        self.assertIn("pypdf", diagnostics["dependencies"])
        self.assertIn("pytesseract", diagnostics["dependencies"])
        self.assertIn("ready", diagnostics["ocr"])
        self.assertIn("common_languages", diagnostics["ocr"])

    def test_jsonl_loader_extracts_text_and_metadata(self):
        content = (
            b'{"id":"a1","text":"first record"}\n'
            b'{"id":"a2","content":"second record"}\n'
        )

        texts, metadatas = load_documents_from_bytes("sample.jsonl", content)

        self.assertEqual(texts, ["first record", "second record"])
        self.assertEqual(metadatas[0]["id"], "a1")
        self.assertEqual(metadatas[1]["line_number"], 2)

    def test_csv_loader_uses_known_text_fields(self):
        content = b"id,title,content\n1,Hello,CSV body\n2,World,Another body\n"

        texts, metadatas = load_documents_from_bytes("sample.csv", content)

        self.assertEqual(texts[0], "CSV body\nHello")
        self.assertEqual(metadatas[0]["row_number"], 1)

    def test_loader_supports_nested_text_fields(self):
        content = b'{"data":{"body":"nested body"},"title":"ignored"}'

        texts, metadatas = load_documents_from_bytes(
            "sample.json",
            content,
            options=LoaderOptions(text_fields=["data.body"])
        )

        self.assertEqual(texts, ["nested body"])
        self.assertEqual(metadatas[0]["text_fields"], "data.body")

    def test_loader_limits_jsonl_records(self):
        content = b'{"text":"one"}\n{"text":"two"}\n{"text":"three"}\n'

        texts, _ = load_documents_from_bytes(
            "sample.jsonl",
            content,
            options=LoaderOptions(max_records=2)
        )

        self.assertEqual(texts, ["one", "two"])

    def test_loader_rejects_oversized_files(self):
        with self.assertRaises(ValueError):
            load_documents_from_bytes(
                "sample.txt",
                b"0123456789",
                options=LoaderOptions(max_file_size_mb=0)
            )

    def test_html_loader_removes_tags_and_scripts(self):
        content = b"<html><script>bad()</script><body><h1>Hello</h1><p>World</p></body></html>"

        texts, _ = load_documents_from_bytes("sample.html", content)

        self.assertIn("Hello", texts[0])
        self.assertIn("World", texts[0])
        self.assertNotIn("bad", texts[0])

    def test_pdf_loader_reports_missing_dependency(self):
        original_import = loaders.__builtins__["__import__"]

        def fake_import(name, *args, **kwargs):
            if name == "pypdf":
                raise ImportError("missing")
            return original_import(name, *args, **kwargs)

        loaders.__builtins__["__import__"] = fake_import
        try:
            with self.assertRaises(ImportError):
                load_documents_from_bytes("sample.pdf", b"%PDF-1.4")
        finally:
            loaders.__builtins__["__import__"] = original_import


class PipelineFeatureTests(unittest.TestCase):
    def test_preview_does_not_mutate_dedup_state(self):
        pipeline = DataPipeline("config.dev.yaml")
        texts = ["same text", "same text"]

        preview = pipeline.prepare_texts(texts, mutate_dedup=False)
        stats = pipeline.process_texts(texts)

        self.assertEqual(preview["stats"]["deduped_count"], 1)
        self.assertEqual(stats["deduped_count"], 1)

    def test_memory_search_supports_metadata_filter(self):
        pipeline = DataPipeline("config.dev.yaml")
        pipeline.init_vector_db()
        pipeline.process_texts(
            ["alpha semantic search document", "beta unrelated document"],
            source_metadata=[{"filename": "alpha.md"}, {"filename": "beta.md"}],
        )

        results = pipeline.search(
            "semantic search",
            top_k=5,
            filter_dict={"filename": "alpha.md"},
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["metadata"]["filename"], "alpha.md")

    def test_sqlite_vector_db_persists_vectors(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "vectors.sqlite3"
            db = SQLiteVectorDBAdapter(path=str(db_path), collection_name="docs")
            db.connect()
            db.create_collection("docs", dimension=3)
            db.add_vectors(
                vectors=[[1.0, 0.0, 0.0]],
                texts=["persistent alpha document"],
                metadatas=[{"filename": "alpha.md"}],
                ids=["vec-1"],
            )
            db.close()

            reloaded = SQLiteVectorDBAdapter(path=str(db_path), collection_name="docs")
            reloaded.connect()
            reloaded.create_collection("docs", dimension=3)
            results = reloaded.search([1.0, 0.0, 0.0], top_k=1, filter_dict={"filename": "alpha.md"})

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["id"], "vec-1")
            self.assertEqual(results[0]["metadata"]["filename"], "alpha.md")
            reloaded.close()

    def test_prepare_texts_adds_parent_child_chunk_metadata(self):
        pipeline = DataPipeline("config.dev.yaml")
        text = "Parent section intro. " + ("alpha beta gamma sentence. " * 40)
        metadata = {
            "filename": "parent.md",
            "file_key": "parent.md",
            "file_hash": "parent-hash",
            "content_hash": "parent-hash",
            "file_type": ".md",
            "document_part": "section",
            "section_title": "Parent Section",
            "heading_path": "Guide > Parent Section",
        }

        prepared = pipeline.prepare_texts(
            [text],
            source_metadata=[metadata],
            mutate_dedup=False,
        )
        chunks = prepared["chunks"]

        self.assertGreater(len(chunks), 1)
        parent_ids = {chunk["metadata"]["parent_id"] for chunk in chunks}
        self.assertEqual(len(parent_ids), 1)
        for index, chunk in enumerate(chunks):
            chunk_metadata = chunk["metadata"]
            self.assertEqual(chunk_metadata["child_id"], chunk_metadata["chunk_id"])
            self.assertEqual(chunk_metadata["child_index"], index)
            self.assertEqual(chunk_metadata["child_count"], len(chunks))
            self.assertEqual(chunk_metadata["parent_type"], "section")
            self.assertEqual(chunk_metadata["parent_heading_path"], "Guide > Parent Section")
            self.assertEqual(chunk_metadata["parent_section_title"], "Parent Section")
            self.assertEqual(chunk_metadata["parent_file_key"], "parent.md")
            self.assertEqual(chunk_metadata["retrieval_level"], "child")
            self.assertTrue(chunk_metadata["retrieval_parent_child"])
            self.assertTrue(chunk_metadata["parent_context"].startswith("Parent section intro."))

        parent_child_report = prepared["stats"]["processing_report"]["parent_child"]
        self.assertTrue(parent_child_report["enabled"])
        self.assertEqual(parent_child_report["parent_count"], 1)
        self.assertEqual(parent_child_report["child_count"], len(chunks))

    def test_clear_vector_db_resets_dedup_state(self):
        pipeline = DataPipeline("config.dev.yaml")
        pipeline.init_vector_db()

        first = pipeline.process_texts(["same text"])
        duplicate = pipeline.process_texts(["same text"])
        pipeline.clear_vector_db(reset_dedup=True)
        after_clear = pipeline.process_texts(["same text"])

        self.assertEqual(first["deduped_count"], 1)
        self.assertEqual(duplicate["deduped_count"], 0)
        self.assertEqual(after_clear["deduped_count"], 1)


if __name__ == "__main__":
    unittest.main()
