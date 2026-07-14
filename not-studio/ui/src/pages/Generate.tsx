import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import type { MusicProvider, PromptPlan, PromptSpec } from "../api/client";
import {
  useCancelJob,
  useDeleteJob,
  useGenerateTracks,
  useJobs,
  usePromptKit,
  useRetryJob,
} from "../api/hooks";
import { CopyIcon, SparklesIcon } from "../components/icons";
import { Badge, Card, Field, Progress, SectionTitle, StatusBadge } from "../components/ui";

function storedPromptPlan(): string {
  try {
    return localStorage.getItem("not-studio:prompt-plan") || "";
  } catch {
    return "";
  }
}

function storedArtworkGuidance(): string {
  try {
    return localStorage.getItem("not-studio:artwork-guidance") || "";
  } catch {
    return "";
  }
}

function parsePromptPlan(value: string): PromptPlan {
  const parsed: unknown = JSON.parse(value);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("Top level must be an object with album_title and prompts");
  }
  const source = parsed as Record<string, unknown>;
  if (typeof source.album_title !== "string" || !source.album_title.trim()) {
    throw new Error("Album plan needs an album_title");
  }
  if (!Array.isArray(source.prompts) || source.prompts.length === 0) {
    throw new Error("Album plan needs a non-empty prompts list");
  }
  if (source.prompts.length > 20) throw new Error("An album can contain at most 20 tracks");
  for (const key of ["notes", "artwork_prompt"] as const) {
    if (source[key] != null && typeof source[key] !== "string") {
      throw new Error(`${key} must be a string when provided`);
    }
  }
  const prompts = source.prompts.map((item, index) => {
    if (!item || typeof item !== "object") throw new Error(`Track ${index + 1} must be an object`);
    const track = item as Record<string, unknown>;
    if (typeof track.title !== "string" || !track.title.trim()) throw new Error(`Track ${index + 1} needs a title`);
    if (typeof track.genre !== "string" || !track.genre.trim()) throw new Error(`Track ${index + 1} needs a genre`);
    if (typeof track.prompt !== "string" || !track.prompt.trim()) throw new Error(`Track ${index + 1} needs a prompt`);
    for (const key of ["notes", "artwork_prompt"] as const) {
      if (track[key] != null && typeof track[key] !== "string") {
        throw new Error(`Track ${index + 1} ${key} must be a string when provided`);
      }
    }
    const duration = Number(track.duration);
    if (!Number.isFinite(duration) || duration < 15 || duration > 900) throw new Error(`Track ${index + 1} duration must be 15–900 seconds`);
    const notes = typeof track.notes === "string" ? track.notes.trim() : "";
    const artworkPrompt = typeof track.artwork_prompt === "string" ? track.artwork_prompt.trim() : "";
    return {
      ...track,
      title: track.title.trim(),
      genre: track.genre.trim(),
      prompt: track.prompt.trim(),
      duration,
      ...(notes ? { notes } : {}),
      ...(artworkPrompt ? { artwork_prompt: artworkPrompt } : {}),
    } as PromptSpec;
  });
  const notes = typeof source.notes === "string" ? source.notes.trim() : "";
  const artworkPrompt = typeof source.artwork_prompt === "string" ? source.artwork_prompt.trim() : "";
  return {
    album_title: source.album_title.trim(),
    ...(notes ? { notes } : {}),
    ...(artworkPrompt ? { artwork_prompt: artworkPrompt } : {}),
    prompts,
  };
}

