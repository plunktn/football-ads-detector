import re
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .config.stadiums import DEFAULT_STADIUM_ID
from .domain.stadium import CameraProfile


JobStatus = Literal[
    "queued",
    "detecting_kickoff",
    "processing",
    "completed",
    "cancelled",
    "error",
]
JobMode = Literal["single", "split"]
AnalysisMode = Literal["discovery", "playlist_verify"]
# "full" or "{N}min" (1–180), e.g. "5min", "16min", "22min".
DurationMode = str


class VerificationStatus(StrEnum):
    """Playlist-slot audit outcome. ``hit`` is derived: status == HIT."""

    HIT = "HIT"
    MISS = "MISS"
    NO_EVIDENCE = "NO_EVIDENCE"
    AMBIGUOUS = "AMBIGUOUS"
    OFFSET = "OFFSET"
    PAST_EOF = "PAST_EOF"


DOUBTFUL_STATUSES = frozenset(
    {
        VerificationStatus.NO_EVIDENCE,
        VerificationStatus.AMBIGUOUS,
        VerificationStatus.OFFSET,
    }
)

_DURATION_MIN_RE = re.compile(r"^(\d+)min$")
_MAX_CUSTOM_MINUTES = 180


def parse_duration_seconds(duration_mode: str) -> float | None:
    """Return window length in seconds, or None for full-match mode."""
    if duration_mode == "full":
        return None
    match = _DURATION_MIN_RE.fullmatch(duration_mode.strip())
    if not match:
        raise ValueError(
            "duration_mode debe ser 'full' o '{N}min' (ej. 5min, 16min, 22min)."
        )
    minutes = int(match.group(1))
    if minutes < 1 or minutes > _MAX_CUSTOM_MINUTES:
        raise ValueError(
            f"Los minutos deben estar entre 1 y {_MAX_CUSTOM_MINUTES}."
        )
    return float(minutes * 60)


def normalize_duration_mode(duration_mode: str) -> str:
    """Validate and normalize a duration_mode string."""
    value = duration_mode.strip()
    if value == "full":
        return value
    parse_duration_seconds(value)  # raises if invalid
    return value


class BrandInput(BaseModel):
    id: str | None = None
    name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    logo_path: str | None = None

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
    stadium_id: str | None = None
    analysis_mode: AnalysisMode = "discovery"
    kickoff_offset_sec: float | None = None
    second_half_start_sec: float | None = None
    include_fixed: bool = False

    @field_validator("duration_mode")
    @classmethod
    def validate_duration_mode(cls, value: str) -> str:
        return normalize_duration_mode(value)

    @field_validator("sample_fps")
    @classmethod
    def validate_sample_fps(cls, value: int) -> int:
        if value not in {1, 2}:
            raise ValueError("sample_fps debe ser 1 o 2.")
        return value

    @model_validator(mode="after")
    def default_stadium_id(self) -> "JobConfig":
        if self.stadium_id is None:
            self.stadium_id = DEFAULT_STADIUM_ID
        return self


class StadiumSummary(BaseModel):
    id: str
    nombre: str


class BrandSummary(BaseModel):
    id: str
    nombre: str
    aliases: list[str] = Field(default_factory=list)
    has_logo: bool = False
    group_id: str | None = None
    activo: bool = True


class BrandGroupSummary(BaseModel):
    id: str
    titulo: str
    brands: list[BrandSummary] = Field(default_factory=list)


BrandRefKind = Literal["logo", "image", "video_frame"]


class BrandRefSummary(BaseModel):
    id: str
    brand_id: str
    kind: BrandRefKind
    source_name: str | None = None
    image_url: str
    created_at: str


class BrandRefsCreateResponse(BaseModel):
    refs: list[BrandRefSummary] = Field(default_factory=list)


class CatalogFrame(BaseModel):
    id: int
    half: str
    frame_idx: int
    time_seconds: float
    zone_id: str | None = None
    posicion: str | None = None
    ocr_text: str = ""
    machine_label: str
    brand_id: str | None = None
    user_verdict: str | None = None
    image_url: str
    crop_image_url: str | None = None
    has_context: bool = False
    visual_hash: str | None = None
    similarity_group: int | None = None


class CatalogBrandBucket(BaseModel):
    brand_id: str
    name: str
    frames: list[CatalogFrame] = Field(default_factory=list)


class CatalogAssignableBrand(BaseModel):
    brand_id: str
    name: str


class CatalogProgress(BaseModel):
    positives: int = 0
    attention: int = 0
    empty: int = 0
    confirmed: bool = False


class CatalogResponse(BaseModel):
    job_id: str
    catalog_confirmed_at: str | None = None
    discarded_count: int = 0
    assignable_brands: list[CatalogAssignableBrand] = Field(default_factory=list)
    brands: list[CatalogBrandBucket] = Field(default_factory=list)
    attention: list[CatalogFrame] = Field(default_factory=list)
    empty: list[CatalogFrame] = Field(default_factory=list)
    progress: CatalogProgress = Field(default_factory=CatalogProgress)


class CatalogFramePatch(BaseModel):
    action: Literal["false_positive", "assign", "mark_empty"]
    brand_id: str | None = None


