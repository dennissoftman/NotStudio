import { useState } from "react";
import { api } from "../api/client";
import {
  useDeleteHistory,
  useJobs,
  useMakeVideo,
  useTracks,
  useVideos,
} from "../api/hooks";
import {
  Card,
  Empty,
  Progress,
  SectionTitle,
  StatusBadge,
  cx,
  fmtDuration,
} from "../components/ui";

export default function Library() {
  const { data: tracks } = useTracks();
  const { data: videos } = useVideos();
  const { data: jobs } = useJobs();
  const makeVideo = useMakeVideo();
  const del = useDeleteHistory();

  const [selected, setSelected] = useState<string[]>([]);
  const [title, setTitle] = useState("");
  const [visualizer, setVisualizer] = useState("cqt");
  const [crossfade, setCrossfade] = useState(6);
  const [error, setError] = useState("");

  const toggle = (id: string) =>
    setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));
  const videoJobs = (jobs ?? []).filter((j) => j.type === "make_video").slice(0, 4);

  async function combine() {
    setError("");
    if (selected.length === 0) {
      setError("Select at least one track");
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
          title="Tracks"
          subtitle="Tick tracks in the order you want them, then make a video."
        />
        {tracks?.length === 0 && <Empty>No tracks yet — generate some on the Generate page.</Empty>}
        <div className="grid gap-2">
          {tracks?.map((t) => {
            const idx = selected.indexOf(t.id);
            const prompt = String((t.meta as Record<string, unknown>)?.prompt ?? "");
            return (
              <Card key={t.id} className="!py-3">
                <div className="flex items-center gap-3">
                  <button
                    onClick={() => toggle(t.id)}
                    title="Select for the mix"
                    className={cx(
                      "flex h-7 w-7 shrink-0 items-center justify-center rounded-md border text-xs font-semibold",
                      idx >= 0
                        ? "border-accent bg-accent text-white"
                        : "border-ink-600 text-slate-500 hover:border-ink-500",
                    )}
                  >
                    {idx >= 0 ? idx + 1 : "+"}
                  </button>
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-medium text-slate-100">{t.title}</div>
                    {prompt && <div className="truncate text-xs text-slate-500">{prompt}</div>}
                  </div>
                  <span className="shrink-0 text-xs text-slate-500">
                    {fmtDuration(t.duration_seconds)}
                  </span>
                  <audio className="h-8 w-56 max-w-[40vw]" controls preload="none" src={api.audioUrl(t.id)} />
                  <button
                    className="shrink-0 text-xs text-red-400 hover:text-red-300"
                    onClick={() => del.mutate(t.id)}
                    title="Delete track"
                  >
                    ✕
                  </button>
                </div>
              </Card>
            );
          })}
        </div>

        {(tracks?.length ?? 0) > 0 && (
          <Card className="mt-3">
            <div className="flex flex-wrap items-end gap-3">
              <label className="grow">
                <span className="label">Video title (optional)</span>
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
                <span className="label">Crossfade (s)</span>
                <input
                  type="number"
                  className="input w-24"
                  value={crossfade}
                  onChange={(e) => setCrossfade(+e.target.value)}
                />
              </label>
              <button
                className="btn-primary"
                disabled={selected.length === 0 || makeVideo.isPending}
                onClick={combine}
              >
                🎬 Make video ({selected.length})
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
        <SectionTitle title="Videos" subtitle="Rendered, YouTube-ready mixes (−14 LUFS audio)." />
        {videos?.length === 0 && <Empty>No videos yet.</Empty>}
        <div className="grid gap-3 sm:grid-cols-2">
          {videos?.map((v) => (
            <Card key={v.id}>
              <div className="mb-2 flex items-center justify-between">
                <div className="truncate font-medium text-slate-100">{v.title}</div>
                <span className="shrink-0 text-xs text-slate-500">
                  {fmtDuration(v.duration_seconds)}
                </span>
              </div>
              <video className="w-full rounded-lg bg-black" controls preload="none" src={api.audioUrl(v.id)} />
              <div className="mt-2 flex gap-2">
                <a className="btn-ghost !text-xs" href={api.audioUrl(v.id)} download>
                  Download
                </a>
                <button className="btn-danger !text-xs" onClick={() => del.mutate(v.id)}>
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
