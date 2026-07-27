import subprocess
import sys
import unittest
from pathlib import Path

import yaml


class MySQLArtifactsTests(unittest.TestCase):
    def test_mysql_schema_contains_route_a_tables(self):
        schema = Path("deploy/mysql/metadata_schema.sql")
        self.assertTrue(schema.exists())

        content = schema.read_text(encoding="utf-8")
        self.assertIn("CREATE DATABASE IF NOT EXISTS data_clean_rag", content)
        self.assertIn("CREATE TABLE IF NOT EXISTS metadata_processing_runs", content)
        self.assertIn("CREATE TABLE IF NOT EXISTS metadata_files", content)
        self.assertIn("CREATE TABLE IF NOT EXISTS metadata_chunks", content)
        self.assertIn("idx_metadata_chunks_run_id", content)

    def test_mysql_example_config_enables_mysql_metadata_only(self):
        config = yaml.safe_load(Path("config.mysql.example.yaml").read_text(encoding="utf-8"))

        self.assertTrue(config["metadata_db"]["enabled"])
        self.assertEqual(config["metadata_db"]["type"], "mysql")
        self.assertEqual(config["metadata_db"]["mysql"]["password_env"], "MYSQL_PASSWORD")
        self.assertEqual(config["vector_db"]["type"], "memory")
        self.assertEqual(config["embedding"]["provider"], "hash")

    def test_mysql_metadata_check_help_runs_without_mysql(self):
        proc = subprocess.run(
            [sys.executable, "scripts/mysql_metadata_check.py", "--help"],
            cwd=Path.cwd(),
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=30,
        )

        self.assertEqual(proc.returncode, 0)
        self.assertIn("Verify MySQL metadata_db connectivity", proc.stdout)


if __name__ == "__main__":
    unittest.main()
