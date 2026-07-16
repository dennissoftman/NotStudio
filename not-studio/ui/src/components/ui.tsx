import { useEffect, useRef, useState, type ReactNode } from "react";
import { Howl } from "howler";
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

let activeAudioPlayer: Howl | null = null;

export function AudioPlayer({ src, label }: { src: string; label: string }) {
  const sound = useRef<Howl | null>(null);
  const progressTimer = useRef<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const [duration, setDuration] = useState(0);
  const [position, setPosition] = useState(0);
  const [error, setError] = useState("");

  useEffect(() => {
    setPlaying(false);
    setDuration(0);
    setPosition(0);
    setError("");

    let player: Howl;
    const stopProgressTimer = () => {
      if (progressTimer.current !== null) window.clearInterval(progressTimer.current);
      progressTimer.current = null;
    };
    const syncProgress = () => {
      const seek = player.seek();
      setPosition(typeof seek === "number" ? seek : 0);
      const nextDuration = player.duration();
      if (Number.isFinite(nextDuration) && nextDuration > 0) setDuration(nextDuration);
    };
    const startProgressTimer = () => {
      stopProgressTimer();
      syncProgress();
      progressTimer.current = window.setInterval(syncProgress, 100);
    };
    player = new Howl({
      src: [src],
      format: ["flac"],
      html5: true,
      preload: "metadata",
      onload: syncProgress,
      onplay: () => {
        setPlaying(true);
        startProgressTimer();
      },
      onpause: () => {
        setPlaying(false);
        syncProgress();
        stopProgressTimer();
      },
      onstop: () => {
        setPlaying(false);
        setPosition(0);
        stopProgressTimer();
      },
      onseek: syncProgress,
      onend: () => {
        setPlaying(false);
        setPosition(player.duration());
        stopProgressTimer();
        if (activeAudioPlayer === player) activeAudioPlayer = null;
      },
      onloaderror: (_id, cause) => setError(`Could not load audio (${String(cause)})`),
      onplayerror: (_id, cause) => {
        setPlaying(false);
        stopProgressTimer();
        setError(`Could not play audio (${String(cause)})`);
      },
    });
    sound.current = player;

    return () => {
      stopProgressTimer();
      if (activeAudioPlayer === player) activeAudioPlayer = null;
      player.unload();
      sound.current = null;
    };
  }, [src]);

  const toggle = () => {
    const player = sound.current;
    if (!player) return;
    if (player.playing()) {
      player.pause();
      return;
    }
    if (activeAudioPlayer && activeAudioPlayer !== player) activeAudioPlayer.pause();
    activeAudioPlayer = player;
    setError("");
    player.play();
  };

  const progressPercent = duration > 0 ? Math.min(100, (position / duration) * 100) : 0;

  return (
    <div className="audio-player" title={error || label}>
      <button
        type="button"
        className="audio-player-button"
        onClick={toggle}
        aria-label={`${playing ? "Pause" : "Play"} ${label}`}
      >
        {playing ? <PauseIcon className="h-4 w-4" /> : <PlayIcon className="h-4 w-4" />}
      </button>
      <span className="w-9 text-right text-[11px] tabular-nums text-slate-500">
        {fmtDuration(position)}
      </span>
      <input
        className="audio-player-range"
        type="range"
        min={0}
        max={duration || 0}
        step={0.1}
        value={Math.min(position, duration || 0)}
        style={{
          background: `linear-gradient(to right, rgb(192 132 252) ${progressPercent}%, rgb(51 65 85) ${progressPercent}%)`,
        }}
        aria-label={`Seek ${label}`}
        onChange={(event) => {
          const next = Number(event.target.value);
          sound.current?.seek(next);
          setPosition(next);
        }}
      />
      <span className="w-9 text-[11px] tabular-nums text-slate-500">
        {duration ? fmtDuration(duration) : "--:--"}
      </span>
    </div>
  );
}

export function VideoPlayer({ src, label }: { src: string; label: string }) {
  return (
    <video
      className="media-video-player"
      title={label}
      src={src}
      preload="metadata"
      playsInline
      controls
    />
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
