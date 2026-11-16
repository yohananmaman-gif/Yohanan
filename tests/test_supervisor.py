import importlib.util
from pathlib import Path
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "supervisor", Path(__file__).resolve().parents[1] / "scripts/supervise_services.py"
)
supervisor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(supervisor)
SLEEP = [sys.executable, "-c", "import time; time.sleep(30)"]


class SupervisorTests(unittest.TestCase):
    def run_case(self, api, bot, stop=None, **kwargs):
        spawned = []
        real_popen = subprocess.Popen
        def launch(*args, **options):
            child = real_popen(*args, **options)
            spawned.append(child)
            return child
        with patch.object(supervisor.subprocess, "Popen", side_effect=launch):
            result = supervisor.supervise(
                api, bot, stop or threading.Event(), tick=0.01,
                backoff=0.01, grace=0.2, **kwargs
            )
        self.assertTrue(all(child.poll() is not None for child in spawned))
        return result, spawned

    def test_conflict_is_fatal_and_never_restarted(self):
        result, children = self.run_case(SLEEP, [sys.executable, "-c", "raise SystemExit(78)"])
        self.assertEqual(result, 78)
        self.assertEqual(len(children), 2)

    def test_bot_crash_has_bounded_restarts(self):
        result, children = self.run_case(
            SLEEP, [sys.executable, "-c", "raise SystemExit(1)"], restart_limit=2
        )
        self.assertEqual(result, 1)
        self.assertEqual(len(children), 4)

    def test_api_exit_stops_bot(self):
        result, children = self.run_case([sys.executable, "-c", "pass"], SLEEP)
        self.assertEqual(result, 1)
        self.assertEqual(len(children), 2)

    def test_shutdown_signal_stops_both_children(self):
        stop = threading.Event()
        timer = threading.Timer(0.15, stop.set)
        timer.start()
        try:
            result, _ = self.run_case(SLEEP, SLEEP, stop)
            self.assertEqual(result, 0)
        finally:
            timer.cancel()
