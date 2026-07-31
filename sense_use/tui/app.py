"""Textual TUI — multi-pane layout, one lane per Backend.

Each pane owns its own Backend + TaskRunner + EventBus so browser / adb /
desktop / vnc can run in parallel without stepping on each other.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys

from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Footer, Header, Input, RichLog, Static

from sense_use.config import Config
from sense_use.core.event_bus import Event
from sense_use.guardian_gateway import PendingConfirm, create_app as create_guardian_app
from sense_use.models import provider_registry
from sense_use.store.session_store import SessionStore
from sense_use.tui.screens.confirm_modal import ConfirmModal
from sense_use.tui.screens.memory_modal import MemoryModal
from sense_use.tui.screens.project_modal import ProjectModal
from sense_use.tui.widgets.memory_tree import MemoryTree
from sense_use.tui.widgets.pane_grid import PaneGrid, columns_for
from sense_use.tui.widgets.target_pane import TargetPane
from sense_use.tui.widgets.target_picker import TargetPicker
from sense_use.tui.widgets.voice_input import VoiceCapture


def _read_clipboard() -> str | None:
    if sys.platform == "darwin":
        cmd = ["pbpaste"]
    elif sys.platform.startswith("linux"):
        cmd = ["xclip", "-selection", "clipboard", "-o"]
    elif sys.platform.startswith("win"):
        cmd = ["powershell", "-NoProfile", "-Command", "Get-Clipboard"]
    else:
        return None
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=3)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.decode("utf-8", errors="replace")


def _write_clipboard(text: str) -> bool:
    if sys.platform == "darwin":
        cmd = ["pbcopy"]
    elif sys.platform.startswith("linux"):
        cmd = ["xclip", "-selection", "clipboard"]
    elif sys.platform.startswith("win"):
        cmd = ["clip"]
    else:
        return False
    try:
        p = subprocess.run(cmd, input=text.encode("utf-8"), timeout=3)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return p.returncode == 0


def _parse_target(spec: str, default_cdp: str) -> tuple[str, str, dict]:
    """Parse one --targets entry.

    Syntax: ``kind[@endpoint]`` — everything after the first ``@`` is
    endpoint config, kind-specific:

    - ``browser`` / ``browser@9223`` / ``browser@127.0.0.1:9223`` /
      ``browser@http://host:9223``
    - ``adb`` / ``adb@TWPVAEUWQ4QWNR9H`` (device serial)
    - ``desktop`` / ``desktop@2`` (monitor index)
    - ``vnc@10.0.0.5:5901`` / ``vnc@10.0.0.5:5901:mypassword``

    Returns ``(kind, title, backend_kwargs)`` — title is user-facing, kwargs
    are fed straight into the Backend constructor.
    """
    raw = spec.strip()
    if "@" in raw:
        kind, endpoint = raw.split("@", 1)
    else:
        kind, endpoint = raw, ""
    kind = kind.strip().lower()
    endpoint = endpoint.strip()

    if kind in ("browser", "cdp", "chrome"):
        cdp = _normalize_cdp(endpoint, default_cdp)
        return "browser", f"browser @ {_short_cdp(cdp)}", {"cdp_url": cdp}

    if kind in ("adb", "mobile", "android"):
        serial = endpoint or None
        title = f"adb @ {serial}" if serial else "adb (default device)"
        return "adb", title, ({"serial": serial} if serial else {})

    if kind in ("desktop", "mac", "local"):
        monitor = int(endpoint) if endpoint.isdigit() else 1
        title = f"desktop (mon {monitor})" if endpoint else "desktop (this mac)"
        return "desktop", title, {"monitor": monitor}

    if kind in ("vnc",):
        # host[:port[:password]]
        parts = endpoint.split(":", 2) if endpoint else []
        import os
        host = parts[0] if len(parts) >= 1 and parts[0] else os.environ.get("SENSE_USE_VNC_HOST", "127.0.0.1")
        port = int(parts[1]) if len(parts) >= 2 and parts[1] else int(os.environ.get("SENSE_USE_VNC_PORT", "5900"))
        password = parts[2] if len(parts) >= 3 else os.environ.get("SENSE_USE_VNC_PASS", "")
        return "vnc", f"vnc @ {host}:{port}", {"host": host, "port": port, "password": password}

    raise ValueError(f"unknown target kind: {kind}")


def _normalize_cdp(endpoint: str, default: str) -> str:
    """Turn ``9223`` / ``127.0.0.1:9223`` / full URL into a CDP URL."""
    if not endpoint:
        return default
    if endpoint.startswith(("http://", "https://")):
        return endpoint
    if ":" in endpoint:
        return f"http://{endpoint}"
    if endpoint.isdigit():
        return f"http://127.0.0.1:{endpoint}"
    # bare hostname — default to :9222
    return f"http://{endpoint}:9222"


def _short_cdp(url: str) -> str:
    # http://127.0.0.1:9222 -> 127.0.0.1:9222
    return url.split("://", 1)[-1].rstrip("/")


def _short_title(kind: str, full_title: str) -> str:
    """Compact pane title for grid mode (1-3 char prefix + endpoint digits).

    Examples (3+ panes):
        browser @ 9222        -> b9222
        browser @ 192.168.1.4 -> b9222        (uses cdp port)
        adb @ TWPVAEUWQ4QW..  -> a·TWPV      (first 4 of serial)
        adb @ 192.168.1.79:.  -> a·41065
        desktop (mon 2)       -> desk·2
        vnc @ 10.0.0.5:5901   -> vnc·5901
    """
    import re
    if kind == "browser":
        # pull last :PORT out of "browser @ 127.0.0.1:9222"
        m = re.search(r":(\d+)\b", full_title)
        if m:
            return f"b{m.group(1)}"
        return "browser"
    if kind == "adb":
        # "adb @ 192.168.1.79:41065" -> a·41065
        # "adb @ TWPVAEUWQ4QWNR9H"  -> a·TWPV
        m = re.search(r":(\d+)\b", full_title)
        if m:
            return f"a·{m.group(1)}"
        m = re.search(r"@ (\w+)", full_title)
        if m:
            return f"a·{m.group(1)[:4]}"
        return "adb"
    if kind == "desktop":
        # "desktop (mon 2)" -> desk·2 / "desktop (this mac)" -> desk·M
        m = re.search(r"mon (\d+)", full_title)
        if m:
            return f"desk·{m.group(1)}"
        return "desk"
    if kind == "vnc":
        # "vnc @ 10.0.0.5:5901" -> vnc·5901
        m = re.search(r":(\d+)\b", full_title)
        if m:
            return f"vnc·{m.group(1)}"
        return "vnc"
    return full_title[:8]


def _build_target_factory(kind: str, kwargs: dict):
    """Return a zero-arg callable that builds the Backend for `kind`.

    Deferred construction — dependencies (playwright, pyautogui, adb) may or
    may not be installed; failures surface only when the user hits Enter in
    that pane, not at TUI boot.
    """
    if kind == "browser":
        from sense_use.backends.browser_backend import BrowserBackend
        return lambda: BrowserBackend(**kwargs)
    if kind == "adb":
        from sense_use.backends.adb_backend import AdbBackend
        return lambda: AdbBackend(**kwargs)
    if kind == "desktop":
        from sense_use.backends.desktop_backend import DesktopBackend
        return lambda: DesktopBackend(**kwargs)
    if kind == "vnc":
        from sense_use.backends.vnc_backend import VncBackend
        return lambda: VncBackend(**kwargs)
    raise ValueError(f"unknown target kind: {kind}")


class SenseUseApp(App):
    CSS = """
    Screen { layout: vertical; }
    #main { height: 1fr; }
    #sidebar { width: 26; border-right: solid $primary; }
    #panes { height: 1fr; }
    RichLog { background: $surface; }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit"),
        Binding("ctrl+s", "archive", "📁 Archive"),
        Binding("ctrl+space", "voice_toggle", "🎙 Voice"),
        Binding("ctrl+shift+v", "paste_clipboard", "📋 Paste"),
        Binding("ctrl+shift+c", "copy_log", "📄 Copy log"),
        Binding("ctrl+y", "copy_log", "📄 Copy", show=False),
        Binding("y", "confirm_yes", "✅ Yes", show=False),
        Binding("n", "confirm_no", "❌ No", show=False),
    ]

    def __init__(
        self,
        cdp_url: str = "http://127.0.0.1:9222",
        provider_key: str = "volc",
        config: Config | None = None,
        targets: list[str] | None = None,
    ) -> None:
        super().__init__()
        self.cdp_url = cdp_url
        self.provider_key = provider_key
        self.config = config or Config()
        # If user gave --targets, we skip the picker and attach right away.
        # Otherwise start with an empty panes area and let the sidebar picker
        # populate it interactively.
        self.targets = targets or []
        self._auto_attach = bool(targets)
        self.panes: dict[str, TargetPane] = {}  # pane_id -> pane
        self._provider = None
        self._voice: VoiceCapture | None = None
        self._voice_task: asyncio.Task | None = None
        self._voice_baseline: str = ""
        self._log_dump_path = "/tmp/sense-use-last.log"
        self._pending_confirm_pane: TargetPane | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="main"):
            with Vertical(id="sidebar"):
                if self._auto_attach:
                    targets_line = " · ".join(self.targets)
                    yield Static(
                        f"[b]Targets[/b]\n\n{targets_line}\n\n"
                        "[dim]Tab to switch pane · Ctrl+S archive · Ctrl+Space voice[/dim]",
                        id="targets", markup=True,
                    )
                else:
                    yield TargetPicker(id="picker")
                yield MemoryTree(id="memtree")
            with PaneGrid(id="panes", initial_columns=columns_for(len(self.targets))):
                try:
                    self._provider = self._build_provider()
                except Exception as exc:  # noqa: BLE001
                    self._provider = None
                    self._provider_error = repr(exc)
                if self._auto_attach:
                    yield from self._spawn_panes(self.targets)
                else:
                    yield Static(
                        "[dim]← pick targets in the sidebar, then press "
                        "[b]Attach selected[/b][/dim]",
                        id="empty-hint", markup=True,
                    )
        yield Footer()

    def _spawn_panes(self, specs: list[str]):
        """Generator: yield TargetPane widgets for the given specs.

        Used both at first render (with --targets) and lazily when the picker
        emits TargetsChosen — the caller mount()s the yielded widgets.

        Title shortening kicks in once the grid has more than one column
        (i.e. 4+ panes), since the long form (``browser @ 9222``) is too
        wide for the ~20-col cells of a 3x3 layout.
        """
        # Decide shortening up-front: we know the *target* total so the
        # caller can pre-pick the right column count.
        projected_total = len(self.panes) + len(specs)
        cols = columns_for(projected_total)
        use_short = cols > 1
        for i, spec in enumerate(specs):
            pane_id = f"pane-{len(self.panes) + i}"
            try:
                kind, title, kwargs = _parse_target(spec, self.cdp_url)
                factory = _build_target_factory(kind, kwargs)
            except ValueError as exc:
                yield Static(f"[red]skip pane {spec!r}: {exc}[/red]")
                continue
            display_title = _short_title(kind, title) if use_short else title
            pane = TargetPane(
                title=display_title,
                backend_spec=spec,
                provider_key=self.provider_key,
                on_confirm_needed=self._on_pane_confirm_needed,
                pane_id=pane_id,
            )
            self.panes[pane_id] = pane
            yield pane

    async def on_target_picker_targets_chosen(
        self, message: TargetPicker.TargetsChosen
    ) -> None:
        """User pressed 'Attach selected' — mount panes for the chosen specs."""
        panes_container = self.query_one("#panes", PaneGrid)
        # Clear the empty-hint placeholder on first attach.
        try:
            self.query_one("#empty-hint", Static).remove()
        except Exception:  # noqa: BLE001
            pass
        # Deduplicate against already-attached specs (metadata check on title).
        existing_titles = {p.title for p in self.panes.values()}
        new_widgets: list[Widget] = []
        for widget in self._spawn_panes(message.specs):
            if isinstance(widget, TargetPane) and widget.title in existing_titles:
                # already have this pane — skip
                self.panes.pop(widget.id or "", None)
                continue
            new_widgets.append(widget)
        for w in new_widgets:
            await panes_container.mount(w)
        # Recompute grid columns to match the new pane count.
        panes_container.recompute_for(len(self.panes))

    def _build_provider(self):
        kwargs = self.config.provider_kwargs(self.provider_key)
        return provider_registry.build(self.provider_key, **kwargs)

    def on_memory_tree_memory_selected(self, event: MemoryTree.MemorySelected) -> None:
        def _after(_: None) -> None:
            self.query_one("#memtree", MemoryTree).refresh_entries()
        self.push_screen(MemoryModal(event.filename), _after)

    async def on_mount(self) -> None:
        # Panes render their own welcome via TargetPane on_mount.
        # Start v0.3.4 Guardian Gateway in-process on port 8775.
        # The confirm callback routes to the correct pane's modal.
        def _guardian_confirm_callback(pending: PendingConfirm) -> None:
            pane = self.panes.get(pending.pane_id)
            if pane is not None and pane._on_confirm_needed:  # noqa: SLF001
                def _after(ok: bool | None) -> None:
                    if not pending.future.done():
                        pending.future.set_result((bool(ok), "user confirmed" if ok else "user rejected"))
                self.push_screen(ConfirmModal(pending.action, pending.label, pending.args), _after)

        guardian = create_guardian_app(mode="local", confirm_callback=_guardian_confirm_callback)
        self._guardian_task = asyncio.create_task(self._run_guardian(guardian, 8775))

    async def _run_guardian(self, app, port: int) -> None:
        import hypercorn.asyncio
        from hypercorn.config import Config
        cfg = Config()
        cfg.bind = [f"127.0.0.1:{port}"]
        cfg.loglevel = "error"
        try:
            await hypercorn.asyncio.serve(app, cfg)
        except Exception:  # noqa: BLE001
            pass

    async def on_paste(self, event: events.Paste) -> None:
        """Flatten multi-line paste into the focused pane's input."""
        text = event.text
        if "\n" not in text and "\r" not in text:
            return
        event.stop()
        event.prevent_default()
        flat = " ".join(text.replace("\r\n", "\n").replace("\r", "\n").splitlines()).strip()
        inp = self._focused_input()
        if inp is None:
            return
        inp.value = inp.value + flat
        inp.cursor_position = len(inp.value)

    def _focused_input(self) -> Input | None:
        focused = self.focused
        if isinstance(focused, Input):
            return focused
        # fall back to first pane's input
        for pane in self.panes.values():
            try:
                return pane.query_one("#pane-input", Input)
            except Exception:  # noqa: BLE001
                continue
        return None

    def _focused_pane(self) -> TargetPane | None:
        """Which pane's Input currently has focus (for voice/paste routing)."""
        node = self.focused
        while node is not None:
            if isinstance(node, TargetPane):
                return node
            node = node.parent  # type: ignore[assignment]
        # fallback: first pane
        return next(iter(self.panes.values()), None)

    # ---- confirm routing ------------------------------------------------

    def _on_pane_confirm_needed(
        self, pane: TargetPane, action: str, label: str, args: dict
    ) -> None:
        self._pending_confirm_pane = pane

        async def _resolve(ok: bool | None) -> None:
            target = self._pending_confirm_pane
            self._pending_confirm_pane = None
            if target is not None:
                await target.resolve_confirm(bool(ok))

        self.push_screen(ConfirmModal(action, label, args), _resolve)

    async def action_confirm_yes(self) -> None:
        # Fallback keyboard yes when modal isn't the active screen (rare).
        pane = self._focused_pane()
        if pane is not None and pane.confirm_active:
            await pane.resolve_confirm(True)

    async def action_confirm_no(self) -> None:
        pane = self._focused_pane()
        if pane is not None and pane.confirm_active:
            await pane.resolve_confirm(False)

    # ---- clipboard ------------------------------------------------------

    async def action_paste_clipboard(self) -> None:
        inp = self._focused_input()
        if inp is None:
            return
        text = await asyncio.to_thread(_read_clipboard)
        if not text:
            return
        flat = " ".join(text.splitlines())
        inp.value = inp.value + flat
        inp.cursor_position = len(inp.value)

    async def action_copy_log(self) -> None:
        pane = self._focused_pane()
        if pane is None:
            return
        blob = "\n".join(pane.log_buffer)
        if not blob:
            return
        ok = await asyncio.to_thread(_write_clipboard, blob)
        # Also dump to file so users have a fallback.
        try:
            with open(self._log_dump_path, "a", encoding="utf-8") as f:
                f.write(f"\n=== {pane.title} ===\n" + blob + "\n")
        except OSError:
            pass
        log = pane.query_one("#pane-log", RichLog)
        if ok:
            log.write(Text.from_markup(f"[green]📄 copied {len(blob)} chars[/green]"))
        else:
            log.write(Text.from_markup(
                f"[yellow]📄 clipboard write failed — see {self._log_dump_path}[/yellow]"
            ))

    # ---- voice ----------------------------------------------------------

    async def action_voice_toggle(self) -> None:
        pane = self._focused_pane()
        if pane is None:
            return
        log = pane.query_one("#pane-log", RichLog)
        inp = pane.query_one("#pane-input", Input)
        if self._voice is None:
            try:
                self._voice = VoiceCapture()
                await self._voice.start()
            except RuntimeError as e:
                log.write(Text.from_markup(f"[red]🎙 voice unavailable: {e}[/red]"))
                self._voice = None
                return
            self._voice_baseline = inp.value
            log.write(Text.from_markup("[cyan]🎙 recording — Ctrl+Space to stop[/cyan]"))
            self._voice_task = asyncio.create_task(self._voice_pump(pane))
        else:
            await self._voice.stop()
            self._voice = None
            if self._voice_task is not None:
                self._voice_task.cancel()
                self._voice_task = None
            log.write(Text.from_markup("[dim]🎙 stopped[/dim]"))

    async def _voice_pump(self, pane: TargetPane) -> None:
        assert self._voice is not None
        inp = pane.query_one("#pane-input", Input)
        log = pane.query_one("#pane-log", RichLog)
        try:
            async for ev in self._voice.events():
                if ev.kind == "partial":
                    inp.value = self._voice_baseline + ev.text
                elif ev.kind == "final":
                    inp.value = self._voice_baseline + ev.text
                    self._voice_baseline = inp.value
                elif ev.kind == "error":
                    log.write(Text.from_markup(f"[red]🎙 asr error: {ev.text}[/red]"))
                    break
        except asyncio.CancelledError:
            pass

    # ---- archive --------------------------------------------------------

    async def action_archive(self) -> None:
        pane = self._focused_pane()
        if pane is None or pane.runner is None:
            return
        session_id = pane.runner.session.id
        log = pane.query_one("#pane-log", RichLog)

        async def _done(slug: str | None) -> None:
            if slug:
                log.write(Text.from_markup(
                    f"[green]📁 archived {session_id[:8]}… to [b]{slug}[/b][/green]"
                ))

        self.push_screen(ProjectModal(session_id), _done)


def run(
    cdp_url: str = "http://127.0.0.1:9222",
    provider_key: str = "volc",
    config: Config | None = None,
    targets: list[str] | None = None,
) -> None:
    SenseUseApp(
        cdp_url=cdp_url,
        provider_key=provider_key,
        config=config,
        targets=targets,
    ).run()
