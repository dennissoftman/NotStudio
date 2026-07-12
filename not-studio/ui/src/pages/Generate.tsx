import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import type { MusicProvider, PromptProvider } from "../api/client";
import {
  useGenerateAlbum,
  useGeneratePromptIdeas,
  useGenerateTracks,
  useHealth,
  useCancelJob,
  useDeleteJob,
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

function parseBoundedNumber(
  value: string,
  min: number,
  max: number,
  label: string,
  integer = false,
) {
  const raw = Number(value);
  if (!value.trim() || !Number.isFinite(raw)) {
    throw new Error(`Enter ${label.toLowerCase()}`);
  }
  const normalized = integer ? Math.round(raw) : raw;
  return Math.max(min, Math.min(max, normalized));
}

function previewBoundedNumber(value: string, min: number, max: number, integer = false) {
  const raw = Number(value);
  if (!value.trim() || !Number.isFinite(raw)) return null;
  const normalized = integer ? Math.round(raw) : raw;
  return Math.max(min, Math.min(max, normalized));
}

function commitBoundedNumber(
  value: string,
  min: number,
  max: number,
  setValue: (value: string) => void,
  integer = false,
) {
  if (!value.trim()) return;
  const raw = Number(value);
  if (!Number.isFinite(raw)) return;
  setValue(String(Math.max(min, Math.min(max, integer ? Math.round(raw) : raw))));
}

function titleCase(value: string) {
  return value.replace(/\b\w/g, (char) => char.toUpperCase());
}

function trackDuration(baseDuration: number, variationPercent: number, index: number, total: number) {
  if (variationPercent <= 0 || total <= 1) return baseDuration;
  const position = index / (total - 1);
  const deviation = position * 2 - 1;
  return Math.max(
    15,
    Math.min(900, Math.round(baseDuration * (1 + deviation * (variationPercent / 100)))),
  );
}

export default function Generate() {
  const [mood, setMood] = useState(MOODS[0]);
  const [customMood, setCustomMood] = useState("");
  const [styles, setStyles] = useState<string[]>(["deep house"]);
  const [trackCountInput, setTrackCountInput] = useState("4");
  const [durationInput, setDurationInput] = useState("180");
  const [durationVariationInput, setDurationVariationInput] = useState("10");
  const [albumTitle, setAlbumTitle] = useState("");
  const [provider, setProvider] = useState<MusicProvider>("stable_audio_local");
  const [promptProvider, setPromptProvider] = useState<PromptProvider>("lm_studio");
  const [tasteNotes, setTasteNotes] = useState("");
  const [promptJson, setPromptJson] = useState("");
  const [error, setError] = useState("");

  const gen = useGenerateAlbum();
  const genTracks = useGenerateTracks();
  const cancelJob = useCancelJob();
  const deleteJob = useDeleteJob();
  const genPrompts = useGeneratePromptIdeas();
  const { data: health } = useHealth();
  const { data: promptProviders } = usePromptProviders();
  const { data: jobs } = useJobs();
  const genJobs = (jobs ?? []).filter((j) => j.type === "generate_tracks").slice(0, 6);
  const availablePromptProviders = promptProviders ?? health?.prompt_providers ?? [];
  const selectedPromptProvider = availablePromptProviders.find(
    (item) => item.provider === promptProvider,
  );

  const effectiveMood = useMemo(() => customMood.trim() || mood, [customMood, mood]);
  const selectedPresetMood = customMood.trim() ? null : mood;
  const trackCountPreview = previewBoundedNumber(trackCountInput, 1, 20, true);
  const durationPreview = previewBoundedNumber(durationInput, 15, 900);
  const durationVariationPreview = previewBoundedNumber(durationVariationInput, 0, 50) ?? 0;
  const durationSummary =
    durationPreview === null
      ? "set duration"
      : durationVariationPreview > 0
        ? `${durationPreview}s target, +/-${durationVariationPreview}% spread`
        : `${durationPreview}s each`;
  const previewPrompts =
    trackCountPreview && durationPreview
      ? Array.from({ length: Math.min(trackCountPreview, 6) }, (_, index) => {
          const trackIndex = index + 1;
          const styleText = styles.length ? styles.join(", ") : "genre-fluid instrumental";
          return {
            title: `${albumTitle.trim() || titleCase(effectiveMood)} ${String(trackIndex).padStart(
              2,
              "0",
            )}`,
            duration: trackDuration(
              durationPreview,
              durationVariationPreview,
              index,
              trackCountPreview,
            ),
            prompt: `${effectiveMood} mood, ${styleText}, instrumental full track, polished arrangement, track ${trackIndex} of ${trackCountPreview}, no vocals`,
          };
        })
      : [];

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
      const trackCount = parseBoundedNumber(trackCountInput, 1, 20, "Track count", true);
      const duration = parseBoundedNumber(durationInput, 15, 900, "Duration seconds");
      const durationVariation = parseBoundedNumber(
        durationVariationInput,
        0,
        50,
        "Duration spread",
      );
      await gen.mutateAsync({
        mood: effectiveMood,
        styles,
        track_count: trackCount,
        duration,
        duration_variation_percent: durationVariation,
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
      const trackCount = parseBoundedNumber(trackCountInput, 1, 20, "Track count", true);
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
                    className={cx(
                      "choice-btn",
                      selectedPresetMood === item && "choice-btn-active",
                    )}
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
                  value={trackCountInput}
                  onBlur={() =>
                    commitBoundedNumber(trackCountInput, 1, 20, setTrackCountInput, true)
                  }
                  onChange={(e) => setTrackCountInput(e.target.value)}
                />
              </Field>
              <Field label="Duration seconds">
                <input
                  className="input"
                  type="number"
                  min={15}
                  max={900}
                  step={15}
                  value={durationInput}
                  onBlur={() => commitBoundedNumber(durationInput, 15, 900, setDurationInput)}
                  onChange={(e) => setDurationInput(e.target.value)}
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

            <Field label={`Duration spread ${durationVariationPreview}%`}>
              <input
                className="w-full accent-accent"
                type="range"
                min={0}
                max={50}
                step={5}
                value={durationVariationInput}
                onChange={(e) => setDurationVariationInput(e.target.value)}
              />
            </Field>

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
                {gen.isPending
                  ? "Submitting"
                  : trackCountPreview
                    ? `Generate ${trackCountPreview} tracks`
                    : "Generate tracks"}
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
                {trackCountPreview ?? "set"} tracks, {durationSummary}
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
                {availablePromptProviders.map((item) => (
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
              <button
                className="btn-ghost"
                disabled={genPrompts.isPending || !selectedPromptProvider?.available}
                onClick={createPromptIdeas}
              >
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

      {previewPrompts.length > 0 && (
        <div className="mt-4">
          <h3 className="mb-2 text-sm font-semibold text-slate-300">Planned prompts</h3>
          <div className="overflow-hidden rounded-lg border border-ink-700">
            {previewPrompts.map((item) => (
              <div key={item.title} className="border-b border-ink-700 p-3 last:border-b-0">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-sm font-medium text-slate-200">{item.title}</span>
                  <span className="shrink-0 text-xs text-slate-500">{item.duration}s</span>
                </div>
                <p className="mt-1 text-xs text-slate-500">{item.prompt}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {genJobs.length > 0 && (
        <div className="mt-6">
          <h3 className="mb-2 text-sm font-semibold text-slate-300">Recent generations</h3>
          <div className="grid gap-2">
            {genJobs.map((j) => (
              <Card key={j.id} className="!py-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="min-w-0 text-sm text-slate-300">{j.message || "queued"}</span>
                  <div className="flex shrink-0 items-center gap-2">
                    <StatusBadge status={j.status} />
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
        </div>
      )}
    </div>
  );
}
