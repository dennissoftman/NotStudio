import type { HistoryItem, TrackVerdict } from "./api/client";

export function verdictOf(track: HistoryItem): TrackVerdict {
  const review = (track.meta as Record<string, unknown>)?.review as
    | Record<string, unknown>
    | undefined;
  return review?.verdict === "liked" ? "liked" : "unreviewed";
}

export function albumTitleOf(track: HistoryItem): string {
  const album = (track.meta as Record<string, unknown>)?.album as
    | Record<string, unknown>
    | undefined;
  return typeof album?.title === "string" ? album.title.trim() : "";
}

export function trackIndexOf(track: HistoryItem): number {
  const value = (track.meta as Record<string, unknown>)?.track_index;
  return typeof value === "number" ? value : Number.MAX_SAFE_INTEGER;
}
