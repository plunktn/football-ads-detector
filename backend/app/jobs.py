import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator

from . import db
from .config.stadiums import load_stadium_profile
from .domain.stadium import CameraProfile
from .pipeline.brands import generate_aliases
from .pipeline.playlist import parse_playlist
from .pipeline.report import write_commercial_report
from .job_storage import maybe_purge_job_media
from .pipeline.run import AnalysisUpdate, run_analysis
from .pipeline.scoreboard import apply_kickoff_overrides, detect_kickoffs
from .schemas import (
    BrandInput,
    BrandResult,
    JobConfig,
    JobEvent,
    JobResponse,
    JobResult,
    JobStatus,
    Kickoff,
)


logger = logging.getLogger(__name__)
TERMINAL_STATUSES = {"completed", "error"}


@dataclass
class JobRecord:
    id: str
    directory: Path
    brands: list[BrandInput]
    video_paths: list[Path]
    config: JobConfig
    status: JobStatus = "queued"
    progress: float = 0.0
    progress_label: str = "En cola"
    error: str | None = None
    kickoff: Kickoff | None = None
    result: JobResult | None = None
    created_at: str | None = None
    playlist_path: Path | None = None
    events: list[dict] = field(default_factory=list)
    subscribers: set[asyncio.Queue[dict]] = field(default_factory=set)

    def response(self) -> JobResponse:
        return JobResponse(
            id=self.id,
            status=self.status,
            progress=self.progress,
            progress_label=self.progress_label,
            error=self.error,
            config=self.config,
            kickoff=self.kickoff,
            result=self.result,
            created_at=self.created_at,
        )


class JobNotFoundError(KeyError):
    pass


