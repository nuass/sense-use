"""VNC backend using vncdotool.

Any VNC-reachable machine (Docker CUA containers, remote workstations, etc.).
Requires `pip install sense-use[vnc]`.
"""

from __future__ import annotations

import asyncio
import io
import re
from typing import Any

from sense_use.core.backend import ActionResult, Backend

try:
    from vncdotool import api as _vncapi  # type: ignore
    from PIL import Image  # type: ignore
except Exception:  # pragma: no cover
    _vncapi = None  # type: ignore
    Image = None  # type: ignore


_KEY_ALIAS = {
    "enter": "enter",
    "return": "enter",
    "esc": "esc",
    "back": "esc",
    "tab": "tab",
    "space": "space",
    "delete": "del",
    "backspace": "bsp",
    "home": "home",
    "end": "end",
    "up": "up",
    "down": "down",
    "left": "left",
    "right": "right",
}

_SENSITIVE_HINTS = re.compile(
    r"(shutdown|restart|log\s*out|sign\s*out|delete|uninstall|format|"
    r"关机|重启|注销|删除|格式化)",
    re.IGNORECASE,
)


class VncBackend(Backend):
    kind = "vnc"

    def __init__(self, host: str, port: int = 5900, password: str = "") -> None:
        if _vncapi is None or Image is None:
            raise RuntimeError(
                "vnc backend needs `pip install sense-use[vnc]` (vncdotool + pillow)"
            )
        self.host = host
        self.port = port
        self.password = password
        self._client: Any = None
        self._size: tuple[int, int] | None = None

    def _endpoint(self) -> str:
        # vncdotool takes "host::port" (raw) or "host:display" (display*100 base)
        return f"{self.host}::{self.port}"

    async def start(self) -> None:
        def _connect() -> Any:
            return _vncapi.connect(self._endpoint(), password=self.password or None)

        self._client = await asyncio.to_thread(_connect)

    async def stop(self) -> None:
        if self._client is not None:
            try:
                await asyncio.to_thread(self._client.disconnect)
            finally:
                self._client = None

    async def screenshot(self) -> bytes:
        def _cap() -> bytes:
            buf = io.BytesIO()
            # captureScreen accepts binary file-like objects; format is inferred
            # from filename when str/Path — pass explicit format for BytesIO.
            self._client.captureScreen(buf, format="PNG")
            return buf.getvalue()

        return await asyncio.to_thread(_cap)

    async def get_size(self) -> tuple[int, int]:
        if self._size is not None:
            return self._size
        png = await self.screenshot()
        img = Image.open(io.BytesIO(png))
        self._size = img.size
        return self._size

    async def click(self, x: int, y: int, button: str = "left") -> ActionResult:
        btn_no = {"left": 1, "middle": 2, "right": 3}.get(button, 1)

        def _do() -> None:
            self._client.mouseMove(int(x), int(y))
            self._client.mousePress(btn_no)

        await asyncio.to_thread(_do)
        return ActionResult(ok=True, detail=f"{button}-click {x},{y}")

    async def type_text(self, text: str) -> ActionResult:
        # vncdotool's keyPress maps single chars to their ASCII keysym; non-ASCII
        # (e.g. CJK) won't type correctly — those callers should paste via the
        # target's clipboard mechanism.
        def _do() -> None:
            for ch in text:
                self._client.keyPress(ch)

        await asyncio.to_thread(_do)
        return ActionResult(ok=True, detail=f"type {len(text)}c")

    async def swipe(
        self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300
    ) -> ActionResult:
        def _do() -> None:
            self._client.mouseMove(int(x1), int(y1))
            self._client.mouseDown(1)
            self._client.mouseMove(int(x2), int(y2))
            self._client.mouseUp(1)

        await asyncio.to_thread(_do)
        return ActionResult(ok=True, detail=f"drag {x1},{y1}->{x2},{y2}")

    async def key(self, name: str) -> ActionResult:
        # vncdotool uses "-" as combo separator (e.g. "ctrl-a"); normalize "+".
        key = _KEY_ALIAS.get(name.lower(), name.lower()).replace("+", "-")

        def _do() -> None:
            self._client.keyPress(key)

        await asyncio.to_thread(_do)
        return ActionResult(ok=True, detail=key)

    def is_sensitive(self, action: str, payload: dict[str, Any]) -> bool:
        label = str(payload.get("label", "") or payload.get("text", ""))
        return bool(_SENSITIVE_HINTS.search(label))
