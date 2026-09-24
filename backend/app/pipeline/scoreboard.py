import re
from collections.abc import Callable
from pathlib import Path

import cv2

from ..domain.stadium import CameraProfile
from ..exceptions import JobCancelled
from ..schemas import Kickoff
from .ocr import read_image_text
from .video import get_video_info, read_frame_at_seconds


def _check_cancel(should_cancel: Callable[[], bool] | None) -> None:
    if should_cancel is not None and should_cancel():
        raise JobCancelled("Detenido por el usuario")


def scoreboard_crop(frame, profile: CameraProfile | None = None):
    """Return only the broadcast scoreboard area, never the LED area."""
    height, width = frame.shape[:2]
    if profile is None:
        return frame[0 : int(0.22 * height), 0 : int(0.42 * width)]
    crop = profile.scoreboard_crop
    x0 = int(crop.x * width)
    y0 = int(crop.y * height)
    x1 = min(width, int((crop.x + crop.w) * width))
    y1 = min(height, int((crop.y + crop.h) * height))
    return frame[y0:y1, x0:x1]


def read_scoreboard_text(frame, profile: CameraProfile | None = None) -> str:
    """OCR the fixed upper-left scoreboard crop only."""
    return read_image_text(scoreboard_crop(frame, profile))


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
    camera_profile: CameraProfile | None = None,
    should_cancel: Callable[[], bool] | None = None,
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
            _check_cancel(should_cancel)
            ok, frame, _ = read_frame_at_seconds(cap, t)
            if ok and frame is not None:
                text = read_scoreboard_text(frame, camera_profile)
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
                        _check_cancel(should_cancel)
                        ok_r, frame_r, _ = read_frame_at_seconds(cap, rt)
                        if ok_r and frame_r is not None:
                            text_r = read_scoreboard_text(frame_r, camera_profile)
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
    camera_profile: CameraProfile | None = None,
    should_cancel: Callable[[], bool] | None = None,
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
            _check_cancel(should_cancel)
            ok, frame, _ = read_frame_at_seconds(cap, t)
            if ok and frame is not None:
                text = read_scoreboard_text(frame, camera_profile)
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


def apply_kickoff_overrides(
    kickoff: Kickoff,
    *,
    kickoff_offset_sec: float | None = None,
    second_half_start_sec: float | None = None,
) -> Kickoff:
    """Replace detected kickoffs when the operator supplies video-second offsets."""
    updates: dict[str, float | str] = {}
    notes: list[str] = []
    if kickoff_offset_sec is not None:
        updates["first_half_video_seconds"] = float(kickoff_offset_sec)
        notes.append("kickoff_offset_sec")
    if second_half_start_sec is not None:
        updates["second_half_start_sec"] = float(second_half_start_sec)
        notes.append("second_half_start_sec")
    if not updates:
        return kickoff
    # second_half_start_sec maps to Kickoff.second_half_video_seconds
    mapped = dict(updates)
    if "second_half_start_sec" in mapped:
        mapped["second_half_video_seconds"] = mapped.pop("second_half_start_sec")
    mapped["note"] = f"{kickoff.note}; overrides: {', '.join(notes)}"
    return kickoff.model_copy(update=mapped)


