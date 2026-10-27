"""python -m polar_remote_proxy"""

from __future__ import annotations

import argparse
import getpass
import os
import sys

from .auth import MIN_LEN, auth_path, load_record, set_password
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
    parser.add_argument("--host", default=os.environ.get("POLAR_REMOTE_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("POLAR_REMOTE_PORT", "8765")))
    args = parser.parse_args(argv)
    record = ensure_password(args.set_password)
    try:
        server = make_server(args.host, args.port, record)
    except OSError as exc:
        raise SystemExit(f"Could not listen on {args.host}:{args.port} ({exc})") from exc
    port = server.server_address[1]
    print("Polar Remote Proxy is running.")
    print("Password required. The desktop is not shared until Polar sends that password.")
    print("On the other PC, open Polar → Remote Desktop and enter:")
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
