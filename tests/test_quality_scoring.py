import unittest

from src.cleaning.text_cleaner import QualityFilter, QualityScorer
from src.pipeline import DataPipeline


class QualityScorerTests(unittest.TestCase):
    def setUp(self):
        self.scorer = QualityScorer({
            "enabled": True,
            "min_word_count": 2,
            "max_word_count": 1000,
            "min_score": 60,
            "remove_gibberish": True,
            "max_symbol_ratio": 0.35,
            "max_repeated_line_ratio": 0.50,
            "max_ocr_noise_ratio": 0.45,
            "max_mojibake_ratio": 0.02,
        })

    def test_valid_text_has_metrics_and_passes(self):
        result = self.scorer.score("This is a useful paragraph with enough natural language content.")

        self.assertTrue(result["valid"])
        self.assertEqual(result["reasons"], [])
        self.assertGreaterEqual(result["score"], 60)
        self.assertGreater(result["metrics"]["word_count"], 2)

    def test_symbol_noise_is_rejected_with_reason(self):
        result = self.scorer.score("@@@@ //// !!!! ???? ####")

        self.assertFalse(result["valid"])
        self.assertIn("too_many_symbols", result["reasons"])
        self.assertGreater(result["metrics"]["symbol_ratio"], 0.35)

    def test_repeated_lines_are_rejected_with_reason(self):
        result = self.scorer.score(("same useful line\n" * 8).strip())

        self.assertFalse(result["valid"])
        self.assertIn("repeated_lines", result["reasons"])
        self.assertGreater(result["metrics"]["repeated_line_ratio"], 0.50)

    def test_ocr_noise_is_rejected_with_reason(self):
        noisy = " ".join(list("abcdefghijklmnopqrstuvwxyz"))
        result = self.scorer.score(noisy)

        self.assertFalse(result["valid"])
        self.assertIn("ocr_noise", result["reasons"])
        self.assertGreater(result["metrics"]["ocr_noise_ratio"], 0.45)

    def test_mojibake_is_rejected_when_enabled(self):
        result = self.scorer.score("\u00e6\u00e6\u00e6 corrupted text data")

        self.assertFalse(result["valid"])
        self.assertIn("mojibake", result["reasons"])

    def test_quality_filter_keeps_boolean_api_compatible(self):
        quality_filter = QualityFilter({"enabled": True, "min_word_count": 2})

        self.assertTrue(quality_filter.is_valid("two words"))
        self.assertFalse(quality_filter.is_valid(""))


class PipelineQualityReportTests(unittest.TestCase):
    def test_prepare_texts_returns_quality_summary_and_rejection_reports(self):
        pipeline = DataPipeline("config.dev.yaml")
        prepared = pipeline.prepare_texts(
            [
                "valid document with semantic content",
                "@@@@ //// !!!! ????",
            ],
            source_metadata=[
                {"filename": "valid.txt"},
                {"filename": "noise.txt"},
            ],
            mutate_dedup=False,
        )

        self.assertEqual(prepared["stats"]["quality_summary"]["scored_count"], 2)
        self.assertEqual(prepared["stats"]["quality_summary"]["rejected_count"], 1)
        self.assertEqual(len(prepared["quality_reports"]), 1)
        self.assertEqual(prepared["quality_reports"][0]["metadata"]["filename"], "noise.txt")
        self.assertIn("too_many_symbols", prepared["quality_reports"][0]["reasons"])


if __name__ == "__main__":
    unittest.main()
