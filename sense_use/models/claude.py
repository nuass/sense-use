"""Claude vision provider — uses Anthropic Messages API.

Requires ``anthropic`` SDK (``pip install anthropic``) and ``ANTHROPIC_API_KEY``.
"""

from __future__ import annotations

import base64
import os

from sense_use.models.base import ModelDecision, ModelProvider
from sense_use.models.volc import SYSTEM_PROMPT, _parse_decision

try:
    from anthropic import AsyncAnthropic  # type: ignore
except Exception:  # pragma: no cover
    AsyncAnthropic = None  # type: ignore


DEFAULT_MODEL = "claude-sonnet-4-6"


class ClaudeProvider(ModelProvider):
    name = "claude"

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        max_tokens: int = 1024,
    ) -> None:
        if AsyncAnthropic is None:
            raise RuntimeError("Claude provider needs `pip install anthropic`")
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise RuntimeError("Claude provider needs ANTHROPIC_API_KEY")
        self.model = model
        self.max_tokens = max_tokens
        self._client = AsyncAnthropic(api_key=self.api_key)

    async def decide(
        self,
        goal: str,
        history: list[dict],
        screenshot_png: bytes,
        page_text: str | None = None,
    ) -> ModelDecision:
        img_b64 = base64.b64encode(screenshot_png).decode("ascii")
        history_lines = [f"- step {i+1}: {h}" for i, h in enumerate(history[-8:])]
        history_text = "\n".join(history_lines) or "(no prior steps)"
        user_text = f"Goal: {goal}\n\nRecent history:\n{history_text}"
        if page_text:
            user_text += f"\n\nCurrent visible page text (truncated):\n{page_text[:2000]}"

        resp = await self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": img_b64,
                            },
                        },
                        {"type": "text", "text": user_text},
                    ],
                }
            ],
        )
        text_parts = [
            block.text for block in resp.content if getattr(block, "type", "") == "text"
        ]
        return _parse_decision("\n".join(text_parts))
