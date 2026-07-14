import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, jobsWebSocketUrl, type Job, type TrackVerdict } from "./client";

const keys = {
  health: ["health"],
  promptKit: ["promptKit"],
  jobs: ["jobs"],
  history: ["history"],
  tracks: ["tracks"],
  videos: ["videos"],
};

export function useHealth() {
  return useQuery({ queryKey: keys.health, queryFn: api.health });
}

export function usePromptKit() {
  return useQuery({ queryKey: keys.promptKit, queryFn: api.promptKit });
}

export function useJobs() {
  const qc = useQueryClient();
  const query = useQuery({ queryKey: keys.jobs, queryFn: () => api.jobs(), staleTime: Infinity });

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
        const completedIds = new Set(
          message.jobs.filter((job) => job.status === "completed").map((job) => job.id),
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
            qc.invalidateQueries({ queryKey: keys.videos }),
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
        qc.invalidateQueries({ queryKey: keys.videos }),
      ]),
  });
}

export function useTracks() {
  return useQuery({ queryKey: keys.tracks, queryFn: () => api.tracks() });
}

export function useVideos() {
  return useQuery({ queryKey: keys.videos, queryFn: api.videos });
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
    mutationFn: ({ id, albumTitle }: { id: string; albumTitle: string | null }) =>
      api.setTrackAlbum(id, albumTitle),
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
    mutationFn: ({ id, file }: { id: string; file: File }) => api.setTrackArtwork(id, file),
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

export function useMakeVideo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: unknown) => api.makeVideo(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.jobs }),
  });
}
