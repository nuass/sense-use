"""Turn v03_narrated_demo.py output into a narrated MP4 (TTS + BGM).

Reads ``narration.json`` from a recording session, synthesizes each ``say``
line with Volcengine TTS, sizes each frame to its own narration length, and
mixes a quiet ambient bed underneath. Also renders the captured ``ps`` table
into an extra frame — the process-isolation evidence is worth showing, not
just claiming.

Usage:
    python examples/build_narrated_mp4.py [session_dir]

Needs VOLC_TTS_APP_ID / VOLC_TTS_ACCESS_KEY in the environment (or in
myopcagent's .env, which this script will read as a fallback).
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import requests

SESSIONS = Path(os.path.expanduser("~/.sense-use/sessions/v03-narrated"))
TTS_URL = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
VOICE = "zh_male_jieshuoxiaoming_uranus_bigtts"
RESOURCE = "seed-tts-2.0"
FALLBACK_ENV = Path(os.path.expanduser("~/dev/myopcagent/06-工具chain/.env"))

PS_SAY = ("每个窗格都是一个独立的操作系统进程。"
          "这是运行时抓下来的真实进程表，"
          "标准输入输出流转任务、画面和审批请求。")
PS_OVERLAY = "进程隔离实证 · 每个窗格独立进程 · 通过 stdio 协同"
PAD_S = 0.45  # breathing room after each narration line


def creds() -> tuple[str, str]:
    app_id = os.getenv("VOLC_TTS_APP_ID") or os.getenv("VOLC_APPID") or ""
    access_key = os.getenv("VOLC_TTS_ACCESS_KEY") or os.getenv("VOLC_TOKEN") or ""
    if (not app_id or not access_key) and FALLBACK_ENV.exists():
        for line in FALLBACK_ENV.read_text(encoding="utf-8", errors="ignore").splitlines():
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip("\"'")
            if not app_id and k in {"VOLC_TTS_APP_ID", "VOLC_TTS_APPID", "VOLC_APPID"}:
                app_id = v
            elif not access_key and k in {"VOLC_TTS_ACCESS_KEY", "VOLC_TOKEN"}:
                access_key = v
    if not app_id or not access_key:
        raise SystemExit("[mp4] missing VOLC_TTS_APP_ID / VOLC_TTS_ACCESS_KEY")
    return app_id, access_key


def synth(text: str, app_id: str, access_key: str) -> bytes:
    resp = requests.post(
        TTS_URL,
        headers={
            "X-Api-App-Id": app_id,
            "X-Api-Access-Key": access_key,
            "X-Api-Resource-Id": RESOURCE,
            "X-Api-Connect-Id": str(uuid.uuid4()),
            "Content-Type": "application/json",
        },
        json={"req_params": {
            "text": text,
            "speaker": VOICE,
            "audio_params": {"format": "mp3", "sample_rate": 24000},
        }},
        stream=True, timeout=120,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
    chunks = []
    for line in resp.iter_lines():
        if not line:
            continue
        data = json.loads(line.decode("utf-8"))
        if data.get("code") not in {0, 20000000}:
            raise RuntimeError(json.dumps(data, ensure_ascii=False)[:300])
        if data.get("data"):
            chunks.append(base64.b64decode(data["data"]))
    if not chunks:
        raise RuntimeError("no audio returned")
    return b"".join(chunks)


def duration_of(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return float(out)


def png_size(path: Path) -> tuple[int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    w, h = out.split("x")
    return int(w), int(h)


def render_ps_card(rows: list[str], overlay: str, dest: Path, width: int = 1600) -> None:
    """Draw the captured process table as a terminal-styled card."""
    from PIL import Image, ImageDraw, ImageFont

    mono = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 26)
    cjk = ImageFont.truetype("/System/Library/Fonts/STHeiti Medium.ttc", 30)
    height = 220 + max(len(rows), 1) * 46
    img = Image.new("RGB", (width, height), (13, 17, 23))
    d = ImageDraw.Draw(img)
    d.text((60, 54), overlay, font=cjk, fill=(180, 220, 255))
    d.text((60, 112), "$ ps -eo pid,ppid,pcpu,rss,command | grep sense_use.worker",
           font=mono, fill=(120, 130, 140))
    y = 170
    for row in rows or ["(no live worker rows captured)"]:
        d.text((60, y), row, font=mono, fill=(126, 231, 135))
        y += 46
    img.save(dest)


def main() -> int:
    if len(sys.argv) > 1:
        session = Path(sys.argv[1])
    else:
        candidates = sorted(p for p in SESSIONS.glob("*") if (p / "narration.json").exists())
        if not candidates:
            raise SystemExit(f"[mp4] no recording session under {SESSIONS}")
        session = candidates[-1]
    print(f"[mp4] session: {session}")

    meta = json.loads((session / "narration.json").read_text())
    frames: list[dict] = meta["frames"]
    ps_rows: list[str] = meta.get("ps_rows", [])

    png_dir = session / "png"
    audio_dir = session / "audio"
    seg_dir = session / "seg"
    for d in (png_dir, audio_dir, seg_dir):
        d.mkdir(exist_ok=True)

    # SVG -> PNG, then splice the ps evidence card in after both-running.
    shots: list[tuple[str, Path, str]] = []
    for f in frames:
        svg = session / f["svg"]
        png = png_dir / (svg.stem + ".png")
        if not png.exists():
            subprocess.run(["rsvg-convert", "-w", "1600", "-f", "png",
                            str(svg), "-o", str(png)], check=True)
        shots.append((f["slug"], png, f["say"]))
        if f["slug"] == "both-running" and ps_rows:
            # Only claim process isolation when we actually captured the table.
            card = png_dir / "evidence-ps.png"
            render_ps_card(ps_rows, PS_OVERLAY, card)
            shots.append(("evidence-ps", card, PS_SAY))
    if not ps_rows:
        print("[mp4] WARNING: no ps rows in narration.json -> evidence card skipped")
    print(f"[mp4] {len(shots)} frames (ps evidence card: {bool(ps_rows)})")

    # The frames differ in aspect ratio (2-pane vs 9-pane grid vs the ps card),
    # so every segment must be letterboxed onto one identical canvas —
    # concat -c copy silently produces garbage on mismatched dimensions.
    canvas_w = 1280
    canvas_h = 2
    for _, png, _ in shots:
        w, h = png_size(png)
        canvas_h = max(canvas_h, round(h * canvas_w / w))
    canvas_h += canvas_h % 2
    vf = (f"scale={canvas_w}:{canvas_h}:force_original_aspect_ratio=decrease"
          f":flags=lanczos,"
          f"pad={canvas_w}:{canvas_h}:(ow-iw)/2:(oh-ih)/2:color=0x0d1117,"
          f"format=yuv420p")
    print(f"[mp4] canvas {canvas_w}x{canvas_h}")

    app_id, access_key = creds()

    # One segment per frame: still image held for exactly its narration length.
    segments: list[Path] = []
    for i, (slug, png, say) in enumerate(shots):
        mp3 = audio_dir / f"{i:02d}-{slug}.mp3"
        if not mp3.exists():
            mp3.write_bytes(synth(say, app_id, access_key))
        dur = duration_of(mp3) + PAD_S
        seg = seg_dir / f"{i:02d}-{slug}.mp4"
        # A cached segment from a run with a different canvas would break concat.
        if seg.exists() and png_size(seg) != (canvas_w, canvas_h):
            seg.unlink()
        if not seg.exists():
            subprocess.run([
                "ffmpeg", "-y", "-loop", "1", "-i", str(png), "-i", str(mp3),
                "-filter_complex",
                f"[0:v]{vf}[v];[1:a]apad[a]",
                "-map", "[v]", "-map", "[a]", "-t", f"{dur:.3f}",
                "-r", "12", "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
                "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
                str(seg),
            ], check=True, capture_output=True)
        segments.append(seg)
        print(f"[mp4] {i:02d} {slug:16s} {dur:5.1f}s  {say[:26]}...")

    total = sum(duration_of(s) for s in segments)
    print(f"[mp4] total {total:.1f}s")

    # Concat segments (uniform encode params, so the demuxer is safe here).
    listing = session / "segments.txt"
    listing.write_text("".join(f"file '{s}'\n" for s in segments))
    narrated = session / "narrated-nobgm.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
                    "-c", "copy", str(narrated)], check=True, capture_output=True)

    # Ambient bed: a soft low drone, ducked well under the narration.
    final = session / "sense-use-v03-narrated.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-i", str(narrated),
        "-f", "lavfi", "-t", f"{total:.3f}",
        "-i", "sine=frequency=110:sample_rate=44100",
        "-f", "lavfi", "-t", f"{total:.3f}",
        "-i", "sine=frequency=164.81:sample_rate=44100",
        "-f", "lavfi", "-t", f"{total:.3f}",
        "-i", "sine=frequency=220:sample_rate=44100",
        "-filter_complex",
        "[1:a][2:a][3:a]amix=inputs=3:normalize=0,tremolo=f=0.15:d=0.6,"
        "lowpass=f=600,volume=0.035,"
        f"afade=t=in:d=1.5,afade=t=out:st={max(total - 2.0, 0):.3f}:d=2.0[bed];"
        "[0:a]volume=1.0[voice];"
        "[voice][bed]amix=inputs=2:duration=first:normalize=0,"
        "alimiter=limit=0.95[aout]",
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
        "-movflags", "+faststart", str(final),
    ], check=True, capture_output=True)

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_type,codec_name,width,height,duration",
         "-of", "csv=p=0", str(final)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    kinds = {tok for line in probe.splitlines() for tok in line.split(",")}
    if not {"video", "audio"} <= kinds:
        raise SystemExit(f"[mp4] FAIL: expected video+audio streams, got {kinds}")
    if png_size(final) != (canvas_w, canvas_h):
        raise SystemExit(f"[mp4] FAIL: final size {png_size(final)} != canvas")
    got = duration_of(final)
    if abs(got - total) > 1.5:
        raise SystemExit(f"[mp4] FAIL: duration {got:.1f}s != segments {total:.1f}s")
    print(f"[mp4] {final} ({final.stat().st_size // 1024}KB, {got:.1f}s)")
    print(f"[mp4] streams: {probe.replace(chr(10), ' | ')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
