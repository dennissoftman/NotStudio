import argparse
import queue
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias

import miniaudio
import numpy as np
import pysubs2
import torch
from kokoro import KPipeline
from tqdm.auto import tqdm

from timeline import load_timeline, timeline_looks_typed, timeline_summary
from utils import (
    clean_spoken_text,
    count_spoken_words,
    prepare_mono_audio_output,
    write_audio_file,
)

KOKORO_SAMPLE_RATE = 24000
KOKORO_REPO_ID = "hexgrad/Kokoro-82M"
DEFAULT_OUTPUT_SAMPLE_RATE = 44100
DEFAULT_VOICE = "am_michael"
DEFAULT_NEWS_SPEED = 1.0
DEFAULT_REFERENCE_WPM = 185
MIN_NEWS_SPEED = 0.9
MAX_NEWS_SPEED = 1.1
DEFAULT_PLAYBACK_BUFFER_SECONDS = 2.0
DEFAULT_PLAYBACK_QUEUE_SIZE = 64

AmericanFemaleVoice: TypeAlias = Literal[
    "af_alloy",
    "af_aoede",
    "af_bella",
    "af_heart",
    "af_jessica",
    "af_kore",
    "af_nicole",
    "af_nova",
    "af_river",
    "af_sarah",
    "af_sky",
]
AmericanMaleVoice: TypeAlias = Literal[
    "am_adam",
    "am_echo",
    "am_eric",
    "am_fenrir",
    "am_liam",
    "am_michael",
    "am_onyx",
    "am_puck",
    "am_santa",
]
BritishFemaleVoice: TypeAlias = Literal[
    "bf_alice",
    "bf_emma",
    "bf_isabella",
    "bf_lily",
]
BritishMaleVoice: TypeAlias = Literal[
    "bm_daniel",
    "bm_fable",
    "bm_george",
    "bm_lewis",
]
KokoroEnglishVoice: TypeAlias = (
    AmericanFemaleVoice | AmericanMaleVoice | BritishFemaleVoice | BritishMaleVoice
)
TorchDevice: TypeAlias = Literal["auto", "cpu", "cuda", "mps"]

AMERICAN_FEMALE_VOICES: tuple[AmericanFemaleVoice, ...] = (
    "af_alloy",
    "af_aoede",
    "af_bella",
    "af_heart",
    "af_jessica",
    "af_kore",
    "af_nicole",
    "af_nova",
    "af_river",
    "af_sarah",
    "af_sky",
)
AMERICAN_MALE_VOICES: tuple[AmericanMaleVoice, ...] = (
    "am_adam",
    "am_echo",
    "am_eric",
    "am_fenrir",
    "am_liam",
    "am_michael",
    "am_onyx",
    "am_puck",
    "am_santa",
)
BRITISH_FEMALE_VOICES: tuple[BritishFemaleVoice, ...] = (
    "bf_alice",
    "bf_emma",
    "bf_isabella",
    "bf_lily",
)
BRITISH_MALE_VOICES: tuple[BritishMaleVoice, ...] = (
    "bm_daniel",
    "bm_fable",
    "bm_george",
    "bm_lewis",
)
KOKORO_ENGLISH_VOICES: tuple[KokoroEnglishVoice, ...] = (
    *AMERICAN_FEMALE_VOICES,
    *AMERICAN_MALE_VOICES,
    *BRITISH_FEMALE_VOICES,
    *BRITISH_MALE_VOICES,
)


@dataclass(frozen=True)
class CaptionCue:
    index: int | None
    start: float
    end: float
    text: str

    @property
    def duration(self):
        return self.end - self.start


def lang_code_for_voice(voice: KokoroEnglishVoice) -> Literal["a", "b"]:
    if voice.startswith("a"):
        return "a"
    if voice.startswith("b"):
        return "b"
    raise ValueError(f"Unsupported English Kokoro voice: {voice}")


