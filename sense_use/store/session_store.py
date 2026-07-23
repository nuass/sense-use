"""Session storage — one jsonl per session under ~/.sense-use/sessions/YYYY-MM-DD/."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from sense_use.core.event_bus import Event

ROOT = Path.home() / ".sense-use"


def session_path(session_id: str, day: date | None = None) -> Path:
    day = day or date.today()
    d = ROOT / "sessions" / day.isoformat()
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{session_id}.jsonl"


class SessionStore:
    def __init__(self, session_id: str) -> None:
        self.path = session_path(session_id)
        # touch file
        self.path.touch(exist_ok=True)

    def append(self, event: Event) -> None:
        record: dict[str, Any] = {
            "kind": event.kind,
            "ts": event.ts,
            "payload": _sanitize(event.payload),
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _sanitize(payload: dict) -> dict:
    """Strip bytes (screenshots) so jsonl stays readable; keep sizes only."""
    out = {}
    for k, v in payload.items():
        if isinstance(v, (bytes, bytearray)):
            out[k] = {"_bytes": len(v)}
        else:
            out[k] = v
    return out
