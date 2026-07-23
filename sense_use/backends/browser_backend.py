"""Browser Backend — Playwright over Chrome DevTools Protocol.

Connects to an existing Chrome launched with:
    google-chrome --remote-debugging-port=9222 --remote-allow-origins='*'

The user's existing Chrome sessions (login cookies, extensions) are reused.
"""

from __future__ import annotations

import re
from typing import Any

from sense_use.core.backend import ActionResult, Backend

SENSITIVE_PATTERNS = re.compile(
    r"(pay|checkout|purchase|delete|remove|logout|sign\s?out|confirm\s?order|"
    r"支付|付款|删除|退出登录|确认下单|确认支付)",
    re.IGNORECASE,
)


class BrowserBackend(Backend):
    kind = "browser"

    def __init__(self, cdp_url: str = "http://127.0.0.1:9222") -> None:
        self.cdp_url = cdp_url
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None

    async def start(self) -> None:
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.connect_over_cdp(self.cdp_url)
        if not self._browser.contexts:
            raise RuntimeError(
                f"CDP at {self.cdp_url} has no browser contexts. "
                "Open at least one tab in that Chrome first."
            )
        self._context = self._browser.contexts[0]
        pages = self._context.pages
        self._page = pages[0] if pages else await self._context.new_page()
        await self._page.bring_to_front()

    async def stop(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    async def screenshot(self) -> bytes:
        assert self._page is not None
        return await self._page.screenshot(type="png", full_page=False)

    async def get_size(self) -> tuple[int, int]:
        assert self._page is not None
        vp = self._page.viewport_size
        if vp:
            return vp["width"], vp["height"]
        size = await self._page.evaluate(
            "() => ({w: window.innerWidth, h: window.innerHeight})"
        )
        return int(size["w"]), int(size["h"])

    async def click(self, x: int, y: int, button: str = "left") -> ActionResult:
        assert self._page is not None
        await self._page.mouse.click(x, y, button=button)
        return ActionResult(ok=True, detail=f"clicked ({x},{y})")

    async def type_text(self, text: str) -> ActionResult:
        assert self._page is not None
        await self._page.keyboard.type(text, delay=20)
        return ActionResult(ok=True, detail=f"typed {len(text)} chars")

    async def swipe(
        self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300
    ) -> ActionResult:
        # In a browser context, "swipe" = mouse-drag or wheel scroll.
        assert self._page is not None
        steps = max(5, duration_ms // 20)
        await self._page.mouse.move(x1, y1)
        await self._page.mouse.down()
        await self._page.mouse.move(x2, y2, steps=steps)
        await self._page.mouse.up()
        return ActionResult(ok=True, detail=f"swiped ({x1},{y1})->({x2},{y2})")

    async def key(self, name: str) -> ActionResult:
        assert self._page is not None
        # Normalize common names.
        mapping = {"back": "BrowserBack", "home": "Home", "enter": "Enter", "esc": "Escape"}
        key = mapping.get(name.lower(), name)
        await self._page.keyboard.press(key)
        return ActionResult(ok=True, detail=f"pressed {key}")

    async def goto(self, url: str) -> ActionResult:
        assert self._page is not None
        await self._page.goto(url, wait_until="domcontentloaded")
        return ActionResult(ok=True, detail=f"navigated to {url}")

    async def read_text(self) -> str:
        """Extract visible page text for the model to reason about."""
        assert self._page is not None
        return await self._page.evaluate("() => document.body.innerText")

    def is_sensitive(self, action: str, payload: dict[str, Any]) -> bool:
        # Any click whose target label matches SENSITIVE_PATTERNS is sensitive.
        label = str(payload.get("label", "") or payload.get("target_text", ""))
        return bool(SENSITIVE_PATTERNS.search(label))
