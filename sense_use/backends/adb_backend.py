"""Android ADB backend.

Uses `adb` on PATH. Wraps mobile-use-agent's ADB class when installed so we
inherit its retry/PNG-validation logic; falls back to inline subprocess calls
otherwise so `sense-use[mobile]` remains optional.
"""

from __future__ import annotations

import asyncio
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from sense_use.core.backend import ActionResult, Backend

try:
    from mobile_use.adb import ADB as _MUAdb  # type: ignore
except Exception:  # pragma: no cover
    _MUAdb = None  # type: ignore


_KEY_ALIAS = {
    "enter": "KEYCODE_ENTER",
    "back": "KEYCODE_BACK",
    "home": "KEYCODE_HOME",
    "esc": "KEYCODE_ESCAPE",
    "tab": "KEYCODE_TAB",
    "delete": "KEYCODE_DEL",
    "backspace": "KEYCODE_DEL",
    "space": "KEYCODE_SPACE",
    "menu": "KEYCODE_MENU",
    "power": "KEYCODE_POWER",
}

_SENSITIVE_HINTS = re.compile(
    r"(支付|转账|付款|删除|注销|退出登录|pay|checkout|delete|uninstall|wipe|logout|sign\s*out)",
    re.IGNORECASE,
)


class AdbBackend(Backend):
    kind = "adb"

    def __init__(self, serial: str | None = None, adb_binary: str = "adb") -> None:
        self.serial = serial
        self.adb_binary = adb_binary
        self._size: tuple[int, int] | None = None
        self._impl: Any | None = None

    async def start(self) -> None:
        if _MUAdb is not None:
            self._impl = _MUAdb(binary=self.adb_binary, serial=self.serial)
        # sanity: `adb get-state`
        rc, out = await self._run(["get-state"])
        if rc != 0 or "device" not in out:
            raise RuntimeError(f"adb device not ready: rc={rc} out={out!r}")

    async def stop(self) -> None:
        self._impl = None

    async def _run(self, args: list[str]) -> tuple[int, str]:
        cmd = [self.adb_binary]
        if self.serial:
            cmd += ["-s", self.serial]
        cmd += args
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await proc.communicate()
        return proc.returncode or 0, out.decode(errors="replace")

    async def _shell(self, cmd: str) -> str:
        rc, out = await self._run(["shell", cmd])
        return out

    async def screenshot(self) -> bytes:
        if self._impl is not None:
            path = Path(tempfile.mkstemp(suffix=".png")[1])
            try:
                await asyncio.to_thread(self._impl.screencap, path)
                return path.read_bytes()
            finally:
                try:
                    os.unlink(path)
                except OSError:
                    pass
        # fallback: exec-out streams raw PNG to stdout
        cmd = [self.adb_binary]
        if self.serial:
            cmd += ["-s", self.serial]
        cmd += ["exec-out", "screencap", "-p"]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        out, err = await proc.communicate()
        if proc.returncode != 0 or not out.startswith(b"\x89PNG"):
            raise RuntimeError(f"adb screencap failed: rc={proc.returncode} err={err[:200]!r}")
        return out

    async def get_size(self) -> tuple[int, int]:
        if self._size is not None:
            return self._size
        out = await self._shell("wm size")
        m = re.search(r"(\d+)x(\d+)", out)
        if not m:
            raise RuntimeError(f"wm size unparseable: {out!r}")
        self._size = (int(m.group(1)), int(m.group(2)))
        return self._size

    async def click(self, x: int, y: int, button: str = "left") -> ActionResult:
        await self._shell(f"input tap {int(x)} {int(y)}")
        return ActionResult(ok=True, detail=f"tap {x},{y}")

    async def type_text(self, text: str) -> ActionResult:
        # `input text` doesn't support spaces or unicode reliably.
        # For ASCII, escape spaces; for CJK, callers should paste via clipboard.
        safe = text.replace(" ", "%s").replace("'", "\\'")
        await self._shell(f"input text '{safe}'")
        return ActionResult(ok=True, detail=f"type {len(text)}c")

    async def swipe(
        self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300
    ) -> ActionResult:
        await self._shell(
            f"input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {int(duration_ms)}"
        )
        return ActionResult(ok=True, detail=f"swipe {x1},{y1}->{x2},{y2}")

    async def key(self, name: str) -> ActionResult:
        keycode = _KEY_ALIAS.get(name.lower(), name.upper())
        if not keycode.startswith("KEYCODE_"):
            keycode = f"KEYCODE_{keycode}"
        await self._shell(f"input keyevent {keycode}")
        return ActionResult(ok=True, detail=keycode)

    def is_sensitive(self, action: str, payload: dict[str, Any]) -> bool:
        label = str(payload.get("label", "") or payload.get("text", ""))
        return bool(_SENSITIVE_HINTS.search(label))
