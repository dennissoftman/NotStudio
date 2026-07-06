import { useState } from "react";
import type { InsertSpec, Program } from "../api/client";
import {
  useBackends,
  useCreateProgram,
  useDeleteProgram,
  usePrograms,
  useUpdateProgram,
} from "../api/hooks";
import { Badge, Card, Empty, Field, Modal, SectionTitle } from "../components/ui";

const INSERT_KINDS = ["news", "info", "ad", "station_id", "weather", "jingle"] as const;

interface FormState {
  name: string;
  description: string;
  music_backend_id: string;
  speech_backend_id: string;
  prompts: string;
  track_seconds: number;
  crossfade_seconds: number;
  target_lufs: number;
  inserts: InsertSpec[];
}

function emptyInsert(): InsertSpec {
  return {
    kind: "news",
    cadence_seconds: 600,
    texts: [],
    voice: "am_michael",
    ducking: true,
    bed_volume_db: -8,
    insert_volume_db: 0,
  };
}

function fromProgram(p?: Program): FormState {
  return {
    name: p?.name ?? "",
    description: p?.description ?? "",
    music_backend_id: p?.music_backend_id ?? "",
    speech_backend_id: p?.speech_backend_id ?? "",
    prompts: (p?.config.music.prompts ?? ["upbeat instrumental radio bed"]).join("\n"),
    track_seconds: p?.config.music.track_seconds ?? 210,
    crossfade_seconds: p?.config.crossfade_seconds ?? 4,
    target_lufs: p?.config.target_lufs ?? -16,
    inserts: p?.config.inserts ?? [emptyInsert()],
  };
}

