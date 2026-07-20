import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import type { GenerationRun, PromptPlan, PromptSpec } from "../api/client";
import {
  useCreateGenerationRun,
  useGenerateGenerationRun,
  useGenerationRuns,
  useJobs,
  useReplanGenerationRun,
  useUpdateGenerationPlan,
  useUploadStyleReference,
} from "../api/hooks";
import { SparklesIcon } from "../components/icons";
import {
  Badge,
  Card,
  Progress,
  SectionTitle,
  StatusBadge,
} from "../components/ui";

function stored(key: string, fallback = "") {
  try {
    return localStorage.getItem(key) || fallback;
  } catch {
    return fallback;
  }
}

function parsePromptPlan(value: string): PromptPlan {
  const source = JSON.parse(value) as Record<string, unknown>;
  if (!source || typeof source !== "object" || Array.isArray(source)) {
    throw new Error("Plan must be a JSON object");
  }
  if (
    !Array.isArray(source.prompts) ||
    source.prompts.length < 1 ||
    source.prompts.length > 20
  ) {
    throw new Error("Plan must contain 1–20 tracks");
  }
  const prompts = source.prompts.map((item, index) => {
    if (!item || typeof item !== "object" || Array.isArray(item))
      throw new Error(`Track ${index + 1} is invalid`);
    const track = item as Record<string, unknown>;
    for (const key of ["title", "genre", "prompt"] as const) {
      if (typeof track[key] !== "string" || !track[key].trim())
        throw new Error(`Track ${index + 1} needs ${key}`);
    }
    const duration = Number(track.duration);
    if (!Number.isFinite(duration) || duration < 15 || duration > 240)
      throw new Error(`Track ${index + 1} duration must be 15–240 seconds`);
    return { ...track, duration } as unknown as PromptSpec;
  });
  return { ...source, prompts } as unknown as PromptPlan;
}

function stageLabel(run: GenerationRun) {
  const labels: Record<string, string> = {
    planning: "Creating the album plan",
    awaiting_review: "Plan ready for review",
    generating_tracks: "Generating tracks with ACE-Step",
    generating_covers: "Generating album and track covers",
    completed: "Album generation complete",
    completed_with_errors: "Complete with artwork warnings",
    failed: "Generation failed",
    cancelled: "Generation cancelled",
  };
  return labels[run.stage] ?? run.stage.replaceAll("_", " ");
}

