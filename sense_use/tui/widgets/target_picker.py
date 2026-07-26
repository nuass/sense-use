"""TargetPicker — sidebar widget listing discovered targets with checkboxes.

User picks which targets to attach as panes. Emits a ``TargetsChosen`` message
carrying the selected specs; the parent app spawns TargetPanes for them.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, SelectionList, Static
from textual.widgets.selection_list import Selection

from sense_use.core.discovery import DiscoveredTarget, discover_all


class TargetPicker(Widget):
    """Sidebar target discovery + multi-select.

    Boot flow:
    1. ``on_mount`` starts an async scan.
    2. Each discovered ``DiscoveredTarget`` becomes a Selection row.
    3. User checks boxes, presses "Attach" — we post ``TargetsChosen``.
    4. Rescan button re-runs discovery.
    """

    DEFAULT_CSS = """
    TargetPicker { height: 1fr; width: 100%; }
    TargetPicker Static.hint { padding: 0 1; color: $text-muted; }
    TargetPicker SelectionList { height: 1fr; margin: 1 0; }
    TargetPicker #btnrow { height: auto; padding: 0 1; }
    TargetPicker Button { width: 100%; margin: 0 0 1 0; }
    """

    @dataclass
    class TargetsChosen(Message):
        specs: list[str]

    def __init__(self, id: str | None = None) -> None:
        super().__init__(id=id)
        self._discovered: list[DiscoveredTarget] = []

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("[b]Available targets[/b]", classes="hint", markup=True)
            yield Static("[dim]scanning…[/dim]", id="status", classes="hint", markup=True)
            yield SelectionList[str](id="targets_list")
            yield Static(id="btnrow")  # placeholder container for buttons
            yield Button("▶ Attach selected", id="attach", variant="success")
            yield Button("⟳ Rescan", id="rescan", variant="default")

    async def on_mount(self) -> None:
        self._start_scan()

    # ---- discovery ------------------------------------------------------

    @work(exclusive=True)
    async def _start_scan(self) -> None:
        status = self.query_one("#status", Static)
        listbox = self.query_one("#targets_list", SelectionList)
        status.update(Text.from_markup("[dim]scanning…[/dim]"))
        listbox.clear_options()

        try:
            self._discovered = await discover_all()
        except Exception as exc:  # noqa: BLE001
            status.update(Text.from_markup(f"[red]scan failed: {exc}[/red]"))
            return

        if not self._discovered:
            status.update(Text.from_markup(
                "[yellow]nothing found[/yellow]\n"
                "[dim]start Chrome with --remote-debugging-port=9222 or plug in adb[/dim]"
            ))
            return

        icons = {"browser": "🌐", "adb": "📱", "desktop": "🖥", "vnc": "🖧"}
        for t in self._discovered:
            icon = icons.get(t.kind, "•")
            label = f"{icon} {t.title}  [dim]{t.detail}[/dim]"
            listbox.add_option(Selection(label, t.spec, initial_state=True))

        status.update(Text.from_markup(
            f"[green]{len(self._discovered)} target(s) found[/green] — check to attach"
        ))

    # ---- button handlers -----------------------------------------------

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "attach":
            listbox = self.query_one("#targets_list", SelectionList)
            specs = list(listbox.selected)
            if not specs:
                self.query_one("#status", Static).update(
                    Text.from_markup("[yellow]select at least one target[/yellow]")
                )
                return
            self.post_message(self.TargetsChosen(specs=specs))
        elif event.button.id == "rescan":
            self._start_scan()

    @property
    def discovered(self) -> list[DiscoveredTarget]:
        return self._discovered
