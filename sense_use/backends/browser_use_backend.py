"""Optional browser-use adapter.

When the user has `pip install browser-use` we can delegate DOM-aware actions
(click_by_index, extract_content, etc.) to it. This module ONLY exposes a
constructor that fails cleanly when the dep is missing; the registry falls
back to the built-in CDP `BrowserBackend` in that case.
"""

from __future__ import annotations

from typing import Any

from sense_use.core.backend import ActionResult, Backend


class BrowserUseBackend(Backend):
    kind = "browser-use"

    def __init__(self, cdp_url: str = "http://127.0.0.1:9222") -> None:
        try:
            from browser_use import Browser  # type: ignore  # noqa: F401
        except Exception as e:  # pragma: no cover
            raise RuntimeError(
                "browser-use not installed; run `pip install browser-use` "
                "or use the built-in 'browser' backend instead"
            ) from e
        self.cdp_url = cdp_url
        self._browser: Any = None

    async def start(self) -> None:  # pragma: no cover
        from browser_use import Browser  # type: ignore

        self._browser = Browser(cdp_url=self.cdp_url)
        await self._browser.start()

    async def stop(self) -> None:  # pragma: no cover
        if self._browser is not None:
            await self._browser.stop()

    async def screenshot(self) -> bytes:  # pragma: no cover
        return await self._browser.screenshot()

    async def get_size(self) -> tuple[int, int]:  # pragma: no cover
        page = await self._browser.current_page()
        w = await page.evaluate("() => window.innerWidth")
        h = await page.evaluate("() => window.innerHeight")
        return int(w), int(h)

    async def click(self, x: int, y: int, button: str = "left") -> ActionResult:  # pragma: no cover
        page = await self._browser.current_page()
        await page.mouse.click(x, y, button=button)
        return ActionResult(ok=True, detail=f"click {x},{y}")

    async def type_text(self, text: str) -> ActionResult:  # pragma: no cover
        page = await self._browser.current_page()
        await page.keyboard.type(text, delay=25)
        return ActionResult(ok=True)

    async def swipe(
        self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300
    ) -> ActionResult:  # pragma: no cover
        page = await self._browser.current_page()
        await page.mouse.move(x1, y1)
        await page.mouse.down()
        await page.mouse.move(x2, y2)
        await page.mouse.up()
        return ActionResult(ok=True)

    async def key(self, name: str) -> ActionResult:  # pragma: no cover
        page = await self._browser.current_page()
        await page.keyboard.press(name)
        return ActionResult(ok=True)
