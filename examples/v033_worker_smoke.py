"""v0.3.3 smoke test: WorkerProcess spawns worker subprocess, reads events.

Runs a browser backend with a trivial 1-step goal to verify the full
round-trip: spawn → user_msg → observe → think → done.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sense_use.worker_proc import WorkerProcess


async def main() -> int:
    wp = WorkerProcess(
        backend_spec="browser",
        provider_key="claude",
        goal="What is the page title (1 step only)?",
        max_steps=1,
    )
    await wp.start()
    print(f"[smoke] worker started, reading events...")

    n_events = 0
    async for ev in wp.events():
        print(f"[smoke] event={ev['event']!r}")
        n_events += 1
        if ev["event"] == "done":
            print(f"[smoke] answer={ev['answer']!r}")
        elif ev["event"] == "error":
            print(f"[smoke] ERROR: {ev['reason']}")
        elif ev["event"] == "observe":
            print(f"[smoke] screenshot size={len(ev['screenshot_bytes'])} bytes")

    await wp.stop()
    print(f"[smoke] total events={n_events}")
    return 0 if n_events > 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
