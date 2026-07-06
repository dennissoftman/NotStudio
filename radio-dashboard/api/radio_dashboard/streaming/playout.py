from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
from sqlmodel import select

from ..audio import dsp
from ..config import get_settings
from ..constants import utcnow
from ..db import session_scope
from ..models import HistoryItem, PlayoutSegment
from . import ffmpeg as ff

_DEVNULL = asyncio.subprocess.DEVNULL
_PIPE = asyncio.subprocess.PIPE


class Broadcast:
    """Fan-out of live PCM frames to subscribers; slow consumers drop frames."""

    def __init__(self, maxsize: int = 64) -> None:
        self._subs: set[asyncio.Queue[bytes | None]] = set()
        self._maxsize = maxsize

    def subscribe(self) -> asyncio.Queue[bytes | None]:
        q: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=self._maxsize)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[bytes | None]) -> None:
        self._subs.discard(q)

    def publish(self, frame: bytes) -> None:
        for q in list(self._subs):
            if q.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    q.get_nowait()  # drop oldest to stay at the live edge
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(frame)


class PlayoutEngine:
    """Streams a stream's ready buffer segments in real time to all consumers."""

    def __init__(
        self,
        *,
        stream_id: str,
        sample_rate: int,
        channels: int,
        frame_seconds: float,
        icecast: dict[str, Any] | None,
        hls_dir: Path,
    ) -> None:
        self.stream_id = stream_id
        self.sample_rate = sample_rate
        self.channels = channels
        self.frame_seconds = frame_seconds
        self.frame_samples = max(1, int(frame_seconds * sample_rate))
        self.icecast = icecast or {}
        self.hls_dir = hls_dir
        self.broadcast = Broadcast()

        self._silence = bytes(self.frame_samples * self.channels * 2)
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._clock: float | None = None
        self._consumers: list[tuple[str, asyncio.Queue[bytes | None], Any, asyncio.Task[None]]] = []
        self.current_segment_id: str | None = None

    # --- lifecycle ------------------------------------------------------------
    @property
    def alive(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.alive:
            return
        self._stop.clear()
        await self._reset_playing()
        await self._start_persistent_consumers()
        self._task = asyncio.create_task(self._run(), name=f"playout:{self.stream_id}")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        for _label, q, proc, feeder in self._consumers:
            self.broadcast.unsubscribe(q)
            feeder.cancel()
            await _kill(proc)
        self._consumers.clear()

    # --- main loop ------------------------------------------------------------
    async def _run(self) -> None:
        try:
            while not self._stop.is_set():
                seg = await self._next_ready_segment()
                if seg is None:  # underrun -> keep the clock alive with silence
                    await self._publish_paced(self._silence)
                    continue
                seg_id, path = seg
                await self._set_state(seg_id, "playing")
                self.current_segment_id = seg_id
                try:
                    await self._play_path(path)
                except Exception:  # noqa: BLE001 — a bad file must not kill the stream
                    pass
                finally:
                    await self._set_state(seg_id, "played", played=True)
                    self.current_segment_id = None
        except asyncio.CancelledError:
            pass

    async def _play_path(self, path: str) -> None:
        if not path or not Path(path).exists():
            return
        handle = await asyncio.to_thread(sf.SoundFile, path)
        try:
            while not self._stop.is_set():
                block = await asyncio.to_thread(
                    handle.read, self.frame_samples, dtype="float32", always_2d=True
                )
                if block.shape[0] == 0:
                    break
                await self._publish_paced(self._encode(block))
        finally:
            await asyncio.to_thread(handle.close)

    def _encode(self, block: np.ndarray) -> bytes:
        data = dsp.ensure_channels(block, self.channels)
        return dsp.to_int16_bytes(data)

    async def _publish_paced(self, frame: bytes) -> None:
        loop = asyncio.get_running_loop()
        now = loop.time()
        if self._clock is None:
            self._clock = now
        delay = self._clock - now
        if delay > 0:
            await asyncio.sleep(delay)
        elif delay < -1.0:  # fell far behind (e.g. blocked) -> resync to now
            self._clock = now
        self.broadcast.publish(frame)
        self._clock += self.frame_seconds

    # --- consumers ------------------------------------------------------------
    async def _start_persistent_consumers(self) -> None:
        self.hls_dir.mkdir(parents=True, exist_ok=True)
        playlist = str(self.hls_dir / "playlist.m3u8")
        segments = str(self.hls_dir / "seg_%05d.ts")
        await self._add_encoder("hls", ff.hls_args(playlist, segments))

        ice = self.icecast
        if ice.get("enabled"):
            await self._add_encoder(
                "icecast",
                ff.icecast_args(
                    host=ice.get("host", "localhost"),
                    port=int(ice.get("port", 8000)),
                    mount=ice.get("mount", "/neural.mp3"),
                    username=ice.get("username", "source"),
                    password=ice.get("password", "hackme"),
                    fmt=ice.get("format", "mp3"),
                ),
            )

    async def _add_encoder(self, label: str, output_args: list[str]) -> None:
        settings = get_settings()
        q = self.broadcast.subscribe()
        proc = await asyncio.create_subprocess_exec(
            settings.ffmpeg_path,
            *ff.pcm_input_args(self.sample_rate, self.channels),
            *output_args,
            stdin=_PIPE,
            stdout=_DEVNULL,
            stderr=_DEVNULL,
        )
        feeder = asyncio.create_task(self._feed(q, proc), name=f"{label}:{self.stream_id}")
        self._consumers.append((label, q, proc, feeder))

    async def _feed(self, q: asyncio.Queue[bytes | None], proc: Any) -> None:
        try:
            while True:
                frame = await q.get()
                if frame is None or proc.stdin is None:
                    break
                proc.stdin.write(frame)
                await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            with contextlib.suppress(Exception):
                proc.stdin.close()

    async def http_mp3(self) -> AsyncIterator[bytes]:
        """Per-listener MP3 stream (each connection gets its own encoder)."""
        settings = get_settings()
        q = self.broadcast.subscribe()
        proc = await asyncio.create_subprocess_exec(
            settings.ffmpeg_path,
            *ff.pcm_input_args(self.sample_rate, self.channels),
            *ff.mp3_stdout_args(),
            stdin=_PIPE,
            stdout=_PIPE,
            stderr=_DEVNULL,
        )
        feeder = asyncio.create_task(self._feed(q, proc))
        try:
            assert proc.stdout is not None
            while True:
                chunk = await proc.stdout.read(4096)
                if not chunk:
                    break
                yield chunk
        finally:
            self.broadcast.unsubscribe(q)
            feeder.cancel()
            await _kill(proc)

    # --- DB helpers -----------------------------------------------------------
    async def _next_ready_segment(self) -> tuple[str, str] | None:
        async with session_scope() as session:
            res = await session.execute(
                select(PlayoutSegment.id, HistoryItem.path)
                .join(HistoryItem, HistoryItem.id == PlayoutSegment.history_item_id)
                .where(
                    PlayoutSegment.stream_id == self.stream_id,
                    PlayoutSegment.state == "ready",
                )
                .order_by(PlayoutSegment.sequence)
                .limit(1)
            )
            row = res.first()
            return (row[0], row[1]) if row else None

    async def _set_state(self, seg_id: str, state: str, played: bool = False) -> None:
        async with session_scope() as session:
            seg = await session.get(PlayoutSegment, seg_id)
            if seg is None:
                return
            seg.state = state
            if played:
                seg.played_at = utcnow()
            session.add(seg)
            await session.commit()

    async def _reset_playing(self) -> None:
        async with session_scope() as session:
            res = await session.execute(
                select(PlayoutSegment).where(
                    PlayoutSegment.stream_id == self.stream_id,
                    PlayoutSegment.state == "playing",
                )
            )
            for seg in res.scalars().all():
                seg.state = "ready"
                session.add(seg)
            await session.commit()


async def _kill(proc: Any) -> None:
    with contextlib.suppress(ProcessLookupError):
        proc.kill()
    with contextlib.suppress(Exception):
        await proc.wait()


class PlayoutManager:
    """Owns the active PlayoutEngines (lives in the API process, not the worker)."""

    def __init__(self) -> None:
        self._engines: dict[str, PlayoutEngine] = {}
        self._lock = asyncio.Lock()

    async def ensure_running(self, stream: Any) -> PlayoutEngine:
        async with self._lock:
            engine = self._engines.get(stream.id)
            if engine and engine.alive:
                return engine
            settings = get_settings()
            engine = PlayoutEngine(
                stream_id=stream.id,
                sample_rate=stream.sample_rate,
                channels=stream.channels,
                frame_seconds=settings.playout_frame_seconds,
                icecast=stream.icecast,
                hls_dir=settings.hls_dir / stream.id,
            )
            await engine.start()
            self._engines[stream.id] = engine
            return engine

    def get(self, stream_id: str) -> PlayoutEngine | None:
        engine = self._engines.get(stream_id)
        return engine if engine and engine.alive else None

    async def stop(self, stream_id: str) -> None:
        engine = self._engines.pop(stream_id, None)
        if engine:
            await engine.stop()

    async def shutdown(self) -> None:
        for engine in list(self._engines.values()):
            await engine.stop()
        self._engines.clear()
