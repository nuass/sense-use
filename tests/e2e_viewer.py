"""End-to-end viewer smoke: spawn viewer, push 20 desktop frames, close.

Runs a real PyQt window for ~4s; asserts subprocess exits cleanly.
"""

from __future__ import annotations

import asyncio
import sys

from sense_use.backends.desktop_backend import DesktopBackend
from sense_use.viewer.ipc import OverlayShape
from sense_use.viewer.spawn import spawn_viewer, stream_backend_frames


async def main() -> int:
    b = DesktopBackend()
    await b.start()
    w, h = await b.get_size()
    print(f"[main] backend up, {w}x{h}")

    proc, server, handle = await spawn_viewer("viewer-e2e", title="sense-use viewer e2e")
    print(f"[main] viewer pid={proc.pid} connected")

    stream = asyncio.create_task(stream_backend_frames(b, handle, fps=5))

    async def push_overlay_later() -> None:
        await asyncio.sleep(2.0)
        await handle.send_overlay(
            [OverlayShape("circle", w // 2, h // 2, r=30, color="#f472b6", label="target")]
        )
        print("[main] overlay pushed")

    overlay_task = asyncio.create_task(push_overlay_later())

    await asyncio.sleep(4.0)
    print("[main] closing viewer")
    await handle.close()
    stream.cancel()
    overlay_task.cancel()

    try:
        await asyncio.wait_for(proc.wait(), timeout=5)
    except asyncio.TimeoutError:
        proc.terminate()
        await proc.wait()
    print(f"[main] viewer exited rc={proc.returncode}")

    server.close()
    await server.wait_closed()
    await b.stop()
    return 0 if proc.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
