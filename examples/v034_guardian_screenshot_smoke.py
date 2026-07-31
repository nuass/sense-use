"""v0.3.4 Guardian screenshot round-trip + rule enforcement.

Covers what v034_guardian_smoke.py does not:
1. The PNG a worker observed actually arrives at the gateway as decoded bytes.
2. ``_pump_bus``'s screenshot_sink fires on observe events.
3. Destructive actions are rejected by rule without hitting the callback.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sense_use.core.event_bus import Event, EventBus
from sense_use.guardian_client import GuardianClient
from sense_use.guardian_gateway import PendingConfirm, create_app
from sense_use.worker import _build_guardian, _StdinConfirm, _pump_bus

# Smallest valid PNG (1x1 transparent).
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)


async def check_sink_fires() -> None:
    """_pump_bus must hand each observe screenshot to the sink."""
    seen: list[bytes] = []
    bus = EventBus()
    task = asyncio.create_task(_pump_bus(bus, _StdinConfirm(), seen.append))
    await asyncio.sleep(0.05)  # let subscribe() register before publishing
    await bus.publish(Event(kind="observe", session_id="s1",
                           payload={"step": 1, "screenshot_bytes": PNG}))
    await asyncio.sleep(0.1)
    task.cancel()
    assert seen == [PNG], f"sink got {[len(b) for b in seen]}, expected [{len(PNG)}]"
    print("[v034] ✓ _pump_bus screenshot_sink fires with exact PNG bytes")


async def check_gateway_roundtrip() -> None:
    """Gateway must decode screenshot_b64 back to the original PNG."""
    received: list[PendingConfirm] = []

    def confirm_callback(pc: PendingConfirm) -> None:
        received.append(pc)
        pc.future.set_result((True, "ok"))

    app = create_app(mode="local", confirm_callback=confirm_callback)

    import hypercorn.asyncio
    from hypercorn.config import Config
    cfg = Config()
    cfg.bind = ["127.0.0.1:8777"]
    cfg.loglevel = "error"
    server = asyncio.create_task(hypercorn.asyncio.serve(app, cfg))
    await asyncio.sleep(0.5)

    try:
        client = GuardianClient(base_url="http://127.0.0.1:8777")

        result = await client.check(
            session_id="s1", pane_id="pane-0", action="click",
            label="Click Search", args={"x": 1, "y": 2},
            backend_kind="browser", screenshot_bytes=PNG,
        )
        assert result.allow is True, result.reason
        assert len(received) == 1, f"expected 1 callback, got {len(received)}"
        got = received[0].screenshot_bytes
        assert got == PNG, (
            f"screenshot corrupted: got {len(got) if got else None} bytes "
            f"{got[:8].hex() if got else ''}, expected {len(PNG)} bytes {PNG[:8].hex()}"
        )
        print(f"[v034] ✓ screenshot survived round-trip ({len(got)} bytes, PNG magic intact)")

        # Destructive action must be blocked by rule, not sent to the user.
        before = len(received)
        blocked = await client.check(
            session_id="s1", pane_id="pane-0", action="delete",
            label="Delete all rows", args={}, backend_kind="browser",
        )
        assert blocked.allow is False, "delete must be blocked"
        assert blocked.approved_by == "rule:default", blocked.approved_by
        assert len(received) == before, "delete must NOT reach the confirm callback"
        print(f"[v034] ✓ 'delete' blocked by rule, callback not invoked: {blocked.reason!r}")

        # A non-destructive 'key' action still requires confirmation.
        keyres = await client.check(
            session_id="s1", pane_id="pane-0", action="key",
            label="Press Enter", args={"name": "enter"}, backend_kind="browser",
        )
        assert keyres.allow is True and keyres.approved_by == "tui:local_user", keyres
        assert len(received) == before + 1, "key action should reach the callback"
        print("[v034] ✓ 'key' action routed to confirm callback (no dead-rule bypass)")
    finally:
        server.cancel()
        try:
            await asyncio.wait_for(server, timeout=1.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass


async def check_worker_wiring() -> None:
    """The observe frame must reach Guardian through the real worker path.

    This is the integration that regressed once already: ``_build_guardian``
    returns a sink that MUST be handed to ``_pump_bus``, otherwise Guardian
    receives screenshot=None on every approval.
    """
    received: list[PendingConfirm] = []

    def confirm_callback(pc: PendingConfirm) -> None:
        received.append(pc)
        pc.future.set_result((True, "ok"))

    app = create_app(mode="local", confirm_callback=confirm_callback)

    import hypercorn.asyncio
    from hypercorn.config import Config
    cfg = Config()
    cfg.bind = ["127.0.0.1:8778"]
    cfg.loglevel = "error"
    server = asyncio.create_task(hypercorn.asyncio.serve(app, cfg))
    await asyncio.sleep(0.5)

    class _Sess:
        id = "sess-wiring"

    try:
        guardian_check, sink = _build_guardian(
            guardian_url="http://127.0.0.1:8778",
            pane_id="pane-3",
            backend_kind="adb",
        )
        # Wire exactly as _run() does.
        bus = EventBus()
        pump = asyncio.create_task(_pump_bus(bus, _StdinConfirm(), sink))
        await asyncio.sleep(0.05)
        await bus.publish(Event(kind="observe", session_id="sess-wiring",
                               payload={"step": 1, "screenshot_bytes": PNG}))
        await asyncio.sleep(0.1)

        allow, reason = await guardian_check("click", {"x": 5}, "Tap Send", _Sess())
        pump.cancel()

        assert allow is True, reason
        assert len(received) == 1, f"expected 1 approval, got {len(received)}"
        pc = received[0]
        assert pc.screenshot_bytes == PNG, (
            "Guardian did not receive the observed frame: got "
            f"{len(pc.screenshot_bytes) if pc.screenshot_bytes else None}, expected {len(PNG)}"
        )
        assert pc.pane_id == "pane-3" and pc.backend_kind == "adb", (pc.pane_id, pc.backend_kind)
        print("[v034] ✓ observe frame reaches Guardian via _build_guardian + _pump_bus wiring")
    finally:
        server.cancel()
        try:
            await asyncio.wait_for(server, timeout=1.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass


async def main() -> int:
    await check_sink_fires()
    await check_gateway_roundtrip()
    await check_worker_wiring()
    print("[v034] ✓ all Guardian screenshot/rule checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
