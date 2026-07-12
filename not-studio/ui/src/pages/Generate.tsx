import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import type { MusicProvider, PromptProvider, PromptSpec } from "../api/client";
import {
  useCancelJob,
  useDeleteJob,
  useGeneratePromptIdeas,
  useGenerateTracks,
  useHealth,
  useJobs,
  usePromptProviders,
  useRetryJob,
} from "../api/hooks";
import { Card, Field, Progress, SectionTitle, StatusBadge, cx } from "../components/ui";

const DEFAULT_MOODS = [
  "after-hours glow", "sunlit optimism", "bittersweet nostalgia", "weightless calm",
  "restless momentum", "rainy introspection", "romantic tension", "quiet confidence",
  "euphoric release", "cinematic wonder", "playful mischief", "focused flow",
];
const DEFAULT_STYLES = [
  "organic deep house", "dream pop", "jazz-inflected downtempo", "ambient electronica",
  "neo-classical minimalism", "leftfield breakbeat", "cinematic post-rock", "warm synthwave",
  "UK garage", "psychedelic soul", "minimal techno", "lofi jazzhop",
];

function storedList(key: string): string[] {
  try {
    const value = JSON.parse(localStorage.getItem(key) || "[]");
    return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
  } catch { return []; }
}

function bounded(value: string, min: number, max: number, label: string, integer = false) {
  const parsed = Number(value);
  if (!value.trim() || !Number.isFinite(parsed)) throw new Error(`Enter ${label.toLowerCase()}`);
  return Math.max(min, Math.min(max, integer ? Math.round(parsed) : parsed));
}

