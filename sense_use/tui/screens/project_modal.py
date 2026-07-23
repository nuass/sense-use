"""ProjectModal — Ctrl+S. Pick an existing project or create a new one, then
archive the current session id into it.

Emits the chosen slug via ``dismiss(slug | None)``. The caller (SenseUseApp)
is responsible for calling ``project_store.archive_session(slug, session_id)``.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, ListItem, ListView, Static

from sense_use.store import project_store


class ProjectModal(ModalScreen[str | None]):
    CSS = """
    ProjectModal {
        align: center middle;
        background: rgba(0, 0, 0, 0.5);
    }
    #box {
        width: 70;
        height: 20;
        padding: 1 2;
        border: thick $accent;
        background: $panel;
    }
    #title { text-style: bold; color: $accent; margin-bottom: 1; }
    ListView { height: 10; border: solid $primary; }
    #new-row { margin-top: 1; }
    #buttons { align-horizontal: center; margin-top: 1; }
    Button { margin: 0 1; }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+n", "focus_new", "New", show=False),
    ]

    def __init__(self, session_id: str) -> None:
        super().__init__()
        self._session_id = session_id

    def compose(self) -> ComposeResult:
        with Vertical(id="box"):
            yield Static(
                f"📁  Archive session [b]{self._session_id[:8]}…[/b] to a project",
                id="title",
                markup=True,
            )
            projects = project_store.list_projects()
            items = [
                ListItem(
                    Static(f"{p.name}  [dim]({len(p.session_ids)} sessions)[/dim]"),
                    id=f"proj-{p.slug}",
                )
                for p in projects
            ]
            yield ListView(*items, id="project-list")
            with Horizontal(id="new-row"):
                yield Input(placeholder="or type a new project name…", id="new-name")
            with Horizontal(id="buttons"):
                yield Button("Archive (Enter)", id="archive", variant="primary")
                yield Button("Cancel (Esc)", id="cancel", variant="default")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_focus_new(self) -> None:
        self.query_one("#new-name", Input).focus()

    def _submit(self) -> None:
        new_name = self.query_one("#new-name", Input).value.strip()
        if new_name:
            proj = project_store.create_project(new_name)
            project_store.archive_session(proj.slug, self._session_id)
            self.dismiss(proj.slug)
            return

        lv = self.query_one("#project-list", ListView)
        item = lv.highlighted_child
        if item is None or item.id is None or not item.id.startswith("proj-"):
            return
        slug = item.id[len("proj-"):]
        project_store.archive_session(slug, self._session_id)
        self.dismiss(slug)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "archive":
            self._submit()
        else:
            self.dismiss(None)