class JobManager:
    def __init__(self, data_root: str | Path):
        self.data_root = Path(data_root)
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.jobs: dict[str, JobRecord] = {}
        self.active_job_id: str | None = None
        self._queue_lock = asyncio.Lock()

    def add_job(
        self,
        *,
        job_id: str,
        directory: Path,
        brands: list[BrandInput],
        video_paths: list[Path],
        config: JobConfig,
        playlist_path: Path | None = None,
    ) -> JobRecord:
        normalized_brands = [
            brand.model_copy(
                update={"aliases": generate_aliases(brand.name, brand.aliases)}
            )
            for brand in brands
        ]
        record = JobRecord(
            id=job_id,
            directory=directory,
            brands=normalized_brands,
            video_paths=video_paths,
            config=config,
            playlist_path=playlist_path,
            status="queued",
            progress_label="En cola",
        )
        self.jobs[job_id] = record
        db.insert_job(
            job_id=job_id,
            stadium_id=config.stadium_id,
            profile_id=None,
            mode=config.mode,
            duration_mode=config.duration_mode,
            status="queued",
            directory=str(directory),
            progress=0.0,
            progress_label="En cola",
        )
        asyncio.create_task(self._maybe_start_next())
        return record

    def get(self, job_id: str) -> JobRecord:
        record = self.jobs.get(job_id)
        if record is not None:
            return record
        row = db.get_job_row(job_id)
        if row is None:
            raise JobNotFoundError(job_id)
        record = self._record_from_row(row)
        self.jobs[job_id] = record
        return record

    def get_result(self, job_id: str) -> JobResult:
        record = self.get(job_id)
        if record.result is not None:
            return record.result
        row = db.get_job_row(job_id)
        if row is None or not row["result_json"]:
            raise JobNotFoundError(job_id)
        result = JobResult.model_validate(json.loads(row["result_json"]))
        record.result = result
        return result

    async def recover_from_db(self) -> None:
        orphaned = await asyncio.to_thread(db.mark_orphaned_jobs_error)
        for job_id in orphaned:
            logger.warning("Marked orphaned job %s as error after restart", job_id)

        rows = await asyncio.to_thread(db.list_non_terminal_jobs)
        for row in rows:
            if row["status"] != "queued":
                continue
            try:
                record = self._record_from_row(row)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                logger.warning("Skipping unrecoverable queued job %s: %s", row["id"], exc)
                await asyncio.to_thread(
                    db.update_job,
                    job_id=row["id"],
                    status="error",
                    error=str(exc),
                    progress_label="No se pudo completar el análisis",
                )
                continue
            self.jobs[record.id] = record

        await self._maybe_start_next()

    @staticmethod
    def _record_from_row(row) -> JobRecord:
        directory = Path(row["directory"])
        config = JobConfig(
            mode=row["mode"],
            duration_mode=row["duration_mode"],
            sample_fps=1,
            stadium_id=row["stadium_id"],
        )
        kickoff = (
            Kickoff.model_validate(json.loads(row["kickoff_json"]))
            if row["kickoff_json"]
            else None
        )
        result = (
            JobResult.model_validate(json.loads(row["result_json"]))
            if row["result_json"]
            else None
        )
        meta_path = directory / "meta.json"
        if not meta_path.is_file():
            if row["status"] in TERMINAL_STATUSES:
                return JobRecord(
                    id=row["id"],
                    directory=directory,
                    brands=[],
                    video_paths=[],
                    config=config,
                    status=row["status"],
                    progress=float(row["progress"]),
                    progress_label=row["progress_label"] or "",
                    error=row["error"],
                    kickoff=kickoff,
                    result=result,
                )
            raise FileNotFoundError(f"Missing job metadata: {meta_path}")

        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        brands = [BrandInput.model_validate(item) for item in meta["brands"]]
        config = JobConfig(
            mode=row["mode"],
            duration_mode=row["duration_mode"],
            sample_fps=meta.get("sample_fps", 1),
            stadium_id=row["stadium_id"],
            analysis_mode=meta.get("analysis_mode", "discovery"),
            kickoff_offset_sec=meta.get("kickoff_offset_sec"),
            second_half_start_sec=meta.get("second_half_start_sec"),
        )
        video_paths = [Path(path) for path in meta["video_paths"]]
        playlist_raw = meta.get("playlist_path")
        playlist_path = Path(playlist_raw) if playlist_raw else None
        return JobRecord(
            id=row["id"],
            directory=directory,
            brands=brands,
            video_paths=video_paths,
            config=config,
            status=row["status"],
            progress=float(row["progress"]),
            progress_label=row["progress_label"] or "",
            error=row["error"],
            kickoff=kickoff,
            result=result,
            created_at=row["created_at"],
            playlist_path=playlist_path,
        )

    async def events(self, job_id: str) -> AsyncIterator[str]:
        record = self.get(job_id)
        queue: asyncio.Queue[dict] = asyncio.Queue()
        record.subscribers.add(queue)
        try:
            for event in record.events:
                yield self._format_sse(event)
            if record.status in TERMINAL_STATUSES:
                return

            while True:
                event = await queue.get()
                yield self._format_sse(event)
                if event.get("status") in TERMINAL_STATUSES:
                    return
        finally:
            record.subscribers.discard(queue)

    async def _maybe_start_next(self) -> None:
        async with self._queue_lock:
            if self.active_job_id is not None:
                active = self.jobs.get(self.active_job_id)
                if active and active.status not in TERMINAL_STATUSES:
                    return

            next_record: JobRecord | None = None
            for record in self.jobs.values():
                if record.status == "queued":
                    next_record = record
                    break

            if next_record is None:
                self.active_job_id = None
                return

            self.active_job_id = next_record.id
            asyncio.create_task(self._run_job(next_record))

    async def _publish(
        self,
        record: JobRecord,
        *,
        status: JobStatus,
        progress: float,
        label: str,
        kickoff: Kickoff | None = None,
        partial_brands: list[BrandResult] | None = None,
        error: str | None = None,
    ) -> None:
        record.status = status
        record.progress = max(0.0, min(1.0, progress))
        record.progress_label = label
        record.error = error
        if kickoff is not None:
            record.kickoff = kickoff

        kickoff_json = (
            record.kickoff.model_dump_json() if record.kickoff is not None else None
        )
        await asyncio.to_thread(
            db.update_job,
            job_id=record.id,
            status=status,
            progress=record.progress,
            progress_label=label,
            error=error,
            kickoff_json=kickoff_json,
            clear_error=error is None,
        )

        event = JobEvent(
            status=status,
            progress=record.progress,
            progress_label=label,
            kickoff=record.kickoff,
            partial_brands=partial_brands or [],
            error=error,
        ).model_dump(mode="json")
        record.events.append(event)
        for subscriber in tuple(record.subscribers):
            subscriber.put_nowait(event)

    @staticmethod
    def _format_sse(event: dict) -> str:
        return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    async def _run_analysis_with_updates(
        self,
        record: JobRecord,
        kickoff: Kickoff,
        camera_profile: CameraProfile | None = None,
    ):
        """Run OpenCV/OCR off-loop while forwarding one-Hz progress to SSE."""
        updates: asyncio.Queue[AnalysisUpdate] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def on_update(update: AnalysisUpdate) -> None:
            loop.call_soon_threadsafe(updates.put_nowait, update)

        worker = asyncio.create_task(
            asyncio.to_thread(
                run_analysis,
                record.video_paths,
                mode=record.config.mode,
                duration_mode=record.config.duration_mode,
                kickoff=kickoff,
                brands=record.brands,
                debug_dir=record.directory / "debug",
                on_update=on_update,
                camera_profile=camera_profile,
                analysis_mode=record.config.analysis_mode,
                playlist_slots=(
                    parse_playlist(record.playlist_path)
                    if record.playlist_path and record.playlist_path.is_file()
                    else None
                ),
            )
        )

        while True:
            if worker.done():
                await asyncio.sleep(0)
                if updates.empty():
                    break
            try:
                update = await asyncio.wait_for(updates.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            progress = 0.1
            if update.total_samples:
                progress += 0.85 * (
                    update.processed_samples / update.total_samples
                )
            clock = int(round(update.match_seconds))
            label = (
                f"{update.half} {clock // 60:02d}:{clock % 60:02d} "
                "— leyendo valla LED"
            )
            await self._publish(
                record,
                status="processing",
                progress=progress,
                label=label,
                kickoff=kickoff,
                partial_brands=update.partial_brands,
            )

        return await worker

    async def _run_job(self, record: JobRecord) -> None:
        try:
            await self._publish(
                record,
                status="detecting_kickoff",
                progress=0.0,
                label="Buscando el saque inicial en el marcador…",
            )
            try:
                camera_profile = load_stadium_profile(
                    record.config.stadium_id or "ligaecuabet"
                )
            except FileNotFoundError:
                logger.warning(
                    "Stadium profile not found for %r; using ROI/scoreboard defaults",
                    record.config.stadium_id or "ligaecuabet",
                )
                camera_profile = None
            kickoff = await asyncio.to_thread(
                detect_kickoffs,
                record.video_paths,
                record.config.mode,
                record.config.duration_mode,
                camera_profile=camera_profile,
            )
            kickoff = apply_kickoff_overrides(
                kickoff,
                kickoff_offset_sec=record.config.kickoff_offset_sec,
                second_half_start_sec=record.config.second_half_start_sec,
            )
            logger.info(
                "Job %s kickoff: 1T %.1fs, 2T %s (%s)",
                record.id,
                kickoff.first_half_video_seconds,
                kickoff.second_half_video_seconds,
                kickoff.note,
            )
            await self._publish(
                record,
                status="processing",
                progress=0.1,
                label="Recortando la valla LED y leyendo marcas…",
                kickoff=kickoff,
            )
            analysis = await self._run_analysis_with_updates(
                record, kickoff, camera_profile=camera_profile
            )
            playlist_slots = []
            if record.playlist_path and record.playlist_path.is_file():
                playlist_slots = parse_playlist(record.playlist_path)
            report_path = record.directory / "informe.xlsx"
            await asyncio.to_thread(
                write_commercial_report,
                report_path,
                led_brands=analysis.brands,
                fixed_brands=analysis.fixed_brands,
                slots=playlist_slots,
                compliance=analysis.compliance,
                hit_rate=analysis.hit_rate,
                analyzed_seconds=analysis.analyzed_seconds,
            )
            result = JobResult(
                analyzed_seconds=analysis.analyzed_seconds,
                brands=analysis.brands,
                fixed_brands=analysis.fixed_brands,
                analysis_mode=record.config.analysis_mode,
                compliance=analysis.compliance,
                hit_rate=analysis.hit_rate,
                report_xlsx_path=str(report_path),
            )
            record.result = result
            result_path = record.directory / "result.json"
            result_json = result.model_dump_json(indent=2)
            result_path.write_text(result_json, encoding="utf-8")
            kickoff_json = kickoff.model_dump_json()
            await asyncio.to_thread(
                db.persist_job_completion,
                record.id,
                status="completed",
                progress=1.0,
                progress_label="Análisis completado",
                kickoff_json=kickoff_json,
                result_json=result_json,
            )
            await asyncio.to_thread(
                maybe_purge_job_media,
                record.directory,
                list(record.video_paths),
            )
            record.video_paths = []
            await self._publish(
                record,
                status="completed",
                progress=1.0,
                label="Análisis completado",
                kickoff=kickoff,
                partial_brands=result.brands,
            )
        except Exception as exc:  # keep failures visible through the API/SSE
            logger.exception("Job %s failed", record.id)
            await asyncio.to_thread(
                db.update_job,
                job_id=record.id,
                status="error",
                progress=record.progress,
                progress_label="No se pudo completar el análisis",
                error=str(exc),
            )
            await self._publish(
                record,
                status="error",
                progress=record.progress,
                label="No se pudo completar el análisis",
                kickoff=record.kickoff,
                error=str(exc),
            )
        finally:
            if self.active_job_id == record.id:
                self.active_job_id = None
            await self._maybe_start_next()
