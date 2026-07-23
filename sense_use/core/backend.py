"""Backend abstraction — all targets (browser/mobile/desktop/vnc) implement this interface.

Coordinate space contract
-------------------------

Every backend uses **native pixels of the frame returned by ``screenshot()``**.
This means:

- **ADB**: device physical pixels (matches ``wm size``). On modern phones this
  is the display's raw resolution (e.g. 1080x2400).
- **Browser (CDP)**: CSS pixels of the current viewport. Retina scaling is
  already baked into Playwright's coordinate system.
- **Desktop (macOS Retina)**: mss returns *physical* pixels while pyautogui
  clicks in *logical* pixels. ``DesktopBackend`` normalizes screenshot output
  to logical coordinates by requesting the primary monitor's logical size —
  callers should treat the frame and click coordinates as identical.
- **VNC**: the remote framebuffer's own resolution.

VLM providers must send clicks in the same space they observed. TaskRunner
does no coordinate transformation — one space, one frame, one click.

Sensitive-action payload contract
---------------------------------

When TaskRunner invokes ``backend.is_sensitive(action, payload)`` the
``payload`` dict is the model's decision ``args`` merged with the action
name. Keys backends may read (all optional):

- ``x``, ``y`` (int, native pixels) — target coordinates for click/swipe
- ``label`` (str) — human-readable element name from the model's decision
- ``text`` (str) — text about to be typed (used by browser/desktop for
  detecting "delete"/"logout" in prompts)
- ``url`` (str) — for browser goto actions

Backends should treat missing keys as safe defaults (never sensitive if
they can't tell). See ``sense_use/backends/*.py`` for concrete uses.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ActionResult:
    ok: bool
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)


class Backend(ABC):
    """
    Uniform interface for all execution backends.

    All coordinates are in the native pixel space of ``screenshot()`` output.
    See the module docstring for the full coordinate + payload contract.
    """

    kind: str = "abstract"

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    async def screenshot(self) -> bytes:
        """Return a PNG-encoded screenshot of the current viewport."""

    @abstractmethod
    async def get_size(self) -> tuple[int, int]:
        """Return (width, height) in pixels. Must match ``screenshot()`` output."""

    @abstractmethod
    async def click(self, x: int, y: int, button: str = "left") -> ActionResult: ...

    @abstractmethod
    async def type_text(self, text: str) -> ActionResult: ...

    @abstractmethod
    async def swipe(
        self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300
    ) -> ActionResult: ...

    @abstractmethod
    async def key(self, name: str) -> ActionResult:
        """Named keys: enter / esc / back / home / tab / ctrl+a / ..."""

    def is_sensitive(self, action: str, payload: dict[str, Any]) -> bool:
        """Return True if this action requires human ✅/❌ confirmation.

        ``payload`` follows the contract in this module's docstring: may
        include ``x``, ``y``, ``label``, ``text``, ``url``.
        """
        return False
