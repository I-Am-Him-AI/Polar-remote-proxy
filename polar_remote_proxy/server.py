"""Home PC listener. Desktop bytes are sent only after the password checks out."""

from __future__ import annotations

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .auth import allowed_usernames, check_password, username_allowed
from .capture import Capture
from .input_relay import handle as relay_input
from .wsutil import accept_key, encode_frame, read_frame

_fail_lock = threading.Lock()
_fails: dict[str, list[float]] = {}


def _note_fail(ip: str) -> None:
    now = time.time()
    with _fail_lock:
        recent = [t for t in _fails.get(ip, []) if now - t < 60]
        recent.append(now)
        _fails[ip] = recent


def _too_many(ip: str) -> bool:
    now = time.time()
    with _fail_lock:
        recent = [t for t in _fails.get(ip, []) if now - t < 60]
        _fails[ip] = recent
        return len(recent) >= 8


class RemoteServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, host: str, port: int, record: dict, capture: Capture | None = None) -> None:
        self.record = record
        self.capture = capture or Capture()
        super().__init__((host, port), _make_handler(self))


def make_server(host: str, port: int, record: dict, capture: Capture | None = None) -> RemoteServer:
    server = RemoteServer(host, port, record, capture)
    server.capture.start()
    return server


def _make_handler(server: RemoteServer):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args) -> None:
            return

        def do_OPTIONS(self) -> None:
            self.send_response(204)
            self._cors()
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "*")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            upgrade = (self.headers.get("Upgrade") or "").lower()
            if upgrade == "websocket" and path in ("/ws", "/"):
                self._websocket()
                return
            if path == "/health":
                self._json(
                    200,
                    {
                        "ok": True,
                        "service": "polar-remote-proxy",
                        "account_link": bool(allowed_usernames(server.record)),
                    },
                )
                return
            self._json(401, {"ok": False, "error": "password_required"})

        def do_POST(self) -> None:
            self._json(401, {"ok": False, "error": "password_required"})

        def _cors(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")

        def _json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self._cors()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _websocket(self) -> None:
            key = self.headers.get("Sec-WebSocket-Key")
            if not key:
                self._json(400, {"ok": False, "error": "bad_handshake"})
                return
            self.send_response(101, "Switching Protocols")
            self.send_header("Upgrade", "websocket")
            self.send_header("Connection", "Upgrade")
            self.send_header("Sec-WebSocket-Accept", accept_key(key))
            self.end_headers()
            self.wfile.flush()
            self.close_connection = True
            sock = self.connection
            sock.settimeout(12)
            try:
                self._session(sock)
            except (ConnectionError, socket.timeout, OSError, ValueError):
                pass
            finally:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                try:
                    sock.close()
                except OSError:
                    pass

        def _session(self, sock: socket.socket) -> None:
            ip = self.client_address[0]
            _send_text(sock, {"type": "hello", "service": "polar-remote-proxy", "state": "waiting"})
            if _too_many(ip):
                time.sleep(1)
                _send_text(sock, {"type": "auth", "ok": False, "state": "wrong_password"})
                _send_close(sock, 4001)
                return
            opcode, payload = read_frame(sock)
            if opcode != 1:
                _send_close(sock, 4000)
                return
            try:
                msg = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                msg = {}
            password = msg.get("password") if isinstance(msg, dict) else ""
            username = msg.get("username") if isinstance(msg, dict) else None
            if not isinstance(password, str) or msg.get("type") != "auth" or not check_password(password, server.record):
                _note_fail(ip)
                time.sleep(0.4)
                _send_text(sock, {"type": "auth", "ok": False, "state": "wrong_password"})
                _send_close(sock, 4001)
                return
            if not username_allowed(username, server.record):
                time.sleep(0.2)
                _send_text(sock, {"type": "auth", "ok": False, "state": "account_required"})
                _send_close(sock, 4003)
                return
            _send_text(sock, {"type": "auth", "ok": True, "state": "waiting"})
            sock.settimeout(0.12)
            last = b""
            while True:
                try:
                    opcode, payload = read_frame(sock)
                except socket.timeout:
                    frame, sw, sh = server.capture.snapshot()
                    if frame and frame != last:
                        sock.sendall(encode_frame(2, frame))
                        last = frame
                    elif frame and last == b"":
                        sock.sendall(encode_frame(2, frame))
                        last = frame
                    continue
                if opcode == 8:
                    return
                if opcode == 9:
                    sock.sendall(encode_frame(10, payload))
                    continue
                if opcode != 1:
                    continue
                try:
                    incoming = json.loads(payload.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if isinstance(incoming, dict):
                    _w, sw, sh = server.capture.snapshot()
                    relay_input(incoming, sw or 1280, sh or 720)

    return Handler


def _send_text(sock: socket.socket, obj: dict) -> None:
    sock.sendall(encode_frame(1, json.dumps(obj).encode("utf-8")))


def _send_close(sock: socket.socket, code: int) -> None:
    import struct

    sock.sendall(encode_frame(8, struct.pack("!H", code)))


def lan_hosts() -> list[str]:
    hosts: list[str] = []
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("8.8.8.8", 80))
        ip = probe.getsockname()[0]
        probe.close()
        if ip and not ip.startswith("127."):
            hosts.append(ip)
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip.startswith("127."):
                continue
            if ip not in hosts:
                hosts.append(ip)
    except OSError:
        pass
    return hosts or ["127.0.0.1"]
