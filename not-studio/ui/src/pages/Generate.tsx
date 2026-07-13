import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import type { MusicProvider, PromptSpec } from "../api/client";
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

function parsePromptPlan(value: string): PromptSpec[] {
  const parsed: unknown = JSON.parse(value);
  if (!Array.isArray(parsed) || parsed.length === 0) throw new Error("Paste a non-empty JSON array");
  if (parsed.length > 20) throw new Error("A batch can contain at most 20 tracks");
  return parsed.map((item, index) => {
    if (!item || typeof item !== "object") throw new Error(`Track ${index + 1} must be an object`);
    const track = item as Record<string, unknown>;
    if (typeof track.title !== "string" || !track.title.trim()) throw new Error(`Track ${index + 1} needs a title`);
    if (typeof track.genre !== "string" || !track.genre.trim()) throw new Error(`Track ${index + 1} needs a genre`);
    if (typeof track.prompt !== "string" || !track.prompt.trim()) throw new Error(`Track ${index + 1} needs a prompt`);
    const duration = Number(track.duration);
    if (!Number.isFinite(duration) || duration < 15 || duration > 900) throw new Error(`Track ${index + 1} duration must be 15–900 seconds`);
    return { ...track, title: track.title.trim(), genre: track.genre.trim(), prompt: track.prompt.trim(), duration } as PromptSpec;
  });
}

export default function Generate() {
  const [promptJson, setPromptJson] = useState(storedPromptPlan);
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

  const plan = useMemo(() => {
    if (!promptJson.trim()) return { prompts: [] as PromptSpec[], error: "" };
    try { return { prompts: parsePromptPlan(promptJson), error: "" }; }
    catch (cause) { return { prompts: [] as PromptSpec[], error: (cause as Error).message }; }
  }, [promptJson]);

  const genres = [...new Set(plan.prompts.map((prompt) => prompt.genre))];
  const totalMinutes = Math.round(plan.prompts.reduce((sum, prompt) => sum + prompt.duration, 0) / 60);

  async function copyKit() {
    if (!promptKit) return;
    await navigator.clipboard.writeText(JSON.stringify(promptKit, null, 2));
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  }

  async function generate() {
    setError("");
    try {
      const prompts = parsePromptPlan(promptJson);
      await genTracks.mutateAsync({ prompts, provider });
    } catch (cause) {
      setError((cause as Error).message);
    }
  }

  return <div>
    <SectionTitle
      title="Generate from your prompts"
      subtitle="Bring the music direction from GPT, paste the JSON plan, and send it straight to Stable Audio."
      actions={<Link className="btn-ghost" to="/library">Review tracks</Link>}
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
              Copy the live JSON contract plus your liked and disliked prompt history, then ask GPT to create the next batch.
            </p>
            {promptKit && <div className="mt-2 flex flex-wrap gap-2">
              <Badge tone="green">{promptKit.taste_profile.liked_examples.length} liked</Badge>
              <Badge tone="red">{promptKit.taste_profile.disliked_examples.length} disliked</Badge>
              <Badge tone="violet">genre-aware schema</Badge>
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
      {showKit && <textarea className="input mt-4 h-80 font-mono text-xs" readOnly value={promptKit ? JSON.stringify(promptKit, null, 2) : "Loading…"} />}
    </Card>

    <Card>
      <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h3 className="font-medium text-slate-100">Prompt plan JSON</h3>
          <p className="text-xs text-slate-500">Required fields: title, genre, prompt, duration. Your draft is saved in this browser.</p>
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
        placeholder={'[\n  {\n    "title": "Glass Transit",\n    "genre": "ambient techno",\n    "prompt": "Instrumental…",\n    "duration": 180\n  }\n]'}
      />
      <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2 text-xs">
          {plan.prompts.length > 0 && <>
            <Badge tone="green">{plan.prompts.length} track{plan.prompts.length === 1 ? "" : "s"}</Badge>
            <Badge>{totalMinutes} min total</Badge>
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
