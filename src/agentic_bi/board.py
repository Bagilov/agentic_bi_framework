"""Declarative board (Power BI dashboard) builder from elements.

A thin layer over `agentic_bi.skeleton`: provides a high-level API to assemble a
board from the core elements (KPI, chart, table, slicer/filter, text header) and
multiple pages, composing the existing skeleton visual builders (no duplicated
format logic).

Example:

    from pathlib import Path
    from agentic_bi.board import Board, col, measure

    board = Board(table="Data", measure_table="Measures")
    p1 = board.add_page("p1", "Main")
    p1.header("Dashboard · Overview")
    p1.kpi(measure("metric_a", "Metric A"))
    p1.kpi(measure("metric_b", "Metric B"))
    p1.chart("lineChart",
             axis=col("period_start", "Period"),
             value=measure("metric_b", "Metric B"))
    p1.filters(["category", "metric"])
    p2 = board.add_page("p2", "Details")
    p2.table([col("metric", "Metric"),
              measure("metric_a", "Metric A"),
              measure("metric_b", "Metric B")])

    report = board.build_report()          # dict report.json (PBIP)
    layout = board.layout()                # dict layout format of .pbix
    board.rebuild(Path("donor.pbix"), Path("output_files/board.pbix"))

Positioning is automatic: page elements are laid out on a grid (rows). An
explicit position can be set via `pos=(x, y, w, h)`.

This module owns the fields (`col`/`measure`), the board itself (pages, report and
layout assembly) and the single-page shortcut; a page's element accumulation and
placement live in `agentic_bi.board_page` and are re-exported here as `PageView`.

Public API:
    Board / PageView, col(), measure(), build_board()
"""

from __future__ import annotations

import logging
from pathlib import Path

from agentic_bi import settings
from agentic_bi.board_page import PageView
from agentic_bi.board_page import (
    _Cursor as _Cursor,
)
from agentic_bi.board_page import (
    _set_position as _set_position,
)
from agentic_bi.skeleton import (
    build_report as _build_report,
)
from agentic_bi.skeleton import (
    layout_from_report as _layout_from_report,
)

logger = logging.getLogger(__name__)

# ─── fields ────────────────────────────────────────────────


def col(name: str, display: str | None = None, agg: str | None = None) -> dict:
    """A model column field.

    Args:
        name: object name in the model (e.g. "period_start").
        display: label in the visual (defaults to name).
        agg: aggregation (e.g. "Sum"/"Count") if an aggregated column is needed.
    """
    f: dict = {"kind": "column", "property": name, "display": display or name}
    if agg:
        f["agg"] = agg
    return f


def measure(name: str, display: str | None = None) -> dict:
    """A model measure field."""
    return {"kind": "measure", "property": name, "display": display or name}


# ─── board ─────────────────────────────────────────────────


class Board:
    """A board = several pages; each page is a set of elements.

    Args:
        table: the columns table (alias "m"); ``None`` resolves from
            ``agentic_bi.settings`` (environment or neutral default).
        measure_table: the measures table (optional; measures alias "s");
            ``None`` resolves from ``agentic_bi.settings``.
    """

    def __init__(self, table: str | None = None, measure_table: str | None = None):
        names = settings.resolve_model(table=table, measure_table=measure_table)
        self.table = names.table
        self.measure_table = names.measure_table
        self.measure_alias = "s" if names.measure_table else None
        self.pages: list[PageView] = []
        self._name_counter = 0

    def _next_name(self) -> int:
        self._name_counter += 1
        return self._name_counter

    def add_page(
        self,
        name: str,
        title: str | None = None,
        width: int = 1280,
        height: int = 800,
        cols: int = 2,
        row_h: int = 320,
    ) -> PageView:
        """Add a page and return its view for populating with elements."""
        page = PageView(self, name, title, width, height, cols, row_h)
        self.pages.append(page)
        return page

    def build_report(self) -> dict:
        """Assemble report.json (PBIP) for all pages."""
        return _build_report([p.section() for p in self.pages])

    def layout(self, base_layout: dict | None = None) -> dict:
        """Assemble the layout format of .pbix for rebuild_pbix(layout=...)."""
        return _layout_from_report(self.build_report(), base_layout)

    def rebuild(self, src: Path, out: Path, base_layout: dict | None = None) -> Path:
        """Fold the board into a binary .pbix (layout replaced, DataModel from src).

        Requires `agentic_bi.rebuild.rebuild_pbix` and an existing donor `src`.
        """
        from agentic_bi.rebuild import rebuild_pbix

        return rebuild_pbix(src, out, layout=self.layout(base_layout))

    def visuals(self) -> list[dict]:
        """A flat list of visual containers across all pages (for validation)."""
        return [c for p in self.pages for c in p.elements]


def build_board(
    *,
    table: str,
    kpi_field: dict,
    chart_type: str,
    chart_axis: dict,
    chart_value: dict,
    table_fields: list[dict],
    filter_columns: list[str],
    measure_table: str | None = None,
    page_name: str = "Page 1",
    header: str | None = None,
) -> Board:
    """A typical single-page board (KPI + chart + table + filters).

    Pass fields via `col()` / `measure()`.
    """
    board = Board(table=table, measure_table=measure_table)
    page = board.add_page(page_name, title=page_name)
    if header:
        page.header(header)
    page.kpi(kpi_field)
    page.chart(chart_type, chart_axis, chart_value)
    page.table(table_fields)
    page.filters(filter_columns)
    return board


__all__ = ["Board", "PageView", "col", "measure", "build_board"]
