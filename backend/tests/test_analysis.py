import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from app.domain.zones import DEFAULT_PANEL_ZONES
from app.pipeline.aggregate import FrameObservation, aggregate_observations
from app.pipeline.hysteresis import apply_hysteresis
from app.pipeline.ocr import OcrHit
from app.pipeline.roi import RoiResult
from app.pipeline.run import FALLBACK_FIRST_HALF_SECONDS, build_analysis_windows, run_analysis
from app.schemas import BrandInput, Kickoff


def observation(index: int, state: bool | None, half: str = "1T"):
    return FrameObservation(
        half=half,
        time_seconds=float(index),
        frame_idx=index * 30,
        detected_brand_ids=frozenset({"nett"} if state is True else set()),
        skipped=state is None,
    )


class HysteresisTests(unittest.TestCase):
    def test_fills_one_second_ocr_gap(self):
        self.assertEqual(
            apply_hysteresis([True, False, True, False]),
            [True, True, True, False],
        )

    def test_fills_up_to_three_second_gaps(self):
        self.assertEqual(
            apply_hysteresis([True, False, False, True]),
            [True, True, True, True],
        )
        self.assertEqual(
            apply_hysteresis([True, None, None, None, True]),
            [True, True, True, True, True],
        )

    def test_does_not_fill_four_second_gap(self):
        self.assertEqual(
            apply_hysteresis([True, False, False, False, False, True]),
            [True, False, False, False, False, True],
        )


class AggregateTests(unittest.TestCase):
    def test_two_false_samples_merge_into_one_run(self):
        """Gap of 2s ≤ MERGE_GAP_SEC → single appearance spanning the bridge."""
        result = aggregate_observations(
            [observation(0, True), observation(1, True), observation(2, False),
             observation(3, False), observation(4, True)],
            [("nett", "NETT plus")],
        )[0]
        self.assertEqual(result.appearances, 1)
        self.assertEqual(result.total_seconds, 5)
        self.assertEqual(result.start_frames, [0])

    def test_four_false_samples_split_segments(self):
        result = aggregate_observations(
            [
                observation(0, True),
                observation(1, False),
                observation(2, False),
                observation(3, False),
                observation(4, False),
                observation(5, True),
            ],
            [("nett", "NETT plus")],
        )[0]
        self.assertEqual(result.appearances, 2)
        self.assertEqual(result.total_seconds, 2)
        self.assertEqual(result.start_frames, [0, 150])

    def test_on_off_on_rotation_stays_one_salida(self):
        """Typical playlist block: 5s ON, 2s OCR miss, 5s ON → one ~12s run."""
        samples = (
            [observation(i, True) for i in range(5)]
            + [observation(5, False), observation(6, False)]
            + [observation(i, True) for i in range(7, 12)]
        )
        result = aggregate_observations(samples, [("nett", "NETT plus")])[0]
        self.assertEqual(result.appearances, 1)
        self.assertEqual(result.total_seconds, 12)

    def test_segment_copies_zone_from_observation(self):
        samples = [
            FrameObservation(
                half="1T",
                time_seconds=float(index),
                frame_idx=index * 30,
                detected_brand_ids=frozenset({"nett"}),
                skipped=False,
                zone_id="led_lateral_main",
                posicion="LATERAL_MAIN",
            )
            for index in range(3)
        ]
        result = aggregate_observations(samples, [("nett", "NETT plus")])[0]
        self.assertEqual(result.segments[0].zone_id, "led_lateral_main")
        self.assertEqual(result.segments[0].posicion, "LATERAL_MAIN")

    def test_four_skips_split_without_counting_unknown_samples(self):
        result = aggregate_observations(
            [observation(0, True), observation(1, None), observation(2, None),
             observation(3, None), observation(4, None), observation(5, True)],
            [("nett", "NETT plus")],
        )[0]
        self.assertEqual(result.appearances, 2)
        self.assertEqual(result.total_seconds, 2)

    def test_empty_brand_remains_visible(self):
        result = aggregate_observations(
            [observation(0, False)],
            [("nett", "NETT plus"), ("lions", "Lions")],
        )
        self.assertEqual([brand.appearances for brand in result], [0, 0])


