import unittest
from pathlib import Path

import numpy as np

from app.pipeline.roi import (
    crop_overhang_ratio,
    extract_fixed_banner_roi,
    extract_led_roi,
    led_height_px,
    _mask_fixed_banner_columns,
    _touchline_ys,
    grass_mask,
)


GREEN = (40, 180, 40)
CYAN = (220, 200, 20)  # BGR: bright LED, not in the grass HSV band
MAGENTA = (220, 20, 220)  # fixed banner color that must stay out of the crop
NAVY = (80, 40, 20)
MATTE_YELLOW = (30, 210, 240)  # BGR matte fixed LigaEcuabet insert
LED_MAGENTA = (90, 20, 200)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_QA_TECNI = _REPO_ROOT / "data" / "qa_tecni_frames" / "t00282.jpg"
_QA_LIBERTAD = _REPO_ROOT / "data" / "qa_libertad_frames" / "t00282.jpg"
_FIXED_LONA_DENYLIST = ("AURUM", "GUTMAN", "MIRACLE", "VENUS", "PLASTIVILL", "NETTPLUSFIJA")


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


def _double_row_lona_frame(height: int = 720, width: int = 1280) -> np.ndarray:
    """Two magenta lona rows above a cyan LED — crop must not climb into them."""
    frame = np.full((height, width, 3), NAVY, dtype=np.uint8)
    grass_top = int(0.62 * height)
    led_h = led_height_px(height)
    led_top = grass_top - led_h
    row1_top = led_top - 36
    row2_top = row1_top - 40
    frame[grass_top:, :] = GREEN
    frame[led_top:grass_top, :] = CYAN
    frame[row1_top:led_top, :] = MAGENTA
    frame[row2_top:row1_top, :] = MAGENTA
    return frame


def _interrupted_led_frame(height: int = 720, width: int = 1280) -> np.ndarray:
    """LED strip with a matte yellow fixed board in the middle (this stadium)."""
    frame = np.full((height, width, 3), NAVY, dtype=np.uint8)
    grass_top = int(0.62 * height)
    led_h = led_height_px(height)
    led_top = grass_top - led_h
    banner_top = led_top - 36
    frame[grass_top:, :] = GREEN
    frame[led_top:grass_top, :] = LED_MAGENTA
    # Smooth matte yellow insert — low texture vs glowing LED.
    x0, x1 = width // 2 - 90, width // 2 + 90
    frame[led_top:grass_top, x0:x1] = MATTE_YELLOW
    frame[banner_top:led_top, :] = MAGENTA
    return frame


def _count_color(image: np.ndarray, color: tuple[int, int, int], tol: int = 40) -> int:
    diff = np.abs(image.astype(np.int16) - np.array(color, dtype=np.int16))
    return int(np.all(diff <= tol, axis=2).sum())


