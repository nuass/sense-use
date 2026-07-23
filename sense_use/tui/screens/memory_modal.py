"""Memory Modal — click a memory entry to see full contents and edit inline.

Emits nothing back to the caller; saves are persisted to disk directly.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static, TextArea

from sense_use.store import memory_store


class MemoryModal(ModalScreen[None]):
    CSS = """
    MemoryModal {
        align: center middle;
        background: rgba(0, 0, 0, 0.5);
    }
    #box {
        width: 90%;
        height: 80%;
        padding: 1 2;
        border: thick $primary;
        background: $panel;
    }
    #title { text-style: bold; color: $primary; margin-bottom: 1; }
    TextArea { height: 1fr; }
    #buttons { align-horizontal: center; margin-top: 1; }
    Button { margin: 0 1; }
    """

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("ctrl+s", "save", "Save"),
    ]

    def __init__(self, filename: str) -> None:
        super().__init__()
        self._filename = filename
        self._original: str = ""

    def compose(self) -> ComposeResult:
        try:
            self._original = memory_store.read_memory(self._filename)
        except FileNotFoundError:
            self._original = ""
        with Vertical(id="box"):
            yield Static(
                f"📝  memory / [b]{self._filename}[/b]  "
                f"[dim](Ctrl+S save · Esc close)[/dim]",
                id="title",
                markup=True,
            )
            yield TextArea.code_editor(self._original, language="markdown", id="editor")
            with Horizontal(id="buttons"):
                yield Button("Save (Ctrl+S)", id="save", variant="primary")
                yield Button("Close (Esc)", id="close", variant="default")

    def action_close(self) -> None:
        self.dismiss(None)

    def action_save(self) -> None:
        content = self.query_one("#editor", TextArea).text
        memory_store.write_memory(self._filename, content)
        self._original = content
        # Flash the title to acknowledge save.
        title = self.query_one("#title", Static)
        title.update(f"📝  memory / [b]{self._filename}[/b]  [green]✓ saved[/green]")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self.action_save()
        else:
            self.dismiss(None)
