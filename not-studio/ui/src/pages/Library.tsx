import { useEffect, useMemo, useRef, useState } from "react";
import { api, type HistoryItem, type TrackVerdict } from "../api/client";
import {
  useDeleteHistory,
  useCancelJob,
  useDeleteJob,
  useJobs,
  useMakeVideo,
  useRetryJob,
  useRegenerateTrack,
  useReviewTrack,
  useSetTrackArtwork,
  useTracks,
  useVideos,
} from "../api/hooks";
import {
  Badge,
  AudioPlayer,
  Card,
  Empty,
  Progress,
  SectionTitle,
  StatusBadge,
  VideoPlayer,
  cx,
  fmtDuration,
} from "../components/ui";
import {
  ChevronIcon,
  DownloadIcon,
  ImageIcon,
  PlusIcon,
  SparklesIcon,
  RetryIcon,
  ThumbsUpIcon,
  TrashIcon,
} from "../components/icons";

type TrackSort = "date-desc" | "date-asc" | "name-asc" | "name-desc" | "duration-asc" | "duration-desc";

function verdictOf(track: HistoryItem): TrackVerdict {
  const review = (track.meta as Record<string, unknown>)?.review as Record<string, unknown> | undefined;
  const verdict = review?.verdict;
  return verdict === "liked" ? verdict : "unreviewed";
}

function TrackArtwork({ track }: { track: HistoryItem }) {
  const input = useRef<HTMLInputElement>(null);
  const artwork = useSetTrackArtwork();
  const details = (track.meta as Record<string, unknown>)?.artwork as Record<string, unknown> | undefined;
  const version = typeof details?.updated_at === "string" ? details.updated_at : undefined;

  return <>
    <button
      type="button"
      className="group relative flex h-16 w-16 shrink-0 items-center justify-center overflow-hidden rounded-xl border border-ink-600 bg-ink-950 text-slate-500 hover:border-accent hover:text-accent-soft"
      onClick={() => input.current?.click()}
      disabled={artwork.isPending}
      title={version ? "Replace track artwork" : "Add track artwork"}
    >
      {version
        ? <img className="h-full w-full object-cover" src={api.artworkUrl(track.id, version)} alt="" />
        : <ImageIcon className="h-6 w-6" />}
      <span className="absolute inset-x-0 bottom-0 bg-black/70 py-0.5 text-[9px] font-medium uppercase tracking-wide text-white opacity-0 transition-opacity group-hover:opacity-100">
        {artwork.isPending ? "Saving" : version ? "Replace" : "Add icon"}
      </span>
    </button>
    <input
      ref={input}
      className="hidden"
      type="file"
      accept="image/png,image/jpeg,image/webp"
      onChange={(event) => {
        const file = event.target.files?.[0];
        if (file) artwork.mutate({ id: track.id, file });
        event.target.value = "";
      }}
    />
    {artwork.error && <span className="sr-only">{artwork.error.message}</span>}
  </>;
}

function TrackMeta({ track }: { track: HistoryItem }) {
  const meta = track.meta as Record<string, unknown>;
  const genre = typeof meta.genre === "string" ? meta.genre : "";
  const prompt = typeof meta.prompt === "string" ? meta.prompt : "";
  const album = meta.album as Record<string, unknown> | undefined;
  const albumTitle = typeof album?.title === "string" ? album.title : "";

  return (
    <div className="min-w-0">
      <div className="truncate font-medium text-slate-100">{track.title}</div>
      <div className="mt-1 flex flex-wrap gap-1.5">
        {albumTitle && <Badge tone="violet">{albumTitle}</Badge>}
        {genre && <Badge tone="blue">{genre}</Badge>}
      </div>
      {prompt && <div className="mt-1 truncate text-xs text-slate-500">{prompt}</div>}
    </div>
  );
}

