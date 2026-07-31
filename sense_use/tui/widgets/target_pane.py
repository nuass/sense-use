"""TargetPane — a self-contained agent lane for one Backend subprocess.

Since v0.3.3 (GOAI AgentTeams compliance) the TaskRunner and Backend
live in a dedicated worker subprocess managed by ``WorkerProcess``. No
state leaks between panes, and crashing a worker won't take down the TUI.

Each pane spawns one ``python -m sense_use.worker`` when the user
submits a goal. Worker stdout is NDJSON; we pump it into the RichLog
and LivePreview widget. Confirmations go back through worker stdin.

The pane is UI-only: it does not know about the outer app's memory
sidebar or project archiver. The outer app queries the pane for its
worker when those features fire.
"""

from __future__ import annotations

import asyncio

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import Input, RichLog, Static

from sense_use.tui.widgets.live_preview import LivePreview
from sense_use.worker_proc import WorkerProcess


class TargetPane(Widget):
    """One agent lane for a single Backend subprocess.

    Parameters
    ----------
    title:
        Human label shown at the top of the pane (e.g. "browser @ 9222").
    backend_spec:
        ``--targets`` style spec string passed to the worker subprocess
        (e.g. "browser", "adb@SERIAL", "desktop", "vnc@host:port:passwd").
    provider_key:
        Model provider name for the worker subprocess (e.g. "claude", "volc").
    on_confirm_needed:
        Callback ``(pane, action, label, args) -> None`` the outer app uses to
        pop a ConfirmModal. The pane sends the reply back to the worker via stdin.
    """

    DEFAULT_CSS = """
    TargetPane {
        border: solid $primary;
        width: 1fr;
        height: 1fr;
    }
    TargetPane > Vertical { height: 100%; }
    TargetPane #pane-title { padding: 0 1; background: $primary 20%; text-style: bold; }
    TargetPane LivePreview { height: 10; }
    TargetPane RichLog { height: 1fr; background: $surface; }
    TargetPane Input { dock: bottom; }
    TargetPane.-focused { border: solid $success; }
    """

    def __init__(
        self,
        title: str,
        backend_spec: str,
        provider_key: str,
        on_confirm_needed=None,
        pane_id: str | None = None,
    ) -> None:
        super().__init__(id=pane_id)
        self.title = title
        self.backend_spec = backend_spec
        self.provider_key = provider_key
        self._on_confirm_needed = on_confirm_needed

        self._worker: WorkerProcess | None = None
        self._pump_task: asyncio.Task | None = None
        self._confirm_active = False
        self._log_buffer: list[str] = []

    # ---- lifecycle -----------------------------------------------------

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(f"[b]{self.title}[/b] · [dim]idle[/dim]", id="pane-title", markup=True)
            yield LivePreview(pane_id="pane-preview")
            yield RichLog(id="pane-log", wrap=True, markup=True, highlight=True)
            yield Input(placeholder=f"goal for {self.title} (Enter to run)…", id="pane-input")

    async def on_mount(self) -> None:
        # No-op now; we don't have a bus until a worker is spawned.
        pass

    async def on_unmount(self) -> None:
        if self._pump_task is not None and not self._pump_task.done():
            self._pump_task.cancel()
        if self._worker is not None:
            await self._worker.stop()

    # ---- event pump ----------------------------------------------------

    async def _pump_events(self, worker: WorkerProcess, log: RichLog) -> None:
        async for p in worker.events():
            event_kind = p.get("event", "unknown")
            plain: str | None = None
            if event_kind == "user_msg":
                plain = f"🧑 {p.get('goal', '')}"
                log.write(Text.from_markup(f"[bold]🧑 {p.get('goal', '')}[/bold]"))
            elif event_kind == "observe":
                size = len(p.get("screenshot_bytes", b""))
                step = p.get("step", 0)
                plain = f"👁 step {step} · {size}b"
                log.write(Text.from_markup(f"[dim]{plain}[/dim]"))
                try:
                    self.query_one(LivePreview).set_bytes(
                        p.get("screenshot_bytes"), step=step,
                    )
                except Exception:  # noqa: BLE001
                    pass
            elif event_kind == "think":
                thought = (p.get("thought", "") or "")[:80]
                action = p.get("action", "")
                step = p.get("step", 0)
                plain = f"🧠 s{step} {thought}\n   → {action} {p.get('args')}"
                log.write(Text.from_markup(
                    f"[yellow]🧠 s{step}[/yellow] {thought}\n"
                    f"   [cyan]→ {action} {p.get('args')}[/cyan]"
                ))
            elif event_kind == "act_result":
                ok = p.get("ok", False)
                color = "green" if ok else "red"
                mark = "✔" if ok else "✖"
                action = p.get("action", "")
                detail = p.get("detail", "")
                plain = f"{mark} {action} — {detail}"
                log.write(Text.from_markup(
                    f"[{color}]{mark} {action} — {detail}[/{color}]"
                ))
            elif event_kind == "confirm_needed":
                self._confirm_active = True
                action = p.get("action", "")
                label = p.get("label", "")
                plain = f"⚠ CONFIRM {action} on {label}"
                log.write(Text.from_markup(
                    f"[bold magenta]⚠ CONFIRM[/bold magenta] {action} on [u]{label}[/u]"
                ))
                if self._on_confirm_needed is not None:
                    self._on_confirm_needed(
                        self, action, label, p.get("args", {}),
                    )
            elif event_kind == "confirm_result":
                self._confirm_active = False
            elif event_kind == "done":
                answer = p.get("answer", "")
                plain = f"✅ {answer}"
                log.write(Text.from_markup(f"[bold green]✅ {answer}[/bold green]"))
                self._set_title_status("done")
            elif event_kind == "error":
                reason = p.get("reason", "")
                plain = f"✖ {reason}"
                log.write(Text.from_markup(f"[bold red]✖ {reason}[/bold red]"))
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
        if self._worker is not None and self._pump_task is not None and not self._pump_task.done():
            self.query_one("#pane-log", RichLog).write(
                Text.from_markup("[dim]⏳ busy — wait for current run[/dim]")
            )
            return
        event.stop()
        await self._start_run(goal)

    async def _start_run(self, goal: str) -> None:
        log = self.query_one("#pane-log", RichLog)
        # Stop any prior worker that somehow didn't clean up.
        if self._worker is not None:
            await self._worker.stop()
        self._log_buffer.clear()
        self._set_title_status("running")

        self._worker = WorkerProcess(
            backend_spec=self.backend_spec,
            provider_key=self.provider_key,
            goal=goal,
        )
        try:
            await self._worker.start()
        except Exception as exc:  # noqa: BLE001
            log.write(Text.from_markup(f"[red]worker spawn failed: {exc}[/red]"))
            self._set_title_status("error")
            return

        # The pump coro reads NDJSON from the worker stdout, converts
        # to RichLog lines and LivePreview updates. It finishes when
        # the worker exits (done / error / killed).
        async def _pump():
            try:
                await self._pump_events(self._worker, log)
            finally:
                pass

        self._pump_task = asyncio.create_task(_pump())

    # ---- helpers exposed to outer app ---------------------------------

    async def resolve_confirm(self, ok: bool) -> None:
        if self._worker is not None and self._confirm_active:
            await self._worker.send_confirm(ok)

    @property
    def confirm_active(self) -> bool:
        return self._confirm_active

    @property
    def log_buffer(self) -> list[str]:
        return self._log_buffer
