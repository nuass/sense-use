"""Planner-side wrapper for one ``sense_use.worker`` subprocess.

Each TargetPane owns one WorkerProcess. The wrapper manages:
- Spawning the subprocess with correct argv
- Reading NDJSON from stdout and converting back to native dicts
- Writing commands (confirm, stop) to stdin
- Termination + cleanup on ``stop()``

The exposed API is intentionally asymmetric: the worker only writes
one kind of thing (events) and only reads one kind of thing (commands).
The planner receives an async stream of event dicts; it sends commands
via ``send_confirm()`` and ``stop()``.

Binary handling
---------------

The worker sends PNGs as base64-encoded strings (``screenshot_b64``
key), which we decode back to bytes in the planner before feeding into
LivePreview.

Error handling
--------------

- Non-zero exit codes are surfaced as a synthetic ``error`` event
- Stderr is tee'd through so planner-side logs can see worker traces
- ``stop()`` sends ``SIGTERM`` + waits, then ``SIGKILL`` if stalled
"""
from __future__ import annotations

import asyncio
import base64
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator


@dataclass
class WorkerProcess:
    backend_spec: str
    provider_key: str
    goal: str
    max_steps: int = 30
    default_cdp: str = "http://127.0.0.1:9222"
    config_path: str | None = None

    _proc: asyncio.subprocess.Process | None = field(default=None, repr=False)
    _event_queue: asyncio.Queue[dict] = field(default_factory=asyncio.Queue, repr=False)

    async def start(self) -> None:
        """Spawn the worker subprocess and wire up the pump coro."""
        argv = [
            sys.executable, "-m", "sense_use.worker",
            "--backend", self.backend_spec,
            "--provider", self.provider_key,
            "--goal", self.goal,
            "--max-steps", str(self.max_steps),
            "--default-cdp", self.default_cdp,
            "--guardian-url", "http://127.0.0.1:8775",
            "--pane-id", "pane-0",  # TODO: proper ID from app
        ]
        if self.config_path is not None:
            argv.extend(["--config-path", self.config_path])

        # CWD to the repo root so imports work regardless of where the
        # user launched the TUI from.
        cwd = Path(__file__).resolve().parent.parent

        self._proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        asyncio.create_task(self._pump_stdout())
        asyncio.create_task(self._pump_stderr())

    async def _pump_stdout(self) -> None:
        assert self._proc is not None
        assert self._proc.stdout is not None
        buf = b""
        while True:
            chunk = await self._proc.stdout.read(256 * 1024)  # 256 KB chunks
            if not chunk:
                break
            buf += chunk
            # Process complete lines.
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                text = line.decode("utf-8").strip()
                if not text:
                    continue
                try:
                    obj = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if not isinstance(obj, dict):
                    continue
                if obj.get("event") == "observe" and "screenshot_b64" in obj:
                    b64 = obj.pop("screenshot_b64")
                    obj["screenshot_bytes"] = base64.b64decode(b64)
                await self._event_queue.put(obj)
        # Handle any leftover incomplete line (shouldn't happen in our protocol).
        if buf.strip():
            try:
                obj = json.loads(buf.decode("utf-8").strip())
                if isinstance(obj, dict):
                    await self._event_queue.put(obj)
            except Exception:  # noqa: BLE001
                pass
        # EOF — wait for the process to exit and report the exit code.
        try:
            code = await asyncio.wait_for(self._proc.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            code = 128
        if code != 0:
            await self._event_queue.put({
                "event": "error",
                "reason": f"worker exited with code {code}",
            })

    async def _pump_stderr(self) -> None:
        # Let worker stderr bubble up but don't block execution.
        assert self._proc is not None
        assert self._proc.stderr is not None
        while True:
            raw = await self._proc.stderr.readline()
            if not raw:
                break
            sys.stderr.buffer.write(b"[worker] " + raw)
            sys.stderr.buffer.flush()

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        """Async generator: yields one event dict at a time until done.

        Events follow the same structure as ``Event.payload`` plus an
        ``event`` key with the kind name. ``screenshot_bytes`` is
        decoded from base64 and returned as bytes.
        """
        while True:
            ev = await self._event_queue.get()
            yield ev
            if ev.get("event") in ("done", "error"):
                break

    async def send_confirm(self, ok: bool) -> None:
        """Send a HITL confirmation reply to the worker.

        Must only be called after receiving ``confirm_needed`` event.
        """
        await self._send({"cmd": "confirm", "ok": ok})

    async def stop(self, timeout: float = 2.0) -> None:
        """Terminate the worker gracefully, then force-kill on timeout."""
        if self._proc is None:
            return
        try:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                try:
                    self._proc.kill()
                except ProcessLookupError:
                    pass
                await self._proc.wait()
        except ProcessLookupError:
            pass
        self._proc = None

    async def _send(self, payload: dict[str, Any]) -> None:
        if self._proc is None or self._proc.stdin is None:
            return
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        self._proc.stdin.write(line.encode("utf-8") + b"\n")
        await self._proc.stdin.drain()
