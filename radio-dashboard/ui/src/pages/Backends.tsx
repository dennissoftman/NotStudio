import { useMemo, useState } from "react";
import type { BackendKind, Provider } from "../api/client";
import {
  useBackends,
  useCreateBackend,
  useDeleteBackend,
  useProviders,
  useUpdateBackend,
} from "../api/hooks";
import { Badge, Card, Empty, Field, Modal, SectionTitle } from "../components/ui";

export default function Backends() {
  const { data: backends } = useBackends();
  const { data: providers } = useProviders();
  const del = useDeleteBackend();
  const toggle = useUpdateBackend();
  const [open, setOpen] = useState(false);

  return (
    <div>
      <SectionTitle
        title="Backends"
        subtitle="Audio + TTS generation engines (feature #2). The mock backend needs no models."
        actions={
          <button className="btn-primary" onClick={() => setOpen(true)}>
            + New backend
          </button>
        }
      />

      <div className="mb-6 grid gap-3 sm:grid-cols-3">
        {providers?.map((p) => (
          <Card key={p.provider} className="!p-3">
            <div className="flex items-center justify-between">
              <span className="font-medium capitalize text-slate-200">
                {p.provider.replace("_", " ")}
              </span>
              <Badge tone={p.available ? "green" : "red"}>
                {p.available ? "available" : "unavailable"}
              </Badge>
            </div>
            <div className="mt-1 text-xs text-slate-500">{p.kinds.join(", ")}</div>
            <p className="mt-2 text-xs text-slate-400">{p.detail}</p>
          </Card>
        ))}
      </div>

      <div className="grid gap-3">
        {backends?.length === 0 && (
          <Empty>No backends yet. Create a mock backend to start instantly.</Empty>
        )}
        {backends?.map((b) => (
          <Card key={b.id} className="flex items-center justify-between !py-3">
            <div>
              <div className="flex items-center gap-2">
                <span className="font-medium text-slate-100">{b.name}</span>
                <Badge tone={b.kind === "music" ? "violet" : "blue"}>{b.kind}</Badge>
                <Badge>{b.provider}</Badge>
                {!b.enabled && <Badge tone="amber">disabled</Badge>}
              </div>
              <div className="mt-1 font-mono text-xs text-slate-500">
                {JSON.stringify(b.config)}
              </div>
            </div>
            <div className="flex gap-2">
              <button
                className="btn-ghost"
                onClick={() =>
                  toggle.mutate({ id: b.id, data: { enabled: !b.enabled } })
                }
              >
                {b.enabled ? "Disable" : "Enable"}
              </button>
              <button className="btn-danger" onClick={() => del.mutate(b.id)}>
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
  const { data: providers } = useProviders();
  const create = useCreateBackend();
  const [name, setName] = useState("");
  const [kind, setKind] = useState<BackendKind>("music");
  const [provider, setProvider] = useState<Provider>("mock");
  const [configText, setConfigText] = useState("{}");
  const [error, setError] = useState("");

  const eligible = useMemo(
    () => providers?.filter((p) => p.kinds.includes(kind)) ?? [],
    [providers, kind]
  );

  function pickProvider(p: Provider) {
    setProvider(p);
    const info = providers?.find((x) => x.provider === p);
    setConfigText(JSON.stringify(info?.default_config ?? {}, null, 2));
  }

  async function submit() {
    setError("");
    let config: Record<string, unknown>;
    try {
      config = JSON.parse(configText || "{}");
    } catch {
      setError("Config must be valid JSON");
      return;
    }
    try {
      await create.mutateAsync({ name, kind, provider, config });
      onClose();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <Modal open onClose={onClose} title="New backend">
      <div className="space-y-3">
        <Field label="Name">
          <input
            className="input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Kokoro voice"
          />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Kind">
            <select
              className="input"
              value={kind}
              onChange={(e) => setKind(e.target.value as BackendKind)}
            >
              <option value="music">music</option>
              <option value="speech">speech</option>
            </select>
          </Field>
          <Field label="Provider">
            <select
              className="input"
              value={provider}
              onChange={(e) => pickProvider(e.target.value as Provider)}
            >
              {eligible.map((p) => (
                <option key={p.provider} value={p.provider} disabled={!p.available}>
                  {p.provider} {p.available ? "" : "(unavailable)"}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <Field label="Config (JSON)">
          <textarea
            className="input font-mono h-28"
            value={configText}
            onChange={(e) => setConfigText(e.target.value)}
          />
        </Field>
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
