# WebVTT Timeline Design for Neural Radio (MVP)

## Goal

The WebVTT file is the canonical timeline representation for every generated radio program.

It is **not just subtitles**. Instead, it describes everything that happens during playback:

- spoken narration
- music beds
- full songs
- jingles and sound effects
- synchronization markers
- future visual events
- safe interruption points for live content insertion

The playback engine should be able to reconstruct an entire radio broadcast from a WebVTT timeline together with the referenced assets.

---

# Design Principles

The timeline should remain:

- human-readable
- editable by both humans and LLMs
- deterministic
- independent of any specific TTS model

Speech speed is **not stored directly**. Instead, cue duration defines the desired pacing. The renderer computes the appropriate TTS speed for the selected voice.

---

# File Structure

A timeline begins with normal WebVTT headers followed by optional global metadata.

```vtt
WEBVTT

NOTE station=Neural FM
NOTE program=Morning News
NOTE generated_at=2026-07-06T08:15:00Z
NOTE default_voice=ava
NOTE default_music_bed=deep_house_news
```

Global metadata provides defaults that individual cues may override.

---

# Cue Types

Every cue has one required field:

```text
type
```

The MVP supports five cue types.

## Speech

Represents any spoken content.

Examples:

- news
- weather
- traffic
- DJ speech
- advertisements
- station identification

Example:

```vtt
news-001
00:00:00.000 --> 00:00:05.400

<v Ava>
Good morning. You're listening to Neural FM.

NOTE type=speech
NOTE section=news
NOTE speaker=ava
NOTE mood=energetic
NOTE pace=fast
```

The renderer uses the cue duration to determine speech speed.

---

## Music Bed

Background music intended to play underneath speech.

Example:

```vtt
bed-001
00:00:00.000 --> 00:00:42.000

NOTE type=music_bed
NOTE asset=deep_house_news_01
NOTE volume=-22dB
NOTE ducking=true
NOTE fade_in=1.0s
NOTE fade_out=2.0s
```

A music bed may overlap multiple speech cues.

---

## Music Track

A standalone song.

Example:

```vtt
song-001
00:00:42.000 --> 00:03:55.000

NOTE type=music_track
NOTE asset=track_000381
NOTE genre=deep_house
NOTE energy=high
NOTE vocal=false
NOTE allow_interrupt=false
```

The playback engine treats this as the primary audio source during its duration.

---

## Sound Effect

Short non-musical assets.

Typical examples:

- station jingles
- sweepers
- transitions
- notification sounds

Example:

```vtt
jingle-001
00:00:40.500 --> 00:00:42.000

NOTE type=sfx
NOTE asset=news_stinger
NOTE volume=-12dB
```

---

## Marker

Zero-duration timeline events.

Markers produce no audio and exist solely for synchronization.

Example:

```vtt
mark-001
00:00:42.000 --> 00:00:42.001

NOTE type=mark
NOTE event=news_start
```

Markers are intended for:

- switching visuals
- analytics
- admin panel events
- automation triggers
- debugging
- synchronization

---

# Metadata

The MVP intentionally keeps metadata small.

## Common Metadata

Every cue may contain:

| Field | Purpose |
|--------|---------|
| type | Cue type |
| section | News, weather, traffic, music, ad, intro, outro |
| priority | low, normal, urgent |
| tags | Optional comma-separated labels |

---

## Speech Metadata

Speech cues additionally support:

| Field | Purpose |
|--------|---------|
| speaker | Voice identifier |
| mood | neutral, energetic, serious, warm, sarcastic |
| pace | slow, normal, fast |

The renderer maps these values to engine-specific parameters.

---

## Music Metadata

Music cues support:

| Field | Purpose |
|--------|---------|
| asset | Audio asset identifier |
| volume | Playback gain |
| ducking | Enable speech ducking |
| fade_in | Fade duration |
| fade_out | Fade duration |
| genre | Optional descriptive label |
| energy | low, medium, high |

---

## Marker Metadata

Marker cues support:

| Field | Purpose |
|--------|---------|
| event | Marker name |
| data | Optional payload |

Example events:

- news_start
- news_end
- music_start
- music_end
- station_id
- safe_interrupt
- visual_change

---

# Timeline Semantics

Speech cues are sequential.

Music beds may overlap speech.

Songs occupy the primary playback channel.

Sound effects may overlap any cue.

Markers have zero duration and are consumed by the playback engine.

---

# Rendering Pipeline

```
LLM
    │
    ▼
Generate WebVTT timeline
    │
    ▼
Timeline Scheduler
    │
    ├── Speech → Kokoro TTS
    ├── Music → Music Generator / Asset Library
    ├── SFX → Asset Library
    └── Markers → Event Dispatcher
    │
    ▼
Mixer
    │
    ▼
Final Radio Stream
```

---

# Current Codebase Integration

The MVP integration point is a provider-neutral timeline layer, not a direct
dependency from WebVTT to any one audio engine.

Implemented pieces:

- `timeline.py` parses and validates typed WebVTT timelines.
- `speech.py --captions program.vtt` can render `type=speech` cues from a typed
  WebVTT timeline with Kokoro.
- Non-speech cues are parsed and validated, but are left for a future scheduler,
  asset resolver, and mixer instead of being hardwired into the speech command.

This keeps the canonical timeline useful before the full broadcast renderer
exists. The speech CLI can produce narration stems from the same source of truth
that a later mixer will use for music beds, tracks, SFX, markers, and live
insertion points.

## Do Not Hardcode

Keep these concerns injectable or configurable:

- voice identifiers and model-specific voice mappings
- default station/program metadata
- asset ID to storage URL/path resolution
- music generator/provider selection
- TTS provider selection
- loudness, ducking, fade, and mix policies
- output storage targets such as local files, R2, or streams
- marker event handlers and automation destinations

The timeline should contain semantic intent and asset identifiers. Runtime code
should resolve those identifiers through separate provider adapters.

## Recommended Next Layer

Add a renderer/scheduler module when the project needs full program output:

1. Load `Timeline`.
2. Resolve asset cues through an `AssetResolver` interface.
3. Render speech cues through a `SpeechRenderer` interface.
4. Generate missing music assets through a `MusicRenderer` interface only when
   the asset resolver cannot provide an existing asset.
5. Mix stems according to cue metadata.
6. Dispatch marker events through registered handlers.

None of those interfaces should be imported by `timeline.py`; the timeline layer
must stay pure, deterministic, and easy to test.

---

# Future Extensions

The MVP schema intentionally leaves room for future features without changing the overall format.

Possible additions include:

- emotion intensity
- multiple simultaneous speakers
- voice switching
- live caller segments
- dynamic advertisements
- chapter metadata
- playlist identifiers
- AI-generated visual prompts
- subtitle translations
- real-time insertion of breaking news
- timeline versioning

None of these extensions require changing the core cue model, only adding new metadata fields.
