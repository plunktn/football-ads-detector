import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator

from .pipeline.brands import generate_aliases
from .pipeline.run import AnalysisUpdate, run_analysis
from .pipeline.scoreboard import detect_kickoffs
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
        )


class JobBusyError(RuntimeError):
    """Raised when v1's single-worker queue is already occupied."""


class JobNotFoundError(KeyError):
    pass


class JobManager:
    def __init__(self, data_root: str | Path):
        self.data_root = Path(data_root)
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.jobs: dict[str, JobRecord] = {}
        self.active_job_id: str | None = None

    def add_job(
        self,
        *,
        job_id: str,
        directory: Path,
        brands: list[BrandInput],
        video_paths: list[Path],
        config: JobConfig,
    ) -> JobRecord:
        if self.active_job_id is not None:
            active = self.jobs.get(self.active_job_id)
            if active and active.status not in TERMINAL_STATUSES:
                raise JobBusyError("Ya hay un análisis en curso.")

        record = JobRecord(
            id=job_id,
            directory=directory,
            brands=[
                brand.model_copy(
                    update={"aliases": generate_aliases(brand.name, brand.aliases)}
                )
                for brand in brands
            ],
            video_paths=video_paths,
            config=config,
        )
        self.jobs[job_id] = record
        self.active_job_id = job_id
        asyncio.create_task(self._run_job(record))
        return record

    def get(self, job_id: str) -> JobRecord:
        record = self.jobs.get(job_id)
        if record is None:
            raise JobNotFoundError(job_id)
        return record

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
            )
        )

        while not worker.done() or not updates.empty():
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
            kickoff = await asyncio.to_thread(
                detect_kickoffs,
                record.video_paths,
                record.config.mode,
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
            analysis = await self._run_analysis_with_updates(record, kickoff)
            result = JobResult(
                analyzed_seconds=analysis.analyzed_seconds,
                brands=analysis.brands,
            )
            record.result = result
            (record.directory / "result.json").write_text(
                result.model_dump_json(indent=2),
                encoding="utf-8",
            )
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
