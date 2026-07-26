"""Discovery + TargetPicker tests.

We monkey-patch the network / subprocess probes to return canned data so
tests don't depend on what's actually running on the box.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from textual.widgets import Button, SelectionList, Static

from sense_use.core import discovery
from sense_use.core.discovery import (
    DiscoveredTarget,
    discover_adb_devices,
    discover_all,
    discover_chrome_cdp,
    discover_desktop_monitors,
)
from sense_use.tui.app import SenseUseApp
from sense_use.tui.widgets.target_picker import TargetPicker


# ---- discovery: chrome CDP ------------------------------------------


@pytest.mark.asyncio
async def test_discover_chrome_cdp_none_when_offline():
    """No CDP endpoint responds → returns empty list, does not raise."""
    # Pick a port range unlikely to be live; use tight timeout.
    result = await discover_chrome_cdp(ports=(59999, 59998), timeout=0.1)
    assert result == []


@pytest.mark.asyncio
async def test_discover_chrome_cdp_finds_endpoint(monkeypatch):
    """When a port returns valid /json/version, we surface it as a target."""

    class _FakeResp:
        status_code = 200
        def json(self):
            return {"Browser": "Chrome/150.0.0.0", "webSocketDebuggerUrl": "ws://x"}

    class _FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url):
            # Only pretend 9223 is live
            if "9223" in url:
                return _FakeResp()
            raise ConnectionError("port closed")

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)

    result = await discover_chrome_cdp(ports=(9222, 9223, 9224), timeout=0.5)
    assert len(result) == 1
    assert result[0].kind == "browser"
    assert result[0].spec == "browser@9223"
    assert "Chrome/150" in result[0].detail


# ---- discovery: adb -------------------------------------------------


@pytest.mark.asyncio
async def test_discover_adb_no_binary(monkeypatch):
    """No adb on PATH → empty list."""
    monkeypatch.setattr(discovery.shutil, "which", lambda _: None)
    assert await discover_adb_devices() == []


@pytest.mark.asyncio
async def test_discover_adb_parses_output(monkeypatch):
    """Emulate two devices, one offline — only online device is returned."""
    fake_stdout = (
        b"List of devices attached\n"
        b"ABC123XYZ           device usb:1-1 product:foo model:Pixel_6 device:foo transport_id:1\n"
        b"OFFLINE9            offline\n"
    )

    class _FakeProc:
        async def communicate(self):
            return (fake_stdout, b"")

    async def _fake_exec(*args, **kwargs):
        return _FakeProc()

    monkeypatch.setattr(discovery.shutil, "which", lambda _: "/fake/adb")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

    result = await discover_adb_devices()
    assert len(result) == 1
    assert result[0].spec == "adb@ABC123XYZ"
    assert "Pixel_6" in result[0].detail


# ---- discovery: desktop --------------------------------------------


def test_discover_desktop_always_yields_at_least_one():
    """Desktop probe never returns empty — mss missing falls back gracefully."""
    result = discover_desktop_monitors()
    assert len(result) >= 1
    assert result[0].kind == "desktop"


# ---- discovery: aggregate ------------------------------------------


@pytest.mark.asyncio
async def test_discover_all_merges_probes(monkeypatch):
    """discover_all runs the 3 probes in parallel and returns them ordered."""
    async def _fake_chrome(*a, **kw):
        return [DiscoveredTarget("browser", "Chrome @ :9222", "browser@9222", "Chrome/150")]

    async def _fake_adb(*a, **kw):
        return [DiscoveredTarget("adb", "Android SN1", "adb@SN1", "Pixel · device")]

    def _fake_desktop(*a, **kw):
        return [DiscoveredTarget("desktop", "Desktop · primary", "desktop", "1512×982")]

    monkeypatch.setattr(discovery, "discover_chrome_cdp", _fake_chrome)
    monkeypatch.setattr(discovery, "discover_adb_devices", _fake_adb)
    monkeypatch.setattr(discovery, "discover_desktop_monitors", _fake_desktop)

    result = await discover_all()
    kinds = [t.kind for t in result]
    assert kinds == ["browser", "adb", "desktop"], f"unexpected order: {kinds}"


# ---- picker widget -------------------------------------------------


@pytest.mark.asyncio
async def test_picker_populates_from_discovery(monkeypatch):
    """Mounting TargetPicker triggers a scan that fills the SelectionList."""
    async def _fake_all(*a, **kw):
        return [
            DiscoveredTarget("browser", "Chrome @ :9222", "browser@9222", "Chrome/150"),
            DiscoveredTarget("adb", "Android SN1", "adb@SN1", "Pixel · device"),
        ]

    monkeypatch.setattr("sense_use.tui.widgets.target_picker.discover_all", _fake_all)

    from textual.app import App as _App
    class _Harness(_App):
        def compose(self):
            yield TargetPicker(id="p")

    app = _Harness()
    async with app.run_test() as pilot:
        # let the async scan complete
        for _ in range(30):
            picker = app.query_one("#p", TargetPicker)
            if len(picker.discovered) >= 2:
                break
            await pilot.pause()
            await asyncio.sleep(0.02)

        picker = app.query_one("#p", TargetPicker)
        assert len(picker.discovered) == 2, f"got {picker.discovered}"
        listbox = picker.query_one("#targets_list", SelectionList)
        # SelectionList exposes count via option_count
        assert listbox.option_count == 2


@pytest.mark.asyncio
async def test_picker_attach_posts_message(monkeypatch):
    """Clicking Attach sends TargetsChosen with the selected specs."""
    async def _fake_all(*a, **kw):
        return [
            DiscoveredTarget("browser", "Chrome", "browser@9222", ""),
            DiscoveredTarget("adb", "Phone", "adb@SN", ""),
        ]

    monkeypatch.setattr("sense_use.tui.widgets.target_picker.discover_all", _fake_all)

    from textual.app import App as _App

    captured: list[list[str]] = []

    class _Harness(_App):
        def compose(self):
            yield TargetPicker(id="p")

        def on_target_picker_targets_chosen(self, msg):
            captured.append(list(msg.specs))

    app = _Harness()
    async with app.run_test() as pilot:
        # wait for scan
        for _ in range(30):
            picker = app.query_one("#p", TargetPicker)
            if len(picker.discovered) >= 2:
                break
            await pilot.pause()
            await asyncio.sleep(0.02)

        # Both options default to selected. Click the Attach button.
        picker = app.query_one("#p", TargetPicker)
        picker.query_one("#attach", Button).press()
        await pilot.pause()

    assert captured, "TargetsChosen was never posted"
    assert set(captured[0]) == {"browser@9222", "adb@SN"}


# ---- app integration -----------------------------------------------


@pytest.mark.asyncio
async def test_app_picker_mode_starts_empty():
    """SenseUseApp with no targets shows the picker + empty-panes hint."""
    class _NoOpProvider:
        async def decide(self, *a, **kw):
            raise NotImplementedError

    app = SenseUseApp(provider_key="fake")
    app._build_provider = lambda: _NoOpProvider()  # type: ignore[method-assign]
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app._auto_attach is False
        assert app.panes == {}
        assert app.query_one("#picker", TargetPicker) is not None
        assert app.query_one("#empty-hint", Static) is not None


@pytest.mark.asyncio
async def test_app_targets_flag_bypasses_picker(monkeypatch):
    """With --targets given, the app should attach immediately, no picker."""
    from sense_use.tui.widgets.target_pane import TargetPane

    class _NoOpProvider:
        async def decide(self, *a, **kw):
            raise NotImplementedError

    app = SenseUseApp(provider_key="fake", targets=["desktop"])
    app._build_provider = lambda: _NoOpProvider()  # type: ignore[method-assign]
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app._auto_attach is True
        assert len(app.panes) == 1
        # picker should not exist in this mode
        assert not app.query("#picker")
        # first pane rendered
        pane = next(iter(app.panes.values()))
        assert isinstance(pane, TargetPane)


@pytest.mark.asyncio
async def test_picker_choice_spawns_panes(monkeypatch):
    """Simulating a TargetsChosen message mounts new TargetPanes."""
    from sense_use.tui.widgets.target_pane import TargetPane

    async def _fake_all(*a, **kw):
        return [DiscoveredTarget("desktop", "Desktop", "desktop", "1×1")]

    monkeypatch.setattr("sense_use.tui.widgets.target_picker.discover_all", _fake_all)

    class _NoOpProvider:
        async def decide(self, *a, **kw):
            raise NotImplementedError

    app = SenseUseApp(provider_key="fake")
    app._build_provider = lambda: _NoOpProvider()  # type: ignore[method-assign]
    async with app.run_test() as pilot:
        await pilot.pause()
        picker = app.query_one("#picker", TargetPicker)
        # wait for scan
        for _ in range(30):
            if picker.discovered:
                break
            await pilot.pause()
            await asyncio.sleep(0.02)
        # Directly invoke the message handler
        await app.on_target_picker_targets_chosen(
            TargetPicker.TargetsChosen(specs=["desktop"])
        )
        await pilot.pause()

    assert len(app.panes) == 1
    pane = next(iter(app.panes.values()))
    assert isinstance(pane, TargetPane)
    assert "desktop" in pane.title.lower() or "Desktop" in pane.title
