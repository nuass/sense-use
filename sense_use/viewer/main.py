"""Floating observation window (PyQt6 subprocess).

Run as:

    python -m sense_use.viewer <socket_path> [--title "text"]

The main process owns the socket server; this subprocess connects as a client,
receives PNG frames + overlays, and sends back user clicks.
"""

from __future__ import annotations

import argparse
import base64
import os
import socket
import struct
import sys
import threading
from dataclasses import dataclass
from queue import Empty, Queue
from typing import Any

try:
    from PyQt6.QtCore import QPoint, QRect, Qt, QTimer, pyqtSignal
    from PyQt6.QtGui import QColor, QImage, QPainter, QPen
    from PyQt6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget
except ImportError as e:  # pragma: no cover
    print(f"PyQt6 not installed: {e}. Install with: pip install sense-use[viewer]", file=sys.stderr)
    sys.exit(2)


@dataclass
class _Shape:
    type: str
    x: int
    y: int
    r: int
    w: int
    h: int
    color: str
    label: str


class ViewerWindow(QWidget):
    click_signal = pyqtSignal(int, int, str)

    def __init__(self, title: str = "sense-use viewer") -> None:
        super().__init__()
        self.setWindowTitle(title)
        # Frameless-with-header: keep normal window but always-on-top-toggleable
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.resize(720, 540)
        self._img: QImage | None = None
        self._img_size: tuple[int, int] = (0, 0)
        self._shapes: list[_Shape] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._label = _PaintLabel(self)
        self._label.click_signal = self.click_signal
        layout.addWidget(self._label)

    def set_frame(self, png_b64: str, w: int, h: int) -> None:
        raw = base64.b64decode(png_b64)
        img = QImage.fromData(raw, "PNG")
        if img.isNull():
            return
        self._img = img
        self._img_size = (w, h)
        self._label.set_image(img, w, h, self._shapes)

    def set_overlay(self, shapes: list[dict[str, Any]]) -> None:
        self._shapes = [
            _Shape(
                type=s.get("type", "circle"),
                x=int(s.get("x", 0)),
                y=int(s.get("y", 0)),
                r=int(s.get("r", 20)),
                w=int(s.get("w", 0)),
                h=int(s.get("h", 0)),
                color=s.get("color", "#f472b6"),
                label=s.get("label", ""),
            )
            for s in shapes
        ]
        if self._img is not None:
            self._label.set_image(self._img, *self._img_size, self._shapes)


