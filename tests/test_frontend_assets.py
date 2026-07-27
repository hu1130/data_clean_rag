import unittest
from pathlib import Path

from api.main import app


class FrontendAssetTests(unittest.TestCase):
    def test_frontend_assets_exist(self):
        frontend_dir = Path("frontend")

        self.assertTrue((frontend_dir / "index.html").exists())
        self.assertTrue((frontend_dir / "style.css").exists())
        self.assertTrue((frontend_dir / "app.js").exists())

    def test_frontend_index_has_core_views(self):
        html = Path("frontend/index.html").read_text(encoding="utf-8")

        for view_id in ("upload", "files", "tasks", "preview", "search", "reports", "system", "config"):
            self.assertIn(f'id="{view_id}"', html)
        self.assertIn('id="apiBase"', html)
        self.assertIn('id="fileInput"', html)
        self.assertIn('id="fileRows"', html)
        self.assertIn('id="reportOutput"', html)
        self.assertIn('id="metadataRunDetailOutput"', html)
        self.assertIn('id="configPatch"', html)

    def test_frontend_search_displays_parent_child_fields(self):
        app_js = Path("frontend/app.js").read_text(encoding="utf-8")

        self.assertIn("parent_context", app_js)
        self.assertIn("child_text", app_js)
        self.assertIn("renderProcessingReport", app_js)

    def test_frontend_has_advanced_operations(self):
        app_js = Path("frontend/app.js").read_text(encoding="utf-8")
        css = Path("frontend/style.css").read_text(encoding="utf-8")

        for function_name in (
            "refreshFiles",
            "showFileDetail",
            "refreshMetadataRuns",
            "showMetadataRunDetail",
            "applyConfigPatch",
            "renderReasonBars",
        ):
            self.assertIn(f"function {function_name}", app_js)

        self.assertIn(".reason-bars", css)
        self.assertIn(".detail-output", css)
        self.assertIn(".code-area", css)

    def test_api_mounts_frontend_app(self):
        mounted_paths = {getattr(route, "path", None) for route in app.routes}

        self.assertIn("/app", mounted_paths)

    def test_vue_frontend_project_exists(self):
        vue_dir = Path("frontend-vue")
        package_json = (vue_dir / "package.json").read_text(encoding="utf-8")

        self.assertTrue((vue_dir / "src" / "App.vue").exists())
        self.assertTrue((vue_dir / "src" / "services" / "api.ts").exists())
        self.assertIn("vue", package_json)
        self.assertIn("element-plus", package_json)
        self.assertIn("echarts", package_json)

    def test_vue_frontend_has_core_pages(self):
        pages_dir = Path("frontend-vue/src/pages")
        expected_pages = [
            "DashboardPage.vue",
            "IngestionPage.vue",
            "FilesPage.vue",
            "PreviewPage.vue",
            "ChunkAuditPage.vue",
            "SearchPage.vue",
            "RagTestPage.vue",
            "TasksPage.vue",
            "ReportsPage.vue",
            "ConfigPage.vue",
        ]

        for page in expected_pages:
            self.assertTrue((pages_dir / page).exists(), page)

    def test_vue_rag_page_calls_real_backend_llm_endpoint(self):
        api_ts = Path("frontend-vue/src/services/api.ts").read_text(encoding="utf-8")
        rag_page = Path("frontend-vue/src/pages/RagTestPage.vue").read_text(encoding="utf-8")

        self.assertIn("ragAsk", api_ts)
        self.assertIn("/api/rag/ask", api_ts)
        self.assertIn("检索并调用 DeepSeek", rag_page)
        self.assertIn("deepseek-v4-flash", rag_page)
        self.assertNotIn('value="mock"', rag_page)


if __name__ == "__main__":
    unittest.main()
