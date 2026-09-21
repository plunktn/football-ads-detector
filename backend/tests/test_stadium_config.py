import tempfile
import unittest
from pathlib import Path

import yaml
from pydantic import ValidationError

from app.config.stadiums import DEFAULT_STADIUM_ID, list_stadiums, load_stadium_profile
from app.domain.stadium import CameraProfile, Stadium


class StadiumConfigTests(unittest.TestCase):
    def test_load_ligaecuabet_matches_hardcoded_constants(self) -> None:
        profile = load_stadium_profile("ligaecuabet")

        self.assertEqual(profile.id, "default")
        self.assertEqual(profile.variante, "default")
        self.assertEqual(profile.scoreboard_crop.model_dump(), {"x": 0.0, "y": 0.0, "w": 0.42, "h": 0.22})
        self.assertEqual(profile.grass_hsv.lower, [28, 25, 30])
        self.assertEqual(profile.grass_hsv.upper, [85, 255, 255])
        self.assertAlmostEqual(profile.led_band.top_frac, 0.12)
        self.assertAlmostEqual(profile.led_band.height_frac, 0.035)
        self.assertEqual(profile.led_band.min_height_px, 22)
        self.assertEqual(profile.led_band.max_height_px, 70)
        self.assertAlmostEqual(profile.grass_y_top_frac, 0.28)
        self.assertAlmostEqual(profile.grass_y_bot_frac, 0.92)
        self.assertAlmostEqual(profile.grass_min_ratio, 0.08)

        assert profile.matte_yellow is not None
        self.assertEqual(profile.matte_yellow.hsv.lower, [18, 70, 70])
        self.assertEqual(profile.matte_yellow.hsv.upper, [40, 255, 255])
        self.assertAlmostEqual(profile.matte_yellow.col_frac, 0.55)
        self.assertAlmostEqual(profile.matte_yellow.keep_col_frac, 0.22)
        self.assertAlmostEqual(profile.matte_yellow.texture_max, 14.0)
        self.assertAlmostEqual(profile.matte_yellow.min_led_mean_v, 70.0)

    def test_load_ligaecuabet_has_panel_zones(self) -> None:
        profile = load_stadium_profile("ligaecuabet")

        self.assertGreaterEqual(len(profile.panel_zones), 1)
        zone = profile.panel_zones[0]
        self.assertEqual(zone.id, "led_lateral_main")
        self.assertEqual(zone.posicion, "LATERAL_MAIN")
        self.assertEqual(zone.tipo_panel, "LED_DYNAMIC")
        self.assertEqual(zone.prioridad, 1)

    def test_missing_panel_zones_uses_default(self) -> None:
        profile = load_stadium_profile("example_day")

        ids = [zone.id for zone in profile.panel_zones]
        self.assertIn("led_lateral_main", ids)
        self.assertEqual(profile.panel_zones[0].id, "led_lateral_main")
        self.assertEqual(profile.panel_zones[0].posicion, "LATERAL_MAIN")

    def test_invalid_posicion_fails_validation(self) -> None:
        payload = {
            "id": "default",
            "scoreboard_crop": {"x": 0.0, "y": 0.0, "w": 0.42, "h": 0.22},
            "grass_hsv": {"lower": [28, 25, 30], "upper": [85, 255, 255]},
            "led_band": {
                "top_frac": 0.12,
                "height_frac": 0.035,
                "min_height_px": 28,
                "max_height_px": 90,
            },
            "panel_zones": [
                {
                    "id": "bad_zone",
                    "posicion": "NOT_A_REAL_POSITION",
                    "tipo_panel": "LED_DYNAMIC",
                }
            ],
        }
        with self.assertRaises(ValidationError):
            CameraProfile.model_validate(payload)

    def test_default_stadium_id(self) -> None:
        self.assertEqual(DEFAULT_STADIUM_ID, "ligaecuabet")
        default_profile = load_stadium_profile()
        named_profile = load_stadium_profile("ligaecuabet")
        self.assertEqual(default_profile.model_dump(), named_profile.model_dump())

    def test_list_stadiums_finds_both_yamls(self) -> None:
        ids = list_stadiums()
        self.assertIn("ligaecuabet", ids)
        self.assertIn("example_day", ids)
        self.assertGreaterEqual(len(ids), 2)

    def test_save_stadium_yaml_is_loadable(self) -> None:
        from app.config.stadiums import save_stadium_yaml

        profile = load_stadium_profile("ligaecuabet")
        stadium = Stadium(
            id="saved_tmp",
            nombre="Saved Tmp",
            pais=None,
            default_camera=profile.id,
            camera=profile,
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = save_stadium_yaml(stadium, directory=Path(tmp))
            loaded = Stadium.model_validate(
                yaml.safe_load(path.read_text(encoding="utf-8"))
            )
        self.assertEqual(loaded.nombre, "Saved Tmp")
        self.assertEqual(loaded.camera.led_band.max_height_px, 70)

    def test_missing_required_field_fails_validation(self) -> None:
        payload = {
            "id": "broken",
            "nombre": "Broken Stadium",
            "camera": {
                "id": "default",
                "scoreboard_crop": {"x": 0.0, "y": 0.0, "w": 0.42, "h": 0.22},
                "grass_hsv": {"lower": [28, 25, 30], "upper": [85, 255, 255]},
                # led_band intentionally omitted
            },
        }
        with self.assertRaises(ValidationError):
            Stadium.model_validate(payload)

    def test_invalid_yaml_file_fails_on_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bad_path = Path(tmp) / "broken.yaml"
            bad_path.write_text(
                yaml.safe_dump(
                    {
                        "id": "broken",
                        "nombre": "Broken",
                        "camera": {"id": "default"},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ValidationError):
                Stadium.model_validate(yaml.safe_load(bad_path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
