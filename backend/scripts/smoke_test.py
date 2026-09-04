#!/usr/bin/env python3
"""End-to-end smoke: playlist parse + playlist_verify + Excel report."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.domain.zones import DEFAULT_PANEL_ZONES
from app.pipeline.ocr import OcrHit
from app.pipeline.playlist import parse_playlist, write_lions_workbook
from app.pipeline.report import write_commercial_report
from app.pipeline.roi import RoiResult
from app.pipeline.run import run_analysis
from app.schemas import BrandInput, Kickoff


def _tiny_video(path: Path, duration_seconds: int = 40) -> Path:
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        10,
        (64, 64),
    )
    for _ in range(duration_seconds * 10):
        writer.write(np.zeros((64, 64, 3), dtype=np.uint8))
    writer.release()
    return path


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="ads-smoke-"))
    video = _tiny_video(tmp / "match.mp4")
    playlist = write_lions_workbook(
        tmp / "PLAYLIST_LIBERTADvORENSE.xlsx",
        {
            "PREVIA": [("LIONS", "0.00", 15)],
            "PRIMER TIEMPO": [
                ("NETT.plus", "0.02", 5),
                ("ECUABET", "0.08", 5),
            ],
            "ENTRETIEMPO": [("PILSENER", "0.00", 15)],
            "SEGUNDO TIEMPO": [("NETPLUS", "0.02", 5)],
            "POST": [("UTPL", "0.00", 15)],
        },
    )
    slots = parse_playlist(playlist)
    assert any(slot.period == "PREVIA" for slot in slots)
    assert any(slot.period == "1T" for slot in slots)
    assert any(slot.period == "2T" for slot in slots)

    crop = np.zeros((24, 80, 3), dtype=np.uint8)
    roi = RoiResult(False, None, crop, None, y0=10, y1=34)
    zone = DEFAULT_PANEL_ZONES[0]

    with patch("app.pipeline.run.locate_zones", return_value=[(zone, roi)]), \
         patch(
             "app.pipeline.run.read_led_hits",
             return_value=[
                 OcrHit(text="NETPLUS", x_center=0.2),
                 OcrHit(text="NETPLUS", x_center=0.8),
             ],
         ), \
         patch(
             "app.pipeline.run.match_brand_ids",
             return_value={"netplus", "ecuabet"},
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

    if result.hit_rate is None or result.hit_rate <= 0.90:
        print(f"SMOKE FAIL hit_rate={result.hit_rate}")
        return 1

    report = write_commercial_report(
        tmp / "informe.xlsx",
        led_brands=result.brands,
        fixed_brands=result.fixed_brands,
        slots=slots,
        compliance=result.compliance,
        hit_rate=result.hit_rate,
        analyzed_seconds=result.analyzed_seconds,
    )
    if not report.is_file():
        print("SMOKE FAIL missing xlsx")
        return 1

    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
