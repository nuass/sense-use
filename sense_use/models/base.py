"""Model provider abstraction — one class per (vision + reasoning) API."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ModelDecision:
    """One step the agent decides to take."""

    thought: str
    action: str            # click / type / swipe / key / goto / read / done
    args: dict             # {x, y} or {text} or {url} or {}
    done: bool = False
    label: str = ""        # human-readable target text for is_sensitive() hook


class ModelProvider(ABC):
    name: str = "abstract"

    @abstractmethod
    async def decide(
        self,
        goal: str,
        history: list[dict],
        screenshot_png: bytes,
        page_text: str | None = None,
    ) -> ModelDecision:
        """Given goal + last-observation, return the next action."""
