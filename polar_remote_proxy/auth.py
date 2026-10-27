"""Connection password. Stored as an scrypt hash, never as plaintext."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path

AUTH_PATH = Path.home() / ".polar-remote-proxy" / "auth.json"
MIN_LEN = 4
_N = 2**14


def auth_path() -> Path:
    override = os.environ.get("POLAR_REMOTE_AUTH_FILE", "").strip()
    if override:
        return Path(override)
    return AUTH_PATH


def _hash(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=8, p=1, dklen=32)


def set_password(password: str, path: Path | None = None) -> None:
    if not isinstance(password, str) or len(password) < MIN_LEN or len(password) > 256:
        raise ValueError(f"Password must be {MIN_LEN}–256 characters")
    salt = secrets.token_bytes(16)
    record = {"salt": salt.hex(), "hash": _hash(password, salt).hex(), "n": _N}
    dest = path or auth_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(record), encoding="utf-8")
    try:
        os.chmod(dest, 0o600)
    except OSError:
        pass


def load_record(path: Path | None = None) -> dict | None:
    dest = path or auth_path()
    if not dest.is_file():
        return None
    try:
        data = json.loads(dest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or "salt" not in data or "hash" not in data:
        return None
    return data


def check_password(password: str, record: dict | None) -> bool:
    if not record or not isinstance(password, str) or len(password) > 256:
        return False
    try:
        salt = bytes.fromhex(record["salt"])
        expected = bytes.fromhex(record["hash"])
        actual = _hash(password, salt)
    except (KeyError, ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)
