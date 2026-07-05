### Using with `stable-audio-3`
import argparse
import json
import re
from pathlib import Path

import torch
import torchaudio
from stable_audio_3 import StableAudioModel
from torchaudio.functional import resample

from utils import normalize_loudness, tag_flac


def slugify(value):
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "untitled"


def load_prompt_specs(path):
    with open(path) as f:
        prompts = json.load(f)

    if not isinstance(prompts, list):
        raise ValueError("Prompt file must contain a JSON list")

    for index, item in enumerate(prompts, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Prompt item {index} must be an object")
        if not item.get("title") or not item.get("prompt"):
            raise ValueError(f"Prompt item {index} must include title and prompt")
        if "duration" in item and (
            not isinstance(item["duration"], int | float) or item["duration"] <= 0
        ):
            raise ValueError(f"Prompt item {index} duration must be a positive number")

    return prompts


def save_generated_audio(
    model,
    prompt,
    duration,
    output_path,
    output_rate,
    title,
    genre,
    track_number=None,
    target_lufs=-16.0,
):
    audio = model.generate(
        prompt=prompt,
        duration=duration,
    )
    audio = audio[0].cpu()

    model_sample_rate = model.model.sample_rate
    if output_rate != model_sample_rate:
        audio = resample(audio, model_sample_rate, output_rate)

    if target_lufs is not None:
        # pyloudnorm expects (samples, channels); tensor is (channels, samples)
        normalized = normalize_loudness(
            audio.transpose(0, 1).numpy(), output_rate, target_lufs
        )
        audio = torch.from_numpy(normalized.T.copy()).clamp(-1, 1)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    torchaudio.save(str(output_path), audio, output_rate)
    tag_flac(output_path, title, genre, prompt, track_number)


def main():
    parser = argparse.ArgumentParser(description="Generate audio with Stable Audio 3.")
    parser.add_argument(
        "-d", "--duration", type=float, default=30, help="Duration in seconds"
    )
    parser.add_argument("prompt", nargs="?", help="Audio prompt")
    parser.add_argument(
        "--prompts",
        help='JSON file containing a list of {"title": "...", "prompt": "...", "duration": 60} objects',
    )
    parser.add_argument(
        "-o", "--output", help="Output file path, or output directory with --prompts"
    )
    parser.add_argument(
        "-r", "--rate", type=int, default=44100, help="Output sample rate"
    )
    parser.add_argument("-t", "--title", help="Track title for single-prompt output")
    parser.add_argument(
        "-g",
        "--genre",
        default=None,
        help="Genre tag to write unless a prompt item defines genre",
    )
    parser.add_argument(
        "--lufs",
        type=float,
        default=-16.0,
        help="Loudness normalization target in LUFS",
    )
    parser.add_argument(
        "--no-normalize",
        dest="lufs",
        action="store_const",
        const=None,
        help="Disable loudness normalization.",
    )
    args = parser.parse_args()

    if not (bool(args.prompts) ^ bool(args.prompt)):
        parser.error("provide either a positional prompt or --prompts")

    model = StableAudioModel.from_pretrained("medium")

    if args.prompts:
        output_dir = Path(args.output) if args.output else Path(".")
        output_dir.mkdir(parents=True, exist_ok=True)
        for track_number, item in enumerate(load_prompt_specs(args.prompts), start=1):
            output_path = output_dir / f"{slugify(item['title'])}.flac"
            duration = item.get("duration", args.duration)
            genre = item.get("genre", args.genre)
            save_generated_audio(
                model,
                item["prompt"],
                duration,
                output_path,
                args.rate,
                item["title"],
                genre,
                track_number,
                args.lufs,
            )
            print(f"Saved: {output_path}")
    else:
        output_path = Path(args.output or "generated.flac")
        title = args.title or output_path.stem
        save_generated_audio(
            model,
            args.prompt,
            args.duration,
            output_path,
            args.rate,
            title,
            args.genre,
            target_lufs=args.lufs,
        )
        print(f"Saved: {output_path}")


if __name__ == "__main__":
    main()
