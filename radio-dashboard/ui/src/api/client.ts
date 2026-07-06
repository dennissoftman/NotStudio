// Typed client for the Radio Dashboard API (served under /api, proxied in dev).

export type BackendKind = "speech" | "music";
export type Provider = "mock" | "kokoro" | "stable_audio";
export type JobStatus =
  | "queued"
  | "in_progress"
  | "completed"
  | "failed"
  | "cancelled"
  | "deferred";
export type StreamStatus = "stopped" | "buffering" | "live";

export interface Backend {
  id: string;
  name: string;
  kind: BackendKind;
  provider: Provider;
  config: Record<string, unknown>;
  enabled: boolean;
  created_at: string;
}

export interface BackendInfo {
  provider: Provider;
  kinds: string[];
  available: boolean;
  detail: string;
  default_config: Record<string, unknown>;
}

export interface InsertSpec {
  kind: "news" | "info" | "ad" | "station_id" | "jingle" | "weather";
  cadence_seconds: number;
  texts: string[];
  voice?: string | null;
  asset?: string | null;
  ducking: boolean;
  bed_volume_db: number;
  insert_volume_db: number;
}

export interface MusicSpec {
  prompts: string[];
  genre?: string | null;
  track_seconds: number;
  crossfade_seconds: number;
}

export interface ProgramConfig {
  target_lufs: number;
  crossfade_seconds: number;
  music: MusicSpec;
  inserts: InsertSpec[];
}

export interface Program {
  id: string;
  name: string;
  description: string;
  music_backend_id: string | null;
  speech_backend_id: string | null;
  config: ProgramConfig;
  created_at: string;
  updated_at: string;
}

export interface IcecastConfig {
  enabled: boolean;
  host: string;
  port: number;
  mount: string;
  username: string;
  password: string;
  format: "mp3" | "ogg";
}

export interface Stream {
  id: string;
  name: string;
  program_id: string | null;
  status: StreamStatus;
  sample_rate: number;
  channels: number;
  buffer_min_seconds: number;
  batch_target_seconds: number;
  batch_max_seconds: number;
  icecast: IcecastConfig | null;
  created_at: string;
  updated_at: string;
}

export interface Job {
  id: string;
  type: string;
  status: JobStatus;
  stream_id: string | null;
  program_id: string | null;
  schedule_id: string | null;
  params: Record<string, unknown>;
  progress: number;
  message: string;
  result: Record<string, unknown> | null;
  error: string | null;
  created_at: string;
  enqueued_at: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface Schedule {
  id: string;
  name: string;
  action: "render_batch" | "start_stream" | "stop_stream";
  program_id: string | null;
  stream_id: string | null;
  trigger_type: "cron" | "interval" | "date";
  trigger: Record<string, unknown>;
  enabled: boolean;
  last_run_at: string | null;
  next_run_at: string | null;
  created_at: string;
}

export interface HistoryItem {
  id: string;
  kind: string;
  title: string;
  stream_id: string | null;
  program_id: string | null;
  job_id: string | null;
  path: string;
  vtt_path: string | null;
  sample_rate: number;
  channels: number;
  duration_seconds: number;
  size_bytes: number;
  lufs: number | null;
  meta: Record<string, unknown>;
  created_at: string;
}

export interface PlayoutSegment {
  id: string;
  stream_id: string;
  history_item_id: string;
  sequence: number;
  duration_seconds: number;
  state: "ready" | "playing" | "played";
  created_at: string;
  played_at: string | null;
}

export interface BufferStatus {
  stream_id: string;
  status: StreamStatus;
  ready_seconds: number;
  min_seconds: number;
  segments_ready: number;
  segments_total: number;
  generating: boolean;
}

export interface Health {
  status: string;
  queue: boolean;
  providers: BackendInfo[];
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

const body = (data: unknown) => JSON.stringify(data);

export const api = {
  health: () => req<Health>("/health"),

  // backends
  providers: () => req<BackendInfo[]>("/backends/providers"),
  backends: () => req<Backend[]>("/backends"),
  createBackend: (data: Partial<Backend>) =>
    req<Backend>("/backends", { method: "POST", body: body(data) }),
  updateBackend: (id: string, data: Partial<Backend>) =>
    req<Backend>(`/backends/${id}`, { method: "PATCH", body: body(data) }),
  deleteBackend: (id: string) =>
    req<void>(`/backends/${id}`, { method: "DELETE" }),

  // programs
  programs: () => req<Program[]>("/programs"),
  createProgram: (data: unknown) =>
    req<Program>("/programs", { method: "POST", body: body(data) }),
  updateProgram: (id: string, data: unknown) =>
    req<Program>(`/programs/${id}`, { method: "PATCH", body: body(data) }),
  deleteProgram: (id: string) =>
    req<void>(`/programs/${id}`, { method: "DELETE" }),

  // streams
  streams: () => req<Stream[]>("/streams"),
  createStream: (data: unknown) =>
    req<Stream>("/streams", { method: "POST", body: body(data) }),
  updateStream: (id: string, data: unknown) =>
    req<Stream>(`/streams/${id}`, { method: "PATCH", body: body(data) }),
  deleteStream: (id: string) => req<void>(`/streams/${id}`, { method: "DELETE" }),
  startStream: (id: string) =>
    req<Stream>(`/streams/${id}/start`, { method: "POST" }),
  stopStream: (id: string) =>
    req<Stream>(`/streams/${id}/stop`, { method: "POST" }),
  buffer: (id: string) => req<BufferStatus>(`/streams/${id}/buffer`),
  segments: (id: string) => req<PlayoutSegment[]>(`/streams/${id}/segments`),

  // jobs
  jobs: (params?: { stream_id?: string; status?: string }) => {
    const q = new URLSearchParams(params as Record<string, string>).toString();
    return req<Job[]>(`/jobs${q ? `?${q}` : ""}`);
  },
  submitJob: (data: unknown) =>
    req<Job>("/jobs", { method: "POST", body: body(data) }),
  cancelJob: (id: string) => req<Job>(`/jobs/${id}/cancel`, { method: "POST" }),

  // schedules
  schedules: () => req<Schedule[]>("/schedules"),
  createSchedule: (data: unknown) =>
    req<Schedule>("/schedules", { method: "POST", body: body(data) }),
  updateSchedule: (id: string, data: unknown) =>
    req<Schedule>(`/schedules/${id}`, { method: "PATCH", body: body(data) }),
  deleteSchedule: (id: string) =>
    req<void>(`/schedules/${id}`, { method: "DELETE" }),

  // history
  history: (params?: { stream_id?: string }) => {
    const q = new URLSearchParams(params as Record<string, string>).toString();
    return req<HistoryItem[]>(`/history${q ? `?${q}` : ""}`);
  },
  deleteHistory: (id: string) => req<void>(`/history/${id}`, { method: "DELETE" }),
  audioUrl: (id: string) => `/api/history/${id}/audio`,
  timelineUrl: (id: string) => `/api/history/${id}/timeline`,
  liveUrl: (id: string) => `/api/streams/${id}/live.mp3`,
  hlsUrl: (id: string) => `/api/streams/${id}/hls/playlist.m3u8`,
};
