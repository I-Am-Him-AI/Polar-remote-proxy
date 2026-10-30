"""Require one JPEG from a Polar Remote Proxy that is already running.

The Windows smoke test uses this against the frozen exe, so a missing
Pillow or mss inside the exe fails the build.
"""

from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from polar_remote_proxy.wsutil import accept_key, encode_frame, read_frame  # noqa: E402


class _Sock:
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


def main() -> None:
    port = int(os.environ.get("POLAR_REMOTE_PORT", "8765"))
    password = os.environ["POLAR_REMOTE_PASSWORD"]
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
    status = head.decode().split("\r\n", 1)[0]
    if "101" not in status or accept_key(key) not in head.decode():
        raise SystemExit(f"websocket upgrade failed: {status}")
    wrapped = _Sock(sock, rest)
    wrapped.settimeout(8)
    _opcode, hello = read_frame(wrapped)
    if json.loads(hello).get("type") != "hello":
        raise SystemExit("missing hello")
    wrapped.sendall(encode_frame(1, json.dumps({"type": "auth", "password": password}).encode(), mask=True))
    _opcode, payload = read_frame(wrapped)
    if not json.loads(payload).get("ok"):
        raise SystemExit(f"auth rejected: {payload[:200]!r}")
    wrapped.settimeout(8)
    opcode, frame = read_frame(wrapped)
    if opcode != 2 or not frame.startswith(b"\xff\xd8"):
        raise SystemExit(f"expected a JPEG frame, got opcode {opcode} and {frame[:12]!r}")
    print(f"jpeg {len(frame)} bytes")
    sock.close()


if __name__ == "__main__":
    main()
