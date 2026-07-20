// Typed client for the Not Studio API.

export type MusicProvider = "ace_step_local";
export type TrackVerdict = "liked" | "unreviewed";
export type JobStatus =
  "queued" | "in_progress" | "completed" | "failed" | "cancelled";

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
  album_title?: string | null;
  album?: Record<string, unknown> | string | null;
  notes?: string | null;
  artwork_prompt?: string | null;
}

export interface PromptPlan {
  album_title?: string | null;
  summary?: string | null;
  notes?: string | null;
  visual_direction?: {
    palette: string[];
    motifs: string[];
    style: string;
    avoid: string[];
  } | null;
  artwork_prompt?: string | null;
  prompts: PromptSpec[];
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
  artwork_guidance: string;
  output_schema: Record<string, unknown>;
  example: PromptPlan;
  taste_profile: {
    liked_genres: string[];
    liked_examples: TasteExample[];
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
  album_id: string | null;
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

export interface GenerationRun {
  id: string;
  status: string;
  stage: string;
  brief: string;
  artwork_guidance: string;
  style_reference_id: string | null;
  cover_output_size: number;
  auto_start: boolean;
  plan: PromptPlan | null;
  params: Record<string, unknown>;
  album_id: string | null;
  plan_job_id: string | null;
  generation_job_id: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface StyleReference {
  id: string;
  path: string;
  mime: string;
  width: number;
  height: number;
  size_bytes: number;
  original_name: string;
  created_at: string;
}

export interface CoverAsset {
  id: string;
  owner_type: "album" | "track";
  owner_id: string;
  version: number;
  status: "queued" | "generating" | "ready" | "failed";
  selected: boolean;
  path: string;
  mime: string;
  width: number;
  height: number;
  size_bytes: number;
  prompt: string;
  effective_prompt: string;
  style_reference_id: string | null;
  seed: number | null;
  provider: string;
  model: string;
  config: Record<string, unknown>;
  job_id: string | null;
  error: string | null;
  created_at: string;
  selected_at: string | null;
}

export interface Health {
  status: string;
  jobs: string;
  model: {
    status: "loading" | "ready" | "failed" | "disabled" | "skipped";
    provider: string;
    model: string;
    checkpoint?: string;
    device: string;
    language_model?: string;
    language_model_backend?: string;
    error?: string;
  } | null;
  providers: MusicProviderInfo[];
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!(init?.body instanceof FormData))
    headers.set("Content-Type", "application/json");
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
    throw new Error(
      typeof detail === "string" ? detail : JSON.stringify(detail),
    );
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

async function downloadReq(path: string, data: unknown): Promise<Blob> {
  const res = await fetch(`/api${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const payload = await res.json();
      detail =
        typeof payload.detail === "string"
          ? payload.detail
          : JSON.stringify(payload.detail);
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return res.blob();
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
  deleteHistory: (id: string) =>
    req<void>(`/history/${id}`, { method: "DELETE" }),
  audioUrl: (id: string) => `/api/history/${id}/audio`,
  artworkUrl: (id: string, version?: string) =>
    `/api/studio/tracks/${id}/artwork${version ? `?v=${encodeURIComponent(version)}` : ""}`,
  albumArtworkUrl: (title: string, version?: string) => {
    const query = new URLSearchParams({ title });
    if (version) query.set("v", version);
    return `/api/studio/albums/artwork?${query.toString()}`;
  },

  generateAlbum: (data: unknown) =>
    req<Job>("/studio/albums/generate", { method: "POST", body: body(data) }),
  downloadAlbum: (data: {
    title: string;
    item_ids: string[];
    include_track_videos: boolean;
  }) => downloadReq("/studio/albums/export", data),
  generateTracks: (data: unknown) =>
    req<Job>("/studio/generate", { method: "POST", body: body(data) }),
  tracks: (params?: { verdict?: TrackVerdict }) => {
    const q = new URLSearchParams(params as Record<string, string>).toString();
    return req<HistoryItem[]>(`/studio/tracks${q ? `?${q}` : ""}`);
  },
  reviewTrack: (
    id: string,
    data: { verdict: TrackVerdict; note?: string | null },
  ) =>
    req<HistoryItem>(`/studio/tracks/${id}/review`, {
      method: "PATCH",
      body: body(data),
    }),
  setTrackAlbum: (id: string, albumTitle: string | null) =>
    req<HistoryItem>(`/studio/tracks/${id}/album`, {
      method: "PATCH",
      body: body({ album_title: albumTitle }),
    }),
  regenerateTrack: (id: string) =>
    req<Job>(`/studio/tracks/${id}/regenerate`, { method: "POST" }),
  setTrackArtwork: (id: string, file: File) => {
    const data = new FormData();
    data.append("file", file);
    return req<HistoryItem>(`/studio/tracks/${id}/artwork`, {
      method: "POST",
      body: data,
    });
  },
  setAlbumArtwork: (title: string, file: File) => {
    const data = new FormData();
    data.append("title", title);
    data.append("file", file);
    return req<{ title: string; updated_at: string }>(
      "/studio/albums/artwork",
      {
        method: "POST",
        body: data,
      },
    );
  },
  promptKit: () => req<PromptKit>("/studio/prompt-kit"),

  generationRuns: () => req<GenerationRun[]>("/studio/album-runs"),
  generationRun: (id: string) => req<GenerationRun>(`/studio/album-runs/${id}`),
  createGenerationRun: (data: unknown) =>
    req<GenerationRun>("/studio/album-runs", {
      method: "POST",
      body: body(data),
    }),
  updateGenerationPlan: (id: string, plan: PromptPlan) =>
    req<GenerationRun>(`/studio/album-runs/${id}/plan`, {
      method: "PATCH",
      body: body({ plan }),
    }),
  replanGenerationRun: (id: string) =>
    req<GenerationRun>(`/studio/album-runs/${id}/replan`, { method: "POST" }),
  generateGenerationRun: (id: string, generateCovers = true) =>
    req<Job>(`/studio/album-runs/${id}/generate`, {
      method: "POST",
      body: body({ generate_covers: generateCovers }),
    }),
  cancelGenerationRun: (id: string) =>
    req<GenerationRun>(`/studio/album-runs/${id}/cancel`, { method: "POST" }),
  uploadStyleReference: (file: File) => {
    const data = new FormData();
    data.append("file", file);
    return req<StyleReference>("/studio/style-references", {
      method: "POST",
      body: data,
    });
  },
  styleReferenceUrl: (id: string) => `/api/studio/style-references/${id}/image`,
  coverUrl: (id: string) => `/api/studio/covers/${id}/image`,
  covers: (ownerType?: "album" | "track") =>
    req<CoverAsset[]>(
      `/studio/covers${ownerType ? `?owner_type=${ownerType}` : ""}`,
    ),
  trackCovers: (id: string) => req<CoverAsset[]>(`/studio/tracks/${id}/covers`),
  albumCovers: (id: string) => req<CoverAsset[]>(`/studio/albums/${id}/covers`),
  generateTrackCover: (id: string, data: unknown) =>
    req<Job>(`/studio/tracks/${id}/covers/generate`, {
      method: "POST",
      body: body(data),
    }),
  generateAlbumCover: (id: string, data: unknown) =>
    req<Job>(`/studio/albums/${id}/covers/generate`, {
      method: "POST",
      body: body(data),
    }),
  generateAllAlbumCovers: (id: string, data: unknown) =>
    req<Job>(`/studio/albums/${id}/covers/generate-all`, {
      method: "POST",
      body: body(data),
    }),
  selectCover: (id: string) =>
    req<CoverAsset>(`/studio/covers/${id}/select`, {
      method: "PUT",
      body: body({ selected: true }),
    }),
};

export function jobsWebSocketUrl(): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/api/jobs/ws`;
}
