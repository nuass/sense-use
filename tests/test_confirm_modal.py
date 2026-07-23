"""ConfirmModal headless test — dismisses via Y and N keys."""

import pytest
from textual.app import App

from sense_use.tui.screens.confirm_modal import ConfirmModal


class _Harness(App):
    def __init__(self, action: str, label: str, args: dict) -> None:
        super().__init__()
        self.result: bool | None = None
        self._action = action
        self._label = label
        self._args = args

    async def on_mount(self) -> None:
        def _got(v: bool | None) -> None:
            self.result = bool(v)
            self.exit()

        self.push_screen(ConfirmModal(self._action, self._label, self._args), _got)


@pytest.mark.asyncio
async def test_confirm_modal_yes():
    app = _Harness("click", "pay button", {"x": 10, "y": 20})
    async with app.run_test() as pilot:
        await pilot.press("y")
        await pilot.pause()
    assert app.result is True


@pytest.mark.asyncio
async def test_confirm_modal_no():
    app = _Harness("click", "delete", {})
    async with app.run_test() as pilot:
        await pilot.press("n")
        await pilot.pause()
    assert app.result is False


@pytest.mark.asyncio
async def test_confirm_modal_replan():
    app = _Harness("click", "logout", {})
    async with app.run_test() as pilot:
        await pilot.press("r")
        await pilot.pause()
    # Replan currently maps to reject (False) at the runner layer.
    assert app.result is False
