"""v0.3 narrated demo: records frames + a matching Chinese narration script.

Runs two real tasks in parallel (Chrome CDP + adb), then snapshots the
9-pane grid, so every frame is a real render rather than a mockup. Also
captures `ps` output mid-run as evidence that each pane genuinely occupies
its own OS process — the claim v0.3.3 rests on.

Emits `narration.json` alongside the SVGs; build_narrated_mp4.py turns that
into TTS audio and muxes the final video.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sense_use.config import ensure_config_exists, load_config
from sense_use.tui.app import SenseUseApp
from sense_use.tui.widgets.target_pane import TargetPane
from textual.widgets import Input

ADB_SERIAL = "TWPVAEUWQ4QWNR9H"
GOAL_BROWSER = "Open https://github.com/nuass/sense-use and tell me what the README says it does"
GOAL_ADB = "Press HOME, then take a screenshot and describe the foreground app briefly"
TARGETS = ["browser", f"adb@{ADB_SERIAL}"]
TASK_TIMEOUT_S = 240  # real multi-round LLM tasks routinely need >90s

GRID_TARGETS = [
    "browser", "browser@9223", f"adb@{ADB_SERIAL}",
    "desktop", "desktop@2", "vnc@10.0.0.5:5901",
    "vnc@10.0.0.6:5901", "vnc@10.0.0.7:5901", "browser@9333",
]


def pane_by_kind(app: SenseUseApp, kind: str) -> TargetPane:
    short_prefix = {"browser": "b", "adb": "a"}.get(kind, kind)
    for p in app.query(TargetPane):
        if (p.title or "").lower().startswith(short_prefix):
            return p
    raise RuntimeError(f"no pane for {kind}")


async def wait_for_done(pane: TargetPane, timeout_s: float) -> tuple[bool, str]:
    """Wait until the pane reaches a terminal state.

    Keyed on the pane's own status, not on the pump task: the pump keeps
    awaiting the worker's stdout well after the terminal ``done``/``error``
    event has already been rendered, so waiting on the task would report a
    timeout for a task that visibly finished.
    """
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        await asyncio.sleep(0.4)
        status = getattr(pane, "_title_status", "?")
        if status in ("done", "error"):
            return True, status
        task = getattr(pane, "_pump_task", None)
        if task is not None and task.done():
            return True, status
    return False, "timeout"


def outcome_lines(subject: str, status: str, elapsed: float,
                  tail: tuple[str, str] | None = None) -> tuple[str, str]:
    """Build overlay + narration from the outcome we actually observed.

    Never assert completion the run did not reach: a demo that narrates
    success over a timed-out pane is a false claim, and the on-screen
    status would contradict the voice-over anyway.
    """
    if status == "done":
        overlay = f"{subject}任务完成 · {elapsed:.0f} 秒"
        say = f"{subject}任务完成，用了 {elapsed:.0f} 秒，答案直接回到对应窗格里。"
    elif status == "error":
        overlay = f"{subject}任务报错 · {elapsed:.0f} 秒 · 错误已回显"
        say = (f"{subject}任务这一轮失败了，用了 {elapsed:.0f} 秒。"
               "失败原因直接回显在窗格里，不会被悄悄吞掉。")
    else:
        overlay = f"{subject}任务仍在进行 · 已 {elapsed:.0f} 秒 · 状态 {status}"
        say = (f"{subject}任务还在推进，已经 {elapsed:.0f} 秒。"
               "长任务不阻塞界面，每一步的进度都实时回显。")
    if tail:
        overlay = f"{overlay} · {tail[0]}"
        say = say + tail[1]
    return overlay, say


def worker_process_table() -> list[str]:
    """Snapshot this run's sense_use.worker processes (the v0.3.3 evidence).

    Filtered to our own children: orphaned workers from earlier runs would
    otherwise inflate the evidence card with processes we did not spawn.
    """
    me = os.getpid()
    try:
        out = subprocess.run(
            ["ps", "-eo", "pid,ppid,pcpu,rss,command"],
            capture_output=True, text=True, timeout=10,
        ).stdout
    except Exception:
        return []
    rows, skipped = [], 0
    for line in out.splitlines():
        if "sense_use.worker" in line and "grep" not in line:
            parts = line.split(None, 4)
            if len(parts) != 5:
                continue
            pid, ppid, cpu, rss, cmd = parts
            if ppid != str(me):
                skipped += 1
                continue
            backend = ""
            if "--backend" in cmd:
                seg = cmd.split("--backend", 1)[1].strip().split()
                backend = seg[0] if seg else ""
            rows.append(f"PID {pid:>6}  PPID {ppid:>6}  CPU {cpu:>5}%  "
                        f"RSS {int(rss)//1024:>4}MB  backend={backend}")
    if skipped:
        print(f"[v03] skipped {skipped} worker row(s) not spawned by pid {me}")
    return rows


async def main() -> int:
    out = (Path(os.path.expanduser("~/.sense-use/sessions/v03-narrated"))
           / time.strftime("%Y%m%d-%H%M%S"))
    out.mkdir(parents=True, exist_ok=True)
    print(f"[v03] out: {out}")

    ensure_config_exists()
    cfg = load_config()
    cfg.apply_voice_env()

    frames: list[dict] = []

    def shot(app: SenseUseApp, slug: str, overlay: str, say: str) -> None:
        """Snapshot one frame + the narration line that goes with it."""
        idx = len(frames)
        svg = app.export_screenshot(title=overlay)
        p = out / f"snap-{idx:02d}-{slug}.svg"
        p.write_text(svg)
        frames.append({"svg": p.name, "slug": slug, "overlay": overlay, "say": say})
        print(f"[v03] {idx:02d} {slug:22s} say={say[:34]}...")

    # ---------- Act 1: two real tasks in parallel ----------
    app = SenseUseApp(cdp_url="http://127.0.0.1:9222", provider_key="claude",
                      config=cfg, targets=TARGETS)
    ps_rows: list[str] = []

    async with app.run_test(size=(160, 42)) as pilot:
        await pilot.pause(1.5)
        shot(app, "boot",
             "sense-use v0.3 · 一个终端里同时接管浏览器与真机",
             "sense-use 是一个自托管的多智能体运行时。"
             "一个终端里，可以同时接管浏览器、安卓真机和桌面。")

        bp, ap = pane_by_kind(app, "browser"), pane_by_kind(app, "adb")

        bp.query_one("#pane-input", Input).focus()
        await pilot.pause(0.3)
        for ch in GOAL_BROWSER:
            await pilot.press(ch)
        shot(app, "browser-typed",
             "左窗格：用自然语言下达浏览器任务",
             "任务用自然语言下达。左边这一格，交给它一个浏览器任务。")

        await pilot.press("enter")
        t0 = time.time()
        await pilot.pause(0.8)

        ap.query_one("#pane-input", Input).focus()
        await pilot.pause(0.3)
        for ch in GOAL_ADB:
            await pilot.press(ch)
        shot(app, "adb-typed",
             "浏览器仍在跑，同时给真机下第二个任务",
             "不用等它跑完。浏览器还在工作，"
             "我们同时给右边的安卓真机下第二个任务。")

        await pilot.press("enter")
        await pilot.pause(2.0)
        # Grab process evidence while both workers are actually alive.
        ps_rows = worker_process_table()
        print(f"[v03] captured {len(ps_rows)} live worker rows")

        shot(app, "both-running",
             "两个任务真正并行 · 每格实时回显模型看到的画面",
             "两个任务真正在并行推进。"
             "每个窗格实时回显模型此刻看到的画面，"
             "它在看什么，一眼就能确认。")

        b_done, b_status = await wait_for_done(bp, TASK_TIMEOUT_S)
        tb = time.time() - t0
        print(f"[v03] browser done={b_done} status={b_status} t={tb:.1f}s")
        shot(app, "browser-done", *outcome_lines("浏览器", b_status, tb))

        a_done, a_status = await wait_for_done(ap, TASK_TIMEOUT_S)
        ta = time.time() - t0
        print(f"[v03] adb done={a_done} status={a_status} t={ta:.1f}s")
        shot(app, "adb-done", *outcome_lines(
            "真机", a_status, ta,
            tail=("两条链路互不阻塞",
                  "两条链路互不阻塞，一个卡住不会拖慢另一个。")))

    # ---------- Act 2: the 9-pane grid ----------
    app2 = SenseUseApp(cdp_url="http://127.0.0.1:9222", provider_key="claude",
                       config=cfg, targets=GRID_TARGETS)
    async with app2.run_test(size=(200, 52)) as pilot2:
        await pilot2.pause(2.0)
        shot(app2, "grid-3x3",
             "9 个目标 · 自动排成 3×3 · 标题自动压缩",
             "目标变多时，界面自己重排。"
             "九个目标自动排成三乘三，标题也跟着压缩，"
             "不需要手动调整布局。")

    (out / "narration.json").write_text(
        json.dumps({"frames": frames, "ps_rows": ps_rows},
                   ensure_ascii=False, indent=2))
    print(f"[v03] {len(frames)} frames + {len(ps_rows)} ps rows -> {out}/narration.json")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
