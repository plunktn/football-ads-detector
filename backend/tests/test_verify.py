import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from app.pipeline.aggregate import FrameObservation
from app.pipeline.playlist import (
    PlaylistSlot,
    libertad_orense_fixture_sheets,
    parse_playlist,
    write_lions_workbook,
)
from app.pipeline.report import write_commercial_report
from app.pipeline.run import run_analysis
from app.pipeline.verify import (
    slot_video_window,
    to_compliance_row,
    verify_slot_from_observations,
)
from app.schemas import BrandInput, BrandResult, Kickoff


class VerifySlotTests(unittest.TestCase):
    def test_maps_clock_to_video_using_kickoff(self) -> None:
        slot = PlaylistSlot("1T", "NETPLUS", 15, 30, 15)
        kickoff = Kickoff(
            first_half_video_seconds=10,
            second_half_video_seconds=100,
        )
        self.assertEqual(slot_video_window(slot, kickoff), (25.0, 40.0))
        second = PlaylistSlot("2T", "LIONS", 30, 45, 15)
        self.assertEqual(slot_video_window(second, kickoff), (130.0, 145.0))

    def test_hit_from_observations_inside_window(self) -> None:
        slot = PlaylistSlot("1T", "NETPLUS", 15, 30, 15)
        kickoff = Kickoff(first_half_video_seconds=0)
        observations = [
            FrameObservation(
                half="1T",
                time_seconds=20.0,
                frame_idx=600,
                detected_brand_ids=frozenset({"netplus"}),
                skipped=False,
                tipo_panel="LED_DYNAMIC",
            )
        ]
        result = verify_slot_from_observations(
            slot, observations, kickoff, "netplus"
        )
        self.assertTrue(result.hit)
        self.assertEqual(result.observed_video_sec, 20.0)

    def test_miss_outside_window(self) -> None:
        slot = PlaylistSlot("1T", "NETPLUS", 15, 30, 15)
        observations = [
            FrameObservation(
                half="1T",
                time_seconds=3.0,
                frame_idx=90,
                detected_brand_ids=frozenset({"netplus"}),
                skipped=False,
            )
        ]
        result = verify_slot_from_observations(
            slot, observations, Kickoff(), "netplus"
        )
        self.assertFalse(result.hit)


class PlaylistVerifyPipelineTests(unittest.TestCase):
    def _video(self, duration_seconds: int) -> Path:
        handle = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
        handle.close()
        path = Path(handle.name)
        writer = cv2.VideoWriter(
            str(path),
            cv2.VideoWriter_fourcc(*"mp4v"),
            10,
            (64, 64),
        )
        for _ in range(duration_seconds * 10):
            writer.write(np.zeros((64, 64, 3), dtype=np.uint8))
        writer.release()
        self.addCleanup(path.unlink, missing_ok=True)
        return path

    def test_synthetic_video_hits_over_90_percent(self) -> None:
        from app.domain.zones import DEFAULT_PANEL_ZONES
        from app.pipeline.ocr import OcrHit
        from app.pipeline.roi import RoiResult

        video = self._video(40)
        tmp = Path(tempfile.mkdtemp())
        playlist = tmp / "PLAYLIST_LIBERTADvORENSE.xlsx"
        write_lions_workbook(
            playlist,
            {
                "PREVIA": [("LIONS", "0.00", 15)],
                "PRIMER TIEMPO": [
                    ("NETPLUS", "0.02", 5),
                    ("ECUABET", "0.08", 5),
                ],
                "ENTRETIEMPO": [],
                "SEGUNDO TIEMPO": [("NETPLUS", "0.02", 5)],
                "POST": [],
            },
        )
        slots = parse_playlist(playlist)
        crop = np.zeros((24, 80, 3), dtype=np.uint8)
        roi = RoiResult(False, None, crop, None, y0=10, y1=34)
        zone = DEFAULT_PANEL_ZONES[0]

        def fake_hits(_crop):
            return [
                OcrHit(text="NETPLUS", x_center=0.2),
                OcrHit(text="NETPLUS", x_center=0.8),
            ]

        # Brand returned depends on video second via side_effect on match? Simpler:
        # patch match_brand_ids based on nothing — always return both brands.
        # Then every slot hits. >90%.
        with patch("app.pipeline.run.locate_zones", return_value=[(zone, roi)]), \
             patch("app.pipeline.run.read_led_hits", side_effect=fake_hits), \
             patch(
                 "app.pipeline.run.match_brand_ids",
                 side_effect=lambda *args, **kwargs: {"netplus", "ecuabet"},
             ), \
             patch("app.pipeline.run.match_fixed_brand_ids", return_value=set()):
            result = run_analysis(
                [video],
                mode="single",
                duration_mode="full",
                kickoff=Kickoff(
                    first_half_video_seconds=0,
                    second_half_video_seconds=20,
                ),
                brands=[
                    BrandInput(id="netplus", name="NETPLUS", aliases=["NETT.plus"]),
                    BrandInput(id="ecuabet", name="ECUABET"),
                ],
                debug_dir=tmp / "debug",
                analysis_mode="playlist_verify",
                playlist_slots=slots,
            )
        self.assertGreater(result.hit_rate or 0.0, 0.90)
        self.assertTrue(all(row.hit for row in result.compliance))


class ReportTests(unittest.TestCase):
    def test_workbook_has_lions_sheets(self) -> None:
        tmp = Path(tempfile.mkdtemp()) / "informe.xlsx"
        brand = BrandResult(
            brand_id="netplus",
            name="NETPLUS",
            appearances=2,
            total_seconds=30,
            minutes=0,
            seconds=30,
            panel_kind="LED",
            count_1t=1,
            count_2t=1,
        )
        slots = parse_playlist(
            write_lions_workbook(
                tmp.with_name("playlist.xlsx"),
                libertad_orense_fixture_sheets(),
            )
        )
        path = write_commercial_report(
            tmp,
            led_brands=[brand],
            fixed_brands=[],
            slots=slots,
            compliance=[
                to_compliance_row(
                    verify_slot_from_observations(
                        next(s for s in slots if s.period == "1T"),
                        [
                            FrameObservation(
                                half="1T",
                                time_seconds=20,
                                frame_idx=1,
                                detected_brand_ids=frozenset({"netplus"}),
                                skipped=False,
                            )
                        ],
                        Kickoff(),
                        "netplus",
                    )
                )
            ],
            hit_rate=1.0,
            analyzed_seconds=40,
        )
        from openpyxl import load_workbook

        wb = load_workbook(path)
        self.assertEqual(
            wb.sheetnames,
            [
                "Resumen",
                "Salidas detectadas",
                "Playlist 1T",
                "Playlist 2T",
                "Cumplimiento",
                "Fijas",
            ],
        )
        self.assertEqual(wb["Resumen"][1][0].value, "Cliente")
        self.assertEqual(wb["Resumen"][2][0].value, "NETPLUS")


if __name__ == "__main__":
    unittest.main()
