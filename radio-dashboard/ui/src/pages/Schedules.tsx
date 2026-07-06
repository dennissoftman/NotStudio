import { useState } from "react";
import type { Schedule } from "../api/client";
import {
  useCreateSchedule,
  useDeleteSchedule,
  usePrograms,
  useSchedules,
  useStreams,
  useUpdateSchedule,
} from "../api/hooks";
import { Badge, Card, Empty, Field, Modal, SectionTitle, fmtTime } from "../components/ui";

function triggerSummary(s: Schedule): string {
  if (s.trigger_type === "interval") return `every ${(s.trigger.seconds as number) ?? "?"}s`;
  if (s.trigger_type === "cron") return `cron "${(s.trigger.expr as string) ?? "* * * * *"}"`;
  if (s.trigger_type === "date") return `at ${(s.trigger.run_at as string) ?? "?"}`;
  return "";
}

export default function Schedules() {
  const { data: schedules } = useSchedules();
  const { data: streams } = useStreams();
  const del = useDeleteSchedule();
  const upd = useUpdateSchedule();
  const [open, setOpen] = useState(false);

  const streamName = (id: string | null) =>
    streams?.find((s) => s.id === id)?.name ?? "—";

  return (
    <div>
      <SectionTitle
        title="Schedules"
        subtitle="Recurring or one-shot triggers that submit jobs / control streams (feature #1)."
        actions={
          <button className="btn-primary" onClick={() => setOpen(true)}>
            + New schedule
          </button>
        }
      />
      <div className="grid gap-2">
        {schedules?.length === 0 && <Empty>No schedules yet.</Empty>}
        {schedules?.map((s) => (
          <Card key={s.id} className="flex items-center justify-between !py-3">
            <div>
              <div className="flex items-center gap-2">
                <span className="font-medium text-slate-100">{s.name}</span>
                <Badge tone="violet">{s.action.replace("_", " ")}</Badge>
                <Badge tone="blue">{triggerSummary(s)}</Badge>
                {!s.enabled && <Badge tone="amber">paused</Badge>}
              </div>
              <div className="mt-1 text-xs text-slate-500">
                Stream: {streamName(s.stream_id)} · last run {fmtTime(s.last_run_at)} · next{" "}
                {fmtTime(s.next_run_at)}
              </div>
            </div>
            <div className="flex gap-2">
              <button
                className="btn-ghost"
                onClick={() => upd.mutate({ id: s.id, data: { enabled: !s.enabled } })}
              >
                {s.enabled ? "Pause" : "Resume"}
              </button>
              <button className="btn-danger" onClick={() => del.mutate(s.id)}>
                Delete
              </button>
            </div>
          </Card>
        ))}
      </div>
      {open && <CreateModal onClose={() => setOpen(false)} />}
    </div>
  );
}

function CreateModal({ onClose }: { onClose: () => void }) {
  const { data: streams } = useStreams();
  const { data: programs } = usePrograms();
  const create = useCreateSchedule();
  const [name, setName] = useState("");
  const [action, setAction] = useState<Schedule["action"]>("render_batch");
  const [streamId, setStreamId] = useState("");
  const [programId, setProgramId] = useState("");
  const [triggerType, setTriggerType] = useState<Schedule["trigger_type"]>("interval");
  const [seconds, setSeconds] = useState(3600);
  const [cron, setCron] = useState("0 * * * *");
  const [runAt, setRunAt] = useState("");
  const [error, setError] = useState("");

  async function submit() {
    setError("");
    const trigger =
      triggerType === "interval"
        ? { seconds: Number(seconds) }
        : triggerType === "cron"
          ? { expr: cron }
          : { run_at: new Date(runAt).toISOString() };
    try {
      await create.mutateAsync({
        name,
        action,
        stream_id: streamId || null,
        program_id: programId || null,
        trigger_type: triggerType,
        trigger,
        enabled: true,
      });
      onClose();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <Modal open onClose={onClose} title="New schedule">
      <div className="space-y-3">
        <Field label="Name">
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Action">
            <select
              className="input"
              value={action}
              onChange={(e) => setAction(e.target.value as Schedule["action"])}
            >
              <option value="render_batch">render batch</option>
              <option value="start_stream">start stream</option>
              <option value="stop_stream">stop stream</option>
            </select>
          </Field>
          <Field label="Stream">
            <select
              className="input"
              value={streamId}
              onChange={(e) => setStreamId(e.target.value)}
            >
              <option value="">(none)</option>
              {streams?.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </Field>
        </div>
        {action === "render_batch" && (
          <Field label="Program (optional override)">
            <select
              className="input"
              value={programId}
              onChange={(e) => setProgramId(e.target.value)}
            >
              <option value="">(use stream's program)</option>
              {programs?.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </Field>
        )}
        <Field label="Trigger">
          <select
            className="input"
            value={triggerType}
            onChange={(e) => setTriggerType(e.target.value as Schedule["trigger_type"])}
          >
            <option value="interval">interval</option>
            <option value="cron">cron</option>
            <option value="date">one-shot date</option>
          </select>
        </Field>
        {triggerType === "interval" && (
          <Field label="Every N seconds">
            <input
              type="number"
              className="input"
              value={seconds}
              onChange={(e) => setSeconds(+e.target.value)}
            />
          </Field>
        )}
        {triggerType === "cron" && (
          <Field label="Cron (min hour dom mon dow, UTC)">
            <input className="input font-mono" value={cron} onChange={(e) => setCron(e.target.value)} />
          </Field>
        )}
        {triggerType === "date" && (
          <Field label="Run at">
            <input
              type="datetime-local"
              className="input"
              value={runAt}
              onChange={(e) => setRunAt(e.target.value)}
            />
          </Field>
        )}
        {error && <p className="text-sm text-red-400">{error}</p>}
        <div className="flex justify-end gap-2 pt-1">
          <button className="btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button className="btn-primary" disabled={!name} onClick={submit}>
            Create
          </button>
        </div>
      </div>
    </Modal>
  );
}
