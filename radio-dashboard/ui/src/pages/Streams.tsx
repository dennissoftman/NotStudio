import { useState } from "react";
import { api, type Stream } from "../api/client";
import {
  useBuffer,
  useCreateStream,
  useDeleteStream,
  usePrograms,
  useStreamAction,
  useStreams,
} from "../api/hooks";
import {
  Badge,
  Card,
  Empty,
  Field,
  Modal,
  Progress,
  SectionTitle,
  StatusBadge,
  fmtDuration,
} from "../components/ui";

export default function Streams() {
  const { data: streams } = useStreams();
  const [open, setOpen] = useState(false);

  return (
    <div>
      <SectionTitle
        title="Streams"
        subtitle="Live channels with a pre-allocated buffer (feature #4) and HTTP/HLS/Icecast output (feature #3)."
        actions={
          <button className="btn-primary" onClick={() => setOpen(true)}>
            + New stream
          </button>
        }
      />
      <div className="grid gap-3">
        {streams?.length === 0 && <Empty>No streams yet. Create one to go live.</Empty>}
        {streams?.map((s) => (
          <StreamCard key={s.id} stream={s} />
        ))}
      </div>
      {open && <CreateModal onClose={() => setOpen(false)} />}
    </div>
  );
}

function StreamCard({ stream }: { stream: Stream }) {
  const { data: programs } = usePrograms();
  const action = useStreamAction();
  const del = useDeleteStream();
  const live = stream.status === "live" || stream.status === "buffering";
  const { data: buf } = useBuffer(stream.id, live);
  const [listening, setListening] = useState(false);

  const program = programs?.find((p) => p.id === stream.program_id);
  const readyMin = (buf?.ready_seconds ?? 0) / 60;
  const targetMin = stream.buffer_min_seconds / 60;
  const pct = buf ? Math.min(1, buf.ready_seconds / stream.buffer_min_seconds) : 0;

  return (
    <Card>
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-base font-semibold text-slate-100">{stream.name}</span>
            <StatusBadge status={stream.status} />
            {buf?.generating && <Badge tone="blue">⚙ generating</Badge>}
          </div>
          <div className="mt-1 text-xs text-slate-500">
            {program ? `Program: ${program.name}` : "No program (default mock)"} ·{" "}
            {stream.sample_rate} Hz · {stream.channels}ch
          </div>
        </div>
        <div className="flex gap-2">
          {stream.status === "live" ? (
            <button
              className="btn-ghost"
              onClick={() => action.mutate({ id: stream.id, action: "stop" })}
            >
              ⏹ Stop
            </button>
          ) : (
            <button
              className="btn-primary"
              onClick={() => action.mutate({ id: stream.id, action: "start" })}
            >
              ▶ Go live
            </button>
          )}
          <button className="btn-danger" onClick={() => del.mutate(stream.id)}>
            Delete
          </button>
        </div>
      </div>

      {live && (
        <div className="mt-4">
          <div className="mb-1 flex items-center justify-between text-xs text-slate-400">
            <span>
              Buffer: {readyMin.toFixed(1)} min ready
              <span className="text-slate-600"> / {targetMin.toFixed(0)} min target</span>
            </span>
            <span>
              {buf?.segments_ready ?? 0} ready · {buf?.segments_total ?? 0} total segments
            </span>
          </div>
          <Progress value={pct} />
          {buf && buf.ready_seconds === 0 && (
            <p className="mt-1 text-xs text-amber-400">
              Buffering — waiting for the first batch to finish generating…
            </p>
          )}
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-3">
        {live && (
          <button className="btn-ghost" onClick={() => setListening((v) => !v)}>
            {listening ? "🔇 Stop listening" : "🔊 Listen"}
          </button>
        )}
        {listening && live && (
          <audio className="h-8" controls autoPlay src={api.liveUrl(stream.id)} />
        )}
        <a
          className="text-xs text-slate-500 hover:text-accent-soft"
          href={api.hlsUrl(stream.id)}
          target="_blank"
          rel="noreferrer"
        >
          HLS playlist ↗
        </a>
        <span className="text-xs text-slate-600">MP3: {api.liveUrl(stream.id)}</span>
        {stream.icecast?.enabled && (
          <Badge tone="violet">
            Icecast → {stream.icecast.host}:{stream.icecast.port}
            {stream.icecast.mount}
          </Badge>
        )}
      </div>

      <div className="mt-2 text-xs text-slate-600">
        Batches: {fmtDuration(stream.batch_target_seconds)} target ·{" "}
        {fmtDuration(stream.batch_max_seconds)} max
      </div>
    </Card>
  );
}

function CreateModal({ onClose }: { onClose: () => void }) {
  const { data: programs } = usePrograms();
  const create = useCreateStream();
  const [name, setName] = useState("");
  const [programId, setProgramId] = useState("");
  const [bufferMin, setBufferMin] = useState(900);
  const [batchTarget, setBatchTarget] = useState(1080);
  const [batchMax, setBatchMax] = useState(1200);
  const [ice, setIce] = useState(false);
  const [iceCfg, setIceCfg] = useState({
    host: "localhost",
    port: 8010,
    mount: "/neural.mp3",
    username: "source",
    password: "hackme",
    format: "mp3" as "mp3" | "ogg",
  });
  const [error, setError] = useState("");

  async function submit() {
    setError("");
    try {
      await create.mutateAsync({
        name,
        program_id: programId || null,
        buffer_min_seconds: Number(bufferMin),
        batch_target_seconds: Number(batchTarget),
        batch_max_seconds: Number(batchMax),
        icecast: ice ? { enabled: true, ...iceCfg } : null,
      });
      onClose();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <Modal open onClose={onClose} title="New stream" wide>
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <Field label="Name">
            <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="Program">
            <select
              className="input"
              value={programId}
              onChange={(e) => setProgramId(e.target.value)}
            >
              <option value="">(default mock program)</option>
              {programs?.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <div className="grid grid-cols-3 gap-3">
          <Field label="Buffer min (s)">
            <input
              type="number"
              className="input"
              value={bufferMin}
              onChange={(e) => setBufferMin(+e.target.value)}
            />
          </Field>
          <Field label="Batch target (s)">
            <input
              type="number"
              className="input"
              value={batchTarget}
              onChange={(e) => setBatchTarget(+e.target.value)}
            />
          </Field>
          <Field label="Batch max (s)">
            <input
              type="number"
              className="input"
              value={batchMax}
              onChange={(e) => setBatchMax(+e.target.value)}
            />
          </Field>
        </div>
        <p className="text-xs text-slate-500">
          Default keeps ≥ 15 min ready and generates ~18 min batches (feature #4).
        </p>

        <label className="flex items-center gap-2 text-sm text-slate-300">
          <input type="checkbox" checked={ice} onChange={(e) => setIce(e.target.checked)} />
          Publish to Icecast (feature #3)
        </label>
        {ice && (
          <div className="grid grid-cols-3 gap-2 rounded-lg border border-ink-700 p-3">
            <Field label="Host">
              <input
                className="input"
                value={iceCfg.host}
                onChange={(e) => setIceCfg({ ...iceCfg, host: e.target.value })}
              />
            </Field>
            <Field label="Port">
              <input
                type="number"
                className="input"
                value={iceCfg.port}
                onChange={(e) => setIceCfg({ ...iceCfg, port: +e.target.value })}
              />
            </Field>
            <Field label="Mount">
              <input
                className="input"
                value={iceCfg.mount}
                onChange={(e) => setIceCfg({ ...iceCfg, mount: e.target.value })}
              />
            </Field>
            <Field label="Username">
              <input
                className="input"
                value={iceCfg.username}
                onChange={(e) => setIceCfg({ ...iceCfg, username: e.target.value })}
              />
            </Field>
            <Field label="Password">
              <input
                className="input"
                value={iceCfg.password}
                onChange={(e) => setIceCfg({ ...iceCfg, password: e.target.value })}
              />
            </Field>
            <Field label="Format">
              <select
                className="input"
                value={iceCfg.format}
                onChange={(e) =>
                  setIceCfg({ ...iceCfg, format: e.target.value as "mp3" | "ogg" })
                }
              >
                <option value="mp3">mp3</option>
                <option value="ogg">ogg</option>
              </select>
            </Field>
          </div>
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
