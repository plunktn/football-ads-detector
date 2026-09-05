import json
import logging
import shutil
from pathlib import Path

from .settings import keep_job_videos


logger = logging.getLogger(__name__)


def purge_job_media(directory: Path, video_paths: list[Path]) -> list[Path]:
    """Remove uploaded videos and debug crops; keep JSON/XLSX deliverables."""
    removed: list[Path] = []
    for video_path in video_paths:
        if video_path.is_file():
            video_path.unlink()
            removed.append(video_path)

    debug_dir = directory / "debug"
    if debug_dir.is_dir():
        shutil.rmtree(debug_dir, ignore_errors=True)
        removed.append(debug_dir)

    meta_path = directory / "meta.json"
    if meta_path.is_file():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["video_paths"] = []
        meta["media_purged"] = True
        meta_path.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    if removed:
        logger.info(
            "Purged job media in %s (%s item(s))",
            directory,
            len(removed),
        )
    return removed


def maybe_purge_job_media(directory: Path, video_paths: list[Path]) -> list[Path]:
    if keep_job_videos():
        return []
    return purge_job_media(directory, video_paths)