export default function Generate() {
  const [brief, setBrief] = useState(() => stored("not-studio:album-brief"));
  const [artworkGuidance, setArtworkGuidance] = useState(() =>
    stored("not-studio:artwork-guidance"),
  );
  const [styleFile, setStyleFile] = useState<File | null>(null);
  const [stylePreview, setStylePreview] = useState("");
  const [outputSize, setOutputSize] = useState(2048);
  const [autoStart, setAutoStart] = useState(false);
  const [activeRunId, setActiveRunId] = useState("");
  const [planJson, setPlanJson] = useState("");
  const [showJson, setShowJson] = useState(false);
  const [error, setError] = useState("");

  const { data: runs } = useGenerationRuns();
  const { data: jobs } = useJobs();
  const createRun = useCreateGenerationRun();
  const uploadReference = useUploadStyleReference();
  const updatePlan = useUpdateGenerationPlan();
  const replan = useReplanGenerationRun();
  const generate = useGenerateGenerationRun();

  const activeRun = useMemo(
    () => runs?.find((run) => run.id === activeRunId) ?? runs?.[0],
    [activeRunId, runs],
  );
  const activeJob = jobs?.find(
    (job) =>
      job.id === activeRun?.generation_job_id ||
      job.id === activeRun?.plan_job_id,
  );

  useEffect(() => {
    try {
      localStorage.setItem("not-studio:album-brief", brief);
      localStorage.setItem("not-studio:artwork-guidance", artworkGuidance);
    } catch {
      /* ignore */
    }
  }, [artworkGuidance, brief]);

  useEffect(() => {
    if (activeRun?.plan) setPlanJson(JSON.stringify(activeRun.plan, null, 2));
  }, [activeRun?.id, activeRun?.updated_at]);

  useEffect(() => {
    if (!styleFile) {
      setStylePreview("");
      return;
    }
    const url = URL.createObjectURL(styleFile);
    setStylePreview(url);
    return () => URL.revokeObjectURL(url);
  }, [styleFile]);

  async function createPlan() {
    setError("");
    if (brief.trim().length < 10) {
      setError("Describe the album in at least a short sentence.");
      return;
    }
    try {
      const reference = styleFile
        ? await uploadReference.mutateAsync(styleFile)
        : null;
      const run = await createRun.mutateAsync({
        brief: brief.trim(),
        artwork_guidance: artworkGuidance.trim(),
        style_reference_id: reference?.id ?? null,
        cover_output_size: outputSize,
        auto_start: autoStart,
        duration_default: 180,
      });
      setActiveRunId(run.id);
    } catch (cause) {
      setError((cause as Error).message);
    }
  }

  async function savePlan() {
    if (!activeRun) return;
    setError("");
    try {
      const plan = parsePromptPlan(planJson);
      await updatePlan.mutateAsync({ id: activeRun.id, plan });
    } catch (cause) {
      setError((cause as Error).message);
    }
  }

  async function startGeneration() {
    if (!activeRun) return;
    setError("");
    try {
      const plan = parsePromptPlan(planJson);
      await updatePlan.mutateAsync({ id: activeRun.id, plan });
      await generate.mutateAsync(activeRun.id);
    } catch (cause) {
      setError((cause as Error).message);
    }
  }

  const pending = createRun.isPending || uploadReference.isPending;
  const plan = (() => {
    try {
      return planJson ? parsePromptPlan(planJson) : null;
    } catch {
      return null;
    }
  })();

  return (
    <div className="space-y-6">
      <SectionTitle
        title="Create an album"
        subtitle="Describe the music and its story. A local planner turns it into tracks, then ACE-Step and FLUX generate the album."
        actions={
          <Link className="btn-ghost" to="/library">
            Open library
          </Link>
        }
      />

      <Card className="overflow-hidden !border-accent/30 bg-gradient-to-br from-accent/10 via-ink-900 to-ink-900">
        <label className="block">
          <span className="label">Album brief</span>
          <textarea
            className="input min-h-44 resize-y text-base leading-7"
            value={brief}
            maxLength={8000}
            placeholder="A seven-track ambient techno album about a city slowly becoming empty. It begins crowded and anxious, becomes spacious, and ends with a warm sunrise. Analog synths, distant railway sounds, no vocals."
            onChange={(event) => setBrief(event.target.value)}
          />
          <span className="mt-1 block text-xs text-slate-500">
            Include track count, mood, musical direction, and any story arc in
            ordinary language.
          </span>
        </label>

        <div className="mt-4 grid gap-4 md:grid-cols-[1fr_14rem]">
          <label>
            <span className="label">Artwork guidance</span>
            <textarea
              className="input min-h-28 resize-y"
              value={artworkGuidance}
              placeholder="Minimal cinematic abstraction, restrained palette, no typography…"
              onChange={(event) => setArtworkGuidance(event.target.value)}
            />
          </label>
          <div>
            <span className="label">Visual style reference</span>
            <label className="flex h-28 cursor-pointer items-center justify-center overflow-hidden rounded-lg border border-dashed border-ink-600 bg-ink-950 text-center text-xs text-slate-500 hover:border-accent/60">
              {stylePreview ? (
                <img
                  className="h-full w-full object-cover"
                  src={stylePreview}
                  alt="Style reference preview"
                />
              ) : (
                "Upload PNG, JPEG, or WebP"
              )}
              <input
                className="hidden"
                type="file"
                accept="image/png,image/jpeg,image/webp"
                onChange={(event) =>
                  setStyleFile(event.target.files?.[0] ?? null)
                }
              />
            </label>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-end justify-between gap-4">
          <div className="flex items-end gap-3">
            <label>
              <span className="label">Cover size</span>
              <select
                className="input w-32"
                value={outputSize}
                onChange={(event) => setOutputSize(Number(event.target.value))}
              >
                <option value={1024}>1024 px</option>
                <option value={2048}>2048 px</option>
                <option value={4096}>4096 px</option>
              </select>
            </label>
            <label className="mb-2 flex items-center gap-2 text-sm text-slate-400">
              <input
                type="checkbox"
                checked={autoStart}
                onChange={(event) => setAutoStart(event.target.checked)}
              />
              Generate automatically after planning
            </label>
          </div>
          <button
            className="btn-primary"
            disabled={pending || brief.trim().length < 10}
            onClick={createPlan}
          >
            <SparklesIcon className="h-4 w-4" />{" "}
            {pending ? "Submitting…" : "Create album plan"}
          </button>
        </div>
        {error && <div className="mt-3 text-sm text-red-400">{error}</div>}
      </Card>

      {activeRun && (
        <Card>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="font-medium text-slate-100">
                  {activeRun.plan?.album_title || "Album run"}
                </h3>
                <Badge
                  tone={activeRun.status === "completed" ? "green" : "violet"}
                >
                  {stageLabel(activeRun)}
                </Badge>
              </div>
              {activeRun.plan?.summary && (
                <p className="mt-1 text-sm text-slate-400">
                  {activeRun.plan.summary}
                </p>
              )}
            </div>
            {activeJob && <StatusBadge status={activeJob.status} />}
          </div>
          {activeJob &&
            (activeJob.status === "queued" ||
              activeJob.status === "in_progress") && (
              <div className="mt-4">
                <div className="mb-1 flex justify-between text-xs text-slate-500">
                  <span>{activeJob.message || "Queued"}</span>
                  <span>{Math.round(activeJob.progress * 100)}%</span>
                </div>
                <Progress value={activeJob.progress} />
              </div>
            )}
          {activeRun.error && (
            <div className="mt-3 text-sm text-red-400">{activeRun.error}</div>
          )}

          {activeRun.status === "awaiting_review" && activeRun.plan && (
            <div className="mt-5">
              <div className="mb-3 flex flex-wrap gap-2">
                <Badge tone="green">
                  {activeRun.plan.prompts.length} tracks
                </Badge>
                <Badge>
                  {Math.round(
                    activeRun.plan.prompts.reduce(
                      (sum, item) => sum + item.duration,
                      0,
                    ) / 60,
                  )}{" "}
                  min
                </Badge>
                <Badge tone="amber">album + track covers</Badge>
              </div>
              <div className="grid gap-2 md:grid-cols-2">
                {activeRun.plan.prompts.map((track, index) => (
                  <div
                    key={`${track.title}-${index}`}
                    className="rounded-lg border border-ink-700 bg-ink-950/50 p-3"
                  >
                    <div className="flex items-start gap-2">
                      <span className="text-xs font-semibold text-accent-soft">
                        {index + 1}
                      </span>
                      <div>
                        <div className="text-sm font-medium text-slate-200">
                          {track.title}
                        </div>
                        <div className="text-xs text-slate-500">
                          {track.genre} · {Math.round(track.duration / 60)} min
                        </div>
                      </div>
                    </div>
                    {track.notes && (
                      <p className="mt-2 text-xs text-slate-500">
                        {track.notes}
                      </p>
                    )}
                  </div>
                ))}
              </div>
              <button
                className="btn-ghost mt-4 !text-xs"
                onClick={() => setShowJson((value) => !value)}
              >
                {showJson ? "Hide advanced JSON" : "Edit advanced JSON"}
              </button>
              {showJson && (
                <textarea
                  className="input mt-2 h-[34rem] resize-y font-mono text-xs leading-5"
                  value={planJson}
                  onChange={(event) => setPlanJson(event.target.value)}
                  spellCheck={false}
                />
              )}
              <div className="mt-4 flex flex-wrap justify-end gap-2">
                <button
                  className="btn-ghost"
                  disabled={replan.isPending}
                  onClick={() => replan.mutate(activeRun.id)}
                >
                  Regenerate plan
                </button>
                {showJson && (
                  <button
                    className="btn-ghost"
                    disabled={!plan || updatePlan.isPending}
                    onClick={savePlan}
                  >
                    Save edits
                  </button>
                )}
                <button
                  className="btn-primary"
                  disabled={!plan || generate.isPending}
                  onClick={startGeneration}
                >
                  <SparklesIcon className="h-4 w-4" /> Generate tracks + covers
                </button>
              </div>
            </div>
          )}

          {(activeRun.status === "completed" ||
            activeRun.status === "completed_with_errors") && (
            <div className="mt-4 flex gap-2">
              <Link className="btn-primary" to="/library">
                Review tracks and covers
              </Link>
              <Link className="btn-ghost" to="/album">
                Assemble album
              </Link>
            </div>
          )}
        </Card>
      )}

      {(runs?.length ?? 0) > 1 && (
        <div>
          <h3 className="mb-2 text-sm font-semibold text-slate-300">
            Recent album runs
          </h3>
          <div className="grid gap-2">
            {runs!.slice(0, 8).map((run) => (
              <button
                key={run.id}
                className="rounded-lg border border-ink-700 bg-ink-900 px-3 py-2 text-left hover:border-ink-600"
                onClick={() => setActiveRunId(run.id)}
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="truncate text-sm text-slate-200">
                    {run.plan?.album_title || run.brief}
                  </span>
                  <span className="shrink-0 text-xs text-slate-500">
                    {stageLabel(run)}
                  </span>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
