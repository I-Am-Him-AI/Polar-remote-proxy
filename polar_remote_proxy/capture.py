"""Screen grabber. Falls back to a labeled test frame when no display is available."""

from __future__ import annotations

import io
import threading
import time


class Capture:
    def __init__(self, max_width: int = 1280, quality: int = 55, fps: float = 8.0) -> None:
        self.max_width = max_width
        self.quality = quality
        self.interval = 1.0 / max(fps, 1.0)
        self.jpeg = b""
        self.width = 0
        self.height = 0
        self.screen_width = 0
        self.screen_height = 0
        self.mode = "starting"
        self.lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="polar-capture", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def snapshot(self) -> tuple[bytes, int, int]:
        with self.lock:
            return self.jpeg, self.screen_width, self.screen_height

    def _loop(self) -> None:
        sct = None
        try:
            import mss

            sct = mss.MSS()
        except Exception:
            sct = None
        while not self._stop.is_set():
            jpeg, w, h, sw, sh, mode = self._grab(sct)
            with self.lock:
                self.jpeg = jpeg
                self.width = w
                self.height = h
                self.screen_width = sw
                self.screen_height = sh
                self.mode = mode
            self._stop.wait(self.interval)
        if sct is not None:
            try:
                sct.close()
            except Exception:
                pass

    def _grab(self, sct) -> tuple[bytes, int, int, int, int, str]:
        if sct is not None:
            try:
                from PIL import Image

                mon = sct.monitors[1]
                raw = sct.grab(mon)
                im = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
                sw, sh = im.size
                if im.width > self.max_width:
                    nh = max(1, int(im.height * (self.max_width / im.width)))
                    im = im.resize((self.max_width, nh), Image.BILINEAR)
                return (*_jpeg(im, self.quality), sw, sh, "screen")
            except Exception:
                pass
        im, sw, sh = _fallback_image()
        return (*_jpeg(im, self.quality), sw, sh, "fallback")


def _jpeg(im, quality: int) -> tuple[bytes, int, int]:
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=quality)
    return buf.getvalue(), im.width, im.height


def _fallback_image():
    from PIL import Image, ImageDraw

    w, h = 960, 540
    im = Image.new("RGB", (w, h), (231, 240, 251))
    draw = ImageDraw.Draw(im)
    draw.rounded_rectangle((36, 36, w - 36, h - 36), 20, fill=(255, 255, 255), outline=(197, 214, 232))
    draw.text((64, 64), "Polar Remote Proxy", fill=(10, 10, 10))
    draw.text((64, 98), "No display was captured on this machine.", fill=(28, 43, 58))
    draw.text((64, 128), "On a normal home PC this area is the real screen.", fill=(90, 111, 134))
    x = int(time.time() * 90) % 680
    draw.rounded_rectangle((64 + x, 190, 64 + x + 90, 228), 8, fill=(26, 79, 214))
    return im, w, h
