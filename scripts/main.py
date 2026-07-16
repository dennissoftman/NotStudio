"""Standalone prompt-to-music generation with ACE-Step."""

import argparse
import json
import re
from pathlib import Path

import torch
import torchaudio
from acestep.handler import AceStepHandler
from acestep.inference import GenerationConfig, GenerationParams, generate_music
from torchaudio.functional import resample
from utils import normalize_loudness, tag_flac


def slugify(value):
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "untitled"


def load_prompt_specs(path):
    with open(path) as file:
        prompts = json.load(file)
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


def load_model():
    model = AceStepHandler()
    status, ready = model.initialize_service(
        project_root="",
        config_path="acestep-v15-sft",
        device="auto",
    )
    if not ready:
        raise RuntimeError(f"ACE-Step 1.5 failed to initialize: {status}")
    return model


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
    raw_path = output_path.with_suffix(".ace-step.wav")
    result = generate_music(
        model,
        None,
        GenerationParams(
            task_type="text2music",
            caption=prompt,
            lyrics="[Instrumental]",
            instrumental=True,
            duration=duration,
            inference_steps=50,
            guidance_scale=7.0,
            thinking=False,
            use_cot_metas=False,
            use_cot_caption=False,
            use_cot_language=False,
            shift=1.0,
        ),
        GenerationConfig(batch_size=1, audio_format="wav"),
        save_dir=str(output_path.parent),
    )
    if not result.success:
        raise RuntimeError(f"ACE-Step 1.5 generation failed: {result.error}")
    generated_path = Path(result.audios[0]["path"]) if result.audios else raw_path
    try:
        audio, model_rate = torchaudio.load(generated_path)
        if output_rate != model_rate:
            audio = resample(audio, model_rate, output_rate)
        if target_lufs is not None:
            normalized = normalize_loudness(
                audio.transpose(0, 1).numpy(), output_rate, target_lufs
            )
            audio = torch.from_numpy(normalized.T.copy()).clamp(-1, 1)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        torchaudio.save(str(output_path), audio, output_rate)
        tag_flac(output_path, title, genre, prompt, track_number)
    finally:
        generated_path.unlink(missing_ok=True)
        generated_path.with_suffix(".json").unlink(missing_ok=True)
        generated_path.with_name(f"{generated_path.stem}_input_params.json").unlink(
            missing_ok=True
        )


def main():
    parser = argparse.ArgumentParser(
        description="Generate text-to-music audio with ACE-Step."
    )
    parser.add_argument(
        "-d", "--duration", type=float, default=30, help="Duration in seconds"
    )
    parser.add_argument("prompt", nargs="?", help="Audio prompt")
    parser.add_argument(
        "--prompts",
        help='JSON file containing a list of {"title": "...", "prompt": "...", "duration": 60} objects',
    )
    parser.add_argument(
        "-o", "--output", help="Output file, or output directory with --prompts"
    )
    parser.add_argument(
        "-r", "--rate", type=int, default=44100, help="Output sample rate"
    )
    parser.add_argument("-t", "--title", help="Track title for single-prompt output")
    parser.add_argument("-g", "--genre", default=None, help="Genre tag")
    parser.add_argument(
        "--lufs", type=float, default=-16.0, help="Loudness target in LUFS"
    )
    parser.add_argument(
        "--no-normalize",
        dest="lufs",
        action="store_const",
        const=None,
        help="Disable loudness normalization",
    )
    args = parser.parse_args()
    if not (bool(args.prompts) ^ bool(args.prompt)):
        parser.error("provide either a positional prompt or --prompts")

    print("Loading ACE-Step")
    model = load_model()
    if args.prompts:
        output_dir = Path(args.output) if args.output else Path(".")
        output_dir.mkdir(parents=True, exist_ok=True)
        for track_number, item in enumerate(load_prompt_specs(args.prompts), start=1):
            output_path = output_dir / f"{slugify(item['title'])}.flac"
            save_generated_audio(
                model,
                item["prompt"],
                item.get("duration", args.duration),
                output_path,
                args.rate,
                item["title"],
                item.get("genre", args.genre),
                track_number,
                args.lufs,
            )
            print(f"Saved: {output_path}")
    else:
        output_path = Path(args.output or "generated.flac")
        save_generated_audio(
            model,
            args.prompt,
            args.duration,
            output_path,
            args.rate,
            args.title or output_path.stem,
            args.genre,
            target_lufs=args.lufs,
        )
        print(f"Saved: {output_path}")


if __name__ == "__main__":
    main()
