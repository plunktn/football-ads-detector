import re
from pathlib import Path

import cv2

from ..schemas import Kickoff
from .ocr import read_image_text
from .video import get_video_info, read_frame_at_seconds


def scoreboard_crop(frame):
    """Return only the broadcast scoreboard area, never the LED area."""
    height, width = frame.shape[:2]
    return frame[0 : int(0.22 * height), 0 : int(0.42 * width)]


def read_scoreboard_text(frame) -> str:
    """OCR the fixed upper-left scoreboard crop only."""
    return read_image_text(scoreboard_crop(frame))


def parse_clock(text: str) -> int | None:
    """Parse the first valid mm:ss value from OCR text."""
    for minutes, seconds in re.findall(r"\b(\d{1,2}):(\d{2})\b", text):
        seconds_int = int(seconds)
        if seconds_int <= 59:
            return int(minutes) * 60 + seconds_int
    return None


def parse_half(text: str) -> str | None:
    tokens = re.findall(r"[A-Z0-9]+", text.upper())
    if "1T" in tokens or "PT" in tokens:
        return "1T"
    if "2T" in tokens or "ST" in tokens:
        return "2T"
    return None


def _scan_for_kickoff(
    path: str | Path,
    *,
    expected_half: str | None,
    start_seconds: float = 0.0,
    max_seconds: float = 900.0,
) -> float | None:
    """Scan up to ~15 minutes for the first low scoreboard clock.

    Full-match files often include tunnel / warm-up before 1T, so a 2-minute
    window falls back to t=0 and skips the actual LED analysis window.

    Seeking on long broadcast MP4s is expensive, so the coarse pass uses a
    15-second stride and then refines around ``t - clock``.
    """
    try:
        info = get_video_info(path)
    except ValueError:
        return None

    if info.duration_seconds <= start_seconds:
        return None

    cap = cv2.VideoCapture(str(path))
    try:
        end_seconds = min(info.duration_seconds, start_seconds + max_seconds)
        t = max(0.0, start_seconds)
        while t < end_seconds:
            ok, frame, _ = read_frame_at_seconds(cap, t)
            if ok and frame is not None:
                text = read_scoreboard_text(frame)
                clock = parse_clock(text)
                half = parse_half(text)
                if clock is not None and clock <= 8 and (
                    expected_half is None or half == expected_half or half is None
                ):
                    return t
                # Running clock ⇒ estimate kickoff and refine nearby.
                if clock is not None and clock <= 20 * 60:
                    estimated = max(0.0, t - float(clock))
                    refine_start = max(0.0, estimated - 4.0)
                    refine_end = min(end_seconds, estimated + 25.0)
                    best = None
                    rt = refine_start
                    while rt < refine_end:
                        ok_r, frame_r, _ = read_frame_at_seconds(cap, rt)
                        if ok_r and frame_r is not None:
                            text_r = read_scoreboard_text(frame_r)
                            clock_r = parse_clock(text_r)
                            half_r = parse_half(text_r)
                            if clock_r is not None and clock_r <= 8 and (
                                expected_half is None
                                or half_r == expected_half
                                or half_r is None
                            ):
                                return rt
                            if clock_r is not None and clock_r <= 20:
                                candidate = max(0.0, rt - float(clock_r))
                                if best is None or clock_r < best[0]:
                                    best = (clock_r, candidate)
                        rt += 2.0
                    if best is not None:
                        return best[1]
                    return estimated
            t += 15.0
    finally:
        cap.release()
    return None


def _detect_second_half_single(
    path: str | Path,
    first_half_seconds: float,
    duration_seconds: float,
) -> float | None:
    """Find a 2T reset in a complete-match recording."""
    if duration_seconds < 40 * 60:
        return None

    start = max(first_half_seconds + 35 * 60, 35 * 60)
    cap = cv2.VideoCapture(str(path))
    seen_late_first_half = False
    previous_clock: int | None = None
    try:
        t = start
        while t < duration_seconds:
            ok, frame, _ = read_frame_at_seconds(cap, t)
            if ok and frame is not None:
                text = read_scoreboard_text(frame)
                clock = parse_clock(text)
                half = parse_half(text)
                if clock is not None and clock >= 40 * 60:
                    seen_late_first_half = True
                if (
                    clock is not None
                    and clock <= 8
                    and seen_late_first_half
                    and (half == "2T" or half is None)
                ):
                    return t
                if (
                    clock is not None
                    and previous_clock is not None
                    and seen_late_first_half
                    and previous_clock >= 40 * 60
                    and clock <= 8
                ):
                    return t
                if clock is not None:
                    previous_clock = clock
            t += 5.0
    finally:
        cap.release()
    return None


def detect_kickoffs(
    video_paths: list[str | Path],
    mode: str,
    duration_mode: str = "full",
) -> Kickoff:
    """Detect kickoff positions for single or split uploads.

    The first-half scan covers up to ~15 minutes of file time so pre-match
    tunnel footage does not force a t=0 fallback. Second-half search is skipped
    for short analysis windows.
    """
    if not video_paths:
        return Kickoff(note="fallback t=0")

    need_second_half = duration_mode == "full"

    if mode == "split" and len(video_paths) >= 2:
        first = _scan_for_kickoff(video_paths[0], expected_half="1T")
        second = (
            _scan_for_kickoff(video_paths[1], expected_half="2T")
            if need_second_half
            else None
        )
        first_value = first if first is not None else 0.0
        second_value = second if second is not None else (0.0 if need_second_half else None)
        missing = []
        if first is None:
            missing.append("1T")
        if need_second_half and second is None:
            missing.append("2T")
        note = (
            f"fallback t=0 ({', '.join(missing)})"
            if missing
            else "detectado por marcador"
        )
        return Kickoff(
            first_half_video_seconds=first_value,
            second_half_video_seconds=second_value,
            note=note,
        )

    path = video_paths[0]
    first = _scan_for_kickoff(path, expected_half="1T")
    first_value = first if first is not None else 0.0
    second = None
    try:
        duration = get_video_info(path).duration_seconds
    except ValueError:
        duration = 0.0
    if need_second_half and first is not None:
        second = _detect_second_half_single(path, first, duration)

    if first is None and second is None:
        note = "fallback t=0"
    elif second is None and need_second_half:
        note = "1T detectado por marcador; 2T no encontrado"
    elif second is None:
        note = "detectado por marcador"
    else:
        note = "detectado por marcador"
    return Kickoff(
        first_half_video_seconds=first_value,
        second_half_video_seconds=second,
        note=note,
    )
