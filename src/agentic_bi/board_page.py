"""Page view of a declarative board: element accumulation and grid placement.

Split out of `board` (which grew past the file-size budget): a page owns its
elements and page-level filters, places them on the page grid (or at an explicit
position), and assembles one report.json section. `board.Board` composes pages
into a report/layout.

Public API:
    PageView(board, name, title, width, height, cols, row_h)
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from agentic_bi.skeleton import (
    card_visual as _card_visual,
)
from agentic_bi.skeleton import (
    chart_visual as _chart_visual,
)
from agentic_bi.skeleton import (
    page_filter as _page_filter,
)
from agentic_bi.skeleton import (
    table_visual as _table_visual,
)

if TYPE_CHECKING:
    from agentic_bi.board import Board

# ─── layout ────────────────────────────────────────────────


class _Cursor:
    """Streaming layout: elements flow across columns, then down to a new row."""

    def __init__(
        self,
        x0: int,
        y0: int,
        canvas_w: int,
        cols: int,
        row_h: int,
        start_index: int = 0,
    ):
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

    def __init__(
        self,
        board: Board,
        name: str,
        title: str | None,
        width: int,
        height: int,
        cols: int,
        row_h: int,
    ):
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
    def _add(
        self, container: dict, pos: tuple[int, int, int, int] | None = None
    ) -> dict:
        n = len(self.elements)
        if pos is None:
            # Clamp to a positive size: a narrow page (width < 2 * margin) would
            # otherwise emit a negative width into the layout, which the renderer
            # treats as a corrupt position.
            item_w = max((self.width - 40) // self.cols, 1)
            x, y, w, h = _Cursor(
                20, 20, self.width, self.cols, self.row_h, start_index=n
            ).next(item_w, self.row_h)
            x, y = max(x, 0), max(y, 0)
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
            "objects": {
                "general": [
                    {
                        "properties": {
                            "paragraphs": [{"textRuns": [{"value": text}]}],
                            "verticalAlignment": {
                                "expr": {"Literal": {"Value": "'Top'"}}
                            },
                        }
                    }
                ]
            },
        }
        cfg = json.dumps(
            {
                "name": f"Header_{self.board._next_name()}",
                "layouts": [
                    {
                        "id": 0,
                        "position": {
                            "x": 20,
                            "y": 20,
                            "width": self.width - 40,
                            "height": 40,
                            "z": 0,
                        },
                    }
                ],
                "singleVisual": single,
            },
            ensure_ascii=False,
        )
        return self._add({"config": cfg, "filters": "[]", "tabOrder": 0}, pos)

    def kpi(self, field: dict, pos: tuple[int, int, int, int] | None = None) -> dict:
        """A KPI card on a single measure (or aggregated column)."""
        return self._add(
            _card_visual(
                field,
                self.board.table,
                measure_table=self.board.measure_table,
                measure_alias=self.board.measure_alias,
            ),
            pos,
        )

    def chart(
        self,
        visual_type: str,
        axis: dict,
        value: dict,
        pos: tuple[int, int, int, int] | None = None,
    ) -> dict:
        """A chart (lineChart / clusteredColumnChart)."""
        return self._add(
            _chart_visual(
                visual_type,
                axis,
                value,
                self.board.table,
                measure_table=self.board.measure_table,
                measure_alias=self.board.measure_alias,
            ),
            pos,
        )

    def table(
        self, fields: list[dict], pos: tuple[int, int, int, int] | None = None
    ) -> dict:
        """A table from a list of fields."""
        return self._add(
            _table_visual(
                fields,
                self.board.table,
                measure_table=self.board.measure_table,
                measure_alias=self.board.measure_alias,
            ),
            pos,
        )

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


__all__ = ["PageView"]
