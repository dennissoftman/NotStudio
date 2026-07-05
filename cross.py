import argparse
from pathlib import Path

import numpy as np
import torch
import torchaudio
from mutagen import File
from torchaudio.functional import resample
from utils import normalize_loudness, tag_flac


def crossfade(a, b, sr, seconds=4):
    n = int(sr * seconds)
    if n <= 0:
        return np.concatenate([a, b])
    if len(a) < n or len(b) < n:
        raise ValueError("Audio files must be longer than the crossfade duration")

    t = np.linspace(0, 1, n).reshape(-1, 1)  # column vector -> works for mono & stereo
    fade_out = np.cos(t * np.pi / 2)
    fade_in = np.sin(t * np.pi / 2)
    overlap = a[-n:] * fade_out + b[:n] * fade_in
    return np.concatenate([a[:-n], overlap, b[n:]])


def load_audio(path, target_sample_rate=None):
    audio, sample_rate = torchaudio.load(path)
    if target_sample_rate is not None and sample_rate != target_sample_rate:
        audio = resample(audio, sample_rate, target_sample_rate)
        sample_rate = target_sample_rate

    return audio.transpose(0, 1).numpy(), sample_rate


def match_channels(a, b):
    if a.shape[1] == b.shape[1]:
        return a, b
    if a.shape[1] == 1:
        return np.repeat(a, b.shape[1], axis=1), b
    if b.shape[1] == 1:
        return a, np.repeat(b, a.shape[1], axis=1)
    raise ValueError(
        f"Cannot mix {a.shape[1]}-channel audio with {b.shape[1]}-channel audio"
    )


def get_audio_tag(path, key):
    audio = File(path, easy=True)
    if audio is None:
        return None

    value = audio.get(key)
    if not value:
        return None
    return value[0]


def get_track_title(path):
    return get_audio_tag(path, "title") or Path(path).stem


def get_track_genre(path):
    return get_audio_tag(path, "genre")


def combine_audio_files(paths, fade_length=4, target_lufs=-16.0):
    combined, sample_rate = load_audio(paths[0])
    combined = normalize_loudness(combined, sample_rate, target_lufs)
    track_starts = [0]

    for path in paths[1:]:
        next_audio, _ = load_audio(path, sample_rate)
        next_audio = normalize_loudness(next_audio, sample_rate, target_lufs)
        combined, next_audio = match_channels(combined, next_audio)
        fade_samples = int(sample_rate * fade_length)
        track_starts.append(max(len(combined) - fade_samples, 0))
        combined = crossfade(combined, next_audio, sample_rate, fade_length)

    return combined, sample_rate, track_starts


def cue_timestamp(sample_index, sample_rate):
    total_frames = round(sample_index * 75 / sample_rate)
    minutes, remainder = divmod(total_frames, 75 * 60)
    seconds, frames = divmod(remainder, 75)
    return f"{minutes:02d}:{seconds:02d}:{frames:02d}"


def cue_quote(value):
    return value.replace('"', "'")


def write_cue(path, audio_filename, titles, starts, sample_rate, genre=None):
    lines = [f'FILE "{cue_quote(audio_filename)}" FLAC']
    for index, (title, start) in enumerate(zip(titles, starts), start=1):
        lines.extend(
            [
                f"  TRACK {index:02d} AUDIO",
                f'    TITLE "{cue_quote(title)}"',
            ]
        )
        if genre:
            lines.append(f'    REM GENRE "{cue_quote(genre)}"')
        lines.append(f"    INDEX 01 {cue_timestamp(start, sample_rate)}")

    path.write_text("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Crossfade audio files into one output file."
    )
    parser.add_argument(
        "inputs", nargs="+", help="Input audio files, in playback order"
    )
    parser.add_argument(
        "-o", "--output", default="output.flac", help="Output audio file path"
    )
    parser.add_argument(
        "-d",
        "--duration",
        type=float,
        default=4,
        help="Crossfade length in seconds",
    )
    parser.add_argument(
        "-g",
        "--genre",
        help="Genre tag override. Defaults to the first input file's genre tag.",
    )
    parser.add_argument(
        "--lufs",
        type=float,
        default=-16.0,
        help="Per-track loudness normalization target in LUFS. Use 'none' to disable.",
    )
    parser.add_argument(
        "--no-normalize",
        dest="lufs",
        action="store_const",
        const=None,
        help="Disable per-track loudness normalization.",
    )
    args = parser.parse_args()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    combined, sample_rate, starts = combine_audio_files(
        args.inputs, args.duration, args.lufs
    )
    output = torch.from_numpy(combined.T.astype(np.float32)).clamp(-1, 1)
    torchaudio.save(str(output_path), output, sample_rate)

    genre = args.genre or get_track_genre(args.inputs[0])
    tag_flac(output_path, output_path.stem, genre)
    cue_path = output_path.with_suffix(".cue")
    write_cue(
        cue_path,
        output_path.name,
        [get_track_title(path) for path in args.inputs],
        starts,
        sample_rate,
        genre,
    )
    print(f"Saved: {output_path}")
    print(f"Saved: {cue_path}")


if __name__ == "__main__":
    main()
