"""Load stadium camera profiles from YAML files under backend/config/stadiums/."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from app.domain.stadium import CameraProfile, Stadium

DEFAULT_STADIUM_ID = "ligaecuabet"
_STADIUMS_DIR = Path(__file__).resolve().parents[2] / "config" / "stadiums"


def _stadium_yaml_path(stadium_id: str) -> Path:
    return _STADIUMS_DIR / f"{stadium_id}.yaml"


def _load_stadium(stadium_id: str) -> Stadium:
    path = _stadium_yaml_path(stadium_id)
    if not path.is_file():
        raise FileNotFoundError(f"Stadium profile not found: {stadium_id!r} ({path})")

    with path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)

    if not isinstance(raw, dict):
        raise ValidationError.from_exception_data(
            "Stadium",
            [{"type": "dict_type", "loc": (), "input": raw, "msg": "YAML root must be a mapping."}],
        )

    return Stadium.model_validate(raw)


def load_stadium_profile(stadium_id: str = DEFAULT_STADIUM_ID) -> CameraProfile:
    """Return the default camera profile for a stadium."""
    stadium = _load_stadium(stadium_id)
    if stadium.camera.id != stadium.default_camera:
        raise ValueError(
            f"Stadium {stadium_id!r} default_camera={stadium.default_camera!r} "
            f"does not match camera.id={stadium.camera.id!r}."
        )
    return stadium.camera


def list_stadiums() -> list[str]:
    """Return stadium ids for every *.yaml file in the config directory."""
    if not _STADIUMS_DIR.is_dir():
        return []
    return sorted(path.stem for path in _STADIUMS_DIR.glob("*.yaml"))


def save_stadium_yaml(stadium: Stadium, directory: Path | None = None) -> Path:
    """Write a stadium profile YAML. Overwrites the file for that stadium_id."""
    dest_dir = directory or _STADIUMS_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / f"{stadium.id}.yaml"
    payload = stadium.model_dump(mode="json")
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(
            payload,
            handle,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )
    return path
