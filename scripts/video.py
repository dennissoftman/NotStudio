"""Render a mix (e.g. cross.py's output) into a YouTube-ready video.

Pipeline fit:  main.py --prompts ...  ->  cross.py *.flac -o mix.flac  ->  video.py mix.flac

By default it draws a polished audio-reactive visualizer (no art needed); pass an
image with --background to use cover art with the visualizer as a bottom band.

Audio quality (so YouTube's loudness normalization won't make it quiet mush):
the audio is mastered once to EBU R128 ~-14 LUFS (two-pass loudnorm) at 48 kHz and
encoded as 384 kbps AAC. To avoid an ffmpeg buffering bug when one audio stream
feeds both a light visualizer and the encoder, it renders in clean passes:
master audio -> render video (visualizer reads the master, no audio) -> mux.

Examples:
    python video.py mix.flac                                  # cqt visualizer, 1080p
    python video.py mix.flac --visualizer spectrum --title "Night Drive"
    python video.py mix.flac --background cover.png --zoom     # art + slow zoom + bottom bars
    python video.py mix.flac --audio-only -o mix.m4a           # just the mastered audio

YouTube chapters are written next to the output (from a sibling .cue if present).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from functools import lru_cache
from pathlib import Path

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


def _run(cmd: list[str], capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=capture, text=True, check=False)


@lru_cache(maxsize=1)
def has_filter(name: str) -> bool:
    proc = _run([FFMPEG, "-hide_banner", "-filters"], capture=True)
    return any(f" {name} " in line for line in (proc.stdout or "").splitlines())


def find_font(explicit: str | None) -> str | None:
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


# --- loudness ----------------------------------------------------------------
def _finite(value) -> bool:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return False
    return f == f and abs(f) != float("inf")


def measure_loudness(audio: Path, i: float, tp: float, lra: float):
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


def loudnorm_filter(audio: Path, i: float, tp: float, lra: float) -> str:
    base = f"loudnorm=I={i}:TP={tp}:LRA={lra}"
    m = measure_loudness(audio, i, tp, lra)
    if m is None:
        return base  # single-pass fallback (e.g. near-silent input)
    return (
        f"{base}:measured_I={m['input_i']}:measured_TP={m['input_tp']}"
        f":measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}"
        f":offset={m['target_offset']}:linear=true"
    )


# --- visualizer --------------------------------------------------------------
def visualizer_core(style: str, w: int, h: int, fps: int) -> str:
    # The visualizer is created at the final size; we deliberately do NOT rescale
    # its output afterwards — feeding a rescaled show* result into blend/overlay
    # segfaults some ffmpeg builds.
    if style == "cqt":
        return f"showcqt=size={w}x{h}:fps={fps}:count=1:gamma=5:bar_g=2:sono_g=4"
    if style == "spectrum":
        return f"showspectrum=size={w}x{h}:mode=combined:color=intensity:scale=cbrt:slide=scroll"
    if style == "waves":
        return f"showwaves=size={w}x{h}:mode=cline:rate={fps}:colors=0x22d3ee|0x818cf8:scale=sqrt"
    raise ValueError(f"unknown visualizer: {style}")


def _viz_sized(style: str, w: int, h: int, fps: int, extra: str = "") -> str:
    return f"{visualizer_core(style, w, h, fps)},fps={fps},setsar=1{extra}"


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
    """Video-only filtergraph. Audio (input 0) is only read by the visualizer."""
    viz_used = style != "none"
    chains: list[str] = []

    if has_background:  # background is input 1; visualizer sits in a bottom band
        bg = (
            f"[1:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},setsar=1,fps={fps}"
        )
        if zoom and not background_is_video:
            bg += (
                f",zoompan=z='min(zoom+0.00018,1.18)':d=1:s={width}x{height}:fps={fps}"
            )
        chains.append(f"{bg}[bg]")
        if viz_used:
            band = max(2, int(height * 0.30) // 2 * 2)
            chains.append(
                f"[0:a]{_viz_sized(style, width, band, fps, ',format=rgba,colorchannelmixer=aa=0.9')}[viz]"
            )
            chains.append(
                f"[bg][viz]overlay=0:{height - band}:shortest=1,format=yuv420p[v0]"
            )
        else:
            chains.append("[bg]format=yuv420p[v0]")
    elif viz_used:
        # Full-frame visualizer over its own dark background + a vignette for depth.
        # (No color base / screen-blend: that path segfaults with show{waves,freqs}.)
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


# --- chapters ----------------------------------------------------------------
def hms(seconds: float) -> str:
    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


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
    out = [f"{hms(t)} {title}" for t, title in zip(starts, titles)]
    if out and not out[0].startswith("0:00 "):
        out[0] = "0:00 " + out[0].split(" ", 1)[1]  # YouTube requires a 0:00 chapter
    return "\n".join(out) + "\n"


def _check(
    result: subprocess.CompletedProcess, parser: argparse.ArgumentParser, what: str
) -> None:
    if result.returncode != 0:
        parser.exit(1, f"video.py: ffmpeg failed while {what}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render a mix into a YouTube-ready video."
    )
    parser.add_argument("audio", help="Input audio (e.g. cross.py's mix.flac).")
    parser.add_argument(
        "-o", "--output", help="Output file. Default: <audio>.mp4 (or .m4a)."
    )
    parser.add_argument(
        "--visualizer", choices=VISUALIZERS, default="cqt", help="Default: cqt."
    )
    parser.add_argument(
        "--background", help="Background image or video (loops to fit)."
    )
    parser.add_argument(
        "--zoom", action="store_true", help="Slow Ken Burns zoom on a bg image."
    )
    parser.add_argument(
        "--title", help="Title text drawn near the top (needs drawtext support)."
    )
    parser.add_argument(
        "--font", help="TTF/TTC font for --title (auto-detected otherwise)."
    )
    parser.add_argument(
        "--resolution", default="1920x1080", help="WxH. Default 1920x1080."
    )
    parser.add_argument("--fps", type=int, default=30, help="Frame rate. Default 30.")
    parser.add_argument(
        "--lufs", type=float, default=-14.0, help="Loudness target (YouTube ~-14)."
    )
    parser.add_argument(
        "--true-peak", type=float, default=-1.0, help="Max true peak dBTP."
    )
    parser.add_argument(
        "--lra", type=float, default=11.0, help="Loudness range target."
    )
    parser.add_argument(
        "--no-normalize", action="store_true", help="Skip loudness normalization."
    )
    parser.add_argument(
        "--audio-bitrate", default="384k", help="AAC bitrate. Default 384k."
    )
    parser.add_argument(
        "--crf", type=int, default=18, help="x264 CRF (lower = better)."
    )
    parser.add_argument(
        "--preset", default="medium", help="x264 preset. Default medium."
    )
    parser.add_argument(
        "--audio-only", action="store_true", help="Emit mastered audio (.m4a) only."
    )
    parser.add_argument(
        "--no-chapters", action="store_true", help="Don't write chapters.txt."
    )
    parser.add_argument(
        "--cue", help="Cue sheet for chapters. Default: sibling <audio>.cue."
    )
    args = parser.parse_args()

    audio = Path(args.audio)
    if not audio.is_file():
        parser.error(f"audio not found: {audio}")

    output = (
        Path(args.output)
        if args.output
        else audio.with_suffix(".m4a" if args.audio_only else ".mp4")
    )
    output.parent.mkdir(parents=True, exist_ok=True)

    if args.no_normalize:
        audio_chain = "aresample=48000"
    else:
        print("Measuring loudness (pass 1/2)...")
        audio_chain = f"{loudnorm_filter(audio, args.lufs, args.true_peak, args.lra)},aresample=48000"

    common_audio = [
        "-c:a",
        "aac",
        "-b:a",
        args.audio_bitrate,
        "-ar",
        "48000",
        "-ac",
        "2",
    ]

    # --- audio-only: master straight to m4a -----------------------------------
    if args.audio_only:
        print(f"Mastering audio: {output}")
        _check(
            _run(
                [
                    FFMPEG,
                    "-y",
                    "-hide_banner",
                    "-i",
                    str(audio),
                    "-af",
                    audio_chain,
                    *common_audio,
                    "-movflags",
                    "+faststart",
                    str(output),
                ]
            ),
            parser,
            "mastering audio",
        )
        print(f"Saved: {output}")
        _write_chapters(args, audio, output)
        return

    # --- video --------------------------------------------------------------
    try:
        width, height = (int(x) for x in args.resolution.lower().split("x"))
    except ValueError:
        parser.error("--resolution must look like 1920x1080")

    background_is_video = False
    if args.background:
        bg_path = Path(args.background)
        if not bg_path.is_file():
            parser.error(f"background not found: {bg_path}")
        background_is_video = bg_path.suffix.lower() in {
            ".mp4",
            ".mov",
            ".webm",
            ".mkv",
            ".gif",
        }

    title_file, font = None, None
    if args.title:
        font = find_font(args.font)
        if not font or not has_filter("drawtext"):
            print(
                "warning: no drawtext/font available; skipping --title.",
                file=sys.stderr,
            )
        else:
            tf = tempfile.NamedTemporaryFile(
                "w", suffix=".txt", delete=False, encoding="utf-8"
            )
            tf.write(args.title)
            tf.close()
            title_file = tf.name

    graph, vlabel = build_video_filter(
        style=args.visualizer,
        width=width,
        height=height,
        fps=args.fps,
        has_background=bool(args.background),
        background_is_video=background_is_video,
        zoom=args.zoom,
        title_file=title_file,
        font=font,
    )

    workdir = Path(tempfile.mkdtemp(prefix="not-studio-video-"))
    master = workdir / "master.flac"
    silent_video = workdir / "video.mp4"
    try:
        # 1) master audio once (single consumer -> no asplit race).
        print("Mastering audio...")
        _check(
            _run(
                [
                    FFMPEG,
                    "-y",
                    "-hide_banner",
                    "-i",
                    str(audio),
                    "-af",
                    audio_chain,
                    "-c:a",
                    "flac",
                    "-ar",
                    "48000",
                    str(master),
                ]
            ),
            parser,
            "mastering audio",
        )

        # 2) render video only; the visualizer reads the mastered audio (input 0).
        # Bound the output to the audio duration: with -an, some visualizers
        # (showwaves/showfreqs) never signal EOF and ffmpeg would run forever.
        print("Rendering video...")
        duration = probe_duration(master)
        dur_args = ["-t", f"{duration:.3f}"] if duration else []
        inputs = ["-i", str(master)]
        if args.background:
            loop = ["-stream_loop", "-1"] if background_is_video else ["-loop", "1"]
            inputs += [*loop, "-i", str(args.background)]
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
                    *dur_args,
                    "-c:v",
                    "libx264",
                    "-preset",
                    args.preset,
                    "-crf",
                    str(args.crf),
                    "-pix_fmt",
                    "yuv420p",
                    "-profile:v",
                    "high",
                    "-g",
                    str(args.fps * 2),
                    "-bf",
                    "2",
                    str(silent_video),
                ]
            ),
            parser,
            "rendering video",
        )

        # 3) mux video + mastered audio (AAC encoded once, no filtering).
        print(f"Muxing: {output}")
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
                    str(output),
                ]
            ),
            parser,
            "muxing",
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
        if title_file:
            Path(title_file).unlink(missing_ok=True)

    print(f"Saved: {output}")
    _write_chapters(args, audio, output)


def _write_chapters(args, audio: Path, output: Path) -> None:
    if args.no_chapters:
        return
    cue_path = Path(args.cue) if args.cue else audio.with_suffix(".cue")
    if not cue_path.is_file():
        return
    chapters = cue_to_chapters(cue_path)
    if chapters:
        chapters_path = output.with_name("chapters.txt")
        chapters_path.write_text(chapters, encoding="utf-8")
        print(f"Saved: {chapters_path} (paste into the YouTube description)")


if __name__ == "__main__":
    main()
