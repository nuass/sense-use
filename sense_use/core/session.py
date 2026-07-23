"""Session: one user goal + one Backend + one event stream."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sense_use.core.backend import Backend


@dataclass
class Session:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    backend: "Backend | None" = None
    goal: str = ""
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    max_steps: int = 30
    step: int = 0
    done: bool = False
