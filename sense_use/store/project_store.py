"""Project store — `~/.sense-use/projects/<slug>.json`.

A project bundles multiple sessions plus optional memory pointers. Nothing
here talks to a DB — everything is a plain JSON file, git-friendly and
inspectable with `cat`.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from sense_use.store.session_store import ROOT

PROJECTS_DIR = ROOT / "projects"


@dataclass
class Project:
    id: str
    name: str
    slug: str
    created_at: str
    tags: list[str] = field(default_factory=list)
    session_ids: list[str] = field(default_factory=list)
    memory_files: list[str] = field(default_factory=list)
    notes: str = ""


def _slugify(name: str) -> str:
    # Keep CJK; strip filesystem-hostile chars; collapse whitespace.
    s = re.sub(r"[\s/\\:*?\"<>|]+", "-", name.strip())
    return s.strip("-") or "untitled"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _ensure_dir() -> None:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)


def _path(slug: str) -> Path:
    return PROJECTS_DIR / f"{slug}.json"


def create_project(name: str, tags: list[str] | None = None) -> Project:
    _ensure_dir()
    slug = _slugify(name)
    # Disambiguate if the slug already exists.
    path = _path(slug)
    if path.exists():
        slug = f"{slug}-{uuid.uuid4().hex[:6]}"
        path = _path(slug)
    proj = Project(
        id=uuid.uuid4().hex,
        name=name,
        slug=slug,
        created_at=_now(),
        tags=tags or [],
    )
    path.write_text(json.dumps(asdict(proj), ensure_ascii=False, indent=2))
    return proj


def list_projects() -> list[Project]:
    _ensure_dir()
    out: list[Project] = []
    for f in sorted(PROJECTS_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text())
            out.append(Project(**data))
        except (OSError, ValueError, TypeError):
            continue
    out.sort(key=lambda p: p.created_at, reverse=True)
    return out


def get_project(slug: str) -> Project | None:
    p = _path(slug)
    if not p.exists():
        return None
    return Project(**json.loads(p.read_text()))


def save(project: Project) -> None:
    _ensure_dir()
    _path(project.slug).write_text(
        json.dumps(asdict(project), ensure_ascii=False, indent=2)
    )


def archive_session(slug: str, session_id: str) -> Project:
    proj = get_project(slug)
    if proj is None:
        raise KeyError(f"project {slug!r} not found")
    if session_id not in proj.session_ids:
        proj.session_ids.append(session_id)
        save(proj)
    return proj


def delete_project(slug: str) -> bool:
    p = _path(slug)
    if not p.exists():
        return False
    p.unlink()
    return True