def speed_for_target_wpm(
    target_wpm: float,
    reference_wpm: float = DEFAULT_REFERENCE_WPM,
    base_speed: float = DEFAULT_NEWS_SPEED,
    min_speed: float = MIN_NEWS_SPEED,
    max_speed: float = MAX_NEWS_SPEED,
) -> float:
    if target_wpm <= 0:
        raise ValueError("target_wpm must be positive")
    if reference_wpm <= 0:
        raise ValueError("reference_wpm must be positive")

    speed = base_speed * target_wpm / reference_wpm
    return min(max(speed, min_speed), max_speed)


def available_accelerators():
    devices = []
    if torch.cuda.is_available():
        devices.append("cuda")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        devices.append("mps")
    return devices


def resolve_torch_device(device: TorchDevice = "auto", require_accelerator=False):
    accelerators = available_accelerators()

    if device == "auto":
        resolved = accelerators[0] if accelerators else "cpu"
    elif device == "cuda":
        if not torch.cuda.is_available():
            raise ValueError("CUDA was requested but is not available.")
        resolved = "cuda"
    elif device == "mps":
        if not (hasattr(torch.backends, "mps") and torch.backends.mps.is_available()):
            raise ValueError("MPS was requested but is not available.")
        resolved = "mps"
    elif device == "cpu":
        resolved = "cpu"
    else:
        raise ValueError(f"Unsupported torch device: {device}")

    if require_accelerator and resolved == "cpu":
        raise ValueError(
            "No hardware accelerator is available; refusing to run on CPU."
        )

    return resolved


def describe_torch_device(device):
    if device == "cuda":
        return f"cuda ({torch.cuda.get_device_name(0)})"
    if device == "mps":
        return "mps (Apple Metal)"
    return "cpu"


def speed_for_caption_cue(
    cue: CaptionCue,
    reference_wpm: float = DEFAULT_REFERENCE_WPM,
    base_speed: float = DEFAULT_NEWS_SPEED,
    min_speed: float = MIN_NEWS_SPEED,
    max_speed: float = MAX_NEWS_SPEED,
):
    words = count_spoken_words(cue.text)
    if words == 0 or cue.duration <= 0:
        return base_speed, 0.0, words, False

    target_wpm = words * 60 / cue.duration
    unclamped = base_speed * target_wpm / reference_wpm
    speed = min(max(unclamped, min_speed), max_speed)
    return speed, target_wpm, words, speed != unclamped


def print_voice_list():
    groups = (
        ("American female", AMERICAN_FEMALE_VOICES),
        ("American male", AMERICAN_MALE_VOICES),
        ("British female", BRITISH_FEMALE_VOICES),
        ("British male", BRITISH_MALE_VOICES),
    )
    for label, voices in groups:
        print(f"{label}: {', '.join(voices)}")


def read_text(args):
    if args.text_file:
        return Path(args.text_file).read_text(encoding="utf-8")
    if args.text:
        return args.text
    if not sys.stdin.isatty():
        return sys.stdin.read()
    raise ValueError("Provide text, --text-file, or pipe text on stdin.")


def caption_format_from_path(path):
    suffix = Path(path).suffix.lower()
    if suffix == ".srt":
        return "srt"
    if suffix in {".vtt", ".webvtt"}:
        return "vtt"
    return None


def cues_from_subtitles(subtitles):
    cues = []
    previous_end = -1.0

    for event_index, event in enumerate(subtitles.events, start=1):
        text = clean_spoken_text(event.plaintext)
        if not text:
            continue

        start = event.start / 1000
        end = event.end / 1000
        if end <= start:
            raise ValueError(f"Caption cue ends before it starts: {text}")
        if start < previous_end:
            raise ValueError("Overlapping caption cues are not supported.")

        cues.append(CaptionCue(event_index, start, end, text))
        previous_end = end

    if not cues:
        raise ValueError("No SRT/WebVTT cues found.")

    return cues


def cues_from_timeline(timeline):
    cues = []
    for index, cue in enumerate(timeline.speech_cues, start=1):
        cues.append(
            CaptionCue(
                index=index,
                start=cue.start,
                end=cue.end,
                text=clean_spoken_text(cue.text),
            )
        )

    if not cues:
        raise ValueError("Timeline does not contain any speech cues.")

    return cues


def parse_captions(caption_text, format_=None):
    subtitles = pysubs2.SSAFile.from_string(caption_text, format_=format_)
    return cues_from_subtitles(subtitles)


