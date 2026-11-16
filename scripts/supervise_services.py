"""Reserved VM entrypoint: preserve the API and supervise one bot worker."""
from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parent.parent
logger = logging.getLogger("services")


def production_environment() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "src"), str(ROOT / ".bot-runtime")])
    env["PYTHONUNBUFFERED"] = "1"
    return env


def check_build() -> None:
    if not (ROOT / "artifacts/api-server/dist/index.mjs").is_file():
        raise RuntimeError("Missing API build")
    if not (ROOT / ".bot-runtime").is_dir():
        raise RuntimeError("Missing bot dependencies")
    # -S proves imports work without development site packages. No network calls.
    subprocess.run(
        [sys.executable, "-S", "-c",
         "import telegram, google.genai, docx; import enigmatech_inspection_bot.bot"],
        cwd=ROOT, env=production_environment(), check=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def stop_child(child: subprocess.Popen, grace: float = 20) -> None:
    if child.poll() is not None:
        return
    try:
        os.killpg(child.pid, signal.SIGTERM)
        child.wait(timeout=grace)
    except ProcessLookupError:
        pass
    except subprocess.TimeoutExpired:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait()


def supervise(
    api_command: list[str],
    bot_command: list[str],
    stop: threading.Event,
    *,
    restart_limit: int = 5,
    backoff: float = 2,
    tick: float = 0.5,
    grace: float = 20,
) -> int:
    children = []
    try:
        def launch(command: list[str]) -> subprocess.Popen:
            child = subprocess.Popen(
                command, cwd=ROOT, env=production_environment(), start_new_session=True
            )
            children.append(child)
            return child

        api = launch(api_command)
        bot = launch(bot_command)
        started = time.monotonic()
        failures = 0
        logger.info("API and bot processes started; readiness is not yet confirmed.")
        while not stop.wait(tick):
            if api.poll() is not None:
                logger.error("API process exited; stopping the VM service.")
                return 1
            code = bot.poll()
            if code is None:
                continue
            if code == 78:
                logger.error("Bot polling conflict: stop the other poller before restarting.")
                return 78
            if time.monotonic() - started >= 300:
                failures = 0
            failures += 1
            if failures > restart_limit:
                logger.error("Bot restart limit reached; stopping the VM service.")
                return 1
            delay = min(backoff * 2 ** (failures - 1), 60)
            logger.warning("Bot exited; retry %d in %.1f seconds.", failures, delay)
            if stop.wait(delay):
                return 0
            children.remove(bot)
            bot = launch(bot_command)
            started = time.monotonic()
        return 0
    finally:
        # Signal both first, so the API cannot report healthy while bot shutdown waits.
        for child in children:
            if child.poll() is None:
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        for child in children:
            stop_child(child, grace)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Offline build check; no poller")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        check_build()
        if args.check:
            logger.info("Production imports and entrypoints verified; no services started.")
            return 0
        stop = threading.Event()
        for signum in (signal.SIGTERM, signal.SIGINT):
            signal.signal(signum, lambda *_: stop.set())
        return supervise(
            ["node", "--enable-source-maps", "artifacts/api-server/dist/index.mjs"],
            [sys.executable, "-S", "-m", "enigmatech_inspection_bot.bot"],
            stop,
        )
    except Exception as error:
        logger.error("Service startup failed (%s).", type(error).__name__)
        return 1


if __name__ == "__main__":
    sys.exit(main())
