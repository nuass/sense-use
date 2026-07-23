"""Textual TUI — main app for M1 (single Browser session, no floating viewer yet)."""

from __future__ import annotations

import asyncio

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, RichLog, Static

from sense_use.backends.browser_backend import BrowserBackend
from sense_use.config import Config
from sense_use.core.event_bus import Event, EventBus
from sense_use.core.session import Session
from sense_use.core.task_runner import TaskRunner
from sense_use.models import provider_registry
from sense_use.store.session_store import SessionStore
from sense_use.tui.screens.confirm_modal import ConfirmModal
from sense_use.tui.screens.memory_modal import MemoryModal
from sense_use.tui.screens.project_modal import ProjectModal
from sense_use.tui.widgets.memory_tree import MemoryTree
from sense_use.tui.widgets.voice_input import VoiceCapture


class SenseUseApp(App):
    CSS = """
    Screen { layout: vertical; }
    #main { height: 1fr; }
    #sidebar { width: 30; border-right: solid $primary; }
    #chat { padding: 0 1; }
    #input { dock: bottom; }
    RichLog { background: $surface; }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit"),
        Binding("ctrl+s", "archive", "📁 Archive"),
        Binding("ctrl+space", "voice_toggle", "🎙 Voice"),
        Binding("y", "confirm_yes", "✅ Yes", show=False),
        Binding("n", "confirm_no", "❌ No", show=False),
    ]

    def __init__(
        self,
        cdp_url: str = "http://127.0.0.1:9222",
        provider_key: str = "volc",
        config: Config | None = None,
    ) -> None:
        super().__init__()
        self.cdp_url = cdp_url
        self.provider_key = provider_key
        self.config = config or Config()
        self.bus = EventBus()
        self.runner: TaskRunner | None = None
        self._runner_task: asyncio.Task | None = None
        self._sub: asyncio.Queue[Event] | None = None
        self._session_store: SessionStore | None = None
        self._confirm_active = False
        self._voice: VoiceCapture | None = None
        self._voice_task: asyncio.Task | None = None
        self._voice_baseline: str = ""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="main"):
            with Vertical(id="sidebar"):
                yield Static("[b]Targets[/b]\n\n• browser @ 9222\n\n[dim]Ctrl+S archive · Ctrl+Space voice[/dim]", id="targets")
                yield MemoryTree(id="memtree")
            with Vertical(id="chat"):
                yield RichLog(id="log", wrap=True, markup=True, highlight=True)
        yield Input(placeholder="Type your task and press Enter (Y/N to confirm)...", id="input")
        yield Footer()

    def on_memory_tree_memory_selected(self, event: MemoryTree.MemorySelected) -> None:
        def _after(_: None) -> None:
            # Reload sidebar in case hook/title changed via update_index_line
            self.query_one("#memtree", MemoryTree).refresh_entries()

        self.push_screen(MemoryModal(event.filename), _after)

    async def on_mount(self) -> None:
        log = self.query_one("#log", RichLog)
        log.write(Text.from_markup(
            "[bold cyan]sense-use[/bold cyan] — Computer + Mobile + Browser Use.\n"
            f"[dim]CDP: {self.cdp_url} · provider: {self.provider_key}[/dim]\n"
            "Type a goal below (e.g. 'open arxiv.org and read top 3 titles for llm agents').\n"
        ))
        self._sub = self.bus.subscribe()
        self.run_worker(self._pump_events(), exclusive=False)

    async def _pump_events(self) -> None:
        log = self.query_one("#log", RichLog)
        assert self._sub is not None
        while True:
            ev = await self._sub.get()
            if self._session_store:
                self._session_store.append(ev)
            self._render_event(log, ev)

    def _render_event(self, log: RichLog, ev: Event) -> None:
        p = ev.payload
        if ev.kind == "user_msg":
            log.write(Text.from_markup(f"[bold]🧑 goal:[/bold] {p.get('goal','')}"))
        elif ev.kind == "observe":
            n = p.get("screenshot_bytes")
            size = n if isinstance(n, int) else (len(n) if n else 0)
            log.write(Text.from_markup(f"[dim]👁 step {p.get('step')} — screenshot {size} bytes[/dim]"))
        elif ev.kind == "think":
            log.write(Text.from_markup(
                f"[yellow]🧠 step {p.get('step')}[/yellow] {p.get('thought','')}\n"
                f"   [cyan]→ {p.get('action')} {p.get('args')}[/cyan]"
            ))
        elif ev.kind == "act_result":
            ok = p.get("ok")
            color = "green" if ok else "red"
            log.write(Text.from_markup(
                f"[{color}]✔ {p.get('action')} — {p.get('detail','')}[/{color}]"
            ))
        elif ev.kind == "confirm_needed":
            self._confirm_active = True
            log.write(Text.from_markup(
                f"[bold magenta]⚠ CONFIRM[/bold magenta] {p.get('action')} on "
                f"[u]{p.get('label','')}[/u] · press [b]Y[/b] to allow, [b]N[/b] to reject"
            ))
            self._push_confirm(p.get("action", ""), p.get("label", ""), p.get("args", {}))
        elif ev.kind == "confirm_result":
            self._confirm_active = False
        elif ev.kind == "done":
            log.write(Text.from_markup(f"[bold green]✅ DONE:[/bold green] {p.get('answer','')}"))
        elif ev.kind == "error":
            log.write(Text.from_markup(f"[bold red]✖ error:[/bold red] {p.get('reason','')}"))

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        goal = event.value.strip()
        event.input.value = ""
        if not goal:
            return
        if self._runner_task and not self._runner_task.done():
            self.query_one("#log", RichLog).write("[dim]⏳ agent busy — wait for it to finish[/dim]")
            return
        await self._start_run(goal)

    async def _start_run(self, goal: str) -> None:
        log = self.query_one("#log", RichLog)
        backend = BrowserBackend(cdp_url=self.cdp_url)
        try:
            await backend.start()
        except Exception as e:  # noqa: BLE001
            log.write(Text.from_markup(f"[red]failed to connect CDP: {e}[/red]"))
            return

        try:
            kwargs = self.config.provider_kwargs(self.provider_key)
            provider = provider_registry.build(self.provider_key, **kwargs)
        except (RuntimeError, KeyError) as e:
            log.write(Text.from_markup(f"[red]{e}[/red]"))
            await backend.stop()
            return

        session = Session(goal=goal)
        self._session_store = SessionStore(session.id)
        self.runner = TaskRunner(session=session, backend=backend, provider=provider, bus=self.bus)
        log.write(Text.from_markup(f"[dim]session {session.id} started[/dim]"))

        async def _go():
            try:
                await self.runner.run()  # type: ignore[union-attr]
            finally:
                await backend.stop()

        self._runner_task = asyncio.create_task(_go())

    async def action_confirm_yes(self) -> None:
        if self._confirm_active and self.runner:
            await self.runner.resolve_confirm(True)

    async def action_confirm_no(self) -> None:
        if self._confirm_active and self.runner:
            await self.runner.resolve_confirm(False)

    def _push_confirm(self, action: str, label: str, args: dict) -> None:
        async def _resolve(ok: bool | None) -> None:
            if self.runner and self._confirm_active:
                await self.runner.resolve_confirm(bool(ok))
        self.push_screen(ConfirmModal(action, label, args), _resolve)

    async def action_voice_toggle(self) -> None:
        log = self.query_one("#log", RichLog)
        inp = self.query_one("#input", Input)
        if self._voice is None:
            try:
                self._voice = VoiceCapture()
                await self._voice.start()
            except RuntimeError as e:
                log.write(Text.from_markup(f"[red]🎙 voice unavailable: {e}[/red]"))
                self._voice = None
                return
            self._voice_baseline = inp.value
            log.write(Text.from_markup("[cyan]🎙 recording — press Ctrl+Space to stop[/cyan]"))
            self._voice_task = asyncio.create_task(self._voice_pump())
        else:
            await self._voice.stop()
            self._voice = None
            if self._voice_task is not None:
                self._voice_task.cancel()
                self._voice_task = None
            log.write(Text.from_markup("[dim]🎙 stopped[/dim]"))

    async def _voice_pump(self) -> None:
        assert self._voice is not None
        inp = self.query_one("#input", Input)
        log = self.query_one("#log", RichLog)
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

    async def action_archive(self) -> None:
        if self.runner is None:
            self.query_one("#log", RichLog).write("[dim]no active session to archive[/dim]")
            return
        session_id = self.runner.session.id
        log = self.query_one("#log", RichLog)

        async def _done(slug: str | None) -> None:
            if slug:
                log.write(Text.from_markup(
                    f"[green]📁 archived session {session_id[:8]}… to project [b]{slug}[/b][/green]"
                ))
            else:
                log.write("[dim]archive cancelled[/dim]")

        self.push_screen(ProjectModal(session_id), _done)


def run(
    cdp_url: str = "http://127.0.0.1:9222",
    provider_key: str = "volc",
    config: Config | None = None,
) -> None:
    SenseUseApp(cdp_url=cdp_url, provider_key=provider_key, config=config).run()
