"""Declarative board (Power BI dashboard) builder from elements.

A thin layer over `agentic_bi.skeleton`: provides a high-level API to assemble a
board from the core elements (KPI, chart, table, slicer/filter, text header) and
multiple pages, composing the existing skeleton visual builders (no duplicated
format logic).

Example:

    from pathlib import Path
    from agentic_bi.board import Board, col, measure

    board = Board(table="fact_table", measure_table="kpi_measures")
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
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from agentic_bi.skeleton import (
    build_report as _build_report,
    card_visual as _card_visual,
    chart_visual as _chart_visual,
    layout_from_report as _layout_from_report,
    page_filter as _page_filter,
    table_visual as _table_visual,
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


# ─── layout ────────────────────────────────────────────────


class _Cursor:
    """Streaming layout: elements flow across columns, then down to a new row."""

    def __init__(self, x0: int, y0: int, canvas_w: int, cols: int, row_h: int,
                 start_index: int = 0):
        self.x0 = x0
        self.y0 = y0
        self.canvas_w = canvas_w
        self.cols = max(cols, 1)
        self.row_h = row_h
        self._idx = start_index

    def next(self, w: int, h: int) -> tuple[int, int, int, int]:
        col_w = (self.canvas_w - 2 * self.x0) // self.cols
        c = self._idx % self.cols
        r = self._idx // self.cols
        self._idx += 1
        return (self.x0 + c * col_w, self.y0 + r * self.row_h, w, h)


def _set_position(container: dict, x: int, y: int, w: int, h: int) -> dict:
    """Fit the position (x,y,w,h) into the visual container's config json."""
    cfg = json.loads(container["config"])
    for lay in cfg.get("layouts", []):
        lay["position"] = {"x": x, "y": y, "width": w, "height": h, "z": 0}
        break
    container["config"] = json.dumps(cfg, ensure_ascii=False)
    return container


# ─── page ──────────────────────────────────────────────────


class PageView:
    """A board page: accumulates elements and page-level filters."""

    def __init__(self, board: "Board", name: str, title: str | None,
                 width: int, height: int, cols: int, row_h: int):
        self.board = board
        self.name = name
        self.title = title or name
        self.width = width
        self.height = height
        self.cols = max(cols, 1)
        self.row_h = row_h
        self.elements: list[dict] = []
        self._filters: list[dict] = []

    # ── internal ──
    def _add(self, container: dict,
             pos: tuple[int, int, int, int] | None = None) -> dict:
        n = len(self.elements)
        if pos is None:
            item_w = (self.width - 40) // self.cols
            x, y, w, h = _Cursor(20, 20, self.width, self.cols, self.row_h,
                                 start_index=n).next(item_w, self.row_h)
        else:
            x, y, w, h = pos
        _set_position(container, x, y, w, h)
        self.elements.append(container)
        return container

    # ── board elements ──
    def header(self, text: str, pos: tuple[int, int, int, int] | None = None) -> dict:
        """A section text header (textbox)."""
        single = {
            "visualType": "textbox",
            "title": text,
            "objects": {"general": [{"properties": {
                "paragraphs": [{"textRuns": [{"value": text}]}],
                "verticalAlignment": {"expr": {"Literal": {"Value": "'Top'"}}},
            }}]},
        }
        cfg = json.dumps({
            "name": f"Header_{self.board._next_name()}",
            "layouts": [{"id": 0, "position": {"x": 20, "y": 20, "width": self.width - 40,
                                               "height": 40, "z": 0}}],
            "singleVisual": single,
        }, ensure_ascii=False)
        return self._add({"config": cfg, "filters": "[]", "tabOrder": 0}, pos)

    def kpi(self, field: dict, pos: tuple[int, int, int, int] | None = None) -> dict:
        """A KPI card on a single measure (or aggregated column)."""
        return self._add(_card_visual(field, self.board.table,
                                      measure_table=self.board.measure_table,
                                      measure_alias=self.board.measure_alias),
                         pos)

    def chart(self, visual_type: str, axis: dict, value: dict,
              pos: tuple[int, int, int, int] | None = None) -> dict:
        """A chart (lineChart / clusteredColumnChart)."""
        return self._add(_chart_visual(visual_type, axis, value, self.board.table,
                                       measure_table=self.board.measure_table,
                                       measure_alias=self.board.measure_alias),
                         pos)

    def table(self, fields: list[dict],
              pos: tuple[int, int, int, int] | None = None) -> dict:
        """A table from a list of fields."""
        return self._add(_table_visual(fields, self.board.table,
                                       measure_table=self.board.measure_table,
                                       measure_alias=self.board.measure_alias),
                         pos)

    def filters(self, columns: list[str]) -> None:
        """Add page-level filters on columns (Categorical)."""
        for c in columns:
            self._filters.append(_page_filter(c, self.board.table))

    @property
    def page_filters(self) -> list[dict]:
        """The list of added page-level filters (data)."""
        return list(self._filters)

    # ── section assembly ──
    def section(self) -> dict:
        """The section (report.json) with all elements and page filters."""
        return {
            "name": self.name,
            "displayName": self.title,
            "width": self.width,
            "height": self.height,
            "filters": list(self._filters),
            "containers": list(self.elements),
        }


# ─── board ─────────────────────────────────────────────────


class Board:
    """A board = several pages; each page is a set of elements.

    Args:
        table: the columns table (alias "m").
        measure_table: the measures table (optional; measures alias "s").
    """

    def __init__(self, table: str = "fact_table",
                 measure_table: str | None = None):
        self.table = table
        self.measure_table = measure_table
        self.measure_alias = "s" if measure_table else None
        self.pages: list[PageView] = []
        self._name_counter = 0

    def _next_name(self) -> int:
        self._name_counter += 1
        return self._name_counter

    def add_page(self, name: str, title: str | None = None,
                 width: int = 1280, height: int = 800,
                 cols: int = 2, row_h: int = 320) -> PageView:
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

    def rebuild(self, src: Path, out: Path,
                base_layout: dict | None = None) -> Path:
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