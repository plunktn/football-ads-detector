from typing import Literal

from pydantic import BaseModel, Field, field_validator


JobStatus = Literal[
    "queued",
    "detecting_kickoff",
    "processing",
    "completed",
    "error",
]
JobMode = Literal["single", "split"]
DurationMode = Literal["5min", "10min", "full"]


class BrandInput(BaseModel):
    id: str | None = None
    name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("El nombre de la marca no puede estar vacío.")
        return value


class JobConfig(BaseModel):
    mode: JobMode
    duration_mode: DurationMode
    sample_fps: int = 1


class Kickoff(BaseModel):
    first_half_video_seconds: float = 0.0
    second_half_video_seconds: float | None = None
    note: str = "fallback t=0"


class BrandResult(BaseModel):
    brand_id: str
    name: str
    appearances: int = 0
    total_seconds: int = 0
    minutes: int = 0
    seconds: int = 0
    start_frames: list[int] = Field(default_factory=list)


class JobResult(BaseModel):
    analyzed_seconds: int = 0
    brands: list[BrandResult] = Field(default_factory=list)


class JobResponse(BaseModel):
    id: str
    status: JobStatus
    progress: float = 0.0
    progress_label: str = ""
    error: str | None = None
    config: JobConfig
    kickoff: Kickoff | None = None
    result: JobResult | None = None


class JobEvent(BaseModel):
    status: JobStatus
    progress: float
    progress_label: str
    kickoff: Kickoff | None = None
    partial_brands: list[BrandResult] = Field(default_factory=list)
    error: str | None = None
