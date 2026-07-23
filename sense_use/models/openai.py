"""OpenAI vision provider — uses OpenAI Chat Completions API.

Requires ``openai`` SDK (``pip install openai``) and ``OPENAI_API_KEY``.
"""

from __future__ import annotations

import base64
import os

from sense_use.models.base import ModelDecision, ModelProvider
from sense_use.models.volc import SYSTEM_PROMPT, _parse_decision

try:
    from openai import AsyncOpenAI  # type: ignore
except Exception:  # pragma: no cover
    AsyncOpenAI = None  # type: ignore


DEFAULT_MODEL = "gpt-4o"


class OpenAIProvider(ModelProvider):
    name = "openai"

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        base_url: str | None = None,
    ) -> None:
        if AsyncOpenAI is None:
            raise RuntimeError("OpenAI provider needs `pip install openai`")
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise RuntimeError("OpenAI provider needs OPENAI_API_KEY")
        self.model = model
        kwargs: dict = {"api_key": self.api_key}
        if base_url or os.environ.get("OPENAI_BASE_URL"):
            kwargs["base_url"] = base_url or os.environ["OPENAI_BASE_URL"]
        self._client = AsyncOpenAI(**kwargs)

    async def decide(
        self,
        goal: str,
        history: list[dict],
        screenshot_png: bytes,
        page_text: str | None = None,
    ) -> ModelDecision:
        img_b64 = base64.b64encode(screenshot_png).decode("ascii")
        data_url = f"data:image/png;base64,{img_b64}"

        history_lines = [f"- step {i+1}: {h}" for i, h in enumerate(history[-8:])]
        history_text = "\n".join(history_lines) or "(no prior steps)"
        user_text = f"Goal: {goal}\n\nRecent history:\n{history_text}"
        if page_text:
            user_text += f"\n\nCurrent visible page text (truncated):\n{page_text[:2000]}"

        resp = await self._client.chat.completions.create(
            model=self.model,
            temperature=0.2,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
        )
        return _parse_decision(resp.choices[0].message.content or "")
