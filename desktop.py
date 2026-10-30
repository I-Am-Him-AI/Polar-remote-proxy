#!/usr/bin/env python3
"""Windowed Polar Remote Proxy. Double-click the .exe. No console."""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import NamedTuple

from polar_remote_proxy.auth import (
    MIN_LEN,
    allowed_usernames,
    auth_path,
    link_username,
    load_record,
    set_password,
    unlink_username,
    valid_username,
)
from polar_remote_proxy.server import lan_hosts, make_server


class Boot(NamedTuple):
    mode: str
    record: dict | None
    error: str


def save_password(password: str, confirm: str) -> None:
    if password != confirm:
        raise ValueError("Those did not match. Try again.")
    if len(password) < MIN_LEN:
        raise ValueError(f"Use at least {MIN_LEN} characters.")
    set_password(password)


def boot_remote() -> Boot:
    """Same first-run rules as the console app, without reading the keyboard."""
    path = auth_path()
    existed = path.is_file()
    env_pw = os.environ.get("POLAR_REMOTE_PASSWORD", "")
    if not existed:
        if not env_pw:
            return Boot("setup", None, "")
        try:
            set_password(env_pw, path)
            user = os.environ.get("POLAR_REMOTE_LINK_USER", "").strip()
            if user:
                link_username(user, path)
        except ValueError as exc:
            return Boot("setup", None, str(exc))
    record = load_record(path)
    if not record:
        return Boot("setup", None, f"No password is saved at {path}")
    return Boot("listen", record, "")


def open_remote(record: dict):
    host = os.environ.get("POLAR_REMOTE_HOST", "0.0.0.0")
    port = int(os.environ.get("POLAR_REMOTE_PORT", "8765"))
    try:
        return make_server(host, port, record)
    except OSError as exc:
        raise OSError(f"Could not listen on {host}:{port} ({exc})") from exc


def describe_remote(server) -> dict:
    port = server.server_address[1]
    return {
        "port": port,
        "hosts": [f"{ip}:{port}" for ip in lan_hosts()],
        "linked": allowed_usernames(server.record),
    }


def _bind_log() -> None:
    dest = Path.home() / ".polar-remote-proxy"
    try:
        dest.mkdir(parents=True, exist_ok=True)
        handle = open(dest / "app.log", "a", encoding="utf-8", buffering=1)
    except OSError:
        return
    sys.stdout = handle
    sys.stderr = handle
    global _LOG
    _LOG = handle


_LOG = None


