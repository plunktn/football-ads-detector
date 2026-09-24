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


if __name__ == "__main__":
    unittest.main()
