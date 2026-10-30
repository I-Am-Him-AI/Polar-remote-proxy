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
from polar_remote_proxy.auth import check_password, load_record


class DesktopBootTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.auth = Path(self.tmp.name) / "auth.json"
        os.environ["POLAR_REMOTE_AUTH_FILE"] = str(self.auth)
        os.environ.pop("POLAR_REMOTE_PASSWORD", None)
        os.environ.pop("POLAR_REMOTE_LINK_USER", None)
        os.environ["POLAR_REMOTE_PORT"] = "0"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_first_run_waits_for_the_window(self) -> None:
        decision = desktop.boot_remote()
        self.assertEqual(decision.mode, "setup")
        self.assertFalse(self.auth.is_file())

    def test_saved_password_listens_and_health_has_no_screen(self) -> None:
        desktop.save_password("correct-horse", "correct-horse")
        decision = desktop.boot_remote()
        self.assertEqual(decision.mode, "listen")
        record = decision.record
        self.assertIsNotNone(record)
        assert record is not None
        self.assertTrue(check_password("correct-horse", record))
        self.assertNotIn("correct-horse", self.auth.read_text(encoding="utf-8"))
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
            server.capture.stop()
            server.shutdown()

    def test_mismatch_does_not_save(self) -> None:
        with self.assertRaises(ValueError):
            desktop.save_password("abcd", "abce")
        self.assertFalse(self.auth.is_file())

    def test_env_password_boots_when_no_file_exists(self) -> None:
        os.environ["POLAR_REMOTE_PASSWORD"] = "env-pass-1"
        os.environ["POLAR_REMOTE_LINK_USER"] = "darren"
        decision = desktop.boot_remote()
        self.assertEqual(decision.mode, "listen")
        record = load_record(self.auth)
        self.assertTrue(check_password("env-pass-1", record))
        self.assertEqual(record["allowed_usernames"], ["darren"])
        self.assertNotIn("env-pass-1", self.auth.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
