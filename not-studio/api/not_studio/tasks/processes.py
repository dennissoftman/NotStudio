from __future__ import annotations

import asyncio
import multiprocessing as mp
import queue
import signal
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

T = TypeVar("T")


@dataclass
class ProcessFailed(RuntimeError):
    message: str
    traceback: str

    def __str__(self) -> str:
        return self.message


def _entrypoint(
    result_queue: mp.Queue,
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> None:
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        result_queue.put(("ok", func(*args, **kwargs), ""))
    except BaseException as exc:  # noqa: BLE001 - preserve child-process failure text
        result_queue.put(("error", f"{type(exc).__name__}: {exc}", traceback.format_exc()))


def _persistent_entrypoint(task_queue: mp.Queue, result_queue: mp.Queue) -> None:
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    while True:
        task = task_queue.get()
        if task is None:
            break
        task_id, func, args, kwargs = task
        try:
            result_queue.put((task_id, "ok", func(*args, **kwargs), ""))
        except BaseException as exc:  # noqa: BLE001 - preserve child-process failure text
            result_queue.put(
                (task_id, "error", f"{type(exc).__name__}: {exc}", traceback.format_exc())
            )


async def run_in_process(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    ctx = mp.get_context("spawn")
    result_queue = ctx.Queue(maxsize=1)
    proc = ctx.Process(target=_entrypoint, args=(result_queue, func, args, kwargs), daemon=True)
    proc.start()
    try:
        result: tuple[str, Any, str] | None = None
        while proc.is_alive():
            try:
                result = result_queue.get_nowait()
                break
            except queue.Empty:
                pass
            await asyncio.sleep(0.2)
        proc.join()
        if result is None:
            try:
                result = result_queue.get_nowait()
            except queue.Empty as exc:
                raise ProcessFailed(f"Worker exited with code {proc.exitcode}", "") from exc
        status, payload, tb = result
        if status == "ok":
            return payload
        raise ProcessFailed(payload, tb)
    except asyncio.CancelledError:
        if proc.is_alive():
            proc.terminate()
            await asyncio.to_thread(proc.join, 5)
            if proc.is_alive():
                proc.kill()
                await asyncio.to_thread(proc.join, 5)
        raise
    finally:
        result_queue.close()
        result_queue.join_thread()


class ReusableProcess:
    def __init__(self, name: str) -> None:
        self.name = name
        self._ctx = mp.get_context("spawn")
        self._task_queue: mp.Queue | None = None
        self._result_queue: mp.Queue | None = None
        self._proc: mp.Process | None = None
        self._lock = asyncio.Lock()
        self._next_task_id = 0

    def is_busy(self) -> bool:
        return self._lock.locked()

    def _ensure_started(self) -> None:
        if self._proc is not None and self._proc.is_alive():
            return
        self._close_queues()
        self._task_queue = self._ctx.Queue()
        self._result_queue = self._ctx.Queue()
        self._proc = self._ctx.Process(
            target=_persistent_entrypoint,
            args=(self._task_queue, self._result_queue),
            name=f"not-studio-{self.name}",
            daemon=True,
        )
        self._proc.start()

    def _terminate(self) -> None:
        proc = self._proc
        if proc is not None and proc.is_alive():
            proc.terminate()
            proc.join(5)
            if proc.is_alive():
                proc.kill()
                proc.join(5)
        self._proc = None
        self._close_queues()

    def _close_queues(self) -> None:
        for work_queue in (self._task_queue, self._result_queue):
            if work_queue is None:
                continue
            work_queue.close()
            work_queue.join_thread()
        self._task_queue = None
        self._result_queue = None

    async def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        async with self._lock:
            self._ensure_started()
            assert self._task_queue is not None
            assert self._result_queue is not None
            assert self._proc is not None
            self._next_task_id += 1
            task_id = self._next_task_id
            self._task_queue.put((task_id, func, args, kwargs))
            try:
                while self._proc.is_alive():
                    try:
                        returned_task_id, status, payload, tb = self._result_queue.get_nowait()
                    except queue.Empty:
                        await asyncio.sleep(0.2)
                        continue
                    if returned_task_id != task_id:
                        continue
                    if status == "ok":
                        return payload
                    raise ProcessFailed(payload, tb)
                raise ProcessFailed(f"Worker exited with code {self._proc.exitcode}", "")
            except asyncio.CancelledError:
                self._terminate()
                raise

    async def shutdown(self) -> None:
        async with self._lock:
            if self._task_queue is not None:
                self._task_queue.put(None)
            if self._proc is not None:
                await asyncio.to_thread(self._proc.join, 5)
                if self._proc.is_alive():
                    self._terminate()
            self._proc = None
            self._close_queues()


class ExclusiveModelProcess:
    """One reusable child at a time, swapping processes between GPU model families."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._family: str | None = None
        self._worker: ReusableProcess | None = None
        self._idle_seconds = 0
        self._idle_task: asyncio.Task[None] | None = None
        self._generation = 0

    def configure_idle_timeout(self, seconds: int) -> None:
        self._idle_seconds = max(0, seconds)

    def _cancel_idle_task(self) -> None:
        if self._idle_task is not None:
            self._idle_task.cancel()
            self._idle_task = None

    def _schedule_idle_shutdown(self) -> None:
        self._cancel_idle_task()
        if self._idle_seconds <= 0 or self._worker is None:
            return
        generation = self._generation

        async def close_when_idle() -> None:
            try:
                await asyncio.sleep(self._idle_seconds)
                async with self._lock:
                    if generation != self._generation or self._worker is None:
                        return
                    await self._worker.shutdown()
                    self._worker = None
                    self._family = None
            except asyncio.CancelledError:
                return

        self._idle_task = asyncio.create_task(close_when_idle())

    def status(self) -> dict[str, Any]:
        worker = self._worker
        return {
            "family": self._family,
            "status": "busy" if self._lock.locked() else ("ready" if worker else "idle"),
        }

    def is_busy(self, family: str | None = None) -> bool:
        return self._lock.locked() and (family is None or family == self._family)

    async def call(self, family: str, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        self._cancel_idle_task()
        async with self._lock:
            self._generation += 1
            if self._family != family:
                if self._worker is not None:
                    await self._worker.shutdown()
                self._worker = ReusableProcess(f"gpu-{family}")
                self._family = family
            assert self._worker is not None
            try:
                result = await self._worker.call(func, *args, **kwargs)
                self._schedule_idle_shutdown()
                return result
            except asyncio.CancelledError:
                # ReusableProcess terminates its child on cancellation. Clear the
                # slot so a later call cannot mistake the dead process for a warm model.
                self._worker = None
                self._family = None
                raise

    async def shutdown(self) -> None:
        self._cancel_idle_task()
        async with self._lock:
            if self._worker is not None:
                await self._worker.shutdown()
            self._worker = None
            self._family = None


_reusable_processes: dict[str, ReusableProcess] = {}
_model_process = ExclusiveModelProcess()


def reusable_process_busy(name: str) -> bool:
    worker = _reusable_processes.get(name)
    return bool(worker and worker.is_busy())


async def run_in_reusable_process(
    name: str, func: Callable[..., T], *args: Any, **kwargs: Any
) -> T:
    worker = _reusable_processes.get(name)
    if worker is None:
        worker = ReusableProcess(name)
        _reusable_processes[name] = worker
    return await worker.call(func, *args, **kwargs)


async def run_in_model_process(family: str, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    return await _model_process.call(family, func, *args, **kwargs)


def model_process_busy(family: str | None = None) -> bool:
    return _model_process.is_busy(family)


def model_process_status() -> dict[str, Any]:
    return _model_process.status()


def configure_model_idle_timeout(seconds: int) -> None:
    _model_process.configure_idle_timeout(seconds)


async def shutdown_reusable_processes() -> None:
    workers = list(_reusable_processes.values())
    _reusable_processes.clear()
    await asyncio.gather(*(worker.shutdown() for worker in workers), return_exceptions=True)
    await _model_process.shutdown()
