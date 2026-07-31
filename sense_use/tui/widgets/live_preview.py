"""LivePreview — per-pane floating image viewer for the latest backend screenshot.

Wraps :mod:`textual_image` and is fed by ``observe`` events from
``TargetPane``. The widget degrades gracefully: if ``textual-image`` isn't
installed, it falls back to a ``Static`` placeholder so the rest of the
TUI still works.

CSS height/width is fixed; the underlying renderable (unicode half-cell,
Sixel, TGP, …) picks the best fit for the terminal.
"""

from __future__ import annotations

import io

from textual.containers import Container
from textual.widgets import Static

try:
    from PIL import Image as PILImage
    from textual_image.widget import Image as _ImageWidget
    _HAVE_IMAGE = True
    _IMPORT_ERR: str | None = None
except Exception as exc:  # noqa: BLE001
    _HAVE_IMAGE = False
    _IMPORT_ERR = repr(exc)
    _ImageWidget = None  # type: ignore[assignment]
    PILImage = None  # type: ignore[assignment]


class LivePreview(Container):
    """A compact image pane that swaps its content on each ``observe`` event.

    The widget composes a single child — either a ``textual_image.widget.Image``
    or a placeholder ``Static`` if the optional dep is missing. The pane
    keeps a step counter on the placeholder so users can see *something*
    is updating even when image rendering isn't available (e.g. plain
    terminal, no Sixel/Kitty support).
    """

    DEFAULT_CSS = """
    LivePreview {
        height: 10;
        background: $surface-darken-1;
        padding: 0 1;
    }
    LivePreview > .img-host { height: 100%; }
    LivePreview > .img-fallback {
        height: 100%;
        content-align: center middle;
        color: $text-muted;
    }
    """

    def __init__(self, pane_id: str | None = None) -> None:
        super().__init__(id=pane_id)
        self._image: _ImageWidget | None = None
        self._fallback: Static | None = None
        self._step: int = 0
        self._last_size: tuple[int, int] = (0, 0)

    def compose(self):
        if _HAVE_IMAGE:
            self._image = _ImageWidget(id="live-image")
            self._image.classes = "img-host"
            yield self._image
        else:
            self._fallback = Static(
                f"[live preview unavailable]\n{_IMPORT_ERR}",
                id="live-fallback",
                classes="img-fallback",
                markup=True,
            )
            yield self._fallback

    # ---- public API used by TargetPane -------------------------------

    def set_bytes(self, png_bytes: bytes | None, step: int | None = None) -> None:
        """Replace the current image with the given PNG bytes.

        Safe to call before the widget is mounted (no-op). Bytes are
        re-decoded each time so we never hold a stale PIL handle.
        """
        if step is not None:
            self._step = step

        if not _HAVE_IMAGE or self._image is None:
            if self._fallback is not None and png_bytes is not None:
                self._fallback.update(
                    f"[live preview: textual-image missing]\n"
                    f"step {self._step} · {len(png_bytes)} bytes"
                )
            return

        if png_bytes is None or not png_bytes:
            return

        try:
            # textual-image 0.13.2 mishandles raw bytes (treats them as a
            # filename) — wrap in BytesIO. PIL copies the stream into its
            # own buffer so we don't need to keep `png_bytes` alive.
            pil = PILImage.open(io.BytesIO(png_bytes))
            self._image.image = pil
            self._last_size = (pil.width, pil.height)
        except Exception as exc:  # noqa: BLE001
            # Don't crash the pane over a bad frame — log into the fallback
            # if we have one, otherwise just swallow.
            if self._fallback is not None:
                self._fallback.update(f"[image decode failed: {exc}]")
