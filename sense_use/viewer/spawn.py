"""Spawn helper: main process starts the viewer subprocess and streams frames."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from sense_use.viewer.ipc import ViewerHandle, listen, socket_path

if TYPE_CHECKING:
    from sense_use.core.backend import Backend


async def spawn_viewer(session_id: str, title: str = "sense-use") -> tuple[
    asyncio.subprocess.Process, asyncio.Server, ViewerHandle
]:
    """Start Unix-socket server, then launch `python -m sense_use.viewer` client.

    Waits until the subprocess dials back in (or times out). Returns
    (process, server, handle) so the caller can pump frames / read clicks /
    kill the subprocess later.
    """
    server, handle = await listen(session_id)
    sock = socket_path(session_id)

    # On some conda/system Python installs the Qt platform plugin path isn't
    # discoverable — hint it explicitly if we can locate the plugins dir.
    env = {**os.environ}
    if "QT_QPA_PLATFORM_PLUGIN_PATH" not in env:
        try:
            import PyQt6  # type: ignore

            pyqt_dir = Path(PyQt6.__file__).parent
            plugins = pyqt_dir / "Qt6" / "plugins" / "platforms"
            if plugins.is_dir():
                env["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(plugins)
        except Exception:
            pass

    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "sense_use.viewer",
        str(sock),
        "--title",
        title,
        env=env,
    )
    try:
        await handle.wait_connected(timeout=10)
    except asyncio.TimeoutError:
        try:
            proc.terminate()
        except ProcessLookupError:
            pass
        await proc.wait()
        raise RuntimeError(
            f"viewer subprocess did not connect within 10s (rc={proc.returncode})"
        )
    return proc, server, handle


async def stream_backend_frames(
    backend: "Backend", handle: ViewerHandle, fps: float = 6.0
) -> None:
    """Poll the backend at `fps` and push each PNG to the viewer.

    Runs until the viewer disconnects. Wrap in `asyncio.create_task` so it
    lives alongside the agent loop.
    """
    interval = 1.0 / max(fps, 1.0)
    w, h = await backend.get_size()
    await handle.send_title(f"{backend.kind} · {w}x{h}")
    while handle.connected:
        try:
            png = await backend.screenshot()
            await handle.send_frame(png, w, h)
        except Exception:
            # Screen may be locked or the target briefly gone — retry next tick.
            pass
        await asyncio.sleep(interval)
