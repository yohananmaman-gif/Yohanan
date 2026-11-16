from __future__ import annotations

import shutil
import os
from uuid import uuid4
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class PhotoAsset:
    path: Path
    caption: str | None = None
    mime_type: str = "image/jpeg"


@dataclass(frozen=True)
class AudioAsset:
    path: Path
    mime_type: str


@dataclass
class InspectionSession:
    photos: list[PhotoAsset] = field(default_factory=list)
    voices: list[AudioAsset] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    temp_dir: Path | None = None
    is_reporting: bool = False

    def ensure_temp_dir(self, chat_id: int) -> Path:
        if self.temp_dir is None:
            root = Path(os.environ.get("BOT_STATE_DIR", ".bot-state")).resolve()
            root.mkdir(mode=0o700, parents=True, exist_ok=True)
            self.temp_dir = root / uuid4().hex
            self.temp_dir.mkdir(mode=0o700)
        return self.temp_dir

    def is_empty(self) -> bool:
        return not (self.photos or self.voices or self.notes)

    def cleanup(self) -> None:
        if self.temp_dir is not None:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
            self.temp_dir = None
        self.photos.clear()
        self.voices.clear()
        self.notes.clear()
        self.is_reporting = False
