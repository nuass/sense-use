"""IPC round-trip: main-process socket server + fake client thread."""

import asyncio
import json
import os
import socket
import struct

import pytest

from sense_use.viewer.ipc import OverlayShape, listen, socket_path


def _fake_client(path: str, out_queue: asyncio.Queue) -> None:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(path)
    hello = json.dumps({"kind": "hello", "pid": os.getpid()}).encode()
    s.sendall(struct.pack(">I", len(hello)) + hello)

    header = s.recv(4)
    (length,) = struct.unpack(">I", header)
    body = b""
    while len(body) < length:
        body += s.recv(length - len(body))
    msg = json.loads(body.decode())
    out_queue.put_nowait(msg)

    click = json.dumps({"kind": "click", "x": 42, "y": 7, "button": "left"}).encode()
    s.sendall(struct.pack(">I", len(click)) + click)
    s.close()


@pytest.mark.asyncio
async def test_viewer_ipc_roundtrip():
    server, handle = await listen("pytest-ipc")
    path = str(socket_path("pytest-ipc"))
    client_recv: asyncio.Queue = asyncio.Queue()

    loop = asyncio.get_running_loop()
    fut = loop.run_in_executor(None, _fake_client, path, client_recv)

    await handle.wait_connected(timeout=5)
    await handle.send_frame(b"\x89PNGtest", 800, 600)

    got_click = False
    async for ev in handle.events():
        if ev.get("kind") == "click":
            assert ev["x"] == 42 and ev["y"] == 7
            got_click = True
        if ev.get("kind") == "closed":
            break

    assert got_click
    frame_msg = client_recv.get_nowait()
    assert frame_msg["kind"] == "frame" and frame_msg["w"] == 800

    server.close()
    await server.wait_closed()
    await fut


def test_overlay_shape_dict():
    s = OverlayShape("circle", 10, 20, r=30, color="#abc")
    d = s.to_dict()
    assert d["type"] == "circle" and d["r"] == 30 and d["color"] == "#abc"
