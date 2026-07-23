"""Qwen-VL local provider — hits an Ollama-compatible server.

Default target: ``http://localhost:11434/api/chat`` running ``qwen2.5-vl:7b``.
Ollama's /api/chat supports vision by passing ``images: [<base64>]`` on the
message. No SDK required — pure httpx.
"""

from __future__ import annotations

import base64
import json
import os

import httpx

from sense_use.models.base import ModelDecision, ModelProvider
from sense_use.models.volc import SYSTEM_PROMPT, _parse_decision


DEFAULT_ENDPOINT = "http://localhost:11434/api/chat"
DEFAULT_MODEL = "qwen2.5-vl:7b"


class QwenLocalProvider(ModelProvider):
    name = "qwen_local"

    def __init__(
        self,
        endpoint: str | None = None,
        model: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.endpoint = endpoint or os.environ.get("OLLAMA_ENDPOINT", DEFAULT_ENDPOINT)
        self.model = model or os.environ.get("QWEN_MODEL", DEFAULT_MODEL)
        self.timeout = timeout

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

        payload = {
            "model": self.model,
            "stream": False,
            "options": {"temperature": 0.2},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_text, "images": [img_b64]},
            ],
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(self.endpoint, json=payload)
            r.raise_for_status()
            body = r.json()

        content = body.get("message", {}).get("content") or ""
        if not content:
            raise RuntimeError(f"empty qwen reply: {json.dumps(body)[:400]}")
        return _parse_decision(content)
