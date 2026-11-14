"""Capture pacing and encode stay well under the old one-second frame gap."""

from __future__ import annotations

import time
import unittest

from PIL import Image

from polar_remote_proxy.capture import _jpeg, fit_width, pace_delay


class CapturePaceTest(unittest.TestCase):
    def test_slow_grab_does_not_add_another_interval(self) -> None:
        self.assertEqual(pace_delay(0.4, 1 / 30), 0.0)

    def test_fast_grab_waits_only_the_remainder(self) -> None:
        delay = pace_delay(0.01, 0.033)
        self.assertGreater(delay, 0.02)
        self.assertLess(delay, 0.025)

    def test_fit_and_jpeg_finish_quickly(self) -> None:
        im = Image.new("RGB", (1920, 1080), (20, 40, 80))
        started = time.perf_counter()
        fitted = fit_width(im, 1280)
        jpeg, width, height = _jpeg(fitted, 46)
        elapsed = time.perf_counter() - started
        self.assertEqual(width, 1280)
        self.assertLess(height, 1080)
        self.assertTrue(jpeg.startswith(b"\xff\xd8"))
        self.assertLess(elapsed, 0.45)


if __name__ == "__main__":
    unittest.main()
