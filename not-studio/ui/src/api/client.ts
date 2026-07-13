// Typed client for the Not Studio API.

export type MusicProvider = "stable_audio_local" | "stable_audio_runpod";
export type TrackVerdict = "liked" | "disliked" | "unreviewed";
export type JobStatus = "queued" | "in_progress" | "completed" | "failed" | "cancelled";

export interface MusicProviderInfo {
  provider: MusicProvider;
  kinds: string[];
  available: boolean;
  detail: string;
  default_config: Record<string, unknown>;
}

export interface PromptSpec {
  title: string;
  genre: string;
  prompt: string;
  duration: number;
}

export interface TasteExample {
  title: string;
  genre: string;
  prompt: string;
  note: string | null;
}

export interface PromptKit {
  task: string;
  requirements: string[];
  output_schema: Record<string, unknown>;
  example: PromptSpec[];
  taste_profile: {
    liked_genres: string[];
    disliked_genres: string[];
    liked_examples: TasteExample[];
    disliked_examples: TasteExample[];
  };
}

export interface Job {
  id: string;
  type: string;
  status: JobStatus;
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

export interface HistoryItem {
  id: string;
  kind: string;
  title: string;
  job_id: string | null;
  path: string;
  sample_rate: number;
  channels: number;
  duration_seconds: number;
  size_bytes: number;
  lufs: number | null;
  meta: Record<string, unknown>;
  created_at: string;
}

export interface Health {
  status: string;
  jobs: string;
  model: {
    status: "loading" | "ready" | "disabled" | "skipped";
    provider: string;
    model: string;
    device: string;
  } | null;
  providers: MusicProviderInfo[];
}

export interface VideoBackgroundUpload {
  id: string;
  filename: string;
  size_bytes: number;
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!(init?.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const res = await fetch(`/api${path}`, {
    ...init,
    headers,
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

  jobs: (params?: { status?: string }) => {
    const q = new URLSearchParams(params as Record<string, string>).toString();
    return req<Job[]>(`/jobs${q ? `?${q}` : ""}`);
  },
  cancelJob: (id: string) => req<Job>(`/jobs/${id}/cancel`, { method: "POST" }),
  retryJob: (id: string) => req<Job>(`/jobs/${id}/retry`, { method: "POST" }),
  deleteJob: (id: string) => req<void>(`/jobs/${id}`, { method: "DELETE" }),

  history: () => req<HistoryItem[]>("/history"),
  deleteHistory: (id: string) => req<void>(`/history/${id}`, { method: "DELETE" }),
  audioUrl: (id: string) => `/api/history/${id}/audio`,

  generateAlbum: (data: unknown) =>
    req<Job>("/studio/albums/generate", { method: "POST", body: body(data) }),
  generateTracks: (data: unknown) =>
    req<Job>("/studio/generate", { method: "POST", body: body(data) }),
  tracks: (params?: { verdict?: TrackVerdict }) => {
    const q = new URLSearchParams(params as Record<string, string>).toString();
    return req<HistoryItem[]>(`/studio/tracks${q ? `?${q}` : ""}`);
  },
  reviewTrack: (id: string, data: { verdict: TrackVerdict; note?: string | null }) =>
    req<HistoryItem>(`/studio/tracks/${id}/review`, { method: "PATCH", body: body(data) }),
  makeVideo: (data: unknown) =>
    req<Job>("/studio/videos", { method: "POST", body: body(data) }),
  uploadVideoBackground: (file: File) => {
    const data = new FormData();
    data.append("file", file);
    return req<VideoBackgroundUpload>("/studio/video-backgrounds", {
      method: "POST",
      body: data,
    });
  },
  videos: () => req<HistoryItem[]>("/studio/videos"),
  promptKit: () => req<PromptKit>("/studio/prompt-kit"),
};

export function jobsWebSocketUrl(): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/api/jobs/ws`;
}