def resolve_kickoff(
    video_paths: list[str | Path],
    mode: str,
    duration_mode: str = "full",
    *,
    kickoff_offset_sec: float | None = None,
    second_half_start_sec: float | None = None,
    clock_mode: str | None = None,
    camera_profile: CameraProfile | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> tuple[Kickoff, list[str]]:
    """Resolve kickoff using operator overrides when present; skip OCR scan if both given.

    Returns ``(kickoff, warnings)``. Warnings are operator-facing strings (e.g. missing 2T).
    ``clock_mode="continuous"`` never scans for a reset to 00:00. Without
    ``second_half_start_sec`` the 2T LED window is omitted and the warning says so.
    Never reuse a fixed second-half second like 3521 or 4145 across matches.
    """
    warnings: list[str] = []
    mode_norm = _normalize_clock_mode(clock_mode)
    need_second_half = duration_mode == "full"
    has_1t = kickoff_offset_sec is not None
    has_2t = second_half_start_sec is not None
    continuous = mode_norm == "continuous"

    def finish(kickoff: Kickoff) -> tuple[Kickoff, list[str]]:
        if (
            has_1t
            and has_2t
            and float(second_half_start_sec) <= float(kickoff_offset_sec)
        ):
            warnings.append(_second_half_order_message())
        past_end = _warn_if_second_half_past_end(
            video_paths, mode, kickoff.second_half_video_seconds
        )
        if past_end:
            warnings.append(past_end)
        return _with_clock_note(kickoff, mode_norm), warnings

    if has_1t and (has_2t or not need_second_half):
        kickoff = Kickoff(
            first_half_video_seconds=float(kickoff_offset_sec),
            second_half_video_seconds=(
                float(second_half_start_sec) if has_2t else None
            ),
            note="overrides_only",
        )
        return finish(kickoff)

    if has_1t and need_second_half and not has_2t:
        first = float(kickoff_offset_sec)
        second = None
        if continuous:
            warnings.append(second_half_omitted_message("continuous"))
            note = "kickoff_offset_sec; continuous_clock; 2T no cargado"
        elif video_paths:
            path = video_paths[0] if mode != "split" else (
                video_paths[1] if len(video_paths) >= 2 else video_paths[0]
            )
            try:
                duration = get_video_info(path).duration_seconds
            except ValueError:
                duration = 0.0
            if mode == "split" and len(video_paths) >= 2:
                second = _scan_for_kickoff(
                    video_paths[1],
                    expected_half="2T",
                    camera_profile=camera_profile,
                    should_cancel=should_cancel,
                )
            else:
                second = _detect_second_half_single(
                    video_paths[0],
                    first,
                    duration,
                    camera_profile=camera_profile,
                    should_cancel=should_cancel,
                )
            if second is None:
                warnings.append(
                    "2T no detectado tras override de 1T; el LED del segundo "
                    "tiempo no entra al informe. Mide el inicio en ESTE archivo "
                    "(no copies 3521 ni 4145 de otro partido)."
                )
                note = "kickoff_offset_sec; 2T scan failed"
            else:
                note = "kickoff_offset_sec; 2T detectado por marcador"
        else:
            warnings.append(second_half_omitted_message(mode_norm))
            note = "kickoff_offset_sec; 2T scan failed"
        return finish(
            Kickoff(
                first_half_video_seconds=first,
                second_half_video_seconds=second,
                note=note,
            )
        )

    if has_2t and not has_1t:
        kickoff = detect_kickoffs(
            video_paths,
            mode,
            duration_mode,
            camera_profile=camera_profile,
            should_cancel=should_cancel,
            clock_mode=mode_norm,
        )
        kickoff = apply_kickoff_overrides(
            kickoff,
            second_half_start_sec=second_half_start_sec,
        )
        if "fallback" in kickoff.note or kickoff.first_half_video_seconds == 0.0:
            warnings.append(
                "1T usó detección/fallback; revisá el offset de kickoff de este partido."
            )
        return finish(kickoff)

    kickoff = detect_kickoffs(
        video_paths,
        mode,
        duration_mode,
        camera_profile=camera_profile,
        should_cancel=should_cancel,
        clock_mode=mode_norm,
    )
    if need_second_half and kickoff.second_half_video_seconds is None:
        warnings.append(second_half_omitted_message(mode_norm))
    return finish(kickoff)


def second_half_omitted_message(clock_mode: str = "reset") -> str:
    """Operator warning when a full-match run will not count 2T LED time."""
    if clock_mode == "continuous":
        return (
            "Reloj continuo: no hay vuelta a 00:00 y el 2T no se detecta solo. "
            "El LED del segundo tiempo no entra al informe hasta que cargues "
            "second_half_start_sec de ESTE archivo "
            "(Libertad vs Orense ≈ 4145 s; no lo copies a otro partido)."
        )
    return (
        "2T no detectado por marcador; el LED del segundo tiempo no entra al informe. "
        "Cargá second_half_start_sec medido en este video "
        "(offsets no son portables entre partidos)."
    )


def _second_half_past_end_message() -> str:
    return (
        "El inicio de 2T cae al final o después del archivo; "
        "el LED del segundo tiempo no entra al informe."
    )


def _second_half_order_message() -> str:
    return (
        "El inicio de 2T no es posterior al kickoff de 1T; "
        "el LED del segundo tiempo no entra al informe."
    )


def _normalize_clock_mode(clock_mode: str | None) -> str:
    mode = (clock_mode or "reset").strip().lower()
    if mode not in {"reset", "continuous"}:
        return "reset"
    return mode


def _warn_if_second_half_past_end(
    video_paths: list[str | Path],
    mode: str,
    second_half_start_sec: float | None,
) -> str | None:
    if second_half_start_sec is None or not video_paths or mode == "split":
        return None
    try:
        duration = get_video_info(video_paths[0]).duration_seconds
    except ValueError:
        return None
    if float(second_half_start_sec) >= duration - 1e-6:
        return _second_half_past_end_message()
    return None


def _with_clock_note(kickoff: Kickoff, clock_mode: str) -> Kickoff:
    if clock_mode != "continuous" or "continuous_clock" in kickoff.note:
        return kickoff
    return kickoff.model_copy(update={"note": f"{kickoff.note}; continuous_clock"})


def detect_kickoffs(
    video_paths: list[str | Path],
    mode: str,
    duration_mode: str = "full",
    camera_profile: CameraProfile | None = None,
    should_cancel: Callable[[], bool] | None = None,
    *,
    clock_mode: str = "reset",
) -> Kickoff:
    """Detect kickoff positions for single or split uploads.

    The first-half scan covers up to ~15 minutes of file time so pre-match
    tunnel footage does not force a t=0 fallback. Second-half search is skipped
    for short analysis windows.
    """
    if not video_paths:
        return Kickoff(note="fallback t=0")

    clock_mode = _normalize_clock_mode(clock_mode)
    need_second_half = duration_mode == "full"

    if mode == "split" and len(video_paths) >= 2:
        first = _scan_for_kickoff(
            video_paths[0],
            expected_half="1T",
            camera_profile=camera_profile,
            should_cancel=should_cancel,
        )
        second = (
            _scan_for_kickoff(
                video_paths[1],
                expected_half="2T",
                camera_profile=camera_profile,
                should_cancel=should_cancel,
            )
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
    first = _scan_for_kickoff(
        path,
        expected_half="1T",
        camera_profile=camera_profile,
        should_cancel=should_cancel,
    )
    first_value = first if first is not None else 0.0
    second = None
    try:
        duration = get_video_info(path).duration_seconds
    except ValueError:
        duration = 0.0
    # A continuous clock never resets to 00:00, so a reset scan cannot find 2T
    # and must not drop that half in silence. The operator supplies the wall
    # second (Libertad vs Orense ≈ 4145).
    if need_second_half and first is not None and clock_mode != "continuous":
        second = _detect_second_half_single(
            path,
            first,
            duration,
            camera_profile=camera_profile,
            should_cancel=should_cancel,
        )

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