def launch() -> None:
    import tkinter as tk
    from tkinter import ttk

    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("IAmHim.PolarRemoteProxy.0.2")
        except Exception:
            pass

    class App(tk.Tk):
        def __init__(self) -> None:
            super().__init__()
            self.title("Polar Remote Proxy")
            self.geometry("520x560")
            self.minsize(440, 480)
            self.server = None
            self._starting = False
            self._body = ttk.Frame(self, padding=16)
            self.configure(bg="#10233f")
            header = tk.Frame(self, bg="#10233f")
            header.pack(fill="x")
            tk.Label(
                header,
                text="Polar Remote Proxy",
                bg="#10233f",
                fg="white",
                font=("Segoe UI", 18, "bold"),
                anchor="w",
            ).pack(fill="x", padx=16, pady=(14, 0))
            tk.Label(
                header,
                text="Share this PC with Polar Remote Desktop",
                bg="#10233f",
                fg="#c5d4e8",
                font=("Segoe UI", 10),
                anchor="w",
            ).pack(fill="x", padx=16, pady=(0, 14))
            style = ttk.Style(self)
            if "vista" in style.theme_names():
                style.theme_use("vista")
            self._body.pack(fill="both", expand=True)
            self.protocol("WM_DELETE_WINDOW", self._close)
            decision = boot_remote()
            if decision.mode == "listen" and decision.record:
                self._status("Starting…")
                self.after(100, lambda: self._listen(decision.record))
            else:
                self._setup(decision.error)

        def _clear(self) -> None:
            for child in self._body.winfo_children():
                child.destroy()

        def _status(self, text: str) -> None:
            self._clear()
            ttk.Label(self._body, text=text, font=("Segoe UI", 12)).pack(anchor="w")

        def _setup(self, error: str) -> None:
            self._clear()
            ttk.Label(
                self._body,
                text="Set a connection password. The other computer types it in Polar, under Remote Desktop.",
                wraplength=460,
            ).pack(anchor="w", pady=(0, 12))
            self._pw = self._labeled("Password")
            self._confirm = self._labeled("Confirm")
            ttk.Label(
                self._body,
                text="Optional: only this Polar username can connect. They still need the password. Leave blank to skip.",
                wraplength=460,
            ).pack(anchor="w", pady=(8, 8))
            self._user = self._labeled("Polar username", secret=False)
            self._err = ttk.Label(self._body, text=error, foreground="#9f1239", wraplength=460)
            self._err.pack(anchor="w", pady=(8, 8))
            ttk.Button(self._body, text="Start", command=self._on_start).pack(anchor="w", pady=(8, 0))
            self.bind("<Return>", lambda _event: self._on_start())

        def _labeled(self, caption: str, secret: bool = True) -> tk.StringVar:
            ttk.Label(self._body, text=caption).pack(anchor="w")
            var = tk.StringVar()
            ttk.Entry(self._body, textvariable=var, show="*" if secret else "", width=42).pack(anchor="w", pady=(0, 8), fill="x")
            return var

        def _on_start(self) -> None:
            if self._starting:
                return
            self._starting = True
            try:
                save_password(self._pw.get(), self._confirm.get())
                user = self._user.get().strip()
                if user:
                    if not valid_username(user):
                        raise ValueError("Use 3–32 letters, numbers, underscores, or hyphens.")
                    link_username(user)
                record = load_record()
                if not record:
                    raise ValueError(f"No password is saved at {auth_path()}")
            except ValueError as exc:
                self._starting = False
                self._err.configure(text=str(exc))
                return
            self._listen(record)

        def _listen(self, record: dict) -> None:
            self._status("Starting…")

            def worker() -> None:
                try:
                    server = open_remote(record)
                    info = describe_remote(server)
                except Exception as exc:
                    self.after(0, lambda e=exc: self._fail(e))
                    return
                self.after(0, lambda s=server, i=info: self._running(s, i))
                try:
                    server.serve_forever()
                except Exception as exc:
                    self.after(0, lambda e=exc: self._fail(e))

            threading.Thread(target=worker, name="polar-remote", daemon=True).start()

        def _fail(self, exc: BaseException) -> None:
            self._starting = False
            self.server = None
            self._setup(str(exc))

        def _running(self, server, info: dict) -> None:
            self.server = server
            self._starting = False
            self.unbind("<Return>")
            self._clear()
            ttk.Label(self._body, text="Polar Remote Proxy is running.", font=("Segoe UI", 12, "bold")).pack(anchor="w")
            ttk.Label(
                self._body,
                text="The desktop is not shared until Polar sends the password.",
                wraplength=460,
            ).pack(anchor="w", pady=(6, 6))
            ttk.Label(self._body, text="On the other PC, open Polar → Remote Desktop, log in, and enter:").pack(anchor="w")
            for host in info["hosts"]:
                ttk.Label(self._body, text=f"Host: {host}", font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=(8, 0))
            ttk.Label(self._body, text="Password: the one you set for this app").pack(anchor="w", padx=(8, 0), pady=(0, 8))
            linked = info["linked"]
            if linked:
                ttk.Label(
                    self._body,
                    text="Linked Polar accounts: " + ", ".join(linked),
                    wraplength=460,
                ).pack(anchor="w", pady=(0, 8))
                ttk.Label(
                    self._body,
                    text="The viewer must be logged in as one of those accounts, and must send this password.",
                    wraplength=460,
                ).pack(anchor="w", pady=(0, 8))
            else:
                ttk.Label(
                    self._body,
                    text="No Polar account is linked. The connection password is enough for this app.",
                    wraplength=460,
                ).pack(anchor="w", pady=(0, 8))
            ttk.Label(self._body, text="Leave this window open. Closing it stops the share.", wraplength=460).pack(anchor="w", pady=(0, 12))
            row = ttk.Frame(self._body)
            row.pack(anchor="w")
            ttk.Button(row, text="Change password", command=self._change_password).pack(side="left", padx=(0, 8))
            ttk.Button(row, text="Link account", command=self._link).pack(side="left", padx=(0, 8))
            if linked:
                ttk.Button(row, text="Unlink", command=self._unlink).pack(side="left", padx=(0, 8))
            ttk.Button(row, text="Stop", command=self._close).pack(side="left")

        def _change_password(self) -> None:
            value = _pair_dialog(self, "Change password", "New connection password", secret=True)
            if not value:
                return
            try:
                save_password(value[0], value[1])
            except ValueError as exc:
                _note(self, str(exc))
                return
            fresh = load_record()
            if fresh and self.server is not None:
                self.server.record = fresh
            _note(self, "Password saved. Polar has to use the new one.")

        def _link(self) -> None:
            value = _pair_dialog(self, "Link a Polar account", "Polar username", secret=False, confirm=False)
            if not value:
                return
            name = value[0].strip()
            try:
                if not valid_username(name):
                    raise ValueError("Use 3–32 letters, numbers, underscores, or hyphens.")
                link_username(name)
            except ValueError as exc:
                _note(self, str(exc))
                return
            fresh = load_record()
            if fresh and self.server is not None:
                self.server.record = fresh
                self._running(self.server, describe_remote(self.server))

        def _unlink(self) -> None:
            if self.server is None:
                return
            names = allowed_usernames(self.server.record)
            if not names:
                return
            try:
                unlink_username(names[-1])
            except ValueError as exc:
                _note(self, str(exc))
                return
            fresh = load_record()
            if fresh and self.server is not None:
                self.server.record = fresh
                self._running(self.server, describe_remote(self.server))

        def _close(self) -> None:
            server = self.server
            self.server = None

            def stop() -> None:
                if server is None:
                    return
                try:
                    server.capture.stop()
                except Exception:
                    pass
                try:
                    server.shutdown()
                except Exception:
                    pass

            threading.Thread(target=stop, daemon=True).start()
            self.destroy()

    App().mainloop()


