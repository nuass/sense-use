"""MemoryTree — sidebar widget listing all memory entries from MEMORY.md.

Emits a ``MemorySelected`` message when the user picks an entry (Enter / click).
The parent app handles the message by pushing ``MemoryModal``.
"""

from __future__ import annotations

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import ListItem, ListView, Static

from sense_use.store import memory_store


class MemoryTree(Vertical):
    """Vertical stack: header + scrollable list of memory entries."""

    DEFAULT_CSS = """
    MemoryTree { height: 1fr; }
    MemoryTree > Static.header { text-style: bold; color: $accent; padding: 0 1; }
    MemoryTree > ListView { height: 1fr; }
    """

    @dataclass
    class MemorySelected(Message):
        filename: str

    def compose(self) -> ComposeResult:
        yield Static("🧠 Memory", classes="header")
        yield ListView(id="memtree-list")

    def on_mount(self) -> None:
        self.refresh_entries()

    def refresh_entries(self) -> None:
        lv = self.query_one("#memtree-list", ListView)
        lv.clear()
        for entry in memory_store.list_memories():
            hook_bit = f"  [dim]{entry.hook}[/dim]" if entry.hook else ""
            lv.append(
                ListItem(
                    Static(f"• {entry.title}{hook_bit}", markup=True),
                    id=f"mem-{entry.filename.replace('.', '-')}",
                )
            )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item = event.item
        if item is None or item.id is None or not item.id.startswith("mem-"):
            return
        # Recover filename by matching against known entries — we stripped dots.
        target_id = item.id[len("mem-"):]
        for entry in memory_store.list_memories():
            if entry.filename.replace(".", "-") == target_id:
                self.post_message(self.MemorySelected(entry.filename))
                return