export default function Generate() {
  const [customMoods, setCustomMoods] = useState(() => storedList("not-studio:moods"));
  const [customStyles, setCustomStyles] = useState(() => storedList("not-studio:styles"));
  const [mood, setMood] = useState(DEFAULT_MOODS[0]);
  const [styles, setStyles] = useState<string[]>([DEFAULT_STYLES[0]]);
  const [newMood, setNewMood] = useState("");
  const [newStyle, setNewStyle] = useState("");
  const [trackCount, setTrackCount] = useState("4");
  const [duration, setDuration] = useState("180");
  const [durationVariation, setDurationVariation] = useState("10");
  const [albumTitle, setAlbumTitle] = useState("");
  const [provider, setProvider] = useState<MusicProvider>("stable_audio_local");
  const [promptProvider, setPromptProvider] = useState<PromptProvider>("lm_studio");
  const [tasteNotes, setTasteNotes] = useState("");
  const [promptJson, setPromptJson] = useState("");
  const [error, setError] = useState("");

  const genPrompts = useGeneratePromptIdeas();
  const genTracks = useGenerateTracks();
  const cancelJob = useCancelJob();
  const deleteJob = useDeleteJob();
  const retryJob = useRetryJob();
  const { data: health } = useHealth();
  const { data: promptProviders } = usePromptProviders();
  const { data: jobs } = useJobs();
  const generationJobs = (jobs ?? []).filter((job) => job.type === "generate_tracks").slice(0, 6);
  const availablePromptProviders = promptProviders ?? health?.prompt_providers ?? [];
  const selectedPromptProvider = availablePromptProviders.find((item) => item.provider === promptProvider);
  const moods = useMemo(() => [...DEFAULT_MOODS, ...customMoods.filter((x) => !DEFAULT_MOODS.includes(x))], [customMoods]);
  const styleOptions = useMemo(() => [...DEFAULT_STYLES, ...customStyles.filter((x) => !DEFAULT_STYLES.includes(x))], [customStyles]);

  useEffect(() => localStorage.setItem("not-studio:moods", JSON.stringify(customMoods)), [customMoods]);
  useEffect(() => localStorage.setItem("not-studio:styles", JSON.stringify(customStyles)), [customStyles]);

  function addMood() {
    const value = newMood.trim().toLowerCase();
    if (!value) return;
    setCustomMoods((current) => current.includes(value) ? current : [...current, value]);
    setMood(value); setNewMood("");
  }
  function addStyle() {
    const value = newStyle.trim().toLowerCase();
    if (!value) return;
    setCustomStyles((current) => current.includes(value) ? current : [...current, value]);
    setStyles((current) => current.includes(value) ? current : [...current, value]);
    setNewStyle("");
  }
  function toggleStyle(style: string) {
    setStyles((current) => current.includes(style) ? current.filter((x) => x !== style) : [...current, style]);
  }

  async function directPrompts() {
    setError("");
    try {
      if (!styles.length) throw new Error("Choose at least one style");
      const result = await genPrompts.mutateAsync({
        provider: promptProvider, mood, styles,
        track_count: bounded(trackCount, 1, 20, "Track count", true),
        duration: bounded(duration, 15, 900, "Duration"),
        duration_variation_percent: bounded(durationVariation, 0, 50, "Duration spread"),
        album_title: albumTitle || null, taste_notes: tasteNotes,
      });
      setPromptJson(JSON.stringify(result.prompts, null, 2));
    } catch (cause) { setError((cause as Error).message); }
  }

  async function generate() {
    setError("");
    try {
      const prompts = JSON.parse(promptJson) as PromptSpec[];
      if (!Array.isArray(prompts) || !prompts.length) throw new Error("Generate at least one prompt first");
      await genTracks.mutateAsync({ prompts, provider });
    } catch (cause) { setError((cause as Error).message); }
  }

  return <div>
    <SectionTitle title="Direct an album" subtitle="Set the musical direction, let the LLM write the track plan, then generate audio from that plan." actions={<Link className="btn-ghost" to="/library">Review tracks</Link>} />
    <Card>
      <div className="space-y-6">
        <div className="grid gap-5 lg:grid-cols-2">
          <Field label="Album title"><input className="input" placeholder="Optional" value={albumTitle} onChange={(e) => setAlbumTitle(e.target.value)} /></Field>
          <Field label="Taste direction"><textarea className="input h-20" value={tasteNotes} onChange={(e) => setTasteNotes(e.target.value)} placeholder="Textures, energy, arrangement, and what to avoid." /></Field>
        </div>
        <Field label="Mood">
          <div className="flex flex-wrap gap-2">{moods.map((item) => <button key={item} className={cx("choice-chip", mood === item && "choice-chip-active")} onClick={() => setMood(item)}>{item}</button>)}</div>
          <div className="mt-2 flex gap-2"><input className="input" value={newMood} onChange={(e) => setNewMood(e.target.value)} onKeyDown={(e) => e.key === "Enter" && addMood()} placeholder="Add your own mood" /><button className="btn-ghost shrink-0" onClick={addMood}>+ Add mood</button></div>
        </Field>
        <Field label="Styles">
          <div className="flex flex-wrap gap-2">{styleOptions.map((item) => <button key={item} className={cx("choice-chip", styles.includes(item) && "choice-chip-active")} onClick={() => toggleStyle(item)}>{item}</button>)}</div>
          <div className="mt-2 flex gap-2"><input className="input" value={newStyle} onChange={(e) => setNewStyle(e.target.value)} onKeyDown={(e) => e.key === "Enter" && addStyle()} placeholder="Add your own style" /><button className="btn-ghost shrink-0" onClick={addStyle}>+ Add style</button></div>
        </Field>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <Field label="Tracks"><input className="input" type="number" min="1" max="20" value={trackCount} onChange={(e) => setTrackCount(e.target.value)} /></Field>
          <Field label="Target seconds"><input className="input" type="number" min="15" max="900" value={duration} onChange={(e) => setDuration(e.target.value)} /></Field>
          <Field label="Duration spread %"><input className="input" type="number" min="0" max="50" value={durationVariation} onChange={(e) => setDurationVariation(e.target.value)} /></Field>
          <Field label="Prompt model"><select className="input" value={promptProvider} onChange={(e) => setPromptProvider(e.target.value as PromptProvider)}>{availablePromptProviders.map((item) => <option key={item.provider} value={item.provider}>{item.provider.replace("_", " ")}{item.available ? "" : " (unavailable)"}</option>)}</select></Field>
          <Field label="Audio engine"><select className="input" value={provider} onChange={(e) => setProvider(e.target.value as MusicProvider)}><option value="stable_audio_local">Stable Audio / Local</option><option value="stable_audio_runpod">Stable Audio / RunPod</option></select></Field>
        </div>
        <div className="border-t border-ink-700 pt-5">
          <div className="mb-2 flex flex-wrap items-end justify-between gap-3"><div><h3 className="font-medium text-slate-100">Album track plan</h3><p className="text-xs text-slate-500">Editable LLM output; this is the only input sent to audio generation.</p></div><button className="btn-ghost" disabled={genPrompts.isPending || !selectedPromptProvider?.available} onClick={directPrompts}>{genPrompts.isPending ? "Directing album…" : promptJson ? "Regenerate track plan" : "Create track plan"}</button></div>
          <textarea className="input h-72 font-mono" value={promptJson} onChange={(e) => setPromptJson(e.target.value)} spellCheck={false} placeholder="Create a track plan to generate editable prompts." />
          <div className="mt-3 flex flex-wrap items-center gap-3"><button className="btn-primary" disabled={!promptJson.trim() || genTracks.isPending} onClick={generate}>{genTracks.isPending ? "Submitting…" : "Generate album from prompts"}</button>{error && <span className="text-sm text-red-400">{error}</span>}</div>
        </div>
      </div>
    </Card>

    {generationJobs.length > 0 && <div className="mt-6"><h3 className="mb-2 text-sm font-semibold text-slate-300">Recent generations</h3><div className="grid gap-2">{generationJobs.map((job) => <Card key={job.id} className="!py-3"><div className="flex flex-wrap items-center justify-between gap-2"><span className="min-w-0 text-sm text-slate-300">{job.message || "queued"}</span><div className="flex items-center gap-2"><StatusBadge status={job.status} />{job.status === "failed" && <button className="btn-primary !text-xs" disabled={retryJob.isPending} onClick={() => retryJob.mutate(job.id)}>Retry</button>}{(job.status === "queued" || job.status === "in_progress") && <button className="btn-danger !text-xs" disabled={cancelJob.isPending} onClick={() => cancelJob.mutate(job.id)}>Cancel</button>}<button className="btn-ghost !text-xs" disabled={deleteJob.isPending} onClick={() => deleteJob.mutate(job.id)}>Remove</button></div></div>{job.status === "in_progress" && <div className="mt-2"><Progress value={job.progress} /></div>}{job.error && <div className="mt-1 text-xs text-red-400">{job.error}</div>}</Card>)}</div></div>}
  </div>;
}
