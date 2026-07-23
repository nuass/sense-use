"""Memory store — Markdown files under `~/.sense-use/memory/` with a
`MEMORY.md` index that acts as a hand-editable table of contents.

The index format mirrors the Claude Code convention:

    - [Title](file.md) — one-line description
    - [Another](other.md) — hook sentence

Reading the index yields ``MemoryEntry`` objects; writing a new memory
appends a line to MEMORY.md automatically.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from sense_use.store.session_store import ROOT

MEM_DIR = ROOT / "memory"
INDEX = MEM_DIR / "MEMORY.md"


@dataclass
class MemoryEntry:
    filename: str
    title: str
    hook: str

    @property
    def path(self) -> Path:
        return MEM_DIR / self.filename


_LINE_RE = re.compile(r"^\s*-\s*\[(?P<title>[^\]]+)\]\((?P<file>[^)]+)\)\s*(?:[—-]\s*(?P<hook>.*))?$")


def _ensure_dir() -> None:
    MEM_DIR.mkdir(parents=True, exist_ok=True)
    if not INDEX.exists():
        INDEX.write_text("# sense-use memory index\n\n", encoding="utf-8")


def list_memories() -> list[MemoryEntry]:
    _ensure_dir()
    out: list[MemoryEntry] = []
    for raw in INDEX.read_text(encoding="utf-8").splitlines():
        m = _LINE_RE.match(raw)
        if not m:
            continue
        out.append(
            MemoryEntry(
                filename=m.group("file"),
                title=m.group("title"),
                hook=(m.group("hook") or "").strip(),
            )
        )
    return out


def read_memory(filename: str) -> str:
    path = MEM_DIR / filename
    if not path.exists():
        raise FileNotFoundError(filename)
    return path.read_text(encoding="utf-8")


def write_memory(filename: str, content: str, title: str | None = None, hook: str = "") -> MemoryEntry:
    """Create or overwrite a memory file. If `title` is given and the file is
    new, append a bullet to MEMORY.md."""
    _ensure_dir()
    path = MEM_DIR / filename
    is_new = not path.exists()
    path.write_text(content, encoding="utf-8")

    if is_new and title:
        line = f"- [{title}]({filename})" + (f" — {hook}" if hook else "")
        with INDEX.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    return MemoryEntry(filename=filename, title=title or filename, hook=hook)


def update_index_line(filename: str, title: str, hook: str) -> None:
    """Rewrite the MEMORY.md line for ``filename``, or append if missing."""
    _ensure_dir()
    new_line = f"- [{title}]({filename})" + (f" — {hook}" if hook else "")
    lines = INDEX.read_text(encoding="utf-8").splitlines()
    updated: list[str] = []
    found = False
    for raw in lines:
        m = _LINE_RE.match(raw)
        if m and m.group("file") == filename:
            updated.append(new_line)
            found = True
        else:
            updated.append(raw)
    if not found:
        updated.append(new_line)
    INDEX.write_text("\n".join(updated) + "\n", encoding="utf-8")


def delete_memory(filename: str) -> bool:
    path = MEM_DIR / filename
    if not path.exists():
        return False
    path.unlink()
    # Drop the matching index line.
    lines = INDEX.read_text(encoding="utf-8").splitlines()
    kept = [
        raw
        for raw in lines
        if not (
            (m := _LINE_RE.match(raw)) is not None and m.group("file") == filename
        )
    ]
    INDEX.write_text("\n".join(kept) + "\n", encoding="utf-8")
    return True
