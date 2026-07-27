import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from api.main import format_search_result, require_api_key


class ApiSecurityTests(unittest.TestCase):
    def test_api_key_not_required_when_env_is_absent(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(require_api_key())

    def test_api_key_accepts_header_token(self):
        with patch.dict(os.environ, {"API_KEY": "secret"}, clear=True):
            self.assertTrue(require_api_key(x_api_key="secret"))

    def test_api_key_accepts_bearer_token(self):
        with patch.dict(os.environ, {"API_KEY": "secret"}, clear=True):
            self.assertTrue(require_api_key(authorization="Bearer secret"))

    def test_api_key_rejects_missing_or_wrong_token(self):
        with patch.dict(os.environ, {"API_KEY": "secret"}, clear=True):
            with self.assertRaises(HTTPException):
                require_api_key()
            with self.assertRaises(HTTPException):
                require_api_key(x_api_key="wrong")

    def test_search_result_exposes_parent_child_context(self):
        result = format_search_result({
            "id": "chunk-1",
            "text": "matched child text",
            "score": 0.75,
            "metadata": {
                "chunk_id": "chunk-1",
                "parent_id": "parent-1",
                "parent_type": "section",
                "parent_context": "full parent context",
                "parent_heading_path": "Guide > Section",
                "parent_section_title": "Section",
            },
        })

        self.assertEqual(result.child_id, "chunk-1")
        self.assertEqual(result.parent_id, "parent-1")
        self.assertEqual(result.parent_context, "full parent context")
        self.assertEqual(result.context_text, "full parent context")
        self.assertEqual(result.parent_heading_path, "Guide > Section")


if __name__ == "__main__":
    unittest.main()
