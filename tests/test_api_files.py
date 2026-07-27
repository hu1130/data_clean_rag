import unittest
from unittest.mock import patch

from api.main import app, list_manifest_files


class FakeManifest:
    def to_dict(self):
        return {
            "backend": "sqlite",
            "files": {
                "old.txt": {
                    "file_key": "old.txt",
                    "filename": "old.txt",
                    "processed_at": 10,
                },
                "new.txt": {
                    "file_key": "new.txt",
                    "filename": "new.txt",
                    "processed_at": 20,
                },
            },
        }


class ApiFileTests(unittest.TestCase):
    def test_file_routes_are_registered(self):
        paths = {getattr(route, "path", None) for route in app.routes}

        self.assertIn("/api/files", paths)
        self.assertIn("/api/files/{file_key:path}", paths)

    def test_manifest_file_list_is_sorted_newest_first(self):
        with patch("api.main.get_processing_manifest", return_value=FakeManifest()), \
             patch("api.main.get_manifest_path", return_value="data/manifest.sqlite3"):
            data = list_manifest_files()

        self.assertEqual(data["backend"], "sqlite")
        self.assertEqual(data["path"], "data/manifest.sqlite3")
        self.assertEqual(data["total"], 2)
        self.assertEqual([item["file_key"] for item in data["files"]], ["new.txt", "old.txt"])


if __name__ == "__main__":
    unittest.main()
