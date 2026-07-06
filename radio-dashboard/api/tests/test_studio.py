"""Studio track-generation progress: stream main.py output -> per-track callbacks."""

from pathlib import Path

from radio_dashboard.backends import stable_audio


def test_generate_batch_reports_per_track_progress(tmp_path, monkeypatch):
    prompts = [
        {"title": "Track One", "prompt": "warm pads", "duration": 5},
        {"title": "Track Two", "prompt": "deep bass", "duration": 5},
    ]

    def fake_stream(script, args, on_line, timeout=None):
        # Emulate main.py --prompts: announce model load, then a line per track.
        on_line("Loading model: medium")
        out_dir = Path(args[args.index("-o") + 1])
        for spec in prompts:
            flac = out_dir / f"{stable_audio._slugify(spec['title'])}.flac"
            flac.write_bytes(b"stub")
            on_line(f"Saved: {flac}")
        return 0

    monkeypatch.setattr(stable_audio, "run_engine_cli_streaming", fake_stream)

    updates: list[tuple[float, str]] = []
    produced = stable_audio.generate_batch(
        prompts,
        sample_rate=44100,
        model="medium",
        out_dir=tmp_path / "out",
        on_progress=lambda frac, msg: updates.append((round(frac, 3), msg)),
    )

    assert len(produced) == 2
    messages = [m for _, m in updates]
    assert any("Loading model" in m for m in messages)
    assert any("1/2" in m for m in messages) and any("2/2" in m for m in messages)
    # progress is monotonic and ends near-complete (before the import/persist step)
    fractions = [f for f, _ in updates]
    assert fractions == sorted(fractions)
    assert fractions[-1] >= 0.9


def test_generate_batch_raises_with_output_tail(tmp_path, monkeypatch):
    def fake_stream(script, args, on_line, timeout=None):
        on_line("Traceback (most recent call last):")
        on_line("RuntimeError: CUDA out of memory")
        return 1

    monkeypatch.setattr(stable_audio, "run_engine_cli_streaming", fake_stream)

    try:
        stable_audio.generate_batch(
            [{"title": "x", "prompt": "y", "duration": 5}],
            sample_rate=44100,
            model="medium",
            out_dir=tmp_path / "out",
        )
    except RuntimeError as exc:
        assert "exit 1" in str(exc) and "CUDA out of memory" in str(exc)
    else:
        raise AssertionError("expected RuntimeError on non-zero exit")
