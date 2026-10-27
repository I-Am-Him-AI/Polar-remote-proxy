"""Connection password. Stored as an scrypt hash, never as plaintext."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
from pathlib import Path

_USER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{2,31}$")

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


def _write(record: dict, path: Path | None = None) -> None:
    dest = path or auth_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(record), encoding="utf-8")
    try:
        os.chmod(dest, 0o600)
    except OSError:
        pass


def set_password(password: str, path: Path | None = None) -> None:
    if not isinstance(password, str) or len(password) < MIN_LEN or len(password) > 256:
        raise ValueError(f"Password must be {MIN_LEN}–256 characters")
    dest = path or auth_path()
    existing = load_record(dest) or {}
    allowed = existing.get("allowed_usernames") if isinstance(existing.get("allowed_usernames"), list) else []
    salt = secrets.token_bytes(16)
    record = {
        "salt": salt.hex(),
        "hash": _hash(password, salt).hex(),
        "n": _N,
        "allowed_usernames": allowed,
    }
    _write(record, dest)


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


def valid_username(name: object) -> bool:
    return isinstance(name, str) and bool(_USER_RE.fullmatch(name))


def allowed_usernames(record: dict | None) -> list[str]:
    if not isinstance(record, dict):
        return []
    raw = record.get("allowed_usernames") or []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    return [item for item in raw if valid_username(item)]


def username_allowed(username: object, record: dict | None) -> bool:
    """Empty allow-list means any viewer. A list means that Polar username only."""
    allowed = allowed_usernames(record)
    if not allowed:
        return True
    if not isinstance(username, str):
        return False
    want = username.casefold()
    return any(name.casefold() == want for name in allowed)


def link_username(username: str, path: Path | None = None) -> list[str]:
    if not valid_username(username):
        raise ValueError("Username must be 3–32 letters, numbers, underscores, or hyphens")
    dest = path or auth_path()
    record = load_record(dest)
    if not record:
        raise ValueError("Set the connection password before linking a Polar account")
    names = allowed_usernames(record)
    if username.casefold() not in {name.casefold() for name in names}:
        names.append(username)
    record["allowed_usernames"] = names
    _write(record, dest)
    return names


def unlink_username(username: str, path: Path | None = None) -> list[str]:
    dest = path or auth_path()
    record = load_record(dest)
    if not record:
        raise ValueError("Set the connection password before unlinking a Polar account")
    key = username.casefold() if isinstance(username, str) else ""
    names = [name for name in allowed_usernames(record) if name.casefold() != key]
    record["allowed_usernames"] = names
    _write(record, dest)
    return names
