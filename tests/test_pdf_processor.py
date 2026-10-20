"""PDF 解析 skill 的行为测试。

锁定口径：extract_pdf 基于 PyMuPDF，返回 PdfExtractionResult；
扫描件检测只标记不做 OCR；不存在的文件应抛明确异常。
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

try:
    from yanhai.skills.pdf_processor import extract_metadata, extract_pdf  # noqa: E402
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False


@unittest.skipUnless(HAS_PYMUPDF, "PyMuPDF 未安装")
class PdfProcessorTests(unittest.TestCase):
    def test_nonexistent_file_raises(self) -> None:
        with self.assertRaises((FileNotFoundError, RuntimeError)):
            extract_pdf("/nonexistent/path/file.pdf")

    def test_metadata_nonexistent_file_raises(self) -> None:
        with self.assertRaises((FileNotFoundError, RuntimeError)):
            extract_metadata("/nonexistent/path/file.pdf")

    def test_non_pdf_file_raises(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"this is not a pdf")
            tmp_path = f.name
        try:
            with self.assertRaises(Exception):
                extract_pdf(tmp_path)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_result_dataclass_has_expected_fields(self) -> None:
        """验证 PdfExtractionResult 的字段定义完整。"""
        from yanhai.skills.pdf_processor import PdfExtractionResult
        fields = PdfExtractionResult.__dataclass_fields__.keys()
        expected = {
            "file_path", "page_count", "metadata", "pages",
            "tables", "images", "full_text", "quality", "is_scanned",
        }
        self.assertTrue(expected.issubset(set(fields)))

    def test_page_text_dataclass_has_scan_flag(self) -> None:
        from yanhai.skills.pdf_processor import PageText
        fields = PageText.__dataclass_fields__.keys()
        self.assertIn("is_scanned", fields)
        self.assertIn("has_tables", fields)
        self.assertIn("image_count", fields)


if __name__ == "__main__":
    unittest.main()
