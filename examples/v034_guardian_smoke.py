"""v0.3.4 Guardian smoke test: in-process gateway + client round-trip.

Spins up the FastAPI gateway, client POSTs /guardian/check, verify
local mode returns allow=True for non-blocked actions.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sense_use.guardian_client import GuardianClient
from sense_use.guardian_gateway import PendingConfirm, create_app


async def main() -> int:
    # Start gateway in background
    confirm_called: list[PendingConfirm] = []

    def confirm_callback(pc: PendingConfirm) -> None:
        confirm_called.append(pc)
        # Auto-approve for smoke test
        pc.future.set_result((True, "smoke auto approve"))

    app = create_app(mode="local", confirm_callback=confirm_callback)

    import hypercorn.asyncio
    from hypercorn.config import Config
    cfg = Config()
    cfg.bind = ["127.0.0.1:8776"]  # non-default to avoid collision
    cfg.loglevel = "error"

    server_task = asyncio.create_task(hypercorn.asyncio.serve(app, cfg))
    await asyncio.sleep(0.5)  # wait for port bind

    try:
        # Client round-trip
        client = GuardianClient(base_url="http://127.0.0.1:8776")
        result = await client.check(
            session_id="smoke-123",
            pane_id="pane-0",
            action="click",
            label="Click Search",
            args={"x": 100, "y": 200},
            backend_kind="browser",
        )
        print(f"[v034] result.allow = {result.allow}")
        print(f"[v034] result.reason = {result.reason!r}")
        print(f"[v034] result.approved_by = {result.approved_by!r}")

        # Non-blocked action should be allowed via callback
        assert result.allow is True, f"expected allow=True, got {result.allow}"
        assert len(confirm_called) == 1, f"expected 1 confirm callback, got {len(confirm_called)}"
        print("[v034] ✓ Guardian gateway round-trip OK")
        return 0
    finally:
        server_task.cancel()
        try:
            await asyncio.wait_for(server_task, timeout=1.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
