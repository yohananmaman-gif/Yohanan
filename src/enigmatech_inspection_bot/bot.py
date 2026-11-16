from __future__ import annotations

import asyncio
from contextlib import suppress
import fcntl
import logging
import mimetypes
import os
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from telegram import BotCommand, Update
from telegram.ext import (
    Application,
    ContextTypes,
    MessageHandler,
    CommandHandler,
    filters,
)
from telegram.error import Conflict

from .reporting import build_report_document, generate_inspection_report
from .sessions import AudioAsset, InspectionSession, PhotoAsset
from .state import load_sessions, remove_session, save_session, state_directory
from .progress import ReportProgress

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

SESSIONS: dict[int, InspectionSession] = {}
CHAT_LOCKS: dict[int, asyncio.Lock] = {}
REPORT_SLOTS = asyncio.Semaphore(2)

MAX_PHOTOS_PER_SESSION = 25
MAX_AUDIO_PER_SESSION = 15
MAX_NOTES_PER_SESSION = 50
MAX_MEDIA_BYTES = 20 * 1024 * 1024
MAX_NOTE_LENGTH = 4096
ALLOWED_AUDIO_EXTENSIONS = {
    ".aac",
    ".flac",
    ".m4a",
    ".mp3",
    ".ogg",
    ".opus",
    ".wav",
}

EMPTY_SESSION_MESSAGE = (
    "⚠️ לא נשמרו עדיין תמונות, הקלטות או הערות טקסט. "
    "שלח חומרים לבוט ולאחר מכן הפעל שוב /report."
)
PROCESSING_MESSAGE = "⏳ מעבד את ההקלטות והתמונות ובונה את הדוח... אנא המתן."
BUSY_MESSAGE = "⏳ הדוח בתהליך יצירה. שלח חומרים נוספים לאחר קבלת הדוח."
ERROR_MESSAGE = (
    "❌ אירעה תקלה במהלך יצירת הדוח. החומרים נשמרו; "
    "נסה שוב בעוד כמה דקות."
)


def _lock_for(chat_id: int) -> asyncio.Lock:
    if chat_id not in CHAT_LOCKS:
        CHAT_LOCKS[chat_id] = asyncio.Lock()
    return CHAT_LOCKS[chat_id]


def _session_directory(chat_id: int, session: InspectionSession) -> Path:
    return session.ensure_temp_dir(chat_id)


def _extension_for_audio(
    file_name: str | None,
    mime_type: str | None,
    is_voice: bool,
) -> tuple[str, str]:
    suffix = Path(file_name or "").suffix.lower()
    if suffix not in ALLOWED_AUDIO_EXTENSIONS:
        if is_voice:
            suffix = ".ogg"
        else:
            suffix = mimetypes.guess_extension(mime_type or "") or ".bin"
    if suffix == ".oga":
        suffix = ".ogg"
    resolved_mime = mime_type or mimetypes.guess_type(f"audio{suffix}")[0]
    if not resolved_mime or not resolved_mime.startswith("audio/"):
        resolved_mime = {
            ".ogg": "audio/ogg",
            ".opus": "audio/opus",
            ".mp3": "audio/mpeg",
            ".m4a": "audio/mp4",
            ".wav": "audio/wav",
            ".aac": "audio/aac",
            ".flac": "audio/flac",
        }.get(suffix, "application/octet-stream")
    return suffix, resolved_mime


async def start_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if update.message is None:
        return
    await update.message.reply_text(
        "שלום! שלח תמונות עם או בלי כיתוב, הודעות קוליות או קובצי שמע, "
        "והערות טקסט. לאחר מכן הפעל /report כדי ליצור דוח Word מסודר.\n\n"
        "פקודות זמינות:\n"
        "/report — יצירת דוח Word\n"
        "/clear — ניקוי החומרים שנשמרו\n"
        "/help — הצגת ההוראות"
    )


