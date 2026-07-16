import { useEffect, useMemo, useState } from "react";
import { api, type HistoryItem } from "../api/client";
import { useTracks } from "../api/hooks";
import { Badge, Card, Empty, SectionTitle, cx, fmtDuration } from "../components/ui";
import { DownloadIcon, PlusIcon } from "../components/icons";
import { albumTitleOf, trackIndexOf } from "../library";

function orderedAlbumTracks(tracks: HistoryItem[], album: string) {
  return tracks
    .filter((track) => albumTitleOf(track) === album)
    .sort(
      (a, b) =>
        trackIndexOf(a) - trackIndexOf(b) ||
        new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
    );
}

export default function Album() {
  const { data: tracks } = useTracks();
  const [selected, setSelected] = useState<string[]>([]);
  const [loadedAlbum, setLoadedAlbum] = useState("");
  const [albumTitle, setAlbumTitle] = useState("");
  const [includeTrackVideos, setIncludeTrackVideos] = useState(false);
  const [exportingAlbum, setExportingAlbum] = useState(false);
  const [error, setError] = useState("");

  const albums = useMemo(
    () =>
      [...new Set((tracks ?? []).map(albumTitleOf).filter(Boolean))].sort((a, b) =>
        a.localeCompare(b, undefined, { numeric: true }),
      ),
    [tracks],
  );
  const selectedTracks = useMemo(() => {
    const byId = new Map((tracks ?? []).map((track) => [track.id, track]));
    return selected.map((id) => byId.get(id)).filter((track): track is HistoryItem => Boolean(track));
  }, [selected, tracks]);
  const visibleTracks = useMemo(
    () => (loadedAlbum ? orderedAlbumTracks(tracks ?? [], loadedAlbum) : tracks ?? []),
    [loadedAlbum, tracks],
  );

  useEffect(() => {
    const available = new Set((tracks ?? []).map((track) => track.id));
    setSelected((current) => current.filter((id) => available.has(id)));
  }, [tracks]);

  function toggle(track: HistoryItem) {
    setSelected((current) =>
      current.includes(track.id)
        ? current.filter((id) => id !== track.id)
        : [...current, track.id],
    );
  }

  function moveTrack(id: string, direction: -1 | 1) {
    setSelected((current) => {
      const index = current.indexOf(id);
      const destination = index + direction;
      if (index < 0 || destination < 0 || destination >= current.length) return current;
      const next = [...current];
      [next[index], next[destination]] = [next[destination], next[index]];
      return next;
    });
  }

  function loadAlbum(title: string) {
    setLoadedAlbum(title);
    if (!title) return;
    setSelected(orderedAlbumTracks(tracks ?? [], title).map((track) => track.id));
    setAlbumTitle(title);
  }

  async function assembleAlbum() {
    setError("");
    if (!albumTitle.trim() || selected.length === 0) return;
    try {
      setExportingAlbum(true);
      const archive = await api.downloadAlbum({
        title: albumTitle.trim(),
        item_ids: selected,
        include_track_videos: includeTrackVideos,
      });
      const url = URL.createObjectURL(archive);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${albumTitle.trim().replace(/[\\/:*?"<>|]/g, "-")}.zip`;
      document.body.append(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setExportingAlbum(false);
    }
  }

  return (
    <div className="space-y-8">
      <SectionTitle
        title="Album"
        subtitle="Choose the track order and export a finished album package."
      />

      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(20rem,0.75fr)]">
        <Card>
          <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
            <label className="min-w-0 sm:w-72">
              <span className="label">Load an album</span>
              <select
                className="input"
                value={loadedAlbum}
                onChange={(event) => loadAlbum(event.target.value)}
              >
                <option value="">All tracks</option>
                {albums.map((album) => (
                  <option key={album} value={album}>
                    {album} ({orderedAlbumTracks(tracks ?? [], album).length} tracks)
                  </option>
                ))}
              </select>
            </label>
            <span className="text-sm text-slate-500">
              {selected.length} track{selected.length === 1 ? "" : "s"} selected
            </span>
          </div>

          {(tracks?.length ?? 0) === 0 ? (
            <Empty>No tracks available to export yet.</Empty>
          ) : (
            <div className="grid gap-2">
              {visibleTracks.map((track) => {
                const index = selected.indexOf(track.id);
                return (
                  <div
                    key={track.id}
                    className={cx(
                      "flex items-center justify-between gap-3 rounded-lg border p-2.5 transition-colors",
                      index >= 0
                        ? "border-accent/60 bg-accent/10"
                        : "border-ink-700 bg-ink-950/40",
                    )}
                  >
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium text-slate-100">{track.title}</div>
                      <div className="mt-0.5 flex flex-wrap gap-1.5">
                        {albumTitleOf(track) && <Badge tone="violet">{albumTitleOf(track)}</Badge>}
                        <span className="text-xs text-slate-500">{fmtDuration(track.duration_seconds)}</span>
                      </div>
                    </div>
                    <button
                      className={cx(
                        "icon-button h-9 w-9",
                        index >= 0 && "!border-accent !bg-accent !text-white",
                      )}
                      onClick={() => toggle(track)}
                      title={index >= 0 ? "Remove from album" : "Add to album"}
                      aria-label={index >= 0 ? `Remove ${track.title} from album` : `Add ${track.title} to album`}
                    >
                      {index >= 0 ? <span className="text-xs font-bold">{index + 1}</span> : <PlusIcon className="h-4 w-4" />}
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </Card>

        <div className="space-y-4 lg:sticky lg:top-4">
          {selectedTracks.length > 0 && (
            <Card>
              <div className="mb-2 flex items-center justify-between">
                <h3 className="font-medium text-slate-100">Track order</h3>
                <button className="btn-ghost !text-xs" onClick={() => setSelected([])}>
                  Clear
                </button>
              </div>
              <div className="max-h-[52vh] space-y-1.5 overflow-y-auto pr-1">
                {selectedTracks.map((track, index) => (
                  <div key={track.id} className="flex items-center gap-2 rounded-lg bg-ink-950/70 px-2.5 py-2">
                    <span className="w-5 text-center text-xs font-semibold text-accent-soft">{index + 1}</span>
                    <span className="min-w-0 flex-1 truncate text-sm text-slate-200">{track.title}</span>
                    <button
                      className="icon-button !h-7 !w-7 !rounded-md !text-xs"
                      disabled={index === 0}
                      onClick={() => moveTrack(track.id, -1)}
                      aria-label={`Move ${track.title} earlier`}
                    >
                      ↑
                    </button>
                    <button
                      className="icon-button !h-7 !w-7 !rounded-md !text-xs"
                      disabled={index === selectedTracks.length - 1}
                      onClick={() => moveTrack(track.id, 1)}
                      aria-label={`Move ${track.title} later`}
                    >
                      ↓
                    </button>
                  </div>
                ))}
              </div>
            </Card>
          )}

          <Card>
            <h3 className="font-medium text-slate-100">Export album</h3>
            <p className="mt-0.5 text-xs text-slate-500">
              Download numbered, tagged FLACs with album cover and a multi-file CUE.
            </p>
            <label className="mt-3 block">
              <span className="label">Album title</span>
              <input
                className="input"
                value={albumTitle}
                maxLength={160}
                placeholder="Album title"
                onChange={(event) => setAlbumTitle(event.target.value)}
              />
            </label>
            <label className="mt-3 flex items-start gap-2 rounded-lg border border-ink-700 bg-ink-950/50 p-3">
              <input
                type="checkbox"
                className="mt-0.5 h-4 w-4 accent-violet-500"
                checked={includeTrackVideos}
                onChange={(event) => setIncludeTrackVideos(event.target.checked)}
              />
              <span>
                <span className="block text-sm text-slate-200">Include a YouTube MP4 for each track</span>
                <span className="mt-0.5 block text-xs text-slate-500">
                  Off by default. Uses the album cover at 1 fps with H.264 video and AAC 320 kbps audio.
                  MP4s are skipped when the album has no cover.
                </span>
              </span>
            </label>
            <button
              className="btn-primary mt-3 w-full"
              disabled={selected.length === 0 || exportingAlbum || !albumTitle.trim()}
              onClick={assembleAlbum}
            >
              <DownloadIcon className="h-4 w-4" />
              {exportingAlbum ? "Assembling…" : "Download album ZIP"}
            </button>
            {error && <div className="mt-2 text-sm text-red-400">{error}</div>}
          </Card>
        </div>
      </div>
    </div>
  );
}
