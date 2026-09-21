"""Unit tests for kickoff override resolution (skip OCR scan when both offsets set)."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from app.pipeline.scoreboard import resolve_kickoff
from app.schemas import Kickoff


class ResolveKickoffTests(unittest.TestCase):
    def test_both_overrides_skip_detect_scan(self) -> None:
        with patch("app.pipeline.scoreboard.detect_kickoffs") as detect, patch(
            "app.pipeline.scoreboard._scan_for_kickoff"
        ) as scan, patch(
            "app.pipeline.scoreboard._detect_second_half_single"
        ) as second:
            kickoff, warnings = resolve_kickoff(
                [Path("match.mp4")],
                "single",
                "full",
                kickoff_offset_sec=282.0,
                second_half_start_sec=3600.0,
            )
        detect.assert_not_called()
        scan.assert_not_called()
        second.assert_not_called()
        self.assertEqual(kickoff.note, "overrides_only")
        self.assertEqual(kickoff.first_half_video_seconds, 282.0)
        self.assertEqual(kickoff.second_half_video_seconds, 3600.0)
        self.assertEqual(warnings, [])

    def test_1t_override_scans_only_2t(self) -> None:
        with patch(
            "app.pipeline.scoreboard._detect_second_half_single",
            return_value=None,
        ) as second, patch(
            "app.pipeline.scoreboard.get_video_info",
        ) as info, patch(
            "app.pipeline.scoreboard.detect_kickoffs",
        ) as detect:
            info.return_value.duration_seconds = 7000.0
            kickoff, warnings = resolve_kickoff(
                [Path("match.mp4")],
                "single",
                "full",
                kickoff_offset_sec=282.0,
            )
        detect.assert_not_called()
        second.assert_called_once()
        self.assertEqual(kickoff.first_half_video_seconds, 282.0)
        self.assertIsNone(kickoff.second_half_video_seconds)
        self.assertTrue(any("2T no detectado" in w for w in warnings))

    def test_no_overrides_calls_detect(self) -> None:
        fake = Kickoff(
            first_half_video_seconds=10.0,
            second_half_video_seconds=100.0,
            note="detectado por marcador",
        )
        with patch(
            "app.pipeline.scoreboard.detect_kickoffs",
            return_value=fake,
        ) as detect:
            kickoff, warnings = resolve_kickoff(
                [Path("match.mp4")],
                "single",
                "full",
            )
        detect.assert_called_once()
        self.assertEqual(kickoff, fake)
        self.assertEqual(warnings, [])


if __name__ == "__main__":
    unittest.main()
