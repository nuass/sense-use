"""Worker process — runs one TaskRunner in a standalone Python process.

This is the v0.3.3 "拆 Worker 进程" half of the AgentTeams refactor.
Each pane spawns one ``python -m sense_use.worker`` subprocess; the
planner (TUI) talks to it over newline-delimited JSON on stdin/stdout.

Wire protocol
-------------

Events (worker → planner), one JSON object per line on stdout::

    {"event": "user_msg",      "goal": "..."}
    {"event": "observe",       "step": 1, "size": 12345,
                                "screenshot_b64": "..."}
    {"event": "think",         "step": 1, "thought": "...", "action": "click",
                                "args": {...}}
    {"event": "act_result",    "step": 1, "action": "click", "ok": true,
                                "detail": "..."}
    {"event": "confirm_needed","action": "delete", "args": {...}, "label": "..."}
    {"event": "confirm_result","ok": true}
    {"event": "done",          "answer": "..."}
    {"event": "error",         "reason": "..."}

Commands (planner → worker), one JSON object per line on stdin::

    {"cmd": "confirm", "ok": true}      # HITL reply to confirm_needed
    {"cmd": "stop"}                       # graceful cancel

Binary blobs (screenshots) are base64-encoded so they survive the
text-only stdio pipe. Each worker owns its own EventBus, Backend, and
ModelProvider — no state leaks between panes.

Why a subprocess and not a thread
---------------------------------

- **Crash isolation** — a misbehaving backend (segfaulting native lib,
  accidental ``os._exit``) cannot take down the TUI.
- **CPU parallelism** — one backend doing heavy image work on a
  background thread no longer fights the event loop.
- **GIL relief** — VLM provider HTTP calls and PIL resizing both hold
  the GIL; isolation lets the planner keep rendering at 30+ fps while
  workers do their work.
- **AgentTeams compliance** — GOAI Track1 1.1 requires "multi-agent
  design must use AgentTeams as the collaborative design foundation";
  separate processes are the cleanest read of that.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import signal
import sys
from pathlib import Path
from typing import Any, Callable


# Make `python -m sense_use.worker` work regardless of CWD.
_PKG_ROOT = Path(__file__).resolve().parent.parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))


from sense_use.config import ensure_config_exists, load_config  # noqa: E402
from sense_use.core.event_bus import EventBus  # noqa: E402
from sense_use.core.session import Session  # noqa: E402
from sense_use.core.task_runner import TaskRunner  # noqa: E402
from sense_use.guardian_client import GuardianClient, PassthroughGuardian  # noqa: E402
from sense_use.models import provider_registry  # noqa: E402
from sense_use.tui.app import _build_target_factory, _parse_target  # noqa: E402


# ---------------------------------------------------------------------------
# Wire I/O
# ---------------------------------------------------------------------------


def _emit(payload: dict[str, Any]) -> None:
    """Write one NDJSON event to stdout and flush immediately.

    Flushing is critical: the planner reads our stdout line-by-line
    asynchronously, and a kernel pipe buffer full of unflushed bytes
    would deadlock the worker waiting on stdin.
    """
    line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


async def _read_commands(queue: asyncio.Queue[dict]) -> None:
    """Read NDJSON commands from stdin and put them on ``queue``.

    We use a background thread + ``run_coroutine_threadsafe`` because
    asyncio's ``connect_read_pipe`` misbehaves when stdin is a non-tty
    pipe (Errno 22 on the read selector on some platforms). EOF
    (parent closed our stdin) is converted to ``{"cmd": "stop"}`` so
    the worker winds down gracefully.
    """
    import threading

    def _drain() -> None:
        for raw in sys.stdin:
            try:
                obj = json.loads(raw.decode("utf-8").strip() or "{}")
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            asyncio.run_coroutine_threadsafe(queue.put(obj), loop)
        # EOF: parent closed stdin.
        asyncio.run_coroutine_threadsafe(queue.put({"cmd": "stop"}), loop)

    loop = asyncio.get_event_loop()
    t = threading.Thread(target=_drain, daemon=True)
    t.start()
    # Block until the main loop decides we're done. The thread will
    # signal via ``queue`` (incl. EOF-as-stop); the main loop polls the
    # queue inside the run/complete wait loop, not here.
    await asyncio.Future()


# ---------------------------------------------------------------------------
# Confirm gate
# ---------------------------------------------------------------------------


class _StdinConfirm:
    """Worker-side gate that blocks until the planner sends ``confirm``.

    Replaces the in-process ``asyncio.Future`` that ``TaskRunner`` would
    normally use. The worker emits ``confirm_needed`` over stdout, then
    awaits ``self.future``; the planner writes
    ``{"cmd": "confirm", "ok": true}`` to stdin and we resolve it.
    """

    def __init__(self) -> None:
        self.future: asyncio.Future[bool] | None = None

    def request(self) -> asyncio.Future[bool]:
        if self.future is None or self.future.done():
            self.future = asyncio.get_event_loop().create_future()
        return self.future

    def resolve(self, ok: bool) -> None:
        if self.future is not None and not self.future.done():
            self.future.set_result(ok)


# ---------------------------------------------------------------------------
# Event adapter — TaskRunner's EventBus -> wire format
# ---------------------------------------------------------------------------


async def _pump_bus(
    bus: EventBus,
    confirm_gate: _StdinConfirm,
    screenshot_sink: Callable[[bytes], None] | None = None,
) -> None:
    """Forward every Event published on the local bus to stdout (NDJSON).

    The ``confirm_needed`` branch also awaits the stdin gate and emits
    a follow-up ``confirm_result`` so the planner knows the round-trip
    is done. Everything else is a straight pass-through.

    ``screenshot_sink`` receives the raw PNG of each ``observe`` event so
    Guardian can attach the latest frame to its approval requests.
    """
    q = bus.subscribe()
    while True:
        ev = await q.get()
        if ev.kind == "observe":
            shot = ev.payload.get("screenshot_bytes") or b""
            if screenshot_sink is not None:
                screenshot_sink(shot)
            _emit({
                "event": "observe",
                "step": ev.payload.get("step"),
                "size": len(shot),
                "screenshot_b64": base64.b64encode(shot).decode("ascii"),
            })
        elif ev.kind == "user_msg":
            _emit({"event": "user_msg", "goal": ev.payload.get("goal", "")})
        elif ev.kind == "think":
            _emit({
                "event": "think",
                "step": ev.payload.get("step"),
                "thought": ev.payload.get("thought", ""),
                "action": ev.payload.get("action", ""),
                "args": ev.payload.get("args", {}),
                "label": ev.payload.get("label", ""),
                "done": ev.payload.get("done", False),
            })
        elif ev.kind == "act_result":
            _emit({
                "event": "act_result",
                "step": ev.payload.get("step"),
                "action": ev.payload.get("action", ""),
                "ok": ev.payload.get("ok", False),
                "detail": ev.payload.get("detail", ""),
            })
        elif ev.kind == "confirm_needed":
            _emit({
                "event": "confirm_needed",
                "action": ev.payload.get("action", ""),
                "args": ev.payload.get("args", {}),
                "label": ev.payload.get("label", ""),
            })
            # Block until planner replies via stdin. The TaskRunner
            # itself is *also* waiting on its own future; we resolve
            # both by reusing the gate's future in the patched
            # ``resolve_confirm`` (see _run()).
            fut = confirm_gate.request()
            ok = await fut
            _emit({"event": "confirm_result", "ok": ok})
        elif ev.kind == "confirm_result":
            pass  # already emitted above
        elif ev.kind == "done":
            _emit({"event": "done", "answer": ev.payload.get("answer", "")})
        elif ev.kind == "error":
            _emit({"event": "error", "reason": ev.payload.get("reason", "")})


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="sense_use.worker")
    p.add_argument("--backend", required=True,
                   help='--targets-style spec, e.g. "browser@9222" or "adb@SERIAL"')
    p.add_argument("--provider", default="claude",
                   help="model provider key (claude / volc / openai / qwen_local)")
    p.add_argument("--goal", required=True, help="user goal string")
    p.add_argument("--max-steps", type=int, default=30)
    p.add_argument("--default-cdp", default="http://127.0.0.1:9222",
                   help="fallback CDP URL when --backend has no port")
    p.add_argument("--config-path", default=None,
                   help="override config file (else ~/.config/sense-use/config.toml)")
    p.add_argument("--pane-id", default="pane-0",
                   help="pane ID for Guardian audit logs")
    p.add_argument("--guardian-url", default="http://127.0.0.1:8775",
                   help="Guardian Gateway HTTP endpoint (empty = passthrough)")
    return p.parse_args(argv)


def _build_guardian(
    guardian_url: str,
    pane_id: str,
    backend_kind: str,
) -> tuple[Callable, Callable[[bytes], None]]:
    """Build the ``(guardian_check, screenshot_sink)`` pair for one worker.

    The sink and the check share ``last_screenshot`` via closure — the sink
    is fed by ``_pump_bus`` on every observe, so each approval request
    carries the frame the model actually made its decision on. Wiring the
    sink into ``_pump_bus`` is mandatory; without it Guardian sees no image.
    """
    client = GuardianClient(base_url=guardian_url)
    last_screenshot: bytes | None = None

    def screenshot_sink(shot: bytes) -> None:
        nonlocal last_screenshot
        last_screenshot = shot or None

    async def guardian_check(action: str, args_dict: dict, label: str, sess) -> tuple[bool, str]:
        result = await client.check(
            session_id=sess.id,
            pane_id=pane_id,
            action=action,
            label=label,
            args=args_dict,
            backend_kind=backend_kind,
            screenshot_bytes=last_screenshot,
        )
        return result.allow, result.reason

    return guardian_check, screenshot_sink


async def _run(args: argparse.Namespace) -> int:
    ensure_config_exists()
    cfg = load_config(args.config_path)
    cfg.apply_voice_env()

    # Build the backend (deferred construction so missing deps don't
    # crash the worker at import time).
    kind, _title, backend_kwargs = _parse_target(args.backend, args.default_cdp)
    backend_factory = _build_target_factory(kind, backend_kwargs)
    backend = backend_factory()
    try:
        await backend.start()
    except Exception as exc:  # noqa: BLE001
        _emit({"event": "error", "reason": f"backend start failed: {exc!r}"})
        return 2

    provider_kwargs = cfg.provider_kwargs(args.provider)
    provider = provider_registry.build(args.provider, **provider_kwargs)

    bus = EventBus()
    session = Session(goal=args.goal, max_steps=args.max_steps)
    runner = TaskRunner(session=session, backend=backend, provider=provider, bus=bus)

    # v0.3.4 Guardian: wrap HTTP client as async fn for TaskRunner
    screenshot_sink: Callable[[bytes], None] | None = None
    if args.guardian_url:
        runner.guardian_check, screenshot_sink = _build_guardian(
            guardian_url=args.guardian_url,
            pane_id=args.pane_id,
            backend_kind=kind,
        )

    confirm_gate = _StdinConfirm()
    cmd_queue: asyncio.Queue[dict] = asyncio.Queue()

    # Patch resolve_confirm on the runner to no-op — the real
    # confirmation is driven by the bus pump + stdin gate, so the
    # planner-facing ``runner.resolve_confirm()`` is unused.
    async def _noop_resolve(_ok: bool) -> None:
        return None
    runner.resolve_confirm = _noop_resolve  # type: ignore[method-assign]

    pump_task = asyncio.create_task(_pump_bus(bus, confirm_gate, screenshot_sink))
    cmd_task = asyncio.create_task(_read_commands(cmd_queue))

    async def runner_coro() -> None:
        try:
            await runner.run()
        except Exception as exc:  # noqa: BLE001
            _emit({"event": "error", "reason": repr(exc)})
        finally:
            try:
                await backend.stop()
            except Exception:  # noqa: BLE001
                pass

    run_task = asyncio.create_task(runner_coro())

    stop_requested = False
    while not stop_requested:
        done, _pending = await asyncio.wait(
            {run_task, cmd_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if run_task in done:
            stop_requested = True
            break
        # Drain queued commands.
        while not cmd_queue.empty():
            cmd = cmd_queue.get_nowait()
            c = cmd.get("cmd")
            if c == "confirm":
                confirm_gate.resolve(bool(cmd.get("ok", False)))
            elif c == "stop":
                run_task.cancel()
                stop_requested = True
                break

    for t in (pump_task, cmd_task):
        t.cancel()
    await asyncio.gather(pump_task, cmd_task, return_exceptions=True)
    try:
        await backend.stop()
    except Exception:  # noqa: BLE001
        pass
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    # Graceful shutdown on SIGTERM (the planner uses proc.terminate()).
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
