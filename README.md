# Polar Remote Proxy

Home-PC app for [Polar](https://github.com/I-Am-Him-AI/Game-website) Remote Desktop.

It runs on the computer you want to view. You set a connection password. The Polar tab on the other PC sends that password and then receives the screen. Nothing is sent until the password matches. No cloud account is required.

## Start

Python 3.10 or newer.

```bash
python start.py
```

On Windows you can double-click `start.bat`. That runs the same command.

The first start asks for a password (at least 4 characters). It is saved as an scrypt hash in `%USERPROFILE%\.polar-remote-proxy\auth.json` (or `~/.polar-remote-proxy/auth.json`). The file is not the password itself.

The window then prints a host such as `192.168.1.20:8765`. Leave the window open.

Change the password later:

```bash
python start.py --set-password
```

Windows may ask to allow Python on private networks. Allow it on the home network so the other PC can connect. Both computers should be on that network, or TCP port 8765 must be forwarded to the home PC.

## Connect from Polar

1. On the other PC, open Polar and click **Remote Desktop** in the left sidebar (same tab, Polar’s address does not change).
2. Host: the address this app printed, for example `192.168.1.20:8765`.
3. Password: the password you set here.
4. Connect.

| What you see | Meaning |
| --- | --- |
| Waiting | Polar is reaching the home PC or waiting for the first frame. |
| Connected | Password accepted. The desktop is on screen. Click it to move the mouse and type. |
| Wrong password | The home PC is up and rejected the password. |
| Home offline | Polar could not reach Polar Remote Proxy. Start this app and check the host. |

The sidebar entry is hidden on a phone.

## What is exposed

- `GET /health` answers `{"ok":true,"service":"polar-remote-proxy"}`. It does not include the screen.
- The screen and keyboard/mouse relay use the WebSocket at `/ws`, and only after a correct password.
- Any other request is rejected with `password_required` and no image.
- Wrong passwords are rejected and are not logged.

Mouse and keyboard need the optional `pynput` package (`python start.py` installs it). If it cannot load, the screen still relays.

If this machine has no display, the app still accepts the password and sends a labeled placeholder instead of a screen. A normal Windows desktop sends the real screen.

## Layout

```
python start.py
polar_remote_proxy/    listener, capture, password check
```
