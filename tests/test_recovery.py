import asyncio
import fcntl
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from enigmatech_inspection_bot import bot
from enigmatech_inspection_bot.sessions import InspectionSession, PhotoAsset
from enigmatech_inspection_bot.state import load_sessions, save_session, remove_session
from enigmatech_inspection_bot.progress import ReportProgress


class RecoveryTests(unittest.TestCase):
    def test_failed_atomic_write_keeps_previous_journal(self):
        with tempfile.TemporaryDirectory() as root, patch.dict("os.environ", {"BOT_STATE_DIR": root}):
            session = InspectionSession(notes=["original"])
            save_session(123, session)
            session.notes.append("new")
            with patch.object(Path, "replace", side_effect=OSError("fixture")):
                with self.assertRaises(OSError):
                    save_session(123, session)
            self.assertEqual(load_sessions()[123].notes, ["original"])
            self.assertFalse(list(Path(root).glob("*.tmp")))

    def test_local_lock_prevents_second_poller_before_network_calls(self):
        with tempfile.TemporaryDirectory() as root, patch.dict("os.environ", {"BOT_STATE_DIR": root}):
            with (Path(root) / "poller.lock").open("a") as handle:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with patch.object(bot, "_run") as run:
                    with self.assertRaises(SystemExit) as result:
                        bot.main()
                    self.assertEqual(result.exception.code, 78)
                    run.assert_not_called()

    def test_round_trip_preserves_materials_but_unlocks_interrupted_report(self):
        with tempfile.TemporaryDirectory() as root, patch.dict("os.environ", {"BOT_STATE_DIR": root}):
            session = InspectionSession(notes=["בדיקה"], is_reporting=True)
            photo = session.ensure_temp_dir(123) / "photo.jpg"
            photo.write_bytes(b"fixture")
            session.photos.append(PhotoAsset(photo, "caption"))
            save_session(123, session)
            recovered = load_sessions()[123]
            self.assertEqual(recovered.notes, ["בדיקה"])
            self.assertFalse(recovered.is_reporting)
            self.assertEqual(recovered.photos[0].path.read_bytes(), b"fixture")
            self.assertEqual((Path(root) / "123.json").stat().st_mode & 0o777, 0o600)
            remove_session(123)
            recovered.cleanup()
            self.assertEqual(load_sessions(), {})
            self.assertFalse(photo.exists())

    def test_corrupt_journal_is_not_overwritten_or_deleted(self):
        with tempfile.TemporaryDirectory() as root, patch.dict("os.environ", {"BOT_STATE_DIR": root}):
            path = Path(root) / "123.json"
            path.write_text("incomplete")
            with self.assertRaises(RuntimeError):
                load_sessions()
            self.assertEqual(path.read_text(), "incomplete")

    def test_missing_media_stops_recovery_instead_of_silently_losing_it(self):
        with tempfile.TemporaryDirectory() as root, patch.dict("os.environ", {"BOT_STATE_DIR": root}):
            session = InspectionSession(photos=[PhotoAsset(Path(root) / "missing.jpg")])
            save_session(123, session)
            with self.assertRaises(RuntimeError):
                load_sessions()
            self.assertTrue((Path(root) / "123.json").exists())


class BotDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.env = patch.dict("os.environ", {"BOT_STATE_DIR": self.directory.name})
        self.env.start()
        bot.SESSIONS.clear()
        bot.CHAT_LOCKS.clear()
        bot.REPORT_SLOTS = asyncio.Semaphore(2)
        self.session = InspectionSession(notes=["inspection"])
        bot.SESSIONS[123] = self.session
        save_session(123, self.session)
        self.status = SimpleNamespace(edit_text=AsyncMock(), delete=AsyncMock())
        self.message = SimpleNamespace(
            reply_text=AsyncMock(return_value=self.status),
            reply_document=AsyncMock(),
        )
        self.update = SimpleNamespace(message=self.message, effective_chat=SimpleNamespace(id=123))
        self.generation = patch.object(bot, "generate_inspection_report", return_value="report")
        self.generation.start()
        self.build = patch.object(bot, "build_report_document",
                                  side_effect=lambda text, photos, path: path.write_bytes(b"docx"))
        self.build.start()

    async def asyncTearDown(self):
        self.generation.stop()
        self.build.stop()
        bot.SESSIONS.clear()
        bot.CHAT_LOCKS.clear()
        self.env.stop()
        self.directory.cleanup()

    async def test_send_failure_keeps_retryable_session_and_journal(self):
        self.message.reply_document.side_effect = TimeoutError("fixture")
        await bot.report_command(self.update, None)
        self.assertIs(bot.SESSIONS[123], self.session)
        self.assertFalse(self.session.is_reporting)
        self.assertEqual(load_sessions()[123].notes, ["inspection"])
        self.assertEqual(bot.REPORT_SLOTS._value, 2)
        self.status.delete.assert_awaited_once()

    async def test_success_cleans_only_after_telegram_accepts_document(self):
        async def accept(**kwargs):
            self.assertIn(123, load_sessions())
            self.assertEqual(kwargs["document"].read(), b"docx")
        self.message.reply_document.side_effect = accept
        await bot.report_command(self.update, None)
        self.assertNotIn(123, bot.SESSIONS)
        self.assertEqual(load_sessions(), {})
        self.assertEqual(bot.REPORT_SLOTS._value, 2)

    async def test_status_failure_does_not_prevent_document_delivery(self):
        self.message.reply_text.side_effect = TimeoutError("fixture")
        await bot.report_command(self.update, None)
        self.message.reply_document.assert_awaited_once()
        self.assertEqual(load_sessions(), {})

    async def test_shutdown_preserves_saved_materials(self):
        await bot._post_shutdown(None)
        self.assertEqual(load_sessions()[123].notes, ["inspection"])

    async def test_capacity_limit_keeps_materials_and_does_not_generate(self):
        bot.REPORT_SLOTS = asyncio.Semaphore(0)
        await bot.report_command(self.update, None)
        self.message.reply_document.assert_not_awaited()
        self.assertFalse(self.session.is_reporting)
        self.assertIn(123, load_sessions())

    async def test_progress_failure_does_not_stop_periodic_updates(self):
        progress = ReportProgress()
        progress.set("fixture stage")
        self.status.edit_text.side_effect = [TimeoutError("fixture"), None, None, None]
        watcher = asyncio.create_task(progress.watch(self.status, interval=0.01))
        try:
            await asyncio.sleep(0.035)
            self.assertGreaterEqual(self.status.edit_text.await_count, 2)
            self.assertIn("fixture stage", self.status.edit_text.call_args.args[0])
        finally:
            watcher.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await watcher

    async def test_note_is_persisted_before_acknowledgement(self):
        self.message.text = "new note"
        async def acknowledge(*args, **kwargs):
            self.assertIn("new note", load_sessions()[123].notes)
        self.message.reply_text.side_effect = acknowledge
        await bot.text_handler(self.update, None)
        self.message.reply_text.assert_awaited_once()

    async def test_conflict_marks_fatal_exit_without_retry_loop(self):
        application = SimpleNamespace(bot_data={}, stop_running=lambda: None)
        await bot.telegram_error_handler(
            None, SimpleNamespace(error=bot.Conflict("fixture"), application=application)
        )
        self.assertEqual(application.bot_data["fatal_exit_code"], 78)
