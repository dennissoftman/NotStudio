import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { api, type Backend } from "./client";

const keys = {
  health: ["health"],
  providers: ["providers"],
  backends: ["backends"],
  programs: ["programs"],
  streams: ["streams"],
  jobs: (streamId?: string) => ["jobs", streamId ?? "all"],
  buffer: (id: string) => ["buffer", id],
  segments: (id: string) => ["segments", id],
  schedules: ["schedules"],
  history: (streamId?: string) => ["history", streamId ?? "all"],
};

export function useHealth() {
  return useQuery({ queryKey: keys.health, queryFn: api.health });
}
export function useProviders() {
  return useQuery({ queryKey: keys.providers, queryFn: api.providers });
}

// --- backends ---------------------------------------------------------------
export function useBackends() {
  return useQuery({ queryKey: keys.backends, queryFn: api.backends });
}
export function useCreateBackend() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Partial<Backend>) => api.createBackend(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.backends }),
  });
}
export function useUpdateBackend() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<Backend> }) =>
      api.updateBackend(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.backends }),
  });
}
export function useDeleteBackend() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteBackend(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.backends }),
  });
}

// --- programs ---------------------------------------------------------------
export function usePrograms() {
  return useQuery({ queryKey: keys.programs, queryFn: api.programs });
}
export function useCreateProgram() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: unknown) => api.createProgram(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.programs }),
  });
}
export function useUpdateProgram() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: unknown }) =>
      api.updateProgram(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.programs }),
  });
}
export function useDeleteProgram() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteProgram(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.programs }),
  });
}

// --- streams ----------------------------------------------------------------
export function useStreams() {
  return useQuery({ queryKey: keys.streams, queryFn: api.streams });
}
export function useBuffer(id: string, enabled = true) {
  return useQuery({
    queryKey: keys.buffer(id),
    queryFn: () => api.buffer(id),
    enabled,
    refetchInterval: 2000,
  });
}
export function useSegments(id: string, enabled = true) {
  return useQuery({
    queryKey: keys.segments(id),
    queryFn: () => api.segments(id),
    enabled,
    refetchInterval: 4000,
  });
}
export function useCreateStream() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: unknown) => api.createStream(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.streams }),
  });
}
export function useUpdateStream() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: unknown }) =>
      api.updateStream(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.streams }),
  });
}
export function useDeleteStream() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteStream(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.streams }),
  });
}
export function useStreamAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, action }: { id: string; action: "start" | "stop" }) =>
      action === "start" ? api.startStream(id) : api.stopStream(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.streams }),
  });
}

// --- jobs -------------------------------------------------------------------
export function useJobs(streamId?: string) {
  return useQuery({
    queryKey: keys.jobs(streamId),
    queryFn: () => api.jobs(streamId ? { stream_id: streamId } : undefined),
    refetchInterval: 1500,
  });
}
export function useSubmitJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: unknown) => api.submitJob(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }),
  });
}
export function useCancelJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.cancelJob(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }),
  });
}

// --- schedules --------------------------------------------------------------
export function useSchedules() {
  return useQuery({ queryKey: keys.schedules, queryFn: api.schedules });
}
export function useCreateSchedule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: unknown) => api.createSchedule(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.schedules }),
  });
}
export function useUpdateSchedule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: unknown }) =>
      api.updateSchedule(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.schedules }),
  });
}
export function useDeleteSchedule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteSchedule(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.schedules }),
  });
}

// --- history ----------------------------------------------------------------
export function useHistory(streamId?: string) {
  return useQuery({
    queryKey: keys.history(streamId),
    queryFn: () => api.history(streamId ? { stream_id: streamId } : undefined),
    refetchInterval: 5000,
  });
}
export function useDeleteHistory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteHistory(id),
    onSuccess: () =>
      Promise.all([
        qc.invalidateQueries({ queryKey: ["history"] }),
        qc.invalidateQueries({ queryKey: ["tracks"] }),
        qc.invalidateQueries({ queryKey: ["videos"] }),
      ]),
  });
}

// --- studio -----------------------------------------------------------------
export function useTracks() {
  return useQuery({ queryKey: ["tracks"], queryFn: api.tracks, refetchInterval: 4000 });
}
export function useVideos() {
  return useQuery({ queryKey: ["videos"], queryFn: api.videos, refetchInterval: 4000 });
}
export function useGenerateTracks() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: unknown) => api.generateTracks(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }),
  });
}
export function useMakeVideo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: unknown) => api.makeVideo(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }),
  });
}
