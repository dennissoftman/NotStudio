"""Build a publishable ZIP of ordered FLAC tracks and optional track MP4s."""

from __future__ import annotations

import asyncio
import re
import shutil
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from mutagen.flac import FLAC, Picture

from . import video_export
from .models import HistoryItem


def safe_filename(value: str, fallback: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "-", value).strip(" .")
    return cleaned[:120] or fallback


def cue_duration(seconds: float) -> str:
    total_seconds = max(0, int(round(seconds)))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def album_cue(
    album_title: str,
    filenames: list[str],
    titles: list[str],
    durations: list[float],
) -> str:
    lines = [f'TITLE "{album_title.replace(chr(34), chr(39))}"']
    for index, (filename, title, duration) in enumerate(zip(filenames, titles, durations), start=1):
        lines.extend(
            [
                f'FILE "{filename}" WAVE',
                f"  TRACK {index:02d} AUDIO",
                f'    TITLE "{title.replace(chr(34), chr(39))}"',
                "    INDEX 01 00:00:00",
                f"    DURATION {cue_duration(duration)}",
            ]
        )
    return "\n".join(lines) + "\n"


def _apply_album_metadata(
    path: Path,
    *,
    item: HistoryItem,
    album_title: str,
    artist: str,
    index: int,
    total: int,
    cover_path: Path | None,
) -> float:
    audio = FLAC(path)
    audio["album"] = album_title
    audio["title"] = item.title
    audio["tracknumber"] = f"{index}/{total}"
    audio["tracktotal"] = str(total)
    audio["discnumber"] = "1"
    release_date = (audio.get("date") or [datetime.now(UTC).date().isoformat()])[0]
    audio["artist"] = artist
    audio["date"] = release_date
    audio["year"] = release_date[:4]
    if cover_path is not None and cover_path.is_file():
        picture = Picture()
        picture.type = 3
        picture.mime = "image/png"
        picture.desc = "Album cover"
        picture.data = cover_path.read_bytes()
        audio.clear_pictures()
        audio.add_picture(picture)
    audio.save()
    return float(audio.info.length)


def _prepare_tracks(
    album_title: str,
    items: list[HistoryItem],
    temp_dir: Path,
    *,
    artist: str,
    cover_path: Path | None,
) -> tuple[list[str], list[Path], list[float]]:
    archive_names: list[str] = []
    paths: list[Path] = []
    durations: list[float] = []
    total = len(items)
    for index, item in enumerate(items, start=1):
        title = safe_filename(item.title, f"Track {index:02d}")
        archive_name = f"{index:02d} - {title}.flac"
        tagged_copy = temp_dir / archive_name
        shutil.copy2(Path(item.path), tagged_copy)
        durations.append(
            _apply_album_metadata(
                tagged_copy,
                item=item,
                album_title=album_title,
                artist=artist,
                index=index,
                total=total,
                cover_path=cover_path,
            )
        )
        archive_names.append(archive_name)
        paths.append(tagged_copy)
    return archive_names, paths, durations


def _write_archive(
    destination: Path,
    temp_dir: Path,
    *,
    album_title: str,
    album_cue_text: str,
    cover_path: Path | None,
) -> None:
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_STORED) as archive:
        for path in sorted(temp_dir.iterdir()):
            archive.write(path, path.name)
        if cover_path is not None and cover_path.is_file():
            archive.write(cover_path, f"{safe_filename(album_title, 'album')}.png")
        archive.writestr(f"{safe_filename(album_title, 'album')}.cue", album_cue_text)


async def create_album_archive(
    album_title: str,
    items: list[HistoryItem],
    destination: Path,
    *,
    artist: str = "Not Studio",
    cover_path: Path | None = None,
    include_track_videos: bool = False,
) -> None:
    """Package tagged FLACs and, when requested and covered, matching MP4s."""
    with tempfile.TemporaryDirectory(prefix="not-studio-album-") as temp_value:
        temp_dir = Path(temp_value)
        names, paths, durations = await asyncio.to_thread(
            _prepare_tracks,
            album_title,
            items,
            temp_dir,
            artist=artist,
            cover_path=cover_path,
        )
        if include_track_videos and cover_path is not None and cover_path.is_file():
            for path in paths:
                await video_export.render_track_video(path, cover_path, path.with_suffix(".mp4"))
        cue = album_cue(album_title, names, [item.title for item in items], durations)
        await asyncio.to_thread(
            _write_archive,
            Path(destination),
            temp_dir,
            album_title=album_title,
            album_cue_text=cue,
            cover_path=cover_path,
        )
