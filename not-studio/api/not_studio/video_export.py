"""Assemble selected tracks into a YouTube-ready video."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

from .audio import dsp

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"

VISUALIZERS = ("cqt", "spectrum", "waves", "none")
RESOLUTIONS = {
    "2160p": (3840, 2160),
    "1440p": (2560, 1440),
    "1080p": (1920, 1080),
    "720p": (1280, 720),
}

_FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Futura.ttc",
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/SFNS.ttf",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


def mix_tracks_to_file(
    paths: list[str],
    output_path: Path,
    *,
    crossfade_seconds: float,
) -> tuple[float, list[float], int, int]:
    """Stream a crossfaded FLAC through ffmpeg without loading the album into RAM."""
    if not paths:
        raise RuntimeError("No audio to combine.")
    source_paths = [Path(path) for path in paths]
    missing = next((path for path in source_paths if not path.is_file()), None)
    if missing:
        raise RuntimeError(f"audio not found: {missing}")

    source_info = [dsp.audio_file_info(str(path)) for path in source_paths]
    durations = [float(info["duration_seconds"]) for info in source_info]
    positive_durations = [duration for duration in durations if duration > 0]
    if len(positive_durations) != len(durations):
        raise RuntimeError("Could not determine every track duration.")
    fade = max(0.0, float(crossfade_seconds))
    if len(paths) > 1:
        fade = min(fade, min(positive_durations) / 2.0)

    starts = [0.0]
    elapsed = durations[0]
    for duration in durations[1:]:
        starts.append(max(0.0, elapsed - fade))
        elapsed += duration - fade

    sample_rate = min(int(info["sample_rate"]) for info in source_info)
    channels = min(int(info["channels"]) for info in source_info)
    layouts = {1: "mono", 2: "stereo"}
    if channels not in layouts:
        raise RuntimeError(f"Unsupported source channel count: {channels}")
    layout = layouts[channels]
    chains = [
        f"[{index}:a]aresample={sample_rate},"
        f"aformat=sample_fmts=fltp:channel_layouts={layout}[a{index}]"
        for index in range(len(paths))
    ]
    current = "[a0]"
    if len(paths) == 1:
        chains.append(f"{current}anull[mix]")
    else:
        for index in range(1, len(paths)):
            output = "[mix]" if index == len(paths) - 1 else f"[x{index}]"
            chains.append(f"{current}[a{index}]acrossfade=d={fade:.6f}:c1=qsin:c2=qsin{output}")
            current = output

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    inputs = [argument for path in source_paths for argument in ("-i", str(path))]
    result = _run(
        [
            FFMPEG,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            *inputs,
            "-filter_complex",
            ";".join(chains),
            "-map",
            "[mix]",
            "-c:a",
            "flac",
            "-ar",
            str(sample_rate),
            "-ac",
            str(channels),
            str(output_path),
        ],
        capture=True,
    )
    _check(result, "crossfading tracks")
    return elapsed, starts, sample_rate, channels


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


def probe_audio_stream(path: Path) -> dict[str, int | float]:
    proc = _run(
        [
            FFPROBE,
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=sample_rate,channels,bit_rate:format=duration,bit_rate",
            "-of",
            "json",
            str(path),
        ],
        capture=True,
    )
    try:
        payload = json.loads(proc.stdout or "{}")
        stream = payload["streams"][0]
        format_info = payload.get("format") or {}
        sample_rate = int(stream["sample_rate"])
        channels = int(stream["channels"])
        duration = float(format_info["duration"])
        raw_bit_rate = stream.get("bit_rate") or format_info.get("bit_rate")
        bit_rate = int(raw_bit_rate) if raw_bit_rate not in (None, "N/A") else 0
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise RuntimeError(f"Could not inspect source audio: {path}") from exc
    if bit_rate <= 0 and duration > 0:
        bit_rate = round(path.stat().st_size * 8 / duration)
    return {
        "sample_rate": sample_rate,
        "channels": channels,
        "duration": duration,
        "bit_rate": bit_rate,
    }


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
    audio_label: str = "[0:a]",
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
                f"{audio_label}{_viz_sized(style, width, band, fps, ',format=rgba,colorchannelmixer=aa=0.9')}[viz]"
            )
            chains.append(f"[bg][viz]overlay=0:{height - band}:shortest=1,format=yuv420p[v0]")
        else:
            chains.append("[bg]format=yuv420p[v0]")
    elif viz_used:
        chains.append(
            f"{audio_label}{_viz_sized(style, width, height, fps)},vignette=PI/5,format=yuv420p[v0]"
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
    resolution: str = "1080p",
    title: str | None = None,
    background: str | None = None,
) -> None:
    mix_path = Path(mix_path)
    out_path = Path(out_path)
    if not mix_path.is_file():
        raise RuntimeError(f"audio not found: {mix_path}")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if resolution not in RESOLUTIONS:
        raise ValueError(f"unknown resolution: {resolution}")
    width, height = RESOLUTIONS[resolution]
    fps = 30
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

    visualizer_used = visualizer != "none"
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
        audio_label="[viz_audio]" if visualizer_used else "[0:a]",
    )
    audio_info = probe_audio_stream(mix_path)
    source_sample_rate = int(audio_info["sample_rate"])
    source_channels = int(audio_info["channels"])
    source_bit_rate = int(audio_info["bit_rate"])
    aac_sample_rates = {
        7350,
        8000,
        11025,
        12000,
        16000,
        22050,
        24000,
        32000,
        44100,
        48000,
        64000,
        88200,
        96000,
    }
    if source_sample_rate not in aac_sample_rates:
        raise RuntimeError(f"AAC cannot preserve the source sample rate of {source_sample_rate} Hz")
    aac_bit_rate = min(512_000, source_bit_rate)
    common_audio = [
        "-c:a",
        "aac",
        "-b:a",
        str(aac_bit_rate),
        "-ar",
        str(source_sample_rate),
        "-ac",
        str(source_channels),
        "-profile:a",
        "aac_low",
        "-aac_coder",
        "twoloop",
    ]
    if visualizer_used:
        graph = f"[0:a]asplit=2[viz_audio][audio];{graph}"
    else:
        graph = f"{graph};[0:a]anull[audio]"

    try:
        duration = float(audio_info["duration"])
        duration_args = ["-t", f"{duration:.3f}"] if duration else []
        inputs = ["-i", str(mix_path)]
        if background:
            loop = ["-stream_loop", "-1"] if background_is_video else ["-loop", "1"]
            inputs += [*loop, "-i", str(background)]
        _check(
            _run(
                [
                    FFMPEG,
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    *inputs,
                    "-filter_complex",
                    graph,
                    "-map",
                    vlabel,
                    "-map",
                    "[audio]",
                    *duration_args,
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "20",
                    "-pix_fmt",
                    "yuv420p",
                    "-profile:v",
                    "high",
                    "-g",
                    str(fps * 2),
                    "-bf",
                    "2",
                    *common_audio,
                    "-shortest",
                    "-movflags",
                    "+faststart",
                    str(out_path),
                ],
                capture=True,
            ),
            "rendering video",
        )

        chapters = cue_to_chapters(mix_path.with_suffix(".cue"))
        if chapters:
            out_path.with_name("chapters.txt").write_text(chapters, encoding="utf-8")
    finally:
        if title_file:
            Path(title_file).unlink(missing_ok=True)
