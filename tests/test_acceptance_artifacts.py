import unittest
from pathlib import Path


class AcceptanceArtifactsTests(unittest.TestCase):
    def test_acceptance_script_and_template_exist(self):
        script = Path("scripts/acceptance_check.py")
        template = Path("docs/验收报告模板.md")

        self.assertTrue(script.exists())
        self.assertTrue(template.exists())

    def test_acceptance_docs_are_referenced(self):
        readme = Path("README.md").read_text(encoding="utf-8")

        self.assertIn("python scripts/acceptance_check.py", readme)
        self.assertIn("docs/验收报告模板.md", readme)
        self.assertIn("默认配置不会切换到 SQLite", readme)


if __name__ == "__main__":
    unittest.main()