export default function Generate() {
  const [promptJson, setPromptJson] = useState(storedPromptPlan);
  const [artworkGuidance, setArtworkGuidance] = useState(storedArtworkGuidance);
  const [provider, setProvider] = useState<MusicProvider>("stable_audio_local");
  const [showKit, setShowKit] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");

  const { data: promptKit } = usePromptKit();
  const { data: jobs } = useJobs();
  const genTracks = useGenerateTracks();
  const cancelJob = useCancelJob();
  const deleteJob = useDeleteJob();
  const retryJob = useRetryJob();
  const generationJobs = (jobs ?? []).filter((job) => job.type === "generate_tracks").slice(0, 6);

  useEffect(() => {
    try { localStorage.setItem("not-studio:prompt-plan", promptJson); } catch { /* ignore */ }
  }, [promptJson]);

  useEffect(() => {
    try { localStorage.setItem("not-studio:artwork-guidance", artworkGuidance); } catch { /* ignore */ }
  }, [artworkGuidance]);

  const guidedPromptKit = useMemo(
    () => promptKit ? { ...promptKit, artwork_guidance: artworkGuidance } : undefined,
    [artworkGuidance, promptKit],
  );

  const plan = useMemo(() => {
    if (!promptJson.trim()) return { value: null as PromptPlan | null, prompts: [] as PromptSpec[], error: "" };
    try {
      const value = parsePromptPlan(promptJson);
      return { value, prompts: value.prompts, error: "" };
    }
    catch (cause) { return { value: null, prompts: [] as PromptSpec[], error: (cause as Error).message }; }
  }, [promptJson]);

  const genres = [...new Set(plan.prompts.map((prompt) => prompt.genre))];
  const totalMinutes = Math.round(plan.prompts.reduce((sum, prompt) => sum + prompt.duration, 0) / 60);

  async function copyKit() {
    if (!guidedPromptKit) return;
    await navigator.clipboard.writeText(JSON.stringify(guidedPromptKit, null, 2));
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  }

  async function generate() {
    setError("");
    try {
      const parsedPlan = parsePromptPlan(promptJson);
      await genTracks.mutateAsync({ ...parsedPlan, provider });
    } catch (cause) {
      setError((cause as Error).message);
    }
  }

  return <div>
    <SectionTitle
      title="Generate from your prompts"
      subtitle="Bring the music direction from GPT, paste the JSON plan, and send it straight to Stable Audio."
      actions={<Link className="btn-ghost" to="/library">Open library</Link>}
    />

    <Card className="mb-4 overflow-hidden !border-accent/30 bg-gradient-to-br from-accent/10 via-ink-900 to-ink-900">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex min-w-0 items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent/20 text-accent-soft">
            <SparklesIcon className="h-5 w-5" />
          </div>
          <div>
            <div className="font-medium text-slate-100">GPT prompt kit</div>
            <p className="mt-0.5 max-w-2xl text-sm text-slate-400">
              Copy the live JSON contract plus your liked prompt history, then ask GPT to create the next batch.
            </p>
            {promptKit && <div className="mt-2 flex flex-wrap gap-2">
              <Badge tone="green">{promptKit.taste_profile.liked_examples.length} liked</Badge>
              <Badge tone="violet">album + artwork schema</Badge>
            </div>}
          </div>
        </div>
        <div className="flex shrink-0 gap-2">
          <button className="btn-ghost" onClick={() => setShowKit((value) => !value)}>{showKit ? "Hide spec" : "View spec"}</button>
          <button className="btn-primary" disabled={!promptKit} onClick={copyKit}>
            <CopyIcon className="h-4 w-4" /> {copied ? "Copied" : "Copy for GPT"}
          </button>
        </div>
      </div>
      <label className="mt-4 block">
        <span className="label">Artwork guidance</span>
        <textarea
          className="input min-h-24 resize-y"
          value={artworkGuidance}
          maxLength={4000}
          placeholder="Describe your preferred visual style, recurring motifs, colors, composition, and anything artwork prompts should avoid."
          onChange={(event) => setArtworkGuidance(event.target.value)}
        />
        <span className="mt-1 block text-xs text-slate-500">
          Saved automatically and included as artwork_guidance in the copied GPT prompt kit.
        </span>
      </label>
      {showKit && <textarea className="input mt-4 h-80 font-mono text-xs" readOnly value={guidedPromptKit ? JSON.stringify(guidedPromptKit, null, 2) : "Loading…"} />}
    </Card>

    <Card>
      <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h3 className="font-medium text-slate-100">Prompt plan JSON</h3>
          <p className="text-xs text-slate-500">
            Required: album_title and prompts. Optional: notes and artwork_prompt. Your draft is saved in this browser.
          </p>
        </div>
        <Field label="Audio engine">
          <select className="input w-auto min-w-52" value={provider} onChange={(event) => setProvider(event.target.value as MusicProvider)}>
            <option value="stable_audio_local">Stable Audio / Local</option>
            <option value="stable_audio_runpod">Stable Audio / RunPod</option>
          </select>
        </Field>
      </div>
      <textarea
        className="input h-[28rem] resize-y font-mono text-sm leading-6"
        value={promptJson}
        onChange={(event) => setPromptJson(event.target.value)}
        spellCheck={false}
        placeholder={'{\n  "album_title": "Glass Transit",\n  "notes": "A nocturnal album arc",\n  "artwork_prompt": "Square abstract glass album cover, no text",\n  "prompts": [\n    {\n      "title": "Last Platform",\n      "genre": "ambient techno",\n      "prompt": "Instrumental…",\n      "duration": 180,\n      "notes": "Quiet opening track",\n      "artwork_prompt": "Empty glass platform at night, no text"\n    }\n  ]\n}'}
      />
      <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2 text-xs">
          {plan.prompts.length > 0 && <>
            <Badge tone="violet">{plan.value?.album_title}</Badge>
            <Badge tone="green">{plan.prompts.length} track{plan.prompts.length === 1 ? "" : "s"}</Badge>
            <Badge>{totalMinutes} min total</Badge>
            {plan.value?.artwork_prompt && <Badge tone="amber">cover direction</Badge>}
            {genres.slice(0, 4).map((genre) => <Badge key={genre} tone="blue">{genre}</Badge>)}
          </>}
          {plan.error && <span className="text-red-400">{plan.error}</span>}
        </div>
        <button className="btn-primary" disabled={plan.prompts.length === 0 || genTracks.isPending} onClick={generate}>
          <SparklesIcon className="h-4 w-4" /> {genTracks.isPending ? "Submitting…" : `Generate ${plan.prompts.length || ""} track${plan.prompts.length === 1 ? "" : "s"}`}
        </button>
      </div>
      {error && <div className="mt-2 text-sm text-red-400">{error}</div>}
    </Card>

    {generationJobs.length > 0 && <div className="mt-6"><h3 className="mb-2 text-sm font-semibold text-slate-300">Recent generations</h3><div className="grid gap-2">{generationJobs.map((job) => <Card key={job.id} className="!py-3"><div className="flex flex-wrap items-center justify-between gap-2"><span className="min-w-0 text-sm text-slate-300">{job.message || "queued"}</span><div className="flex items-center gap-2"><StatusBadge status={job.status} />{job.status === "failed" && <button className="btn-primary !text-xs" disabled={retryJob.isPending} onClick={() => retryJob.mutate(job.id)}>Retry</button>}{(job.status === "queued" || job.status === "in_progress") && <button className="btn-danger !text-xs" disabled={cancelJob.isPending} onClick={() => cancelJob.mutate(job.id)}>Cancel</button>}<button className="btn-ghost !text-xs" disabled={deleteJob.isPending} onClick={() => deleteJob.mutate(job.id)}>Remove</button></div></div>{job.status === "in_progress" && <div className="mt-2"><Progress value={job.progress} /></div>}{job.error && <div className="mt-1 text-xs text-red-400">{job.error}</div>}</Card>)}</div></div>}
  </div>;
}
