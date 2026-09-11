export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:43124";

export type JobStatus =
  | "queued"
  | "detecting_kickoff"
  | "processing"
  | "completed"
  | "cancelled"
  | "error";

export type JobMode = "single" | "split";
export type AnalysisMode = "discovery" | "playlist_verify";
/** "full" or "{N}min" e.g. "5min", "16min", "22min" */
export type DurationMode = string;

export type VerificationStatus =
  | "HIT"
  | "MISS"
  | "NO_EVIDENCE"
  | "AMBIGUOUS"
  | "OFFSET"
  | "PAST_EOF";

export const DOUBTFUL_STATUSES: VerificationStatus[] = [
  "NO_EVIDENCE",
  "AMBIGUOUS",
  "OFFSET",
];

export type Brand = {
  id: string;
  name: string;
  aliases: string[];
  logo?: File;
};

export type BrandResult = {
  brand_id: string;
  name: string;
  appearances: number;
  total_seconds: number;
  minutes: number;
  seconds: number;
  start_frames: number[];
  segments: SegmentResult[];
};

export type SegmentResult = {
  half: string;
  clock_start: string;
  clock_end: string;
  video_seconds_start: number;
  video_seconds_end: number;
  start_frame: number;
  end_frame: number;
  duration_seconds: number;
  zone_id?: string | null;
  posicion?: string | null;
};

export type Kickoff = {
  first_half_video_seconds: number;
  second_half_video_seconds: number | null;
  note: string;
};

export type Job = {
  id: string;
  status: JobStatus;
  progress: number;
  progress_label: string;
  error: string | null;
  created_at?: string | null;
  config: {
    mode: JobMode;
    duration_mode: DurationMode;
    sample_fps: number;
    stadium_id?: string | null;
    analysis_mode?: AnalysisMode;
    kickoff_offset_sec?: number | null;
    second_half_start_sec?: number | null;
  };
  kickoff: Kickoff | null;
  result: {
    analyzed_seconds: number;
    brands: BrandResult[];
    fixed_brands?: BrandResult[];
    analysis_mode?: AnalysisMode;
    compliance?: ComplianceRow[];
    hit_rate?: number | null;
    report_xlsx_path?: string | null;
  } | null;
};

export type ComplianceRow = {
  brand: string;
  period: string;
  scheduled_start_sec: number;
  duration_sec: number;
  status: VerificationStatus;
  hit: boolean;
  delta_sec?: number | null;
  reason?: string | null;
  observed_video_sec?: number | null;
  capture_path?: string | null;
  source?: string | null;
  zone?: string | null;
};

export type JobSummary = {
  id: string;
  status: JobStatus;
  progress: number;
  stadium_id: string | null;
  created_at: string;
  summary: {
    brand_count: number;
    total_exposure_seconds: number;
    analyzed_seconds: number;
  };
};

export type JobEvent = {
  status: JobStatus;
  progress: number;
  progress_label: string;
  kickoff?: Kickoff | null;
  partial_brands?: BrandResult[];
  error?: string | null;
};

export type Stadium = {
  id: string;
  nombre: string;
};

export type SavedBrand = {
  id: string;
  nombre: string;
  aliases: string[];
  has_logo: boolean;
};

export type BrandSummary = {
  id: string;
  nombre: string;
  aliases: string[];
  has_logo: boolean;
  activo?: boolean;
  group_id?: string | null;
};

export type BrandGroup = {
  id: string;
  titulo: string;
  brands: BrandSummary[];
};

export type CatalogMachineLabel = "positive" | "attention" | "empty";

export type CatalogFrame = {
  id: number;
  half: string;
  frame_idx: number;
  time_seconds: number;
  zone_id?: string | null;
  posicion?: string | null;
  ocr_text?: string;
  machine_label: CatalogMachineLabel;
  brand_id?: string | null;
  user_verdict?: string | null;
  image_url: string;
  crop_image_url?: string | null;
  has_context?: boolean;
  visual_hash?: string | null;
  similarity_group?: number | null;
};