export default function Programs() {
  const { data: programs } = usePrograms();
  const { data: backends } = useBackends();
  const del = useDeleteProgram();
  const [editing, setEditing] = useState<Program | "new" | null>(null);

  const backendName = (id: string | null) =>
    backends?.find((b) => b.id === id)?.name ?? "—";

  return (
    <div>
      <SectionTitle
        title="Programs"
        subtitle="Orchestration recipes: a music bed with news / info / ads / IDs woven in."
        actions={
          <button className="btn-primary" onClick={() => setEditing("new")}>
            + New program
          </button>
        }
      />

      <div className="grid gap-3">
        {programs?.length === 0 && <Empty>No programs yet.</Empty>}
        {programs?.map((p) => (
          <Card key={p.id} className="flex items-start justify-between">
            <div>
              <div className="flex items-center gap-2">
                <span className="font-medium text-slate-100">{p.name}</span>
                <Badge tone="violet">{p.config.inserts.length} inserts</Badge>
              </div>
              {p.description && (
                <p className="mt-1 text-sm text-slate-400">{p.description}</p>
              )}
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
                <span>🎵 music: {backendName(p.music_backend_id)}</span>
                <span>🎙 speech: {backendName(p.speech_backend_id)}</span>
                <span>{p.config.music.track_seconds}s tracks</span>
                <span>{p.config.target_lufs} LUFS</span>
              </div>
              <div className="mt-2 flex flex-wrap gap-1">
                {p.config.inserts.map((ins, i) => (
                  <Badge key={i} tone="blue">
                    {ins.kind} · {ins.cadence_seconds}s
                  </Badge>
                ))}
              </div>
            </div>
            <div className="flex gap-2">
              <button className="btn-ghost" onClick={() => setEditing(p)}>
                Edit
              </button>
              <button className="btn-danger" onClick={() => del.mutate(p.id)}>
                Delete
              </button>
            </div>
          </Card>
        ))}
      </div>

      {editing && (
        <ProgramModal
          program={editing === "new" ? undefined : editing}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  );
}

function ProgramModal({
  program,
  onClose,
}: {
  program?: Program;
  onClose: () => void;
}) {
  const { data: backends } = useBackends();
  const create = useCreateProgram();
  const update = useUpdateProgram();
  const [f, setF] = useState<FormState>(fromProgram(program));
  const [error, setError] = useState("");

  const music = backends?.filter((b) => b.kind === "music") ?? [];
  const speech = backends?.filter((b) => b.kind === "speech") ?? [];
  const set = (patch: Partial<FormState>) => setF({ ...f, ...patch });
  const setInsert = (i: number, patch: Partial<InsertSpec>) =>
    set({ inserts: f.inserts.map((x, j) => (j === i ? { ...x, ...patch } : x)) });

  async function submit() {
    setError("");
    const config = {
      target_lufs: Number(f.target_lufs),
      crossfade_seconds: Number(f.crossfade_seconds),
      music: {
        prompts: f.prompts.split("\n").map((s) => s.trim()).filter(Boolean),
        track_seconds: Number(f.track_seconds),
        crossfade_seconds: Number(f.crossfade_seconds),
      },
      inserts: f.inserts.map((ins) => ({
        ...ins,
        cadence_seconds: Number(ins.cadence_seconds),
        bed_volume_db: Number(ins.bed_volume_db),
        insert_volume_db: Number(ins.insert_volume_db),
        texts: (Array.isArray(ins.texts) ? ins.texts : [])
          .map((s) => s.trim())
          .filter(Boolean),
      })),
    };
    const payload = {
      name: f.name,
      description: f.description,
      music_backend_id: f.music_backend_id || null,
      speech_backend_id: f.speech_backend_id || null,
      config,
    };
    try {
      if (program) await update.mutateAsync({ id: program.id, data: payload });
      else await create.mutateAsync(payload);
      onClose();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <Modal open onClose={onClose} title={program ? "Edit program" : "New program"} wide>
      <div className="max-h-[70vh] space-y-4 overflow-y-auto pr-1">
        <div className="grid grid-cols-2 gap-3">
          <Field label="Name">
            <input className="input" value={f.name} onChange={(e) => set({ name: e.target.value })} />
          </Field>
          <Field label="Description">
            <input
              className="input"
              value={f.description}
              onChange={(e) => set({ description: e.target.value })}
            />
          </Field>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Music backend">
            <select
              className="input"
              value={f.music_backend_id}
              onChange={(e) => set({ music_backend_id: e.target.value })}
            >
              <option value="">(default mock)</option>
              {music.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name} ({b.provider})
                </option>
              ))}
            </select>
          </Field>
          <Field label="Speech backend">
            <select
              className="input"
              value={f.speech_backend_id}
              onChange={(e) => set({ speech_backend_id: e.target.value })}
            >
              <option value="">(default mock)</option>
              {speech.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name} ({b.provider})
                </option>
              ))}
            </select>
          </Field>
        </div>

        <Field label="Music prompts (one per line, cycled per track)">
          <textarea
            className="input h-20"
            value={f.prompts}
            onChange={(e) => set({ prompts: e.target.value })}
          />
        </Field>
        <div className="grid grid-cols-3 gap-3">
          <Field label="Track seconds">
            <input
              type="number"
              className="input"
              value={f.track_seconds}
              onChange={(e) => set({ track_seconds: +e.target.value })}
            />
          </Field>
          <Field label="Crossfade s">
            <input
              type="number"
              className="input"
              value={f.crossfade_seconds}
              onChange={(e) => set({ crossfade_seconds: +e.target.value })}
            />
          </Field>
          <Field label="Target LUFS">
            <input
              type="number"
              className="input"
              value={f.target_lufs}
              onChange={(e) => set({ target_lufs: +e.target.value })}
            />
          </Field>
        </div>

        <div>
          <div className="mb-2 flex items-center justify-between">
            <span className="label !mb-0">Inserts</span>
            <button
              className="btn-ghost !py-1 !text-xs"
              onClick={() => set({ inserts: [...f.inserts, emptyInsert()] })}
            >
              + Add insert
            </button>
          </div>
          <div className="space-y-3">
            {f.inserts.map((ins, i) => (
              <div key={i} className="rounded-lg border border-ink-700 p-3">
                <div className="grid grid-cols-4 gap-2">
                  <Field label="Kind">
                    <select
                      className="input"
                      value={ins.kind}
                      onChange={(e) => setInsert(i, { kind: e.target.value as InsertSpec["kind"] })}
                    >
                      {INSERT_KINDS.map((k) => (
                        <option key={k} value={k}>
                          {k}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <Field label="Cadence s">
                    <input
                      type="number"
                      className="input"
                      value={ins.cadence_seconds}
                      onChange={(e) => setInsert(i, { cadence_seconds: +e.target.value })}
                    />
                  </Field>
                  <Field label="Bed dB">
                    <input
                      type="number"
                      className="input"
                      value={ins.bed_volume_db}
                      onChange={(e) => setInsert(i, { bed_volume_db: +e.target.value })}
                    />
                  </Field>
                  <Field label="Voice">
                    <input
                      className="input"
                      value={ins.voice ?? ""}
                      onChange={(e) => setInsert(i, { voice: e.target.value })}
                    />
                  </Field>
                </div>
                <div className="mt-2">
                  <Field label="Scripts (one per line, cycled)">
                    <textarea
                      className="input h-16"
                      value={Array.isArray(ins.texts) ? ins.texts.join("\n") : ""}
                      onChange={(e) =>
                        setInsert(i, { texts: e.target.value.split("\n") as string[] })
                      }
                    />
                  </Field>
                </div>
                <div className="mt-2 flex items-center justify-between">
                  <label className="flex items-center gap-2 text-xs text-slate-400">
                    <input
                      type="checkbox"
                      checked={ins.ducking}
                      onChange={(e) => setInsert(i, { ducking: e.target.checked })}
                    />
                    Duck music under this insert
                  </label>
                  <button
                    className="text-xs text-red-400 hover:text-red-300"
                    onClick={() => set({ inserts: f.inserts.filter((_, j) => j !== i) })}
                  >
                    Remove
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>

        {error && <p className="text-sm text-red-400">{error}</p>}
      </div>
      <div className="mt-4 flex justify-end gap-2 border-t border-ink-800 pt-3">
        <button className="btn-ghost" onClick={onClose}>
          Cancel
        </button>
        <button className="btn-primary" disabled={!f.name} onClick={submit}>
          {program ? "Save" : "Create"}
        </button>
      </div>
    </Modal>
  );
}
