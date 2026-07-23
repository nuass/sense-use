"""Local desktop backend (pyautogui + mss).

Controls this machine's mouse and keyboard. On macOS the terminal running
sense-use must be granted Accessibility permission (System Settings ->
Privacy & Security -> Accessibility).
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from sense_use.core.backend import ActionResult, Backend

try:
    import pyautogui  # type: ignore
except Exception:  # pragma: no cover
    pyautogui = None  # type: ignore

try:
    import mss  # type: ignore
    import mss.tools  # type: ignore
except Exception:  # pragma: no cover
    mss = None  # type: ignore


_KEY_ALIAS = {
    "enter": "enter",
    "return": "enter",
    "esc": "escape",
    "back": "escape",
    "tab": "tab",
    "space": "space",
    "delete": "delete",
    "backspace": "backspace",
    "home": "home",
    "end": "end",
    "up": "up",
    "down": "down",
    "left": "left",
    "right": "right",
}

_SENSITIVE_HINTS = re.compile(
    r"(shutdown|restart|log\s*out|sign\s*out|delete|uninstall|format|"
    r"关机|重启|注销|删除|格式化|清空)",
    re.IGNORECASE,
)


class DesktopBackend(Backend):
    kind = "desktop"

    def __init__(self, monitor: int = 1) -> None:
        if pyautogui is None or mss is None:
            raise RuntimeError(
                "desktop backend needs `pip install sense-use[desktop]` (pyautogui + mss)"
            )
        self.monitor = monitor
        self._size: tuple[int, int] | None = None
        pyautogui.FAILSAFE = True

    async def start(self) -> None:
        await self.get_size()

    async def stop(self) -> None:
        pass

    async def screenshot(self) -> bytes:
        def _grab() -> bytes:
            with mss.mss() as sct:
                mon = sct.monitors[self.monitor]
                raw = sct.grab(mon)
                # mss.tools.to_png returns encoded bytes when output is None
                return mss.tools.to_png(raw.rgb, raw.size)

        return await asyncio.to_thread(_grab)

    async def get_size(self) -> tuple[int, int]:
        if self._size is not None:
            return self._size

        def _size() -> tuple[int, int]:
            with mss.mss() as sct:
                mon = sct.monitors[self.monitor]
                return mon["width"], mon["height"]

        self._size = await asyncio.to_thread(_size)
        return self._size

    async def click(self, x: int, y: int, button: str = "left") -> ActionResult:
        def _do() -> None:
            pyautogui.click(x=int(x), y=int(y), button=button)

        await asyncio.to_thread(_do)
        return ActionResult(ok=True, detail=f"{button}-click {x},{y}")

    async def type_text(self, text: str) -> ActionResult:
        def _do() -> None:
            pyautogui.typewrite(text, interval=0.02)

        await asyncio.to_thread(_do)
        return ActionResult(ok=True, detail=f"type {len(text)}c")

    async def swipe(
        self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300
    ) -> ActionResult:
        dur = max(duration_ms, 100) / 1000.0

        def _do() -> None:
            pyautogui.moveTo(int(x1), int(y1))
            pyautogui.dragTo(int(x2), int(y2), duration=dur, button="left")

        await asyncio.to_thread(_do)
        return ActionResult(ok=True, detail=f"drag {x1},{y1}->{x2},{y2}")

    async def key(self, name: str) -> ActionResult:
        # Hotkey combos: "ctrl+a" / "cmd+shift+t"
        if "+" in name:
            parts = [p.strip().lower() for p in name.split("+")]
            await asyncio.to_thread(pyautogui.hotkey, *parts)
            return ActionResult(ok=True, detail=name)
        key = _KEY_ALIAS.get(name.lower(), name.lower())
        await asyncio.to_thread(pyautogui.press, key)
        return ActionResult(ok=True, detail=key)

    def is_sensitive(self, action: str, payload: dict[str, Any]) -> bool:
        label = str(payload.get("label", "") or payload.get("text", ""))
        if _SENSITIVE_HINTS.search(label):
            return True
        # macOS menu bar top strip
        if action == "click" and int(payload.get("y", 999)) <= 30:
            return True
        return False
