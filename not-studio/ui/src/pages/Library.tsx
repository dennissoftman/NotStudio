import { useEffect, useMemo, useState } from "react";
import { api, type HistoryItem, type TrackVerdict } from "../api/client";
import {
  useDeleteHistory,
  useJobs,
  useMakeVideo,
  useReviewTrack,
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
  cx,
  fmtDuration,
} from "../components/ui";

function verdictOf(track: HistoryItem): TrackVerdict {
  const review = (track.meta as Record<string, unknown>)?.review as Record<string, unknown> | undefined;
  const verdict = review?.verdict;
  return verdict === "liked" || verdict === "disliked" ? verdict : "unreviewed";
}

function TrackMeta({ track }: { track: HistoryItem }) {
  const meta = track.meta as Record<string, unknown>;
  const mood = typeof meta.mood === "string" ? meta.mood : "";
  const styles = Array.isArray(meta.styles)
    ? meta.styles.filter((s): s is string => typeof s === "string")
    : [];
  const prompt = typeof meta.prompt === "string" ? meta.prompt : "";

  return (
    <div className="min-w-0">
      <div className="truncate font-medium text-slate-100">{track.title}</div>
      <div className="mt-1 flex flex-wrap gap-1.5">
        {mood && <Badge tone="blue">{mood}</Badge>}
        {styles.map((style) => (
          <Badge key={style} tone="gray">
            {style}
          </Badge>
        ))}
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
  const review = useReviewTrack();
  const del = useDeleteHistory();

  const likedIds = useMemo(
    () => (tracks ?? []).filter((track) => verdictOf(track) === "liked").map((track) => track.id),
    [tracks],
  );
  const [selected, setSelected] = useState<string[]>([]);
  const [title, setTitle] = useState("");
  const [visualizer, setVisualizer] = useState("cqt");
  const [crossfade, setCrossfade] = useState(6);
  const [error, setError] = useState("");

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
        <SectionTitle
          title="Review tracks"
          subtitle="Listen to each candidate, keep the strong ones, then make a mix."
        />

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
        <div className="grid gap-2">
          {tracks?.map((track) => {
            const idx = selected.indexOf(track.id);
            const verdict = verdictOf(track);
            return (
              <Card key={track.id} className="!py-3">
                <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
                  <TrackMeta track={track} />
                  <div className="flex flex-wrap items-center gap-2 lg:justify-end">
                    <span className="text-xs text-slate-500">{fmtDuration(track.duration_seconds)}</span>
                    <audio className="h-8 w-64 max-w-full" controls preload="none" src={api.audioUrl(track.id)} />
                    <button
                      className={cx("btn-ghost !text-xs", verdict === "liked" && "!border-emerald-500 !text-emerald-300")}
                      onClick={() => setVerdict(track, "liked")}
                      disabled={review.isPending}
                    >
                      Like
                    </button>
                    <button
                      className={cx("btn-ghost !text-xs", verdict === "disliked" && "!border-red-500 !text-red-300")}
                      onClick={() => setVerdict(track, "disliked")}
                      disabled={review.isPending}
                    >
                      Dislike
                    </button>
                    <button
                      onClick={() => toggle(track.id)}
                      title="Select for the mix"
                      disabled={verdict === "disliked"}
                      className={cx(
                        "flex h-8 min-w-8 shrink-0 items-center justify-center rounded-md border px-2 text-xs font-semibold disabled:opacity-40",
                        idx >= 0
                          ? "border-accent bg-accent text-white"
                          : "border-ink-600 text-slate-500 hover:border-accent",
                      )}
                    >
                      {idx >= 0 ? idx + 1 : "+"}
                    </button>
                    <button
                      className="btn-danger !text-xs"
                      onClick={() => del.mutate(track.id)}
                      title="Delete track"
                    >
                      Delete
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
                Make mix ({selected.length})
              </button>
              {error && <span className="text-sm text-red-400">{error}</span>}
            </div>
          </Card>
        )}

        {videoJobs.length > 0 && (
          <div className="mt-3 grid gap-2">
            {videoJobs.map((j) => (
              <Card key={j.id} className="!py-2">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-slate-300">{j.message || "rendering"}</span>
                  <StatusBadge status={j.status} />
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
                  Download MP4
                </a>
                <button className="btn-danger !text-xs" onClick={() => del.mutate(video.id)}>
                  Delete
                </button>
              </div>
            </Card>
          ))}
        </div>
      </div>
    </div>
  );
}
