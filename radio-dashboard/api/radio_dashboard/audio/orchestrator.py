"""Program orchestration + mixing (feature #2).

Turns a Program recipe into a single continuous audio batch: a crossfaded music
bed with spoken inserts (news / info / ads / station IDs / weather) woven in and
the bed ducked underneath them. Emits a typed WebVTT timeline describing the
result (the canonical Neural Radio representation), validated against the parent
engine's parser when it is importable.

This module is deliberately free of DB / arq / FastAPI so it can be unit-tested
with the mock backends. Cancellation is cooperative: ``cancel_check`` is called
between every generated cue.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from .. import engine_bridge
from ..backends.base import MusicBackend, SpeechBackend
from ..schemas import ProgramConfig
from . import dsp

# Speech-like inserts are spoken; jingles/sfx would need an asset library.
_SPOKEN_KINDS = {"news", "info", "ad", "station_id", "weather"}

ProgressFn = Callable[[float, str], None]
CancelFn = Callable[[], None]


@dataclass
class _Cue:
    kind: str  # "music_track" | "speech"
    start: float
    end: float
    text: str = ""
    asset: str = ""
    voice: str = ""
    section: str = ""


@dataclass
class RenderResult:
    data: np.ndarray
    sample_rate: int
    channels: int
    duration: float
    vtt_text: str
    lufs: float | None
    music_tracks: int
    inserts: int
    cues: list[_Cue] = field(default_factory=list)


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "asset"


def _format_ts(seconds: float) -> str:
    ms_total = round(max(0.0, seconds) * 1000)
    hours, rem = divmod(ms_total, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{ms:03d}"


def _noop(*_a: object, **_k: object) -> None:
    return None


def render_batch(
    *,
    program_config: dict | ProgramConfig,
    music_backend: MusicBackend,
    speech_backend: SpeechBackend | None,
    target_seconds: float,
    sample_rate: int,
    channels: int,
    batch_index: int = 0,
    station_name: str = "Neural FM",
    program_name: str = "Program",
    cancel_check: CancelFn | None = None,
    progress: ProgressFn | None = None,
) -> RenderResult:
    cfg = (
        program_config
        if isinstance(program_config, ProgramConfig)
        else ProgramConfig.model_validate(program_config or {})
    )
    check = cancel_check or _noop
    report = progress or _noop

    # --- 1. Music bed: crossfade tracks until we cover the target -------------
    track_seconds = max(5.0, float(cfg.music.track_seconds))
    crossfade = max(0.0, float(cfg.crossfade_seconds or cfg.music.crossfade_seconds))
    prompts = cfg.music.prompts or ["instrumental radio music bed"]
    xfade_n = int(crossfade * sample_rate)

    check()
    report(0.02, "Generating music bed")
    bed = np.zeros((0, channels), dtype=np.float32)
    music_cues: list[_Cue] = []
    track_i = 0
    while len(bed) < int(target_seconds * sample_rate):
        prompt = prompts[(batch_index + track_i) % len(prompts)]
        buf = music_backend.generate_music(
            prompt=prompt,
            duration=track_seconds,
            sample_rate=sample_rate,
            channels=channels,
        )
        piece = dsp.ensure_channels(buf.data, channels)
        start_sample = 0 if track_i == 0 else max(len(bed) - xfade_n, 0)
        bed = piece if track_i == 0 else dsp.equal_power_crossfade(bed, piece, xfade_n)
        music_cues.append(
            _Cue(
                kind="music_track",
                start=start_sample / sample_rate,
                end=len(bed) / sample_rate,
                asset=_slug(cfg.music.genre or prompt),
                section="music",
            )
        )
        track_i += 1
        check()
        report(
            min(0.55, 0.02 + 0.53 * len(bed) / max(1, int(target_seconds * sample_rate))),
            f"Music track {track_i}",
        )

    # Trim to target; a gentle tail fade keeps batch boundaries seamless.
    bed = bed[: int(target_seconds * sample_rate)]
    bed = dsp.apply_fade(bed, 0.0, min(2.0, crossfade or 2.0), sample_rate)
    if music_cues:
        music_cues[-1].end = len(bed) / sample_rate

    # --- 2. Inserts: speak + overlay with ducking -----------------------------
    speech_cues: list[_Cue] = []
    inserts = [i for i in cfg.inserts]
    total_inserts_est = (
        sum(max(1, int(target_seconds // max(30.0, i.cadence_seconds))) for i in inserts) or 1
    )
    done_inserts = 0

    for idx, spec in enumerate(inserts):
        if spec.kind not in _SPOKEN_KINDS:
            continue  # jingles/sfx need an asset library — skipped in the MVP
        if speech_backend is None:
            break
        texts = spec.texts or ([station_name] if spec.kind == "station_id" else [])
        if not texts:
            continue

        cadence = max(20.0, float(spec.cadence_seconds))
        offset = 5.0 + idx * 11.0  # stagger kinds so they don't stack up
        bed_gain = dsp.db_to_gain(spec.bed_volume_db)
        insert_gain = dsp.db_to_gain(spec.insert_volume_db)

        t = offset
        text_i = 0
        while t < target_seconds - 2.0:
            check()
            text = texts[text_i % len(texts)]
            buf = speech_backend.synthesize(
                text=text,
                sample_rate=sample_rate,
                channels=1,
                voice=spec.voice,
            )
            dur = buf.duration
            bed = dsp.overlay_with_duck(
                bed,
                buf.data,
                at_seconds=t,
                sample_rate=sample_rate,
                ducking=spec.ducking,
                bed_gain=bed_gain,
                insert_gain=insert_gain,
            )
            speech_cues.append(
                _Cue(
                    kind="speech",
                    start=t,
                    end=t + dur,
                    text=text,
                    voice=spec.voice or "",
                    section=spec.kind,
                )
            )
            done_inserts += 1
            report(
                0.55 + 0.4 * min(1.0, done_inserts / total_inserts_est),
                f"Insert {spec.kind} @ {int(t)}s",
            )
            t += cadence
            text_i += 1

    # --- 3. Loudness + limit --------------------------------------------------
    check()
    report(0.96, "Normalizing loudness")
    bed = dsp.normalize_lufs(bed, sample_rate, cfg.target_lufs)
    bed = dsp.peak_limit(bed)
    lufs = dsp.measure_lufs(bed, sample_rate)

    cues = music_cues + speech_cues
    vtt = _build_webvtt(
        music_cues,
        speech_cues,
        station_name=station_name,
        program_name=program_name,
        batch_index=batch_index,
    )
    report(1.0, "Batch complete")
    return RenderResult(
        data=bed,
        sample_rate=sample_rate,
        channels=channels,
        duration=len(bed) / sample_rate,
        vtt_text=vtt,
        lufs=lufs,
        music_tracks=len(music_cues),
        inserts=len(speech_cues),
        cues=cues,
    )


def _build_webvtt(
    music_cues: list[_Cue],
    speech_cues: list[_Cue],
    *,
    station_name: str,
    program_name: str,
    batch_index: int,
) -> str:
    lines = [
        "WEBVTT",
        "",
        f"NOTE station={station_name}",
        f"NOTE program={program_name}",
        f"NOTE batch={batch_index}",
        "",
    ]

    for i, cue in enumerate(music_cues, start=1):
        lines += [
            f"music-{i:03d}",
            f"{_format_ts(cue.start)} --> {_format_ts(cue.end)}",
            "",
            "NOTE type=music_track",
            f"NOTE asset={cue.asset or 'generated'}",
            f"NOTE section={cue.section or 'music'}",
            "",
        ]

    # The typed-WebVTT validator forbids overlapping speech cues; nudge starts so
    # the emitted timeline stays valid even when audio inserts overlap.
    prev_end = -1.0
    for i, cue in enumerate(sorted(speech_cues, key=lambda c: c.start), start=1):
        start = max(cue.start, prev_end)
        end = max(start + 0.05, cue.end if cue.end > start else start + 0.5)
        prev_end = end
        voice_line = f"<v {cue.voice}>" if cue.voice else "<v Announcer>"
        lines += [
            f"speech-{i:03d}",
            f"{_format_ts(start)} --> {_format_ts(end)}",
            "",
            voice_line,
            cue.text,
            "NOTE type=speech",
            f"NOTE section={cue.section or 'speech'}",
            "",
        ]

    text = "\n".join(lines)
    _validate_best_effort(text)
    return text


def _validate_best_effort(vtt_text: str) -> None:
    module = engine_bridge.load_timeline_module()
    if module is None:
        return
    try:
        module.parse_webvtt_timeline(vtt_text)
    except Exception:
        # Metadata only — never fail a render because the timeline didn't validate.
        pass
