"""PaneGrid — responsive grid container for N TargetPanes.

Replaces a plain ``Horizontal`` with a fixed-column grid that scales
based on the number of attached panes:

- 1-3 panes  → 1 column  (1xN)
- 4-6 panes  → 2 columns (2x3)
- 7-9 panes  → 3 columns (3x3)
- 10+ panes  → 3 columns (3x4+, scrolls vertically)

The column count is reactive; bumping it triggers a layout refresh via
``grid_size_columns`` in the stylesheet.
"""

from __future__ import annotations

from textual.containers import Grid
from textual.reactive import reactive


def columns_for(n: int) -> int:
    """Pick a column count for ``n`` panes — kept small/simple on purpose.

    The spec is *horizontal* (1 row of N when N≤3, 2 rows when 4-6, 3 rows
    when 7-9). With Textual's Grid we set the column count, rows are
    auto-derived.
    """
    if n <= 0:
        return 1
    if n <= 3:
        return n           # 1 / 2 / 3 panes -> side-by-side
    if n <= 6:
        return 2           # 4-6 panes -> 2 cols × 2-3 rows
    return 3               # 7+ panes -> 3 cols × ceil(N/3) rows


class PaneGrid(Grid):
    """Grid container whose column count is a reactive attribute.

    Children flow in mount order; rows are added automatically by the
    layout engine. Each child stretches to fill its cell (``1fr`` both
    ways) so panes look uniform regardless of count.
    """

    DEFAULT_CSS = """
    PaneGrid {
        width: 1fr;
        height: 1fr;
        layout: grid;
        grid-size-columns: 1;
        grid-gutter: 1 1;
    }
    PaneGrid > TargetPane {
        width: 1fr;
        height: 1fr;
    }
    """

    column_count: reactive[int] = reactive(1)

    def __init__(self, *, initial_columns: int = 1, **kwargs) -> None:
        super().__init__(**kwargs)
        self.column_count = max(1, initial_columns)

    def watch_column_count(self, new: int) -> None:
        # ``grid_size_columns`` is a layout-affecting style; setting it
        # on the live widget is enough — Textual will recompute layout
        # and resize children on the next refresh cycle.
        self.styles.grid_size_columns = new

    def recompute_for(self, child_count: int) -> None:
        """Public helper: snap ``column_count`` to the rule for ``child_count`` panes."""
        self.column_count = columns_for(child_count)
