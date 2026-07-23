"""Async event bus — agent -> (TUI, viewer, session_store) fan-out."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Literal

EventKind = Literal[
    "user_msg", "observe", "think", "act", "act_result",
    "confirm_needed", "confirm_result", "error", "done",
]


@dataclass
class Event:
    kind: EventKind
    session_id: str
    ts: float = field(default_factory=time.time)
    payload: dict[str, Any] = field(default_factory=dict)


class EventBus:
    """Multi-subscriber async pub-sub. Each subscriber gets its own queue."""

    def __init__(self) -> None:
        self._subs: list[asyncio.Queue[Event]] = []

    def subscribe(self) -> asyncio.Queue[Event]:
        q: asyncio.Queue[Event] = asyncio.Queue()
        self._subs.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[Event]) -> None:
        if q in self._subs:
            self._subs.remove(q)

    async def publish(self, event: Event) -> None:
        for q in list(self._subs):
            await q.put(event)
