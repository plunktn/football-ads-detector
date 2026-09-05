import unittest

from app.eval.metrics import (
    Interval,
    aggregate_brand_totals,
    compute_brand_metrics,
    interval_seconds,
    merge_intervals,
    overlap_seconds,
    round_metrics,
)


class IntervalTests(unittest.TestCase):
    def test_interval_seconds_sums_lengths(self):
        intervals = [Interval(0, 5), Interval(10, 12)]
        self.assertEqual(interval_seconds(intervals), 7.0)

    def test_merge_intervals_combines_overlap(self):
        merged = merge_intervals([Interval(0, 5), Interval(3, 8), Interval(10, 11)])
        self.assertEqual(merged, [Interval(0, 8), Interval(10, 11)])


class OverlapTests(unittest.TestCase):
    def test_full_overlap(self):
        predicted = [Interval(10, 20)]
        ground_truth = [Interval(10, 20)]
        self.assertEqual(overlap_seconds(predicted, ground_truth), 10.0)

    def test_partial_overlap(self):
        predicted = [Interval(10, 25)]
        ground_truth = [Interval(20, 30)]
        self.assertEqual(overlap_seconds(predicted, ground_truth), 5.0)

    def test_no_overlap(self):
        predicted = [Interval(0, 5)]
        ground_truth = [Interval(10, 15)]
        self.assertEqual(overlap_seconds(predicted, ground_truth), 0.0)

    def test_multiple_intervals_overlap(self):
        predicted = [Interval(0, 10), Interval(20, 30)]
        ground_truth = [Interval(5, 15), Interval(25, 35)]
        self.assertEqual(overlap_seconds(predicted, ground_truth), 10.0)


class BrandMetricsTests(unittest.TestCase):
    def test_perfect_detection(self):
        intervals = [Interval(10.0, 25.0)]
        metrics = compute_brand_metrics(intervals, intervals)
        self.assertEqual(metrics["precision"], 1.0)
        self.assertEqual(metrics["recall"], 1.0)
        self.assertEqual(metrics["error_s"], 0.0)
        self.assertEqual(metrics["true_positive_seconds"], 15.0)

    def test_no_predictions_zero_precision(self):
        ground_truth = [Interval(0, 10)]
        metrics = compute_brand_metrics([], ground_truth)
        self.assertEqual(metrics["precision"], 0.0)
        self.assertEqual(metrics["recall"], 0.0)
        self.assertEqual(metrics["error_s"], 10.0)

    def test_no_ground_truth_zero_recall(self):
        predicted = [Interval(0, 8)]
        metrics = compute_brand_metrics(predicted, [])
        self.assertEqual(metrics["precision"], 0.0)
        self.assertEqual(metrics["recall"], 0.0)
        self.assertEqual(metrics["error_s"], 8.0)

    def test_partial_match(self):
        predicted = [Interval(0, 20)]
        ground_truth = [Interval(0, 10)]
        metrics = compute_brand_metrics(predicted, ground_truth)
        self.assertEqual(metrics["true_positive_seconds"], 10.0)
        self.assertAlmostEqual(metrics["precision"], 0.5)
        self.assertAlmostEqual(metrics["recall"], 1.0)
        self.assertEqual(metrics["error_s"], 10.0)


class AggregateBrandTotalsTests(unittest.TestCase):
    def test_micro_average_across_clips(self):
        clip_a = compute_brand_metrics([Interval(0, 10)], [Interval(0, 10)])
        clip_b = compute_brand_metrics([Interval(0, 5)], [Interval(0, 10)])
        combined = aggregate_brand_totals([clip_a, clip_b])
        self.assertEqual(combined["true_positive_seconds"], 15.0)
        self.assertEqual(combined["predicted_seconds"], 15.0)
        self.assertEqual(combined["gt_seconds"], 20.0)
        self.assertAlmostEqual(combined["precision"], 1.0)
        self.assertAlmostEqual(combined["recall"], 0.75)
        self.assertEqual(combined["error_s"], 5.0)


class RoundMetricsTests(unittest.TestCase):
    def test_sorted_rounded_keys(self):
        rounded = round_metrics(
            {"recall": 0.123456789, "precision": 0.987654321},
            places=4,
        )
        self.assertEqual(list(rounded.keys()), ["precision", "recall"])
        self.assertEqual(rounded["precision"], 0.9877)
        self.assertEqual(rounded["recall"], 0.1235)


if __name__ == "__main__":
    unittest.main()
