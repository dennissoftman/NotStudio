"""ffmpeg command builders + a raw-PCM input spec.

Every consumer takes the same interleaved little-endian s16 PCM on stdin (what
:func:`radio_dashboard.audio.dsp.to_int16_bytes` produces) and encodes to its
target: MP3 (HTTP + Icecast) or AAC/HLS.
"""

from __future__ import annotations

from ..config import get_settings


def pcm_input_args(sample_rate: int, channels: int) -> list[str]:
    return [
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "s16le",
        "-ar",
        str(sample_rate),
        "-ac",
        str(channels),
        "-i",
        "pipe:0",
    ]


def mp3_stdout_args(bitrate: str | None = None) -> list[str]:
    bitrate = bitrate or get_settings().stream_mp3_bitrate
    return ["-c:a", "libmp3lame", "-b:a", bitrate, "-f", "mp3", "pipe:1"]


def icecast_args(
    *,
    host: str,
    port: int,
    mount: str,
    username: str,
    password: str,
    fmt: str = "mp3",
    bitrate: str | None = None,
) -> list[str]:
    bitrate = bitrate or get_settings().stream_mp3_bitrate
    if not mount.startswith("/"):
        mount = "/" + mount
    url = f"icecast://{username}:{password}@{host}:{port}{mount}"
    if fmt == "ogg":
        codec = ["-c:a", "libvorbis", "-content_type", "application/ogg", "-f", "ogg"]
    else:
        codec = ["-c:a", "libmp3lame", "-content_type", "audio/mpeg", "-f", "mp3"]
    return ["-b:a", bitrate, *codec, url]


def hls_args(playlist_path: str, segment_pattern: str) -> list[str]:
    return [
        "-c:a",
        "aac",
        "-b:a",
        get_settings().stream_mp3_bitrate,
        "-f",
        "hls",
        "-hls_time",
        "4",
        "-hls_list_size",
        "6",
        "-hls_flags",
        "delete_segments+append_list+omit_endlist",
        "-hls_segment_filename",
        segment_pattern,
        playlist_path,
    ]
