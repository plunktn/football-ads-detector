import importlib.util
import sys
import unittest
from pathlib import Path


def _load():
    path = Path(__file__).resolve().parents[1] / "eval" / "gold" / "compare_gold.py"
    spec = importlib.util.spec_from_file_location("compare_gold", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


compare_gold = _load()


class GoldCompareTests(unittest.TestCase):
    def test_error_excludes_doubtful_and_passes_at_boundary(self) -> None:
        labels = [
            {
                "brand": "NETT plus",
                "brand_id": "nett",
                "start_s": 0,
                "end_s": 10,
                "quality": "good",
                "doubtful": False,
            },
            {
                "brand": "NETT plus",
                "brand_id": "nett",
                "start_s": 20,
                "end_s": 25,
                "quality": "bad",
                "doubtful": True,
            },
        ]
        detector = [
            {"brand_id": "nett", "brand": "NETT plus", "start_s": 0, "end_s": 12},
        ]
        report = compare_gold.compare_minutes(labels, detector, tolerance_pct=20)
        self.assertEqual(len(report.brands), 1)
        score = report.brands[0]
        self.assertEqual(score.gold_seconds, 10)
        self.assertEqual(score.detector_seconds, 12)
        self.assertAlmostEqual(score.error_pct or 0, 20.0)
        self.assertAlmostEqual(score.doubtful_pct or 0, 100.0 * 5 / 15)
        self.assertAlmostEqual(report.doubtful_pct or 0, 100.0 * 5 / 15)
        self.assertTrue(report.passed)

    def test_over_tolerance_fails_and_brands_stay_separate(self) -> None:
        labels = [
            {"brand": "NETT plus", "brand_id": "nett", "start_s": 0, "end_s": 10, "doubtful": False},
            {"brand": "ECUABET", "brand_id": "ecuabet", "start_s": 0, "end_s": 10, "doubtful": False},
        ]
        detector = [
            {"brand_id": "nett", "start_s": 0, "end_s": 13},
            {"brand_id": "ecuabet", "start_s": 0, "end_s": 10},
        ]
        report = compare_gold.compare_minutes(labels, detector, tolerance_pct=20)
        by_name = {brand.brand: brand for brand in report.brands}
        self.assertAlmostEqual(by_name["NETT plus"].error_pct or 0, 30.0)
        self.assertAlmostEqual(by_name["ECUABET"].error_pct or 0, 0.0)
        self.assertFalse(report.passed)

    def test_result_json_ignores_fixed_brands(self) -> None:
        labels = [
            {"brand": "NETT plus", "brand_id": "nett", "start_s": 0, "end_s": 10, "quality": "good"},
        ]
        payload = {
            "brands": [
                {
                    "brand_id": "nett",
                    "name": "NETT plus",
                    "panel_kind": "LED",
                    "segments": [
                        {
                            "video_seconds_start": 0,
                            "video_seconds_end": 10,
                            "duration_seconds": 10,
                        }
                    ],
                }
            ],
            "fixed_brands": [
                {
                    "brand_id": "lions",
                    "name": "Lions",
                    "panel_kind": "FIJA",
                    "segments": [
                        {
                            "video_seconds_start": 0,
                            "video_seconds_end": 100,
                            "duration_seconds": 100,
                        }
                    ],
                }
            ],
        }
        report = compare_gold.compare_minutes(
            labels,
            compare_gold.detector_rows(payload),
            tolerance_pct=20,
        )
        self.assertEqual([brand.brand for brand in report.brands], ["NETT plus"])
        self.assertEqual(report.brands[0].detector_seconds, 10)
        self.assertTrue(report.passed)

    def test_example_fixture_has_no_detector_score(self) -> None:
        payload = compare_gold.load_json(
            Path(__file__).resolve().parents[1] / "eval" / "gold" / "clips" / "example.json"
        )
        self.assertIsNone(payload["video"])
        report = compare_gold.compare_minutes(compare_gold.gold_rows(payload), None)
        self.assertIsNone(report.passed)
        self.assertTrue(all(brand.error_pct is None for brand in report.brands))
        self.assertAlmostEqual(report.doubtful_pct or 0, 100.0 * 6 / 29)
        self.assertIn("n/a", compare_gold.format_report(report))

    def test_detector_unmeasurable_time_is_excluded_from_the_error(self) -> None:
        labels = [
            {
                "brand": "NETT plus",
                "brand_id": "nett",
                "start_s": 0,
                "end_s": 10,
                "doubtful": False,
            }
        ]
        detector = [
            {"brand_id": "nett", "brand": "NETT plus", "start_s": 0, "end_s": 6},
        ]
        doubtful = [
            {
                "half": "1T",
                "start_s": 6,
                "end_s": 10,
                "doubtful": True,
                "measurable": False,
                "reason": "illegible_ocr",
            }
        ]
        report = compare_gold.compare_minutes(
            labels,
            detector,
            tolerance_pct=20,
            detector_doubtful=doubtful,
        )
        score = report.brands[0]
        self.assertAlmostEqual(score.gold_seconds, 6.0)
        self.assertAlmostEqual(score.detector_seconds or 0, 6.0)
        self.assertAlmostEqual(score.error_pct or 0, 0.0)
        self.assertAlmostEqual(report.detector_unmeasurable_seconds, 4.0)
        self.assertTrue(report.passed)
        self.assertIn("no medible", compare_gold.format_report(report))

    def test_measurable_false_is_excluded_like_doubtful(self) -> None:
        labels = [
            {
                "brand_id": "nett",
                "brand": "NETT plus",
                "start_s": 0,
                "end_s": 10,
                "measurable": False,
            },
            {
                "brand_id": "nett",
                "brand": "NETT plus",
                "start_s": 10,
                "end_s": 20,
                "measurable": True,
            },
        ]
        detector = [{"brand_id": "nett", "start_s": 10, "end_s": 20}]
        report = compare_gold.compare_minutes(labels, detector, tolerance_pct=15)
        self.assertAlmostEqual(report.brands[0].gold_seconds, 10.0)
        self.assertAlmostEqual(report.excluded_label_seconds, 10.0)
        self.assertTrue(report.passed)
        self.assertIn("excluido del pass", compare_gold.format_report(report))

    def _synthetic_paths(self) -> tuple[Path, Path]:
        root = Path(__file__).resolve().parents[1] / "eval" / "gold"
        return (
            root / "clips" / "synthetic_interest.json",
            root / "fixtures" / "synthetic_interest_detector.json",
        )

    def test_synthetic_interest_clip_passes_inside_15_percent(self) -> None:
        gold_path, detector_path = self._synthetic_paths()
        gold = compare_gold.load_json(gold_path)
        detector = compare_gold.load_json(detector_path)
        self.assertTrue(gold["synthetic"])
        self.assertIsNone(gold["video"])
        self.assertEqual(gold["second_half_start_sec"], 4145)
        self.assertNotIn("sponsor-local", gold["interest_brands"])
        report = compare_gold.compare_minutes(
            compare_gold.gold_rows(gold),
            compare_gold.detector_rows(detector),
            tolerance_pct=15,
            detector_doubtful=compare_gold.detector_unmeasurable_rows(detector),
            expected_seconds=gold["expected_seconds"],
            interest_brands=gold["interest_brands"],
        )
        self.assertFalse(report.label_error)
        self.assertTrue(report.interest_scoped)
        self.assertTrue(report.passed)
        by_name = {brand.brand: brand for brand in report.brands}
        self.assertEqual(by_name["Sponsor local"].status, "fuera")
        self.assertFalse(by_name["Sponsor local"].in_claim)
        self.assertGreater(abs(by_name["Sponsor local"].error_pct or 0), 20)
        self.assertEqual(by_name["NETTPLUS"].status, "PASS")
        self.assertAlmostEqual(by_name["NETTPLUS"].detector_seconds or 0, 36.0)
        self.assertAlmostEqual(report.detector_unmeasurable_seconds, 18.0)
        text = compare_gold.format_report(report)
        self.assertIn("PASS", text)
        self.assertIn("doubtful_segments", text)
        self.assertIn("fuera", text)
        self.assertEqual(
            compare_gold.main(
                [
                    "--gold",
                    str(gold_path),
                    "--detector",
                    str(detector_path),
                    "--tolerance",
                    "15",
                ]
            ),
            0,
        )

    def test_synthetic_nettplus_fails_if_doubtful_segments_are_kept(self) -> None:
        gold_path, detector_path = self._synthetic_paths()
        gold = compare_gold.load_json(gold_path)
        detector = compare_gold.load_json(detector_path)
        report = compare_gold.compare_minutes(
            compare_gold.gold_rows(gold),
            compare_gold.detector_rows(detector),
            tolerance_pct=20,
            detector_doubtful=[],
            expected_seconds=gold["expected_seconds"],
            interest_brands=gold["interest_brands"],
        )
        nett = next(brand for brand in report.brands if brand.brand == "NETTPLUS")
        self.assertAlmostEqual(nett.detector_seconds or 0, 54.0)
        self.assertGreater(abs(nett.error_pct or 0), 20)
        self.assertFalse(report.passed)
        self.assertIn("FAIL", compare_gold.format_report(report))

    def test_expected_seconds_mismatch_fails_before_the_detector(self) -> None:
        labels = [
            {
                "brand": "Ecuabet",
                "brand_id": "ecuabet",
                "start_s": 0,
                "end_s": 10,
                "doubtful": False,
            }
        ]
        report = compare_gold.compare_minutes(
            labels,
            [{"brand_id": "ecuabet", "start_s": 0, "end_s": 10}],
            tolerance_pct=15,
            expected_seconds={"ecuabet": 99},
            interest_brands=["ecuabet"],
        )
        self.assertTrue(report.label_error)
        self.assertFalse(report.passed)
        self.assertIn("no coincide", compare_gold.format_report(report))


if __name__ == "__main__":
    unittest.main()
