import unittest

import numpy as np

from app.pipeline.roi import extract_led_roi, led_height_px


GREEN = (40, 180, 40)
CYAN = (220, 200, 20)  # BGR: bright LED, not in the grass HSV band
MAGENTA = (220, 20, 220)  # fixed banner color that must stay out of the crop
NAVY = (80, 40, 20)


def _sideline_frame(height: int = 720, width: int = 1280) -> np.ndarray:
    """Synthetic lateral broadcast: stands, magenta banners, cyan LED, grass."""
    frame = np.full((height, width, 3), NAVY, dtype=np.uint8)
    grass_top = int(0.62 * height)
    led_h = led_height_px(height)
    led_top = grass_top - led_h
    banner_top = led_top - 40
    frame[grass_top:, :] = GREEN
    frame[led_top:grass_top, :] = CYAN
    frame[banner_top:led_top, :] = MAGENTA
    return frame


def _count_color(image: np.ndarray, color: tuple[int, int, int], tol: int = 40) -> int:
    diff = np.abs(image.astype(np.int16) - np.array(color, dtype=np.int16))
    return int(np.all(diff <= tol, axis=2).sum())


class RoiTests(unittest.TestCase):
    def test_crop_keeps_led_and_excludes_fixed_banners(self):
        frame = _sideline_frame()
        roi = extract_led_roi(frame)
        self.assertFalse(roi.skipped, roi.reason)
        self.assertIsNotNone(roi.crop_bgr)
        crop = roi.crop_bgr
        self.assertGreater(_count_color(crop, CYAN), 500)
        # One border row of the fixed banner can leak when the LED hugs it;
        # anything larger means the ROI climbed into the lonas.
        self.assertLess(_count_color(crop, MAGENTA), crop.shape[1] * 3)
        self.assertLess(_count_color(crop, GREEN), 400)

    def test_low_grass_is_skipped(self):
        frame = np.full((480, 640, 3), NAVY, dtype=np.uint8)
        roi = extract_led_roi(frame)
        self.assertTrue(roi.skipped)
        self.assertEqual(roi.reason, "low_grass")

    def test_wide_shot_is_skipped(self):
        height, width = 720, 1280
        frame = np.full((height, width, 3), NAVY, dtype=np.uint8)
        frame[int(0.20 * height) :, :] = GREEN
        roi = extract_led_roi(frame)
        self.assertTrue(roi.skipped)
        self.assertEqual(roi.reason, "wide_shot")


if __name__ == "__main__":
    unittest.main()
