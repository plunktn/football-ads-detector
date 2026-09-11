"use client";

import {
  ArrowLeft,
  ChevronDown,
  Download,
  FileVideo,
  History,
  LoaderCircle,
  ScanLine,
  Trash2,
  UploadCloud,
  ZoomIn,
} from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import {
  type ChangeEvent,
  type DragEvent,
  useEffect,
  useRef,
  useState,
} from "react";

import { CatalogReview } from "@/components/catalog-review";
import { FrameLightbox } from "@/components/frame-lightbox";
import {
  type Brand,
  type BrandGroup,
  type BrandResult,
  type BrandSummary,
  type ComplianceRow,
  type DurationMode,
  type Job,
  type JobMode,
  type JobSummary,
  type Stadium,
  type VerificationStatus,
  DOUBTFUL_STATUSES,
  deleteJob,
  exportCsvUrl,
  exportXlsxUrl,
  getActiveJob,
  getFrameUrl,
  getJob,
  jobPreviewUrl,
  listBrandGroups,
  listJobs,
  listStadiums,
  submitJob,
  watchJob,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";

const ACCEPTED_VIDEO_TYPES = ".mp4,.mov,.mkv,.webm";

function formatBytes(bytes: number) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatSeconds(totalSeconds: number) {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes} min ${seconds} s`;
}

function JobPreviewStill({ jobId }: { jobId: string }) {
  const [attempt, setAttempt] = useState(0);
  const [gone, setGone] = useState(false);
  if (gone) return null;
  return (
    <div className="overflow-hidden rounded-xl border border-border/70 bg-black/30">
      <p className="border-b border-border/50 px-3 py-2 font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
        Vista del partido
      </p>
      <Image
        src={`${jobPreviewUrl(jobId)}?a=${attempt}`}
        alt="Vista previa del partido en análisis"
        width={960}
        height={540}
        unoptimized
        className="h-auto max-h-[42vh] w-full object-contain"
        onError={() => {
          if (attempt >= 10) {
            setGone(true);
            return;
          }
          window.setTimeout(() => setAttempt((value) => value + 1), 1200);
        }}
      />
    </div>
  );
}

function formatJobDate(iso: string) {
  try {
    return new Intl.DateTimeFormat("es", {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

function jobStatusLabel(status: Job["status"]) {
  switch (status) {
    case "queued":
      return "En cola";
    case "detecting_kickoff":
      return "Detectando kickoff";
    case "processing":
      return "Procesando";
    case "completed":
      return "Completado";
    case "error":
      return "Error";
  }
}

function emptyResult(brand: Brand): BrandResult {
  return {
    brand_id: brand.id,
    name: brand.name,
    appearances: 0,
    total_seconds: 0,
    minutes: 0,
    seconds: 0,
    start_frames: [],
    segments: [],
  };
}

type FileDropzoneProps = {
  id: string;
  label: string;
  hint: string;
  file: File | undefined;
  onFileChange: (file: File | undefined) => void;
  onInvalid?: (message: string) => void;
};

function FileDropzone({
  id,
  label,
  hint,
  file,
  onFileChange,
  onInvalid,
}: FileDropzoneProps) {
  const [isDragging, setIsDragging] = useState(false);

  const handleFile = (candidate: File | undefined) => {
    if (!candidate) return;
    const extension = `.${candidate.name.split(".").pop()?.toLowerCase()}`;
    if (![".mp4", ".mov", ".mkv", ".webm"].includes(extension)) {
      onInvalid?.("Ese archivo no parece un video compatible. Usa MP4, MOV, MKV o WebM.");
      return;
    }
    onInvalid?.("");
    onFileChange(candidate);
  };

  const handleInput = (event: ChangeEvent<HTMLInputElement>) => {
    handleFile(event.target.files?.[0]);
    event.target.value = "";
  };

  const handleDrop = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    setIsDragging(false);
    handleFile(event.dataTransfer.files?.[0]);
  };

  return (
    <label
      htmlFor={id}
      onDragEnter={(event) => {
        event.preventDefault();
        setIsDragging(true);
      }}
      onDragOver={(event) => event.preventDefault()}
      onDragLeave={() => setIsDragging(false)}
      onDrop={handleDrop}
      className={`group flex min-h-36 cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed px-4 py-6 text-center transition-colors duration-200 ${
        isDragging
          ? "border-primary bg-primary/10"
          : "border-border/80 bg-background/40 hover:border-primary/60 hover:bg-primary/5"
      }`}
    >
      <input
        id={id}
        type="file"
        accept={ACCEPTED_VIDEO_TYPES}
        onChange={handleInput}
        className="sr-only"
      />
      {file ? (
        <>
          <div className="mb-3 flex size-11 items-center justify-center rounded-xl bg-primary/15 text-primary">
            <FileVideo className="size-5" aria-hidden="true" />
          </div>
          <span className="max-w-full truncate text-sm font-medium text-foreground">
            {file.name}
          </span>
          <span className="mt-1 font-mono text-xs text-muted-foreground">
            {formatBytes(file.size)}
          </span>
        </>
      ) : (
        <>
          <div className="mb-3 flex size-11 items-center justify-center rounded-xl border border-border bg-muted/60 text-muted-foreground transition-colors group-hover:border-primary/50 group-hover:text-primary">
            <UploadCloud className="size-5" aria-hidden="true" />
          </div>
          <span className="text-sm font-medium text-foreground">{label}</span>
          <span className="mt-1 text-xs text-muted-foreground">{hint}</span>
        </>
      )}
    </label>
  );
}

function formatMinuto(startSec: number) {
  const minute = Math.floor(startSec / 60);
  const second = Math.floor(startSec % 60);
  return `${minute}.${String(second).padStart(2, "0")}`;
}

function statusBadgeVariant(
  status: VerificationStatus,
): "default" | "secondary" | "destructive" | "outline" {
  if (status === "HIT") return "default";
  if (status === "MISS") return "destructive";
  if (status === "PAST_EOF") return "outline";
  return "secondary";
}

function ComplianceTable({ rows }: { rows: ComplianceRow[] }) {
  const [onlyDoubtful, setOnlyDoubtful] = useState(false);
  const filtered = onlyDoubtful
    ? rows.filter((row) =>
        DOUBTFUL_STATUSES.includes(row.status ?? (row.hit ? "HIT" : "MISS")),
      )
    : rows;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-primary">
            Cumplimiento playlist
          </p>
          <h3 className="mt-1 text-lg font-semibold">Auditoría de salidas</h3>
        </div>
        <label className="flex cursor-pointer items-center gap-2 text-xs text-muted-foreground">
          <input
            type="checkbox"
            className="size-4 accent-primary"
            checked={onlyDoubtful}
            onChange={(event) => setOnlyDoubtful(event.target.checked)}
          />
          Solo dudosas
        </label>
      </div>
      <div className="overflow-hidden rounded-xl border border-border/80">
        <div className="overflow-x-auto">
          <table className="w-full min-w-180 text-left text-sm">
            <thead className="bg-muted/40 text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">Marca</th>
                <th className="px-3 py-2 font-medium">Periodo</th>
                <th className="px-3 py-2 font-medium">Minuto</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">Δ s</th>
                <th className="px-3 py-2 font-medium">Captura</th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr>
                  <td
                    colSpan={6}
                    className="px-3 py-6 text-center text-xs text-muted-foreground"
                  >
                    {onlyDoubtful
                      ? "No hay filas dudosas."
                      : "Sin filas de cumplimiento."}
                  </td>
                </tr>
              ) : (
                filtered.map((row, index) => {
                  const status =
                    row.status ?? (row.hit ? "HIT" : ("MISS" as VerificationStatus));
                  const captureName = row.capture_path
                    ? row.capture_path.split(/[/\\]/).pop()
                    : null;
                  return (
                    <tr
                      key={`${row.brand}-${row.period}-${row.scheduled_start_sec}-${index}`}
                      className="border-t border-border/60"
                    >
                      <td className="px-3 py-2 font-medium">{row.brand}</td>
                      <td className="px-3 py-2 font-mono text-xs">{row.period}</td>
                      <td className="px-3 py-2 font-mono text-xs">
                        {formatMinuto(row.scheduled_start_sec)}
                      </td>
                      <td className="px-3 py-2">
                        <Badge variant={statusBadgeVariant(status)} className="text-[10px]">
                          {status}
                        </Badge>
                      </td>
                      <td className="px-3 py-2 font-mono text-xs">
                        {row.delta_sec == null ? "—" : row.delta_sec.toFixed(1)}
                      </td>
                      <td
                        className="max-w-40 truncate px-3 py-2 font-mono text-[10px] text-muted-foreground"
                        title={row.capture_path ?? row.reason ?? undefined}
                      >
                        {captureName ?? row.reason ?? "—"}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function ResultsTable({
  jobId,
  brands,
  resultBrands,
}: {
  jobId: string;
  brands: Brand[];
  resultBrands: BrandResult[];
}) {
  const [selectedFrame, setSelectedFrame] = useState<{
    src: string;
    label: string;
  } | null>(null);
  const resultById = new Map(resultBrands.map((brand) => [brand.brand_id, brand]));
  const rowBrands =
    brands.length > 0
      ? brands
      : resultBrands.map((brand) => ({
          id: brand.brand_id,
          name: brand.name,
          aliases: [],
        }));
  const rows = rowBrands.map(
    (brand) => resultById.get(brand.id) ?? emptyResult(brand),
  );

  return (
    <>
      <div className="overflow-hidden rounded-xl border border-border/80">
        <div className="overflow-x-auto">
          <table className="w-full min-w-180 text-left text-sm">
            <thead className="bg-muted/35 text-xs uppercase tracking-[0.16em] text-muted-foreground">
              <tr>
                <th className="px-4 py-3 font-medium">Marca</th>
                <th className="px-4 py-3 text-right font-medium">Apariciones</th>
                <th className="px-4 py-3 text-right font-medium">Tiempo</th>
                <th className="px-4 py-3 font-medium">Frames de inicio</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/70">
              {rows.map((brand) => (
                <tr key={brand.brand_id} className="bg-card/40">
                  <td colSpan={4} className="p-0">
                    <details className="group">
                      <summary className="grid cursor-pointer list-none grid-cols-[minmax(180px,1fr)_130px_140px_minmax(280px,1.5fr)] items-center gap-0 px-4 py-4 transition-colors hover:bg-muted/25 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary [&::-webkit-details-marker]:hidden">
                        <span className="flex items-center gap-2 font-medium text-foreground">
                          <ChevronDown
                            className="size-4 shrink-0 text-primary transition-transform duration-200 group-open:rotate-180"
                            aria-hidden="true"
                          />
                          {brand.name}
                        </span>
                        <span className="text-right font-mono tabular-nums text-foreground">
                          {brand.appearances}
                        </span>
                        <span className="text-right font-mono tabular-nums text-foreground">
                          {brand.minutes} min {brand.seconds} s
                        </span>
                        <span className="pl-4 font-mono text-xs tabular-nums text-muted-foreground">
                          {brand.start_frames.length
                            ? brand.start_frames.join(", ")
                            : "—"}
                        </span>
                      </summary>
                      <div className="border-t border-border/60 bg-background/35 px-4 py-4">
                        {brand.segments.length ? (
                          <div className="space-y-3">
                            <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                              {brand.segments.length} tramo
                              {brand.segments.length === 1 ? "" : "s"} detectado
                              {brand.segments.length === 1 ? "" : "s"}
                            </p>
                            <div className="grid gap-3">
                              {brand.segments.map((segment, index) => {
                                const frameSrc = getFrameUrl(
                                  jobId,
                                  segment.half,
                                  segment.start_frame,
                                );
                                const frameLabel = `${brand.name}, ${segment.half}, frame ${segment.start_frame}`;
                                return (
                                  <article
                                    key={`${segment.half}-${segment.start_frame}-${index}`}
                                    className="flex flex-col gap-4 rounded-xl border border-border/70 bg-card/45 p-3 sm:flex-row sm:items-center"
                                  >
                                    <button
                                      type="button"
                                      className="group/frame relative h-20 w-36 shrink-0 overflow-hidden rounded-lg border border-border/80 bg-muted/50 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                                      onClick={() =>
                                        setSelectedFrame({
                                          src: frameSrc,
                                          label: frameLabel,
                                        })
                                      }
                                      aria-label={`Ampliar ${frameLabel}`}
                                    >
                                      <Image
                                        src={frameSrc}
                                        alt={`Vista previa de ${frameLabel}`}
                                        width={144}
                                        height={80}
                                        unoptimized
                                        className="h-full w-full object-cover transition-transform duration-200 group-hover/frame:scale-105"
                                      />
                                      <span className="absolute inset-0 flex items-center justify-center bg-black/0 text-white opacity-0 transition-opacity group-hover/frame:bg-black/45 group-hover/frame:opacity-100">
                                        <ZoomIn className="size-5" aria-hidden="true" />
                                      </span>
                                    </button>
                                    <div className="min-w-0 flex-1">
                                      <div className="flex flex-wrap items-center gap-2">
                                        <Badge variant="secondary" className="font-mono text-[10px]">
                                          {segment.half}
                                        </Badge>
                                        {segment.posicion ? (
                                          <Badge
                                            variant="outline"
                                            className="border-primary/25 bg-primary/5 font-mono text-[10px] uppercase tracking-[0.12em] text-primary"
                                          >
                                            {segment.posicion}
                                          </Badge>
                                        ) : null}
                                        <span className="font-mono text-sm text-foreground">
                                          {segment.clock_start} → {segment.clock_end}
                                        </span>
                                        {segment.zone_id ? (
                                          <span className="font-mono text-[10px] text-muted-foreground">
                                            {segment.zone_id}
                                          </span>
                                        ) : null}
                                      </div>
                                      <div className="mt-2 grid gap-1 text-xs text-muted-foreground sm:grid-cols-2">
                                        <span>
                                          Duración:{" "}
                                          <strong className="font-mono font-medium text-foreground">
                                            {segment.duration_seconds} s
                                          </strong>
                                        </span>
                                        <span>
                                          Frame inicio:{" "}
                                          <strong className="font-mono font-medium text-foreground">
                                            {segment.start_frame}
                                          </strong>
                                        </span>
                                        <span>
                                          Frame fin:{" "}
                                          <strong className="font-mono font-medium text-foreground">
                                            {segment.end_frame}
                                          </strong>
                                        </span>
                                        <span>
                                          Video:{" "}
                                          <strong className="font-mono font-medium text-foreground">
                                            {segment.video_seconds_start.toFixed(1)}–
                                            {segment.video_seconds_end.toFixed(1)} s
                                          </strong>
                                        </span>
                                      </div>
                                    </div>
                                    <Button
                                      type="button"
                                      variant="ghost"
                                      className="min-h-11 shrink-0 gap-2 self-start text-xs text-muted-foreground hover:text-foreground sm:self-center"
                                      onClick={() =>
                                        setSelectedFrame({
                                          src: frameSrc,
                                          label: frameLabel,
                                        })
                                      }
                                    >
                                      <ZoomIn className="size-4" aria-hidden="true" />
                                      Ver frame
                                    </Button>
                                  </article>
                                );
                              })}
                            </div>
                          </div>
                        ) : (
                          <p className="text-xs text-muted-foreground">
                            No se detectaron tramos de exposición para esta marca.
                          </p>
                        )}
                      </div>
                    </details>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      {selectedFrame ? (
        <FrameLightbox
          src={selectedFrame.src}
          label={selectedFrame.label}
          onClose={() => setSelectedFrame(null)}
        />
      ) : null}
    </>
  );
}

function summaryToBrand(brand: BrandSummary): Brand {
  return {
    id: brand.id,
    name: brand.nombre,
    aliases: brand.aliases.length
      ? brand.aliases
      : [brand.nombre.replace(/\s+/g, ""), brand.nombre.toUpperCase()],
  };
}

export default function Home() {
  const [mode, setMode] = useState<JobMode>("single");
  const [durationMode, setDurationMode] = useState<DurationMode>("5min");
  const [durationPreset, setDurationPreset] = useState<"5min" | "10min" | "full" | "custom">(
    "5min",
  );
  const [customMinutes, setCustomMinutes] = useState("");
  const [stadiumId, setStadiumId] = useState("ligaecuabet");
  const [stadiums, setStadiums] = useState<Stadium[]>([
    { id: "ligaecuabet", nombre: "LigaEcuabet (default)" },
  ]);
  const [video, setVideo] = useState<File>();
  const [videoFirst, setVideoFirst] = useState<File>();
  const [videoSecond, setVideoSecond] = useState<File>();
  const [usePlaylist, setUsePlaylist] = useState(false);
  const [playlist, setPlaylist] = useState<File>();
  const [kickoffOffsetSec, setKickoffOffsetSec] = useState("");
  const [secondHalfStartSec, setSecondHalfStartSec] = useState("");
  const [brands, setBrands] = useState<Brand[]>([]);
  const [brandGroups, setBrandGroups] = useState<BrandGroup[]>([]);
  const [groupsLoading, setGroupsLoading] = useState(true);
  const [selectedGroupId, setSelectedGroupId] = useState("");
  const [jobBrandEnabled, setJobBrandEnabled] = useState<Record<string, boolean>>(
    {},
  );
  const [job, setJob] = useState<Job | null>(null);
  const [recentJobs, setRecentJobs] = useState<JobSummary[]>([]);
  const [deleteTarget, setDeleteTarget] = useState<JobSummary | null>(null);
  const [deletingJob, setDeletingJob] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const stopWatching = useRef<(() => void) | null>(null);

  const refreshRecentJobs = () => {
    void listJobs()
      .then((items) => setRecentJobs(items))
      .catch(() => {
        // El historial es opcional si el backend aún no expone GET /jobs.
      });
  };

  useEffect(() => {
    refreshRecentJobs();
  }, []);

  useEffect(() => {
    if (job?.status === "completed" || job?.status === "error") {
      refreshRecentJobs();
    }
  }, [job?.status]);

  const isBusy =
    submitting ||
    job?.status === "queued" ||
    job?.status === "detecting_kickoff" ||
    job?.status === "processing";
  const hasVideo =
    mode === "single" ? Boolean(video) : Boolean(videoFirst && videoSecond);
  const selectedGroup = brandGroups.find((group) => group.id === selectedGroupId);
  const enabledBrands = (selectedGroup?.brands ?? [])
    .filter((brand) => jobBrandEnabled[brand.id])
    .map(summaryToBrand);
  const customMinutesValid = (() => {
    if (durationPreset !== "custom") return true;
    const parsed = Number(customMinutes);
    return customMinutes.trim() !== "" && Number.isFinite(parsed) && parsed >= 1;
  })();
  const canSubmit =
    hasVideo &&
    customMinutesValid &&
    (enabledBrands.length > 0 || Boolean(usePlaylist && playlist));

  const attachToJob = (candidate: Job) => {
    setJob(candidate);
    setConnectionError(null);
    stopWatching.current?.();
    stopWatching.current = watchJob(
      candidate.id,
      (update) => {
        setJob((current) =>
          current
            ? {
                ...current,
                ...update,
                config: current.config,
              }
            : {
                ...candidate,
                ...update,
                config: candidate.config,
              },
        );
        const partialBrands = update.result?.brands;
        if (partialBrands?.length) {
          setBrands((current) =>
            current.length
              ? current
              : partialBrands.map((brand) => ({
                  id: brand.brand_id,
                  name: brand.name,
                  aliases: [],
                })),
          );
        }
      },
      (message) => setConnectionError(message),
    );
  };

  useEffect(() => {
    let cancelled = false;
    void getActiveJob()
      .then((active) => {
        if (!cancelled && active) attachToJob(active);
      })
      .catch(() => {
        // The empty state remains usable when the backend is not running yet.
      });

    return () => {
      cancelled = true;
      stopWatching.current?.();
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    void listStadiums()
      .then((items) => {
        if (!cancelled && items.length) {
          setStadiums(items);
          setStadiumId((current) =>
            items.some((stadium) => stadium.id === current)
              ? current
              : items[0].id,
          );
        }
      })
      .catch(() => {
        // Keep the default fallback stadium when the backend is unavailable.
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    void listBrandGroups()
      .then((items) => {
        if (cancelled) return;
        setBrandGroups(items);
        setSelectedGroupId((current) => {
          if (current && items.some((group) => group.id === current)) return current;
          const seeded = items.find((group) => group.id === "ligaecuabet");
          return seeded?.id ?? items[0]?.id ?? "";
        });
      })
      .catch(() => {
        if (!cancelled) setBrandGroups([]);
      })
      .finally(() => {
        if (!cancelled) setGroupsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const group = brandGroups.find((item) => item.id === selectedGroupId);
    const next: Record<string, boolean> = {};
    for (const brand of group?.brands ?? []) {
      next[brand.id] = brand.activo !== false;
    }
    setJobBrandEnabled(next);
  }, [selectedGroupId, brandGroups]);

  const handleSubmit = async () => {
    if (!canSubmit || isBusy) return;
    setSubmitting(true);
    setConnectionError(null);
    stopWatching.current?.();
    try {
      const analysisMode =
        usePlaylist && playlist ? "playlist_verify" : "discovery";
      const effectiveDuration =
        analysisMode === "playlist_verify" ? "full" : durationMode;
      const kickoffParsed = kickoffOffsetSec.trim()
        ? Number(kickoffOffsetSec)
        : null;
      const secondParsed = secondHalfStartSec.trim()
        ? Number(secondHalfStartSec)
        : null;
      const created = await submitJob({
        mode,
        durationMode: effectiveDuration,
        stadiumId,
        brands: enabledBrands,
        video,
        videoFirst,
        videoSecond,
        playlist: usePlaylist ? playlist : undefined,
        analysisMode,
        kickoffOffsetSec:
          kickoffParsed != null && Number.isFinite(kickoffParsed)
            ? kickoffParsed
            : null,
        secondHalfStartSec:
          secondParsed != null && Number.isFinite(secondParsed)
            ? secondParsed
            : null,
      });
      setBrands(enabledBrands);
      const initialJob: Job = {
        id: created.id,
        status: "queued",
        progress: 0,
        progress_label: "En cola",
        error: null,
        config: {
          mode,
          duration_mode: effectiveDuration,
          sample_fps: 1,
          analysis_mode: analysisMode,
          kickoff_offset_sec:
            kickoffParsed != null && Number.isFinite(kickoffParsed)
              ? kickoffParsed
              : null,
          second_half_start_sec:
            secondParsed != null && Number.isFinite(secondParsed)
              ? secondParsed
              : null,
        },
        kickoff: null,
        result: null,
      };
      setJob(initialJob);
      stopWatching.current = watchJob(
        created.id,
        (update) =>
          setJob((current) =>
            current
              ? {
                  ...current,
                  ...update,
                  config: current.config,
                }
              : initialJob,
          ),
        (message) => setConnectionError(message),
      );
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "No se pudo iniciar el análisis.";
      if (message.toLowerCase().includes("análisis en curso")) {
        const active = await getActiveJob().catch(() => null);
        if (active) {
          attachToJob(active);
          return;
        }
      }
      setConnectionError(message);
    } finally {
      setSubmitting(false);
    }
  };

  const loadHistoricalJob = async (summary: JobSummary) => {
    if (job?.id === summary.id) return;
    setConnectionError(null);
    stopWatching.current?.();
    stopWatching.current = null;
    try {
      const loaded = await getJob(summary.id);
      setJob(loaded);
      if (loaded.result?.brands.length) {
        setBrands(
          loaded.result.brands.map((brand) => ({
            id: brand.brand_id,
            name: brand.name,
            aliases: [],
          })),
        );
      }
      if (loaded.status !== "completed" && loaded.status !== "error") {
        attachToJob(loaded);
      }
    } catch (error) {
      setConnectionError(
        error instanceof Error ? error.message : "No se pudo cargar el análisis.",
      );
    }
  };

  const resetJob = () => {
    stopWatching.current?.();
    stopWatching.current = null;
    setJob(null);
    setConnectionError(null);
  };

  useEffect(() => {
    if (!deleteTarget || deletingJob) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setDeleteTarget(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [deleteTarget, deletingJob]);

  const handleDeleteJob = async () => {
    if (!deleteTarget) return;
    setDeletingJob(true);
    try {
      await deleteJob(deleteTarget.id);
      setRecentJobs((current) =>
        current.filter((item) => item.id !== deleteTarget.id),
      );
      if (job?.id === deleteTarget.id) {
        resetJob();
      }
      setConnectionError(null);
      setDeleteTarget(null);
    } catch (error) {
      setConnectionError(
        error instanceof Error ? error.message : "No se pudo borrar el análisis.",
      );
      setDeleteTarget(null);
    } finally {
      setDeletingJob(false);
    }
  };

  const resultBrands =
    job?.result?.brands ??
    (job?.status === "processing"
      ? []
      : brands.map((brand) => emptyResult(brand)));

  const workspaceMode = Boolean(job);
  const canLeaveWorkspace =
    job?.status === "completed" || job?.status === "error";

  return (
    <main className="min-h-dvh overflow-x-hidden bg-background">
      <div className="pointer-events-none fixed inset-0 bg-[radial-gradient(circle_at_15%_0%,oklch(0.32_0.12_145/0.12),transparent_32%),radial-gradient(circle_at_85%_10%,oklch(0.35_0.1_75/0.09),transparent_25%)]" />
      <div
        className={`relative mx-auto flex min-h-dvh w-full flex-col gap-8 px-4 py-6 sm:px-6 lg:px-8 ${
          workspaceMode ? "max-w-6xl" : "max-w-3xl"
        }`}
      >
        {!workspaceMode ? (
          <>
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">
            Nuevo análisis
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Video, grupo de marcas, ventana y estadio.
          </p>
        </div>

          <Card className="border-border/80 bg-card/80 shadow-xl shadow-black/15 backdrop-blur-xl">
            <CardContent className="space-y-7 pt-6">
              <section aria-labelledby="video-heading">
                <div className="mb-3">
                  <h2 id="video-heading" className="text-sm font-semibold text-foreground">
                    Video del partido
                  </h2>
                  <p className="mt-1 text-xs text-muted-foreground">
                    MP4, MOV, MKV o WebM
                  </p>
                </div>
                <Tabs
                  value={mode}
                  onValueChange={(value) => setMode(value as JobMode)}
                  className="w-full"
                >
                  <TabsList className="grid h-auto w-full grid-cols-2 bg-muted/60 p-1">
                    <TabsTrigger
                      value="single"
                      className="min-h-10 text-xs"
                      disabled={Boolean(isBusy)}
                    >
                      Un video
                    </TabsTrigger>
                    <TabsTrigger
                      value="split"
                      className="min-h-10 text-xs"
                      disabled={Boolean(isBusy)}
                    >
                      Dos videos
                    </TabsTrigger>
                  </TabsList>
                  <TabsContent value="single" className="mt-3">
                    <FileDropzone
                      id="video-single"
                      label="Arrastra el partido acá"
                      hint="o elige un archivo · partido completo"
                      file={video}
                      onFileChange={setVideo}
                      onInvalid={(message) => setConnectionError(message || null)}
                    />
                  </TabsContent>
                  <TabsContent value="split" className="mt-3 grid gap-3 sm:grid-cols-2">
                    <FileDropzone
                      id="video-first"
                      label="Cargar 1T"
                      hint="primer tiempo"
                      file={videoFirst}
                      onFileChange={setVideoFirst}
                      onInvalid={(message) => setConnectionError(message || null)}
                    />
                    <FileDropzone
                      id="video-second"
                      label="Cargar 2T"
                      hint="segundo tiempo"
                      file={videoSecond}
                      onFileChange={setVideoSecond}
                      onInvalid={(message) => setConnectionError(message || null)}
                    />
                  </TabsContent>
                </Tabs>
              </section>

              <Separator className="bg-border/60" />

              <section aria-labelledby="brands-heading">
                <div className="mb-3">
                  <h2 id="brands-heading" className="text-sm font-semibold text-foreground">
                    Marcas a detectar
                  </h2>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Grupo del catálogo. Los interruptores aplican solo a este análisis.
                  </p>
                </div>
                {groupsLoading ? (
                  <p className="rounded-lg border border-border/70 bg-muted/20 px-4 py-3 text-xs text-muted-foreground">
                    Cargando grupos…
                  </p>
                ) : brandGroups.length ? (
                  <>
                    <Label htmlFor="brand-group" className="sr-only">
                      Grupo
                    </Label>
                    <Select
                      value={selectedGroupId}
                      onValueChange={(value) => {
                        if (value) setSelectedGroupId(value);
                      }}
                      disabled={Boolean(isBusy)}
                    >
                      <SelectTrigger id="brand-group" className="h-11 w-full bg-background/60">
                        <SelectValue placeholder="Elige un grupo" />
                      </SelectTrigger>
                      <SelectContent>
                        {brandGroups.map((group) => (
                          <SelectItem key={group.id} value={group.id}>
                            {group.titulo}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    {selectedGroup?.brands.length ? (
                      <div className="mt-3 space-y-2">
                        {selectedGroup.brands.map((brand) => {
                          const enabled = Boolean(jobBrandEnabled[brand.id]);
                          return (
                            <label
                              key={brand.id}
                              className={`flex cursor-pointer items-center justify-between gap-3 rounded-lg border px-3 py-2.5 transition-colors ${
                                enabled
                                  ? "border-primary/30 bg-primary/5"
                                  : "border-border/70 bg-muted/20"
                              } ${isBusy ? "pointer-events-none opacity-50" : "hover:border-border"}`}
                            >
                              <span
                                className={`min-w-0 truncate text-sm font-medium ${
                                  enabled ? "text-foreground" : "text-muted-foreground"
                                }`}
                              >
                                {brand.nombre}
                              </span>
                              <Switch
                                checked={enabled}
                                disabled={Boolean(isBusy)}
                                onCheckedChange={(checked) =>
                                  setJobBrandEnabled((current) => ({
                                    ...current,
                                    [brand.id]: checked,
                                  }))
                                }
                                aria-label={`${enabled ? "Desactivar" : "Activar"} ${brand.nombre}`}
                              />
                            </label>
                          );
                        })}
                      </div>
                    ) : (
                      <div className="mt-3 rounded-lg border border-dashed border-border/70 px-4 py-3 text-center text-xs text-muted-foreground">
                        Este grupo no tiene marcas.{" "}
                        <Link
                          href="/configuracion"
                          className="font-medium text-primary underline-offset-4 hover:underline"
                        >
                          Agregar en Configuración
                        </Link>
                      </div>
                    )}
                  </>
                ) : (
                  <div className="rounded-lg border border-dashed border-border/70 px-4 py-4 text-center text-xs text-muted-foreground">
                    Todavía no hay grupos de marcas.{" "}
                    <Link
                      href="/configuracion"
                      className="font-medium text-primary underline-offset-4 hover:underline"
                    >
                      Créalos en Configuración
                    </Link>
                  </div>
                )}
              </section>

              <Separator className="bg-border/60" />

              <details className="rounded-lg border border-border/70 bg-muted/15 open:pb-0">
                <summary className="cursor-pointer list-none px-3 py-3 text-sm font-medium text-foreground [&::-webkit-details-marker]:hidden">
                  Playlist / reporte Lions
                  <span className="mt-0.5 block text-xs font-normal text-muted-foreground">
                    Opcional. Sin playlist = discovery.
                  </span>
                </summary>
                <div className="space-y-3 border-t border-border/60 px-3 py-3">
                <label className="flex cursor-pointer items-start gap-3 rounded-lg border border-border/70 bg-muted/20 p-3 text-sm">
                  <input
                    type="checkbox"
                    className="mt-1 size-4 accent-primary"
                    checked={usePlaylist}
                    disabled={Boolean(isBusy)}
                    onChange={(event) => {
                      setUsePlaylist(event.target.checked);
                      if (!event.target.checked) setPlaylist(undefined);
                      if (event.target.checked) {
                        setDurationPreset("full");
                        setDurationMode("full");
                      }
                    }}
                  />
                  <span>
                    <span className="font-medium text-foreground">
                      Verificar playlist/reporte
                    </span>
                    <span className="mt-0.5 block text-xs text-muted-foreground">
                      Sube el xlsx multi-hoja (PREVIA / 1T / ENTRETIEMPO / 2T / POST).
                    </span>
                  </span>
                </label>
                {usePlaylist ? (
                  <div className="mt-3 space-y-3">
                    <div>
                      <Label htmlFor="playlist-xlsx" className="sr-only">
                        Archivo playlist
                      </Label>
                      <Input
                        id="playlist-xlsx"
                        type="file"
                        accept=".xlsx,.xlsm,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        disabled={Boolean(isBusy)}
                        className="h-11 bg-background/60"
                        onChange={(event) => setPlaylist(event.target.files?.[0])}
                      />
                      {playlist ? (
                        <p className="mt-2 truncate text-xs text-muted-foreground">
                          {playlist.name}
                        </p>
                      ) : null}
                    </div>
                    <div className="grid gap-3 sm:grid-cols-2">
                      <div className="space-y-1.5">
                        <Label htmlFor="kickoff-offset" className="text-xs">
                          Offset kickoff 1T (s de archivo)
                        </Label>
                        <Input
                          id="kickoff-offset"
                          type="number"
                          min={0}
                          step={0.1}
                          placeholder="Auto (marcador)"
                          value={kickoffOffsetSec}
                          disabled={Boolean(isBusy)}
                          className="h-10 bg-background/60 font-mono"
                          onChange={(event) => setKickoffOffsetSec(event.target.value)}
                        />
                      </div>
                      <div className="space-y-1.5">
                        <Label htmlFor="second-half-start" className="text-xs">
                          Inicio 2T (s de archivo)
                        </Label>
                        <Input
                          id="second-half-start"
                          type="number"
                          min={0}
                          step={0.1}
                          placeholder="Auto (marcador)"
                          value={secondHalfStartSec}
                          disabled={Boolean(isBusy)}
                          className="h-10 bg-background/60 font-mono"
                          onChange={(event) =>
                            setSecondHalfStartSec(event.target.value)
                          }
                        />
                      </div>
                    </div>
                    <p className="text-[11px] text-muted-foreground">
                      Vacío = detección automática. Ejemplo full match: 282 / 3521.
                    </p>
                  </div>
                ) : null}
                </div>
              </details>

              <Separator className="bg-border/60" />

              <section aria-labelledby="duration-heading">
                <div className="mb-3">
                  <h2 id="duration-heading" className="text-sm font-semibold text-foreground">
                    Ventana de análisis
                  </h2>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Desde el saque del marcador.
                  </p>
                </div>
                <Select
                  value={durationPreset}
                  onValueChange={(value) => {
                    const preset = value as "5min" | "10min" | "full" | "custom";
                    setDurationPreset(preset);
                    if (preset === "custom") {
                      const parsed = Number(customMinutes);
                      if (
                        customMinutes.trim() &&
                        Number.isFinite(parsed) &&
                        parsed >= 1
                      ) {
                        setDurationMode(`${Math.min(180, Math.round(parsed))}min`);
                      }
                    } else {
                      setDurationMode(preset);
                    }
                  }}
                  disabled={Boolean(isBusy)}
                >
                  <SelectTrigger className="h-11 w-full bg-background/60">
                    <SelectValue placeholder="Elige una duración" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="5min">5 minutos</SelectItem>
                    <SelectItem value="10min">10 minutos</SelectItem>
                    <SelectItem value="custom">Personalizado</SelectItem>
                    <SelectItem value="full">Partido entero</SelectItem>
                  </SelectContent>
                </Select>
                {durationPreset === "custom" ? (
                  <div className="mt-3 flex items-center gap-3">
                    <Input
                      type="number"
                      min={1}
                      max={180}
                      step={1}
                      value={customMinutes}
                      placeholder="Minutos"
                      disabled={Boolean(isBusy)}
                      onChange={(event) => {
                        const raw = event.target.value;
                        setCustomMinutes(raw);
                        const parsed = Number(raw);
                        if (raw.trim() && Number.isFinite(parsed) && parsed >= 1) {
                          setDurationMode(
                            `${Math.min(180, Math.max(1, Math.round(parsed)))}min`,
                          );
                        }
                      }}
                      className="h-11 w-28 bg-background/60 font-mono"
                      aria-label="Minutos personalizados"
                    />
                    <span className="text-sm text-muted-foreground">minutos desde el saque</span>
                  </div>
                ) : null}
              </section>

              <section aria-labelledby="stadium-heading">
                <div className="mb-3">
                  <h2 id="stadium-heading" className="text-sm font-semibold text-foreground">
                    Estadio
                  </h2>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Perfil de cámara / ROI LED. Calibrar en Configuración.
                  </p>
                </div>
                <Select
                  value={stadiumId}
                  onValueChange={(value) => {
                    if (value) setStadiumId(value);
                  }}
                  disabled={Boolean(isBusy)}
                >
                  <SelectTrigger className="h-11 w-full bg-background/60">
                    <SelectValue placeholder="Elegí un estadio" />
                  </SelectTrigger>
                  <SelectContent>
                    {stadiums.map((stadium) => (
                      <SelectItem key={stadium.id} value={stadium.id}>
                        {stadium.nombre}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </section>

              <Tooltip>
                <TooltipTrigger render={<span className="block" />}>
                  <Button
                    type="button"
                    className="h-12 w-full gap-2 bg-primary font-semibold text-primary-foreground shadow-[0_0_24px_oklch(0.7_0.18_145/0.14)] transition-all duration-200 hover:bg-primary/90 hover:shadow-[0_0_30px_oklch(0.7_0.18_145/0.2)]"
                    onClick={handleSubmit}
                    disabled={!canSubmit || Boolean(isBusy)}
                  >
                    {submitting ? (
                      <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />
                    ) : (
                      <ScanLine className="size-4" aria-hidden="true" />
                    )}
                    {submitting ? "Iniciando análisis…" : "Analizar vallas LED"}
                  </Button>
                </TooltipTrigger>
                {(!canSubmit) && (
                  <TooltipContent>
                    Carga un video y activa al menos una marca, o una playlist Lions.
                    {durationPreset === "custom" && !customMinutesValid
                      ? " Indica los minutos personalizados."
                      : ""}
                  </TooltipContent>
                )}
              </Tooltip>
              {connectionError ? (
                <p className="text-sm text-destructive" role="alert">
                  {connectionError}
                </p>
              ) : null}
            </CardContent>
          </Card>

        {recentJobs.length > 0 && (
          <section aria-labelledby="recent-jobs-heading">
            <Card className="border-border/80 bg-card/80 shadow-xl shadow-black/15 backdrop-blur-xl">
              <CardHeader className="border-b border-border/60 pb-5">
                <div className="flex items-start gap-3">
                  <div className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                    <History className="size-4" aria-hidden="true" />
                  </div>
                  <div>
                    <CardTitle id="recent-jobs-heading" className="text-base">
                      Análisis recientes
                    </CardTitle>
                    <CardDescription className="mt-1">
                      Abre uno para revisar el catálogo o exportar.
                    </CardDescription>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="divide-y divide-border/60 p-0">
                {recentJobs.map((summary) => {
                  const isSelected = job?.id === summary.id;
                  const stadiumName =
                    stadiums.find((stadium) => stadium.id === summary.stadium_id)
                      ?.nombre ??
                    summary.stadium_id ??
                    "Estadio";
                  const canDelete =
                    summary.status === "completed" || summary.status === "error";
                  return (
                    <div
                      key={summary.id}
                      className={`flex items-stretch gap-1 transition-colors hover:bg-muted/25 ${
                        isSelected ? "bg-primary/5" : ""
                      }`}
                    >
                      <button
                        type="button"
                        onClick={() => void loadHistoricalJob(summary)}
                        className="flex min-w-0 flex-1 flex-col gap-3 px-5 py-4 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary sm:flex-row sm:items-center sm:justify-between"
                      >
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="font-mono text-xs text-muted-foreground">
                              {summary.id.slice(0, 8)}
                            </span>
                            <Badge
                              variant={
                                summary.status === "completed"
                                  ? "default"
                                  : summary.status === "error"
                                    ? "destructive"
                                    : "secondary"
                              }
                              className="font-mono text-[10px] uppercase tracking-[0.12em]"
                            >
                              {jobStatusLabel(summary.status)}
                            </Badge>
                            {isSelected ? (
                              <Badge variant="outline" className="text-[10px]">
                                Seleccionado
                              </Badge>
                            ) : null}
                          </div>
                          <p className="mt-1 text-sm font-medium text-foreground">
                            {stadiumName}
                          </p>
                          <p className="mt-0.5 text-xs text-muted-foreground">
                            {formatJobDate(summary.created_at)}
                          </p>
                        </div>
                        <div className="grid shrink-0 gap-1 text-xs text-muted-foreground sm:text-right">
                          {summary.status === "completed" ? (
                            <>
                              <span>
                                {summary.summary.brand_count} marca
                                {summary.summary.brand_count === 1 ? "" : "s"}
                              </span>
                              <span className="font-mono tabular-nums">
                                {formatSeconds(summary.summary.total_exposure_seconds)}{" "}
                                de exposición
                              </span>
                            </>
                          ) : summary.status === "processing" ||
                            summary.status === "detecting_kickoff" ? (
                            <span className="font-mono tabular-nums text-primary">
                              {Math.round(summary.progress * 100)}%
                            </span>
                          ) : null}
                        </div>
                      </button>
                      <div className="flex items-center pr-3">
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon-sm"
                          className="size-9 text-muted-foreground hover:bg-destructive/15 hover:text-destructive"
                          disabled={!canDelete}
                          title={
                            canDelete
                              ? "Borrar análisis"
                              : "Solo se pueden borrar análisis terminados"
                          }
                          aria-label={`Borrar análisis ${summary.id.slice(0, 8)}`}
                          onClick={(event) => {
                            event.stopPropagation();
                            setDeleteTarget(summary);
                          }}
                        >
                          <Trash2 className="size-4" aria-hidden="true" />
                        </Button>
                      </div>
                    </div>
                  );
                })}
              </CardContent>
            </Card>
          </section>
        )}
          </>
        ) : job ? (
          <section aria-live="polite" className="pb-10">
            <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                  {jobStatusLabel(job.status)}
                  {job.id ? ` · ${job.id.slice(0, 8)}` : ""}
                </p>
                <h1 className="mt-1 text-2xl font-semibold tracking-tight text-foreground">
                  {job.status === "completed"
                    ? "Revisión de frames"
                    : job.status === "error"
                      ? "Análisis fallido"
                      : "Analizando partido"}
                </h1>
                <p className="mt-1 text-sm text-muted-foreground">
                  {job.status === "detecting_kickoff"
                    ? "Buscando el saque inicial en el marcador…"
                    : job.status === "completed"
                      ? `Ventana analizada: ${formatSeconds(job.result?.analyzed_seconds ?? 0)}. Confirma propuestos y asigna lo dudoso.`
                      : job.status === "error"
                        ? job.error ?? "No se pudo completar el análisis."
                        : job.progress_label || "Preparando el análisis…"}
                </p>
              </div>
              {canLeaveWorkspace ? (
                <Button
                  type="button"
                  variant="outline"
                  className="h-10 gap-2"
                  onClick={resetJob}
                >
                  <ArrowLeft className="size-4" aria-hidden="true" />
                  Nuevo análisis
                </Button>
              ) : null}
            </div>

            <Card className="border-border/80 bg-card/80 shadow-xl shadow-black/15 backdrop-blur-xl">
              <CardContent className="space-y-6 pt-6">
                {job.status !== "completed" && job.status !== "error" ? (
                  <div className="space-y-4">
                    <div>
                      <div className="mb-2 flex items-center justify-between font-mono text-xs">
                        <span className="text-muted-foreground">
                          {job.status === "detecting_kickoff"
                            ? "Detectando kickoff"
                            : "Procesando"}
                        </span>
                        <span className="text-primary">
                          {Math.round(job.progress * 100)}%
                        </span>
                      </div>
                      <Progress value={job.progress * 100} className="h-2 bg-muted/70" />
                    </div>
                    <JobPreviewStill jobId={job.id} />
                    <p className="text-xs text-muted-foreground">
                      Un partido a la vez en esta pestaña. Si necesitas otro, ábrelo en
                      una pestaña nueva.
                    </p>
                    {job.kickoff ? (
                      <div className="grid gap-3 sm:grid-cols-2">
                        <div className="rounded-lg border border-border/70 bg-muted/25 p-3">
                          <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                            Kickoff 1T
                          </p>
                          <p className="mt-1 font-mono text-sm text-foreground">
                            {job.kickoff.first_half_video_seconds.toFixed(1)} s
                          </p>
                        </div>
                        <div className="rounded-lg border border-border/70 bg-muted/25 p-3">
                          <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                            Kickoff 2T
                          </p>
                          <p className="mt-1 font-mono text-sm text-foreground">
                            {job.kickoff.second_half_video_seconds == null
                              ? "No detectado"
                              : `${job.kickoff.second_half_video_seconds.toFixed(1)} s`}
                          </p>
                        </div>
                      </div>
                    ) : null}
                    <CatalogReview jobId={job.id} live readOnly />
                  </div>
                ) : null}

                {job.status === "error" ? (
                  <Button type="button" variant="secondary" onClick={resetJob} className="gap-2">
                    <ScanLine className="size-4" aria-hidden="true" />
                    Volver a configurar
                  </Button>
                ) : null}

                {job.status === "completed" ? (
                  <div className="space-y-8">
                    <CatalogReview jobId={job.id} />
                    {job.result?.compliance && job.result.compliance.length > 0 ? (
                      <ComplianceTable rows={job.result.compliance} />
                    ) : null}
                    <details className="rounded-xl border border-border/70 bg-background/35">
                      <summary className="cursor-pointer list-none px-4 py-3 text-sm font-medium text-foreground [&::-webkit-details-marker]:hidden">
                        Exportar / resumen técnico
                      </summary>
                      <div className="space-y-4 border-t border-border/60 px-4 py-4">
                        <div className="flex flex-wrap items-center gap-2">
                          <a
                            href={exportCsvUrl(job.id)}
                            download={`analisis-${job.id.slice(0, 8)}.csv`}
                          >
                            <Button type="button" variant="outline" className="gap-2">
                              <Download className="size-4" aria-hidden="true" />
                              CSV
                            </Button>
                          </a>
                          <a
                            href={exportXlsxUrl(job.id)}
                            download={`informe-${job.id.slice(0, 8)}.xlsx`}
                          >
                            <Button type="button" variant="outline" className="gap-2">
                              <Download className="size-4" aria-hidden="true" />
                              Excel pipeline
                            </Button>
                          </a>
                        </div>
                        <ResultsTable
                          jobId={job.id}
                          brands={brands}
                          resultBrands={resultBrands}
                        />
                      </div>
                    </details>
                  </div>
                ) : null}
              </CardContent>
            </Card>
          </section>
        ) : null}
      </div>

      {deleteTarget ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm"
          role="dialog"
          aria-modal="true"
          aria-labelledby="delete-job-title"
          onClick={() => {
            if (!deletingJob) setDeleteTarget(null);
          }}
        >
          <div
            className="w-full max-w-md rounded-2xl border border-border bg-card p-5 shadow-2xl"
            onClick={(event) => event.stopPropagation()}
          >
            <h3 id="delete-job-title" className="text-base font-semibold">
              Borrar análisis
            </h3>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              ¿Seguro que quieres borrar{" "}
              <span className="font-mono text-foreground">
                {deleteTarget.id.slice(0, 8)}
              </span>
              ? Se elimina el catálogo, frames e informe de ese partido. No se puede
              deshacer.
            </p>
            <p className="mt-2 text-xs text-muted-foreground">
              {formatJobDate(deleteTarget.created_at)}
              {deleteTarget.stadium_id ? ` · ${deleteTarget.stadium_id}` : ""}
            </p>
            <div className="mt-5 flex justify-end gap-2">
              <Button
                type="button"
                variant="ghost"
                onClick={() => setDeleteTarget(null)}
                disabled={deletingJob}
              >
                Cancelar
              </Button>
              <Button
                type="button"
                variant="destructive"
                className="gap-2"
                onClick={() => void handleDeleteJob()}
                disabled={deletingJob}
              >
                {deletingJob ? (
                  <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />
                ) : (
                  <Trash2 className="size-4" aria-hidden="true" />
                )}
                Borrar
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </main>
  );
}
