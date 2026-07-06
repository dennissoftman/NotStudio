import { Link } from "react-router-dom";
import { useHealth, useHistory, useJobs, useStreams } from "../api/hooks";
import { Badge, Card, SectionTitle, fmtDuration } from "../components/ui";
import type { ReactNode } from "react";

function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <Card>
      <div className="text-xs uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-slate-100">{value}</div>
      {hint && <div className="mt-1 text-xs text-slate-500">{hint}</div>}
    </Card>
  );
}

export default function Dashboard() {
  const { data: health } = useHealth();
  const { data: streams } = useStreams();
  const { data: jobs } = useJobs();
  const { data: history } = useHistory();

  const live = streams?.filter((s) => s.status === "live").length ?? 0;
  const activeJobs =
    jobs?.filter((j) => ["queued", "in_progress"].includes(j.status)).length ?? 0;
  const totalDuration = history?.reduce((a, h) => a + h.duration_seconds, 0) ?? 0;
  const availableProviders = health?.providers.filter((p) => p.available).length ?? 0;

  const empty =
    (streams?.length ?? 0) === 0 &&
    (history?.length ?? 0) === 0 &&
    (jobs?.length ?? 0) === 0;

  return (
    <div>
      <SectionTitle
        title="Dashboard"
        subtitle="Neural Radio — generate, orchestrate and stream AI radio."
      />

      {!health?.queue && (
        <Card className="mb-4 border-amber-900/50 bg-amber-950/20">
          <div className="text-sm text-amber-200">
            ⚠ Task queue offline — start Redis to enable job generation:
            <code className="ml-2 rounded bg-ink-950 px-2 py-0.5 font-mono text-xs">
              docker compose up -d redis
            </code>{" "}
            then run the arq worker.
          </div>
        </Card>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label="Streams"
          value={streams?.length ?? 0}
          hint={`${live} live now`}
        />
        <Stat label="Active jobs" value={activeJobs} hint="queued + running" />
        <Stat
          label="History"
          value={history?.length ?? 0}
          hint={`${fmtDuration(totalDuration)} generated`}
        />
        <Stat
          label="Providers"
          value={availableProviders}
          hint={health?.providers.map((p) => p.provider).join(", ")}
        />
      </div>

      {empty && (
        <Card className="mt-6">
          <h3 className="mb-2 font-semibold text-slate-100">Get started</h3>
          <ol className="list-inside list-decimal space-y-1 text-sm text-slate-400">
            <li>
              Create a <Link className="text-accent-soft" to="/backends">mock backend</Link>{" "}
              (music + speech) — no models needed.
            </li>
            <li>
              Build a <Link className="text-accent-soft" to="/programs">program</Link>: a music
              bed with news / info / ad inserts.
            </li>
            <li>
              Create a <Link className="text-accent-soft" to="/streams">stream</Link> and press
              <b> Go live</b> — it buffers ~18 min ahead and plays.
            </li>
          </ol>
        </Card>
      )}

      {(streams?.length ?? 0) > 0 && (
        <div className="mt-6">
          <h3 className="mb-2 text-sm font-semibold text-slate-300">Streams</h3>
          <div className="grid gap-2">
            {streams?.map((s) => (
              <Link
                key={s.id}
                to="/streams"
                className="card flex items-center justify-between px-4 py-3 hover:border-ink-600"
              >
                <span className="font-medium text-slate-100">{s.name}</span>
                <Badge tone={s.status === "live" ? "green" : "gray"}>{s.status}</Badge>
              </Link>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
