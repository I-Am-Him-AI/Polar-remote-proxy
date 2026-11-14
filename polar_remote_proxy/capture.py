"""Screen grabber. Falls back to a labeled test frame when no display is available.

The grab, scale, and JPEG encode stay on this thread. A short budget keeps a
new frame from waiting out an extra full interval after a slow grab.
"""

from __future__ import annotations

import io
import sys
import threading
import time

try:
    from PIL import Image

    _BOX = Image.Resampling.BOX
except Exception:  # pragma: no cover - Pillow is required at runtime
    Image = None
    _BOX = 0


class _POINT:
    """Filled in on Windows. Defined here so the hot path does not rebuild it."""


if sys.platform == "win32":
    import ctypes

    class _POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def pace_delay(elapsed: float, interval: float) -> float:
    """How long to wait so frames are paced without stacking delay on a slow grab."""
    remain = interval - elapsed
    if remain <= 0:
        return 0.0
    return remain


class Capture:
    def __init__(self, max_width: int = 1280, quality: int = 46, fps: float = 30.0) -> None:
        self.max_width = max_width
        self.quality = quality
        self.interval = 1.0 / max(fps, 1.0)
        self.jpeg = b""
        self.width = 0
        self.height = 0
        self.screen_width = 0
        self.screen_height = 0
        self.cursor: tuple[float, float] | None = None
        self.mode = "starting"
        self.lock = threading.Lock()
        self._stop = threading.Event()
        self._sig = b""
        self._thread = threading.Thread(target=self._loop, name="polar-capture", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def screen_size(self) -> tuple[int, int]:
        with self.lock:
            return self.screen_width, self.screen_height

    def snapshot(self) -> tuple[bytes, int, int, tuple[float, float] | None]:
        with self.lock:
            return self.jpeg, self.screen_width, self.screen_height, self.cursor

    def _loop(self) -> None:
        sct = None
        try:
            import mss

            sct = mss.MSS()
        except Exception:
            sct = None
        while not self._stop.is_set():
            started = time.perf_counter()
            jpeg, w, h, sw, sh, cursor, mode = self._grab(sct)
            with self.lock:
                self.jpeg = jpeg
                self.width = w
                self.height = h
                self.screen_width = sw
                self.screen_height = sh
                self.cursor = cursor
                self.mode = mode
            delay = pace_delay(time.perf_counter() - started, self.interval)
            if delay > 0 and self._stop.wait(delay):
                break
        if sct is not None:
            try:
                sct.close()
            except Exception:
                pass

    def _grab(self, sct) -> tuple[bytes, int, int, int, int, tuple[float, float] | None, str]:
        if sct is not None and Image is not None:
            try:
                mon = sct.monitors[1]
                raw = sct.grab(mon)
                sw, sh = raw.size
                sig = _sample(raw.bgra)
                cursor = _cursor_norm(int(mon.get("left", 0)), int(mon.get("top", 0)), sw, sh)
                if sig == self._sig and self.jpeg:
                    return self.jpeg, self.width, self.height, sw, sh, cursor, "screen"
                im = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
                im = fit_width(im, self.max_width)
                jpeg, w, h = _jpeg(im, self.quality)
                self._sig = sig
                return jpeg, w, h, sw, sh, cursor, "screen"
            except Exception:
                pass
        im, sw, sh = _fallback_image()
        cursor = _cursor_norm(0, 0, sw, sh)
        jpeg, w, h = _jpeg(im, self.quality)
        return jpeg, w, h, sw, sh, cursor, "fallback"


def fit_width(im, max_width: int):
    if im.width <= max_width:
        return im
    nh = max(1, int(im.height * (max_width / im.width)))
    return im.resize((max_width, nh), _BOX)


def _jpeg(im, quality: int) -> tuple[bytes, int, int]:
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=quality, optimize=False, subsampling=2)
    return buf.getvalue(), im.width, im.height


def _sample(blob: bytes) -> bytes:
    step = max(1, len(blob) // 4096)
    return blob[::step]


def _cursor_norm(origin_x: int, origin_y: int, sw: int, sh: int) -> tuple[float, float] | None:
    """Windows cursor in monitor space. Other hosts draw the pointer in the browser."""
    if sw <= 1 or sh <= 1 or sys.platform != "win32":
        return None
    try:
        import ctypes

        pt = _POINT()
        if not ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
            return None
        x = float(pt.x)
        y = float(pt.y)
    except Exception:
        return None
    nx = (x - origin_x) / float(sw)
    ny = (y - origin_y) / float(sh)
    if nx < -0.02 or ny < -0.02 or nx > 1.02 or ny > 1.02:
        return None
    if nx < 0:
        nx = 0.0
    elif nx > 1:
        nx = 1.0
    if ny < 0:
        ny = 0.0
    elif ny > 1:
        ny = 1.0
    return (round(nx, 4), round(ny, 4))


def _fallback_image():
    from PIL import ImageDraw

    w, h = 960, 540
    im = Image.new("RGB", (w, h), (12, 18, 24))
    draw = ImageDraw.Draw(im)
    draw.rounded_rectangle((36, 36, w - 36, h - 36), 20, fill=(255, 255, 255), outline=(197, 214, 232))
    draw.text((64, 64), "Polar Remote Proxy", fill=(10, 10, 10))
    draw.text((64, 98), "No display was captured on this machine.", fill=(28, 43, 58))
    draw.text((64, 128), "On a normal home PC this area is the real screen.", fill=(90, 111, 134))
    x = int(time.time() * 90) % 680
    draw.rounded_rectangle((64 + x, 190, 64 + x + 90, 228), 8, fill=(26, 79, 214))
    return im, w, h
