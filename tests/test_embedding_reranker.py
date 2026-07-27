import unittest

from src.embedding.models import EmbeddingModel
from src.embedding.reranker import KeywordReranker, RerankerFactory
from src.pipeline import DataPipeline


class EmbeddingConfigTests(unittest.TestCase):
    def test_hash_embedding_respects_configured_dimension(self):
        model = EmbeddingModel(provider="hash", model_name="hash", dimension=64)

        embeddings = model.encode(["alpha document"])

        self.assertEqual(model.dimension, 64)
        self.assertEqual(embeddings.shape, (1, 64))
        self.assertEqual(model.info()["provider"], "hash")

    def test_openai_embedding_dimension_can_be_configured_without_client_call(self):
        model = EmbeddingModel(
            provider="openai",
            model_name="text-embedding-3-small",
            api_key="test-key",
            dimension=256,
        )

        self.assertEqual(model.dimension, 256)
        self.assertEqual(model.info()["provider"], "openai")


class RerankerTests(unittest.TestCase):
    def test_keyword_reranker_promotes_lexical_match(self):
        reranker = KeywordReranker()
        results = [
            {"id": "1", "text": "unrelated document", "score": 0.99, "metadata": {}},
            {"id": "2", "text": "target phrase appears here", "score": 0.1, "metadata": {}},
        ]

        reranked = reranker.rerank("target phrase", results, top_k=1)

        self.assertEqual(reranked[0]["id"], "2")
        self.assertIn("rerank_score", reranked[0])
        self.assertIn("vector_score", reranked[0])

    def test_pipeline_search_uses_reranker_when_enabled(self):
        pipeline = DataPipeline("config.dev.yaml")
        pipeline.reranker_config = {"enabled": True, "type": "keyword", "candidate_top_k": 2}
        pipeline.reranker = RerankerFactory.create(pipeline.reranker_config)
        pipeline.init_vector_db()
        pipeline.process_texts(
            ["unrelated document", "target phrase appears here"],
            source_metadata=[{"filename": "a.txt"}, {"filename": "b.txt"}],
        )

        results = pipeline.search("target phrase", top_k=1)

        self.assertEqual(results[0]["metadata"]["filename"], "b.txt")
        self.assertIn("rerank_score", results[0])


class ProcessingReportTests(unittest.TestCase):
    def test_process_texts_returns_file_processing_report(self):
        pipeline = DataPipeline("config.dev.yaml")
        pipeline.init_vector_db()

        stats = pipeline.process_texts(
            ["valid document with enough content"],
            source_metadata=[{"filename": "report.md", "file_type": ".md", "document_part": "document"}],
        )

        report = stats["processing_report"]
        self.assertEqual(report["summary"]["stored_count"], 1)
        self.assertEqual(report["embedding"]["provider"], "hash")
        self.assertEqual(report["files"][0]["filename"], "report.md")
        self.assertEqual(report["files"][0]["chunks"], 1)

    def test_process_texts_emits_progress_events(self):
        pipeline = DataPipeline("config.dev.yaml")
        pipeline.init_vector_db()
        events = []

        stats = pipeline.process_texts(
            ["valid document with enough content for progress tracking"],
            source_metadata=[{"filename": "progress.md", "file_type": ".md"}],
            progress_callback=events.append,
        )

        stages = [event["stage"] for event in events]
        self.assertEqual(stats["stored_count"], 1)
        self.assertIn("starting", stages)
        self.assertIn("cleaning", stages)
        self.assertIn("quality_filter", stages)
        self.assertIn("deduplication", stages)
        self.assertIn("chunking", stages)
        self.assertIn("embedding", stages)
        self.assertIn("storing", stages)
        self.assertEqual(events[-1]["stage"], "completed")
        self.assertEqual(events[-1]["percent"], 100)


if __name__ == "__main__":
    unittest.main()