def _note(parent, text: str) -> None:
    import tkinter as tk
    from tkinter import messagebox

    messagebox.showinfo("Polar Remote Proxy", text, parent=parent)


def _pair_dialog(parent, title: str, label: str, secret: bool, confirm: bool = True):
    import tkinter as tk
    from tkinter import ttk

    box = tk.Toplevel(parent)
    box.title(title)
    box.transient(parent)
    box.grab_set()
    box.resizable(False, False)
    frame = ttk.Frame(box, padding=16)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text=label).pack(anchor="w")
    first = tk.StringVar()
    ttk.Entry(frame, textvariable=first, show="*" if secret else "", width=36).pack(anchor="w", pady=(0, 8))
    second = tk.StringVar()
    if confirm:
        ttk.Label(frame, text="Confirm").pack(anchor="w")
        ttk.Entry(frame, textvariable=second, show="*", width=36).pack(anchor="w", pady=(0, 8))
    picked: dict = {"value": None}

    def ok() -> None:
        picked["value"] = (first.get(), second.get())
        box.destroy()

    def cancel() -> None:
        box.destroy()

    row = ttk.Frame(frame)
    row.pack(anchor="e", pady=(8, 0))
    ttk.Button(row, text="Cancel", command=cancel).pack(side="right")
    ttk.Button(row, text="Save", command=ok).pack(side="right", padx=(0, 8))
    box.bind("<Escape>", lambda _event: cancel())
    box.wait_window()
    return picked["value"]


def main() -> None:
    _bind_log()
    try:
        import multiprocessing

        multiprocessing.freeze_support()
    except Exception:
        pass
    try:
        launch()
    except Exception:
        import traceback

        traceback.print_exc()
        try:
            import tkinter as tk
            from tkinter import messagebox

            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("Polar Remote Proxy", traceback.format_exc()[-1500:])
            root.destroy()
        except Exception:
            pass
        raise SystemExit(1)


if __name__ == "__main__":
    main()
