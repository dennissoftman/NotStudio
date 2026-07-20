import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, jobsWebSocketUrl, type Job, type TrackVerdict } from "./client";

const keys = {
  health: ["health"],
  promptKit: ["promptKit"],
  jobs: ["jobs"],
  history: ["history"],
  tracks: ["tracks"],
  generationRuns: ["generationRuns"],
  trackCovers: (id: string) => ["trackCovers", id],
  albumCovers: (id: string) => ["albumCovers", id],
  covers: (ownerType: string) => ["covers", ownerType],
};

export function useHealth() {
  return useQuery({ queryKey: keys.health, queryFn: api.health });
}

export function usePromptKit() {
  return useQuery({ queryKey: keys.promptKit, queryFn: api.promptKit });
}

export function useJobs() {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: keys.jobs,
    queryFn: () => api.jobs(),
    staleTime: Infinity,
  });

  useEffect(() => {
    let socket: WebSocket | undefined;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;

    const connect = () => {
      socket = new WebSocket(jobsWebSocketUrl());
      socket.onmessage = (event) => {
        const message = JSON.parse(event.data) as { type: string; jobs: Job[] };
        if (message.type !== "jobs") return;
        const previous = qc.getQueryData<Job[]>(keys.jobs) ?? [];
        qc.setQueryData(keys.jobs, message.jobs);
        void qc.invalidateQueries({ queryKey: keys.generationRuns });
        const completedIds = new Set(
          message.jobs
            .filter((job) => job.status === "completed")
            .map((job) => job.id),
        );
        if (
          message.jobs.some(
            (job) =>
              completedIds.has(job.id) &&
              previous.find((old) => old.id === job.id)?.status !== "completed",
          )
        ) {
          void Promise.all([
            qc.invalidateQueries({ queryKey: keys.history }),
            qc.invalidateQueries({ queryKey: keys.tracks }),
            qc.invalidateQueries({ queryKey: ["trackCovers"] }),
            qc.invalidateQueries({ queryKey: ["albumCovers"] }),
            qc.invalidateQueries({ queryKey: ["covers"] }),
          ]);
        }
      };
      socket.onclose = () => {
        if (!stopped) retry = setTimeout(connect, 1500);
      };
    };
    connect();
    return () => {
      stopped = true;
      if (retry) clearTimeout(retry);
      socket?.close();
    };
  }, [qc]);

  return query;
}

export function useCancelJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.cancelJob(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.jobs }),
  });
}

export function useDeleteJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteJob(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.jobs }),
  });
}

export function useRetryJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.retryJob(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.jobs }),
  });
}

export function useHistory() {
  return useQuery({ queryKey: keys.history, queryFn: api.history });
}

export function useDeleteHistory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteHistory(id),
    onSuccess: () =>
      Promise.all([
        qc.invalidateQueries({ queryKey: keys.history }),
        qc.invalidateQueries({ queryKey: keys.tracks }),
      ]),
  });
}

export function useTracks() {
  return useQuery({ queryKey: keys.tracks, queryFn: () => api.tracks() });
}

export function useGenerateTracks() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: unknown) => api.generateTracks(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.jobs }),
  });
}

export function useGenerateAlbum() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: unknown) => api.generateAlbum(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.jobs }),
  });
}

export function useReviewTrack() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, verdict }: { id: string; verdict: TrackVerdict }) =>
      api.reviewTrack(id, { verdict }),
    onSuccess: () =>
      Promise.all([
        qc.invalidateQueries({ queryKey: keys.tracks }),
        qc.invalidateQueries({ queryKey: keys.history }),
      ]),
  });
}

export function useSetTrackAlbum() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      albumTitle,
    }: {
      id: string;
      albumTitle: string | null;
    }) => api.setTrackAlbum(id, albumTitle),
    onSuccess: () =>
      Promise.all([
        qc.invalidateQueries({ queryKey: keys.tracks }),
        qc.invalidateQueries({ queryKey: keys.history }),
      ]),
  });
}

export function useRegenerateTrack() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.regenerateTrack(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.jobs }),
  });
}

export function useSetTrackArtwork() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, file }: { id: string; file: File }) =>
      api.setTrackArtwork(id, file),
    onSuccess: () =>
      Promise.all([
        qc.invalidateQueries({ queryKey: keys.tracks }),
        qc.invalidateQueries({ queryKey: keys.history }),
      ]),
  });
}

export function useSetAlbumArtwork() {
  return useMutation({
    mutationFn: ({ title, file }: { title: string; file: File }) =>
      api.setAlbumArtwork(title, file),
  });
}

export function useGenerationRuns() {
  return useQuery({
    queryKey: keys.generationRuns,
    queryFn: api.generationRuns,
  });
}

export function useCreateGenerationRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: unknown) => api.createGenerationRun(data),
    onSuccess: () =>
      Promise.all([
        qc.invalidateQueries({ queryKey: keys.generationRuns }),
        qc.invalidateQueries({ queryKey: keys.jobs }),
      ]),
  });
}

export function useUpdateGenerationPlan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      plan,
    }: {
      id: string;
      plan: Parameters<typeof api.updateGenerationPlan>[1];
    }) => api.updateGenerationPlan(id, plan),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.generationRuns }),
  });
}

export function useReplanGenerationRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.replanGenerationRun,
    onSuccess: () =>
      Promise.all([
        qc.invalidateQueries({ queryKey: keys.generationRuns }),
        qc.invalidateQueries({ queryKey: keys.jobs }),
      ]),
  });
}

export function useGenerateGenerationRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.generateGenerationRun(id),
    onSuccess: () =>
      Promise.all([
        qc.invalidateQueries({ queryKey: keys.generationRuns }),
        qc.invalidateQueries({ queryKey: keys.jobs }),
      ]),
  });
}

export function useUploadStyleReference() {
  return useMutation({ mutationFn: api.uploadStyleReference });
}

export function useCovers(ownerType: "album" | "track") {
  return useQuery({
    queryKey: keys.covers(ownerType),
    queryFn: () => api.covers(ownerType),
  });
}

export function useAlbumCovers(id: string | null) {
  return useQuery({
    queryKey: keys.albumCovers(id ?? ""),
    queryFn: () => api.albumCovers(id!),
    enabled: Boolean(id),
  });
}

export function useGenerateTrackCover() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: unknown }) =>
      api.generateTrackCover(id, data),
    onSuccess: (_data, vars) =>
      Promise.all([
        qc.invalidateQueries({ queryKey: keys.trackCovers(vars.id) }),
        qc.invalidateQueries({ queryKey: ["covers"] }),
        qc.invalidateQueries({ queryKey: keys.jobs }),
      ]),
  });
}

export function useGenerateAlbumCover() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: unknown }) =>
      api.generateAlbumCover(id, data),
    onSuccess: (_data, vars) =>
      Promise.all([
        qc.invalidateQueries({ queryKey: keys.albumCovers(vars.id) }),
        qc.invalidateQueries({ queryKey: ["covers"] }),
        qc.invalidateQueries({ queryKey: keys.jobs }),
      ]),
  });
}

export function useSelectCover() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.selectCover,
    onSuccess: () =>
      Promise.all([
        qc.invalidateQueries({ queryKey: ["trackCovers"] }),
        qc.invalidateQueries({ queryKey: ["albumCovers"] }),
        qc.invalidateQueries({ queryKey: ["covers"] }),
        qc.invalidateQueries({ queryKey: keys.tracks }),
      ]),
  });
}
