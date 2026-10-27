"""python -m polar_remote_proxy"""

from __future__ import annotations

import argparse
import getpass
import os
import sys

from .auth import (
    MIN_LEN,
    allowed_usernames,
    auth_path,
    link_username,
    load_record,
    set_password,
    unlink_username,
    valid_username,
)
from .server import lan_hosts, make_server


def _prompt_password() -> str:
    print("Set a connection password. The other PC types this in Polar → Remote Desktop.")
    while True:
        first = getpass.getpass("Password: ")
        second = getpass.getpass("Confirm: ")
        if first != second:
            print("Those did not match. Try again.")
            continue
        if len(first) < MIN_LEN:
            print(f"Use at least {MIN_LEN} characters.")
            continue
        return first


def _prompt_link() -> str:
    print("Optional: link this PC to a Polar username.")
    print("Only that account can connect, and they still need this password.")
    print("Press Enter to skip. Polar still asks the viewer to log in.")
    while True:
        name = input("Polar username: ").strip()
        if not name:
            return ""
        if valid_username(name):
            return name
        print("Use 3–32 letters, numbers, underscores, or hyphens.")


def ensure_password(force: bool) -> dict:
    path = auth_path()
    if force or not path.is_file():
        env = os.environ.get("POLAR_REMOTE_PASSWORD", "")
        if env and not force and not sys.stdin.isatty():
            set_password(env, path)
        elif env and not force and os.environ.get("POLAR_REMOTE_PASSWORD_SAVE") == "1":
            set_password(env, path)
        elif not path.is_file():
            if env and not sys.stdin.isatty():
                set_password(env, path)
            else:
                set_password(_prompt_password(), path)
        else:
            set_password(_prompt_password(), path)
    record = load_record(path)
    if not record:
        raise SystemExit(f"No password is saved at {path}")
    return record


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Polar Remote Proxy")
    parser.add_argument("--set-password", action="store_true", help="Set a new connection password and keep running")
    parser.add_argument("--link-user", action="append", default=[], metavar="NAME", help="Also require this Polar username")
    parser.add_argument("--unlink-user", action="append", default=[], metavar="NAME", help="Remove a Polar username from the allow-list")
    parser.add_argument("--host", default=os.environ.get("POLAR_REMOTE_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("POLAR_REMOTE_PORT", "8765")))
    args = parser.parse_args(argv)
    existed = auth_path().is_file()
    record = ensure_password(args.set_password)
    try:
        if args.link_user or args.unlink_user:
            for name in args.link_user:
                link_username(name)
            for name in args.unlink_user:
                unlink_username(name)
            record = load_record()
        elif not existed and sys.stdin.isatty():
            linked = _prompt_link()
            if linked:
                link_username(linked)
                record = load_record()
        elif not existed:
            env_user = os.environ.get("POLAR_REMOTE_LINK_USER", "").strip()
            if env_user:
                link_username(env_user)
                record = load_record()
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if not record:
        raise SystemExit(f"No password is saved at {auth_path()}")
    try:
        server = make_server(args.host, args.port, record)
    except OSError as exc:
        raise SystemExit(f"Could not listen on {args.host}:{args.port} ({exc})") from exc
    port = server.server_address[1]
    print("Polar Remote Proxy is running.")
    print("Password required. The desktop is not shared until Polar sends that password.")
    linked = allowed_usernames(record)
    if linked:
        print("Linked Polar accounts: " + ", ".join(linked))
        print("The viewer must be logged in as one of those accounts, and must send this password.")
    else:
        print("No Polar account is linked. The connection password is enough for this app.")
        print("Link one with: python start.py --link-user NAME")
    print("On the other PC, open Polar → Remote Desktop, log in, and enter:")
    for ip in lan_hosts():
        print(f"  Host: {ip}:{port}")
    print("  Password: the one you set for this app")
    print("Leave this window open. Ctrl+C stops it.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.capture.stop()
        server.shutdown()


if __name__ == "__main__":
    main()
