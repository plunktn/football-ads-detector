import unittest

import numpy as np

from app.domain.zones import DEFAULT_PANEL_ZONES, PanelZone
from app.pipeline.stages import ShotKind, classify_shot, locate_zones
from tests.test_roi import GREEN, NAVY, _sideline_frame, _wide_far_led_frame


class ShotClassTests(unittest.TestCase):
    def test_sideline_frame_is_wide_led(self):
        self.assertEqual(classify_shot(_sideline_frame()), ShotKind.WIDE_LED)

    def test_touchline_in_upper_third_is_wide(self):
        height, width = 720, 1280
        frame = np.full((height, width, 3), NAVY, dtype=np.uint8)
        frame[int(0.20 * height) :, :] = GREEN
        self.assertEqual(classify_shot(frame), ShotKind.WIDE)

    def test_navy_frame_is_graphic_bumper(self):
        frame = np.full((480, 640, 3), NAVY, dtype=np.uint8)
        self.assertEqual(classify_shot(frame), ShotKind.GRAPHIC_BUMPER)

    def test_faint_grass_is_unknown(self):
        height, width = 480, 640
        frame = np.full((height, width, 3), NAVY, dtype=np.uint8)
        # ~6% grass: below grass_min_ratio (0.08) but not empty.
        frame[height - 30 :, :] = GREEN
        self.assertEqual(classify_shot(frame), ShotKind.UNKNOWN)

    def test_empty_frame_is_unknown(self):
        self.assertEqual(classify_shot(np.zeros((0, 0, 3), dtype=np.uint8)), ShotKind.UNKNOWN)

    def test_behind_goal_is_not_emitted_yet(self):
        self.assertNotEqual(classify_shot(_sideline_frame()), ShotKind.BEHIND_GOAL)

    def test_closeup_has_grass_without_led(self):
        height, width = 720, 1280
        frame = np.full((height, width, 3), NAVY, dtype=np.uint8)
        # Mid/lower grass, no bright emissive band above touchline.
        frame[int(0.55 * height) :, :] = GREEN
        self.assertEqual(classify_shot(frame), ShotKind.CLOSEUP)


class LocateZonesTests(unittest.TestCase):
    def test_wide_led_main_uses_led_roi(self):
        frame = _sideline_frame()
        shot = classify_shot(frame)
        located = locate_zones(frame, None, shot)
        self.assertGreaterEqual(len(located), 1)
        zone, roi = located[0]
        self.assertEqual(zone.posicion, "LATERAL_MAIN")
        self.assertEqual(zone.id, DEFAULT_PANEL_ZONES[0].id)
        self.assertFalse(roi.skipped, roi.reason)

    def test_fixed_second_row_is_located(self):
        frame = _sideline_frame()
        located = locate_zones(
            frame, None, classify_shot(frame), include_fixed=True
        )
        kinds = {zone.tipo_panel for zone, _roi in located}
        self.assertIn("LED_DYNAMIC", kinds)
        self.assertIn("FIXED_PRINT", kinds)

    def test_fixed_second_row_skipped_by_default(self):
        frame = _sideline_frame()
        located = locate_zones(frame, None, classify_shot(frame))
        kinds = {zone.tipo_panel for zone, _roi in located}
        self.assertIn("LED_DYNAMIC", kinds)
        self.assertNotIn("FIXED_PRINT", kinds)

    def test_wide_closeup_and_graphic_return_empty(self):
        height, width = 720, 1280
        wide = np.full((height, width, 3), NAVY, dtype=np.uint8)
        wide[int(0.20 * height) :, :] = GREEN
        self.assertEqual(locate_zones(wide, None, ShotKind.WIDE), [])

        graphic = np.full((480, 640, 3), NAVY, dtype=np.uint8)
        self.assertEqual(locate_zones(graphic, None, ShotKind.GRAPHIC_BUMPER), [])
        self.assertEqual(locate_zones(graphic, None, ShotKind.CLOSEUP), [])

    def test_legacy_lateral_alias_still_locates(self):
        frame = _sideline_frame()
        located = locate_zones(frame, None, ShotKind.LATERAL)
        self.assertGreaterEqual(len(located), 1)

    def test_other_positions_are_stubs(self):
        frame = _sideline_frame()
        from app.config.stadiums import load_stadium_profile

        profile = load_stadium_profile("ligaecuabet")
        extra = PanelZone(
            id="behind_goal_left",
            posicion="BEHIND_GOAL_LEFT",
            tipo_panel="LED_DYNAMIC",
            prioridad=2,
        )
        profile = profile.model_copy(
            update={"panel_zones": list(profile.panel_zones) + [extra]}
        )
        located = locate_zones(frame, profile, ShotKind.WIDE_LED)
        self.assertFalse(any(zone.id == "behind_goal_left" for zone, _roi in located))
        self.assertTrue(
            all(zone.posicion == "LATERAL_MAIN" for zone, _roi in located)
        )
        located_fixed = locate_zones(
            frame, profile, ShotKind.WIDE_LED, include_fixed=True
        )
        self.assertTrue(
            all(
                zone.posicion in {"LATERAL_MAIN", "FIXED_BOARD_MIDFIELD"}
                for zone, _roi in located_fixed
            )
        )

    def test_empty_panel_zones_uses_virtual_lateral_main(self):
        from app.config.stadiums import load_stadium_profile

        frame = _sideline_frame()
        profile = load_stadium_profile("ligaecuabet").model_copy(update={"panel_zones": []})
        located = locate_zones(frame, profile, ShotKind.WIDE_LED)
        self.assertEqual(len(located), 1)
        self.assertEqual(located[0][0].posicion, "LATERAL_MAIN")
        located_fixed = locate_zones(
            frame, profile, ShotKind.WIDE_LED, include_fixed=True
        )
        self.assertEqual(len(located_fixed), 2)

    def test_far_led_sideline_still_locates(self):
        frame = _wide_far_led_frame()
        shot = classify_shot(frame)
        self.assertEqual(shot, ShotKind.WIDE_LED)
        located = locate_zones(frame, None, shot)
        self.assertGreaterEqual(len(located), 1)
        self.assertFalse(located[0][1].skipped, located[0][1].reason)

    def test_elevated_shot_with_led_is_wide_led(self):
        from tests.test_roi import MAGENTA, led_height_px

        height, width = 720, 1280
        frame = np.full((height, width, 3), NAVY, dtype=np.uint8)
        grass_top = int(0.20 * height)
        led_h = led_height_px(height)
        led_top = grass_top - led_h
        frame[grass_top:, :] = GREEN
        frame[led_top:grass_top, :] = (0, 230, 255)
        frame[led_top - 30 : led_top, :] = MAGENTA
        self.assertEqual(classify_shot(frame), ShotKind.WIDE_LED)
        located = locate_zones(frame, None, ShotKind.WIDE_LED)
        self.assertGreaterEqual(len(located), 1)
        self.assertFalse(located[0][1].skipped, located[0][1].reason)


if __name__ == "__main__":
    unittest.main()
