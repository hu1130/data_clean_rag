import asyncio
import unittest
from unittest.mock import patch

from api.main import RagAskRequest, SearchResult, app, build_rag_messages, rag_ask


class FakeRagPipeline:
    config = {
        "llm": {
            "provider": "ollama",
            "model_name": "llama3.1",
            "max_context_chars": 1200,
        }
    }

    def __init__(self):
        self.last_query = None
        self.last_top_k = None
        self.last_filter = None

    def search(self, query, top_k=5, filter_dict=None):
        self.last_query = query
        self.last_top_k = top_k
        self.last_filter = filter_dict
        return [
            {
                "id": "chunk-1",
                "text": "child text",
                "score": 0.92,
                "metadata": {
                    "filename": "sample.pdf",
                    "page_number": 1,
                    "parent_context": "parent context for answer",
                },
            }
        ]


class RagApiTests(unittest.TestCase):
    def test_rag_ask_route_is_registered(self):
        paths = {getattr(route, "path", None) for route in app.routes}

        self.assertIn("/api/rag/ask", paths)

    def test_build_rag_messages_uses_context_and_citations(self):
        sources = [
            SearchResult(
                id="chunk-1",
                text="短文本",
                score=0.9,
                metadata={"filename": "sample.pdf", "page_number": 3},
                context_text="这是可引用的父级上下文。",
            )
        ]

        messages, prompt = build_rag_messages("这份文件讲了什么？", sources)

        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[1]["role"], "user")
        self.assertIn("[1] 来源: sample.pdf / page=3", prompt)
        self.assertIn("这是可引用的父级上下文。", prompt)
        self.assertIn("这份文件讲了什么？", prompt)
        self.assertIn("每个关键结论后标注引用编号", prompt)
        self.assertIn("回答先给结论，再给依据", prompt)

    def test_rag_ask_searches_and_calls_llm(self):
        fake_pipeline = FakeRagPipeline()
        with patch("api.main.pipeline", fake_pipeline), \
             patch("api.main.call_chat_model", return_value={
                 "answer": "answer with [1]",
                 "provider": "ollama",
                 "model": "llama3.1",
                 "usage": {"eval_count": 2},
             }) as call_llm:
            response = asyncio.run(rag_ask(RagAskRequest(
                question="answer?",
                top_k=2,
                filters={"file_type": ".pdf"},
                provider="ollama",
                model="llama3.1",
            )))

        self.assertEqual(fake_pipeline.last_query, "answer?")
        self.assertEqual(fake_pipeline.last_top_k, 2)
        self.assertEqual(fake_pipeline.last_filter, {"file_type": ".pdf"})
        self.assertEqual(response.answer, "answer with [1]")
        self.assertEqual(response.total_sources, 1)
        self.assertEqual(response.sources[0].metadata["filename"], "sample.pdf")
        call_llm.assert_called_once()


if __name__ == "__main__":
    unittest.main()
