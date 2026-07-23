"""ProjectModal headless test — new project via typing name."""

import shutil

import pytest
from textual.app import App

from sense_use.store import memory_store, project_store, session_store
from sense_use.tui.screens.project_modal import ProjectModal


@pytest.fixture
def tmp_root(tmp_path, monkeypatch):
    monkeypatch.setattr(session_store, "ROOT", tmp_path)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(memory_store, "MEM_DIR", tmp_path / "memory")
    monkeypatch.setattr(memory_store, "INDEX", tmp_path / "memory" / "MEMORY.md")
    yield tmp_path
    shutil.rmtree(tmp_path, ignore_errors=True)


class _Harness(App):
    def __init__(self, session_id: str) -> None:
        super().__init__()
        self.result: str | None = "__unset__"  # type: ignore[assignment]
        self._session_id = session_id

    async def on_mount(self) -> None:
        def _got(slug):
            self.result = slug
            self.exit()

        self.push_screen(ProjectModal(self._session_id), _got)


@pytest.mark.asyncio
async def test_project_modal_creates_new(tmp_root):
    app = _Harness("session-xyz")
    async with app.run_test() as pilot:
        # Focus the new-name input, then type.
        await pilot.press("ctrl+n")
        for ch in "test-proj":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
    assert app.result and "test-proj" in app.result  # slug contains name
    projects = project_store.list_projects()
    assert len(projects) == 1
    assert "session-xyz" in projects[0].session_ids


@pytest.mark.asyncio
async def test_project_modal_cancel(tmp_root):
    app = _Harness("session-xyz")
    async with app.run_test() as pilot:
        await pilot.press("escape")
        await pilot.pause()
    assert app.result is None
    assert project_store.list_projects() == []
