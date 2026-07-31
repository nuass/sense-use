"""Real-task sense-use demo: 2 panes (browser + adb-wifi) running real goals
in parallel, captured to SVG → PNG → MP4 via Textual Pilot.

Unlike tui_snapshots.py (which uses fake memory entries and stops before
tasks finish), this script *waits for the runner to complete* on each pane
before snapping the next frame. The result is a demo that actually proves
sense-use can drive Chrome CDP and adb-wifi at the same time.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, "/Users/cony.zhangbjgmail.com/dev/sense-use")

from sense_use.config import ensure_config_exists, load_config
from sense_use.tui.app import SenseUseApp
from sense_use.tui.widgets.target_pane import TargetPane
from textual.widgets import Input

ADB_SERIAL = "192.168.1.79:41065"
GOAL_BROWSER = "Open https://github.com/nuass/sense-use and tell me the first sentence of the README's Why section"
GOAL_ADB = "Press HOME, then take a screenshot and describe the current foreground app briefly"
TARGETS = ["browser", f"adb@{ADB_SERIAL}"]
# Hard upper bound per task (seconds) — if not done by then, snap anyway
TASK_TIMEOUT_S = 75


def pane_by_kind(app: SenseUseApp, kind: str) -> TargetPane:
    """Find the TargetPane by its title prefix."""
    for p in app.query(TargetPane):
        title = (p.title or "").lower()
        if title.startswith(kind):
            return p
    raise RuntimeError(f"no pane for {kind}")


def pane_input_for(pane: TargetPane) -> Input:
    return pane.query_one("#pane-input", Input)


async def wait_for_done(pane: TargetPane, timeout_s: float) -> tuple[bool, str]:
    """Poll pane._runner_task until done or timeout. Return (done, status)."""
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        await asyncio.sleep(0.4)
        task = getattr(pane, "_runner_task", None)
        if task is not None and task.done():
            return True, getattr(pane, "_title_status", "?")
    return False, "timeout"


async def main() -> int:
    out = (
        Path(os.path.expanduser("~/.sense-use/sessions/tui-demo-live"))
        / time.strftime("%Y%m%d-%H%M%S")
    )
    out.mkdir(parents=True, exist_ok=True)
    print(f"[tui-live] out: {out}")

    ensure_config_exists()
    cfg = load_config()
    cfg.apply_voice_env()

    app = SenseUseApp(
        cdp_url="http://127.0.0.1:9222",
        provider_key="claude",
        config=cfg,
        targets=TARGETS,
    )

    snapshots: list[Path] = []
    steps: list[tuple[str, str]] = []

    def shot(slug: str, label: str) -> Path:
        svg = app.export_screenshot(title=label)
        p = out / f"snap-{len(snapshots):02d}-{slug}.svg"
        p.write_text(svg)
        snapshots.append(p)
        steps.append((p.stem, label))
        print(f"[tui-live] {len(snapshots):02d} {slug:28s} -> {p.name}")
        return p

    async with app.run_test(size=(160, 42)) as pilot:
        # 1. Boot 2 panes
        await pilot.pause(1.5)
        shot("01-boot-2pane", f"Boot · 2 panes (browser + adb@{ADB_SERIAL})")

        browser_pane = pane_by_kind(app, "browser")
        adb_pane = pane_by_kind(app, "adb")

        # 2. Type browser goal
        bi = pane_input_for(browser_pane)
        bi.focus()
        await pilot.pause(0.3)
        for ch in GOAL_BROWSER:
            await pilot.press(ch)
        await pilot.pause(0.3)
        shot("02-browser-typed", "Browser pane · goal typed")

        # 3. Dispatch browser (real task)
        await pilot.press("enter")
        t0 = time.time()
        print(f"[tui-live] browser dispatched at t=0")

        # 4. While browser runs, type adb goal
        await pilot.pause(0.8)
        ai = pane_input_for(adb_pane)
        ai.focus()
        await pilot.pause(0.3)
        for ch in GOAL_ADB:
            await pilot.press(ch)
        await pilot.pause(0.3)
        shot("03-adb-typed", "While browser runs · adb goal typed")

        # 5. Dispatch adb (now both running in parallel)
        await pilot.press("enter")
        print(f"[tui-live] adb dispatched at t={time.time()-t0:.1f}")
        await pilot.pause(0.5)
        shot("04-both-running", "Both panes running in parallel")

        # 6. Poll for browser done
        browser_done, browser_status = await wait_for_done(browser_pane, TASK_TIMEOUT_S)
        t_b = time.time() - t0
        print(
            f"[tui-live] browser done={browser_done} status={browser_status} t={t_b:.1f}s"
        )
        shot("05-browser-done", f"Browser done · status={browser_status} · t={t_b:.0f}s")

        # 7. Poll for adb done
        adb_done, adb_status = await wait_for_done(adb_pane, TASK_TIMEOUT_S)
        t_a = time.time() - t0
        print(f"[tui-live] adb done={adb_done} status={adb_status} t={t_a:.1f}s")
        shot("06-adb-done", f"adb done · status={adb_status} · t={t_a:.0f}s")

        # 8. Final state
        await pilot.pause(1.0)
        shot("07-final", "Final · both tasks complete")

    if not shutil.which("rsvg-convert"):
        print("[tui-live] rsvg-convert not found, abort")
        return 1
    if not shutil.which("ffmpeg"):
        print("[tui-live] ffmpeg not found, abort")
        return 1

    # SVG -> PNG (1600w)
    png_dir = out / "png"
    png_dir.mkdir(exist_ok=True)
    pngs = []
    for svg in snapshots:
        png = png_dir / (svg.stem + ".png")
        subprocess.run(
            ["rsvg-convert", "-w", "1600", "-f", "png", str(svg), "-o", str(png)],
            check=True,
        )
        pngs.append(png)
    print(f"[tui-live] {len(pngs)} PNGs")

    # concat list with per-frame duration
    list_file = out / "concat.txt"
    with list_file.open("w") as f:
        for png in pngs:
            stem = png.stem
            if "boot" in stem:
                dur = 1.5
            elif "typed" in stem:
                dur = 1.2
            elif "running" in stem:
                dur = 2.5
            elif "done" in stem:
                dur = 2.5
            else:
                dur = 2.0
            f.write(f"file '{png}'\n")
            f.write(f"duration {dur}\n")
        f.write(f"file '{pngs[-1]}'\n")  # tail

    # MP4
    mp4 = out / "demo-live.mp4"
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
                "-vf", "fps=10,scale=900:-2:flags=lanczos,format=yuv420p",
                "-c:v", "libx264", "-preset", "veryfast", "-threads", "2",
                "-crf", "26", "-movflags", "+faststart",
                str(mp4),
            ],
            check=True,
            capture_output=True,
            timeout=180,
        )
        print(f"[tui-live] MP4: {mp4} ({mp4.stat().st_size // 1024}KB)")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print(f"[tui-live] MP4 failed: {type(exc).__name__} {getattr(exc, 'stderr', b'')[:200]}")

    # Storyboard markdown
    sb = [
        f"# sense-use LIVE demo · {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"- browser pane (Chrome @ 9222): {GOAL_BROWSER}",
        f"- adb pane (PFJM10 wifi @{ADB_SERIAL}): {GOAL_ADB}",
        f"- browser done: {browser_done} status={browser_status}",
        f"- adb done:     {adb_done} status={adb_status}",
        "",
    ]
    for stem, label in steps:
        sb.append(f"## {label}")
        sb.append(f"![{label}](png/{stem}.png)")
        sb.append("")
    (out / "storyboard.md").write_text("\n".join(sb))

    print(f"[tui-live] all artifacts in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
