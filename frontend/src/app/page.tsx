"use client";

import {
  Activity,
  AlertCircle,
  Check,
  ChevronDown,
  CircleHelp,
  Clock3,
  Download,
  FileVideo,
  History,
  Info,
  LoaderCircle,
  Plus,
  ScanLine,
  ShieldCheck,
  SlidersHorizontal,
  Trash2,
  UploadCloud,
  X,
  ZoomIn,
} from "lucide-react";
import Image from "next/image";
import {
  type ChangeEvent,
  type DragEvent,
  useEffect,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";

import {
  type Brand,
  type BrandResult,
  type ComplianceRow,
  type DurationMode,
  type Job,
  type JobMode,
  type JobSummary,
  type SavedBrand,
  type Stadium,
  type VerificationStatus,
  DOUBTFUL_STATUSES,
  exportCsvUrl,
  exportXlsxUrl,
  getActiveJob,
  getFrameUrl,
  getJob,
  listBrands,
  listJobs,
  listStadiums,
  proposeCalibration,
  saveCalibration,
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";

const ACCEPTED_VIDEO_TYPES = ".mp4,.mov,.mkv,.webm";

function slugify(value: string) {
  return (
    value
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/(^-|-$)/g, "") || "brand"
  );
}

function formatBytes(bytes: number) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatSeconds(totalSeconds: number) {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes} min ${seconds} s`;
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
      onInvalid?.("Ese archivo no parece un video compatible. Usá MP4, MOV, MKV o WebM.");
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

  useEffect(() => {
    if (!selectedFrame) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSelectedFrame(null);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [selectedFrame]);

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
      {selectedFrame &&
        createPortal(
          <div
            className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-black/80 p-4 backdrop-blur-sm"
            role="dialog"
            aria-modal="true"
            aria-label={`Frame ampliado: ${selectedFrame.label}`}
            onClick={() => setSelectedFrame(null)}
          >
            <div
              className="relative my-auto w-full max-w-5xl rounded-2xl border border-border bg-card p-3 shadow-2xl"
              onClick={(event) => event.stopPropagation()}
            >
              <div className="mb-3 flex items-center justify-between gap-4 px-1">
                <p className="truncate font-mono text-xs text-muted-foreground">
                  {selectedFrame.label}
                </p>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="size-10 shrink-0"
                  onClick={() => setSelectedFrame(null)}
                  aria-label="Cerrar frame ampliado"
                >
                  <X className="size-4" aria-hidden="true" />
                </Button>
              </div>
              <Image
                src={selectedFrame.src}
                alt={selectedFrame.label}
                width={1280}
                height={720}
                unoptimized
                className="h-auto max-h-[78vh] w-full rounded-xl object-contain"
                style={{ width: "100%", height: "auto" }}
              />
            </div>
          </div>,
          document.body,
        )}
    </>
  );
}

const CALIBRATION_ACCEPT = ".jpg,.jpeg,.png,.bmp,.webp,.mp4,.mov,.mkv,.webm";

function StadiumCalibrationSection({
  onSaved,
}: {
  onSaved: (stadiumId: string) => void;
}) {
  const [sampleFile, setSampleFile] = useState<File>();
  const [stadiumId, setCalibStadiumId] = useState("");
  const [nombre, setNombre] = useState("");
  const [pais, setPais] = useState("");
  const [cameraJson, setCameraJson] = useState("");
  const [previews, setPreviews] = useState<{
    scoreboard?: string;
    grass?: string;
  }>({});
  const [busy, setBusy] = useState<"propose" | "save" | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleSample = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setSampleFile(file);
    setError(null);
    setMessage(null);
  };

  const handlePropose = async () => {
    if (!sampleFile) {
      setError("Sube una imagen o un video de muestra.");
      return;
    }
    setBusy("propose");
    setError(null);
    setMessage(null);
    try {
      const proposal = await proposeCalibration(sampleFile);
      setCameraJson(JSON.stringify(proposal.camera, null, 2));
      setPreviews({
        scoreboard: proposal.previews?.scoreboard_jpeg_b64
          ? `data:image/jpeg;base64,${proposal.previews.scoreboard_jpeg_b64}`
          : undefined,
        grass: proposal.previews?.grass_mask_jpeg_b64
          ? `data:image/jpeg;base64,${proposal.previews.grass_mask_jpeg_b64}`
          : undefined,
      });
      setMessage("Propuesta lista. Revisa el crop HSV y guarda el perfil.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo proponer.");
    } finally {
      setBusy(null);
    }
  };

  const handleSave = async () => {
    if (!stadiumId.trim() || !nombre.trim()) {
      setError("Indica el id y el nombre del estadio.");
      return;
    }
    let camera;
    try {
      camera = JSON.parse(cameraJson);
    } catch {
      setError("El JSON de la cámara no es válido.");
      return;
    }
    setBusy("save");
    setError(null);
    setMessage(null);
    try {
      const saved = await saveCalibration({
        stadium_id: stadiumId.trim(),
        nombre: nombre.trim(),
        pais: pais.trim() || null,
        camera,
      });
      setMessage(
        `Perfil ${saved.id} guardado (versión ${saved.version}). Ya aparece en el selector.`,
      );
      onSaved(saved.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo guardar.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <details className="rounded-xl border border-border/70 bg-background/35">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-3 text-sm font-medium text-foreground [&::-webkit-details-marker]:hidden">
        <SlidersHorizontal className="size-4 text-primary" aria-hidden="true" />
        Calibrar estadio
        <ChevronDown className="ml-auto size-4 text-muted-foreground" aria-hidden="true" />
      </summary>
      <div className="space-y-3 border-t border-border/60 px-3 py-3">
        <p className="text-xs text-muted-foreground">
          Sube un frame o un clip corto. El sistema propone crop del marcador y
          HSV del césped; tú confirmas y guardas una nueva versión del perfil.
        </p>
        <label className="flex cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed border-border/80 bg-background/40 px-3 py-4 text-center hover:border-primary/60">
          <input
            type="file"
            accept={CALIBRATION_ACCEPT}
            onChange={handleSample}
            className="sr-only"
          />
          <UploadCloud className="mb-2 size-4 text-muted-foreground" aria-hidden="true" />
          <span className="text-xs font-medium text-foreground">
            {sampleFile ? sampleFile.name : "Subir imagen o video de muestra"}
          </span>
        </label>
        <Button
          type="button"
          variant="secondary"
          className="h-10 w-full gap-2"
          onClick={() => void handlePropose()}
          disabled={busy !== null || !sampleFile}
        >
          {busy === "propose" ? (
            <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />
          ) : null}
          Proponer
        </Button>
        {(previews.scoreboard || previews.grass) && (
          <div className="grid grid-cols-2 gap-2">
            {previews.scoreboard ? (
              <figure>
                <img
                  src={previews.scoreboard}
                  alt="Recorte propuesto del marcador"
                  className="h-20 w-full rounded-lg border border-border/70 object-cover"
                />
                <figcaption className="mt-1 font-mono text-[10px] text-muted-foreground">
                  Marcador
                </figcaption>
              </figure>
            ) : null}
            {previews.grass ? (
              <figure>
                <img
                  src={previews.grass}
                  alt="Máscara HSV del césped"
                  className="h-20 w-full rounded-lg border border-border/70 object-cover"
                />
                <figcaption className="mt-1 font-mono text-[10px] text-muted-foreground">
                  Césped
                </figcaption>
              </figure>
            ) : null}
          </div>
        )}
        <div className="grid gap-2">
          <div>
            <Label htmlFor="calib-stadium-id" className="text-xs">
              Id del estadio
            </Label>
            <Input
              id="calib-stadium-id"
              value={stadiumId}
              onChange={(event) => setCalibStadiumId(event.target.value)}
              placeholder="capwell"
              className="mt-1 h-10 font-mono text-sm"
            />
          </div>
          <div>
            <Label htmlFor="calib-nombre" className="text-xs">
              Nombre
            </Label>
            <Input
              id="calib-nombre"
              value={nombre}
              onChange={(event) => setNombre(event.target.value)}
              placeholder="Estadio Capwell"
              className="mt-1 h-10 text-sm"
            />
          </div>
          <div>
            <Label htmlFor="calib-pais" className="text-xs">
              País (opcional)
            </Label>
            <Input
              id="calib-pais"
              value={pais}
              onChange={(event) => setPais(event.target.value)}
              placeholder="Ecuador"
              className="mt-1 h-10 text-sm"
            />
          </div>
          <div>
            <Label htmlFor="calib-camera-json" className="text-xs">
              Perfil de cámara (JSON editable)
            </Label>
            <textarea
              id="calib-camera-json"
              value={cameraJson}
              onChange={(event) => setCameraJson(event.target.value)}
              spellCheck={false}
              rows={10}
              className="mt-1 w-full rounded-md border border-input bg-background/60 p-2 font-mono text-[11px] text-foreground"
              placeholder='Pulsa "Proponer" para rellenar crop, HSV y banda LED.'
            />
          </div>
        </div>
        <Button
          type="button"
          className="h-10 w-full"
          onClick={() => void handleSave()}
          disabled={busy !== null || !cameraJson.trim()}
        >
          {busy === "save" ? (
            <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />
          ) : null}
          Guardar perfil
        </Button>
        {error ? (
          <p className="text-xs text-destructive">{error}</p>
        ) : null}
        {message ? (
          <p className="text-xs text-muted-foreground">{message}</p>
        ) : null}
      </div>
    </details>
  );
}

export default function Home() {
  const [mode, setMode] = useState<JobMode>("single");
  const [durationMode, setDurationMode] = useState<DurationMode>("5min");
  const [durationPreset, setDurationPreset] = useState<"5min" | "10min" | "full" | "custom">(
    "5min",
  );
  const [customMinutes, setCustomMinutes] = useState(16);
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
  const [brandName, setBrandName] = useState("");
  const [savedBrands, setSavedBrands] = useState<SavedBrand[]>([]);
  const [libraryBrandId, setLibraryBrandId] = useState("");
  const [job, setJob] = useState<Job | null>(null);
  const [recentJobs, setRecentJobs] = useState<JobSummary[]>([]);
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
  const canSubmit =
    hasVideo && (brands.length > 0 || Boolean(usePlaylist && playlist));

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
    void listBrands()
      .then((items) => {
        if (!cancelled) setSavedBrands(items);
      })
      .catch(() => {
        // The job form stays usable without the brand library.
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const addBrand = () => {
    const name = brandName.trim();
    if (!name) return;
    const baseId = slugify(name);
    let id = baseId;
    let suffix = 2;
    while (brands.some((brand) => brand.id === id)) {
      id = `${baseId}-${suffix}`;
      suffix += 1;
    }
    setBrands((current) => [
      ...current,
      {
        id,
        name,
        aliases: [name.replace(/\s+/g, ""), name.toUpperCase()],
      },
    ]);
    setBrandName("");
  };

  const addBrandFromLibrary = () => {
    const saved = savedBrands.find((item) => item.id === libraryBrandId);
    if (!saved || brands.some((brand) => brand.id === saved.id)) return;
    setBrands((current) => [
      ...current,
      {
        id: saved.id,
        name: saved.nombre,
        aliases: saved.aliases.length
          ? saved.aliases
          : [saved.nombre.replace(/\s+/g, ""), saved.nombre.toUpperCase()],
      },
    ]);
    setLibraryBrandId("");
  };

  const removeBrand = (id: string) => {
    setBrands((current) => current.filter((brand) => brand.id !== id));
  };

  const setLogo = (id: string, logo: File | undefined) => {
    setBrands((current) =>
      current.map((brand) => (brand.id === id ? { ...brand, logo } : brand)),
    );
  };

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
        brands,
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

  const resultBrands =
    job?.result?.brands ??
    (job?.status === "processing"
      ? []
      : brands.map((brand) => emptyResult(brand)));

  return (
    <main className="min-h-dvh overflow-x-hidden bg-background">
      <div className="pointer-events-none fixed inset-0 bg-[radial-gradient(circle_at_15%_0%,oklch(0.32_0.12_145/0.12),transparent_32%),radial-gradient(circle_at_85%_10%,oklch(0.35_0.1_75/0.09),transparent_25%)]" />
      <div className="relative mx-auto flex min-h-dvh w-full max-w-7xl flex-col px-4 py-5 sm:px-6 lg:px-8">
        <header className="flex items-center justify-between border-b border-border/60 pb-5">
          <div className="flex items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-[0_0_24px_oklch(0.7_0.18_145/0.2)]">
              <ScanLine className="size-5" aria-hidden="true" />
            </div>
            <div>
              <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.24em] text-primary">
                Match ops / 01
              </p>
              <p className="text-sm font-semibold tracking-tight text-foreground">
                Football Ads Detector
              </p>
            </div>
          </div>
          <Badge
            variant="outline"
            className="gap-2 border-primary/25 bg-primary/5 px-3 py-1.5 font-mono text-[10px] uppercase tracking-[0.16em] text-primary"
          >
            <span className="size-1.5 rounded-full bg-primary shadow-[0_0_8px_currentColor]" />
            CPU / local
          </Badge>
        </header>

        <section className="grid flex-1 gap-8 py-9 lg:grid-cols-[minmax(0,1.12fr)_minmax(360px,0.88fr)] lg:gap-12 lg:py-14">
          <div className="flex flex-col justify-center">
            <div className="mb-9 max-w-2xl">
              <Badge className="mb-5 gap-2 border border-primary/20 bg-primary/10 px-3 py-1.5 font-mono text-[10px] uppercase tracking-[0.18em] text-primary hover:bg-primary/10">
                <Activity className="size-3.5" aria-hidden="true" />
                LED sideline intelligence
              </Badge>
              <h1 className="max-w-xl text-4xl font-semibold leading-[1.05] tracking-[-0.045em] text-foreground sm:text-6xl">
                Medí cada segundo de tus{" "}
                <span className="text-primary [text-shadow:0_0_24px_oklch(0.7_0.18_145/0.18)]">
                  vallas LED.
                </span>
              </h1>
              <p className="mt-5 max-w-xl text-base leading-7 text-muted-foreground sm:text-lg">
                Subí el partido, cargá tus marcas y obtené apariciones,
                exposición y frames de inicio. El análisis mira la franja a
                ras de césped, no las lonas fijas ni los fondos de arco.
              </p>
            </div>

            <div className="grid max-w-2xl gap-3 sm:grid-cols-3">
              {[
                { icon: ShieldCheck, label: "ROI geométrica", value: "Solo LED" },
                { icon: Clock3, label: "Muestreo", value: "1 frame / s" },
                { icon: ScanLine, label: "Lectura", value: "OCR CPU" },
              ].map(({ icon: Icon, label, value }) => (
                <div
                  key={label}
                  className="rounded-xl border border-border/70 bg-card/35 p-4 backdrop-blur-sm"
                >
                  <Icon className="mb-5 size-4 text-primary" aria-hidden="true" />
                  <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                    {label}
                  </p>
                  <p className="mt-1 text-sm font-medium text-foreground">{value}</p>
                </div>
              ))}
            </div>
          </div>

          <Card className="border-border/80 bg-card/80 shadow-2xl shadow-black/20 backdrop-blur-xl">
            <CardHeader className="border-b border-border/60 pb-5">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <CardTitle className="text-lg">Configurar análisis</CardTitle>
                  <CardDescription className="mt-1.5">
                    Prepará la fuente y las marcas a buscar.
                  </CardDescription>
                </div>
                <div className="rounded-lg border border-border/70 bg-muted/30 p-2 text-muted-foreground">
                  <CircleHelp className="size-4" aria-hidden="true" />
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-7 pt-6">
              <section aria-labelledby="video-heading">
                <div className="mb-3 flex items-center justify-between">
                  <div>
                    <h2 id="video-heading" className="text-sm font-semibold text-foreground">
                      Video del partido
                    </h2>
                    <p className="mt-1 text-xs text-muted-foreground">
                      MP4, MOV, MKV o WebM
                    </p>
                  </div>
                  <Badge variant="secondary" className="font-mono text-[10px]">
                    01 / 03
                  </Badge>
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
                      label="Arrastrá el partido acá"
                      hint="o elegí un archivo · partido completo"
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
                <div className="mb-3 flex items-center justify-between">
                  <div>
                    <h2 id="brands-heading" className="text-sm font-semibold text-foreground">
                      Marcas a detectar
                    </h2>
                    <p className="mt-1 text-xs text-muted-foreground">
                      El nombre es obligatorio. El logo es opcional.
                    </p>
                  </div>
                  <Badge variant="secondary" className="font-mono text-[10px]">
                    02 / 03
                  </Badge>
                </div>
                <div className="flex gap-2">
                  <div className="relative flex-1">
                    <Label htmlFor="brand-name" className="sr-only">
                      Nombre de la marca
                    </Label>
                    <Input
                      id="brand-name"
                      value={brandName}
                      onChange={(event) => setBrandName(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") {
                          event.preventDefault();
                          addBrand();
                        }
                      }}
                      placeholder="Ej. NETT plus"
                      className="h-11 bg-background/60 pr-3"
                      disabled={Boolean(isBusy)}
                    />
                  </div>
                  <Button
                    type="button"
                    variant="secondary"
                    className="h-11 gap-2 px-4"
                    onClick={addBrand}
                    disabled={!brandName.trim() || Boolean(isBusy)}
                  >
                    <Plus className="size-4" aria-hidden="true" />
                    <span className="hidden sm:inline">Agregar</span>
                  </Button>
                </div>
                {savedBrands.length ? (
                  <div className="mt-3 rounded-lg border border-border/70 bg-muted/20 p-3">
                    <p className="text-xs font-medium text-foreground">
                      Biblioteca de marcas
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      Reutilizá marcas guardadas con logo en el servidor.
                    </p>
                    <div className="mt-2 flex gap-2">
                      <Select
                        value={libraryBrandId}
                        onValueChange={(value) => {
                          if (value) setLibraryBrandId(value);
                        }}
                        disabled={Boolean(isBusy)}
                      >
                        <SelectTrigger className="h-10 flex-1 bg-background/60">
                          <SelectValue placeholder="Elegir marca guardada" />
                        </SelectTrigger>
                        <SelectContent>
                          {savedBrands.map((saved) => (
                            <SelectItem
                              key={saved.id}
                              value={saved.id}
                              disabled={brands.some((brand) => brand.id === saved.id)}
                            >
                              {saved.nombre}
                              {saved.has_logo ? " · logo" : ""}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <Button
                        type="button"
                        variant="outline"
                        className="h-10 shrink-0 px-3"
                        onClick={addBrandFromLibrary}
                        disabled={
                          !libraryBrandId ||
                          Boolean(isBusy) ||
                          brands.some((brand) => brand.id === libraryBrandId)
                        }
                      >
                        Usar
                      </Button>
                    </div>
                  </div>
                ) : null}
                {brands.length ? (
                  <div className="mt-3 space-y-2">
                    {brands.map((brand) => (
                      <div
                        key={brand.id}
                        className="flex flex-wrap items-center gap-2 rounded-lg border border-border/70 bg-muted/25 p-2.5"
                      >
                        <Badge
                          variant="outline"
                          className="max-w-[45%] gap-2 truncate bg-background/50"
                        >
                          <span className="size-1.5 shrink-0 rounded-full bg-primary" />
                          <span className="truncate">{brand.name}</span>
                        </Badge>
                        <label className="ml-auto flex min-h-9 cursor-pointer items-center gap-2 rounded-md border border-transparent px-2 text-xs text-muted-foreground transition-colors hover:border-border hover:text-foreground">
                          <Input
                            type="file"
                            accept="image/png,image/jpeg,image/webp"
                            className="sr-only"
                            onChange={(event) => setLogo(brand.id, event.target.files?.[0])}
                            disabled={Boolean(isBusy)}
                          />
                          <UploadCloud className="size-3.5" aria-hidden="true" />
                          {brand.logo ? "Logo cargado" : "Logo opcional"}
                        </label>
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          className="size-9 text-muted-foreground hover:text-destructive"
                          onClick={() => removeBrand(brand.id)}
                          disabled={Boolean(isBusy)}
                          aria-label={`Quitar ${brand.name}`}
                        >
                          <Trash2 className="size-4" aria-hidden="true" />
                        </Button>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="mt-3 rounded-lg border border-dashed border-border/70 px-4 py-3 text-center text-xs text-muted-foreground">
                    Todavía no agregaste marcas.
                  </div>
                )}
              </section>

              <Separator className="bg-border/60" />

              <section aria-labelledby="playlist-heading">
                <div className="mb-3">
                  <h2 id="playlist-heading" className="text-sm font-semibold text-foreground">
                    Playlist / reporte Lions
                  </h2>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Sin playlist el job hace discovery a 1 fps. Con Excel se verifica
                    cada pauta 1T/2T con estados HIT/MISS/dudosos y sale el informe.
                  </p>
                </div>
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
                      Con playlist se analiza el partido completo.
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
              </section>

              <Separator className="bg-border/60" />

              <section aria-labelledby="duration-heading">
                <div className="mb-3 flex items-center justify-between">
                  <div>
                    <h2 id="duration-heading" className="text-sm font-semibold text-foreground">
                      Ventana de análisis
                    </h2>
                    <p className="mt-1 text-xs text-muted-foreground">
                      Útil para validar clips antes del partido entero.
                    </p>
                  </div>
                  <Badge variant="secondary" className="font-mono text-[10px]">
                    03 / 03
                  </Badge>
                </div>
                <Select
                  value={durationPreset}
                  onValueChange={(value) => {
                    const preset = value as "5min" | "10min" | "full" | "custom";
                    setDurationPreset(preset);
                    if (preset === "custom") {
                      setDurationMode(`${customMinutes}min`);
                    } else {
                      setDurationMode(preset);
                    }
                  }}
                  disabled={Boolean(isBusy)}
                >
                  <SelectTrigger className="h-11 w-full bg-background/60">
                    <SelectValue placeholder="Elegí una duración" />
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
                      disabled={Boolean(isBusy)}
                      onChange={(event) => {
                        const next = Number(event.target.value);
                        const minutes = Number.isFinite(next)
                          ? Math.min(180, Math.max(1, Math.round(next)))
                          : 1;
                        setCustomMinutes(minutes);
                        setDurationMode(`${minutes}min`);
                      }}
                      className="h-11 w-28 bg-background/60 font-mono"
                      aria-label="Minutos personalizados"
                    />
                    <span className="text-sm text-muted-foreground">minutos desde el saque</span>
                  </div>
                ) : null}
                <div className="mt-3 flex gap-2 text-xs leading-5 text-muted-foreground">
                  <Info className="mt-0.5 size-3.5 shrink-0 text-primary" aria-hidden="true" />
                  Arranca en el saque inicial que leemos del marcador (arriba a la izquierda).
                </div>
              </section>

              <section aria-labelledby="stadium-heading">
                <div className="mb-3">
                  <h2 id="stadium-heading" className="text-sm font-semibold text-foreground">
                    Estadio
                  </h2>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Perfil geométrico de la cancha para el ROI de vallas LED.
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
                <div className="mt-3">
                  <StadiumCalibrationSection
                    onSaved={(savedId) => {
                      void listStadiums()
                        .then((items) => {
                          if (items.length) {
                            setStadiums(items);
                            setStadiumId(savedId);
                          }
                        })
                        .catch(() => {
                          setStadiumId(savedId);
                        });
                    }}
                  />
                </div>
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
                    Cargá un video y al menos una marca, o una playlist Lions.
                  </TooltipContent>
                )}
              </Tooltip>
            </CardContent>
          </Card>
        </section>

        {recentJobs.length > 0 && (
          <section aria-labelledby="recent-jobs-heading" className="pb-8">
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
                      Abrí un análisis anterior para ver resultados o exportar CSV.
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
                  return (
                    <button
                      key={summary.id}
                      type="button"
                      onClick={() => void loadHistoricalJob(summary)}
                      className={`flex w-full flex-col gap-3 px-5 py-4 text-left transition-colors hover:bg-muted/25 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary sm:flex-row sm:items-center sm:justify-between ${
                        isSelected ? "bg-primary/5" : ""
                      }`}
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
                  );
                })}
              </CardContent>
            </Card>
          </section>
        )}

        {(connectionError || job) && (
          <section aria-live="polite" className="pb-10">
            <Card className="border-border/80 bg-card/80 shadow-xl shadow-black/15 backdrop-blur-xl">
              <CardHeader className="flex flex-row items-start justify-between gap-4 border-b border-border/60 pb-5">
                <div className="flex gap-3">
                  <div
                    className={`mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-lg ${
                      job?.status === "error" || connectionError
                        ? "bg-destructive/10 text-destructive"
                        : job?.status === "completed"
                          ? "bg-primary/10 text-primary"
                          : "bg-amber-400/10 text-amber-300"
                    }`}
                  >
                    {job?.status === "completed" ? (
                      <Check className="size-4" aria-hidden="true" />
                    ) : job?.status === "error" || connectionError ? (
                      <AlertCircle className="size-4" aria-hidden="true" />
                    ) : (
                      <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />
                    )}
                  </div>
                  <div>
                    <CardTitle className="text-base">
                      {job?.status === "completed"
                        ? "Análisis completado"
                        : job?.status === "error" || connectionError
                          ? "No pudimos completar el análisis"
                          : "Análisis en curso"}
                    </CardTitle>
                    <CardDescription className="mt-1">
                      {job?.status === "detecting_kickoff"
                        ? "Buscando el saque inicial en el marcador…"
                        : job?.status === "completed"
                          ? `Analizamos ${formatSeconds(job.result?.analyzed_seconds ?? 0)} de ${
                              mode === "split" ? "los videos cargados" : "video"
                            }.`
                          : job?.status === "error" || connectionError
                            ? job?.error ?? connectionError
                            : job?.progress_label ?? "Preparando el análisis…"}
                    </CardDescription>
                  </div>
                </div>
                {job?.status === "completed" || job?.status === "error" ? (
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="size-9 text-muted-foreground"
                    onClick={resetJob}
                    aria-label="Cerrar resultados"
                  >
                    <X className="size-4" aria-hidden="true" />
                  </Button>
                ) : null}
              </CardHeader>
              <CardContent className="space-y-5 pt-6">
                {job && job.status !== "completed" && job.status !== "error" && (
                  <div>
                    <div className="mb-2 flex items-center justify-between font-mono text-xs">
                      <span className="text-muted-foreground">
                        {job.status === "detecting_kickoff"
                          ? "Detectando kickoff"
                          : "Procesando job"}
                      </span>
                      <span className="text-primary">
                        {Math.round(job.progress * 100)}%
                      </span>
                    </div>
                    <Progress value={job.progress * 100} className="h-2 bg-muted/70" />
                  </div>
                )}

                {job?.status === "error" || connectionError ? (
                  <Button type="button" variant="secondary" onClick={resetJob} className="gap-2">
                    <ScanLine className="size-4" aria-hidden="true" />
                    Volver a intentar
                  </Button>
                ) : null}

                {job?.status === "processing" && resultBrands.length > 0 && (
                  <div>
                    <div className="mb-4">
                      <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-primary">
                        Lectura parcial
                      </p>
                      <h3 className="mt-1 text-lg font-semibold">
                        Exposición acumulada
                      </h3>
                    </div>
                    <ResultsTable
                      jobId={job.id}
                      brands={brands}
                      resultBrands={resultBrands}
                    />
                  </div>
                )}

                {job?.kickoff && (
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
                    <p className="text-xs text-muted-foreground sm:col-span-2">
                      {job.kickoff.note}
                    </p>
                  </div>
                )}

                {job?.status === "completed" && (
                  <div className="space-y-8">
                    {job.result?.compliance && job.result.compliance.length > 0 ? (
                      <ComplianceTable rows={job.result.compliance} />
                    ) : null}
                    <div>
                      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
                        <div>
                          <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-primary">
                            Reporte / marcas
                          </p>
                          <h3 className="mt-1 text-lg font-semibold">Exposición detectada</h3>
                          {typeof job.result?.hit_rate === "number" ? (
                            <p className="mt-1 text-xs text-muted-foreground">
                              Cumplimiento HIT/(HIT+MISS):{" "}
                              {Math.round(job.result.hit_rate * 100)}%
                            </p>
                          ) : null}
                        </div>
                        <div className="flex flex-wrap items-center gap-2">
                          <a
                            href={exportCsvUrl(job.id)}
                            download={`analisis-${job.id.slice(0, 8)}.csv`}
                          >
                            <Button type="button" variant="outline" className="gap-2">
                              <Download className="size-4" aria-hidden="true" />
                              Exportar CSV
                            </Button>
                          </a>
                          {job.result?.report_xlsx_path || job.status === "completed" ? (
                            <a
                              href={exportXlsxUrl(job.id)}
                              download={`informe-${job.id.slice(0, 8)}.xlsx`}
                            >
                              <Button type="button" variant="outline" className="gap-2">
                                <Download className="size-4" aria-hidden="true" />
                                Informe Excel
                              </Button>
                            </a>
                          ) : null}
                          <Badge variant="outline" className="gap-2 border-primary/25 text-primary">
                            <Check className="size-3.5" aria-hidden="true" />
                            Datos listos
                          </Badge>
                        </div>
                      </div>
                      <ResultsTable
                        jobId={job.id}
                        brands={brands}
                        resultBrands={resultBrands}
                      />
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          </section>
        )}

        {!job && !connectionError && (
          <div className="flex items-center justify-center gap-2 pb-5 text-center text-xs text-muted-foreground">
            <Info className="size-3.5" aria-hidden="true" />
            <span>
              Subí el video del partido y la lista de marcas. Solo medimos la
              valla LED a ras de césped.
            </span>
          </div>
        )}
      </div>
    </main>
  );
}
