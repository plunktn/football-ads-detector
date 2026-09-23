"""Time-based on/off hysteresis for LED brand exposure.

Same brand + same half: short holes stay inside one interval. Duration is the
wall-clock span from the first positive sample through the end of the last
one (``last + sample_interval``), including the bridged hole. A different
brand's positive detection inside the hole closes the interval. Halves are
never joined.

Knobs (environment, optional):

* ``LED_MERGE_GAP_SEC`` (default 8): maximum hole, in seconds, that still
  belongs to the same appearance.
* ``LED_OFF_HOLD_SEC`` (default: the merge gap): absence that closes an open
  appearance before a later hit can extend it. When this is smaller than the
  merge gap, a second pass still joins same-brand holes up to the merge gap
  if no other brand was seen inside them.
* ``LED_ON_CONFIRM_SEC`` (default 0): consecutive positive seconds required
  to open an appearance. ``0`` opens on the first hit.

Fixed boards do not use these defaults. Invalid or negative values fall back
to the defaults above.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DEFAULT_LED_MERGE_GAP_SEC = 8.0
DEFAULT_LED_ON_CONFIRM_SEC = 0.0


@dataclass(frozen=True)
class LedTiming:
    merge_gap_sec: float = DEFAULT_LED_MERGE_GAP_SEC
    on_confirm_sec: float = DEFAULT_LED_ON_CONFIRM_SEC
    off_hold_sec: float = DEFAULT_LED_MERGE_GAP_SEC


@dataclass(frozen=True)
class PresenceSample:
    half: str
    time_seconds: float
    present: bool
    blocked: bool = False
    frame_idx: int = 0
    zone_id: str | None = None
    posicion: str | None = None
    tipo_panel: str | None = None
    source_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class PresenceInterval:
    half: str
    start_seconds: float
    end_seconds: float
    last_sighting_seconds: float
    duration_seconds: int
    start_frame: int
    end_frame: int
    zone_id: str | None
    posicion: str | None
    tipo_panel: str | None
    source_ids: tuple[int, ...]


def _env_float(name: str, default: float) -> tuple[float, bool]:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default, False
    try:
        value = float(raw.strip())
    except ValueError:
        logger.warning("Ignoring invalid %s=%r; using %s", name, raw, default)
        return default, False
    if value < 0:
        logger.warning("Ignoring negative %s=%s; using %s", name, value, default)
        return default, False
    return value, True


def load_led_timing() -> LedTiming:
    """Read LED gap / on / off knobs. Unset off-hold follows the merge gap."""
    gap, _gap_set = _env_float("LED_MERGE_GAP_SEC", DEFAULT_LED_MERGE_GAP_SEC)
    on_confirm, _on_set = _env_float("LED_ON_CONFIRM_SEC", DEFAULT_LED_ON_CONFIRM_SEC)
    hold, hold_set = _env_float("LED_OFF_HOLD_SEC", gap)
    if not hold_set:
        hold = gap
    return LedTiming(
        merge_gap_sec=gap,
        on_confirm_sec=on_confirm,
        off_hold_sec=hold,
    )


def wall_clock_seconds(start_seconds: float, end_seconds: float) -> int:
    """Integer seconds of a half-open coverage window. At least 1 when non-empty."""
    span = end_seconds - start_seconds
    if span <= 0:
        return 0
    return max(1, int(round(span)))


def _confirmed(coverage_seconds: float, on_confirm_sec: float) -> bool:
    if on_confirm_sec <= 0:
        return True
    return coverage_seconds + 1e-9 >= on_confirm_sec


def _collapse(samples: Sequence[PresenceSample]) -> list[PresenceSample]:
    """One sample per (half, timestamp). A positive wins over a foreign brand."""
    groups: dict[tuple[str, float], list[PresenceSample]] = {}
    for sample in samples:
        groups.setdefault((sample.half, sample.time_seconds), []).append(sample)
    collapsed: list[PresenceSample] = []
    for half, time_seconds in sorted(groups, key=lambda key: (key[0], key[1])):
        group = groups[(half, time_seconds)]
        present = [sample for sample in group if sample.present]
        if present:
            primary = present[0]
            source_ids = tuple(
                source_id
                for sample in present
                for source_id in sample.source_ids
            )
            collapsed.append(
                PresenceSample(
                    half=half,
                    time_seconds=time_seconds,
                    present=True,
                    blocked=False,
                    frame_idx=primary.frame_idx,
                    zone_id=primary.zone_id,
                    posicion=primary.posicion,
                    tipo_panel=primary.tipo_panel,
                    source_ids=source_ids,
                )
            )
            continue
        blocked = [sample for sample in group if sample.blocked]
        primary = blocked[0] if blocked else group[0]
        collapsed.append(
            PresenceSample(
                half=half,
                time_seconds=time_seconds,
                present=False,
                blocked=bool(blocked),
                frame_idx=primary.frame_idx,
                zone_id=primary.zone_id,
                posicion=primary.posicion,
                tipo_panel=primary.tipo_panel,
                source_ids=(),
            )
        )
    return collapsed


@dataclass
class _OpenRun:
    half: str
    start: float
    start_frame: int
    last: float
    last_frame: int
    zone_id: str | None
    posicion: str | None
    tipo_panel: str | None
    coverage: float
    confirmed: bool
    source_ids: list[int]


def _start_run(sample: PresenceSample, sample_interval: float, on_confirm_sec: float) -> _OpenRun:
    coverage = sample_interval
    return _OpenRun(
        half=sample.half,
        start=sample.time_seconds,
        start_frame=sample.frame_idx,
        last=sample.time_seconds,
        last_frame=sample.frame_idx,
        zone_id=sample.zone_id,
        posicion=sample.posicion,
        tipo_panel=sample.tipo_panel,
        coverage=coverage,
        confirmed=_confirmed(coverage, on_confirm_sec),
        source_ids=list(sample.source_ids),
    )


def _emit(run: _OpenRun, sample_interval: float) -> PresenceInterval | None:
    if not run.confirmed:
        return None
    end = run.last + sample_interval
    return PresenceInterval(
        half=run.half,
        start_seconds=run.start,
        end_seconds=end,
        last_sighting_seconds=run.last,
        duration_seconds=wall_clock_seconds(run.start, end),
        start_frame=run.start_frame,
        end_frame=run.last_frame,
        zone_id=run.zone_id,
        posicion=run.posicion,
        tipo_panel=run.tipo_panel,
        source_ids=tuple(run.source_ids),
    )


def _merge_half(
    rows: Sequence[PresenceSample],
    *,
    sample_interval: float,
    on_confirm_sec: float,
    off_hold_sec: float,
) -> list[PresenceInterval]:
    intervals: list[PresenceInterval] = []
    run: _OpenRun | None = None

    def close() -> None:
        nonlocal run
        if run is None:
            return
        emitted = _emit(run, sample_interval)
        if emitted is not None:
            intervals.append(emitted)
        run = None

    for sample in rows:
        if sample.present:
            if run is None:
                run = _start_run(sample, sample_interval, on_confirm_sec)
                continue
            gap = sample.time_seconds - (run.last + sample_interval)
            if run.confirmed and gap > off_hold_sec + 1e-9:
                close()
                run = _start_run(sample, sample_interval, on_confirm_sec)
                continue
            if not run.confirmed and gap > 1e-6:
                run = _start_run(sample, sample_interval, on_confirm_sec)
                continue
            if not run.confirmed:
                run.coverage += sample_interval
                run.confirmed = _confirmed(run.coverage, on_confirm_sec)
            run.last = sample.time_seconds
            run.last_frame = sample.frame_idx
            run.source_ids.extend(sample.source_ids)
            continue
        if run is None:
            continue
        if not run.confirmed or sample.blocked:
            close()
    close()
    return intervals


def _blocked_between(
    previous: PresenceInterval,
    nxt: PresenceInterval,
    blockers: Sequence[PresenceSample],
) -> bool:
    hole_start = previous.end_seconds
    hole_end = nxt.start_seconds
    if hole_end <= hole_start + 1e-9:
        return False
    for sample in blockers:
        if sample.half != previous.half:
            continue
        if hole_start - 1e-9 <= sample.time_seconds < hole_end - 1e-9:
            return True
    return False


def _combine(previous: PresenceInterval, nxt: PresenceInterval) -> PresenceInterval:
    end = max(previous.end_seconds, nxt.end_seconds)
    if nxt.last_sighting_seconds >= previous.last_sighting_seconds:
        last_sighting = nxt.last_sighting_seconds
        end_frame = nxt.end_frame
    else:
        last_sighting = previous.last_sighting_seconds
        end_frame = previous.end_frame
    return PresenceInterval(
        half=previous.half,
        start_seconds=previous.start_seconds,
        end_seconds=end,
        last_sighting_seconds=last_sighting,
        duration_seconds=wall_clock_seconds(previous.start_seconds, end),
        start_frame=previous.start_frame,
        end_frame=end_frame,
        zone_id=previous.zone_id or nxt.zone_id,
        posicion=previous.posicion or nxt.posicion,
        tipo_panel=previous.tipo_panel or nxt.tipo_panel,
        source_ids=previous.source_ids + nxt.source_ids,
    )


def _join_gaps(
    intervals: Sequence[PresenceInterval],
    blockers: Sequence[PresenceSample],
    *,
    merge_gap_sec: float,
) -> list[PresenceInterval]:
    if not intervals:
        return []
    ordered = sorted(
        intervals,
        key=lambda item: (item.half, item.start_seconds, item.end_seconds),
    )
    merged: list[PresenceInterval] = [ordered[0]]
    for nxt in ordered[1:]:
        previous = merged[-1]
        if nxt.half != previous.half:
            merged.append(nxt)
            continue
        gap = nxt.start_seconds - previous.end_seconds
        if gap <= merge_gap_sec + 1e-9 and not _blocked_between(previous, nxt, blockers):
            merged[-1] = _combine(previous, nxt)
            continue
        merged.append(nxt)
    return merged


def merge_presence(
    samples: Sequence[PresenceSample],
    *,
    sample_interval: float = 1.0,
    on_confirm_sec: float = 0.0,
    off_hold_sec: float = DEFAULT_LED_MERGE_GAP_SEC,
    merge_gap_sec: float = DEFAULT_LED_MERGE_GAP_SEC,
) -> list[PresenceInterval]:
    """Build same-half presence intervals from positive, absent, and blocking samples.

    ``blocked`` means another brand is positively on at that timestamp while
    this brand is not. Those timestamps cut the run and are not absorbed into
    its wall-clock duration.
    """
    if sample_interval <= 0:
        sample_interval = 1.0
    collapsed = _collapse(samples)
    by_half: dict[str, list[PresenceSample]] = {}
    for sample in collapsed:
        by_half.setdefault(sample.half, []).append(sample)
    intervals: list[PresenceInterval] = []
    for rows in by_half.values():
        intervals.extend(
            _merge_half(
                rows,
                sample_interval=sample_interval,
                on_confirm_sec=on_confirm_sec,
                off_hold_sec=off_hold_sec,
            )
        )
    blockers = [sample for sample in collapsed if sample.blocked and not sample.present]
    return _join_gaps(intervals, blockers, merge_gap_sec=merge_gap_sec)
