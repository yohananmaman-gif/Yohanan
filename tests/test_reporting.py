from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn

from enigmatech_inspection_bot.reporting import (
    build_report_document,
    choose_latest_flash_model,
)


class FlashModelSelectionTests(unittest.TestCase):
    def test_selects_latest_non_deprecated_flash_model(self) -> None:
        selected = choose_latest_flash_model(
            [
                "models/gemini-2.5-flash",
                "models/gemini-3-flash-preview",
                "models/gemini-3.8-flash",
                "models/gemini-3.8-flash-preview",
                "models/gemini-3.1-pro",
            ]
        )
        self.assertEqual(selected, "gemini-3.8-flash")

    def test_returns_none_when_only_deprecated_flash_models_exist(self) -> None:
        self.assertIsNone(
            choose_latest_flash_model(
                ["models/gemini-2.5-flash", "models/gemini-2.5-flash-lite"]
            )
        )


class WordReportTests(unittest.TestCase):
    def test_word_report_has_rtl_paragraphs_and_clean_headings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "EnigmaTech_Report_20261116_120000.docx"
            build_report_document(
                "## תקציר מנהלים\nהבדיקה הושלמה.\n"
                "## ממצאים וליקויים בשטח\n**נמצא ליקוי** בתמונה #1.\n"
                "## פעולות נדרשות והמלצות לביצוע\n- לבצע תיקון.",
                [],
                path,
                created_at=datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc),
            )

            document = Document(path)
            text = "\n".join(paragraph.text for paragraph in document.paragraphs)
            self.assertIn("דוח פיקוח וסיור בשטח - 16/11/2026 12:00", text)
            self.assertIn("נמצא ליקוי בתמונה #1.", text)
            self.assertIn("• לבצע תיקון.", text)
            self.assertNotIn("**", text)
            self.assertIn("נספח תמונות מהשטח", text)

            for paragraph in document.paragraphs:
                self.assertEqual(paragraph.alignment, WD_ALIGN_PARAGRAPH.RIGHT)
                self.assertIsNotNone(paragraph._p.pPr.find(qn("w:bidi")))
                for run in paragraph.runs:
                    self.assertIsNotNone(run._element.rPr.find(qn("w:rtl")))
                    self.assertEqual(run.font.name, "Arial")


if __name__ == "__main__":
    unittest.main()