export type JobCatalog = {
  job_id: string;
  catalog_confirmed_at: string | null;
  discarded_count: number;
  brands: { brand_id: string; name: string; frames: CatalogFrame[] }[];
  attention: CatalogFrame[];
  empty: CatalogFrame[];
  progress: {
    positives: number;
    attention: number;
    empty: number;
    confirmed: boolean;
  };
};

export function resolveApiUrl(pathOrUrl: string): string {
  if (/^https?:\/\//i.test(pathOrUrl)) return pathOrUrl;
  const path = pathOrUrl.startsWith("/") ? pathOrUrl : `/${pathOrUrl}`;
  return `${API_URL}${path}`;
}

export type CameraProfilePayload = {
  id: string;
  variante: "default" | "dia" | "noche";
  scoreboard_crop: { x: number; y: number; w: number; h: number };
  grass_hsv: { lower: number[]; upper: number[] };
  led_band: {
    top_frac: number;
    height_frac: number;
    min_height_px: number;
    max_height_px: number;
  };
  grass_y_top_frac?: number;
  grass_y_bot_frac?: number;
  grass_min_ratio?: number;
  matte_yellow?: unknown;
  panel_zones?: unknown;
};

export type CalibrationProposal = {
  camera: CameraProfilePayload;
  previews?: {
    scoreboard_jpeg_b64?: string | null;
    grass_mask_jpeg_b64?: string | null;
  };
};

export type SaveCalibrationPayload = {
  stadium_id: string;
  nombre: string;
  pais?: string | null;
  camera: CameraProfilePayload;
};

export type CalibrationSaveResult = {
  id: string;
  nombre: string;
  pais?: string | null;
  profile_id: string;
  version: number;
  yaml_path?: string | null;
  camera: CameraProfilePayload;
};

function apiErrorMessage(body: unknown, fallback: string): string {
  if (!body || typeof body !== "object") return fallback;
  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail) && detail.length) {
    return detail
      .map((item) =>
        typeof item === "string"
          ? item
          : typeof item === "object" && item && "msg" in item
            ? String((item as { msg: unknown }).msg)
            : "",
      )
      .filter(Boolean)
      .join(" ");
  }
  return fallback;
}

const DEFAULT_STADIUMS: Stadium[] = [
  { id: "ligaecuabet", nombre: "LigaEcuabet (default)" },
];

export async function listStadiums(): Promise<Stadium[]> {
  const response = await fetch(`${API_URL}/stadiums`, {
    cache: "no-store",
  });
  if (response.status === 404) {
    return DEFAULT_STADIUMS;
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(body?.detail ?? "No se pudieron cargar los estadios.");
  }
  return body;
}

export async function listBrands(): Promise<SavedBrand[]> {
  const response = await fetch(`${API_URL}/brands`, {
    cache: "no-store",
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(body?.detail ?? "No se pudieron cargar las marcas guardadas.");
  }
  return body;
}

type CreateBrandInput = {
  name: string;
  aliases?: string[];
  logo?: File;
  group_id?: string;
};

export async function createBrand(input: CreateBrandInput): Promise<BrandSummary> {
  const form = new FormData();
  form.append("name", input.name);
  if (input.aliases?.length) {
    form.append("aliases", JSON.stringify(input.aliases));
  }
  if (input.logo) {
    form.append("logo", input.logo);
  }
  if (input.group_id) {
    form.append("group_id", input.group_id);
  }

  const response = await fetch(`${API_URL}/brands`, {
    method: "POST",
    body: form,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(apiErrorMessage(body, "No se pudo guardar la marca."));
  }
  return body;
}

export async function listBrandGroups(): Promise<BrandGroup[]> {
  const response = await fetch(`${API_URL}/brand-groups`, {
    cache: "no-store",
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(apiErrorMessage(body, "No se pudieron cargar los grupos."));
  }
  return body ?? [];
}

export async function createBrandGroup(titulo: string): Promise<BrandGroup> {
  const response = await fetch(`${API_URL}/brand-groups`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ titulo }),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(apiErrorMessage(body, "No se pudo crear el grupo."));
  }
  return body;
}

export async function deleteBrandGroup(groupId: string): Promise<void> {
  const response = await fetch(
    `${API_URL}/brand-groups/${encodeURIComponent(groupId)}`,
    { method: "DELETE" },
  );
  if (response.status === 204) return;
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(apiErrorMessage(body, "No se pudo eliminar el grupo."));
  }
}

