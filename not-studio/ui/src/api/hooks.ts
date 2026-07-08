import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type TrackVerdict } from "./client";

const keys = {
  health: ["health"],
  promptProviders: ["promptProviders"],
  jobs: ["jobs"],
  history: ["history"],
  tracks: ["tracks"],
  videos: ["videos"],
};

export function useHealth() {
  return useQuery({ queryKey: keys.health, queryFn: api.health });
}

export function usePromptProviders() {
  return useQuery({ queryKey: keys.promptProviders, queryFn: api.promptProviders });
}

export function useJobs() {
  return useQuery({ queryKey: keys.jobs, queryFn: () => api.jobs(), refetchInterval: 1500 });
}

export function useCancelJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.cancelJob(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.jobs }),
  });
}

export function useHistory() {
  return useQuery({ queryKey: keys.history, queryFn: api.history, refetchInterval: 5000 });
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
  return useQuery({ queryKey: keys.tracks, queryFn: () => api.tracks(), refetchInterval: 4000 });
}

export function useVideos() {
  return useQuery({ queryKey: keys.videos, queryFn: api.videos, refetchInterval: 4000 });
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

export function useGeneratePromptIdeas() {
  return useMutation({ mutationFn: (data: unknown) => api.generatePromptIdeas(data) });
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

export function useMakeVideo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: unknown) => api.makeVideo(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.jobs }),
  });
}
