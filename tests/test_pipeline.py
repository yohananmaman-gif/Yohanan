from pathlib import Path
from types import SimpleNamespace
import threading
import time
import unittest
from unittest.mock import patch

from enigmatech_inspection_bot.reporting import generate_inspection_report, UPLOAD_WORKERS
from enigmatech_inspection_bot.sessions import AudioAsset, PhotoAsset


class FakeFiles:
    def __init__(self, failure=None):
        self.lock = threading.Lock()
        self.active = self.peak = 0
        self.uploaded = []
        self.deleted = []
        self.failure = failure

    def upload(self, file, config):
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            time.sleep(0.06 if file == "voice" else 0.02)
            if file == self.failure:
                raise ValueError("fixture upload failed")
            with self.lock:
                self.uploaded.append(file)
            return SimpleNamespace(name=file, uri=f"https://files.invalid/{file}",
                                   mime_type=config.mime_type, state="ACTIVE")
        finally:
            with self.lock:
                self.active -= 1

    def delete(self, name, config):
        with self.lock:
            self.deleted.append(name)


class GeminiServiceError(Exception):
    def __init__(self, code):
        super().__init__("Gemini service error")
        self.code = code


class PipelineTests(unittest.TestCase):
    def run_report(self, *, failure=None, text="דוח"):
        files = FakeFiles(failure)
        captured = {}

        def generate(**kwargs):
            captured.update(kwargs)
            return SimpleNamespace(text=text)

        client = SimpleNamespace(files=files, models=SimpleNamespace(generate_content=generate),
                                 close=lambda: None)
        stages = []
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-fixture"}), \
             patch("enigmatech_inspection_bot.reporting.genai.Client", return_value=client):
            try:
                result = generate_inspection_report(
                    ["note"], [AudioAsset(Path("voice"), "audio/ogg")],
                    [PhotoAsset(Path(f"photo{i}")) for i in range(6)], stages.append,
                )
            except Exception:
                self.assertCountEqual(files.uploaded, files.deleted)
                self.assertEqual(files.active, 0)
                raise
        return files, captured, stages, result

    def test_parallel_uploads_are_bounded_and_keep_original_order(self):
        files, captured, stages, result = self.run_report()
        self.assertGreater(files.peak, 1)
        self.assertLessEqual(files.peak, UPLOAD_WORKERS)
        uris = [p.file_data.file_uri for p in captured["contents"] if p.file_data]
        self.assertEqual(uris, ["https://files.invalid/voice"] +
                         [f"https://files.invalid/photo{i}" for i in range(6)])
        self.assertEqual(result, "דוח")
        self.assertCountEqual(files.uploaded, files.deleted)
        self.assertTrue(any("7/7" in stage for stage in stages))

    def test_upload_failure_joins_workers_and_cleans_successful_uploads(self):
        with self.assertRaises(ValueError):
            self.run_report(failure="photo1")

    def test_empty_generation_still_cleans_all_media(self):
        with self.assertRaisesRegex(RuntimeError, "empty"):
            self.run_report(text="")

    def test_retries_overloaded_model_then_uses_another_flash_model(self):
        files = FakeFiles()
        attempts = []

        def generate(model, **kwargs):
            attempts.append(model)
            if model == "gemini-3.8-flash":
                raise GeminiServiceError(503)
            return SimpleNamespace(text="דוח חלופי")

        client = SimpleNamespace(
            files=files,
            models=SimpleNamespace(
                generate_content=generate,
                list=lambda: [
                    SimpleNamespace(
                        name="models/gemini-3.7-flash",
                        supported_actions=["generateContent"],
                    ),
                    SimpleNamespace(
                        name="models/gemini-2.5-flash",
                        supported_actions=["generateContent"],
                    ),
                ],
            ),
            close=lambda: None,
        )
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-fixture"}), \
             patch("enigmatech_inspection_bot.reporting.genai.Client",
                   return_value=client), \
             patch("enigmatech_inspection_bot.reporting.time.sleep"):
            result = generate_inspection_report([], [], [])

        self.assertEqual(result, "דוח חלופי")
        self.assertEqual(attempts, ["gemini-3.8-flash"] * 4 + ["gemini-3.7-flash"])
