"""sense-use headless demo runner — verifies the observe→think→act loop on a real
Chrome 9222 page, prints a transcript, and saves screenshots to a session dir.

Usage:
    python -m sense_use.examples.headless_demo "Open https://github.com/nuass/sense-use and tell me the first sentence of the README's Why section"
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

from sense_use.backends.browser_backend import BrowserBackend
from sense_use.core.event_bus import Event, EventBus
from sense_use.core.session import Session
from sense_use.core.task_runner import TaskRunner
from sense_use.models.provider_registry import all_specs, build


async def main(goal: str) -> int:
    sessions_root = Path.home() / ".sense-use" / "sessions" / "demos"
    sessions_root.mkdir(parents=True, exist_ok=True)
    sid = time.strftime("%Y%m%d-%H%M%S")
    out = sessions_root / sid
    out.mkdir(exist_ok=True)
    log = out / "transcript.jsonl"
    log.write_text("")

    provider_key = os.environ.get("SENSE_USE_DEMO_PROVIDER", "claude")
    print(f"[demo] provider={provider_key}  session={sid}")
    print(f"[demo] goal: {goal}\n")

    backend = BrowserBackend(cdp_url="http://127.0.0.1:9222")
    await backend.start()

    spec = next((s for s in all_specs() if s.key == provider_key), None)
    if spec is None:
        print(f"[demo] provider {provider_key!r} not registered")
        return 2
    cfg = {
        p.name: os.environ.get(p.env) if (p.env and p.kind == "secret") else None
        for p in spec.params
    }
    cfg = {k: v for k, v in cfg.items() if v}
    try:
        provider = build(provider_key, **cfg)
    except Exception as exc:
        print(f"[demo] provider init failed: {exc}")
        return 3

    session = Session(id=sid, goal=goal, max_steps=6)
    bus = EventBus()
    q: asyncio.Queue[Event] = bus.subscribe()

    runner = TaskRunner(session=session, backend=backend, provider=provider, bus=bus)

    async def consumer():
        with log.open("a") as f:
            try:
                while True:
                    ev = await q.get()
                    payload = {k: v for k, v in ev.payload.items() if k != "screenshot_bytes"}
                    if "screenshot_bytes" in ev.payload:
                        (out / f"step-{ev.payload.get('step', 0):02d}.png").write_bytes(
                            ev.payload["screenshot_bytes"]
                        )
                        payload["screenshot_path"] = f"step-{ev.payload.get('step', 0):02d}.png"
                    line = json.dumps({"kind": ev.kind, **payload}, ensure_ascii=False)
                    f.write(line + "\n")
                    f.flush()
            except asyncio.CancelledError:
                raise

    consumer_task = asyncio.create_task(consumer())
    await asyncio.sleep(0)  # let consumer start and subscribe its queue
    try:
        answer = await asyncio.wait_for(runner.run(), timeout=120)
    except Exception as exc:
        answer = f"ERROR: {exc!r}"
    # drain remaining events before cancelling
    await asyncio.sleep(0.5)
    consumer_task.cancel()
    try:
        await consumer_task
    except (asyncio.CancelledError, Exception):
        pass

    print(f"\n[demo] final answer: {answer}")
    print(f"[demo] artifacts: {out}")
    await backend.stop()
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('usage: python -m sense_use.examples.headless_demo "GOAL"')
        sys.exit(1)
    sys.exit(asyncio.run(main(sys.argv[1])))
