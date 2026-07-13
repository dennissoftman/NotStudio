import { useEffect, useMemo, useState } from "react";
import { api, type HistoryItem, type TrackVerdict, type VideoResolution } from "../api/client";
import {
  useDeleteHistory,
  useCancelJob,
  useDeleteJob,
  useJobs,
  useMakeVideo,
  useRetryJob,
  useReviewTrack,
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
  cx,
  fmtDuration,
} from "../components/ui";
import {
  ChevronIcon,
  DownloadIcon,
  PlusIcon,
  SparklesIcon,
  ThumbsDownIcon,
  ThumbsUpIcon,
  TrashIcon,
} from "../components/icons";

type TrackSort = "date-desc" | "date-asc" | "name-asc" | "name-desc" | "duration-asc" | "duration-desc";

function verdictOf(track: HistoryItem): TrackVerdict {
  const review = (track.meta as Record<string, unknown>)?.review as Record<string, unknown> | undefined;
  const verdict = review?.verdict;
  return verdict === "liked" || verdict === "disliked" ? verdict : "unreviewed";
}

function TrackMeta({ track }: { track: HistoryItem }) {
  const meta = track.meta as Record<string, unknown>;
  const genre = typeof meta.genre === "string" ? meta.genre : "";
  const prompt = typeof meta.prompt === "string" ? meta.prompt : "";

  return (
    <div className="min-w-0">
      <div className="truncate font-medium text-slate-100">{track.title}</div>
      <div className="mt-1 flex flex-wrap gap-1.5">
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
  const del = useDeleteHistory();

  const likedIds = useMemo(
    () => (tracks ?? []).filter((track) => verdictOf(track) === "liked").map((track) => track.id),
    [tracks],
  );
  const [selected, setSelected] = useState<string[]>([]);
  const [title, setTitle] = useState("");
  const [visualizer, setVisualizer] = useState("cqt");
  const [resolution, setResolution] = useState<VideoResolution>("1080p");
  const [crossfade, setCrossfade] = useState(6);
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
      if (current.length > 0) return current.filter((id) => likedIds.includes(id));
      return likedIds;
    });
  }, [likedIds]);

  const counts = useMemo(() => {
    const initial = { liked: 0, disliked: 0, unreviewed: 0 };
    for (const track of tracks ?? []) initial[verdictOf(track)] += 1;
    return initial;
  }, [tracks]);

  const toggle = (id: string) =>
    setSelected((current) =>
      current.includes(id) ? current.filter((x) => x !== id) : [...current, id],
    );
  const videoJobs = (jobs ?? []).filter((j) => j.type === "make_video").slice(0, 4);

  async function setVerdict(track: HistoryItem, verdict: TrackVerdict) {
    const current = verdictOf(track);
    const next = current === verdict ? "unreviewed" : verdict;
    await review.mutateAsync({ id: track.id, verdict: next });
    if (next === "liked") setSelected((ids) => (ids.includes(track.id) ? ids : [...ids, track.id]));
    if (next === "disliked") setSelected((ids) => ids.filter((id) => id !== track.id));
  }

  async function combine() {
    setError("");
    if (selected.length === 0) {
      setError("Like and select at least one track");
      return;
    }
    try {
      await makeVideo.mutateAsync({
        item_ids: selected,
        title: title || null,
        visualizer,
        resolution,
        crossfade_seconds: crossfade,
      });
      setSelected([]);
      setTitle("");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="space-y-10">
      <div>
        <SectionTitle title="Review tracks" subtitle="Listen to each candidate, keep the strong ones, then make a mix." />

        <div className="mb-3 grid gap-2 sm:grid-cols-3">
          <Card className="!py-3">
            <div className="text-xs uppercase tracking-wide text-slate-500">Liked</div>
            <div className="mt-1 text-2xl font-semibold text-emerald-300">{counts.liked}</div>
          </Card>
          <Card className="!py-3">
            <div className="text-xs uppercase tracking-wide text-slate-500">Unreviewed</div>
            <div className="mt-1 text-2xl font-semibold text-slate-200">{counts.unreviewed}</div>
          </Card>
          <Card className="!py-3">
            <div className="text-xs uppercase tracking-wide text-slate-500">Disliked</div>
            <div className="mt-1 text-2xl font-semibold text-red-300">{counts.disliked}</div>
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
            return (
              <Card key={track.id} className="!py-3">
                <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
                  <TrackMeta track={track} />
                  <div className="flex flex-wrap items-center gap-2 lg:justify-end">
                    <span className="text-xs text-slate-500">{fmtDuration(track.duration_seconds)}</span>
                    <AudioPlayer
                      src={api.audioUrl(track.id)}
                      label={track.title}
                      durationSeconds={track.duration_seconds}
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
                      className={cx("review-button", verdict === "disliked" && "review-button-disliked")}
                      onClick={() => setVerdict(track, "disliked")}
                      disabled={review.isPending}
                      aria-label={`${verdict === "disliked" ? "Remove dislike from" : "Dislike"} ${track.title}`}
                      title="Dislike"
                    >
                      <ThumbsDownIcon className="h-[18px] w-[18px]" />
                    </button>
                    <button
                      onClick={() => toggle(track.id)}
                      title="Select for the mix"
                      disabled={verdict === "disliked"}
                      className={cx(
                        "icon-button h-9 w-9 disabled:opacity-40",
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
            <div className="flex flex-wrap items-end gap-3">
              <label className="grow">
                <span className="label">Mix title</span>
                <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} />
              </label>
              <label>
                <span className="label">Visualizer</span>
                <select
                  className="input w-auto"
                  value={visualizer}
                  onChange={(e) => setVisualizer(e.target.value)}
                >
                  <option value="cqt">cqt</option>
                  <option value="spectrum">spectrum</option>
                  <option value="waves">waves</option>
                  <option value="none">none</option>
                </select>
              </label>
              <label>
                <span className="label">Resolution</span>
                <select
                  className="input w-auto"
                  value={resolution}
                  onChange={(e) => setResolution(e.target.value as VideoResolution)}
                >
                  <option value="2160p">2160p / 4K</option>
                  <option value="1440p">1440p</option>
                  <option value="1080p">1080p</option>
                  <option value="720p">720p</option>
                </select>
              </label>
              <label>
                <span className="label">Crossfade seconds</span>
                <input
                  type="number"
                  className="input w-28"
                  value={crossfade}
                  onChange={(e) => setCrossfade(+e.target.value)}
                />
              </label>
              <button
                className="btn-primary"
                disabled={selected.length === 0 || makeVideo.isPending}
                onClick={combine}
              >
                <SparklesIcon className="h-4 w-4" /> Make mix ({selected.length})
              </button>
              {error && <span className="text-sm text-red-400">{error}</span>}
            </div>
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
              <video className="w-full rounded-md bg-black" controls preload="none" src={api.audioUrl(video.id)} />
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