type PatchBrandInput = {
  activo?: boolean;
  group_id?: string | null;
  nombre?: string;
  logo?: File;
};

export async function patchBrand(
  brandId: string,
  patch: PatchBrandInput,
): Promise<BrandSummary> {
  const url = `${API_URL}/brands/${encodeURIComponent(brandId)}`;
  const hasFile = Boolean(patch.logo);
  let response: Response;
  if (hasFile) {
    const form = new FormData();
    if (patch.logo) form.append("logo", patch.logo);
    if (patch.activo !== undefined) form.append("activo", String(patch.activo));
    if (patch.group_id !== undefined) {
      form.append("group_id", patch.group_id ?? "");
    }
    if (patch.nombre !== undefined) form.append("nombre", patch.nombre);
    response = await fetch(url, { method: "PATCH", body: form });
  } else {
    response = await fetch(url, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        activo: patch.activo,
        group_id: patch.group_id,
        nombre: patch.nombre,
      }),
    });
  }
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(apiErrorMessage(body, "No se pudo actualizar la marca."));
  }
  return body;
}

export async function deleteBrand(brandId: string): Promise<void> {
  const response = await fetch(
    `${API_URL}/brands/${encodeURIComponent(brandId)}`,
    { method: "DELETE" },
  );
  if (response.status === 204) return;
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(apiErrorMessage(body, "No se pudo eliminar la marca."));
  }
}

export async function getJobCatalog(jobId: string): Promise<JobCatalog> {
  const response = await fetch(
    `${API_URL}/jobs/${encodeURIComponent(jobId)}/catalog`,
    { cache: "no-store" },
  );
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(apiErrorMessage(body, "No se pudo cargar el catálogo."));
  }
  return body;
}

export function catalogFrameImageUrl(jobId: string, frameId: number): string {
  return `${API_URL}/jobs/${encodeURIComponent(jobId)}/catalog/frames/${frameId}/image`;
}

export function catalogFrameCropUrl(jobId: string, frameId: number): string {
  return `${catalogFrameImageUrl(jobId, frameId)}?kind=crop`;
}

export function jobPreviewUrl(jobId: string): string {
  return `${API_URL}/jobs/${encodeURIComponent(jobId)}/preview.jpg`;
}

export type CatalogFramePatch =
  | { action: "false_positive" }
  | { action: "assign"; brand_id: string };

