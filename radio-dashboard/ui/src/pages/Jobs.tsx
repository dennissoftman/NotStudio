import { useState } from "react";
import {
  useCancelJob,
  useJobs,
  usePrograms,
  useStreams,
  useSubmitJob,
} from "../api/hooks";
import {
  Card,
  Empty,
  Field,
  Modal,
  Progress,
  SectionTitle,
  StatusBadge,
  fmtTime,
} from "../components/ui";

const ACTIVE = new Set(["queued", "in_progress", "deferred"]);

export default function Jobs() {
  const { data: jobs } = useJobs();
  const { data: streams } = useStreams();
  const cancel = useCancelJob();
  const [open, setOpen] = useState(false);

  const streamName = (id: string | null) =>
    streams?.find((s) => s.id === id)?.name ?? (id ? id.slice(0, 8) : "—");

  return (
    <div>
      <SectionTitle
        title="Jobs"
        subtitle="Submit, track and cancel generation tasks (feature #1)."
        actions={
          <button className="btn-primary" onClick={() => setOpen(true)}>
            + Submit job
          </button>
        }
      />
      <div className="grid gap-2">
        {jobs?.length === 0 && <Empty>No jobs yet.</Empty>}
        {jobs?.map((j) => (
          <Card key={j.id} className="!py-3">
            <div className="flex items-start justify-between">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs text-slate-500">{j.id.slice(0, 8)}</span>
                  <span className="text-sm text-slate-300">{j.type}</span>
                  <StatusBadge status={j.status} />
                  <span className="text-xs text-slate-500">→ {streamName(j.stream_id)}</span>
                </div>
                {j.status === "in_progress" && (
                  <div className="mt-2 w-72 max-w-full">
                    <Progress value={j.progress} />
                    <div className="mt-1 text-xs text-slate-500">
                      {Math.round(j.progress * 100)}% · {j.message}
                    </div>
                  </div>
                )}
                {j.error && <div className="mt-1 text-xs text-red-400">{j.error}</div>}
                {j.result?.duration_seconds != null && (
                  <div className="mt-1 text-xs text-slate-500">
                    Rendered {Math.round(Number(j.result.duration_seconds))}s ·{" "}
                    {String(j.result.music_tracks ?? "?")} tracks ·{" "}
                    {String(j.result.inserts ?? "?")} inserts
                  </div>
                )}
              </div>
              <div className="flex flex-col items-end gap-1">
                <span className="text-xs text-slate-600">{fmtTime(j.created_at)}</span>
                {ACTIVE.has(j.status) && (
                  <button className="btn-danger !py-1 !text-xs" onClick={() => cancel.mutate(j.id)}>
                    Cancel
                  </button>
                )}
              </div>
            </div>
          </Card>
        ))}
      </div>
      {open && <SubmitModal onClose={() => setOpen(false)} />}
    </div>
  );
}

function SubmitModal({ onClose }: { onClose: () => void }) {
  const { data: streams } = useStreams();
  const { data: programs } = usePrograms();
  const submit = useSubmitJob();
  const [streamId, setStreamId] = useState("");
  const [programId, setProgramId] = useState("");
  const [target, setTarget] = useState(120);
  const [error, setError] = useState("");

  async function go() {
    setError("");
    if (!streamId && !programId) {
      setError("Pick a stream or a program");
      return;
    }
    try {
      await submit.mutateAsync({
        type: "batch",
        stream_id: streamId || null,
        program_id: programId || null,
        params: { target_seconds: Number(target) },
      });
      onClose();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <Modal open onClose={onClose} title="Submit generation job">
      <div className="space-y-3">
        <Field label="Stream (buffers into its playout queue)">
          <select
            className="input"
            value={streamId}
            onChange={(e) => setStreamId(e.target.value)}
          >
            <option value="">(none — one-off render)</option>
            {streams?.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="…or a program (one-off render to history)">
          <select
            className="input"
            value={programId}
            onChange={(e) => setProgramId(e.target.value)}
          >
            <option value="">(none)</option>
            {programs?.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Target seconds">
          <input
            type="number"
            className="input"
            value={target}
            onChange={(e) => setTarget(+e.target.value)}
          />
        </Field>
        <p className="text-xs text-slate-500">
          Tip: use a short target (e.g. 60–120s) with the mock backend for a quick demo.
        </p>
        {error && <p className="text-sm text-red-400">{error}</p>}
        <div className="flex justify-end gap-2 pt-1">
          <button className="btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button className="btn-primary" onClick={go}>
            Submit
          </button>
        </div>
      </div>
    </Modal>
  );
}
