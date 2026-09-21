import tempfile
import unittest
from pathlib import Path

import numpy as np
import yaml

from app.config.stadiums import save_stadium_yaml
from app.domain.stadium import Stadium
from app.pipeline.calibrate import estimate_grass_hsv, propose_from_frame


class GrassHsvEstimationTests(unittest.TestCase):
    def test_synthetic_green_frame_yields_green_hsv_bounds(self) -> None:
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        # BGR green pitch in the lower-middle sample window.
        frame[120:220, 40:280] = (40, 180, 40)

        hsv = estimate_grass_hsv(frame)

        self.assertGreaterEqual(hsv.lower[0], 30)
        self.assertLessEqual(hsv.lower[0], 70)
        self.assertGreaterEqual(hsv.upper[0], 50)
        self.assertLessEqual(hsv.upper[0], 90)
        self.assertLess(hsv.lower[0], hsv.upper[0])
        self.assertGreater(hsv.upper[1], hsv.lower[1])
        self.assertGreater(hsv.upper[2], hsv.lower[2])

    def test_non_green_frame_falls_back_to_defaults(self) -> None:
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        frame[:, :] = (210, 40, 40)  # BGR blue, not grass.
        hsv = estimate_grass_hsv(frame)
        self.assertEqual(hsv.lower, [28, 25, 30])
        self.assertEqual(hsv.upper, [85, 255, 255])

    def test_propose_from_frame_returns_camera_and_previews(self) -> None:
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        frame[120:220, 40:280] = (40, 180, 40)
        camera, previews = propose_from_frame(frame)
        self.assertEqual(camera.id, "default")
        self.assertEqual(camera.led_band.min_height_px, 22)
        self.assertIn("scoreboard_jpeg_b64", previews)
        self.assertIn("grass_mask_jpeg_b64", previews)


class SaveStadiumYamlTests(unittest.TestCase):
    def test_roundtrip_yaml(self) -> None:
        from app.config.stadiums import load_stadium_profile

        template = load_stadium_profile("ligaecuabet")
        stadium = Stadium(
            id="calib_test",
            nombre="Calib Test",
            pais="Ecuador",
            default_camera=template.id,
            camera=template,
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = save_stadium_yaml(stadium, directory=Path(tmp))
            loaded = Stadium.model_validate(
                yaml.safe_load(path.read_text(encoding="utf-8"))
            )
        self.assertEqual(loaded.id, "calib_test")
        self.assertEqual(loaded.camera.grass_hsv.lower, template.grass_hsv.lower)


if __name__ == "__main__":
    unittest.main()
