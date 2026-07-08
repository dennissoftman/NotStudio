import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import type { MusicProvider, PromptProvider } from "../api/client";
import {
  useGenerateAlbum,
  useGeneratePromptIdeas,
  useGenerateTracks,
  useHealth,
  useJobs,
  usePromptProviders,
} from "../api/hooks";
import { Card, Field, Progress, SectionTitle, StatusBadge, cx } from "../components/ui";

const MOODS = ["night drive", "sunrise", "melancholic", "euphoric", "focused", "dreamy"];
const STYLES = [
  "deep house",
  "synthwave",
  "lofi hip hop",
  "ambient",
  "downtempo",
  "breakbeat",
  "cinematic",
  "minimal techno",
];

export default function Generate() {
  const [mood, setMood] = useState(MOODS[0]);
  const [customMood, setCustomMood] = useState("");
  const [styles, setStyles] = useState<string[]>(["deep house"]);
  const [trackCount, setTrackCount] = useState(4);
  const [duration, setDuration] = useState(180);
  const [albumTitle, setAlbumTitle] = useState("");
  const [provider, setProvider] = useState<MusicProvider>("stable_audio_local");
  const [promptProvider, setPromptProvider] = useState<PromptProvider>("lm_studio");
  const [tasteNotes, setTasteNotes] = useState("");
  const [promptJson, setPromptJson] = useState("");
  const [error, setError] = useState("");

  const gen = useGenerateAlbum();
  const genTracks = useGenerateTracks();
  const genPrompts = useGeneratePromptIdeas();
  const { data: health } = useHealth();
  const { data: promptProviders } = usePromptProviders();
  const { data: jobs } = useJobs();
  const genJobs = (jobs ?? []).filter((j) => j.type === "generate_tracks").slice(0, 6);

  const effectiveMood = useMemo(() => customMood.trim() || mood, [customMood, mood]);

  function toggleStyle(style: string) {
    setStyles((current) =>
      current.includes(style) ? current.filter((s) => s !== style) : [...current, style],
    );
  }

  async function submit() {
    setError("");
    if (!effectiveMood) {
      setError("Choose a mood");
      return;
    }
    if (styles.length === 0) {
      setError("Choose at least one style");
      return;
    }
    try {
      await gen.mutateAsync({
        mood: effectiveMood,
        styles,
        track_count: trackCount,
        duration,
        album_title: albumTitle || null,
        provider,
      });
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function createPromptIdeas() {
    setError("");
    try {
      const result = await genPrompts.mutateAsync({
        provider: promptProvider,
        mood: effectiveMood,
        styles,
        track_count: trackCount,
        album_title: albumTitle || null,
        taste_notes: tasteNotes,
      });
      setPromptJson(JSON.stringify(result.prompts, null, 2));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function submitPromptJson() {
    setError("");
    try {
      const prompts = JSON.parse(promptJson);
      if (!Array.isArray(prompts) || prompts.length === 0) {
        throw new Error("expected a non-empty prompt array");
      }
      await genTracks.mutateAsync({ prompts, provider });
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div>
      <SectionTitle
        title="Album generation"
        subtitle="Choose the direction, generate a batch, then review tracks into a mix."
        actions={
          <Link className="btn-ghost" to="/library">
            Review tracks
          </Link>
        }
      />

      <div className="grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
        <Card>
          <div className="space-y-5">
            <Field label="Mood">
              <div className="grid gap-2 sm:grid-cols-3">
                {MOODS.map((item) => (
                  <button
                    key={item}
                    className={cx("choice-btn", mood === item && !customMood && "choice-btn-active")}
                    onClick={() => {
                      setMood(item);
                      setCustomMood("");
                    }}
                  >
                    {item}
                  </button>
                ))}
              </div>
              <input
                className="input mt-2"
                placeholder="Custom mood"
                value={customMood}
                onChange={(e) => setCustomMood(e.target.value)}
              />
            </Field>

            <Field label="Styles">
              <div className="grid gap-2 sm:grid-cols-4">
                {STYLES.map((style) => (
                  <button
                    key={style}
                    className={cx("choice-btn", styles.includes(style) && "choice-btn-active")}
                    onClick={() => toggleStyle(style)}
                  >
                    {style}
                  </button>
                ))}
              </div>
            </Field>

            <div className="grid gap-3 sm:grid-cols-3">
              <Field label="Track count">
                <input
                  className="input"
                  type="number"
                  min={1}
                  max={20}
                  value={trackCount}
                  onChange={(e) => setTrackCount(Math.max(1, Math.min(20, +e.target.value)))}
                />
              </Field>
              <Field label="Duration seconds">
                <input
                  className="input"
                  type="number"
                  min={15}
                  max={900}
                  step={15}
                  value={duration}
                  onChange={(e) => setDuration(Math.max(15, Math.min(900, +e.target.value)))}
                />
              </Field>
              <Field label="Provider">
                <select
                  className="input"
                  value={provider}
                  onChange={(e) => setProvider(e.target.value as MusicProvider)}
                >
                  <option value="stable_audio_local">Stable Audio / Local</option>
                  <option value="stable_audio_runpod">Stable Audio / RunPod</option>
                </select>
              </Field>
            </div>

            <Field label="Album title">
              <input
                className="input"
                placeholder="Optional"
                value={albumTitle}
                onChange={(e) => setAlbumTitle(e.target.value)}
              />
            </Field>

            <div className="flex flex-wrap items-center gap-3">
              <button className="btn-primary" disabled={gen.isPending} onClick={submit}>
                {gen.isPending ? "Submitting" : `Generate ${trackCount} tracks`}
              </button>
              {error && <span className="text-sm text-red-400">{error}</span>}
            </div>
          </div>
        </Card>

        <Card>
          <h3 className="text-sm font-semibold text-slate-200">Current batch</h3>
          <dl className="mt-3 space-y-3 text-sm">
            <div>
              <dt className="text-xs uppercase tracking-wide text-slate-500">Mood</dt>
              <dd className="text-slate-100">{effectiveMood}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-slate-500">Styles</dt>
              <dd className="text-slate-100">{styles.join(", ") || "none"}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-slate-500">Output</dt>
              <dd className="text-slate-100">
                {trackCount} tracks, {duration}s each
              </dd>
            </div>
          </dl>
        </Card>
      </div>

      <Card className="mt-4">
        <div className="grid gap-4 lg:grid-cols-[0.8fr_1.2fr]">
          <div className="space-y-3">
            <h3 className="text-sm font-semibold text-slate-200">LLM prompt director</h3>
            <Field label="Prompt provider">
              <select
                className="input"
                value={promptProvider}
                onChange={(e) => setPromptProvider(e.target.value as PromptProvider)}
              >
                {(promptProviders ?? health?.prompt_providers ?? []).map((item) => (
                  <option key={item.provider} value={item.provider}>
                    {item.provider.replace("_", " ")}
                    {item.available ? "" : " (needs key)"}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Taste notes">
              <textarea
                className="input h-28"
                value={tasteNotes}
                onChange={(e) => setTasteNotes(e.target.value)}
                placeholder="What you liked/disliked in previous batches, references to texture, energy, arrangement."
              />
            </Field>
            <div className="flex flex-wrap gap-2">
              <button className="btn-ghost" disabled={genPrompts.isPending} onClick={createPromptIdeas}>
                {genPrompts.isPending ? "Generating prompts" : "Generate prompts"}
              </button>
              <button
                className="btn-primary"
                disabled={!promptJson.trim() || genTracks.isPending}
                onClick={submitPromptJson}
              >
                Generate from prompts
              </button>
            </div>
          </div>
          <Field label="Prompt JSON">
            <textarea
              className="input h-72 font-mono"
              value={promptJson}
              onChange={(e) => setPromptJson(e.target.value)}
              spellCheck={false}
              placeholder="LLM-generated prompts appear here and can be edited before audio generation."
            />
          </Field>
        </div>
      </Card>

      {genJobs.length > 0 && (
        <div className="mt-6">
          <h3 className="mb-2 text-sm font-semibold text-slate-300">Recent generations</h3>
          <div className="grid gap-2">
            {genJobs.map((j) => (
              <Card key={j.id} className="!py-3">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-slate-300">{j.message || "queued"}</span>
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
        </div>
      )}
    </div>
  );
}
