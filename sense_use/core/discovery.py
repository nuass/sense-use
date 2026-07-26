"""Target discovery — enumerate what agents can attach to on this box.

Sources
-------
- **Chrome CDP**: probe common debugging ports (9222 / 9223 / 9333 / 9334 /
  9335) with a short-timeout HTTP GET to ``/json/version``. If it responds
  with a JSON that has a "webSocketDebuggerUrl" field, it's a live CDP
  endpoint. We *don't* try to parse `ps` for `--remote-debugging-port`
  because that requires macOS accessibility perms on modern Chrome.

- **ADB**: shell out to ``adb devices -l`` and parse serial + model.

- **Desktop**: always present — one entry per monitor from ``mss.monitors``.

- **VNC**: skipped (no reliable local-service discovery without nmap).

All probes are best-effort — if the tool is missing / times out, we return
an empty list for that source instead of raising.
"""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass, field
from typing import Any


DEFAULT_CDP_PORTS: tuple[int, ...] = (9222, 9223, 9224, 9333, 9334, 9335)


@dataclass
class DiscoveredTarget:
    """One target found on the local box, ready to be turned into a pane."""

    kind: str                       # "browser" / "adb" / "desktop" / "vnc"
    title: str                      # human-readable, shown in the picker
    spec: str                       # canonical --targets string (e.g. "browser@9223")
    detail: str = ""                # extra info line (Chrome version, model, monitor size)
    metadata: dict[str, Any] = field(default_factory=dict)


# ---- individual probes ---------------------------------------------------


async def discover_chrome_cdp(
    ports: tuple[int, ...] = DEFAULT_CDP_PORTS,
    timeout: float = 0.4,
) -> list[DiscoveredTarget]:
    """Probe ``/json/version`` on each candidate port. Returns live CDP endpoints."""
    try:
        import httpx  # type: ignore
    except ImportError:
        return []

    async def _probe(port: int) -> DiscoveredTarget | None:
        url = f"http://127.0.0.1:{port}/json/version"
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.get(url)
                if r.status_code != 200:
                    return None
                data = r.json()
        except Exception:  # noqa: BLE001
            return None
        if "webSocketDebuggerUrl" not in data:
            return None
        browser = data.get("Browser", "Chrome")
        return DiscoveredTarget(
            kind="browser",
            title=f"Chrome @ :{port}",
            spec=f"browser@{port}",
            detail=browser,
            metadata={"port": port, "endpoint": f"http://127.0.0.1:{port}"},
        )

    results = await asyncio.gather(*(_probe(p) for p in ports))
    return [r for r in results if r is not None]


async def discover_adb_devices(adb_binary: str = "adb") -> list[DiscoveredTarget]:
    """Run ``adb devices -l`` and return one target per online device."""
    if shutil.which(adb_binary) is None:
        return []
    try:
        proc = await asyncio.create_subprocess_exec(
            adb_binary, "devices", "-l",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=3.0)
    except (asyncio.TimeoutError, FileNotFoundError, OSError):
        return []

    lines = stdout.decode("utf-8", errors="replace").splitlines()
    out: list[DiscoveredTarget] = []
    for line in lines[1:]:  # skip "List of devices attached"
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        serial, state = parts[0], parts[1]
        if state != "device":
            continue  # skip "offline" / "unauthorized"
        # Extract model=... if present
        model = ""
        for p in parts[2:]:
            if p.startswith("model:"):
                model = p.split(":", 1)[1]
                break
        detail = f"{model} · {state}" if model else state
        out.append(DiscoveredTarget(
            kind="adb",
            title=f"Android {serial[:12]}{'…' if len(serial) > 12 else ''}",
            spec=f"adb@{serial}",
            detail=detail,
            metadata={"serial": serial, "model": model},
        ))
    return out


def discover_desktop_monitors() -> list[DiscoveredTarget]:
    """One entry per attached monitor. Always includes at least the primary."""
    try:
        import mss  # type: ignore
        with mss.mss() as sct:
            mons = sct.monitors  # index 0 = "all", 1..N = individual
    except Exception:  # noqa: BLE001
        # mss unavailable — still expose the primary as a target so the user
        # sees something clickable.
        return [DiscoveredTarget(
            kind="desktop",
            title="This Mac (primary)",
            spec="desktop",
            detail="mss unavailable — falls back on pyautogui",
            metadata={"monitor": 1},
        )]

    out: list[DiscoveredTarget] = []
    for i, m in enumerate(mons):
        if i == 0:
            continue  # skip aggregate
        w, h = m.get("width", 0), m.get("height", 0)
        label = "primary" if i == 1 else f"monitor {i}"
        out.append(DiscoveredTarget(
            kind="desktop",
            title=f"Desktop · {label}",
            spec=f"desktop@{i}" if i > 1 else "desktop",
            detail=f"{w}×{h}",
            metadata={"monitor": i, "width": w, "height": h},
        ))
    return out


# ---- top-level entry point ----------------------------------------------


async def discover_all(
    cdp_ports: tuple[int, ...] = DEFAULT_CDP_PORTS,
) -> list[DiscoveredTarget]:
    """Run every probe in parallel and return the merged, ordered list.

    Order: browsers → adb → desktop — mirrors the "typical use" flow.
    """
    chrome_task = asyncio.create_task(discover_chrome_cdp(cdp_ports))
    adb_task = asyncio.create_task(discover_adb_devices())
    # desktop probe is sync + cheap
    desktop = discover_desktop_monitors()
    chrome, adb = await asyncio.gather(chrome_task, adb_task)
    return [*chrome, *adb, *desktop]
