"""Project + memory store tests. Uses an isolated ROOT so they don't touch
the user's real ~/.sense-use/."""

import shutil

import pytest

from sense_use.store import memory_store, project_store, session_store


@pytest.fixture
def tmp_root(tmp_path, monkeypatch):
    monkeypatch.setattr(session_store, "ROOT", tmp_path)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(memory_store, "MEM_DIR", tmp_path / "memory")
    monkeypatch.setattr(memory_store, "INDEX", tmp_path / "memory" / "MEMORY.md")
    yield tmp_path
    shutil.rmtree(tmp_path, ignore_errors=True)


def test_project_create_and_archive(tmp_root):
    p = project_store.create_project("行思家政", tags=["家政"])
    assert p.slug == "行思家政"
    assert (tmp_root / "projects" / "行思家政.json").exists()

    project_store.archive_session(p.slug, "sess-abc")
    project_store.archive_session(p.slug, "sess-abc")  # idempotent
    reloaded = project_store.get_project(p.slug)
    assert reloaded.session_ids == ["sess-abc"]


def test_project_list_sorted(tmp_root):
    project_store.create_project("a")
    project_store.create_project("b")
    names = [p.name for p in project_store.list_projects()]
    assert set(names) == {"a", "b"}


def test_project_slug_dedup(tmp_root):
    p1 = project_store.create_project("dup")
    p2 = project_store.create_project("dup")
    assert p1.slug != p2.slug


def test_memory_write_and_index(tmp_root):
    entry = memory_store.write_memory(
        "hello.md",
        "# Hello\n\nContent here.\n",
        title="Hello Memo",
        hook="first test entry",
    )
    assert entry.title == "Hello Memo"
    idx = (tmp_root / "memory" / "MEMORY.md").read_text()
    assert "- [Hello Memo](hello.md) — first test entry" in idx

    entries = memory_store.list_memories()
    assert len(entries) == 1
    assert entries[0].filename == "hello.md"
    assert entries[0].hook == "first test entry"


def test_memory_read_and_overwrite_no_dup_index(tmp_root):
    memory_store.write_memory("m.md", "v1", title="M", hook="h")
    memory_store.write_memory("m.md", "v2")  # overwrite; no index change
    assert memory_store.read_memory("m.md") == "v2"
    idx = (tmp_root / "memory" / "MEMORY.md").read_text()
    assert idx.count("(m.md)") == 1


def test_memory_delete(tmp_root):
    memory_store.write_memory("gone.md", "x", title="Gone", hook="")
    assert memory_store.delete_memory("gone.md") is True
    assert memory_store.list_memories() == []
    assert not (tmp_root / "memory" / "gone.md").exists()


def test_memory_update_index_line(tmp_root):
    memory_store.write_memory("u.md", "v", title="Old", hook="old hook")
    memory_store.update_index_line("u.md", "New", "new hook")
    idx = (tmp_root / "memory" / "MEMORY.md").read_text()
    assert "New](u.md) — new hook" in idx
    assert "Old" not in idx
