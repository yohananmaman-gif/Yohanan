"""Thread-safe stage reporting without sending Telegram requests from worker threads."""
from __future__ import annotations

import asyncio
import logging
import threading
import time

logger = logging.getLogger(__name__)


class ReportProgress:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stage = "מכין את החומרים"
        self.started = time.monotonic()

    def set(self, stage: str) -> None:
        with self._lock:
            self._stage = stage

    async def watch(self, status_message, interval: float = 15) -> None:
        while True:
            await asyncio.sleep(interval)
            with self._lock:
                stage = self._stage
            elapsed = int(time.monotonic() - self.started)
            try:
                await status_message.edit_text(
                    f"⏳ {stage}\nחלפו {elapsed // 60}:{elapsed % 60:02d} דקות. "
                    "אין צורך לשלוח שוב /report."
                )
            except Exception as error:
                logger.warning("Progress update unavailable (%s).", type(error).__name__)
