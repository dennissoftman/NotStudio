import { useState } from "react";
import { Link } from "react-router-dom";
import { useGenerateTracks, useHealth, useJobs } from "../api/hooks";
import { Card, Progress, SectionTitle, StatusBadge } from "../components/ui";

const EXAMPLE = JSON.stringify(
  [
    { title: "Neon Drift", prompt: "warm analog synthwave, instrumental, 90 bpm, lush pads, driving bassline", duration: 180 },
    { title: "Rain on Glass", prompt: "lofi hip hop, instrumental, mellow rhodes, vinyl crackle, soft drums, 75 bpm", duration: 180 },
    { title: "Deep Current", prompt: "deep house, instrumental, hypnotic groove, warm sub bass, 122 bpm", duration: 210 },
  ],
  null,
  2,
);

export default function Generate() {
  const [text, setText] = useState(EXAMPLE);
  const [provider, setProvider] = useState<"stable_audio" | "mock">("stable_audio");
  const [error, setError] = useState("");
  const gen = useGenerateTracks();
  const { data: health } = useHealth();
  const { data: jobs } = useJobs();
  const genJobs = (jobs ?? []).filter((j) => j.type === "generate_tracks").slice(0, 6);

  async function submit() {
    setError("");
    let prompts: unknown;
    try {
      prompts = JSON.parse(text);
      if (!Array.isArray(prompts) || prompts.length === 0)
        throw new Error("expected a non-empty JSON array");
    } catch (e) {
      setError("Invalid prompts JSON: " + (e as Error).message);
      return;
    }
    try {
      await gen.mutateAsync({ prompts, provider });
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div>
      <SectionTitle
        title="Generate tracks"
        subtitle="Paste a list of prompts — each becomes a track in your Library."
        actions={
          <Link className="btn-ghost" to="/library">
            Open Library →
          </Link>
        }
      />

      <Card>
        <label className="label">Prompts — JSON array of {"{ title, prompt, duration }"}</label>
        <textarea
          className="input h-64 font-mono"
          value={text}
          onChange={(e) => setText(e.target.value)}
          spellCheck={false}
        />
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <select
            className="input w-auto"
            value={provider}
            onChange={(e) => setProvider(e.target.value as "stable_audio" | "mock")}
          >
            <option value="stable_audio">Stable Audio 3 — local</option>
            <option value="mock">Mock — instant, for testing</option>
          </select>
          <button className="btn-primary" disabled={gen.isPending || !health?.queue} onClick={submit}>
            {gen.isPending ? "Submitting…" : "Generate tracks"}
          </button>
          {!health?.queue && (
            <span className="text-sm text-amber-400">Worker/Redis offline — start them first.</span>
          )}
          {error && <span className="text-sm text-red-400">{error}</span>}
        </div>
        <p className="mt-2 text-xs text-slate-500">
          Stable Audio runs locally through the parent engine (medium model). First run downloads
          the model; the parent repo env must be synced (<code>uv sync</code> at the repo root).
        </p>
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