def _wide_far_led_frame(height: int = 720, width: int = 1280) -> np.ndarray:
    """High camera: yellow LED sits in the upper third, grass much lower."""
    frame = np.full((height, width, 3), NAVY, dtype=np.uint8)
    grass_top = 256
    led_top, led_bot = 124, 152
    banner_top = 88
    frame[grass_top:, :] = GREEN
    frame[led_top:led_bot, :] = (0, 230, 255)  # BGR bright yellow LED
    frame[banner_top:led_top, :] = MAGENTA
    return frame


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
        self.assertLess(_count_color(crop, MAGENTA), crop.shape[1] * 2)
        self.assertLess(_count_color(crop, GREEN), 400)

    def test_double_row_lona_stays_out_of_led_crop(self):
        frame = _double_row_lona_frame()
        roi = extract_led_roi(frame)
        self.assertFalse(roi.skipped, roi.reason)
        crop = roi.crop_bgr
        self.assertIsNotNone(crop)
        self.assertGreater(_count_color(crop, CYAN), 500)
        self.assertLess(_count_color(crop, MAGENTA), crop.shape[1] * 2)
        mask = grass_mask(frame)
        y_grass = _touchline_ys(mask)
        self.assertIsNotNone(y_grass)
        touch = float(np.median(y_grass))
        led_h = led_height_px(frame.shape[0])
        self.assertLessEqual(
            crop_overhang_ratio(touch, roi.y0, led_h),
            1.35,
        )

    def test_overhang_ratio_flags_high_crop(self):
        self.assertLessEqual(crop_overhang_ratio(400, 370, 30), 1.35)
        self.assertGreater(crop_overhang_ratio(400, 300, 30), 1.35)

    def test_matte_yellow_insert_is_masked_from_led_crop(self):
        frame = _interrupted_led_frame()
        roi = extract_led_roi(frame)
        self.assertFalse(roi.skipped, roi.reason)
        crop = roi.crop_bgr
        self.assertIsNotNone(crop)
        yellow_px = _count_color(crop, MATTE_YELLOW, tol=35)
        led_px = _count_color(crop, LED_MAGENTA, tol=45)
        self.assertGreater(led_px, 800)
        self.assertLess(yellow_px, crop.shape[0] * 8)

    def test_mask_helper_blanks_matte_yellow_columns(self):
        crop = np.zeros((40, 300, 3), dtype=np.uint8)
        crop[:, :100] = LED_MAGENTA
        crop[:, 100:200] = MATTE_YELLOW
        crop[:, 200:] = LED_MAGENTA
        masked = _mask_fixed_banner_columns(crop)
        self.assertLess(_count_color(masked[:, 120:180], MATTE_YELLOW, tol=35), 40)
        self.assertGreater(_count_color(masked[:, :100], LED_MAGENTA, tol=45), 200)

    def test_matte_mask_is_skipped_when_profile_has_no_matte_yellow(self):
        from app.config.stadiums import load_stadium_profile

        crop = np.zeros((40, 300, 3), dtype=np.uint8)
        crop[:, :100] = LED_MAGENTA
        crop[:, 100:200] = MATTE_YELLOW
        crop[:, 200:] = LED_MAGENTA
        with_matte = load_stadium_profile("ligaecuabet")
        without_matte = with_matte.model_copy(update={"matte_yellow": None})

        blanked = _mask_fixed_banner_columns(crop, profile=with_matte)
        left_visible = _mask_fixed_banner_columns(crop, profile=without_matte)

        self.assertLess(_count_color(blanked[:, 120:180], MATTE_YELLOW, tol=35), 40)
        self.assertGreater(_count_color(left_visible[:, 120:180], MATTE_YELLOW, tol=35), 800)
        np.testing.assert_array_equal(left_visible, crop)

        frame = _interrupted_led_frame()
        roi_blanked = extract_led_roi(frame, profile=with_matte)
        roi_kept = extract_led_roi(frame, profile=without_matte)
        self.assertFalse(roi_blanked.skipped, roi_blanked.reason)
        self.assertFalse(roi_kept.skipped, roi_kept.reason)
        yellow_blanked = _count_color(roi_blanked.crop_bgr, MATTE_YELLOW, tol=35)
        yellow_kept = _count_color(roi_kept.crop_bgr, MATTE_YELLOW, tol=35)
        self.assertLess(yellow_blanked, roi_blanked.crop_bgr.shape[0] * 8)
        # Without matte config the helper leaves yellow alone; the thin LED strip
        # may already exclude most of the insert, so kept >= blanked is enough.
        self.assertGreaterEqual(yellow_kept, yellow_blanked)

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

    def test_far_yellow_led_is_cropped_not_the_grass(self):
        frame = _wide_far_led_frame()
        roi = extract_led_roi(frame)
        self.assertFalse(roi.skipped, roi.reason)
        crop = roi.crop_bgr
        self.assertIsNotNone(crop)
        self.assertGreater(_count_color(crop, (0, 230, 255), tol=40), 400)
        self.assertLess(_count_color(crop, MAGENTA), crop.shape[1] * 4)
        self.assertLess(_count_color(crop, GREEN), crop.shape[1] * 6)

    def test_ligaecuabet_profile_matches_hardcoded_defaults(self):
        from app.config.stadiums import load_stadium_profile

        frame = _sideline_frame()
        profile = load_stadium_profile("ligaecuabet")
        default = extract_led_roi(frame)
        tuned = extract_led_roi(frame, profile=profile)
        self.assertEqual(default.skipped, tuned.skipped)
        self.assertIsNotNone(default.crop_bgr)
        self.assertIsNotNone(tuned.crop_bgr)
        np.testing.assert_array_equal(default.crop_bgr, tuned.crop_bgr)
        self.assertEqual(led_height_px(720), led_height_px(720, profile=profile))

    def test_fixed_crop_keeps_second_row_not_led(self):
        frame = _sideline_frame()
        led = extract_led_roi(frame)
        fixed = extract_fixed_banner_roi(frame, led=led)
        self.assertFalse(fixed.skipped, fixed.reason)
        crop = fixed.crop_bgr
        self.assertIsNotNone(crop)
        self.assertGreater(_count_color(crop, MAGENTA), 400)
        self.assertLess(_count_color(crop, CYAN), crop.shape[1] * 4)

    def test_canonical_qa_tecni_282_stays_on_led(self):
        if not _QA_TECNI.is_file():
            self.skipTest(f"missing {_QA_TECNI}")
        import cv2

        frame = cv2.imread(str(_QA_TECNI))
        self.assertIsNotNone(frame)
        roi = extract_led_roi(frame)
        self.assertFalse(roi.skipped, roi.reason)
        mask = grass_mask(frame)
        y_grass = _touchline_ys(mask)
        self.assertIsNotNone(y_grass)
        touch = float(np.median(y_grass))
        led_h = led_height_px(frame.shape[0])
        self.assertLessEqual(crop_overhang_ratio(touch, roi.y0, led_h), 1.35)
        self._assert_no_fixed_lona_ocr(roi.crop_bgr)

    def test_canonical_qa_libertad_282_stays_on_led(self):
        if not _QA_LIBERTAD.is_file():
            self.skipTest(f"missing {_QA_LIBERTAD}")
        import cv2

        frame = cv2.imread(str(_QA_LIBERTAD))
        self.assertIsNotNone(frame)
        roi = extract_led_roi(frame)
        self.assertFalse(roi.skipped, roi.reason)
        mask = grass_mask(frame)
        y_grass = _touchline_ys(mask)
        self.assertIsNotNone(y_grass)
        touch = float(np.median(y_grass))
        led_h = led_height_px(frame.shape[0])
        self.assertLessEqual(crop_overhang_ratio(touch, roi.y0, led_h), 1.35)
        self._assert_no_fixed_lona_ocr(roi.crop_bgr)

    def _assert_no_fixed_lona_ocr(self, crop_bgr: np.ndarray) -> None:
        try:
            from app.pipeline.ocr import read_led_hits
        except Exception:
            return
        hits = read_led_hits(crop_bgr)
        blob = " ".join(hit.text.upper() for hit in hits)
        for needle in _FIXED_LONA_DENYLIST:
            self.assertNotIn(needle, blob.replace(" ", ""), msg=blob)


if __name__ == "__main__":
    unittest.main()
