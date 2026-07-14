import { useEffect, useMemo, useRef, useState } from "react";
import { api, type HistoryItem } from "../api/client";
import {
  useCancelJob,
  useDeleteHistory,
  useDeleteJob,
  useJobs,
  useMakeVideo,
  useRetryJob,
  useTracks,
  useVideos,
} from "../api/hooks";
import {
  Badge,
  Card,
  Empty,
  Progress,
  SectionTitle,
  StatusBadge,
  VideoPlayer,
  cx,
  fmtDuration,
} from "../components/ui";
import { DownloadIcon, PlusIcon, SparklesIcon, TrashIcon } from "../components/icons";
import { albumTitleOf, trackIndexOf } from "../library";

type MixMode = "album" | "video";

function orderedAlbumTracks(tracks: HistoryItem[], album: string) {
  return tracks
    .filter((track) => albumTitleOf(track) === album)
    .sort(
      (a, b) =>
        trackIndexOf(a) - trackIndexOf(b) ||
        new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
    );
}

export default function Mix() {
  const { data: tracks } = useTracks();
  const { data: videos } = useVideos();
  const { data: jobs } = useJobs();
  const makeVideo = useMakeVideo();
  const cancelJob = useCancelJob();
  const deleteJob = useDeleteJob();
  const retryJob = useRetryJob();
  const del = useDeleteHistory();
  const [mode, setMode] = useState<MixMode>("album");
  const [selected, setSelected] = useState<string[]>([]);
  const [loadedAlbum, setLoadedAlbum] = useState("");
  const [albumTitle, setAlbumTitle] = useState("");
  const [exportingAlbum, setExportingAlbum] = useState(false);
  const [background, setBackground] = useState<File | null>(null);
  const [uploadingBackground, setUploadingBackground] = useState(false);
  const [error, setError] = useState("");
  const backgroundInput = useRef<HTMLInputElement>(null);

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
  const videoJobs = (jobs ?? []).filter((job) => job.type === "make_video").slice(0, 4);

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
      const archive = await api.downloadAlbum({ title: albumTitle.trim(), item_ids: selected });
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

  async function combine() {
    setError("");
    if (selected.length === 0) {
      setError("Select at least one track");
      return;
    }
    if (!background) {
      setError("Choose a video for the mix");
      return;
    }
    try {
      setUploadingBackground(true);
      const uploadedBackground = await api.uploadVideoBackground(background);
      await makeVideo.mutateAsync({ item_ids: selected, background_id: uploadedBackground.id });
      setBackground(null);
      if (backgroundInput.current) backgroundInput.current.value = "";
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setUploadingBackground(false);
    }
  }

  return (
    <div className="space-y-8">
      <SectionTitle
        title="Mix"
        subtitle="Build an ordered release or combine tracks with a video backdrop."
      />

      <div className="flex gap-1 rounded-xl border border-ink-700 bg-ink-900/80 p-1">
        {([
          ["album", "Album export"],
          ["video", "Video mix"],
        ] as const).map(([value, label]) => (
          <button
            key={value}
            className={cx(
              "flex-1 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
              mode === value
                ? "bg-accent text-white"
                : "text-slate-400 hover:bg-ink-800 hover:text-slate-100",
            )}
            onClick={() => setMode(value)}
          >
            {label}
          </button>
        ))}
      </div>

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
              {selected.length} track{selected.length === 1 ? "" : "s"} in queue
            </span>
          </div>

        {(tracks?.length ?? 0) === 0 ? (
          <Empty>No tracks available to mix yet.</Empty>
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
                    title={index >= 0 ? "Remove from mix" : "Add to mix"}
                    aria-label={index >= 0 ? `Remove ${track.title} from mix` : `Add ${track.title} to mix`}
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
            <h3 className="font-medium text-slate-100">Mix order</h3>
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
        {mode === "album" ? (
          <div>
            <h3 className="font-medium text-slate-100">Export album</h3>
            <p className="mt-0.5 text-xs text-slate-500">
              Download numbered FLACs with album tags, embedded covers, and a CUE file.
            </p>
            <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-end">
              <label className="min-w-0 flex-1">
                <span className="label">Album title</span>
                <input
                  className="input"
                  value={albumTitle}
                  maxLength={160}
                  placeholder="Album title"
                  onChange={(event) => setAlbumTitle(event.target.value)}
                />
              </label>
              <button
                className="btn-primary shrink-0"
                disabled={selected.length === 0 || exportingAlbum || !albumTitle.trim()}
                onClick={assembleAlbum}
              >
                <DownloadIcon className="h-4 w-4" />
                {exportingAlbum ? "Assembling…" : "Download album ZIP"}
              </button>
            </div>
          </div>
        ) : (
          <div>
            <h3 className="font-medium text-slate-100">Render video mix</h3>
            <p className="mt-0.5 text-xs text-slate-500">
              Your backdrop is looped over the selected queue and encoded as a YouTube-ready MP4.
            </p>
            <label className="mt-3 block">
              <span className="label">Video input</span>
              <input
                ref={backgroundInput}
                type="file"
                className="input file:mr-3 file:rounded-md file:border-0 file:bg-ink-700 file:px-3 file:py-1 file:text-sm file:text-slate-100"
                onChange={(event) => setBackground(event.target.files?.[0] ?? null)}
              />
            </label>
            {background && (
              <div className="mt-2 flex items-center gap-2 text-xs text-slate-300">
                <Badge tone="violet">Looping backdrop</Badge>
                <span className="truncate">{background.name}</span>
                <button
                  className="text-slate-500 hover:text-slate-200"
                  type="button"
                  onClick={() => {
                    setBackground(null);
                    if (backgroundInput.current) backgroundInput.current.value = "";
                  }}
                >
                  Remove
                </button>
              </div>
            )}
            <div className="mt-3 flex justify-end">
              <button
                className="btn-primary"
                disabled={!background || selected.length === 0 || makeVideo.isPending || uploadingBackground}
                onClick={combine}
              >
                <SparklesIcon className="h-4 w-4" />
                {uploadingBackground ? "Uploading backdrop…" : `Make mix (${selected.length})`}
              </button>
            </div>
          </div>
        )}
        {error && <div className="mt-2 text-sm text-red-400">{error}</div>}
        </Card>
      </div>
      </div>

      {videoJobs.length > 0 && (
        <div className="grid gap-2">
          {videoJobs.map((job) => (
            <Card key={job.id} className="!py-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="min-w-0 text-sm text-slate-300">{job.message || "rendering"}</span>
                <div className="flex shrink-0 items-center gap-2">
                  <StatusBadge status={job.status} />
                  {job.status === "failed" && (
                    <button className="btn-primary !text-xs" disabled={retryJob.isPending} onClick={() => retryJob.mutate(job.id)}>
                      Retry
                    </button>
                  )}
                  {(job.status === "queued" || job.status === "in_progress") && (
                    <button className="btn-danger !text-xs" disabled={cancelJob.isPending} onClick={() => cancelJob.mutate(job.id)}>
                      Cancel
                    </button>
                  )}
                  <button className="btn-ghost !text-xs" disabled={deleteJob.isPending} onClick={() => deleteJob.mutate(job.id)}>
                    Remove
                  </button>
                </div>
              </div>
              {job.status === "in_progress" && <div className="mt-2"><Progress value={job.progress} /></div>}
              {job.error && <div className="mt-1 text-xs text-red-400">{job.error}</div>}
            </Card>
          ))}
        </div>
      )}

      <div>
        <SectionTitle title="Rendered mixes" subtitle="Video mixes ready for upload." />
        {videos?.length === 0 && <Empty>No video mixes yet.</Empty>}
        <div className="grid gap-3 sm:grid-cols-2">
          {videos?.map((video) => (
            <Card key={video.id}>
              <div className="mb-2 flex items-center justify-between gap-3">
                <div className="truncate font-medium text-slate-100">{video.title}</div>
                <span className="shrink-0 text-xs text-slate-500">{fmtDuration(video.duration_seconds)}</span>
              </div>
              <VideoPlayer src={api.audioUrl(video.id)} label={video.title} />
              <div className="mt-2 flex gap-2">
                <a className="btn-ghost !text-xs" href={api.audioUrl(video.id)} download>
                  <DownloadIcon className="h-4 w-4" /> Download MP4
                </a>
                <button className="icon-button icon-button-danger" aria-label={`Delete ${video.title}`} title="Delete mix" onClick={() => del.mutate(video.id)}>
                  <TrashIcon className="h-4 w-4" />
                </button>
              </div>
            </Card>
          ))}
        </div>
      </div>
    </div>
  );
}
