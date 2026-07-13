import { useEffect, useRef, useState, type ReactNode } from "react";
import { PauseIcon, PlayIcon, XIcon } from "./icons";

export function cx(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}

export function Card({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return <div className={cx("card p-4", className)}>{children}</div>;
}

export function SectionTitle({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-4 flex items-end justify-between gap-4">
      <div>
        <h2 className="text-lg font-semibold text-slate-100">{title}</h2>
        {subtitle && <p className="text-sm text-slate-400">{subtitle}</p>}
      </div>
      {actions}
    </div>
  );
}

type Tone = "gray" | "green" | "amber" | "red" | "violet" | "blue";
const TONES: Record<Tone, string> = {
  gray: "bg-ink-700 text-slate-300",
  green: "bg-emerald-500/15 text-emerald-300",
  amber: "bg-amber-500/15 text-amber-300",
  red: "bg-red-500/15 text-red-300",
  violet: "bg-accent/20 text-accent-soft",
  blue: "bg-sky-500/15 text-sky-300",
};

export function Badge({ tone = "gray", children }: { tone?: Tone; children: ReactNode }) {
  return <span className={cx("badge", TONES[tone])}>{children}</span>;
}

export function StatusBadge({ status }: { status: string }) {
  const map: Record<string, Tone> = {
    live: "green",
    buffering: "amber",
    stopped: "gray",
    completed: "green",
    in_progress: "blue",
    queued: "amber",
    failed: "red",
    cancelled: "gray",
    deferred: "gray",
  };
  return <Badge tone={map[status] ?? "gray"}>{status.replace("_", " ")}</Badge>;
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      {children}
    </label>
  );
}

export function Progress({ value }: { value: number }) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-ink-700">
      <div
        className="h-full rounded-full bg-accent transition-all"
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-ink-700 p-8 text-center text-sm text-slate-500">
      {children}
    </div>
  );
}

const AUDIO_PLAY_EVENT = "not-studio:audio-play";

export function AudioPlayer({
  src,
  label,
  durationSeconds = 0,
}: {
  src: string;
  label: string;
  durationSeconds?: number;
}) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const idRef = useRef(Math.random().toString(36).slice(2));
  const [playing, setPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(durationSeconds);

  useEffect(() => {
    const pauseOther = (event: Event) => {
      if ((event as CustomEvent<string>).detail !== idRef.current) audioRef.current?.pause();
    };
    window.addEventListener(AUDIO_PLAY_EVENT, pauseOther);
    return () => window.removeEventListener(AUDIO_PLAY_EVENT, pauseOther);
  }, []);

  async function toggle() {
    const audio = audioRef.current;
    if (!audio) return;
    if (audio.paused) {
      window.dispatchEvent(new CustomEvent(AUDIO_PLAY_EVENT, { detail: idRef.current }));
      await audio.play();
    } else {
      audio.pause();
    }
  }

  const max = duration || 0;
  return (
    <div className="audio-player min-w-64 max-w-full">
      <audio
        ref={audioRef}
        preload="none"
        src={src}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
        onTimeUpdate={(event) => setCurrentTime(event.currentTarget.currentTime)}
        onLoadedMetadata={(event) => setDuration(event.currentTarget.duration)}
      />
      <button
        type="button"
        aria-label={`${playing ? "Pause" : "Play"} ${label}`}
        className="audio-play-button"
        onClick={toggle}
      >
        {playing ? <PauseIcon className="h-4 w-4" /> : <PlayIcon className="h-4 w-4 translate-x-px" />}
      </button>
      <span className="w-9 shrink-0 text-right text-[11px] tabular-nums text-slate-400">
        {fmtDuration(currentTime)}
      </span>
      <input
        aria-label={`Seek ${label}`}
        className="audio-range min-w-20 flex-1"
        type="range"
        min={0}
        max={max}
        step={0.1}
        value={Math.min(currentTime, max)}
        onChange={(event) => {
          const next = Number(event.target.value);
          if (audioRef.current) audioRef.current.currentTime = next;
          setCurrentTime(next);
        }}
      />
      <span className="w-9 shrink-0 text-[11px] tabular-nums text-slate-500">
        {fmtDuration(duration)}
      </span>
    </div>
  );
}

export function Modal({
  open,
  onClose,
  title,
  children,
  wide,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  wide?: boolean;
}) {
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-4 pt-16"
      onClick={onClose}
    >
      <div
        className={cx("card w-full p-5", wide ? "max-w-2xl" : "max-w-md")}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-base font-semibold text-slate-100">{title}</h3>
          <button className="icon-button" aria-label="Close" onClick={onClose}>
            <XIcon className="h-4 w-4" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function fmtDuration(seconds: number): string {
  if (!seconds || seconds < 0) return "0:00";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  if (m >= 60) {
    const h = Math.floor(m / 60);
    return `${h}h ${m % 60}m`;
  }
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function fmtBytes(bytes: number): string {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`;
}

export function fmtTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
  return d.toLocaleString();
}
