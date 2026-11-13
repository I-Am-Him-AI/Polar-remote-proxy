"""Window launcher uses the same password file and health check as the console app."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

import desktop
from polar_remote_proxy.auth import check_password, is_share_active, load_record, set_share_active


class DesktopBootTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.auth = Path(self.tmp.name) / "auth.json"
        self.share = Path(self.tmp.name) / "share.json"
        os.environ["POLAR_REMOTE_AUTH_FILE"] = str(self.auth)
        os.environ["POLAR_REMOTE_SHARE_FILE"] = str(self.share)
        os.environ.pop("POLAR_REMOTE_PASSWORD", None)
        os.environ.pop("POLAR_REMOTE_LINK_USER", None)
        os.environ["POLAR_REMOTE_PORT"] = "0"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_first_run_waits_for_the_window(self) -> None:
        decision = desktop.boot_remote()
        self.assertEqual(decision.mode, "setup")
        self.assertFalse(self.auth.is_file())

    def test_saved_password_stays_stopped_until_start(self) -> None:
        desktop.save_password("correct-horse", "correct-horse")
        decision = desktop.boot_remote()
        self.assertEqual(decision.mode, "stopped")
        self.assertFalse(is_share_active())
        record = decision.record
        self.assertIsNotNone(record)
        assert record is not None
        self.assertTrue(check_password("correct-horse", record))
        self.assertNotIn("correct-horse", self.auth.read_text(encoding="utf-8"))

    def test_active_share_listens_and_health_has_no_screen(self) -> None:
        desktop.save_password("correct-horse", "correct-horse")
        set_share_active(True)
        decision = desktop.boot_remote()
        self.assertEqual(decision.mode, "listen")
        record = decision.record
        self.assertIsNotNone(record)
        assert record is not None
        server = desktop.open_remote(record)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as res:
                body = res.read()
            health = json.loads(body.decode())
            self.assertEqual(health["service"], "polar-remote-proxy")
            self.assertNotIn(b"\xff\xd8", body)
        finally:
            server.stop_share()

    def test_stop_leaves_durable_paused_state(self) -> None:
        desktop.save_password("correct-horse", "correct-horse")
        set_share_active(True)
        self.assertEqual(desktop.boot_remote().mode, "listen")
        set_share_active(False)
        again = desktop.boot_remote()
        self.assertEqual(again.mode, "stopped")
        self.assertTrue(check_password("correct-horse", again.record))
        self.assertTrue(self.auth.is_file())

    def test_mismatch_does_not_save(self) -> None:
        with self.assertRaises(ValueError):
            desktop.save_password("abcd", "abce")
        self.assertFalse(self.auth.is_file())

    def test_env_password_boots_when_no_file_exists(self) -> None:
        os.environ["POLAR_REMOTE_PASSWORD"] = "env-pass-1"
        os.environ["POLAR_REMOTE_LINK_USER"] = "darren"
        decision = desktop.boot_remote()
        self.assertEqual(decision.mode, "listen")
        self.assertTrue(is_share_active())
        record = load_record(self.auth)
        self.assertTrue(check_password("env-pass-1", record))
        self.assertEqual(record["allowed_usernames"], ["darren"])
        self.assertNotIn("env-pass-1", self.auth.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
