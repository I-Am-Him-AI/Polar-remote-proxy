"""Password gate: no frames before auth, wrong password rejected, health has no image."""

from __future__ import annotations

import json
import socket
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from polar_remote_proxy.auth import check_password, link_username, load_record, set_password, username_allowed
from polar_remote_proxy.server import make_server
from polar_remote_proxy.wsutil import accept_key, encode_frame, read_frame


class _Sock:
    """Socket wrapper that replays bytes already read with the HTTP handshake."""

    def __init__(self, sock: socket.socket, rest: bytes) -> None:
        self._sock = sock
        self._rest = rest

    def recv(self, n: int) -> bytes:
        if self._rest:
            take, self._rest = self._rest[:n], self._rest[n:]
            return take
        return self._sock.recv(n)

    def sendall(self, data: bytes) -> None:
        self._sock.sendall(data)

    def settimeout(self, timeout: float) -> None:
        self._sock.settimeout(timeout)

    def close(self) -> None:
        self._sock.close()


def _connect(port: int) -> _Sock:
    sock = socket.create_connection(("127.0.0.1", port), timeout=5)
    key = "dGhlIHNhbXBsZSBub25jZQ=="
    req = (
        "GET /ws HTTP/1.1\r\n"
        f"Host: 127.0.0.1:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    )
    sock.sendall(req.encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            break
        buf += chunk
    head, rest = buf.split(b"\r\n\r\n", 1)
    text = head.decode()
    if "101" not in text.split("\r\n", 1)[0]:
        raise AssertionError(text)
    if accept_key(key) not in text:
        raise AssertionError("bad accept")
    sock.settimeout(3)
    return _Sock(sock, rest)


class ProtocolTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.auth_file = str(Path(self._tmp.name) / "auth.json")
        set_password("correct-horse", Path(self.auth_file))
        record = json.loads(Path(self.auth_file).read_text(encoding="utf-8"))
        self.assertTrue(check_password("correct-horse", record))
        self.assertFalse(check_password("nope", record))
        self.server = make_server("127.0.0.1", 0, record)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.capture.stop()
        self.server.shutdown()
        self.thread.join(timeout=3)
        self._tmp.cleanup()

    def test_health_has_no_image(self) -> None:
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=3) as res:
            body = res.read()
        self.assertNotIn(b"\xff\xd8", body)
        data = json.loads(body)
        self.assertEqual(data["service"], "polar-remote-proxy")
        self.assertTrue(data["ok"])
        self.assertFalse(data["account_link"])
        self.assertNotIn(b"correct-horse", body)

    def test_http_root_rejects_without_pixels(self) -> None:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{self.port}/", timeout=3)
            self.fail("expected 401")
        except urllib.error.HTTPError as exc:
            body = exc.read()
            self.assertEqual(exc.code, 401)
            self.assertNotIn(b"\xff\xd8", body)
            self.assertIn(b"password_required", body)

    def test_wrong_password_sends_no_frame(self) -> None:
        sock = _connect(self.port)
        _opcode, hello = read_frame(sock)
        self.assertEqual(json.loads(hello)["type"], "hello")
        sock.sendall(encode_frame(1, json.dumps({"type": "auth", "password": "wrong"}).encode(), mask=True))
        opcode, payload = read_frame(sock)
        msg = json.loads(payload)
        self.assertEqual(opcode, 1)
        self.assertFalse(msg["ok"])
        self.assertEqual(msg["state"], "wrong_password")
        self.assertNotIn(b"\xff\xd8", payload)
        sock.close()

    def test_right_password_gets_jpeg(self) -> None:
        sock = _connect(self.port)
        read_frame(sock)
        sock.sendall(encode_frame(1, json.dumps({"type": "auth", "password": "correct-horse"}).encode(), mask=True))
        opcode, payload = read_frame(sock)
        self.assertTrue(json.loads(payload)["ok"])
        sock.settimeout(4)
        opcode, payload = read_frame(sock)
        self.assertEqual(opcode, 2)
        self.assertTrue(payload.startswith(b"\xff\xd8"))
        sock.close()

    def test_linked_account_rejects_other_username_without_pixels(self) -> None:
        self.server.record["allowed_usernames"] = ["darren"]
        sock = _connect(self.port)
        read_frame(sock)
        sock.sendall(
            encode_frame(
                1,
                json.dumps({"type": "auth", "password": "correct-horse", "username": "other"}).encode(),
                mask=True,
            )
        )
        opcode, payload = read_frame(sock)
        msg = json.loads(payload)
        self.assertEqual(opcode, 1)
        self.assertFalse(msg["ok"])
        self.assertEqual(msg["state"], "account_required")
        self.assertNotIn(b"\xff\xd8", payload)
        sock.close()

    def test_linked_account_accepts_matching_username(self) -> None:
        self.server.record["allowed_usernames"] = ["Darren"]
        sock = _connect(self.port)
        read_frame(sock)
        sock.sendall(
            encode_frame(
                1,
                json.dumps({"type": "auth", "password": "correct-horse", "username": "darren"}).encode(),
                mask=True,
            )
        )
        opcode, payload = read_frame(sock)
        self.assertTrue(json.loads(payload)["ok"])
        sock.settimeout(4)
        opcode, payload = read_frame(sock)
        self.assertEqual(opcode, 2)
        self.assertTrue(payload.startswith(b"\xff\xd8"))
        sock.close()

    def test_wrong_password_stays_wrong_when_linked(self) -> None:
        self.server.record["allowed_usernames"] = ["darren"]
        sock = _connect(self.port)
        read_frame(sock)
        sock.sendall(
            encode_frame(
                1,
                json.dumps({"type": "auth", "password": "wrong", "username": "darren"}).encode(),
                mask=True,
            )
        )
        _opcode, payload = read_frame(sock)
        msg = json.loads(payload)
        self.assertEqual(msg["state"], "wrong_password")
        self.assertNotIn(b"\xff\xd8", payload)
        sock.close()

    def test_password_change_keeps_linked_names_and_not_plaintext(self) -> None:
        link_username("darren", Path(self.auth_file))
        set_password("new-password-1", Path(self.auth_file))
        record = load_record(Path(self.auth_file))
        self.assertTrue(check_password("new-password-1", record))
        self.assertFalse(check_password("correct-horse", record))
        self.assertTrue(username_allowed("Darren", record))
        self.assertFalse(username_allowed("other", record))
        raw = Path(self.auth_file).read_text(encoding="utf-8")
        self.assertNotIn("correct-horse", raw)
        self.assertNotIn("new-password-1", raw)
        self.server.record["allowed_usernames"] = ["darren"]
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=3) as res:
            body = res.read().decode()
        health = json.loads(body)
        self.assertTrue(health["account_link"])
        self.assertNotIn("darren", body)
        self.assertNotIn("username", body)


if __name__ == "__main__":
    unittest.main()
