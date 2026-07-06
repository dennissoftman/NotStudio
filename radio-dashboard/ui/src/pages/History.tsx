import { api } from "../api/client";
import { useDeleteHistory, useHistory, useStreams } from "../api/hooks";
import {
  Badge,
  Card,
  Empty,
  SectionTitle,
  fmtBytes,
  fmtDuration,
  fmtTime,
} from "../components/ui";

export default function History() {
  const { data: items } = useHistory();
  const { data: streams } = useStreams();
  const del = useDeleteHistory();

  const streamName = (id: string | null) =>
    streams?.find((s) => s.id === id)?.name ?? "one-off";

  return (
    <div>
      <SectionTitle
        title="History"
        subtitle="Every generated batch is saved with its WebVTT timeline (feature #4)."
      />
      <div className="grid gap-3">
        {items?.length === 0 && <Empty>Nothing generated yet.</Empty>}
        {items?.map((h) => (
          <Card key={h.id}>
            <div className="flex items-start justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-medium text-slate-100">{h.title}</span>
                  <Badge tone="violet">{h.kind}</Badge>
                  <span className="text-xs text-slate-500">{streamName(h.stream_id)}</span>
                </div>
                <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
                  <span>⏱ {fmtDuration(h.duration_seconds)}</span>
                  <span>{fmtBytes(h.size_bytes)}</span>
                  <span>{h.sample_rate} Hz · {h.channels}ch</span>
                  {h.lufs != null && <span>{h.lufs.toFixed(1)} LUFS</span>}
                  {h.meta?.music_tracks != null && (
                    <span>
                      {String(h.meta.music_tracks)} tracks · {String(h.meta.inserts)} inserts
                    </span>
                  )}
                  <span>{fmtTime(h.created_at)}</span>
                </div>
              </div>
              <div className="flex gap-2">
                {h.vtt_path && (
                  <a
                    className="btn-ghost !text-xs"
                    href={api.timelineUrl(h.id)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Timeline
                  </a>
                )}
                <a className="btn-ghost !text-xs" href={api.audioUrl(h.id)} download>
                  Download
                </a>
                <button className="btn-danger !text-xs" onClick={() => del.mutate(h.id)}>
                  Delete
                </button>
              </div>
            </div>
            <audio className="mt-3 h-9 w-full" controls preload="none" src={api.audioUrl(h.id)} />
          </Card>
        ))}
      </div>
    </div>
  );
}
