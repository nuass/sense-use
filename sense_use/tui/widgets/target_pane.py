"""TargetPane — a self-contained agent lane for one Backend.

Each pane owns its own {Backend, TaskRunner, EventBus, Session, Input, RichLog}
so multiple targets (browser / adb / desktop / vnc) can run side-by-side in
the same TUI without stepping on each other.

The pane is UI-only: it does not know about the outer app's memory sidebar or
project archiver. The outer app queries the pane for its runner/session when
those features fire.
"""

from __future__ import annotations

import asyncio

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import Input, RichLog, Static

from sense_use.core.backend import Backend
from sense_use.core.event_bus import Event, EventBus
from sense_use.core.session import Session
from sense_use.core.task_runner import TaskRunner
from sense_use.models.base import ModelProvider


class TargetPane(Widget):
    """One agent lane for a single Backend.

    Parameters
    ----------
    title:
        Human label shown at the top of the pane (e.g. "browser @ 9222").
    backend_factory:
        Zero-arg callable that returns a fresh Backend on demand. We defer
        construction so an unreachable target (no adb device, no CDP) only
        fails when the user tries to use it, not on TUI boot.
    provider:
        Shared ModelProvider — cheap and stateless, safe to share across panes.
    on_confirm_needed:
        Callback ``(pane, action, label, args) -> None`` the outer app uses to
        pop a ConfirmModal. The pane still owns the resolve future.
    """

    DEFAULT_CSS = """
    TargetPane {
        border: solid $primary;
        width: 1fr;
        height: 1fr;
    }
    TargetPane > Vertical { height: 100%; }
    TargetPane #pane-title { padding: 0 1; background: $primary 20%; text-style: bold; }
    TargetPane RichLog { height: 1fr; background: $surface; }
    TargetPane Input { dock: bottom; }
    TargetPane.-focused { border: solid $success; }
    """

    def __init__(
        self,
        title: str,
        backend_factory,
        provider: ModelProvider,
        on_confirm_needed=None,
        pane_id: str | None = None,
    ) -> None:
        super().__init__(id=pane_id)
        self.title = title
        self._backend_factory = backend_factory
        self.provider = provider
        self._on_confirm_needed = on_confirm_needed

        self.bus = EventBus()
        self.backend: Backend | None = None
        self.runner: TaskRunner | None = None
        self._runner_task: asyncio.Task | None = None
        self._sub: asyncio.Queue[Event] | None = None
        self._pump_task: asyncio.Task | None = None
        self._confirm_active = False
        self._log_buffer: list[str] = []

    # ---- lifecycle -----------------------------------------------------

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(f"[b]{self.title}[/b] · [dim]idle[/dim]", id="pane-title", markup=True)
            yield RichLog(id="pane-log", wrap=True, markup=True, highlight=True)
            yield Input(placeholder=f"goal for {self.title} (Enter to run)…", id="pane-input")

    async def on_mount(self) -> None:
        self._sub = self.bus.subscribe()
        self._pump_task = asyncio.create_task(self._pump_events())

    async def on_unmount(self) -> None:
        if self._pump_task is not None:
            self._pump_task.cancel()
        if self._runner_task is not None and not self._runner_task.done():
            self._runner_task.cancel()
        if self.backend is not None:
            try:
                await self.backend.stop()
            except Exception:  # noqa: BLE001
                pass

    # ---- event pump ----------------------------------------------------

    async def _pump_events(self) -> None:
        log = self.query_one("#pane-log", RichLog)
        assert self._sub is not None
        while True:
            ev = await self._sub.get()
            self._render_event(log, ev)

    def _render_event(self, log: RichLog, ev: Event) -> None:
        p = ev.payload
        plain: str | None = None
        if ev.kind == "user_msg":
            plain = f"🧑 {p.get('goal','')}"
            log.write(Text.from_markup(f"[bold]🧑 {p.get('goal','')}[/bold]"))
        elif ev.kind == "observe":
            n = p.get("screenshot_bytes")
            size = n if isinstance(n, int) else (len(n) if n else 0)
            plain = f"👁 step {p.get('step')} · {size}b"
            log.write(Text.from_markup(f"[dim]{plain}[/dim]"))
        elif ev.kind == "think":
            plain = (
                f"🧠 s{p.get('step')} {p.get('thought','')[:80]}\n"
                f"   → {p.get('action')} {p.get('args')}"
            )
            log.write(Text.from_markup(
                f"[yellow]🧠 s{p.get('step')}[/yellow] {p.get('thought','')[:80]}\n"
                f"   [cyan]→ {p.get('action')} {p.get('args')}[/cyan]"
            ))
        elif ev.kind == "act_result":
            ok = p.get("ok")
            color = "green" if ok else "red"
            mark = "✔" if ok else "✖"
            plain = f"{mark} {p.get('action')} — {p.get('detail','')}"
            log.write(Text.from_markup(
                f"[{color}]{mark} {p.get('action')} — {p.get('detail','')}[/{color}]"
            ))
        elif ev.kind == "confirm_needed":
            self._confirm_active = True
            plain = f"⚠ CONFIRM {p.get('action')} on {p.get('label','')}"
            log.write(Text.from_markup(
                f"[bold magenta]⚠ CONFIRM[/bold magenta] {p.get('action')} on [u]{p.get('label','')}[/u]"
            ))
            if self._on_confirm_needed is not None:
                self._on_confirm_needed(self, p.get("action", ""), p.get("label", ""), p.get("args", {}))
        elif ev.kind == "confirm_result":
            self._confirm_active = False
        elif ev.kind == "done":
            plain = f"✅ {p.get('answer','')}"
            log.write(Text.from_markup(f"[bold green]✅ {p.get('answer','')}[/bold green]"))
            self._set_title_status("done")
        elif ev.kind == "error":
            plain = f"✖ {p.get('reason','')}"
            log.write(Text.from_markup(f"[bold red]✖ {p.get('reason','')}[/bold red]"))
            self._set_title_status("error")

        if plain is not None:
            self._log_buffer.append(plain)

    def _set_title_status(self, status: str) -> None:
        try:
            self.query_one("#pane-title", Static).update(
                Text.from_markup(f"[b]{self.title}[/b] · [dim]{status}[/dim]")
            )
        except Exception:  # noqa: BLE001
            pass

    # ---- input ---------------------------------------------------------

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        # This runs only when the pane's own Input is submitted; other panes'
        # Inputs won't reach here because Textual scopes the message to the
        # widget's DOM subtree.
        if event.input.id != "pane-input":
            return
        goal = event.value.strip()
        event.input.value = ""
        if not goal:
            return
        if self._runner_task is not None and not self._runner_task.done():
            self.query_one("#pane-log", RichLog).write(
                Text.from_markup("[dim]⏳ busy — wait for current run[/dim]")
            )
            return
        event.stop()
        await self._start_run(goal)

    async def _start_run(self, goal: str) -> None:
        log = self.query_one("#pane-log", RichLog)
        # (Re)create backend for each run so a crashed backend from a prior
        # run doesn't leak state. Providers are stateless — reuse.
        try:
            self.backend = self._backend_factory()
            await self.backend.start()
        except Exception as exc:  # noqa: BLE001
            log.write(Text.from_markup(f"[red]backend start failed: {exc}[/red]"))
            self._set_title_status("error")
            return

        session = Session(goal=goal)
        self.runner = TaskRunner(
            session=session, backend=self.backend, provider=self.provider, bus=self.bus,
        )
        log.write(Text.from_markup(f"[dim]session {session.id[:8]}… started[/dim]"))
        self._set_title_status("running")

        async def _go():
            try:
                await self.runner.run()  # type: ignore[union-attr]
            finally:
                if self.backend is not None:
                    try:
                        await self.backend.stop()
                    except Exception:  # noqa: BLE001
                        pass

        self._runner_task = asyncio.create_task(_go())

    # ---- helpers exposed to outer app ---------------------------------

    async def resolve_confirm(self, ok: bool) -> None:
        if self.runner is not None and self._confirm_active:
            await self.runner.resolve_confirm(ok)

    @property
    def confirm_active(self) -> bool:
        return self._confirm_active

    @property
    def log_buffer(self) -> list[str]:
        return self._log_buffer