def load_captions(path):
    if timeline_looks_typed(path):
        return cues_from_timeline(load_timeline(path))

    subtitles = pysubs2.load(
        path, encoding="utf-8", format_=caption_format_from_path(path)
    )
    return cues_from_subtitles(subtitles)


def synthesize_speech(
    text,
    voice: KokoroEnglishVoice = DEFAULT_VOICE,
    speed=DEFAULT_NEWS_SPEED,
    lang_code: Literal["a", "b"] | None = None,
    device: str | None = None,
    split_pattern=r"\n+",
    pause_seconds=0.18,
    print_chunks=False,
    progress=False,
):
    chunks = list(
        iter_speech_chunks(
            text=text,
            voice=voice,
            speed=speed,
            lang_code=lang_code,
            device=device,
            split_pattern=split_pattern,
            pause_seconds=pause_seconds,
            print_chunks=print_chunks,
            progress=progress,
        )
    )
    if not chunks:
        raise RuntimeError("Kokoro did not produce audio.")

    return np.concatenate(chunks)


def iter_speech_chunks(
    text,
    voice: KokoroEnglishVoice = DEFAULT_VOICE,
    speed=DEFAULT_NEWS_SPEED,
    lang_code: Literal["a", "b"] | None = None,
    device: str | None = None,
    pipeline=None,
    split_pattern=r"\n+",
    pause_seconds=0.18,
    print_chunks=False,
    progress=False,
):
    text = clean_spoken_text(text)
    if not text:
        raise ValueError("Speech text is empty.")

    if pipeline is None:
        pipeline = KPipeline(
            lang_code=lang_code or lang_code_for_voice(voice),
            repo_id=KOKORO_REPO_ID,
            device=device,
        )
    generator = pipeline(
        text,
        voice=voice,
        speed=speed,
        split_pattern=split_pattern,
    )

    pause = np.zeros(int(KOKORO_SAMPLE_RATE * pause_seconds), dtype=np.float32)
    pending = None
    if progress:
        generator = tqdm(generator, desc="Generating speech", unit="chunk")

    for index, (graphemes, phonemes, audio) in enumerate(generator):
        if print_chunks:
            print(f"[{index}] {graphemes}")
            print(phonemes)

        audio = np.asarray(audio, dtype=np.float32)
        if audio.ndim != 1:
            audio = audio.reshape(-1)

        if len(audio):
            if pending is not None:
                yield pending
                if len(pause):
                    yield pause
            pending = audio

    if pending is None:
        raise RuntimeError("Kokoro did not produce audio.")

    yield pending


def iter_caption_speech_chunks(
    cues,
    voice: KokoroEnglishVoice = DEFAULT_VOICE,
    base_speed=DEFAULT_NEWS_SPEED,
    lang_code: Literal["a", "b"] | None = None,
    device: str | None = None,
    print_chunks=False,
    print_cue_timing=False,
    progress=False,
):
    cursor = 0
    pipeline = KPipeline(
        lang_code=lang_code or lang_code_for_voice(voice),
        repo_id=KOKORO_REPO_ID,
        device=device,
    )
    cue_iterable = cues
    if progress:
        cue_iterable = tqdm(cues, desc="Generating caption cues", unit="cue")

    for fallback_index, cue in enumerate(cue_iterable, start=1):
        start_sample = round(cue.start * KOKORO_SAMPLE_RATE)
        if start_sample > cursor:
            yield np.zeros(start_sample - cursor, dtype=np.float32)
            cursor = start_sample

        speed, target_wpm, words, clamped = speed_for_caption_cue(
            cue,
            base_speed=base_speed,
        )
        cue_label = cue.index if cue.index is not None else fallback_index
        if print_cue_timing:
            clamped_note = " clamped" if clamped else ""
            print(
                f"Cue {cue_label}: {words} words over {cue.duration:.2f}s, "
                f"{target_wpm:.1f} WPM -> speed {speed:.2f}{clamped_note}"
            )

        cue_samples = 0
        for chunk in iter_speech_chunks(
            cue.text,
            voice=voice,
            speed=speed,
            lang_code=lang_code,
            device=device,
            pipeline=pipeline,
            pause_seconds=0,
            print_chunks=print_chunks,
        ):
            cue_samples += len(chunk)
            yield chunk

        cursor += cue_samples
        cue_end_sample = round(cue.end * KOKORO_SAMPLE_RATE)
        if cursor < cue_end_sample:
            yield np.zeros(cue_end_sample - cursor, dtype=np.float32)
            cursor = cue_end_sample
        elif print_cue_timing and cursor > cue_end_sample:
            overrun = (cursor - cue_end_sample) / KOKORO_SAMPLE_RATE
            print(f"Cue {cue_label}: generated speech overruns cue by {overrun:.2f}s.")


