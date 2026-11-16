"""Private, atomic local recovery journal. Not a cross-machine backup."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from uuid import uuid4

from .sessions import AudioAsset, InspectionSession, PhotoAsset

logger = logging.getLogger(__name__)


def state_directory() -> Path:
    root = Path(os.environ.get("BOT_STATE_DIR", ".bot-state")).resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root


def save_session(chat_id: int, session: InspectionSession) -> None:
    root = state_directory()
    payload = {
        "chat_id": chat_id,
        "notes": session.notes,
        "temp_dir": str(session.temp_dir) if session.temp_dir else None,
        "photos": [
            {"path": str(p.path), "caption": p.caption, "mime_type": p.mime_type}
            for p in session.photos
        ],
        "voices": [
            {"path": str(v.path), "mime_type": v.mime_type} for v in session.voices
        ],
    }
    temporary = root / f".{uuid4().hex}.tmp"
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            os.chmod(temporary, 0o600)
            json.dump(payload, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(root / f"{chat_id}.json")
    finally:
        temporary.unlink(missing_ok=True)


def remove_session(chat_id: int) -> None:
    (state_directory() / f"{chat_id}.json").unlink(missing_ok=True)


def load_sessions() -> dict[int, InspectionSession]:
    recovered = {}
    root = state_directory()
    for manifest in root.glob("*.json"):
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            chat_id = int(data["chat_id"])
            if manifest.stem != str(chat_id):
                raise ValueError("Mismatched manifest")
            directory = Path(data["temp_dir"]) if data["temp_dir"] else None
            assets = data["photos"] + data["voices"]
            # Only trust files inside the private state directory.
            for asset in assets:
                path = Path(asset["path"]).resolve()
                if not path.is_relative_to(root) or not path.is_file():
                    raise ValueError("Missing or invalid saved media")
            if directory and directory.resolve().parent != root:
                raise ValueError("Invalid saved directory")
            recovered[chat_id] = InspectionSession(
                notes=data["notes"],
                photos=[PhotoAsset(**{**p, "path": Path(p["path"])}) for p in data["photos"]],
                voices=[AudioAsset(**{**v, "path": Path(v["path"])}) for v in data["voices"]],
                temp_dir=directory,
                is_reporting=False,
            )
        except Exception as error:
            # Do not delete corrupt manifests or partially recovered media.
            logger.error("Saved session needs recovery (%s).", type(error).__name__)
            raise RuntimeError("Saved materials require recovery; journal left untouched.") from None
    return recovered
