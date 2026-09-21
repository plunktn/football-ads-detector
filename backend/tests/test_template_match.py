import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from app.pipeline.brands import match_brand_ids, match_fixed_brand_ids, prepare_brands
from app.pipeline.extract import TemplateHit, detect_fixed_brands, match_logo
from app.schemas import BrandInput


RED = (40, 40, 220)
CYAN = (220, 200, 20)
NAVY = (40, 30, 20)
GREEN = (30, 180, 40)


def _solid(width: int, height: int, color: tuple[int, int, int]) -> np.ndarray:
    return np.full((height, width, 3), color, dtype=np.uint8)


def _crop_with_logo(
    logo: np.ndarray,
    *,
    crop_w: int = 240,
    crop_h: int = 72,
    x: int = 80,
    y: int = 16,
) -> np.ndarray:
    crop = _solid(crop_w, crop_h, NAVY)
    h, w = logo.shape[:2]
    crop[y : y + h, x : x + w] = logo
    return crop


class MatchLogoTests(unittest.TestCase):
    def test_matching_solid_logo_is_a_hit(self):
        logo = _solid(48, 28, RED)
        crop = _crop_with_logo(logo)
        hit = match_logo(crop, logo)
        self.assertIsInstance(hit, TemplateHit)
        self.assertGreaterEqual(hit.score, 0.70)
        x, y, w, h = hit.bbox
        self.assertGreater(w, 0)
        self.assertGreater(h, 0)
        crop_area = crop.shape[0] * crop.shape[1]
        self.assertAlmostEqual(hit.visible_area_ratio, (w * h) / crop_area, places=6)
        self.assertLessEqual(abs(x - 80), 4)
        self.assertLessEqual(abs(y - 16), 4)

    def test_wrong_template_is_a_miss(self):
        logo = _solid(48, 28, RED)
        crop = _crop_with_logo(logo)
        wrong = _solid(48, 28, GREEN)
        self.assertIsNone(match_logo(crop, wrong))

    def test_threshold_is_configurable(self):
        logo = _solid(48, 28, RED)
        crop = _crop_with_logo(logo)
        self.assertIsNone(match_logo(crop, logo, score_threshold=1.01))


class DetectFixedBrandsTests(unittest.TestCase):
    def test_returns_brand_id_score_and_visible_area(self):
        logo = _solid(48, 28, RED)
        crop = _crop_with_logo(logo)
        brands = [
            (
                BrandInput(id="ligaecuabet", name="LigaEcuabet"),
                logo,
            ),
            (
                BrandInput(id="other", name="Other"),
                _solid(48, 28, GREEN),
            ),
            (
                BrandInput(id="no-logo", name="No Logo"),
                None,
            ),
        ]
        hits = detect_fixed_brands(crop, brands)
        self.assertEqual([item["brand_id"] for item in hits], ["ligaecuabet"])
        self.assertGreaterEqual(hits[0]["score"], 0.70)
        self.assertGreater(hits[0]["visible_area_ratio"], 0.0)

    def test_match_fixed_brand_ids_from_logo_path(self):
        logo = _solid(48, 28, CYAN)
        crop = _crop_with_logo(logo)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "logo.png"
            cv2.imwrite(str(path), logo)
            brand = BrandInput(id="fixed", name="Fixed Print", logo_path=str(path))
            self.assertEqual(match_fixed_brand_ids(crop, [brand]), {"fixed"})

    def test_led_ocr_path_still_matches_without_logos(self):
        brands = prepare_brands(
            [BrandInput(id="ecuabet", name="ECUABET")]
        )
        hits = match_brand_ids("ECUABET ECUABET", brands)
        self.assertEqual(hits, {"ecuabet"})
        self.assertEqual(
            match_fixed_brand_ids(_solid(80, 32, NAVY), [BrandInput(id="ecuabet", name="ECUABET")]),
            set(),
        )


if __name__ == "__main__":
    unittest.main()
