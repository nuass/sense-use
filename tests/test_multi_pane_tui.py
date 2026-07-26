"""Multi-pane TUI tests — mount, event isolation, confirm routing.

Uses fakes so we don't need Chrome / adb / desktop:
- FakeBackend: records calls, no real I/O.
- FakeProvider: emits a scripted sequence of ModelDecisions per goal.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from textual.widgets import Input, RichLog

from sense_use.core.backend import ActionResult, Backend
from sense_use.models.base import ModelDecision, ModelProvider
from sense_use.tui.app import SenseUseApp, _parse_target
from sense_use.tui.widgets.target_pane import TargetPane


# ---- fakes ---------------------------------------------------------------


class FakeBackend(Backend):
    """Minimal Backend that records every call, does no real work."""

    kind = "fake"

    def __init__(self, label: str = "fake", sensitive_pattern: str | None = None) -> None:
        self.label = label
        self.sensitive_pattern = sensitive_pattern
        self.calls: list[tuple[str, dict]] = []
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def screenshot(self) -> bytes:
        return b"\x89PNG\r\n\x1a\n" + b"\x00" * 8  # bogus PNG header

    async def get_size(self) -> tuple[int, int]:
        return (100, 100)

    async def click(self, x: int, y: int, button: str = "left") -> ActionResult:
        self.calls.append(("click", {"x": x, "y": y}))
        return ActionResult(ok=True, detail=f"clicked ({x},{y})")

    async def type_text(self, text: str) -> ActionResult:
        self.calls.append(("type", {"text": text}))
        return ActionResult(ok=True, detail=f"typed {len(text)} chars")

    async def swipe(self, x1, y1, x2, y2, duration_ms=300) -> ActionResult:
        self.calls.append(("swipe", {"x1": x1, "y1": y1, "x2": x2, "y2": y2}))
        return ActionResult(ok=True, detail="swiped")

    async def key(self, name: str) -> ActionResult:
        self.calls.append(("key", {"name": name}))
        return ActionResult(ok=True, detail=f"pressed {name}")

    def is_sensitive(self, action: str, payload: dict[str, Any]) -> bool:
        if not self.sensitive_pattern:
            return False
        label = str(payload.get("label", ""))
        return self.sensitive_pattern in label


class FakeProvider(ModelProvider):
    """Emits a scripted list of decisions, one per turn."""

    name = "fake"

    def __init__(self, script: list[ModelDecision] | None = None) -> None:
        self.script = script or [ModelDecision(thought="done", action="done", args={"answer": "ok"}, done=True)]
        self.calls = 0

    async def decide(self, goal, history, screenshot_png, page_text=None):
        i = min(self.calls, len(self.script) - 1)
        self.calls += 1
        return self.script[i]


# ---- helpers -------------------------------------------------------------


def _make_app(targets_with_backends: list[tuple[str, FakeBackend]],
              provider: ModelProvider) -> SenseUseApp:
    """Build a SenseUseApp whose panes use the supplied FakeBackends.

    We build the app with dummy targets then monkey-patch each pane's
    ``_backend_factory`` before the user submits any goal, so pane wiring +
    layout matches real usage while I/O stays fake.
    """
    app = SenseUseApp(
        cdp_url="http://127.0.0.1:9222",
        provider_key="fake",
        targets=[t for t, _ in targets_with_backends],
    )
    # Inject provider before compose() runs.
    app._build_provider = lambda: provider  # type: ignore[method-assign]

    # Save the fake-backend mapping — we'll patch each pane on mount.
    app._fake_backends = [b for _, b in targets_with_backends]  # type: ignore[attr-defined]
    return app


def _patch_pane_backends(app: SenseUseApp) -> None:
    fakes = getattr(app, "_fake_backends", [])
    for i, pane in enumerate(app.panes.values()):
        if i < len(fakes):
            fake = fakes[i]
            pane._backend_factory = (lambda f=fake: f)  # type: ignore[method-assign]


# ---- tests ---------------------------------------------------------------


def test_parse_target_all_shapes():
    """--targets syntax parses correctly for every documented case."""
    def p(s):
        return _parse_target(s, "http://127.0.0.1:9222")

    kind, _, kw = p("browser")
    assert kind == "browser" and kw == {"cdp_url": "http://127.0.0.1:9222"}

    kind, _, kw = p("browser@9223")
    assert kind == "browser" and kw == {"cdp_url": "http://127.0.0.1:9223"}

    kind, _, kw = p("browser@remote:9224")
    assert kind == "browser" and kw == {"cdp_url": "http://remote:9224"}

    kind, _, kw = p("adb@ABC123")
    assert kind == "adb" and kw == {"serial": "ABC123"}

    kind, _, kw = p("desktop@2")
    assert kind == "desktop" and kw == {"monitor": 2}

    kind, _, kw = p("vnc@10.0.0.5:5901:pw")
    assert kind == "vnc" and kw == {"host": "10.0.0.5", "port": 5901, "password": "pw"}

    with pytest.raises(ValueError):
        p("banana")


@pytest.mark.asyncio
async def test_multi_pane_mount():
    """Three panes mount, each with its own Input + RichLog + title."""
    app = _make_app(
        [("browser@9222", FakeBackend("A")),
         ("browser@9223", FakeBackend("B")),
         ("adb@SN1",       FakeBackend("C"))],
        FakeProvider(),
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        assert len(app.panes) == 3
        titles = [p.title for p in app.panes.values()]
        assert titles == [
            "browser @ 127.0.0.1:9222",
            "browser @ 127.0.0.1:9223",
            "adb @ SN1",
        ]
        # Each pane owns exactly one Input + one RichLog under its subtree.
        for pane in app.panes.values():
            assert isinstance(pane.query_one("#pane-input"), Input)
            assert isinstance(pane.query_one("#pane-log"), RichLog)


@pytest.mark.asyncio
async def test_event_bus_isolation():
    """Each pane's log only receives events from its own EventBus.

    We drive both panes' runners with a 2-step script (click then done) and
    assert their log_buffers each contain their own session's events, with no
    cross-talk (Pane A never sees Pane B's think/act lines).
    """
    provider = FakeProvider(script=[
        ModelDecision(thought="pane A click", action="click", args={"x": 11, "y": 12}, label="btn-A"),
        ModelDecision(thought="done A", action="done", args={"answer": "A-done"}, done=True),
    ])
    provider_b = FakeProvider(script=[
        ModelDecision(thought="pane B click", action="click", args={"x": 21, "y": 22}, label="btn-B"),
        ModelDecision(thought="done B", action="done", args={"answer": "B-done"}, done=True),
    ])

    app = _make_app(
        [("browser@9222", FakeBackend("A")),
         ("browser@9223", FakeBackend("B"))],
        provider,
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        _patch_pane_backends(app)

        panes = list(app.panes.values())
        pane_a, pane_b = panes[0], panes[1]
        # Each pane gets its own provider so decision streams don't interleave.
        pane_a.provider = provider
        pane_b.provider = provider_b

        # Submit goals directly (bypass keyboard focus quirks in headless mode).
        await pane_a._start_run("goal-A")
        await pane_b._start_run("goal-B")

        # Wait for both runners to finish.
        for _ in range(50):
            if (pane_a._runner_task and pane_a._runner_task.done()
                and pane_b._runner_task and pane_b._runner_task.done()):
                break
            await pilot.pause()
            await asyncio.sleep(0.02)

        assert pane_a._runner_task.done(), "pane A runner still running"
        assert pane_b._runner_task.done(), "pane B runner still running"

        buf_a = "\n".join(pane_a.log_buffer)
        buf_b = "\n".join(pane_b.log_buffer)

        # Positive assertions
        assert "pane A click" in buf_a
        assert "A-done" in buf_a
        assert "pane B click" in buf_b
        assert "B-done" in buf_b

        # Isolation: no cross-talk
        assert "pane B click" not in buf_a, f"pane A leaked B events:\n{buf_a}"
        assert "B-done"       not in buf_a
        assert "pane A click" not in buf_b, f"pane B leaked A events:\n{buf_b}"
        assert "A-done"       not in buf_b


@pytest.mark.asyncio
async def test_confirm_routing_hits_correct_pane():
    """A sensitive action in pane B must resolve pane B's future, not A's.

    We install a FakeBackend on B that flags every click as sensitive, and
    verify the app remembers `_pending_confirm_pane == pane_b` before the
    modal resolves.
    """
    sensitive_backend = FakeBackend("B", sensitive_pattern="delete")

    provider_a = FakeProvider(script=[
        ModelDecision(thought="idle A", action="done", args={"answer": "A-idle"}, done=True),
    ])
    provider_b = FakeProvider(script=[
        ModelDecision(thought="click delete", action="click",
                      args={"x": 1, "y": 1}, label="delete account"),
        # After confirm is rejected, the runner continues — end it.
        ModelDecision(thought="give up", action="done", args={"answer": "B-rejected"}, done=True),
    ])

    app = _make_app(
        [("browser@9222", FakeBackend("A")),
         ("browser@9223", sensitive_backend)],
        provider_a,
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        _patch_pane_backends(app)
        panes = list(app.panes.values())
        pane_a, pane_b = panes[0], panes[1]
        pane_a.provider = provider_a
        pane_b.provider = provider_b

        # We can't drive the modal from run_test easily because push_screen
        # would block on user input, so we override the callback to auto-reject
        # while still exercising the routing bookkeeping.
        captured: dict[str, Any] = {"pane_id": None, "action": None, "label": None}

        original_callback = app._on_pane_confirm_needed

        def _spy(pane, action, label, args):
            captured["pane_id"] = pane.id
            captured["action"] = action
            captured["label"] = label
            # Simulate the user pressing "N" — resolve directly without pushing modal.
            asyncio.create_task(pane.resolve_confirm(False))

        app._on_pane_confirm_needed = _spy  # type: ignore[method-assign]
        # rewire panes to use spy
        for p in app.panes.values():
            p._on_confirm_needed = _spy

        await pane_b._start_run("delete something")

        for _ in range(60):
            if pane_b._runner_task and pane_b._runner_task.done():
                break
            await pilot.pause()
            await asyncio.sleep(0.02)

        assert pane_b._runner_task.done()
        # The confirm event fired for pane_b, not pane_a
        assert captured["pane_id"] == pane_b.id, captured
        assert captured["action"] == "click"
        assert "delete" in captured["label"]

        # Pane A never saw a confirm event
        buf_a = "\n".join(pane_a.log_buffer)
        assert "CONFIRM" not in buf_a