def synthesize_caption_speech(
    cues,
    voice: KokoroEnglishVoice = DEFAULT_VOICE,
    base_speed=DEFAULT_NEWS_SPEED,
    lang_code: Literal["a", "b"] | None = None,
    device: str | None = None,
    print_chunks=False,
    print_cue_timing=False,
    progress=False,
):
    chunks = list(
        iter_caption_speech_chunks(
            cues,
            voice=voice,
            base_speed=base_speed,
            lang_code=lang_code,
            device=device,
            print_chunks=print_chunks,
            print_cue_timing=print_cue_timing,
            progress=progress,
        )
    )
    if not chunks:
        raise RuntimeError("Kokoro did not produce caption audio.")

    return np.concatenate(chunks)


def miniaudio_stream_from_queue(audio_queue, done, stats=None):
    current = np.empty(0, dtype=np.float32)
    requested_frames = yield b""
    stats = stats if stats is not None else {}
    stats.setdefault("underruns", 0)

    while True:
        requested_frames = requested_frames or 1024

        while len(current) < requested_frames and not done.is_set():
            try:
                chunk = audio_queue.get(timeout=0.05)
            except queue.Empty:
                stats["underruns"] += 1
                break
            if chunk is None:
                done.set()
                break
            current = np.concatenate([current, chunk])

        if len(current) == 0 and done.is_set():
            return

        output = current[:requested_frames]
        current = current[requested_frames:]
        if len(output) < requested_frames:
            output = np.pad(output, (0, requested_frames - len(output)))

        requested_frames = yield output.astype(np.float32).tobytes()


def wait_for_prebuffer(
    producer,
    audio_queue,
    produced_samples,
    lock,
    playback_rate,
    buffer_seconds,
    errors,
):
    target_samples = max(0, int(playback_rate * buffer_seconds))
    if target_samples == 0:
        return

    while producer.is_alive() and not errors:
        with lock:
            ready_samples = produced_samples[0]
        if ready_samples >= target_samples:
            return
        if audio_queue.full():
            return
        time.sleep(0.05)


def play_speech(
    text,
    voice: KokoroEnglishVoice = DEFAULT_VOICE,
    speed=DEFAULT_NEWS_SPEED,
    target_wpm=None,
    lang_code: Literal["a", "b"] | None = None,
    device: str | None = None,
    playback_rate=DEFAULT_OUTPUT_SAMPLE_RATE,
    buffer_seconds=DEFAULT_PLAYBACK_BUFFER_SECONDS,
    queue_size=DEFAULT_PLAYBACK_QUEUE_SIZE,
    print_chunks=False,
    progress=False,
):
    if target_wpm is not None:
        speed = speed_for_target_wpm(target_wpm)

    audio_queue = queue.Queue(maxsize=queue_size)
    done = threading.Event()
    produced_samples = [0]
    produced_samples_lock = threading.Lock()
    errors = []

    def produce_audio():
        try:
            for chunk in iter_speech_chunks(
                text=text,
                voice=voice,
                speed=speed,
                lang_code=lang_code,
                device=device,
                print_chunks=print_chunks,
                progress=progress,
            ):
                chunk = prepare_mono_audio_output(
                    chunk,
                    source_rate=KOKORO_SAMPLE_RATE,
                    output_rate=playback_rate,
                    target_lufs=None,
                )
                with produced_samples_lock:
                    produced_samples[0] += len(chunk)
                audio_queue.put(chunk.astype(np.float32))
        except Exception as exc:
            errors.append(exc)
        finally:
            audio_queue.put(None)

    producer = threading.Thread(target=produce_audio, daemon=True)
    producer.start()
    wait_for_prebuffer(
        producer,
        audio_queue,
        produced_samples,
        produced_samples_lock,
        playback_rate,
        buffer_seconds,
        errors,
    )
    if errors:
        raise errors[0]

    playback_stats = {}
    stream = miniaudio_stream_from_queue(audio_queue, done, playback_stats)
    next(stream)

    with miniaudio.PlaybackDevice(
        output_format=miniaudio.SampleFormat.FLOAT32,
        nchannels=1,
        sample_rate=playback_rate,
        app_name="NeuralRadio",
    ) as playback_device:
        playback_device.start(stream)
        while producer.is_alive() or not done.is_set():
            time.sleep(0.05)

    producer.join()
    if errors:
        raise errors[0]
    if playback_stats.get("underruns"):
        print(f"Playback buffer underruns: {playback_stats['underruns']}")