class ReportFrame(BaseModel):
    id: int
    half: str
    frame_idx: int
    time_seconds: float
    posicion: str | None = None
    ocr_text: str = ""
    image_url: str
    crop_image_url: str | None = None
    has_context: bool = False


class ReportSegment(BaseModel):
    half: str
    clock_start: str
    clock_end: str
    video_seconds_start: float
    video_seconds_end: float
    duration_seconds: int
    posicion: str | None = None
    frame_count: int = 0
    sample_frame: ReportFrame
    frames: list[ReportFrame] = Field(default_factory=list)


class ReportBrand(BaseModel):
    brand_id: str
    name: str
    appearances: int = 0
    total_seconds: int = 0
    minutes: int = 0
    seconds: int = 0
    duration_label: str = "0 s"
    frame_count: int = 0
    count_1t: int = 0
    count_2t: int = 0
    segments: list[ReportSegment] = Field(default_factory=list)


class ReportSummary(BaseModel):
    brand_count: int = 0
    appearances: int = 0
    total_seconds: int = 0
    duration_label: str = "0 s"
    minutes: int = 0
    seconds: int = 0


class CatalogReportResponse(BaseModel):
    job_id: str
    catalog_confirmed_at: str | None = None
    confirmed: bool = False
    stadium_id: str | None = None
    created_at: str | None = None
    summary: ReportSummary = Field(default_factory=ReportSummary)
    brands: list[ReportBrand] = Field(default_factory=list)
    analyzed_seconds: int | None = None


class Kickoff(BaseModel):
    first_half_video_seconds: float = 0.0
    second_half_video_seconds: float | None = None
    note: str = "fallback t=0"


class SegmentResult(BaseModel):
    half: str
    clock_start: str
    clock_end: str
    video_seconds_start: float
    video_seconds_end: float
    start_frame: int
    end_frame: int
    duration_seconds: int
    zone_id: str | None = None
    posicion: str | None = None
    tipo_panel: str | None = None


class BrandResult(BaseModel):
    brand_id: str
    name: str
    appearances: int = 0
    total_seconds: int = 0
    minutes: int = 0
    seconds: int = 0
    start_frames: list[int] = Field(default_factory=list)
    segments: list[SegmentResult] = Field(default_factory=list)
    panel_kind: Literal["LED", "FIJA", "AMBAS"] | None = None
    count_1t: int = 0
    count_2t: int = 0


class ComplianceRow(BaseModel):
    brand: str
    period: str
    scheduled_start_sec: float
    duration_sec: float
    status: VerificationStatus = VerificationStatus.MISS
    hit: bool = False
    delta_sec: float | None = None
    reason: str | None = None
    observed_video_sec: float | None = None
    capture_path: str | None = None
    source: str | None = None
    zone: str | None = None

    @model_validator(mode="after")
    def sync_hit_from_status(self) -> "ComplianceRow":
        self.hit = self.status == VerificationStatus.HIT
        return self


class JobResult(BaseModel):
    analyzed_seconds: int = 0
    brands: list[BrandResult] = Field(default_factory=list)
    fixed_brands: list[BrandResult] = Field(default_factory=list)
    analysis_mode: AnalysisMode = "discovery"
    compliance: list[ComplianceRow] = Field(default_factory=list)
    hit_rate: float | None = None
    report_xlsx_path: str | None = None
    warnings: list[str] = Field(default_factory=list)

class JobSummaryTotals(BaseModel):
    brand_count: int = 0
    total_exposure_seconds: int = 0
    analyzed_seconds: int = 0


class JobSummary(BaseModel):
    id: str
    status: JobStatus
    progress: float = 0.0
    stadium_id: str | None = None
    created_at: str
    summary: JobSummaryTotals = Field(default_factory=JobSummaryTotals)


class JobResponse(BaseModel):
    id: str
    status: JobStatus
    progress: float = 0.0
    progress_label: str = ""
    error: str | None = None
    config: JobConfig
    kickoff: Kickoff | None = None
    result: JobResult | None = None
    created_at: str | None = None
    catalog_confirmed_at: str | None = None


class CalibrationPreviews(BaseModel):
    scoreboard_jpeg_b64: str | None = None
    grass_mask_jpeg_b64: str | None = None


class CalibrationProposeResponse(BaseModel):
    camera: CameraProfile
    previews: CalibrationPreviews = Field(default_factory=CalibrationPreviews)


class CalibrationSaveRequest(BaseModel):
    stadium_id: str = Field(min_length=1)
    nombre: str = Field(min_length=1)
    pais: str | None = None
    default_camera: str = "default"
    camera: CameraProfile

    @field_validator("stadium_id", "nombre")
    @classmethod
    def strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("El campo no puede estar vacío.")
        return value

    @field_validator("pais")
    @classmethod
    def strip_pais(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class CalibrationSaveResponse(BaseModel):
    id: str
    nombre: str
    pais: str | None = None
    profile_id: str
    version: int
    yaml_path: str | None = None
    camera: CameraProfile


class JobEvent(BaseModel):
    status: JobStatus
    progress: float
    progress_label: str
    kickoff: Kickoff | None = None
    partial_brands: list[BrandResult] = Field(default_factory=list)
    error: str | None = None
