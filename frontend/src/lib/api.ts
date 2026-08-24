export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:43124";

export type JobStatus =
  | "queued"
  | "detecting_kickoff"
  | "processing"
  | "completed"
  | "error";

export type JobMode = "single" | "split";
export type DurationMode = "5min" | "10min" | "full";

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
  config: {
    mode: JobMode;
    duration_mode: DurationMode;
    sample_fps: number;
  };
  kickoff: Kickoff | null;
  result: {
    analyzed_seconds: number;
    brands: BrandResult[];
  } | null;
};

export type JobEvent = {
  status: JobStatus;
  progress: number;
  progress_label: string;
  kickoff?: Kickoff | null;
  partial_brands?: BrandResult[];
  error?: string | null;
};

type SubmitJobInput = {
  mode: JobMode;
  durationMode: DurationMode;
  brands: Brand[];
  video?: File;
  videoFirst?: File;
  videoSecond?: File;
};

export async function submitJob(input: SubmitJobInput): Promise<{ id: string }> {
  const form = new FormData();
  form.append("mode", input.mode);
  form.append("duration_mode", input.durationMode);
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
