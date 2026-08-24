import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from app.pipeline.aggregate import FrameObservation, aggregate_observations
from app.pipeline.hysteresis import apply_hysteresis
from app.pipeline.roi import RoiResult
from app.pipeline.run import build_analysis_windows, run_analysis
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

    def test_does_not_turn_two_unknown_seconds_into_exposure(self):
        self.assertEqual(
            apply_hysteresis([True, None, None, True]),
            [True, None, None, True],
        )


class AggregateTests(unittest.TestCase):
    def test_two_false_samples_close_segment(self):
        result = aggregate_observations(
            [observation(0, True), observation(1, True), observation(2, False),
             observation(3, False), observation(4, True)],
            [("nett", "NETT plus")],
        )[0]
        self.assertEqual(result.appearances, 2)
        self.assertEqual(result.total_seconds, 3)
        self.assertEqual(result.start_frames, [0, 120])

    def test_three_skips_close_without_counting_unknown_samples(self):
        result = aggregate_observations(
            [observation(0, True), observation(1, None), observation(2, None),
             observation(3, None), observation(4, True)],
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

    def test_run_analysis_uses_one_sample_per_second(self):
        video = self._video(3)
        crop = np.zeros((32, 100, 3), dtype=np.uint8)
        roi = RoiResult(False, None, crop, None)
        updates = []
        with patch("app.pipeline.run.extract_led_roi", return_value=roi), \
             patch("app.pipeline.run.read_led_text", return_value="NETTPLUS"):
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
        self.assertTrue(updates)


if __name__ == "__main__":
    unittest.main()
