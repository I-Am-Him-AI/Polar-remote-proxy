"""Minimal WebSocket frames (RFC 6455) for one password-gated viewer."""

from __future__ import annotations

import base64
import hashlib
import os
import socket
import struct

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def accept_key(sec_key: str) -> str:
    digest = hashlib.sha1((sec_key.strip() + GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


def encode_frame(opcode: int, payload: bytes, mask: bool = False) -> bytes:
    if len(payload) > 8_000_000:
        raise ValueError("frame too large")
    head = bytearray([0x80 | (opcode & 0x0F)])
    length = len(payload)
    mask_bit = 0x80 if mask else 0
    if length < 126:
        head.append(mask_bit | length)
    elif length < 65536:
        head.append(mask_bit | 126)
        head += struct.pack("!H", length)
    else:
        head.append(mask_bit | 127)
        head += struct.pack("!Q", length)
    if mask:
        key = os.urandom(4)
        head += key
        payload = bytes(b ^ key[i % 4] for i, b in enumerate(payload))
    return bytes(head) + payload


def recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("closed")
        buf += chunk
    return bytes(buf)


def read_frame(sock: socket.socket, max_len: int = 1_000_000) -> tuple[int, bytes]:
    b1, b2 = recv_exact(sock, 2)
    opcode = b1 & 0x0F
    masked = (b2 & 0x80) != 0
    length = b2 & 0x7F
    if length == 126:
        length = struct.unpack("!H", recv_exact(sock, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", recv_exact(sock, 8))[0]
    if length > max_len:
        raise ValueError("frame too large")
    mask = recv_exact(sock, 4) if masked else b""
    data = recv_exact(sock, length) if length else b""
    if masked:
        data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
    return opcode, data
