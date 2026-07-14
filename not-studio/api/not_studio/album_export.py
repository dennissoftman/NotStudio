"""Build a publishable ZIP of ordered, metadata-tagged FLAC tracks."""

from __future__ import annotations

import re
import shutil
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from mutagen.flac import FLAC

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


def create_album_archive(
    album_title: str,
    items: list[HistoryItem],
    destination: Path,
    *,
    artist: str = "Not Studio",
    cover_path: Path | None = None,
) -> None:
    """Copy tracks, apply album metadata, and package them with a multi-file CUE."""
    total = len(items)
    archive_names: list[str] = []
    durations: list[float] = []
    with tempfile.TemporaryDirectory(prefix="not-studio-album-") as temp_value:
        temp_dir = Path(temp_value)
        for index, item in enumerate(items, start=1):
            source = Path(item.path)
            title = safe_filename(item.title, f"Track {index:02d}")
            archive_name = f"{index:02d} - {title}.flac"
            tagged_copy = temp_dir / archive_name
            shutil.copy2(source, tagged_copy)

            audio = FLAC(tagged_copy)
            audio["album"] = album_title
            audio["title"] = item.title
            audio["tracknumber"] = f"{index}/{total}"
            audio["tracktotal"] = str(total)
            audio["discnumber"] = "1"
            release_date = (audio.get("date") or [datetime.now(UTC).date().isoformat()])[0]
            audio["artist"] = artist
            audio["date"] = release_date
            audio["year"] = release_date[:4]
            audio.save()
            archive_names.append(archive_name)
            durations.append(float(audio.info.length))

        cue_name = f"{safe_filename(album_title, 'album')}.cue"
        cue = album_cue(
            album_title,
            archive_names,
            [item.title for item in items],
            durations,
        )
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_STORED) as archive:
            for archive_name in archive_names:
                archive.write(temp_dir / archive_name, archive_name)
            if cover_path is not None and cover_path.is_file():
                archive.write(cover_path, f"{safe_filename(album_title, 'album')}.png")
            archive.writestr(cue_name, cue)
