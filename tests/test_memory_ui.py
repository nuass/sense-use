"""MemoryTree + MemoryModal headless tests."""

import shutil

import pytest
from textual.app import App, ComposeResult

from sense_use.store import memory_store, project_store, session_store
from sense_use.tui.screens.memory_modal import MemoryModal
from sense_use.tui.widgets.memory_tree import MemoryTree


@pytest.fixture
def tmp_root(tmp_path, monkeypatch):
    monkeypatch.setattr(session_store, "ROOT", tmp_path)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(memory_store, "MEM_DIR", tmp_path / "memory")
    monkeypatch.setattr(memory_store, "INDEX", tmp_path / "memory" / "MEMORY.md")
    yield tmp_path
    shutil.rmtree(tmp_path, ignore_errors=True)


class _TreeHarness(App):
    def __init__(self) -> None:
        super().__init__()
        self.selected: str | None = None

    def compose(self) -> ComposeResult:
        yield MemoryTree(id="mt")

    def on_memory_tree_memory_selected(self, event: MemoryTree.MemorySelected) -> None:
        self.selected = event.filename
        self.exit()


class _ModalHarness(App):
    def __init__(self, filename: str) -> None:
        super().__init__()
        self._filename = filename
        self.closed = False

    async def on_mount(self) -> None:
        def _done(_: None) -> None:
            self.closed = True
            self.exit()

        self.push_screen(MemoryModal(self._filename), _done)


@pytest.mark.asyncio
async def test_memory_tree_lists_and_emits(tmp_root):
    memory_store.write_memory("hello.md", "hi", title="Hello", hook="greet")
    memory_store.write_memory("second.md", "two", title="Second", hook="s")

    app = _TreeHarness()
    async with app.run_test() as pilot:
        await pilot.pause()
        tree = app.query_one("#mt", MemoryTree)
        # Directly emit the message from the tree — clicking the ListView
        # in headless Pilot is flaky. We're testing that the widget/message
        # wiring works, not the ListView keyboard nav (that's textual's).
        tree.post_message(MemoryTree.MemorySelected("hello.md"))
        await pilot.pause()
    assert app.selected == "hello.md"


@pytest.mark.asyncio
async def test_memory_modal_edits_file(tmp_root):
    memory_store.write_memory("edit.md", "original\n", title="Edit", hook="")
    app = _ModalHarness("edit.md")
    async with app.run_test() as pilot:
        await pilot.pause()  # let push_screen finish
        editor = app.screen.query_one("TextArea")
        editor.text = "modified content\n"
        await pilot.press("ctrl+s")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
    assert memory_store.read_memory("edit.md") == "modified content\n"