def play_captions(
    cues,
    voice: KokoroEnglishVoice = DEFAULT_VOICE,
    speed=DEFAULT_NEWS_SPEED,
    lang_code: Literal["a", "b"] | None = None,
    device: str | None = None,
    playback_rate=DEFAULT_OUTPUT_SAMPLE_RATE,
    buffer_seconds=DEFAULT_PLAYBACK_BUFFER_SECONDS,
    queue_size=DEFAULT_PLAYBACK_QUEUE_SIZE,
    print_chunks=False,
    print_cue_timing=False,
    progress=False,
):
    audio_queue = queue.Queue(maxsize=queue_size)
    done = threading.Event()
    produced_samples = [0]
    produced_samples_lock = threading.Lock()
    errors = []

    def produce_audio():
        try:
            for chunk in iter_caption_speech_chunks(
                cues,
                voice=voice,
                base_speed=speed,
                lang_code=lang_code,
                device=device,
                print_chunks=print_chunks,
                print_cue_timing=print_cue_timing,
                progress=progress,
            ):
                chunk = prepare_mono_audio_output(
                    chunk,
                    source_rate=KOKORO_SAMPLE_RATE,
                    output_rate=playback_rate,
                    target_lufs=None,
                )
                with produced_samples_lock:
                    produced_samples[0] += len(chunk)
                audio_queue.put(chunk.astype(np.float32))
        except Exception as exc:
            errors.append(exc)
        finally:
            audio_queue.put(None)

    producer = threading.Thread(target=produce_audio, daemon=True)
    producer.start()
    wait_for_prebuffer(
        producer,
        audio_queue,
        produced_samples,
        produced_samples_lock,
        playback_rate,
        buffer_seconds,
        errors,
    )
    if errors:
        raise errors[0]

    playback_stats = {}
    stream = miniaudio_stream_from_queue(audio_queue, done, playback_stats)
    next(stream)

    with miniaudio.PlaybackDevice(
        output_format=miniaudio.SampleFormat.FLOAT32,
        nchannels=1,
        sample_rate=playback_rate,
        app_name="NeuralRadio",
    ) as playback_device:
        playback_device.start(stream)
        while producer.is_alive() or not done.is_set():
            time.sleep(0.05)

    producer.join()
    if errors:
        raise errors[0]
    if playback_stats.get("underruns"):
        print(f"Playback buffer underruns: {playback_stats['underruns']}")


def save_speech(
    text,
    output_path,
    voice: KokoroEnglishVoice = DEFAULT_VOICE,
    speed=DEFAULT_NEWS_SPEED,
    target_wpm=None,
    lang_code: Literal["a", "b"] | None = None,
    device: str | None = None,
    output_rate=DEFAULT_OUTPUT_SAMPLE_RATE,
    target_lufs=-16.0,
    title=None,
    genre="News",
    description=None,
    print_chunks=False,
    progress=False,
):
    if target_wpm is not None:
        speed = speed_for_target_wpm(target_wpm)

    audio = synthesize_speech(
        text=text,
        voice=voice,
        speed=speed,
        lang_code=lang_code,
        device=device,
        print_chunks=print_chunks,
        progress=progress,
    )
    audio = prepare_mono_audio_output(
        audio,
        source_rate=KOKORO_SAMPLE_RATE,
        output_rate=output_rate,
        target_lufs=target_lufs,
    )

    return write_audio_file(
        output_path,
        audio,
        output_rate,
        title=title,
        genre=genre,
        description=description or clean_spoken_text(text),
    )


