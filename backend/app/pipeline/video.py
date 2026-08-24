from dataclasses import dataclass
from pathlib import Path

import cv2


@dataclass(frozen=True)
class VideoInfo:
    path: Path
    fps: float
    frame_count: int
    duration_seconds: float
    width: int
    height: int


def read_frame_at_seconds(cap: cv2.VideoCapture, t: float):
    """Seek to a time position and return the frame plus its source index."""
    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
    ok, frame = cap.read()
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_idx = int(round(t * fps))
    return ok, frame, frame_idx


def get_video_info(path: str | Path) -> VideoInfo:
    video_path = Path(path)
    cap = cv2.VideoCapture(str(video_path))
    try:
        if not cap.isOpened():
            raise ValueError(f"No se pudo abrir el video: {video_path.name}")

        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        duration = frame_count / fps if frame_count and fps else 0.0
        return VideoInfo(
            path=video_path,
            fps=float(fps),
            frame_count=frame_count,
            duration_seconds=float(duration),
            width=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0),
            height=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0),
        )
    finally:
        cap.release()
