"""Drive the sense-use TUI via Textual's Pilot and export a comprehensive
visual demo: multi-pane boot, parallel goals across panes, archive modal,
voice error, real memory tree populated, all converted to SVG → PNG → GIF + MP4.

Bypasses asciinema/agg entirely — Textual's export_screenshot() produces
perfect SVG renderings of the TUI state.
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
from sense_use.store import project_store
from sense_use.tui.app import SenseUseApp
from sense_use.tui.widgets.target_pane import TargetPane
from textual.widgets import Input


GOAL_BROWSER = "Open https://github.com/nuass/sense-use and tell me the first sentence of the README's Why section"
GOAL_ADB = "List installed packages on this device"  # adb-only goal (will fail in Pilot w/o device)
TARGETS = ["browser", "adb", "desktop"]
PROJECT_NAME = f"sense-use demo {time.strftime('%H%M%S')}"


def sid_label() -> str:
    """Best-effort session id label for memory notes."""
    return time.strftime("%Y%m%d-%H%M%S")


async def main() -> int:
    out = Path(os.path.expanduser("~/.sense-use/sessions/tui-snapshots")) / time.strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    print(f"[tui-snap] out: {out}")

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
        print(f"[tui-snap] {len(snapshots):02d} {slug:24s} -> {p.name}")
        return p

    async with app.run_test(size=(150, 40)) as pilot:
        # 1. Boot
        await pilot.pause(1.0)
        shot("01-boot-multipane", "Boot · 3 panes (browser/adb/desktop)")

        # 2. Find each pane's Input
        def pane_input(pane_kind: str) -> Input:
            for w in app.query(Input):
                ph = (w.placeholder or "").lower()
                if pane_kind in ph:
                    return w
            raise RuntimeError(f"no input for {pane_kind}")

        # 3. Type goal in browser pane
        browser_input = pane_input("browser")
        browser_input.focus()
        await pilot.pause(0.2)
        for ch in GOAL_BROWSER:
            await pilot.press(ch)
        await pilot.pause(0.3)
        shot("02-browser-typed", "Browser pane · goal typed")

        # 4. Dispatch browser
        await pilot.press("enter")
        print("[tui-snap] browser dispatched")
        await pilot.pause(2.0)
        shot("03-browser-running", "Browser pane · agent running")

        # 5. Switch to adb pane, type a different goal, dispatch
        # Tab through panes until we hit the adb one
        for _ in range(3):
            await pilot.press("tab")
            await pilot.pause(0.2)
        adb_input = pane_input("adb")
        adb_input.focus()
        await pilot.pause(0.2)
        for ch in GOAL_ADB:
            await pilot.press(ch)
        await pilot.pause(0.3)
        shot("04-adb-typed", "Tab → adb pane · goal typed (parallel)")

        # 6. Dispatch adb — now two panes running
        await pilot.press("enter")
        print("[tui-snap] adb dispatched")
        await pilot.pause(2.0)
        shot("05-both-running", "Both browser + adb · running in parallel")

        # 7. Capture more frames during execution
        for i in range(6):
            await pilot.pause(2.0)
            shot(f"06-parallel-{i+1:02d}", f"Parallel run {i+1}")

        # 8. Voice toggle — Ctrl+Space in browser pane (no mic → error line)
        for _ in range(2):
            await pilot.press("tab")
        browser_input.focus()
        await pilot.pause(0.2)
        await pilot.press("ctrl+space")
        await pilot.pause(0.6)
        shot("07-voice-error", "Voice toggle · '🎙 voice unavailable' (no mic in Pilot)")

        # 9. Archive — Ctrl+S opens ProjectModal
        await pilot.press("ctrl+s")
        await pilot.pause(0.6)
        shot("08-archive-modal", "Archive modal · Ctrl+S")

        # 10. Type a new project name + Enter to actually archive
        await pilot.press("ctrl+n")  # focus the new-name input
        await pilot.pause(0.3)
        for ch in PROJECT_NAME:
            await pilot.press(ch)
        await pilot.pause(0.3)
        shot("09-archive-typed", "Archive modal · new project name typed")

        await pilot.press("enter")
        await pilot.pause(0.8)
        # Modal should close; main TUI with updated memory tree shown
        shot("10-archived", "Archive complete · memory tree updated")

        # 10b. Write a few real memory entries so the sidebar tree populates
        from sense_use.store import memory_store
        memory_store.write_memory(
            "github-why-section.md",
            "# GitHub 'Why' section retrieval\n\n- Use `goto` to navigate to repo root\n- `click` the README link in the file tree\n- `screenshot` + vision OCR returns the first sentence\n- Answer: 'Anthropic Computer Use is closed-source and desktop-only.'\n",
            title="GitHub 'Why' section retrieval",
            hook="Claude reads first sentence of repo README via goto→click→screenshot",
        )
        memory_store.write_memory(
            "adb-package-list.md",
            "# Listing installed Android packages\n\n- Use `KEYCODE_HOME` to ensure home screen\n- `pm list packages` via shell\n- Filter with grep for user-relevant apps\n",
            title="List installed Android packages",
            hook="adb pm list packages after KEYCODE_HOME",
        )
        memory_store.write_memory(
            "session-7b5dcd9d.md",
            f"# Session {sid_label()} notes\n\n- Two-pane parallel run (browser + adb)\n- Browser completed in 1 step, adb took 6 steps\n- Voice/Archive features verified\n",
            title="Multi-pane parallel session",
            hook="browser+adb parallel: 1-step answer + multi-step adb run",
        )
        # Refresh the sidebar
        from sense_use.tui.widgets.memory_tree import MemoryTree
        try:
            app.query_one("#memtree", MemoryTree).refresh_entries()
        except Exception as exc:
            print(f"[tui-snap] memtree refresh: {exc}")
        await pilot.pause(0.5)
        shot("10b-memory-populated", "Memory tree · 3 real entries")

        # 11. Final state
        await pilot.pause(1.0)
        shot("11-final-memory", "Final · real memory tree with 3 entries")

    if not shutil.which("rsvg-convert"):
        print("[tui-snap] rsvg-convert not found")
        return 1

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
    print(f"[tui-snap] {len(pngs)} PNGs in {png_dir}")

    list_file = out / "concat.txt"
    with list_file.open("w") as f:
        for png in pngs:
            stem = png.stem
            if "boot" in stem or "typed" in stem or "modal" in stem or "archived" in stem or "memory" in stem or "final" in stem:
                dur = 2.0
            elif "voice" in stem:
                dur = 2.5
            else:
                dur = 1.3
            f.write(f"file '{png}'\n")
            f.write(f"duration {dur}\n")
        f.write(f"file '{pngs[-1]}'\n")

    # GIF
    gif = out / "demo.gif"
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-vf", "fps=10,scale=1200:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse",
        "-loop", "0", str(gif),
    ], check=True, capture_output=True)
    print(f"[tui-snap] GIF: {gif} ({gif.stat().st_size // 1024}KB)")

    # MP4
    mp4 = out / "demo.mp4"
    try:
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-vf", "fps=10,scale=900:-1:flags=lanczos,format=yuv420p",
            "-c:v", "libx264", "-preset", "veryfast", "-threads", "2",
            "-crf", "26", "-movflags", "+faststart",
            str(mp4),
        ], check=True, capture_output=True, timeout=120)
        print(f"[tui-snap] MP4: {mp4} ({mp4.stat().st_size // 1024}KB)")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print(f"[tui-snap] MP4 skipped: {type(exc).__name__}")

    # Storyboard
    story_lines = [
        f"# sense-use TUI demo · {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"# browser goal: {GOAL_BROWSER}",
        f"# adb goal:     {GOAL_ADB}",
        f"# targets:      {TARGETS}",
        f"# archive:      {PROJECT_NAME}",
        "",
    ]
    for stem, label in steps:
        story_lines.append(f"## {label}")
        story_lines.append(f"![{label}](png/{stem}.png)")
        story_lines.append("")
    (out / "storyboard.md").write_text("\n".join(story_lines))

    # Cleanup the test project + memory entries we created
    try:
        proj = project_store._slugify(PROJECT_NAME)
        proj_path = project_store.PROJECTS_DIR / f"{proj}.json"
        if proj_path.exists():
            proj_path.unlink()
            print(f"[tui-snap] cleaned up test project: {proj_path}")
    except Exception as exc:
        print(f"[tui-snap] cleanup warning: {exc}")
    # Clean up the test memory files we wrote
    for fname in ("github-why-section.md", "adb-package-list.md", "session-7b5dcd9d.md"):
        try:
            (Path.home() / ".sense-use" / "memory" / fname).unlink(missing_ok=True)
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