class WindowTests(unittest.TestCase):
    def _video(self, duration_seconds: int) -> Path:
        handle = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
        handle.close()
        path = Path(handle.name)
        writer = cv2.VideoWriter(
            str(path),
            cv2.VideoWriter_fourcc(*"mp4v"),
            10,
            (32, 32),
        )
        for _ in range(duration_seconds * 10):
            writer.write(np.zeros((32, 32, 3), dtype=np.uint8))
        writer.release()
        self.addCleanup(path.unlink, missing_ok=True)
        return path

    def test_single_full_splits_at_second_half_kickoff(self):
        video = self._video(20)
        windows = build_analysis_windows(
            [video],
            mode="single",
            duration_mode="full",
            kickoff=Kickoff(
                first_half_video_seconds=2,
                second_half_video_seconds=11,
            ),
        )
        self.assertEqual([(window.half, window.start_seconds, window.end_seconds)
                          for window in windows],
                         [("1T", 2, 11), ("2T", 11, 20)])

    def test_custom_minutes_window(self):
        video = self._video(1200)
        windows = build_analysis_windows(
            [video],
            mode="single",
            duration_mode="16min",
            kickoff=Kickoff(first_half_video_seconds=10),
        )
        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0].half, "1T")
        self.assertEqual(windows[0].start_seconds, 10)
        self.assertEqual(windows[0].end_seconds, 10 + 16 * 60)

    def _long_match(self, video: Path):
        info = patch("app.pipeline.run.get_video_info")
        mocked = info.start()
        self.addCleanup(info.stop)
        mocked.return_value.duration_seconds = 7200.0
        mocked.return_value.path = video
        return mocked

    def test_continuous_clock_without_2t_drops_led_after_the_fallback(self):
        """Libertad-style file: 2T wall time is ~4145s and the clock does not reset.

        Without an override the sampler stops at kickoff + 47 min, so LED
        seconds at 4145 never become samples.
        """
        video = self._video(2)
        self._long_match(video)
        windows = build_analysis_windows(
            [video],
            mode="single",
            duration_mode="full",
            kickoff=Kickoff(first_half_video_seconds=180),
        )
        self.assertEqual([window.half for window in windows], ["1T"])
        self.assertEqual(
            windows[0].end_seconds,
            180 + FALLBACK_FIRST_HALF_SECONDS,
        )
        self.assertLess(windows[0].end_seconds, 4145)
        self.assertFalse(
            any(window.start_seconds <= 4145 < window.end_seconds for window in windows)
        )

    def test_2t_override_keeps_led_window_at_4145(self):
        video = self._video(2)
        self._long_match(video)
        windows = build_analysis_windows(
            [video],
            mode="single",
            duration_mode="full",
            kickoff=Kickoff(
                first_half_video_seconds=180,
                second_half_video_seconds=4145,
                note="overrides_only; continuous_clock",
            ),
        )
        self.assertEqual(
            [(window.half, window.start_seconds, window.end_seconds) for window in windows],
            [("1T", 180, 4145), ("2T", 4145, 7200)],
        )
        self.assertTrue(
            any(window.start_seconds <= 4145 < window.end_seconds for window in windows)
        )

    def test_second_half_override_counts_led_seconds(self):
        video = self._video(12)
        crop = np.zeros((32, 100, 3), dtype=np.uint8)
        roi = RoiResult(False, None, crop, None)
        with patch(
            "app.pipeline.run.locate_zones",
            return_value=[(DEFAULT_PANEL_ZONES[0], roi)],
        ), patch(
            "app.pipeline.run.read_led_hits",
            return_value=[
                OcrHit(text="NETTPLUS", x_center=0.2),
                OcrHit(text="NETTPLUS", x_center=0.8),
            ],
        ):
            result = run_analysis(
                [video],
                mode="single",
                duration_mode="full",
                kickoff=Kickoff(
                    first_half_video_seconds=1,
                    second_half_video_seconds=6,
                ),
                brands=[BrandInput(id="nett", name="NETT plus")],
                debug_dir=video.parent / "debug",
            )
        halves = {segment.half for segment in result.brands[0].segments}
        self.assertIn("2T", halves)
        self.assertIn("2T", result.halves)
        second = [
            segment
            for segment in result.brands[0].segments
            if segment.half == "2T"
        ]
        self.assertGreater(second[0].duration_seconds, 0)
        self.assertGreater(result.brands[0].total_seconds, second[0].duration_seconds)

    def test_run_analysis_uses_one_sample_per_second(self):
        video = self._video(3)
        crop = np.zeros((32, 100, 3), dtype=np.uint8)
        roi = RoiResult(False, None, crop, None)
        updates = []
        with patch("app.pipeline.run.locate_zones", return_value=[(DEFAULT_PANEL_ZONES[0], roi)]), \
             patch(
                 "app.pipeline.run.read_led_hits",
                 return_value=[
                     OcrHit(text="NETTPLUS", x_center=0.2),
                     OcrHit(text="NETTPLUS", x_center=0.8),
                 ],
             ):
            result = run_analysis(
                [video],
                mode="single",
                duration_mode="5min",
                kickoff=Kickoff(),
                brands=[BrandInput(id="nett", name="NETT plus")],
                debug_dir=video.parent / "debug",
                on_update=updates.append,
            )
        self.assertEqual(result.analyzed_seconds, 3)
        self.assertEqual(result.brands[0].total_seconds, 3)
        self.assertEqual(result.brands[0].appearances, 1)
        self.assertEqual(result.brands[0].start_frames, [0])
        self.assertEqual(result.brands[0].segments[0].zone_id, "led_lateral_main")
        self.assertEqual(result.brands[0].segments[0].posicion, "LATERAL_MAIN")
        self.assertTrue(updates)


if __name__ == "__main__":
    unittest.main()
