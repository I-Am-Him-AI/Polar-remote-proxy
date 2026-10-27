#!/usr/bin/env python3
"""One-command start: install what is missing, then run Polar Remote Proxy."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _missing() -> list[str]:
    missing = []
    for mod in ("PIL", "mss"):
        try:
            __import__(mod)
        except Exception:
            missing.append(mod)
    return missing


def main() -> None:
    if _missing():
        req = ROOT / "requirements.txt"
        print("Installing Polar Remote Proxy dependencies…")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(req)])
    # Mouse and keyboard relay. The screen still works if this cannot install.
    subprocess.call([sys.executable, "-m", "pip", "install", "pynput>=1.7.6"])
    sys.path.insert(0, str(ROOT))
    from polar_remote_proxy.__main__ import main as run

    run()


if __name__ == "__main__":
    main()
