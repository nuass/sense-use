"""v0.3.1 step-2 integration smoke: does LivePreview render inside a real
TargetPane under Textual Pilot? Boots one adb pane, lets a real
TaskRunner fire one ``observe`` event, and exports an SVG → PNG so we
can eyeball the floating image area.

This is the bridge between the standalone ``v031_live_preview_smoke.py``
(which proved the widget renders in isolation) and the live demo
(``tui_demo_live.py``). If this works the next step is the real demo MP4.
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
from sense_use.tui.widgets.live_preview import LivePreview
from sense_use.tui.widgets.target_pane import TargetPane


ADB_SERIAL = "TWPVAEUWQ4QWNR9H"  # USB PEAM00 (wifi dropped this morning)
GOAL = "Press HOME, then describe the foreground app briefly"


async def wait_for_observe(pane: TargetPane, timeout_s: float) -> tuple[bool, int]:
    """Block until at least one observe event has been processed by the pane."""
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        await asyncio.sleep(0.2)
        preview = pane.query_one(LivePreview)
        if preview._step >= 1:
            return True, preview._step
    return False, 0


async def main() -> int:
    out = (
        Path(os.path.expanduser("~/.sense-use/sessions/v031-integration"))
        / time.strftime("%Y%m%d-%H%M%S")
    )
    out.mkdir(parents=True, exist_ok=True)
    print(f"[v031-int] out: {out}")

    ensure_config_exists()
    cfg = load_config()
    cfg.apply_voice_env()

    app = SenseUseApp(
        cdp_url="http://127.0.0.1:9222",
        provider_key="claude",
        config=cfg,
        targets=[f"adb@{ADB_SERIAL}"],
    )

    snapshots: list[Path] = []

    def shot(slug: str, label: str) -> Path:
        svg = app.export_screenshot(title=label)
        p = out / f"snap-{len(snapshots):02d}-{slug}.svg"
        p.write_text(svg)
        snapshots.append(p)
        print(f"[v031-int] {len(snapshots):02d} {slug:28s} -> {p.name}")
        return p

    async with app.run_test(size=(140, 42)) as pilot:
        # 1. Boot
        await pilot.pause(1.5)
        shot("01-boot", "Boot · 1 adb pane (preview area empty)")

        pane = next(iter(app.panes.values()))
        print(f"[v031-int] pane title: {pane.title!r}")
        preview = pane.query_one(LivePreview)
        print(f"[v031-int] LivePreview mounted: image={preview._image is not None}")

        # 2. Type goal
        from textual.widgets import Input
        inp = pane.query_one("#pane-input", Input)
        inp.focus()
        await pilot.pause(0.3)
        for ch in GOAL:
            await pilot.press(ch)
        await pilot.pause(0.3)
        shot("02-typed", "Goal typed")

        # 3. Dispatch
        await pilot.press("enter")
        print(f"[v031-int] dispatched at t=0")

        # 4. Wait for first observe to land in LivePreview
        ok, step = await wait_for_observe(pane, timeout_s=20)
        elapsed = 0
        if ok:
            print(f"[v031-int] first observe landed at step {step}")
        else:
            print(f"[v031-int] WARN: no observe in 20s, snapshotting anyway")
        await pilot.pause(0.4)
        shot("03-preview-1", f"After step 1 observe · live preview should show phone screen")

        # 5. Let it run a couple more steps
        await pilot.pause(5.0)
        shot("04-preview-2", "After ~5s · preview should be updating per step")

        # 6. Show pane count + final state
        last_step = pane.query_one(LivePreview)._step
        last_size = pane.query_one(LivePreview)._last_size
        print(f"[v031-int] final LivePreview step={last_step} size={last_size}")

        # 7. Don't wait for full task — just check integration
        await pilot.pause(2.0)
        shot("05-final", f"Final · last_step={last_step}")

    # Convert to PNG for eyeball check
    if not shutil.which("rsvg-convert"):
        print("[v031-int] rsvg-convert missing — SVG only")
        return 0

    png_dir = out / "png"
    png_dir.mkdir(exist_ok=True)
    for svg in snapshots:
        png = png_dir / (svg.stem + ".png")
        subprocess.run(
            ["rsvg-convert", "-w", "1600", "-f", "png", str(svg), "-o", str(png)],
            check=True,
        )
    print(f"[v031-int] {len(snapshots)} PNGs in {png_dir}/")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
