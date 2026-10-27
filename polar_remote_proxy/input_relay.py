"""Best-effort mouse and keyboard relay. Viewing still works if this cannot load."""

from __future__ import annotations

_mouse = None
_keyboard = None
_button = None
_key = None
_ready = False
_failed = False


def _load() -> bool:
    global _mouse, _keyboard, _button, _key, _ready, _failed
    if _ready:
        return True
    if _failed:
        return False
    try:
        from pynput.keyboard import Controller as Keyboard
        from pynput.keyboard import Key
        from pynput.mouse import Button
        from pynput.mouse import Controller as Mouse

        _mouse = Mouse()
        _keyboard = Keyboard()
        _button = Button
        _key = Key
        _ready = True
        return True
    except Exception:
        _failed = True
        return False


def _clamp(value: float) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0.0
    if value < 0:
        return 0.0
    if value > 1:
        return 1.0
    return value


def handle(msg: dict, screen_w: int, screen_h: int) -> None:
    try:
        _handle(msg, screen_w, screen_h)
    except Exception:
        return


def _handle(msg: dict, screen_w: int, screen_h: int) -> None:
    if not _load():
        return
    kind = msg.get("type")
    if kind == "mouse":
        x = int(_clamp(msg.get("x", 0)) * max(screen_w - 1, 1))
        y = int(_clamp(msg.get("y", 0)) * max(screen_h - 1, 1))
        _mouse.position = (x, y)
        button = _button.left
        which = int(msg.get("button") or 0)
        if which == 1:
            button = _button.middle
        elif which == 2:
            button = _button.right
        action = msg.get("action")
        if action == "down":
            _mouse.press(button)
        elif action == "up":
            _mouse.release(button)
        elif action == "click":
            _mouse.click(button)
    elif kind == "wheel":
        dy = int(msg.get("dy") or 0)
        dx = int(msg.get("dx") or 0)
        _mouse.scroll(dx / 120 if abs(dx) > 20 else dx, -dy / 120 if abs(dy) > 20 else -dy)
    elif kind == "key":
        key = _map_key(str(msg.get("key") or ""))
        if key is None:
            return
        if msg.get("action") == "up":
            _keyboard.release(key)
        else:
            _keyboard.press(key)


def _map_key(name: str):
    if not name or len(name) > 32:
        return None
    special = {
        "Enter": _key.enter,
        "Backspace": _key.backspace,
        "Tab": _key.tab,
        "Escape": _key.esc,
        " ": _key.space,
        "Delete": _key.delete,
        "ArrowUp": _key.up,
        "ArrowDown": _key.down,
        "ArrowLeft": _key.left,
        "ArrowRight": _key.right,
        "Shift": _key.shift,
        "Control": _key.ctrl,
        "Alt": _key.alt,
        "Meta": _key.cmd,
        "Home": _key.home,
        "End": _key.end,
        "PageUp": _key.page_up,
        "PageDown": _key.page_down,
    }
    if name in special:
        return special[name]
    if len(name) == 1:
        return name
    return None
