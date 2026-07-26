"""Volc (火山方舟) doubao-seed-vision provider.

API: https://ark.cn-beijing.volces.com/api/v3/chat/completions
OpenAI-compatible schema; image is base64 data URL.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any

import httpx

from sense_use.models.base import ModelDecision, ModelProvider

DEFAULT_ENDPOINT = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
DEFAULT_MODEL = "doubao-seed-1-6-flash-250615"

SYSTEM_PROMPT = """\
You are sense-use, an agent controlling one target (browser / mobile / desktop).
On each turn you receive: the user goal, the recent action history, and a fresh screenshot (plus optional page text).

Reply with ONE JSON object, no prose outside JSON:
{
  "thought": "short reasoning",
  "action": "click|type|swipe|key|goto|read|done",
  "args":   { ... },
  "label":  "label of the target element you are about to touch",
  "done":   false
}

Action args:
- click: {"x": int, "y": int}
- type:  {"text": string}
- swipe: {"x1": int, "y1": int, "x2": int, "y2": int}
- key:   {"name": "enter|esc|back|home|tab|..."}
- goto:  {"url": string}
- read:  {}
- done:  {"answer": string}   set done=true when the goal is achieved

Coordinates are in the screenshot's pixel space. Take small, verifiable steps.

CRITICAL JSON rules — violate any and the run fails:
1. Emit exactly ONE JSON object. No markdown fences, no prose before or after.
2. Inside string values, NEVER include a raw double-quote (") — if you must quote
   something the user said, use 「」 or single quotes '...' or backticks `...`.
3. `args.text` MUST contain the FULL text the user wanted, verbatim. Do not
   truncate at punctuation, quotes, or commas.
4. After a `type` action for a search box, the next step should usually be
   `key` with {"name": "enter"} unless you have another reason.
5. Every action's args MUST include ALL required keys — click needs BOTH x and y
   integers (never x alone), swipe needs x1/y1/x2/y2, key needs name, goto needs
   url. Missing keys fail the step silently.
"""


class VolcProvider(ModelProvider):
    name = "volc"

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        endpoint: str = DEFAULT_ENDPOINT,
        timeout: float = 60.0,
    ) -> None:
        self.api_key = api_key or os.environ.get("ARK_API_KEY") or os.environ.get("VOLC_API_KEY")
        if not self.api_key:
            raise RuntimeError(
                "Volc provider needs ARK_API_KEY (or VOLC_API_KEY) env var, "
                "or pass api_key= explicitly."
            )
        self.model = model
        self.endpoint = endpoint
        self.timeout = timeout

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
            snippet = page_text[:2000]
            user_text += f"\n\nCurrent visible page text (truncated):\n{snippet}"

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ]

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(self.endpoint, headers=headers, json=payload)
            r.raise_for_status()
            body = r.json()

        content = body["choices"][0]["message"]["content"]
        return _parse_decision(content)


def _parse_decision(text: str) -> ModelDecision:
    """Extract the JSON object from the model response, tolerating code fences."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[1] if "\n" in stripped else stripped
        if stripped.endswith("```"):
            stripped = stripped[: -3]
        stripped = stripped.strip()
        if stripped.startswith("json"):
            stripped = stripped[4:].strip()

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end < 0:
        raise ValueError(f"model reply is not JSON:\n{text}")
    raw = stripped[start : end + 1]

    try:
        obj: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError:
        # Model often embeds Chinese full-width quotes (" " ' ') inside string
        # values, which are legal Unicode but confuse json.loads when they mix
        # with straight quotes. Normalize to safe replacements and retry.
        repaired = (
            raw.replace("“", "「")
            .replace("”", "」")
            .replace("‘", "『")
            .replace("’", "』")
        )
        try:
            obj = json.loads(repaired)
        except json.JSONDecodeError:
            # Last resort: try json_repair if installed (opt-in).
            try:
                import json_repair  # type: ignore

                obj = json_repair.loads(raw)  # type: ignore[assignment]
            except Exception as exc:  # noqa: BLE001
                raise ValueError(
                    f"model reply is not valid JSON: {exc}\n---\n{text}"
                ) from exc

    return ModelDecision(
        thought=str(obj.get("thought", "")),
        action=str(obj.get("action", "done")),
        args=obj.get("args", {}) or {},
        done=bool(obj.get("done", False)),
        label=str(obj.get("label", "")),
    )
