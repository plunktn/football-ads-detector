"use client";

import {
  Activity,
  AlertCircle,
  Check,
  CircleHelp,
  Clock3,
  FileVideo,
  Info,
  LoaderCircle,
  Plus,
  ScanLine,
  ShieldCheck,
  Trash2,
  UploadCloud,
  X,
} from "lucide-react";
import {
  type ChangeEvent,
  type DragEvent,
  useEffect,
  useRef,
  useState,
} from "react";

import {
  type Brand,
  type BrandResult,
  type DurationMode,
  type Job,
  type JobMode,
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

function ResultsTable({
  brands,
  resultBrands,
}: {
  brands: Brand[];
  resultBrands: BrandResult[];
}) {
  const resultById = new Map(resultBrands.map((brand) => [brand.brand_id, brand]));
  const rows = brands.map((brand) => resultById.get(brand.id) ?? emptyResult(brand));

  return (
    <div className="overflow-hidden rounded-xl border border-border/80">
      <div className="overflow-x-auto">
        <table className="w-full min-w-150 text-left text-sm">
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
                <td className="px-4 py-4 font-medium text-foreground">{brand.name}</td>
                <td className="px-4 py-4 text-right font-mono tabular-nums text-foreground">
                  {brand.appearances}
                </td>
                <td className="px-4 py-4 text-right font-mono tabular-nums text-foreground">
                  {brand.minutes} min {brand.seconds} s
                </td>
                <td className="px-4 py-4 font-mono text-xs tabular-nums text-muted-foreground">
                  {brand.start_frames.length ? brand.start_frames.join(", ") : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function Home() {
  const [mode, setMode] = useState<JobMode>("single");
  const [durationMode, setDurationMode] = useState<DurationMode>("5min");
  const [video, setVideo] = useState<File>();
  const [videoFirst, setVideoFirst] = useState<File>();
  const [videoSecond, setVideoSecond] = useState<File>();
  const [brands, setBrands] = useState<Brand[]>([]);
  const [brandName, setBrandName] = useState("");
  const [job, setJob] = useState<Job | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const stopWatching = useRef<(() => void) | null>(null);

  const isBusy =
    submitting ||
    job?.status === "queued" ||
    job?.status === "detecting_kickoff" ||
    job?.status === "processing";
  const hasVideo =
    mode === "single" ? Boolean(video) : Boolean(videoFirst && videoSecond);

  useEffect(() => {
    return () => stopWatching.current?.();
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

  const removeBrand = (id: string) => {
    setBrands((current) => current.filter((brand) => brand.id !== id));
  };

  const setLogo = (id: string, logo: File | undefined) => {
    setBrands((current) =>
      current.map((brand) => (brand.id === id ? { ...brand, logo } : brand)),
    );
  };

  const handleSubmit = async () => {
    if (!hasVideo || !brands.length || isBusy) return;
    setSubmitting(true);
    setConnectionError(null);
    stopWatching.current?.();
    try {
      const created = await submitJob({
        mode,
        durationMode,
        brands,
        video,
        videoFirst,
        videoSecond,
      });
      const initialJob: Job = {
        id: created.id,
        status: "queued",
        progress: 0,
        progress_label: "En cola",
        error: null,
        config: { mode, duration_mode: durationMode, sample_fps: 1 },
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
      setConnectionError(
        error instanceof Error ? error.message : "No se pudo iniciar el análisis.",
      );
    } finally {
      setSubmitting(false);
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
                  value={durationMode}
                  onValueChange={(value) => setDurationMode(value as DurationMode)}
                  disabled={Boolean(isBusy)}
                >
                  <SelectTrigger className="h-11 w-full bg-background/60">
                    <SelectValue placeholder="Elegí una duración" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="5min">5 minutos</SelectItem>
                    <SelectItem value="10min">10 minutos</SelectItem>
                    <SelectItem value="full">Partido entero</SelectItem>
                  </SelectContent>
                </Select>
                <div className="mt-3 flex gap-2 text-xs leading-5 text-muted-foreground">
                  <Info className="mt-0.5 size-3.5 shrink-0 text-primary" aria-hidden="true" />
                  Arranca en el saque inicial que leemos del marcador (arriba a la izquierda).
                </div>
              </section>

              <Tooltip>
                <TooltipTrigger render={<span className="block" />}>
                  <Button
                    type="button"
                    className="h-12 w-full gap-2 bg-primary font-semibold text-primary-foreground shadow-[0_0_24px_oklch(0.7_0.18_145/0.14)] transition-all duration-200 hover:bg-primary/90 hover:shadow-[0_0_30px_oklch(0.7_0.18_145/0.2)]"
                    onClick={handleSubmit}
                    disabled={!hasVideo || !brands.length || Boolean(isBusy)}
                  >
                    {submitting ? (
                      <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />
                    ) : (
                      <ScanLine className="size-4" aria-hidden="true" />
                    )}
                    {submitting ? "Iniciando análisis…" : "Analizar vallas LED"}
                  </Button>
                </TooltipTrigger>
                {(!hasVideo || !brands.length) && (
                  <TooltipContent>
                    Cargá un video y al menos una marca para continuar.
                  </TooltipContent>
                )}
              </Tooltip>
            </CardContent>
          </Card>
        </section>

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
                    <ResultsTable brands={brands} resultBrands={resultBrands} />
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
                  <div>
                    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
                      <div>
                        <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-primary">
                          Reporte / marcas
                        </p>
                        <h3 className="mt-1 text-lg font-semibold">Exposición detectada</h3>
                      </div>
                      <Badge variant="outline" className="gap-2 border-primary/25 text-primary">
                        <Check className="size-3.5" aria-hidden="true" />
                        Datos listos
                      </Badge>
                    </div>
                    <ResultsTable brands={brands} resultBrands={resultBrands} />
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
