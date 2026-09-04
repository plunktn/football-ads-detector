export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:43124";

export type JobStatus =
  | "queued"
  | "detecting_kickoff"
  | "processing"
  | "completed"
  | "error";

export type JobMode = "single" | "split";
export type AnalysisMode = "discovery" | "playlist_verify";
/** "full" or "{N}min" e.g. "5min", "16min", "22min" */
export type DurationMode = string;

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
  hit: boolean;
  observed_video_sec?: number | null;
  capture_path?: string | null;
  source?: string | null;
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
};

export async function createBrand(input: CreateBrandInput): Promise<SavedBrand> {
  const form = new FormData();
  form.append("name", input.name);
  if (input.aliases?.length) {
    form.append("aliases", JSON.stringify(input.aliases));
  }
  if (input.logo) {
    form.append("logo", input.logo);
  }

  const response = await fetch(`${API_URL}/brands`, {
    method: "POST",
    body: form,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body.detail ?? "No se pudo guardar la marca.");
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
  return status === "completed" || status === "error";
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
