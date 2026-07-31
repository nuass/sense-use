"""v0.3.2 step-1 smoke: verify PaneGrid auto-layouts N=3/6/9 panes.

Boots the app with multiple targets and exports one SVG per scenario
(1×3, 2×3, 3×3) so we can eyeball the column count + short titles.
Doesn't actually run any task — just layout.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sense_use.config import ensure_config_exists, load_config
from sense_use.tui.app import SenseUseApp


# 9 fake-but-valid targets. Browser/Adb/Desktop. ADB serial is the
# known USB one — boot doesn't connect, only `Enter` does, so the
# adb-backend just sits in "idle" until the user types.
TARGETS_3 = ["browser", "browser@9223", f"adb@TWPVAEUWQ4QWNR9H"]
TARGETS_6 = TARGETS_3 + ["desktop", "desktop@2", "vnc@10.0.0.5:5901"]
TARGETS_9 = TARGETS_6 + ["vnc@10.0.0.6:5901", "vnc@10.0.0.7:5901", "browser@9333"]


async def boot_once(out: Path, label: str, targets: list[str]) -> Path:
    ensure_config_exists()
    cfg = load_config()
    cfg.apply_voice_env()
    app = SenseUseApp(
        cdp_url="http://127.0.0.1:9222",
        provider_key="claude",
        config=cfg,
        targets=targets,
    )
    async with app.run_test(size=(200, 50)) as pilot:
        await pilot.pause(1.5)
        svg = app.export_screenshot(title=label)
        p = out / f"grid-{len(targets):02d}pane.svg"
        p.write_text(svg)
        from sense_use.tui.widgets.pane_grid import columns_for
        print(f"[v032] {len(targets)} panes -> {p.name} · cols={columns_for(len(targets))} · titles={list(app.panes.keys())}")
        for pane in app.panes.values():
            print(f"  · {pane.id!r:14s} title={pane.title!r}")
    return p


async def main() -> int:
    out = (
        Path(os.path.expanduser("~/.sense-use/sessions/v032-grid"))
        / time.strftime("%Y%m%d-%H%M%S")
    )
    out.mkdir(parents=True, exist_ok=True)
    print(f"[v032] out: {out}")

    snaps = []
    for n, targets in [(3, TARGETS_3), (6, TARGETS_6), (9, TARGETS_9)]:
        p = await boot_once(out, f"{n} panes · expected {('1x'+str(n), '2x3', '3x3')[0 if n<=3 else 1 if n<=6 else 2]}", targets)
        snaps.append(p)

    if not shutil.which("rsvg-convert"):
        print("[v032] rsvg-convert missing — SVG only")
        return 0

    png_dir = out / "png"
    png_dir.mkdir(exist_ok=True)
    for svg in snaps:
        png = png_dir / (svg.stem + ".png")
        subprocess.run(
            ["rsvg-convert", "-w", "1800", "-f", "png", str(svg), "-o", str(png)],
            check=True,
        )
    print(f"[v032] {len(snaps)} PNGs in {png_dir}/")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
