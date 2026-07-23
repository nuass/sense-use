"""Viewer IPC — length-prefixed JSON over Unix socket.

Frame protocol
--------------

Every message = 4-byte big-endian length header, then JSON body (utf-8).
Binary payloads (screenshot PNG) are base64-encoded inside JSON. This keeps
the protocol dependency-free (no msgpack); PNG is already compressed so the
b64 overhead is fine for 30 fps up to ~1080p.

Message kinds
-------------

Main process -> viewer subprocess:
    {"kind": "frame",   "png_b64": "...", "w": 1920, "h": 1080}
    {"kind": "overlay", "shapes": [{"type": "circle", "x": 100, "y": 200, "r": 24, "color": "#f6c"}]}
    {"kind": "title",   "text": "browser · session <id>"}
    {"kind": "close"}

Viewer subprocess -> main process:
    {"kind": "click",   "x": 123, "y": 456, "button": "left"}
    {"kind": "closed"}
    {"kind": "hello",   "pid": 12345}

Socket path
-----------

    ~/.sense-use/sockets/viewer-<session_id>.sock

Kept short (macOS AF_UNIX has a 104-byte path limit).
"""

from __future__ import annotations

import asyncio
import base64
import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator

SOCK_DIR = Path.home() / ".sense-use" / "sockets"


def socket_path(session_id: str) -> Path:
    SOCK_DIR.mkdir(parents=True, exist_ok=True)
    return SOCK_DIR / f"viewer-{session_id[:16]}.sock"


def _encode(msg: dict[str, Any]) -> bytes:
    body = json.dumps(msg, ensure_ascii=False).encode("utf-8")
    return struct.pack(">I", len(body)) + body


async def send_json(writer: asyncio.StreamWriter, msg: dict[str, Any]) -> None:
    writer.write(_encode(msg))
    await writer.drain()


async def send_frame(writer: asyncio.StreamWriter, png: bytes, w: int, h: int) -> None:
    await send_json(
        writer,
        {"kind": "frame", "png_b64": base64.b64encode(png).decode("ascii"), "w": w, "h": h},
    )


async def read_json(reader: asyncio.StreamReader) -> dict[str, Any] | None:
    header = await reader.readexactly(4) if not reader.at_eof() else b""
    if len(header) < 4:
        return None
    (length,) = struct.unpack(">I", header)
    body = await reader.readexactly(length)
    return json.loads(body.decode("utf-8"))


@dataclass
class OverlayShape:
    type: str  # "circle" / "rect"
    x: int
    y: int
    r: int = 0
    w: int = 0
    h: int = 0
    color: str = "#f472b6"
    label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "x": self.x,
            "y": self.y,
            "r": self.r,
            "w": self.w,
            "h": self.h,
            "color": self.color,
            "label": self.label,
        }


async def listen(session_id: str) -> tuple[asyncio.Server, "ViewerHandle"]:
    """Start a Unix-socket server for the given session; returns a handle
    the main process uses to push frames/overlays and receive clicks.
    """
    path = socket_path(session_id)
    if path.exists():
        path.unlink()
    handle = ViewerHandle()
    server = await asyncio.start_unix_server(handle._on_connect, path=str(path))
    return server, handle


class ViewerHandle:
    """Main-process side. Push frames/overlays; iterate `events()` to get clicks."""

    def __init__(self) -> None:
        self._writer: asyncio.StreamWriter | None = None
        self._events: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._connected: asyncio.Event = asyncio.Event()

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    async def wait_connected(self, timeout: float = 10.0) -> None:
        await asyncio.wait_for(self._connected.wait(), timeout=timeout)

    async def _on_connect(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self._writer = writer
        self._connected.set()
        try:
            while True:
                msg = await read_json(reader)
                if msg is None:
                    break
                await self._events.put(msg)
        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        finally:
            self._connected.clear()
            self._writer = None
            await self._events.put({"kind": "closed"})

    async def send_frame(self, png: bytes, w: int, h: int) -> None:
        if self._writer is None:
            return
        try:
            await send_frame(self._writer, png, w, h)
        except (BrokenPipeError, ConnectionResetError):
            self._connected.clear()
            self._writer = None

    async def send_overlay(self, shapes: list[OverlayShape]) -> None:
        if self._writer is None:
            return
        try:
            await send_json(
                self._writer,
                {"kind": "overlay", "shapes": [s.to_dict() for s in shapes]},
            )
        except (BrokenPipeError, ConnectionResetError):
            self._connected.clear()
            self._writer = None

    async def send_title(self, text: str) -> None:
        if self._writer is None:
            return
        try:
            await send_json(self._writer, {"kind": "title", "text": text})
        except (BrokenPipeError, ConnectionResetError):
            self._connected.clear()
            self._writer = None

    async def close(self) -> None:
        if self._writer is not None:
            try:
                await send_json(self._writer, {"kind": "close"})
            except Exception:
                pass

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        while True:
            ev = await self._events.get()
            yield ev
            if ev.get("kind") == "closed":
                return
