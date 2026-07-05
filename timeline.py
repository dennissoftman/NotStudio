from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

TIMELINE_CUE_TYPES = frozenset(
    {
        "speech",
        "music_bed",
        "music_track",
        "sfx",
        "mark",
    }
)


class TimelineParseError(ValueError):
    """Raised when a WebVTT timeline cannot be parsed or validated."""


@dataclass(frozen=True)
class TimelineCue:
    identifier: str | None
    start: float
    end: float
    text: str = ""
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def type(self) -> str | None:
        return self.metadata.get("type")

    def require_type(self) -> str:
        cue_type = self.type
        if not cue_type:
            label = self.identifier or format_timestamp(self.start)
            raise TimelineParseError(f"Timeline cue {label} is missing NOTE type=...")
        return cue_type


@dataclass(frozen=True)
class Timeline:
    metadata: dict[str, str]
    cues: tuple[TimelineCue, ...]

    def cues_by_type(self, cue_type: str) -> tuple[TimelineCue, ...]:
        return tuple(cue for cue in self.cues if cue.type == cue_type)

    @property
    def speech_cues(self) -> tuple[TimelineCue, ...]:
        return self.cues_by_type("speech")

    @property
    def asset_cues(self) -> tuple[TimelineCue, ...]:
        return tuple(
            cue for cue in self.cues if cue.type in {"music_bed", "music_track", "sfx"}
        )

    @property
    def marker_cues(self) -> tuple[TimelineCue, ...]:
        return self.cues_by_type("mark")


def load_timeline(path: str | Path) -> Timeline:
    return parse_webvtt_timeline(Path(path).read_text(encoding="utf-8"))


def parse_webvtt_timeline(text: str) -> Timeline:
    lines = text.splitlines()
    if lines and lines[0].startswith("\ufeff"):
        lines[0] = lines[0].lstrip("\ufeff")
    if not lines or lines[0].strip() != "WEBVTT":
        raise TimelineParseError("Timeline must start with WEBVTT.")

    metadata: dict[str, str] = {}
    cues: list[TimelineCue] = []
    index = 1

    while index < len(lines):
        index = _skip_blank(lines, index)
        if index >= len(lines):
            break

        line = lines[index].strip()
        if line.startswith("NOTE ") and "-->" not in line:
            key, value = _parse_note(line, index + 1)
            metadata[key] = value
            index += 1
            continue

        cue, index = _parse_cue(lines, index)
        cues.append(cue)

    timeline = Timeline(metadata=metadata, cues=tuple(cues))
    validate_timeline(timeline)
    return timeline


def validate_timeline(timeline: Timeline) -> None:
    for cue in timeline.cues:
        if cue.end < cue.start:
            raise TimelineParseError(
                "Timeline cue "
                f"{cue.identifier or format_timestamp(cue.start)} ends before it starts."
            )
        cue_type = cue.require_type()
        if cue_type not in TIMELINE_CUE_TYPES:
            raise TimelineParseError(f"Unsupported timeline cue type: {cue_type}")
        if cue_type == "speech" and cue.end <= cue.start:
            raise TimelineParseError(
                "Speech timeline cues must have positive duration."
            )
        if cue_type == "speech" and not cue.text.strip():
            raise TimelineParseError("Speech timeline cues must include spoken text.")
        if cue_type in {"music_bed", "music_track", "sfx"} and not cue.metadata.get(
            "asset"
        ):
            raise TimelineParseError(
                f"{cue_type} timeline cues must include NOTE asset=..."
            )

    previous_speech_end = -1.0
    for cue in timeline.speech_cues:
        if cue.start < previous_speech_end:
            raise TimelineParseError(
                "Overlapping speech timeline cues are not supported."
            )
        previous_speech_end = cue.end


def timeline_looks_typed(path: str | Path) -> bool:
    suffix = Path(path).suffix.lower()
    if suffix not in {".vtt", ".webvtt"}:
        return False

    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return False

    return any(line.strip().startswith("NOTE type=") for line in text.splitlines())


def timeline_summary(timeline: Timeline) -> str:
    counts = {}
    for cue in timeline.cues:
        counts[cue.require_type()] = counts.get(cue.require_type(), 0) + 1

    parts = [f"{counts[key]} {key}" for key in sorted(counts)]
    assets = {
        cue.metadata["asset"] for cue in timeline.asset_cues if "asset" in cue.metadata
    }
    if assets:
        parts.append(f"{len(assets)} asset refs")
    return ", ".join(parts) or "0 cues"


def _parse_cue(lines: list[str], index: int) -> tuple[TimelineCue, int]:
    identifier = None
    timing_line = lines[index].strip()

    if "-->" not in timing_line:
        identifier = timing_line or None
        index += 1
        if index >= len(lines):
            raise TimelineParseError(f"Cue {identifier} is missing a timing line.")
        timing_line = lines[index].strip()

    if "-->" not in timing_line:
        raise TimelineParseError(f"Invalid timeline timing line: {timing_line}")

    start_text, end_text = [
        part.strip().split()[0] for part in timing_line.split("-->", 1)
    ]
    start = parse_timestamp(start_text)
    end = parse_timestamp(end_text)
    index += 1
    index = _skip_blank(lines, index)

    text_lines: list[str] = []
    cue_metadata: dict[str, str] = {}
    while index < len(lines) and lines[index].strip():
        line = lines[index].strip()
        if line.startswith("NOTE "):
            key, value = _parse_note(line, index + 1)
            cue_metadata[key] = value
        else:
            text_lines.append(lines[index])
        index += 1

    return (
        TimelineCue(
            identifier=identifier,
            start=start,
            end=end,
            text=_normalize_text_lines(text_lines),
            metadata=cue_metadata,
        ),
        index,
    )


def _parse_note(line: str, line_number: int) -> tuple[str, str]:
    payload = line[5:].strip()
    if "=" not in payload:
        raise TimelineParseError(f"NOTE on line {line_number} must use key=value.")
    key, value = payload.split("=", 1)
    key = key.strip()
    if not key:
        raise TimelineParseError(f"NOTE on line {line_number} has an empty key.")
    return key, value.strip()


def _skip_blank(lines: list[str], index: int) -> int:
    while index < len(lines) and not lines[index].strip():
        index += 1
    return index


def _normalize_text_lines(lines: list[str]) -> str:
    text = "\n".join(lines).strip()
    if text.startswith("<v ") and ">" in text:
        text = text.split(">", 1)[1]
    return text.strip()


def parse_timestamp(value: str) -> float:
    try:
        hours_text, minutes_text, seconds_text = value.split(":")
        seconds_parts = seconds_text.split(".", 1)
        seconds = int(seconds_parts[0])
        milliseconds = (
            int(seconds_parts[1].ljust(3, "0")[:3]) if len(seconds_parts) == 2 else 0
        )
        return (
            int(hours_text) * 3600
            + int(minutes_text) * 60
            + seconds
            + milliseconds / 1000
        )
    except (TypeError, ValueError) as exc:
        raise TimelineParseError(f"Invalid WebVTT timestamp: {value}") from exc


def format_timestamp(seconds: float) -> str:
    milliseconds_total = round(seconds * 1000)
    hours, remainder = divmod(milliseconds_total, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds_part, milliseconds = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{seconds_part:02}.{milliseconds:03}"