async def clear_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if update.message is None or update.effective_chat is None:
        return
    chat_id = update.effective_chat.id
    async with _lock_for(chat_id):
        session = SESSIONS.get(chat_id)
        if session is not None and session.is_reporting:
            await update.message.reply_text(
                "⏳ הדוח בתהליך יצירה. ניתן לנקות את החומרים לאחר קבלת הדוח."
            )
            return
        if session is not None:
            remove_session(chat_id)
            SESSIONS.pop(chat_id, None)
            session.cleanup()
    await update.message.reply_text(
        "🗑️ כל התמונות, ההקלטות והערות הטקסט שנשמרו נוקו."
    )


async def photo_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    message = update.message
    if message is None or update.effective_chat is None or not message.photo:
        return
    chat_id = update.effective_chat.id
    async with _lock_for(chat_id):
        session = SESSIONS.setdefault(chat_id, InspectionSession())
        if session.is_reporting:
            await message.reply_text(BUSY_MESSAGE)
            return
        if len(session.photos) >= MAX_PHOTOS_PER_SESSION:
            await message.reply_text(
                f"⚠️ ניתן לשמור עד {MAX_PHOTOS_PER_SESSION} תמונות בדוח אחד."
            )
            return

        photo = max(
            message.photo,
            key=lambda item: (item.width * item.height, item.file_size or 0),
        )
        if photo.file_size and photo.file_size > MAX_MEDIA_BYTES:
            await message.reply_text("⚠️ התמונה גדולה מדי. שלח תמונה עד 20MB.")
            return

        index = len(session.photos) + 1
        path = _session_directory(chat_id, session) / f"photo_{index}_{uuid4().hex}.jpg"
        try:
            telegram_file = await context.bot.get_file(photo.file_id)
            await telegram_file.download_to_drive(custom_path=path)
            if path.stat().st_size > MAX_MEDIA_BYTES:
                path.unlink(missing_ok=True)
                await message.reply_text("⚠️ התמונה גדולה מדי. שלח תמונה עד 20MB.")
                return
            session.photos.append(
                PhotoAsset(path=path, caption=message.caption, mime_type="image/jpeg")
            )
            save_session(chat_id, session)
        except Exception as error:
            session.photos[:] = [photo for photo in session.photos if photo.path != path]
            path.unlink(missing_ok=True)
            logger.error("Could not download a Telegram photo (%s).", type(error).__name__)
            await message.reply_text("❌ לא הצלחתי לשמור את התמונה. נסה לשלוח אותה שוב.")
            return
    await message.reply_text(f"📸 תמונה #{index} נשמרה.")


async def audio_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    message = update.message
    if message is None or update.effective_chat is None:
        return

    is_voice = message.voice is not None
    media = message.voice or message.audio or message.document
    if media is None:
        return

    if message.document is not None and message.voice is None and message.audio is None:
        document_name = message.document.file_name or ""
        document_mime = message.document.mime_type or ""
        if (
            Path(document_name).suffix.lower() not in ALLOWED_AUDIO_EXTENSIONS
            and not document_mime.startswith("audio/")
        ):
            return

    file_size = getattr(media, "file_size", None)
    if file_size and file_size > MAX_MEDIA_BYTES:
        await message.reply_text("⚠️ קובץ השמע גדול מדי. שלח קובץ עד 20MB.")
        return

    file_id = media.file_id
    file_name = getattr(media, "file_name", None)
    mime_type = getattr(media, "mime_type", None)
    suffix, resolved_mime = _extension_for_audio(file_name, mime_type, is_voice)
    chat_id = update.effective_chat.id

    async with _lock_for(chat_id):
        session = SESSIONS.setdefault(chat_id, InspectionSession())
        if session.is_reporting:
            await message.reply_text(BUSY_MESSAGE)
            return
        if len(session.voices) >= MAX_AUDIO_PER_SESSION:
            await message.reply_text(
                f"⚠️ ניתן לשמור עד {MAX_AUDIO_PER_SESSION} הקלטות בדוח אחד."
            )
            return

        index = len(session.voices) + 1
        path = (
            _session_directory(chat_id, session)
            / f"audio_{index}_{uuid4().hex}{suffix}"
        )
        try:
            telegram_file = await context.bot.get_file(file_id)
            await telegram_file.download_to_drive(custom_path=path)
            if path.stat().st_size > MAX_MEDIA_BYTES:
                path.unlink(missing_ok=True)
                await message.reply_text("⚠️ קובץ השמע גדול מדי. שלח קובץ עד 20MB.")
                return
            session.voices.append(AudioAsset(path=path, mime_type=resolved_mime))
            save_session(chat_id, session)
        except Exception as error:
            session.voices[:] = [voice for voice in session.voices if voice.path != path]
            path.unlink(missing_ok=True)
            logger.error(
                "Could not download a Telegram audio file (%s).",
                type(error).__name__,
            )
            await message.reply_text("❌ לא הצלחתי לשמור את ההקלטה. נסה לשלוח אותה שוב.")
            return
    await message.reply_text(f"🎙️ הקלטה #{index} נשמרה.")


