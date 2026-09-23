"""LED merge, on/off hysteresis, and report totals.

Duration of a merged run is the wall-clock span from the first positive
sample through the end of the last one (last timestamp + sample interval),
including a bridged hole. Fixed-board aggregation keeps the 3 s gap.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openpyxl import load_workbook

from app import db
from app.pipeline.aggregate import (
    FrameObservation,
    aggregate_led_observations,
    aggregate_observations,
)
from app.pipeline.catalog_report import build_catalog_report
from app.pipeline.led_timing import LedTiming, load_led_timing
from app.pipeline.report import write_commercial_report


LED = LedTiming(merge_gap_sec=8.0, on_confirm_sec=0.0, off_hold_sec=8.0)


def observation(
    index: int,
    state: bool | None,
    *,
    brand: str = "nett",
    half: str = "1T",
    extra_brands: frozenset[str] | None = None,
) -> FrameObservation:
    detected: set[str] = set()
    if state is True:
        detected.add(brand)
    if extra_brands:
        detected.update(extra_brands)
    return FrameObservation(
        half=half,
        time_seconds=float(index),
        frame_idx=index * 30,
        detected_brand_ids=frozenset(detected),
        skipped=state is None,
    )


def _stream(hits: dict[int, str | None], *, length: int, half: str = "1T") -> list[FrameObservation]:
    """One sample per second. ``hits[t]`` is a brand id, ``None`` skips, missing is a miss."""
    rows: list[FrameObservation] = []
    for index in range(length):
        if index not in hits:
            rows.append(observation(index, False, half=half))
            continue
        brand = hits[index]
        if brand is None:
            rows.append(observation(index, None, half=half))
            continue
        rows.append(observation(index, True, brand=brand, half=half))
    return rows


class LedMergeTests(unittest.TestCase):
    def test_gap_just_under_threshold_is_one_wall_clock_interval(self) -> None:
        # Hit at t=0 and t=9. Coverage gap = 9 - 1 = 8 s, equal to the hold.
        rows = _stream({0: "nett", 9: "nett"}, length=10)
        result = aggregate_led_observations(rows, [("nett", "NETT plus")], timing=LED)[0]
        self.assertEqual(result.appearances, 1)
        self.assertEqual(result.total_seconds, 10)
        self.assertEqual(result.segments[0].video_seconds_start, 0.0)
        self.assertEqual(result.segments[0].video_seconds_end, 10.0)
        self.assertEqual(result.segments[0].duration_seconds, 10)
        self.assertNotEqual(result.total_seconds, 2)

    def test_gap_just_over_threshold_stays_two_crumbs(self) -> None:
        # Hit at t=0 and t=10. Coverage gap = 9 s > 8 s.
        rows = _stream({0: "nett", 10: "nett"}, length=11)
        result = aggregate_led_observations(rows, [("nett", "NETT plus")], timing=LED)[0]
        self.assertEqual(result.appearances, 2)
        self.assertEqual(result.total_seconds, 2)
        self.assertEqual(
            [segment.duration_seconds for segment in result.segments],
            [1, 1],
        )

    def test_other_brand_inside_the_hole_does_not_merge(self) -> None:
        rows = _stream({0: "nett", 1: "nett", 3: "ecuabet", 4: "ecuabet", 6: "nett", 7: "nett"}, length=8)
        results = {
            brand.brand_id: brand
            for brand in aggregate_led_observations(
                rows,
                [("nett", "NETT plus"), ("ecuabet", "ECUABET")],
                timing=LED,
            )
        }
        nett = results["nett"]
        ecuabet = results["ecuabet"]
        self.assertEqual(nett.appearances, 2)
        self.assertEqual(nett.total_seconds, 4)
        self.assertEqual(ecuabet.appearances, 1)
        self.assertEqual(ecuabet.total_seconds, 2)
        self.assertTrue(all(segment.half == "1T" for segment in nett.segments))

    def test_half_boundary_is_not_bridged(self) -> None:
        rows = [
            observation(100, True, half="1T"),
            observation(101, True, half="2T"),
        ]
        result = aggregate_led_observations(rows, [("nett", "NETT plus")], timing=LED)[0]
        self.assertEqual(result.appearances, 2)
        self.assertEqual(result.count_1t, 1)
        self.assertEqual(result.count_2t, 1)
        self.assertEqual([segment.half for segment in result.segments], ["1T", "2T"])
        self.assertEqual([segment.duration_seconds for segment in result.segments], [1, 1])

    def test_trailing_misses_are_not_appended(self) -> None:
        rows = _stream({0: "nett", 1: "nett"}, length=22)
        result = aggregate_led_observations(rows, [("nett", "NETT plus")], timing=LED)[0]
        self.assertEqual(result.appearances, 1)
        self.assertEqual(result.total_seconds, 2)

    def test_on_confirm_drops_isolated_hits_until_consecutive(self) -> None:
        timing = LedTiming(merge_gap_sec=8.0, on_confirm_sec=2.0, off_hold_sec=8.0)
        lone = aggregate_led_observations(
            _stream({0: "nett"}, length=1),
            [("nett", "NETT plus")],
            timing=timing,
        )[0]
        self.assertEqual(lone.appearances, 0)
        self.assertEqual(lone.total_seconds, 0)

        pair = aggregate_led_observations(
            _stream({0: "nett", 1: "nett"}, length=2),
            [("nett", "NETT plus")],
            timing=timing,
        )[0]
        self.assertEqual(pair.appearances, 1)
        self.assertEqual(pair.total_seconds, 2)

        broken = aggregate_led_observations(
            _stream({0: "nett", 2: "nett"}, length=3),
            [("nett", "NETT plus")],
            timing=timing,
        )[0]
        self.assertEqual(broken.appearances, 0)

    def test_wider_merge_gap_joins_what_off_hold_closed(self) -> None:
        timing = LedTiming(merge_gap_sec=8.0, on_confirm_sec=0.0, off_hold_sec=2.0)
        merged = aggregate_led_observations(
            _stream({0: "nett", 5: "nett"}, length=6),
            [("nett", "NETT plus")],
            timing=timing,
        )[0]
        self.assertEqual(merged.appearances, 1)
        self.assertEqual(merged.total_seconds, 6)

        blocked = aggregate_led_observations(
            _stream({0: "nett", 3: "ecuabet", 5: "nett"}, length=6),
            [("nett", "NETT plus"), ("ecuabet", "ECUABET")],
            timing=timing,
        )
        nett = next(brand for brand in blocked if brand.brand_id == "nett")
        self.assertEqual(nett.appearances, 2)
        self.assertEqual(nett.total_seconds, 2)

    def test_same_timestamp_zones_count_once(self) -> None:
        rows: list[FrameObservation] = []
        for index in range(3):
            rows.append(
                FrameObservation(
                    half="1T",
                    time_seconds=float(index),
                    frame_idx=index,
                    detected_brand_ids=frozenset({"nett"}),
                    skipped=False,
                    zone_id="led_a",
                )
            )
            rows.append(
                FrameObservation(
                    half="1T",
                    time_seconds=float(index),
                    frame_idx=index,
                    detected_brand_ids=frozenset(),
                    skipped=False,
                    zone_id="led_b",
                )
            )
        result = aggregate_led_observations(rows, [("nett", "NETT plus")], timing=LED)[0]
        self.assertEqual(result.appearances, 1)
        self.assertEqual(result.total_seconds, 3)

    def test_led_gap_is_wider_than_fixed_default(self) -> None:
        rows = _stream({0: "nett", 5: "nett"}, length=6)
        brands = [("nett", "NETT plus")]
        fixed = aggregate_observations(rows, brands)[0]
        led = aggregate_led_observations(rows, brands, timing=LED)[0]
        self.assertEqual(fixed.appearances, 2)
        self.assertEqual(fixed.total_seconds, 2)
        self.assertEqual(led.appearances, 1)
        self.assertEqual(led.total_seconds, 6)

    def test_env_override_and_invalid_fallback(self) -> None:
        with patch.dict(os.environ, {"LED_MERGE_GAP_SEC": "2", "LED_ON_CONFIRM_SEC": "0"}):
            os.environ.pop("LED_OFF_HOLD_SEC", None)
            timing = load_led_timing()
            self.assertEqual(timing.merge_gap_sec, 2.0)
            self.assertEqual(timing.off_hold_sec, 2.0)
            result = aggregate_led_observations(
                _stream({0: "nett", 5: "nett"}, length=6),
                [("nett", "NETT plus")],
            )[0]
        self.assertEqual(result.appearances, 2)

        with patch.dict(os.environ, {"LED_MERGE_GAP_SEC": "nope"}):
            os.environ.pop("LED_OFF_HOLD_SEC", None)
            self.assertEqual(load_led_timing().merge_gap_sec, 8.0)


class ReportUsesMergedIntervalsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        db.set_db_path(Path(self._tmpdir.name) / "test.db")
        db.init_db()
        db.upsert_brand("nett", "NETT plus")
        db.upsert_brand("ecuabet", "ECUABET")
        db.insert_job(
            job_id="job-merge",
            stadium_id="ligaecuabet",
            profile_id=None,
            mode="single",
            duration_mode="full",
            status="completed",
            directory=self._tmpdir.name,
        )

    def tearDown(self) -> None:
        db.reset_db_path()
        self._tmpdir.cleanup()

    def _frame(self, frame_idx: int, time_seconds: float, brand_id: str, half: str = "1T") -> dict:
        return {
            "half": half,
            "frame_idx": frame_idx,
            "time_seconds": time_seconds,
            "crop_relpath": f"{brand_id}-{frame_idx}.jpg",
            "machine_label": "positive",
            "brand_id": brand_id,
        }

    def test_catalog_and_excel_use_wall_clock_span(self) -> None:
        # Positive crumbs at 0, 1, 7, 8. Hole of 5 s is inside the 8 s bridge.
        # Span is 9 s, not the 4 detected seconds.
        times = [0.0, 1.0, 7.0, 8.0]
        db.insert_job_frames(
            "job-merge",
            [self._frame(index, time_seconds, "nett") for index, time_seconds in enumerate(times)],
        )
        payload = build_catalog_report("job-merge", timing=LED, sample_interval=1.0)
        assert payload is not None
        brand = payload["brands"][0]
        self.assertEqual(brand["appearances"], 1)
        self.assertEqual(brand["total_seconds"], 9)
        self.assertEqual(brand["segments"][0]["duration_seconds"], 9)
        self.assertEqual(brand["segments"][0]["video_seconds_start"], 0.0)
        self.assertEqual(brand["segments"][0]["video_seconds_end"], 9.0)
        self.assertEqual(payload["summary"]["total_seconds"], 9)

        rows = _stream({0: "nett", 1: "nett", 7: "nett", 8: "nett"}, length=9)
        led = aggregate_led_observations(rows, [("nett", "NETT plus")], timing=LED)[0]
        self.assertEqual(led.total_seconds, brand["total_seconds"])

        path = Path(self._tmpdir.name) / "informe.xlsx"
        write_commercial_report(path, led_brands=[led], analyzed_seconds=9)
        workbook = load_workbook(path)
        self.assertEqual(workbook["Resumen LED"].cell(row=2, column=3).value, 9)
        self.assertEqual(workbook["Salidas LED"].max_row, 2)
        self.assertEqual(workbook["Salidas LED"].cell(row=2, column=5).value, 9)
        resumen = sum(
            int(workbook["Resumen LED"].cell(row=row, column=3).value or 0)
            for row in range(2, workbook["Resumen LED"].max_row + 1)
        )
        salidas = sum(
            int(workbook["Salidas LED"].cell(row=row, column=5).value or 0)
            for row in range(2, workbook["Salidas LED"].max_row + 1)
        )
        self.assertEqual(resumen, salidas)
        self.assertNotEqual(resumen, 4)
        workbook.close()

    def test_catalog_brand_change_and_half_boundary(self) -> None:
        db.insert_job_frames(
            "job-merge",
            [
                self._frame(1, 0.0, "nett"),
                self._frame(2, 3.0, "ecuabet"),
                self._frame(3, 6.0, "nett"),
                self._frame(4, 11.0, "nett", half="2T"),
            ],
        )
        payload = build_catalog_report("job-merge", timing=LED, sample_interval=1.0)
        assert payload is not None
        by_id = {brand["brand_id"]: brand for brand in payload["brands"]}
        self.assertEqual(by_id["nett"]["appearances"], 3)
        self.assertEqual(by_id["nett"]["total_seconds"], 3)
        self.assertEqual(by_id["ecuabet"]["appearances"], 1)
        self.assertEqual(by_id["ecuabet"]["total_seconds"], 1)
        halves = [segment["half"] for segment in by_id["nett"]["segments"]]
        self.assertEqual(halves.count("1T"), 2)
        self.assertEqual(halves.count("2T"), 1)

    def test_catalog_reads_sample_fps_from_job_meta(self) -> None:
        meta = Path(self._tmpdir.name) / "meta.json"
        meta.write_text(json.dumps({"sample_fps": 2}), encoding="utf-8")
        db.insert_job_frames(
            "job-merge",
            [self._frame(1, 0.0, "nett"), self._frame(2, 0.5, "nett")],
        )
        payload = build_catalog_report("job-merge", timing=LED)
        assert payload is not None
        brand = payload["brands"][0]
        self.assertEqual(brand["appearances"], 1)
        self.assertEqual(brand["total_seconds"], 1)
        self.assertEqual(brand["segments"][0]["video_seconds_end"], 1.0)


if __name__ == "__main__":
    unittest.main()
