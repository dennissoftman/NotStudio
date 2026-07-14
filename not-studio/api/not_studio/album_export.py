"""Build a publishable ZIP of ordered, metadata-tagged FLAC tracks."""

from __future__ import annotations

import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from mutagen.flac import FLAC

from .models import HistoryItem


def safe_filename(value: str, fallback: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "-", value).strip(" .")
    return cleaned[:120] or fallback


def album_cue(album_title: str, filenames: list[str], titles: list[str]) -> str:
    lines = [f'TITLE "{album_title.replace(chr(34), chr(39))}"']
    for index, (filename, title) in enumerate(zip(filenames, titles), start=1):
        lines.extend(
            [
                f'FILE "{filename}" WAVE',
                f"  TRACK {index:02d} AUDIO",
                f'    TITLE "{title.replace(chr(34), chr(39))}"',
                "    INDEX 01 00:00:00",
            ]
        )
    return "\n".join(lines) + "\n"


def create_album_archive(album_title: str, items: list[HistoryItem], destination: Path) -> None:
    """Copy tracks, apply album metadata, and package them with a multi-file CUE."""
    total = len(items)
    archive_names: list[str] = []
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
            audio.save()
            archive_names.append(archive_name)

        cue_name = f"{safe_filename(album_title, 'album')}.cue"
        cue = album_cue(album_title, archive_names, [item.title for item in items])
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_STORED) as archive:
            for archive_name in archive_names:
                archive.write(temp_dir / archive_name, archive_name)
            archive.writestr(cue_name, cue)