async def text_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    message = update.message
    if message is None or update.effective_chat is None or not message.text:
        return
    note = message.text.strip()
    if not note:
        return
    if len(note) > MAX_NOTE_LENGTH:
        await message.reply_text("⚠️ ההערה ארוכה מדי. שלח הודעה קצרה יותר.")
        return

    chat_id = update.effective_chat.id
    async with _lock_for(chat_id):
        session = SESSIONS.setdefault(chat_id, InspectionSession())
        if session.is_reporting:
            await message.reply_text(BUSY_MESSAGE)
            return
        if len(session.notes) >= MAX_NOTES_PER_SESSION:
            await message.reply_text(
                f"⚠️ ניתן לשמור עד {MAX_NOTES_PER_SESSION} הערות בדוח אחד."
            )
            return
        session.notes.append(note)
        try:
            save_session(chat_id, session)
        except Exception as error:
            session.notes.pop()
            logger.error("Could not save note (%s).", type(error).__name__)
            await message.reply_text("❌ לא הצלחתי לשמור את ההערה. נסה שוב.")
            return
    await message.reply_text("✅ הערת הטקסט נשמרה.")


async def report_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    message = update.message
    if message is None or update.effective_chat is None:
        return

    chat_id = update.effective_chat.id
    async with _lock_for(chat_id):
        session = SESSIONS.get(chat_id)
        if session is None or session.is_empty():
            await message.reply_text(EMPTY_SESSION_MESSAGE)
            return
        if session.is_reporting:
            await message.reply_text("⏳ הדוח כבר נמצא בתהליך יצירה. אנא המתן.")
            return
        if REPORT_SLOTS.locked():
            await message.reply_text(
                "⏳ המערכת מכינה דוחות אחרים. החומרים שלך נשמרו; נסה /report בעוד רגע."
            )
            return
        notes = list(session.notes)
        voices = list(session.voices)
        photos = list(session.photos)
        report_directory = _session_directory(chat_id, session)
        save_session(chat_id, session)
        await REPORT_SLOTS.acquire()
        session.is_reporting = True

    progress = ReportProgress()
    progress_task = None
    status_message = None
    started = time.monotonic()
    stage = "starting"
    try:
        try:
            status_message = await message.reply_text(PROCESSING_MESSAGE)
            progress_task = asyncio.create_task(progress.watch(status_message))
        except Exception as error:
            logger.warning("Initial progress unavailable (%s).", type(error).__name__)
        stage = "generation"
        report_text = await asyncio.to_thread(
            generate_inspection_report,
            notes,
            voices,
            photos,
            progress.set,
        )
        stage = "document"
        stage_started = time.monotonic()
        progress.set("בונה את קובץ ה-Word")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        document_path = report_directory / f"EnigmaTech_Report_{timestamp}.docx"
        await asyncio.to_thread(
            build_report_document,
            report_text,
            photos,
            document_path,
        )
        logger.info("Report stage=document seconds=%.2f", time.monotonic() - stage_started)
        stage = "delivery"
        stage_started = time.monotonic()
        progress.set("שולח את הדוח ל-Telegram")
        with document_path.open("rb") as document_file:
            await message.reply_document(
                document=document_file,
                filename=document_path.name,
                caption="📄 הדוח מוכן! מצורף קובץ Word מסודר.",
                write_timeout=120,
                read_timeout=120,
            )
        logger.info("Report stage=delivery seconds=%.2f", time.monotonic() - stage_started)
    except asyncio.CancelledError:
        session.is_reporting = False
        raise
    except Exception as error:
        logger.error("Inspection report failed stage=%s (%s).", stage, type(error).__name__)
        async with _lock_for(chat_id):
            if SESSIONS.get(chat_id) is session:
                session.is_reporting = False
        await message.reply_text(ERROR_MESSAGE)
        return
    finally:
        if progress_task:
            progress_task.cancel()
            with suppress(asyncio.CancelledError):
                await progress_task
        if status_message:
            # Remove stale "processing" status on both success and failure.
            with suppress(Exception):
                await status_message.delete()
        REPORT_SLOTS.release()

    async with _lock_for(chat_id):
        if SESSIONS.get(chat_id) is session:
            remove_session(chat_id)
            SESSIONS.pop(chat_id, None)
        session.cleanup()
    logger.info("Report stage=complete seconds=%.2f", time.monotonic() - started)