export default function Library() {
  const { data: tracks } = useTracks();
  const { data: videos } = useVideos();
  const { data: jobs } = useJobs();
  const makeVideo = useMakeVideo();
  const cancelJob = useCancelJob();
  const deleteJob = useDeleteJob();
  const retryJob = useRetryJob();
  const review = useReviewTrack();
  const regenerate = useRegenerateTrack();
  const del = useDeleteHistory();

  const availableTrackIds = useMemo(
    () => new Set((tracks ?? []).map((track) => track.id)),
    [tracks],
  );
  const [selected, setSelected] = useState<string[]>([]);
  const [albumTitle, setAlbumTitle] = useState("");
  const [exportingAlbum, setExportingAlbum] = useState(false);
  const [albumError, setAlbumError] = useState("");
  const [background, setBackground] = useState<File | null>(null);
  const [uploadingBackground, setUploadingBackground] = useState(false);
  const backgroundInput = useRef<HTMLInputElement>(null);
  const [error, setError] = useState("");
  const [sort, setSort] = useState<TrackSort>("date-desc");

  const sortedTracks = useMemo(() => {
    const items = [...(tracks ?? [])];
    return items.sort((a, b) => {
      if (sort === "name-asc" || sort === "name-desc") {
        const order = a.title.localeCompare(b.title, undefined, { numeric: true });
        return sort === "name-asc" ? order : -order;
      }
      if (sort === "duration-asc" || sort === "duration-desc") {
        const order = a.duration_seconds - b.duration_seconds;
        return sort === "duration-asc" ? order : -order;
      }
      const order = new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
      return sort === "date-asc" ? order : -order;
    });
  }, [sort, tracks]);

  useEffect(() => {
    setSelected((current) => {
      const available = current.filter((id) => availableTrackIds.has(id));
      return available.length === current.length ? current : available;
    });
  }, [availableTrackIds]);

  const counts = useMemo(() => {
    const initial = { liked: 0, unreviewed: 0 };
    for (const track of tracks ?? []) initial[verdictOf(track)] += 1;
    return initial;
  }, [tracks]);

  const toggle = (track: HistoryItem) => {
    const selecting = !selected.includes(track.id);
    if (selecting && selected.length === 0 && !albumTitle.trim()) {
      const album = (track.meta as Record<string, unknown>)?.album as
        | Record<string, unknown>
        | undefined;
      if (typeof album?.title === "string" && album.title.trim()) {
        setAlbumTitle(album.title.trim());
      }
    }
    setSelected((current) =>
      current.includes(track.id)
        ? current.filter((id) => id !== track.id)
        : [...current, track.id],
    );
  };
  const videoJobs = (jobs ?? []).filter((j) => j.type === "make_video").slice(0, 4);

  async function setVerdict(track: HistoryItem, verdict: TrackVerdict) {
    const current = verdictOf(track);
    const next = current === verdict ? "unreviewed" : verdict;
    await review.mutateAsync({ id: track.id, verdict: next });
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
      await makeVideo.mutateAsync({
        item_ids: selected,
        background_id: uploadedBackground.id,
      });
      setSelected([]);
      setBackground(null);
      if (backgroundInput.current) backgroundInput.current.value = "";
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setUploadingBackground(false);
    }
  }

  async function assembleAlbum() {
    setAlbumError("");
    const title = albumTitle.trim();
    if (!title) {
      setAlbumError("Enter an album title");
      return;
    }
    if (selected.length === 0) {
      setAlbumError("Select at least one track");
      return;
    }
    try {
      setExportingAlbum(true);
      const archive = await api.downloadAlbum({ title, item_ids: selected });
      const url = URL.createObjectURL(archive);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${title.replace(/[\\/:*?"<>|]/g, "-")}.zip`;
      document.body.append(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (cause) {
      setAlbumError((cause as Error).message);
    } finally {
      setExportingAlbum(false);
    }
  }

  return (
    <div className="space-y-10">
      <div>
        <SectionTitle title="Review tracks" subtitle="Keep the right tracks, add covers, and order them for an album or video mix." />

        <div className="mb-3 grid gap-2 sm:grid-cols-2">
          <Card className="!py-3">
            <div className="text-xs uppercase tracking-wide text-slate-500">Liked</div>
            <div className="mt-1 text-2xl font-semibold text-emerald-300">{counts.liked}</div>
          </Card>
          <Card className="!py-3">
            <div className="text-xs uppercase tracking-wide text-slate-500">Unreviewed</div>
            <div className="mt-1 text-2xl font-semibold text-slate-200">{counts.unreviewed}</div>
          </Card>
        </div>

        {tracks?.length === 0 && <Empty>No tracks yet. Generate an album batch first.</Empty>}
        {(tracks?.length ?? 0) > 0 && <div className="mb-2 flex items-center gap-1 rounded-lg border border-ink-700 bg-ink-900/80 p-1.5 text-xs text-slate-500">
          <span className="px-2 uppercase tracking-wide">Sort list</span>
          {([['date', 'Generated'], ['name', 'Name'], ['duration', 'Duration']] as const).map(([key, label]) => {
            const active = sort.startsWith(key);
            const direction = active && sort.endsWith('asc') ? 'asc' : 'desc';
            return <button key={key} className={cx("inline-flex items-center gap-1 rounded-md px-2.5 py-1.5 transition-colors hover:bg-ink-700 hover:text-slate-200", active && "bg-ink-700 text-slate-100")} onClick={() => setSort(`${key}-${active && direction === 'desc' ? 'asc' : 'desc'}` as TrackSort)}>{label} {active && <ChevronIcon className="h-3.5 w-3.5" direction={direction === "asc" ? "up" : "down"} />}</button>;
          })}
        </div>}
        <div className="grid gap-2">
          {sortedTracks.map((track) => {
            const idx = selected.indexOf(track.id);
            const verdict = verdictOf(track);
            const regenerationJob = (jobs ?? []).find(
              (job) =>
                job.params.replacement_item_id === track.id &&
                (job.status === "queued" || job.status === "in_progress"),
            );
            return (
              <Card key={track.id} className="!py-3">
                <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
                  <div className="flex min-w-0 items-center gap-3">
                    <TrackArtwork track={track} />
                    <TrackMeta track={track} />
                  </div>
                  <div className="flex flex-wrap items-center gap-2 lg:justify-end">
                    <span className="text-xs text-slate-500">{fmtDuration(track.duration_seconds)}</span>
                    <AudioPlayer
                      src={api.audioUrl(track.id)}
                      label={track.title}
                    />
                    <button
                      className={cx("review-button", verdict === "liked" && "review-button-liked")}
                      onClick={() => setVerdict(track, "liked")}
                      disabled={review.isPending}
                      aria-label={`${verdict === "liked" ? "Remove like from" : "Like"} ${track.title}`}
                      title="Like"
                    >
                      <ThumbsUpIcon className="h-[18px] w-[18px]" />
                    </button>
                    <button
                      className="review-button"
                      onClick={() => regenerate.mutate(track.id)}
                      disabled={regenerate.isPending || Boolean(regenerationJob)}
                      aria-label={`Regenerate ${track.title}`}
                      title="Regenerate and replace track"
                    >
                      <RetryIcon
                        className={cx(
                          "h-[18px] w-[18px]",
                          Boolean(regenerationJob) && "animate-spin",
                        )}
                      />
                    </button>
                    <a
                      className="icon-button"
                      href={api.audioUrl(track.id)}
                      download
                      aria-label={`Download ${track.title}`}
                      title="Download FLAC"
                    >
                      <DownloadIcon className="h-4 w-4" />
                    </a>
                    <button
                      onClick={() => toggle(track)}
                      title="Select for album or mix"
                      className={cx(
                        "icon-button h-9 w-9",
                        idx >= 0
                          ? "!border-accent !bg-accent !text-white"
                          : "hover:!border-accent hover:!text-accent-soft",
                      )}
                    >
                      {idx >= 0 ? <span className="text-xs font-bold">{idx + 1}</span> : <PlusIcon className="h-4 w-4" />}
                    </button>
                    <button
                      className="icon-button icon-button-danger"
                      onClick={() => del.mutate(track.id)}
                      aria-label={`Delete ${track.title}`}
                      title="Delete track"
                    >
                      <TrashIcon className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              </Card>
            );
          })}
        </div>

        {(tracks?.length ?? 0) > 0 && (
          <Card className="mt-3">
            <div className="mb-4 rounded-lg border border-accent/30 bg-accent/5 p-3">
              <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h3 className="font-medium text-slate-100">Assemble album</h3>
                  <p className="mt-0.5 text-xs text-slate-500">
                    Download numbered FLACs with album metadata, embedded covers, and a CUE file.
                  </p>
                </div>
                <Badge tone="violet">
                  {selected.length} track{selected.length === 1 ? "" : "s"} in order
                </Badge>
              </div>
              <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
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
              {albumError && <div className="mt-2 text-sm text-red-400">{albumError}</div>}
            </div>

            <div className="mb-4 rounded-lg border border-ink-700 bg-ink-950/60 p-3">
              <label>
                <span className="label">Video input</span>
                <input
                  ref={backgroundInput}
                  type="file"
                  className="input file:mr-3 file:rounded-md file:border-0 file:bg-ink-700 file:px-3 file:py-1 file:text-sm file:text-slate-100"
                  onChange={(event) => setBackground(event.target.files?.[0] ?? null)}
                />
              </label>
              <p className="mt-2 text-xs text-slate-500">
                Any format your FFmpeg installation can read (MP4, MKV, AVI, MOV, WebM, and more).
                The source video is preserved visually, muted, looped to the complete track sequence, and automatically encoded as a YouTube-ready H.264/AAC MP4.
              </p>
              {background && <div className="mt-2 flex items-center gap-2 text-xs text-slate-300">
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
              </div>}
            </div>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-sm text-slate-400">
                {selected.length} selected track{selected.length === 1 ? "" : "s"}, played in selection order.
              </p>
              <button
                className="btn-primary"
                disabled={!background || selected.length === 0 || makeVideo.isPending || uploadingBackground}
                onClick={combine}
              >
                <SparklesIcon className="h-4 w-4" /> {uploadingBackground ? "Uploading backdrop…" : `Make mix (${selected.length})`}
              </button>
            </div>
            {error && <div className="mt-2 text-sm text-red-400">{error}</div>}
          </Card>
        )}

        {videoJobs.length > 0 && (
          <div className="mt-3 grid gap-2">
            {videoJobs.map((j) => (
              <Card key={j.id} className="!py-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="min-w-0 text-sm text-slate-300">{j.message || "rendering"}</span>
                  <div className="flex shrink-0 items-center gap-2">
                    <StatusBadge status={j.status} />
                    {j.status === "failed" && (
                      <button
                        className="btn-primary !text-xs"
                        disabled={retryJob.isPending}
                        onClick={() => retryJob.mutate(j.id)}
                      >
                        Retry
                      </button>
                    )}
                    {(j.status === "queued" || j.status === "in_progress") && (
                      <button
                        className="btn-danger !text-xs"
                        disabled={cancelJob.isPending}
                        onClick={() => cancelJob.mutate(j.id)}
                      >
                        Cancel
                      </button>
                    )}
                    <button
                      className="btn-ghost !text-xs"
                      disabled={deleteJob.isPending}
                      onClick={() => deleteJob.mutate(j.id)}
                    >
                      Remove
                    </button>
                  </div>
                </div>
                {j.status === "in_progress" && (
                  <div className="mt-2">
                    <Progress value={j.progress} />
                  </div>
                )}
                {j.error && <div className="mt-1 text-xs text-red-400">{j.error}</div>}
              </Card>
            ))}
          </div>
        )}
      </div>

      <div>
        <SectionTitle title="Mixes" subtitle="Rendered videos ready for YouTube upload." />
        {videos?.length === 0 && <Empty>No mixes yet.</Empty>}
        <div className="grid gap-3 sm:grid-cols-2">
          {videos?.map((video) => (
            <Card key={video.id}>
              <div className="mb-2 flex items-center justify-between gap-3">
                <div className="truncate font-medium text-slate-100">{video.title}</div>
                <span className="shrink-0 text-xs text-slate-500">
                  {fmtDuration(video.duration_seconds)}
                </span>
              </div>
              <VideoPlayer
                src={api.audioUrl(video.id)}
                label={video.title}
              />
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