def save_captions(
    cues,
    output_path,
    voice: KokoroEnglishVoice = DEFAULT_VOICE,
    speed=DEFAULT_NEWS_SPEED,
    lang_code: Literal["a", "b"] | None = None,
    device: str | None = None,
    output_rate=DEFAULT_OUTPUT_SAMPLE_RATE,
    target_lufs=-16.0,
    title=None,
    genre="News",
    description=None,
    print_chunks=False,
    print_cue_timing=False,
    progress=False,
):
    audio = synthesize_caption_speech(
        cues,
        voice=voice,
        base_speed=speed,
        lang_code=lang_code,
        device=device,
        print_chunks=print_chunks,
        print_cue_timing=print_cue_timing,
        progress=progress,
    )
    audio = prepare_mono_audio_output(
        audio,
        source_rate=KOKORO_SAMPLE_RATE,
        output_rate=output_rate,
        target_lufs=target_lufs,
    )

    return write_audio_file(
        output_path,
        audio,
        output_rate,
        title=title,
        genre=genre,
        description=description,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Generate English male speech for Neural Radio with Kokoro."
    )
    parser.add_argument("text", nargs="?", help="Text to speak.")
    parser.add_argument("--text-file", help="UTF-8 text file to speak.")
    parser.add_argument("--captions", help="SRT or WebVTT caption file to speak.")
    parser.add_argument(
        "--list-voices",
        action="store_true",
        help="List supported American/British English Kokoro voices and exit.",
    )
    parser.add_argument(
        "-o", "--output", default="speech.flac", help="Output audio file."
    )
    parser.add_argument(
        "--play",
        action="store_true",
        help="Play speech through Python/miniaudio instead of saving a file.",
    )
    parser.add_argument(
        "--voice",
        choices=KOKORO_ENGLISH_VOICES,
        default=DEFAULT_VOICE,
        help="Kokoro voice. Default is am_michael, an American English male voice.",
    )
    parser.add_argument(
        "--lang-code",
        choices=("a", "b"),
        default=None,
        help="Kokoro language code. Use 'a' for American English, 'b' for British English.",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=DEFAULT_NEWS_SPEED,
        help="Speech speed. Defaults to a brisk radio delivery.",
    )
    parser.add_argument(
        "--target-wpm",
        type=float,
        help=(
            "Derive Kokoro speed from a target words-per-minute pace. "
            "Good news range is usually 175-195."
        ),
    )
    parser.add_argument(
        "--rate",
        type=int,
        default=DEFAULT_OUTPUT_SAMPLE_RATE,
        help="Output/playback sample rate. Defaults to 44100; use at least 32000.",
    )
    parser.add_argument(
        "--device",
        choices=("auto", "cpu", "cuda", "mps"),
        default="auto",
        help="Torch device for Kokoro. Auto prefers CUDA, then Apple MPS, then CPU.",
    )
    parser.add_argument(
        "--require-accelerator",
        action="store_true",
        help="Fail if --device auto resolves to CPU.",
    )
    parser.add_argument(
        "--buffer-seconds",
        type=float,
        default=DEFAULT_PLAYBACK_BUFFER_SECONDS,
        help="Seconds of generated audio to prebuffer before --play starts output.",
    )
    parser.add_argument(
        "--queue-size",
        type=int,
        default=DEFAULT_PLAYBACK_QUEUE_SIZE,
        help="Maximum generated audio chunks queued during --play.",
    )
    parser.add_argument(
        "--no-progress",
        dest="progress",
        action="store_false",
        help="Disable tqdm progress bars.",
    )
    parser.set_defaults(progress=True)
    parser.add_argument("--title", help="FLAC title tag.")
    parser.add_argument("--genre", default="News", help="FLAC genre tag.")
    parser.add_argument(
        "--lufs",
        type=float,
        default=-16.0,
        help="Loudness normalization target in LUFS.",
    )
    parser.add_argument(
        "--no-normalize",
        dest="lufs",
        action="store_const",
        const=None,
        help="Disable loudness normalization.",
    )
    parser.add_argument(
        "--print-chunks",
        action="store_true",
        help="Print generated text/phoneme chunks for debugging pronunciation.",
    )
    parser.add_argument(
        "--print-cue-timing",
        action="store_true",
        help="Print caption cue WPM, speed, and overrun diagnostics.",
    )
    args = parser.parse_args()

    if args.list_voices:
        print_voice_list()
        return

    try:
        if args.buffer_seconds < 0:
            raise ValueError("--buffer-seconds must be non-negative.")
        if args.queue_size <= 0:
            raise ValueError("--queue-size must be positive.")
        if args.rate < 32000:
            raise ValueError("--rate must be at least 32000 for this speech pipeline.")

        torch_device = resolve_torch_device(args.device, args.require_accelerator)
        print(f"Torch device: {describe_torch_device(torch_device)}")

        if args.captions and (args.text or args.text_file):
            raise ValueError("Provide --captions or text input, not both.")
        if args.captions and args.target_wpm is not None:
            raise ValueError(
                "--target-wpm is ignored for captions; cue timings set WPM."
            )

        if args.captions:
            if timeline_looks_typed(args.captions):
                timeline = load_timeline(args.captions)
                cues = cues_from_timeline(timeline)
                print(f"Loaded timeline: {timeline_summary(timeline)}.")
                print(f"Rendering {len(cues)} speech cues.")
            else:
                cues = load_captions(args.captions)
                print(f"Loaded {len(cues)} caption cues.")
            if args.play:
                play_captions(
                    cues,
                    voice=args.voice,
                    speed=args.speed,
                    lang_code=args.lang_code,
                    device=torch_device,
                    playback_rate=args.rate,
                    buffer_seconds=args.buffer_seconds,
                    queue_size=args.queue_size,
                    print_chunks=args.print_chunks,
                    print_cue_timing=args.print_cue_timing,
                    progress=args.progress,
                )
                output_path = None
            else:
                output_path = save_captions(
                    cues,
                    output_path=args.output,
                    voice=args.voice,
                    speed=args.speed,
                    lang_code=args.lang_code,
                    device=torch_device,
                    output_rate=args.rate,
                    target_lufs=args.lufs,
                    title=args.title,
                    genre=args.genre,
                    description=f"Speech generated from {args.captions}",
                    print_chunks=args.print_chunks,
                    print_cue_timing=args.print_cue_timing,
                    progress=args.progress,
                )
        else:
            text = read_text(args)
            if args.target_wpm is not None:
                word_count = count_spoken_words(text)
                args.speed = speed_for_target_wpm(args.target_wpm)
                print(
                    f"Estimated {word_count} spoken words; using speed {args.speed:.2f} "
                    f"for target {args.target_wpm:g} WPM."
                )
            if args.play:
                play_speech(
                    text=text,
                    voice=args.voice,
                    speed=args.speed,
                    target_wpm=args.target_wpm,
                    lang_code=args.lang_code,
                    device=torch_device,
                    playback_rate=args.rate,
                    buffer_seconds=args.buffer_seconds,
                    queue_size=args.queue_size,
                    print_chunks=args.print_chunks,
                    progress=args.progress,
                )
                output_path = None
            else:
                output_path = save_speech(
                    text=text,
                    output_path=args.output,
                    voice=args.voice,
                    speed=args.speed,
                    target_wpm=args.target_wpm,
                    lang_code=args.lang_code,
                    device=torch_device,
                    output_rate=args.rate,
                    target_lufs=args.lufs,
                    title=args.title,
                    genre=args.genre,
                    print_chunks=args.print_chunks,
                    progress=args.progress,
                )
    except Exception as exc:
        parser.exit(1, f"speech.py: error: {exc}\n")

    if output_path is None:
        print("Played speech.")
    else:
        print(f"Saved: {output_path}")


if __name__ == "__main__":
    main()