class _PaintLabel(QLabel):
    click_signal: pyqtSignal

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setMouseTracking(False)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img: QImage | None = None
        self._native_w = 0
        self._native_h = 0
        self._shapes: list[_Shape] = []

    def set_image(self, img: QImage, native_w: int, native_h: int, shapes: list[_Shape]) -> None:
        self._img = img
        self._native_w = native_w
        self._native_h = native_h
        self._shapes = shapes
        self.update()

    def paintEvent(self, ev) -> None:  # noqa: N802
        if self._img is None:
            return
        p = QPainter(self)
        # Fit image into widget preserving aspect ratio
        widget_w = self.width()
        widget_h = self.height()
        scaled = self._img.scaled(
            widget_w,
            widget_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        off_x = (widget_w - scaled.width()) // 2
        off_y = (widget_h - scaled.height()) // 2
        p.drawImage(off_x, off_y, scaled)
        # Overlays
        if self._native_w > 0 and self._native_h > 0:
            sx = scaled.width() / self._native_w
            sy = scaled.height() / self._native_h
            for s in self._shapes:
                pen = QPen(QColor(s.color))
                pen.setWidth(3)
                p.setPen(pen)
                cx = off_x + int(s.x * sx)
                cy = off_y + int(s.y * sy)
                if s.type == "circle":
                    r = max(int(s.r * sx), 12)
                    p.drawEllipse(QPoint(cx, cy), r, r)
                elif s.type == "rect":
                    p.drawRect(QRect(cx, cy, int(s.w * sx), int(s.h * sy)))
                if s.label:
                    p.drawText(cx + 12, cy - 8, s.label)

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        if self._img is None or self._native_w == 0:
            return
        widget_w = self.width()
        widget_h = self.height()
        scaled_w = min(widget_w, int(widget_h * self._native_w / self._native_h))
        scaled_h = min(widget_h, int(widget_w * self._native_h / self._native_w))
        off_x = (widget_w - scaled_w) // 2
        off_y = (widget_h - scaled_h) // 2
        rel_x = ev.position().x() - off_x
        rel_y = ev.position().y() - off_y
        if rel_x < 0 or rel_y < 0 or rel_x > scaled_w or rel_y > scaled_h:
            return
        nx = int(rel_x * self._native_w / scaled_w)
        ny = int(rel_y * self._native_h / scaled_h)
        btn = {Qt.MouseButton.LeftButton: "left", Qt.MouseButton.RightButton: "right"}.get(
            ev.button(), "left"
        )
        self.click_signal.emit(nx, ny, btn)


class _SockClient:
    """Blocking Unix-socket client run in a background thread. Frames enter
    the frame queue; clicks are sent to the socket by the Qt thread via
    `send_click`.
    """

    def __init__(self, sock_path: str) -> None:
        self.sock_path = sock_path
        self.sock: socket.socket | None = None
        self.rx_queue: Queue[dict[str, Any]] = Queue()
        self.tx_lock = threading.Lock()
        self.stopped = threading.Event()

    def start(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self.sock_path)
        self._send({"kind": "hello", "pid": os.getpid()})
        t = threading.Thread(target=self._recv_loop, daemon=True)
        t.start()

    def _send(self, msg: dict[str, Any]) -> None:
        import json

        body = json.dumps(msg, ensure_ascii=False).encode("utf-8")
        with self.tx_lock:
            if self.sock is None:
                return
            try:
                self.sock.sendall(struct.pack(">I", len(body)) + body)
            except OSError:
                self.stopped.set()

    def send_click(self, x: int, y: int, button: str) -> None:
        self._send({"kind": "click", "x": x, "y": y, "button": button})

    def _recv_exact(self, n: int) -> bytes:
        assert self.sock is not None
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("socket closed")
            buf += chunk
        return buf

    def _recv_loop(self) -> None:
        import json

        try:
            while not self.stopped.is_set():
                header = self._recv_exact(4)
                (length,) = struct.unpack(">I", header)
                body = self._recv_exact(length)
                msg = json.loads(body.decode("utf-8"))
                self.rx_queue.put(msg)
        except (ConnectionError, OSError):
            pass
        finally:
            self.stopped.set()
            self.rx_queue.put({"kind": "closed"})


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("socket_path")
    ap.add_argument("--title", default="sense-use viewer")
    args = ap.parse_args(argv)

    app = QApplication(sys.argv)
    win = ViewerWindow(args.title)
    win.show()

    client = _SockClient(args.socket_path)
    try:
        client.start()
    except (FileNotFoundError, ConnectionRefusedError) as e:
        print(f"cannot connect to {args.socket_path}: {e}", file=sys.stderr)
        return 1

    win.click_signal.connect(lambda x, y, b: client.send_click(x, y, b))

    def _drain() -> None:
        while True:
            try:
                msg = client.rx_queue.get_nowait()
            except Empty:
                return
            kind = msg.get("kind")
            if kind == "frame":
                win.set_frame(msg["png_b64"], msg["w"], msg["h"])
            elif kind == "overlay":
                win.set_overlay(msg.get("shapes", []))
            elif kind == "title":
                win.setWindowTitle(msg.get("text", args.title))
            elif kind in ("close", "closed"):
                app.quit()
                return

    timer = QTimer()
    timer.timeout.connect(_drain)
    timer.start(33)  # ~30 fps drain

    rc = app.exec()
    client.stopped.set()
    return rc


if __name__ == "__main__":
    sys.exit(main())
