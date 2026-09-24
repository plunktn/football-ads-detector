"""Durable 1T kickoff and 2T start overrides.

Profiles live in ``backend/config/clock_overrides.yaml``. They are local
operator config: job uploads may override a field for one run, and nothing
here is pushed through the cloud brand/stadium sync.

A ``continuous`` clock does not return to 00:00 at half-time, so the
scoreboard reset scan cannot find 2T. Libertad vs Orense is the QA example:
2T starts at about 4145 wall seconds of that full-match file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml


_DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "clock_overrides.yaml"
_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_MODES = {"reset", "continuous"}

_HEADER = """# Overrides durables de kickoff / 2T.
# Segundos de pared de ESTE archivo de video. No viajan por el sync de cloud
# y no se copian a otro partido.
# clock_mode:
#   reset       — el marcador vuelve cerca de 00:00 al empezar el 2T
#   continuous  — el reloj no se reinicia; sin second_half_start_sec el LED
#                 del segundo tiempo no entra al informe
"""


class ClockOverrideError(ValueError):
    """Operator-facing validation error for a clock profile or job request."""


@dataclass(frozen=True)
class ClockOverride:
    id: str
    label: str
    clock_mode: str
    kickoff_offset_sec: float | None
    second_half_start_sec: float | None
    notes: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "clock_mode": self.clock_mode,
            "kickoff_offset_sec": self.kickoff_offset_sec,
            "second_half_start_sec": self.second_half_start_sec,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class MergedClock:
    """Offsets that will be stored on the job. Explicit form values win."""

    profile_id: str | None
    kickoff_offset_sec: float | None
    second_half_start_sec: float | None
    clock_mode: str


def normalize_clock_mode(value: str | None) -> str:
    if value is None or str(value).strip() == "":
        return "reset"
    mode = str(value).strip().lower()
    if mode not in _MODES:
        raise ClockOverrideError("clock_mode debe ser reset o continuous.")
    return mode


def _optional_seconds(value: object, field_name: str) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ClockOverrideError(f"{field_name} debe ser un número.") from exc
    if number < 0:
        raise ClockOverrideError(f"{field_name} no puede ser negativo.")
    return number


def _validate_pair(
    kickoff_offset_sec: float | None,
    second_half_start_sec: float | None,
) -> None:
    if (
        kickoff_offset_sec is not None
        and second_half_start_sec is not None
        and second_half_start_sec <= kickoff_offset_sec
    ):
        raise ClockOverrideError(
            "second_half_start_sec debe ser posterior al kickoff de 1T."
        )


def _profile_from_raw(raw: object) -> ClockOverride:
    if not isinstance(raw, dict):
        raise ClockOverrideError("Cada perfil de reloj debe ser un objeto.")
    profile_id = str(raw.get("id") or "").strip()
    if not _ID_RE.fullmatch(profile_id):
        raise ClockOverrideError(
            "El id del perfil usa minúsculas, números y guiones (ej. libertad-vs-orense)."
        )
    label = str(raw.get("label") or profile_id).strip() or profile_id
    kickoff = _optional_seconds(raw.get("kickoff_offset_sec"), "kickoff_offset_sec")
    second = _optional_seconds(
        raw.get("second_half_start_sec"), "second_half_start_sec"
    )
    _validate_pair(kickoff, second)
    notes = raw.get("notes") or ""
    return ClockOverride(
        id=profile_id,
        label=label,
        clock_mode=normalize_clock_mode(
            None if raw.get("clock_mode") is None else str(raw.get("clock_mode"))
        ),
        kickoff_offset_sec=kickoff,
        second_half_start_sec=second,
        notes=str(notes).strip(),
    )


def load_clock_overrides(path: str | Path | None = None) -> list[ClockOverride]:
    source = Path(path) if path else _DEFAULT_PATH
    if not source.is_file():
        return []
    raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ClockOverrideError("clock_overrides.yaml debe ser un mapeo.")
    profiles = raw.get("profiles") or []
    if not isinstance(profiles, list):
        raise ClockOverrideError("profiles debe ser una lista.")
    loaded = [_profile_from_raw(item) for item in profiles]
    ids = [item.id for item in loaded]
    if len(ids) != len(set(ids)):
        raise ClockOverrideError("Hay dos perfiles de reloj con el mismo id.")
    return loaded


def get_clock_override(
    profile_id: str,
    path: str | Path | None = None,
) -> ClockOverride:
    key = profile_id.strip()
    for profile in load_clock_overrides(path):
        if profile.id == key:
            return profile
    raise ClockOverrideError(f"Perfil de reloj desconocido: {profile_id!r}.")


def save_clock_overrides(
    profiles: list[ClockOverride],
    path: str | Path | None = None,
) -> Path:
    source = Path(path) if path else _DEFAULT_PATH
    source.parent.mkdir(parents=True, exist_ok=True)
    payload = {"profiles": [item.as_dict() for item in profiles]}
    body = yaml.safe_dump(
        payload,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )
    source.write_text(_HEADER + body, encoding="utf-8")
    return source


def upsert_clock_override(
    profile_id: str,
    fields: dict[str, object],
    path: str | Path | None = None,
) -> ClockOverride:
    """Insert or replace one profile and rewrite the YAML."""
    key = profile_id.strip()
    raw = dict(fields)
    raw["id"] = key
    incoming = _profile_from_raw(raw)
    current = load_clock_overrides(path)
    replaced = False
    updated: list[ClockOverride] = []
    for profile in current:
        if profile.id == incoming.id:
            updated.append(incoming)
            replaced = True
        else:
            updated.append(profile)
    if not replaced:
        updated.append(incoming)
    save_clock_overrides(updated, path)
    return incoming


def merge_clock_request(
    *,
    profile_id: str | None,
    kickoff_offset_sec: float | None,
    second_half_start_sec: float | None,
    clock_mode: str | None,
    path: str | Path | None = None,
) -> MergedClock:
    """Fill empty job fields from a saved profile. Explicit numbers win.

    ``clock_mode=None`` means the form did not send a mode, so the profile
    mode is kept. An empty profile id is a one-off job.
    """
    kickoff = _optional_seconds(kickoff_offset_sec, "kickoff_offset_sec")
    second = _optional_seconds(second_half_start_sec, "second_half_start_sec")
    explicit_mode = None if clock_mode is None or str(clock_mode).strip() == "" else (
        normalize_clock_mode(clock_mode)
    )
    selected: ClockOverride | None = None
    clean_id = profile_id.strip() if isinstance(profile_id, str) else ""
    if clean_id:
        selected = get_clock_override(clean_id, path)
        if kickoff is None:
            kickoff = selected.kickoff_offset_sec
        if second is None:
            second = selected.second_half_start_sec
    _validate_pair(kickoff, second)
    mode = explicit_mode or (selected.clock_mode if selected else "reset")
    return MergedClock(
        profile_id=selected.id if selected else None,
        kickoff_offset_sec=kickoff,
        second_half_start_sec=second,
        clock_mode=mode,
    )
