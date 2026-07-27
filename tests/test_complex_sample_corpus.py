import unittest
from pathlib import Path

from src.io import LoaderOptions, load_documents_from_path


class ComplexSampleCorpusTests(unittest.TestCase):
    def test_complex_sample_corpus_loads_multiple_formats(self):
        sample_dir = Path("test_files/complex_samples")

        texts, metadatas = load_documents_from_path(
            str(sample_dir),
            options=LoaderOptions(text_fields=["data.body"], max_records=100),
        )

        combined = "\n".join(texts)
        file_types = {metadata.get("file_type") for metadata in metadatas}

        self.assertGreaterEqual(len(texts), 8)
        self.assertIn(".md", file_types)
        self.assertIn(".csv", file_types)
        self.assertIn(".jsonl", file_types)
        self.assertIn(".txt", file_types)
        self.assertIn(".html", file_types)
        self.assertIn("付款条件", combined)
        self.assertIn("扫描 OCR 噪声样例", combined)
        self.assertIn("父子 chunk", combined)


if __name__ == "__main__":
    unittest.main()
