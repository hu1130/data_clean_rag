import json
import os
import unittest
from unittest.mock import patch

from src.llm import LLMConfigError, call_chat_model


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class LLMClientTests(unittest.TestCase):
    def test_openai_requires_api_key(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(LLMConfigError):
                call_chat_model(
                    {"provider": "openai", "model_name": "gpt-test", "api_key_env": "MISSING_OPENAI_KEY"},
                    [{"role": "user", "content": "hello"}],
                )

    def test_ollama_response_is_normalized(self):
        with patch("urllib.request.urlopen", return_value=FakeResponse({"message": {"content": "answer"}, "eval_count": 3})):
            result = call_chat_model(
                {"provider": "ollama", "model_name": "llama3.1"},
                [{"role": "user", "content": "hello"}],
            )

        self.assertEqual(result["answer"], "answer")
        self.assertEqual(result["provider"], "ollama")
        self.assertEqual(result["model"], "llama3.1")
        self.assertEqual(result["usage"]["eval_count"], 3)

    def test_openai_compatible_can_skip_api_key(self):
        captured = {}

        def fake_urlopen(request, timeout):
            captured["headers"] = dict(request.header_items())
            captured["timeout"] = timeout
            return FakeResponse({"choices": [{"message": {"content": "local answer"}}]})

        with patch.dict(os.environ, {}, clear=True):
            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                result = call_chat_model(
                    {
                        "provider": "openai_compatible",
                        "model_name": "local-model",
                        "base_url": "http://127.0.0.1:8000/v1",
                        "api_key_required": False,
                    },
                    [{"role": "user", "content": "hello"}],
                )

        self.assertEqual(result["answer"], "local answer")
        self.assertNotIn("Authorization", captured["headers"])
        self.assertEqual(captured["timeout"], 60)


if __name__ == "__main__":
    unittest.main()
