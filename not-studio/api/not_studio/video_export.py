"""Assemble selected tracks into a YouTube-ready video."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

import numpy as np

from .audio import dsp

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"

VISUALIZERS = ("cqt", "spectrum", "waves", "none")

_FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Futura.ttc",
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/SFNS.ttf",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


def crossfade_tracks(
    paths: list[str],
    *,
    sample_rate: int,
    channels: int,
    crossfade_seconds: float,
) -> tuple[np.ndarray, list[float]]:
    """Equal-power crossfade the tracks into one buffer; return (mix, start_times)."""
    n = int(crossfade_seconds * sample_rate)
    arrays = [dsp.load_audio_file(p, sample_rate, channels) for p in paths]
    arrays = [a for a in arrays if len(a)]
    if not arrays:
        raise RuntimeError("No audio to combine.")

    mix = arrays[0]
    starts = [0.0]
    for track in arrays[1:]:
        starts.append(max(len(mix) - n, 0) / sample_rate)
        mix = dsp.equal_power_crossfade(mix, track, n)
    return mix, starts


def _cue_timestamp(seconds: float) -> str:
    frames = int(round(seconds * 75))  # CD frames, 75/sec (matches cross.py)
    minutes, rem = divmod(frames, 75 * 60)
    secs, frame = divmod(rem, 75)
    return f"{minutes:02d}:{secs:02d}:{frame:02d}"


def write_cue(path: Path, audio_name: str, titles: list[str], starts: list[float]) -> None:
    lines = [f'FILE "{audio_name}" FLAC']
    for index, (title, start) in enumerate(zip(titles, starts), start=1):
        lines += [
            f"  TRACK {index:02d} AUDIO",
            f'    TITLE "{title.replace(chr(34), chr(39))}"',
            f"    INDEX 01 {_cue_timestamp(start)}",
        ]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run(cmd: list[str], capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=capture, text=True, check=False)


def _check(result: subprocess.CompletedProcess[str], what: str) -> None:
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"ffmpeg failed while {what}: {detail}")


@lru_cache(maxsize=1)
def has_filter(name: str) -> bool:
    proc = _run([FFMPEG, "-hide_banner", "-filters"], capture=True)
    return any(f" {name} " in line for line in (proc.stdout or "").splitlines())


def find_font(explicit: str | None = None) -> str | None:
    if explicit:
        return explicit if Path(explicit).is_file() else None
    return next((f for f in _FONT_CANDIDATES if Path(f).is_file()), None)


def probe_duration(path: Path) -> float | None:
    proc = _run(
        [
            FFPROBE,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ],
        capture=True,
    )
    try:
        return float((proc.stdout or "").strip())
    except ValueError:
        return None


def _finite(value: object) -> bool:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return False
    return f == f and abs(f) != float("inf")


def measure_loudness(audio: Path, i: float, tp: float, lra: float) -> dict | None:
    proc = _run(
        [
            FFMPEG,
            "-hide_banner",
            "-nostats",
            "-i",
            str(audio),
            "-af",
            f"loudnorm=I={i}:TP={tp}:LRA={lra}:print_format=json",
            "-f",
            "null",
            "-",
        ],
        capture=True,
    )
    text = proc.stderr or ""
    start, end = text.rfind("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except ValueError:
        return None
    keys = ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")
    return data if all(_finite(data.get(k)) for k in keys) else None


def loudnorm_filter(audio: Path, i: float = -14.0, tp: float = -1.0, lra: float = 11.0) -> str:
    base = f"loudnorm=I={i}:TP={tp}:LRA={lra}"
    measured = measure_loudness(audio, i, tp, lra)
    if measured is None:
        return base
    return (
        f"{base}:measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
        f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}"
        f":offset={measured['target_offset']}:linear=true"
    )


def visualizer_core(style: str, width: int, height: int, fps: int) -> str:
    if style == "cqt":
        return f"showcqt=size={width}x{height}:fps={fps}:count=1:gamma=5:bar_g=2:sono_g=4"
    if style == "spectrum":
        return (
            f"showspectrum=size={width}x{height}:mode=combined:"
            "color=intensity:scale=cbrt:slide=scroll"
        )
    if style == "waves":
        return (
            f"showwaves=size={width}x{height}:mode=cline:rate={fps}:"
            "colors=0x22d3ee|0x818cf8:scale=sqrt"
        )
    raise ValueError(f"unknown visualizer: {style}")


def _viz_sized(style: str, width: int, height: int, fps: int, extra: str = "") -> str:
    return f"{visualizer_core(style, width, height, fps)},fps={fps},setsar=1{extra}"


def build_video_filter(
    *,
    style: str,
    width: int,
    height: int,
    fps: int,
    has_background: bool,
    background_is_video: bool,
    zoom: bool,
    title_file: str | None,
    font: str | None,
) -> tuple[str, str]:
    if style not in VISUALIZERS:
        raise ValueError(f"unknown visualizer: {style}")
    viz_used = style != "none"
    chains: list[str] = []

    if has_background:
        bg = (
            f"[1:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},setsar=1,fps={fps}"
        )
        if zoom and not background_is_video:
            bg += f",zoompan=z='min(zoom+0.00018,1.18)':d=1:s={width}x{height}:fps={fps}"
        chains.append(f"{bg}[bg]")
        if viz_used:
            band = max(2, int(height * 0.30) // 2 * 2)
            chains.append(
                f"[0:a]{_viz_sized(style, width, band, fps, ',format=rgba,colorchannelmixer=aa=0.9')}[viz]"
            )
            chains.append(f"[bg][viz]overlay=0:{height - band}:shortest=1,format=yuv420p[v0]")
        else:
            chains.append("[bg]format=yuv420p[v0]")
    elif viz_used:
        chains.append(
            f"[0:a]{_viz_sized(style, width, height, fps)},vignette=PI/5,format=yuv420p[v0]"
        )
    else:
        chains.append(
            f"color=c=0x0a0b16:s={width}x{height}:r={fps},vignette=PI/4.5,format=yuv420p[v0]"
        )

    label = "[v0]"
    if title_file and font:
        fontsize = max(30, height // 22)
        chains.append(
            f"[v0]drawtext=fontfile='{font}':textfile='{title_file}':"
            f"fontcolor=white@0.94:fontsize={fontsize}:x=(w-text_w)/2:y={height // 14}:"
            f"box=1:boxcolor=black@0.38:boxborderw=24:line_spacing=10[v]"
        )
        label = "[v]"
    return ";".join(chains), label


def hms(seconds: float) -> str:
    total = int(round(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def cue_to_chapters(cue_path: Path) -> str | None:
    try:
        lines = cue_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    titles: list[str] = []
    starts: list[float] = []
    for line in lines:
        line = line.strip()
        if line.startswith("TITLE "):
            titles.append(line[6:].strip().strip('"'))
        elif line.startswith("INDEX 01 "):
            mm, ss, ff = line.split()[-1].split(":")
            starts.append(int(mm) * 60 + int(ss) + int(ff) / 75.0)
    if not starts or len(titles) < len(starts):
        return None
    out = [f"{hms(t)} {title}" for title, t in zip(titles, starts)]
    if out and not out[0].startswith("0:00 "):
        out[0] = "0:00 " + out[0].split(" ", 1)[1]
    return "\n".join(out) + "\n"


def render_video(
    mix_path: Path,
    out_path: Path,
    *,
    visualizer: str = "cqt",
    title: str | None = None,
    background: str | None = None,
) -> None:
    mix_path = Path(mix_path)
    out_path = Path(out_path)
    if not mix_path.is_file():
        raise RuntimeError(f"audio not found: {mix_path}")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    width, height, fps = 1920, 1080, 30
    background_is_video = False
    if background:
        bg_path = Path(background)
        if not bg_path.is_file():
            raise RuntimeError(f"background not found: {bg_path}")
        background_is_video = bg_path.suffix.lower() in {
            ".mp4",
            ".mov",
            ".webm",
            ".mkv",
            ".gif",
        }

    title_file, font = None, None
    if title:
        font = find_font()
        if font and has_filter("drawtext"):
            tf = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8")
            tf.write(title)
            tf.close()
            title_file = tf.name

    graph, vlabel = build_video_filter(
        style=visualizer,
        width=width,
        height=height,
        fps=fps,
        has_background=bool(background),
        background_is_video=background_is_video,
        zoom=False,
        title_file=title_file,
        font=font,
    )
    common_audio = ["-c:a", "aac", "-b:a", "384k", "-ar", "48000", "-ac", "2"]
    audio_chain = f"{loudnorm_filter(mix_path)},aresample=48000"

    workdir = Path(tempfile.mkdtemp(prefix="not-studio-video-"))
    master = workdir / "master.flac"
    silent_video = workdir / "video.mp4"
    try:
        _check(
            _run(
                [
                    FFMPEG,
                    "-y",
                    "-hide_banner",
                    "-i",
                    str(mix_path),
                    "-af",
                    audio_chain,
                    "-c:a",
                    "flac",
                    "-ar",
                    "48000",
                    str(master),
                ],
                capture=True,
            ),
            "mastering audio",
        )

        duration = probe_duration(master)
        duration_args = ["-t", f"{duration:.3f}"] if duration else []
        inputs = ["-i", str(master)]
        if background:
            loop = ["-stream_loop", "-1"] if background_is_video else ["-loop", "1"]
            inputs += [*loop, "-i", str(background)]
        _check(
            _run(
                [
                    FFMPEG,
                    "-y",
                    "-hide_banner",
                    *inputs,
                    "-filter_complex",
                    graph,
                    "-map",
                    vlabel,
                    "-an",
                    *duration_args,
                    "-c:v",
                    "libx264",
                    "-preset",
                    "medium",
                    "-crf",
                    "18",
                    "-pix_fmt",
                    "yuv420p",
                    "-profile:v",
                    "high",
                    "-g",
                    str(fps * 2),
                    "-bf",
                    "2",
                    str(silent_video),
                ],
                capture=True,
            ),
            "rendering video",
        )

        _check(
            _run(
                [
                    FFMPEG,
                    "-y",
                    "-hide_banner",
                    "-i",
                    str(silent_video),
                    "-i",
                    str(master),
                    "-map",
                    "0:v",
                    "-map",
                    "1:a",
                    "-c:v",
                    "copy",
                    *common_audio,
                    "-shortest",
                    "-movflags",
                    "+faststart",
                    str(out_path),
                ],
                capture=True,
            ),
            "muxing",
        )

        chapters = cue_to_chapters(mix_path.with_suffix(".cue"))
        if chapters:
            out_path.with_name("chapters.txt").write_text(chapters, encoding="utf-8")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
        if title_file:
            Path(title_file).unlink(missing_ok=True)