export async function patchCatalogFrame(
  jobId: string,
  frameId: number,
  patch: CatalogFramePatch,
): Promise<CatalogFrame | JobCatalog | Record<string, unknown>> {
  const response = await fetch(
    `${API_URL}/jobs/${encodeURIComponent(jobId)}/catalog/frames/${frameId}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    },
  );
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(apiErrorMessage(body, "No se pudo actualizar el recorte."));
  }
  return body;
}

export async function confirmJobCatalog(jobId: string): Promise<JobCatalog> {
  const response = await fetch(
    `${API_URL}/jobs/${encodeURIComponent(jobId)}/catalog/confirm`,
    { method: "POST" },
  );
  if (response.status === 204) {
    return getJobCatalog(jobId);
  }
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(apiErrorMessage(body, "No se pudo confirmar el catálogo."));
  }
  if (body && typeof body === "object" && "brands" in body) {
    return body as JobCatalog;
  }
  return getJobCatalog(jobId);
}

export type ReportFrame = {
  id: number;
  half: string;
  frame_idx: number;
  time_seconds: number;
  posicion?: string | null;
  ocr_text?: string;
  image_url: string;
  crop_image_url?: string | null;
  has_context?: boolean;
};

export type ReportSegment = {
  half: string;
  clock_start: string;
  clock_end: string;
  video_seconds_start: number;
  video_seconds_end: number;
  duration_seconds: number;
  posicion?: string | null;
  frame_count: number;
  sample_frame: ReportFrame;
  frames: ReportFrame[];
};

export type ReportBrand = {
  brand_id: string;
  name: string;
  appearances: number;
  total_seconds: number;
  minutes: number;
  seconds: number;
  duration_label: string;
  frame_count: number;
  count_1t: number;
  count_2t: number;
  segments: ReportSegment[];
};

export type JobReport = {
  job_id: string;
  catalog_confirmed_at: string | null;
  confirmed: boolean;
  stadium_id?: string | null;
  created_at?: string | null;
  summary: {
    brand_count: number;
    appearances: number;
    total_seconds: number;
    duration_label: string;
    minutes: number;
    seconds: number;
  };
  brands: ReportBrand[];
  analyzed_seconds?: number | null;
};

export async function getJobReport(jobId: string): Promise<JobReport> {
  const response = await fetch(
    `${API_URL}/jobs/${encodeURIComponent(jobId)}/report`,
    { cache: "no-store" },
  );
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(apiErrorMessage(body, "No se pudo cargar el informe."));
  }
  return body;
}

export async function proposeCalibration(file: File): Promise<CalibrationProposal> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`${API_URL}/calibration/propose`, {
    method: "POST",
    body: form,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(apiErrorMessage(body, "No se pudo proponer la calibración."));
  }
  return body;
}

export async function saveCalibration(
  payload: SaveCalibrationPayload,
): Promise<CalibrationSaveResult> {
  const response = await fetch(`${API_URL}/calibration/save`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(apiErrorMessage(body, "No se pudo guardar el perfil."));
  }
  return body;
}

type SubmitJobInput = {
  mode: JobMode;
  durationMode: DurationMode;
  stadiumId: string;
  brands: Brand[];
  video?: File;
  videoFirst?: File;
  videoSecond?: File;
  playlist?: File;
  analysisMode?: AnalysisMode;
  kickoffOffsetSec?: number | null;
  secondHalfStartSec?: number | null;
};

export async function submitJob(input: SubmitJobInput): Promise<{ id: string }> {
  const form = new FormData();
  form.append("mode", input.mode);
  form.append("duration_mode", input.durationMode);
  form.append("stadium_id", input.stadiumId);
  form.append("analysis_mode", input.analysisMode ?? "discovery");
  form.append(
    "brands",
    JSON.stringify(
      input.brands.map(({ id, name, aliases }) => ({ id, name, aliases })),
    ),
  );

  if (input.mode === "single" && input.video) {
    form.append("video", input.video);
  }
  if (input.mode === "split" && input.videoFirst && input.videoSecond) {
    form.append("video_first", input.videoFirst);
    form.append("video_second", input.videoSecond);
  }
  if (input.playlist) {
    form.append("playlist", input.playlist);
  }
  if (
    input.kickoffOffsetSec != null &&
    Number.isFinite(input.kickoffOffsetSec)
  ) {
    form.append("kickoff_offset_sec", String(input.kickoffOffsetSec));
  }
  if (
    input.secondHalfStartSec != null &&
    Number.isFinite(input.secondHalfStartSec)
  ) {
    form.append("second_half_start_sec", String(input.secondHalfStartSec));
  }
  for (const brand of input.brands) {
    if (brand.logo) {
      form.append(`logo_${brand.id}`, brand.logo);
    }
  }

  const response = await fetch(`${API_URL}/jobs`, {
    method: "POST",
    body: form,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body.detail ?? "No se pudo crear el análisis.");
  }
  return body;
}

export async function getJob(jobId: string): Promise<Job> {
  const response = await fetch(`${API_URL}/jobs/${jobId}`, {
    cache: "no-store",
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body.detail ?? "No se pudo consultar el análisis.");
  }
  return body;
}

export async function listJobs(): Promise<JobSummary[]> {
  const response = await fetch(`${API_URL}/jobs`, {
    cache: "no-store",
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(body?.detail ?? "No se pudo cargar el historial de análisis.");
  }
  return body ?? [];
}

export async function deleteJob(jobId: string): Promise<void> {
  const response = await fetch(`${API_URL}/jobs/${encodeURIComponent(jobId)}`, {
    method: "DELETE",
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(apiErrorMessage(body, "No se pudo borrar el análisis."));
  }
}

export async function cancelJob(jobId: string): Promise<Job> {
  const response = await fetch(
    `${API_URL}/jobs/${encodeURIComponent(jobId)}/cancel`,
    { method: "POST" },
  );
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(apiErrorMessage(body, "No se pudo detener el análisis."));
  }
  return body as Job;
}

export function exportCsvUrl(jobId: string): string {
  return `${API_URL}/jobs/${encodeURIComponent(jobId)}/export.csv`;
}

export function exportXlsxUrl(jobId: string): string {
  return `${API_URL}/jobs/${encodeURIComponent(jobId)}/export.xlsx`;
}

export async function getActiveJob(): Promise<Job | null> {
  const response = await fetch(`${API_URL}/jobs/active`, {
    cache: "no-store",
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(body?.detail ?? "No se pudo recuperar el análisis.");
  }
  return body;
}

export function getFrameUrl(
  jobId: string,
  half: string,
  frameIdx: number,
): string {
  const params = new URLSearchParams({ half });
  return `${API_URL}/jobs/${encodeURIComponent(jobId)}/frames/${frameIdx}?${params.toString()}`;
}

function isTerminal(status: JobStatus) {
  return status === "completed" || status === "error" || status === "cancelled";
}

export function watchJob(
  jobId: string,
  onUpdate: (job: Partial<Job> & { status: JobStatus }) => void,
  onError: (message: string) => void,
) {
  let source: EventSource | null = new EventSource(
    `${API_URL}/jobs/${jobId}/events`,
  );
  let pollingTimer: ReturnType<typeof setInterval> | null = null;
  let closed = false;

  const stopPolling = () => {
    if (pollingTimer) {
      clearInterval(pollingTimer);
      pollingTimer = null;
    }
  };

  const poll = async () => {
    try {
      const job = await getJob(jobId);
      onUpdate(job);
      if (isTerminal(job.status)) {
        cleanup();
      }
    } catch (error) {
      onError(error instanceof Error ? error.message : "Error de conexión.");
    }
  };

  const startPolling = () => {
    if (pollingTimer || closed) return;
    void poll();
    pollingTimer = setInterval(() => void poll(), 1000);
  };

  const cleanup = () => {
    closed = true;
    source?.close();
    source = null;
    stopPolling();
  };

  source.onmessage = (message) => {
    try {
      const event = JSON.parse(message.data) as JobEvent;
      onUpdate({
        id: jobId,
        status: event.status,
        progress: event.progress,
        progress_label: event.progress_label,
        kickoff: event.kickoff,
        error: event.error ?? null,
        result: event.partial_brands
          ? { analyzed_seconds: 0, brands: event.partial_brands }
          : null,
      });
      if (isTerminal(event.status)) {
        cleanup();
      }
    } catch {
      onError("El backend envió un evento inválido.");
    }
  };

  source.onerror = () => {
    source?.close();
    source = null;
    startPolling();
  };

  return cleanup;
}
