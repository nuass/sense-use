"""ConfirmModal — pops when the agent hits a sensitive action.

Bindings: Y = ✅ allow, N = ❌ reject, R = 🔁 replan (rejects and hints at retry).
Emits a boolean via ``dismiss(True/False)`` back to whoever pushed it.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class ConfirmModal(ModalScreen[bool]):
    CSS = """
    ConfirmModal {
        align: center middle;
        background: rgba(0, 0, 0, 0.5);
    }
    #box {
        width: 60;
        padding: 1 2;
        border: thick $warning;
        background: $panel;
    }
    #title { text-style: bold; color: $warning; }
    #detail { margin: 1 0; }
    #buttons { align-horizontal: center; }
    Button { margin: 0 1; }
    """

    BINDINGS = [
        Binding("y", "yes", "Yes"),
        Binding("n", "no", "No"),
        Binding("r", "replan", "Replan"),
        Binding("escape", "no", "Cancel", show=False),
    ]

    def __init__(self, action: str, label: str, args: dict) -> None:
        super().__init__()
        self._action = action
        self._label = label
        self._args = args

    def compose(self) -> ComposeResult:
        with Vertical(id="box"):
            yield Static("⚠  Sensitive action — confirm before proceeding", id="title")
            yield Static(
                f"[b]action:[/b] {self._action}\n"
                f"[b]target:[/b] {self._label or '(no label)'}\n"
                f"[b]args:[/b] {self._args}",
                id="detail",
                markup=True,
            )
            yield Static(
                "[dim]Y = ✅ allow    N = ❌ reject    R = 🔁 replan[/dim]",
                markup=True,
            )
            with Vertical(id="buttons"):
                yield Button("✅ Allow (Y)", id="yes", variant="success")
                yield Button("❌ Reject (N)", id="no", variant="error")
                yield Button("🔁 Replan (R)", id="replan", variant="warning")

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)

    def action_replan(self) -> None:
        # Same effect as "no" but the caller can hint replan in history.
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "yes":
            self.dismiss(True)
        else:
            self.dismiss(False)
