"""v0.3.1 step-1 smoke test: verify textual-image can render a real adb
screenshot inside a Textual Pilot and export it via SVG → PNG.

If this works, the live preview path is viable. If the rendered image
shows as a placeholder/empty, we know the headless Pilot can't show
real images (but the live TUI can) — in that case we fall back to
embedding only the last image as a static thumbnail.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import io

from PIL import Image as PILImage
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Static
from textual_image.widget import Image as ImageWidget


ADB_SERIAL = "TWPVAEUWQ4QWNR9H"  # PEAM00 USB (fallback after wifi dropped)


def grab_adb_screenshot() -> bytes:
    """Take a real screenshot from PFJM10 over adb wifi and return PNG bytes."""
    import tempfile
    out = Path(tempfile.mkstemp(suffix=".png")[1])
    try:
        subprocess.run(
            ["adb", "-s", ADB_SERIAL, "exec-out", "screencap", "-p"],
            stdout=out.open("wb"), check=True, timeout=10,
        )
        return out.read_bytes()
    finally:
        try:
            out.unlink()
        except OSError:
            pass


class SmokeApp(App):
    CSS = """
    Screen { layout: vertical; padding: 1; }
    #title { height: 3; content-align: center middle; background: $primary 20%; }
    #img { height: 1fr; border: solid $accent; }
    """

    def __init__(self, png_bytes: bytes) -> None:
        super().__init__()
        # textual-image 0.13.2 has a bug with raw bytes (opens as filename)
        # — wrap as PIL.Image to be safe.
        self.png_image = PILImage.open(io.BytesIO(png_bytes))

    def compose(self) -> ComposeResult:
        yield Static(f"v0.3.1 smoke · {self.png_image.size} from {ADB_SERIAL}", id="title")
        yield ImageWidget(self.png_image, id="img")


def main() -> int:
    out = Path(os.path.expanduser("~/.sense-use/sessions/v031-smoke")) / time.strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    print(f"[smoke] out: {out}")

    print(f"[smoke] grabbing screenshot from {ADB_SERIAL} ...")
    png = grab_adb_screenshot()
    print(f"[smoke] got {len(png)} bytes (PNG: {png[:8]!r})")

    from textual.widgets import Static
    async def go() -> None:
        app = SmokeApp(png)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(1.0)
            svg = app.export_screenshot(title="v0.3.1 smoke test")
            (out / "smoke.svg").write_text(svg)
            print(f"[smoke] SVG saved ({(out / 'smoke.svg').stat().st_size} bytes)")

    asyncio.run(go())

    # Convert SVG to PNG and check size
    svg = out / "smoke.svg"
    png_out = out / "smoke.png"
    subprocess.run(
        ["rsvg-convert", "-w", "1600", "-f", "png", str(svg), "-o", str(png_out)],
        check=True,
    )
    print(f"[smoke] PNG saved ({png_out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