async def telegram_error_handler(
    update: object, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if isinstance(context.error, Conflict):
        logger.error(
            "Telegram polling conflict: another bot instance is active. "
            "Stop the other poller before restarting this workflow."
        )
        context.application.bot_data["fatal_exit_code"] = 78
        context.application.stop_running()
        return
    logger.error(
        "Unhandled Telegram update error (%s).",
        type(context.error).__name__,
    )
    message = getattr(update, "effective_message", None)
    if message is not None:
        try:
            await message.reply_text("❌ אירעה תקלה בעיבוד ההודעה. נסה שוב.")
        except Exception:
            logger.warning("Could not send the Telegram error notice.")


async def _post_init(application: Application) -> None:
    commands = [
        BotCommand("start", "התחלת שימוש"),
        BotCommand("help", "הוראות שימוש"),
        BotCommand("report", "יצירת דוח Word"),
        BotCommand("clear", "ניקוי החומרים שנשמרו"),
    ]
    try:
        await application.bot.set_my_commands(commands)
    except Exception as error:
        logger.warning(
            "Could not update the Telegram command menu (%s).",
            type(error).__name__,
        )


async def _post_shutdown(application: Application) -> None:
    for chat_id, session in list(SESSIONS.items()):
        save_session(chat_id, session)
    SESSIONS.clear()
    CHAT_LOCKS.clear()


def main() -> None:
    # Prevent accidental local duplicate pollers; this does not lock other VMs.
    with (state_directory() / "poller.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logger.error("A bot poller is already running in this environment.")
            raise SystemExit(78)
        try:
            _run()
        except Exception as error:
            # Startup/request exceptions may contain credentials in request URLs.
            logger.error("Bot stopped unexpectedly (%s).", type(error).__name__)
            raise SystemExit(1) from None


def _run() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    missing = [
        name
        for name, value in (
            ("TELEGRAM_BOT_TOKEN", token),
            ("GEMINI_API_KEY", gemini_key),
        )
        if not value
    ]
    if missing:
        raise SystemExit(
            "Missing required Replit Secrets: " + ", ".join(missing)
        )
    SESSIONS.update(load_sessions())
    logger.info("Recovered %d unfinished sessions.", len(SESSIONS))

    application = (
        Application.builder()
        .token(token)
        .concurrent_updates(8)
        .connection_pool_size(32)
        .pool_timeout(60)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    application.add_handler(CommandHandler(["start", "help"], start_command))
    application.add_handler(CommandHandler("clear", clear_command))
    application.add_handler(CommandHandler("report", report_command))
    application.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    application.add_handler(
        MessageHandler(
            filters.VOICE | filters.AUDIO | filters.Document.ALL,
            audio_handler,
        )
    )
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler)
    )
    application.add_error_handler(telegram_error_handler)

    logger.info("Starting EnigmaTech Inspection Bot polling.")
    application.run_polling(
        drop_pending_updates=False,
        bootstrap_retries=-1,
        poll_interval=1.0,
        timeout=30,
        allowed_updates=["message"],
    )
    if application.bot_data.get("fatal_exit_code"):
        raise SystemExit(application.bot_data["fatal_exit_code"])


if __name__ == "__main__":
    main()
