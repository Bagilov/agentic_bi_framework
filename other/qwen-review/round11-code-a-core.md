# Bundle 1: board + spec + layout

==================== FILE: src/agentic_bi/board.py ====================

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
)
from agentic_bi.skeleton import (
    card_visual as _card_visual,
)
from agentic_bi.skeleton import (
    chart_visual as _chart_visual,
)
from agentic_bi.skeleton import (
    layout_from_report as _layout_from_report,
)
from agentic_bi.skeleton import (
    page_filter as _page_filter,
)
from agentic_bi.skeleton import (
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
            item_w = (self.width - 40) // self.cols
            x, y, w, h = _Cursor(
                20, 20, self.width, self.cols, self.row_h, start_index=n
            ).next(item_w, self.row_h)
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


# ─── board ─────────────────────────────────────────────────


class Board:
    """A board = several pages; each page is a set of elements.

    Args:
        table: the columns table (alias "m").
        measure_table: the measures table (optional; measures alias "s").
    """

    def __init__(self, table: str = "fact_table", measure_table: str | None = None):
        self.table = table
        self.measure_table = measure_table
        self.measure_alias = "s" if measure_table else None
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

==================== FILE: src/agentic_bi/spec.py ====================

"""Declarative dashboard model (spec).

Lets you describe a dashboard and its lifecycle USING DATA ONLY (YAML/JSON),
without code: page/element composition, model fields, and — at the pipeline
level — which quality thresholds to apply and how to deploy via a git client.

Format (YAML/JSON):

    dashboard:
      name: "Overview board"
      table: fact_table
      measure_table: kpi_measures   # optional
      pages:
        - name: p1
          title: "Main"
          header: "Dashboard · Overview"       # optional
          filters: [category, metric]  # page-level Categorical filters
          elements:
            - type: kpi
              field: {kind: measure, property: metric_a, display: "Metric A"}
            - type: chart
              visual_type: lineChart           # lineChart | clusteredColumnChart
              axis:   {kind: column,  property: period_start, display: "Period"}
              value:  {kind: measure, property: metric_b,    display: "Metric B"}
            - type: table
              fields:
                - {kind: column,  property: metric, display: "Metric"}
                - {kind: measure, property: metric_a,    display: "Metric A"}
    quality:
      thresholds: {}                           # threshold overrides (see thresholds.py)
    deploy:
      pbirs_sync_config: "git-deploy.yaml"   # git-deploy config
      target_folder: "/Target/Dev"
      branch: "dev"
      dry_run: false
    support:
      agents: []                               # support-agent manifests (see agents.py)
      enable_ids: []                           # enable agents from the registry
      disable_ids: []                          # disable agents from the registry

``spec_to_board()`` translates a spec into a ``Board`` object from ``board.py``;
``to_dict/from_dict``/``load`` provide serialization and structural validation.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

from agentic_bi.board import Board, col, measure

logger = logging.getLogger(__name__)

# element type tags the board builder understands
_ELEMENT_TYPES = {"kpi", "chart", "table"}


def _field_dict(f: dict) -> dict:
    """Normalize a field dict into the board.col()/measure() format.

    The spec is untrusted input, so a malformed field fails here with a message
    naming the offending value, instead of a bare `KeyError`/`AttributeError`
    much later in `spec_to_board`.
    """
    if not isinstance(f, dict):
        raise ValueError(f"a field must be a mapping, got {type(f).__name__}: {f!r}")
    prop = f.get("property")
    if not prop:
        raise ValueError(f"a field must have a 'property' key: {f!r}")
    kind = f.get("kind", "column")
    if kind == "measure":
        return measure(prop, f.get("display"))
    return col(prop, f.get("display"), agg=f.get("agg"))


@dataclass
class ElementSpec:
    """A single visual/element of a page."""

    type: str
    field: dict | None = None
    fields: list[dict] | None = None
    visual_type: str = "lineChart"
    axis: dict | None = None
    value: dict | None = None
    pos: list[int] | None = None  # [x, y, w, h]
    text: str | None = None


@dataclass
class PageSpec:
    """A board page."""

    name: str
    title: str | None = None
    header: str | None = None
    filters: list[str] = field(default_factory=list)
    elements: list[ElementSpec] = field(default_factory=list)


@dataclass
class DashboardSpec:
    """A declarative dashboard specification."""

    name: str
    table: str
    measure_table: str | None = None
    pages: list[PageSpec] = field(default_factory=list)
    quality: dict = field(default_factory=dict)  # {thresholds: {...}}
    deploy: dict = field(default_factory=dict)  # {pbirs_sync_config, ...}
    control: dict = field(default_factory=dict)  # {verify, expected}
    support: dict = field(default_factory=dict)  # {agents, enable_ids, disable_ids}


# ─── parsing ───────────────────────────────────────────────


def _parse_element(e: dict) -> ElementSpec:
    if not isinstance(e, dict):
        raise ValueError(f"an element must be a mapping, got {type(e).__name__}: {e!r}")
    etype = e.get("type", "table")
    if etype not in _ELEMENT_TYPES:
        raise ValueError(
            f"Unknown element type '{etype}'; allowed: {sorted(_ELEMENT_TYPES)}"
        )
    return ElementSpec(
        type=etype,
        field=e.get("field"),
        fields=e.get("fields"),
        visual_type=e.get("visual_type", "lineChart"),
        axis=e.get("axis"),
        value=e.get("value"),
        pos=e.get("pos"),
        text=e.get("text"),
    )


def _parse_page(p: dict) -> PageSpec:
    if not isinstance(p, dict):
        raise ValueError(f"a page must be a mapping, got {type(p).__name__}: {p!r}")
    elements = p.get("elements", []) or []
    if not isinstance(elements, list):
        raise ValueError(f"page '{p.get('name')}': elements must be a list")
    return PageSpec(
        name=p.get("name"),
        title=p.get("title"),
        header=p.get("header"),
        filters=p.get("filters", []) or [],
        elements=[_parse_element(e) for e in elements],
    )


def from_dict(d: dict) -> DashboardSpec:
    """Build a spec from a dict (after YAML/JSON).

    A missing `name` is defaulted to an empty string so `validate_spec` reports
    it as a problem (untrusted input must not crash on a bare `KeyError`).
    """
    dash = d.get("dashboard", d)
    pages = [_parse_page(p) for p in dash.get("pages", []) or []]
    return DashboardSpec(
        name=dash.get("name", ""),
        table=dash.get("table", "fact_table"),
        measure_table=dash.get("measure_table"),
        pages=pages,
        quality=d.get("quality", {}) or {},
        deploy=d.get("deploy", {}) or {},
        control=d.get("control", {}) or {},
        support=d.get("support", {}) or {},
    )


def load(path: Path) -> DashboardSpec:
    """Load a spec from a YAML/JSON file (depends on the extension)."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore

            data = yaml.safe_load(text)
        except ImportError:  # pragma: no cover
            raise RuntimeError(
                "YAML specs need PyYAML: uv pip install pyyaml"
            ) from None
    else:
        data = json.loads(text)
    return from_dict(data)


def to_dict(spec: DashboardSpec) -> dict:
    """Back to a dict (for saving/tests)."""
    return {
        "dashboard": {
            "name": spec.name,
            "table": spec.table,
            "measure_table": spec.measure_table,
            "pages": [asdict(p) for p in spec.pages],
        },
        "quality": spec.quality,
        "deploy": spec.deploy,
        "control": spec.control,
        "support": spec.support,
    }


def to_yaml(spec: DashboardSpec) -> str:
    """Serialize a spec to a YAML string."""
    try:
        import yaml  # type: ignore

        return yaml.safe_dump(to_dict(spec), allow_unicode=True, sort_keys=False)
    except ImportError:  # pragma: no cover
        return json.dumps(to_dict(spec), ensure_ascii=False, indent=2)


# ─── translation to a board ────────────────────────────────


def spec_to_board(spec: DashboardSpec) -> Board:
    """Translate a spec into a ready ``Board`` builder (agentic_bi.board)."""
    board = Board(table=spec.table, measure_table=spec.measure_table)
    for ps in spec.pages:
        page = board.add_page(ps.name, title=ps.title)
        page.filters(ps.filters)
        if ps.header:
            page.header(ps.header)
        for el in ps.elements:
            pos = tuple(el.pos) if el.pos else None
            if el.type == "kpi":
                page.kpi(_field_dict(el.field), pos=pos)
            elif el.type == "chart":
                page.chart(
                    el.visual_type, _field_dict(el.axis), _field_dict(el.value), pos=pos
                )
            elif el.type == "table":
                page.table([_field_dict(f) for f in el.fields], pos=pos)
    return board


def _validate_field(f: dict, where: str, problems: list[str]) -> None:
    """Check one field mapping has a `property` and a sane `kind`."""
    if not isinstance(f, dict):
        problems.append(f"{where}: field must be a mapping, got {type(f).__name__}")
        return
    if not f.get("property"):
        problems.append(f"{where}: field is missing 'property'")
    if f.get("kind", "column") not in ("column", "measure"):
        problems.append(f"{where}: unknown field kind {f.get('kind')!r}")


def _validate_pos(pos: object, where: str, problems: list[str]) -> None:
    """Check `pos` is four integers (a length-2 or string pos breaks the layout)."""
    if pos is None:
        return
    if not isinstance(pos, (list, tuple)) or len(pos) != 4:
        problems.append(f"{where}: pos must be [x, y, w, h], got {pos!r}")
        return
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in pos):
        problems.append(f"{where}: pos values must be integers, got {pos!r}")


def validate_spec(spec: DashboardSpec) -> list[str]:
    """Structural validation of a spec; returns problems (empty = ok).

    Catches the defects that would otherwise surface as a late `KeyError`/
    `TypeError` in `spec_to_board` or as a silently wrong layout: a page or
    element missing a key, a field without `property`, a malformed `pos`, and
    duplicate page names (whose sections collide in the built layout).
    """
    problems: list[str] = []
    if not spec.name:
        problems.append("Missing dashboard.name")
    if not spec.table:
        problems.append("Missing dashboard.table")
    if not spec.pages:
        problems.append("No pages (dashboard.pages) — the board is empty")
    seen_pages: set[str] = set()
    for p in spec.pages:
        if not p.name:
            problems.append("Page without name")
        elif p.name in seen_pages:
            problems.append(f"Duplicate page name '{p.name}'")
        else:
            seen_pages.add(p.name)
        for el in p.elements:
            where = f"{p.name}/{el.type}"
            _validate_pos(el.pos, where, problems)
            if el.type == "kpi":
                if not el.field:
                    problems.append(f"{where}: missing field")
                else:
                    _validate_field(el.field, where, problems)
            elif el.type == "chart":
                if not el.axis or not el.value:
                    problems.append(f"{where}: axis and value are required")
                else:
                    _validate_field(el.axis, f"{where}/axis", problems)
                    _validate_field(el.value, f"{where}/value", problems)
            elif el.type == "table":
                if not el.fields:
                    problems.append(f"{where}: missing fields")
                else:
                    for i, f in enumerate(el.fields):
                        _validate_field(f, f"{where}/field[{i}]", problems)
    return problems


__all__ = [
    "DashboardSpec",
    "PageSpec",
    "ElementSpec",
    "from_dict",
    "load",
    "to_dict",
    "to_yaml",
    "spec_to_board",
    "validate_spec",
]

==================== FILE: src/agentic_bi/engine_layout_visual.py ====================

"""Visual container/config construction for the from-scratch .pbix layout.

Supported visual kinds (see `_VISUAL_TYPES`):
    table matrix card column bar line area pie donut funnel waterfall
    treemap stackedColumn stackedBar scatter gauge kpi slicer

Projection roles follow real Power BI `Report/Layout` conventions:
    cartesian / pie / funnel / waterfall : Category + Y (+ Series)
    treemap                              : Group + Values
    scatter                              : X + Y (+ Size)
    gauge                                : Y
    kpi                                  : Indicator + TrendLine
    table / card / slicer / matrix       : Values (matrix: Rows + Values)

The query primitives (`_col_ref`, `_agg_item`, `_data_query`, ...) live in
`engine_layout_query`; this module owns the `Visual` description, the kind table
and the container assembly.

Public API:
    Visual(kind, table, ...)                       - a visual description
    _VISUAL_TYPES                                  - kind -> QOM visualType
    _visual_config(v) -> dict                      - singleVisual config
    _container(v, x, y, w, h) -> dict              - a visualContainer
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field

from agentic_bi.engine_layout_query import (
    _agg_item,
    _col_item,
    _col_ref,
    _data_query,
    _measure_item,
    _src,
)

logger = logging.getLogger(__name__)

# kind -> QOM visualType
_VISUAL_TYPES = {
    "table": "tableEx",
    "matrix": "pivotTable",
    "card": "card",
    "column": "columnChart",
    "bar": "barChart",
    "line": "lineChart",
    "area": "areaChart",
    "pie": "pieChart",
    "donut": "donutChart",
    "treemap": "treemap",
    "funnel": "funnel",
    "waterfall": "waterfallChart",
    "stackedColumn": "stackedColumnChart",
    "stackedBar": "stackedBarChart",
    "scatter": "scatterChart",
    "gauge": "gauge",
    "kpi": "kpi",
    "slicer": "slicer",
}

# category charts that accept an optional Series breakdown
_SERIES_CHARTS = {"stackedColumn", "stackedBar"}


@dataclass
class Visual:
    """A single visual on a page.

    kind    - one of `_VISUAL_TYPES` (table/matrix/card/column/bar/line/area/
              pie/donut/funnel/waterfall/treemap/stackedColumn/stackedBar/
              scatter/gauge/kpi/slicer)
    table   - the model table name
    columns - a list of columns (table; for matrix - the row hierarchy)
    axis    - the category/axis column (charts), the group column (treemap),
              or the slicer field
    value   - the value column (charts/matrix/gauge/kpi); aggregated by `agg`
    agg     - the value aggregation
    measure - an existing model measure to use as the value instead of
              `value`+`agg` (charts/card/gauge/kpi/matrix/treemap)
    x/y/size- scatter measures (X, Y, bubble Size); aggregated by `agg`
    trend   - KPI trend-axis column
    series  - optional Series breakdown column (stacked charts)
    title   - an optional title
    pos     - an optional position (x, y, w, h)
    """

    kind: str
    table: str
    columns: list[str] = field(default_factory=list)
    axis: str | None = None
    value: str | None = None
    agg: str = "sum"
    measure: str | None = None
    x: str | None = None
    y: str | None = None
    size: str | None = None
    trend: str | None = None
    series: str | None = None
    title: str | None = None
    pos: tuple[int, int, int, int] | None = None

    def __post_init__(self) -> None:
        if self.kind not in _VISUAL_TYPES:
            raise ValueError(f"unknown visual kind: {self.kind}")


def _visual_config(v: Visual) -> dict:
    """Assemble the config of one visualContainer from a Visual description.

    It always builds `projections` - without them Power BI does not bind the
    fields and the visual renders empty.
    """
    src = _src()
    select: list[dict] = []
    order: list[dict] = []
    projections: dict[str, list[dict]] = {}

    def add_column(name: str) -> str:
        item, qref = _col_item(src, v.table, name)
        select.append(item)
        return qref

    def add_agg(prop: str) -> str:
        item, qref = _agg_item(src, v.table, prop, v.agg)
        select.append(item)
        return qref

    def add_measure(name: str) -> str:
        item, qref = _measure_item(src, v.table, name)
        select.append(item)
        return qref

    def add_value() -> str:
        """The value role: an explicit measure, else `value` aggregated by `agg`."""
        if v.measure:
            return add_measure(v.measure)
        return add_agg(v.value)

    if v.kind == "table":
        projections["Values"] = [{"queryRef": add_column(n)} for n in v.columns]
    elif v.kind == "card":
        projections["Values"] = [{"queryRef": add_value()}]
    elif v.kind == "gauge":
        projections["Y"] = [{"queryRef": add_value()}]
    elif v.kind == "kpi":
        projections["Indicator"] = [{"queryRef": add_value()}]
        if v.trend:
            projections["TrendLine"] = [{"queryRef": add_column(v.trend)}]
    elif v.kind == "slicer":
        qref = add_column(v.axis)
        projections["Values"] = [{"queryRef": qref, "active": True}]
        order.append({"Direction": 1, "Expression": _col_ref(src, v.axis)})
    elif v.kind == "matrix":
        row_refs = []
        for d in v.columns:
            dref = add_column(d)
            row_refs.append({"queryRef": dref})
            order.append({"Direction": 1, "Expression": _col_ref(src, d)})
        projections["Rows"] = row_refs
        if v.value:
            projections["Values"] = [{"queryRef": add_value()}]
    elif v.kind == "treemap":
        projections["Group"] = [{"queryRef": add_column(v.axis)}]
        projections["Values"] = [{"queryRef": add_value()}]
    elif v.kind == "scatter":
        projections["X"] = [{"queryRef": add_agg(v.x or v.value)}]
        projections["Y"] = [{"queryRef": add_agg(v.y or v.axis)}]
        if v.size:
            projections["Size"] = [{"queryRef": add_agg(v.size)}]
    else:  # category charts (incl. stacked with optional Series)
        axis_ref = add_column(v.axis)
        val_ref = add_value()
        order.append({"Direction": 1, "Expression": _col_ref(src, v.axis)})
        projections["Category"] = [{"queryRef": axis_ref}]
        projections["Y"] = [{"queryRef": val_ref}]
        if v.series and v.kind in _SERIES_CHARTS:
            projections["Series"] = [{"queryRef": add_column(v.series)}]

    objects = {}
    if v.title:
        objects["title"] = [
            {"properties": {"text": {"expr": {"Literal": {"Value": f"'{v.title}'"}}}}}
        ]
    if v.kind == "slicer":
        objects["data"] = [
            {"properties": {"mode": {"expr": {"Literal": {"Value": "'Dropdown'"}}}}}
        ]
    if v.kind == "matrix":
        objects["rowHeaders"] = [
            {
                "properties": {
                    "stepped": {"expr": {"Literal": {"Value": "true"}}},
                    "steppedLayoutIndentation": {"expr": {"Literal": {"Value": "15D"}}},
                }
            }
        ]

    return {
        "name": str(uuid.uuid4()),
        "layouts": [
            {
                "id": 0,
                "position": {"x": 20, "y": 20, "z": 0, "width": 600, "height": 400},
            }
        ],
        "singleVisual": {
            "visualType": _VISUAL_TYPES[v.kind],
            "projections": projections,
            "prototypeQuery": {
                "Version": 2,
                "From": [{"Name": src, "Entity": v.table, "Type": 0}],
                "Select": select,
                **({"OrderBy": order} if order else {}),
            },
            "drillFilterOtherVisuals": True,
            "objects": objects,
            "vcObjects": {},
        },
        "howCreated": "manual",
    }


def _container(v: Visual, x: int, y: int, w: int, h: int) -> dict:
    """Wrap the visual config into a positioned `visualContainer`."""
    cfg = _visual_config(v)
    for lay in cfg.get("layouts", []):
        lay["position"] = {
            "x": x,
            "y": y,
            "z": 0,
            "width": w,
            "height": h,
            "tabOrder": 0,
        }
        break
    container = {
        "x": x,
        "y": y,
        "z": 0,
        "width": w,
        "height": h,
        "config": json.dumps(cfg, ensure_ascii=False),
        "filters": "[]",
    }
    query = _data_query(cfg.get("singleVisual", {}))
    if query is not None:
        container["query"] = query
        container["dataTransforms"] = "[]"
    return container

==================== FILE: src/agentic_bi/engine_layout_query.py ====================

"""Semantic-query building blocks for a from-scratch `.pbix` layout.

Power BI persists a visual's query in two places: `prototypeQuery` (legacy) inside
`singleVisual`, and a container-level `query` holding a
`SemanticQueryDataShapeCommand` (what current Desktop actually renders from).
Without the latter a data-bound visual renders blank.

This module builds both halves:

* the raw refs - `_col_ref`, `_agg_ref`, `_measure_ref`;
* the `Select` items and the queryRef each projection points at - `_col_item`,
  `_agg_item`, `_measure_item`;
* `_data_query`, which serializes the container-level command.

Aggregation codes/labels mirror the QOM `AggregationFunction` values.

Public API:
    _src() -> str
    _col_ref(src, prop) / _agg_ref(src, prop, agg) / _measure_ref(src, name)
    _col_item(src, table, name) / _agg_item(src, table, prop, agg)
    _measure_item(src, table, name)
    _data_query(single_visual) -> str | None
"""

from __future__ import annotations

import json

# QOM AggregationFunction codes and their display labels.
_AGG_FUNC = {
    "sum": 0,
    "avg": 1,
    "average": 1,
    "count": 2,
    "min": 3,
    "max": 4,
    "count_nonnull": 5,
    "median": 6,
    "stddev": 7,
    "var": 8,
}
_AGG_LABEL = {
    "sum": "Sum",
    "avg": "Avg",
    "average": "Avg",
    "min": "Min",
    "max": "Max",
    "count": "Count",
    "count_nonnull": "Count",
    "median": "Median",
    "stddev": "StDev",
    "var": "Var",
}


def _src() -> str:
    """The source alias inside a visual query (ASCII, safe for all encoders)."""
    return "t"


def _col_ref(src: str, prop: str) -> dict:
    return {"Column": {"Expression": {"SourceRef": {"Source": src}}, "Property": prop}}


def _agg_ref(src: str, prop: str, agg: str) -> dict:
    return {
        "Aggregation": {
            "Expression": _col_ref(src, prop),
            "Function": _AGG_FUNC.get(agg.lower(), 0),
        }
    }


def _measure_ref(src: str, name: str) -> dict:
    return {"Measure": {"Expression": {"SourceRef": {"Source": src}}, "Property": name}}


def _col_item(src: str, table: str, name: str) -> tuple[dict, str]:
    """A `Column` select item; returns (item, queryRef)."""
    qref = f"{table}.{name}"
    return ({**_col_ref(src, name), "Name": qref, "NativeReferenceName": name}, qref)


def _agg_item(src: str, table: str, prop: str, agg: str) -> tuple[dict, str]:
    """An `Aggregation` select item; returns (item, queryRef)."""
    label = _AGG_LABEL.get(agg.lower(), "Sum")
    qref = f"{label}({table}.{prop})"
    return (
        {
            **_agg_ref(src, prop, agg),
            "Name": qref,
            "NativeReferenceName": f"{label} {prop}",
        },
        qref,
    )


def _measure_item(src: str, table: str, name: str) -> tuple[dict, str]:
    """A `Measure` select item; returns (item, queryRef)."""
    qref = f"{table}.{name}"
    return (
        {**_measure_ref(src, name), "Name": qref, "NativeReferenceName": name},
        qref,
    )


def _data_query(single_visual: dict) -> str | None:
    """Serialize the container-level semantic query newer Desktop needs to bind data.

    Power BI Desktop persists the visual query in two places: `prototypeQuery`
    inside `singleVisual` (legacy) and a container-level `query` holding a
    `SemanticQueryDataShapeCommand` (what current Desktop actually renders from).
    Without the latter a data-bound visual renders blank.
    """
    pq = single_visual.get("prototypeQuery")
    if not pq:
        return None
    projections = list(range(len(pq.get("Select", []))))
    return json.dumps(
        {
            "Commands": [
                {
                    "SemanticQueryDataShapeCommand": {
                        "Query": pq,
                        "Binding": {
                            "Primary": {
                                "Groupings": [
                                    {"Projections": projections, "Subtotal": 1}
                                ]
                            },
                            "DataReduction": {
                                "DataVolume": 3,
                                "Primary": {"Window": {"Count": 500}},
                            },
                            "Version": 1,
                        },
                        "ExecutionMetricsKind": 1,
                    }
                }
            ]
        },
        ensure_ascii=False,
    )

==================== FILE: src/agentic_bi/engine_types.py ====================

"""Type inference helpers for the engine data pipeline."""

from __future__ import annotations

import datetime as _dt

_DATE_FORMATS = (
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
    "%d.%m.%Y",
    "%d.%m.%Y %H:%M:%S",
    "%Y/%m/%d",
)


def coerce(v):
    if v is None:
        return None
    if isinstance(v, (int, float, bool)):
        return v
    s = str(v).strip()
    if s == "" or s.lower() in ("na", "nan", "null", "none"):
        return None
    low = s.lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s.replace(",", "") if low.count(",") == 1 else s)
    except ValueError:
        return v


def is_date(v) -> bool:
    if isinstance(v, (_dt.date, _dt.datetime)):
        return True
    if not isinstance(v, str):
        return False
    return any(try_fmt(v, f) for f in _DATE_FORMATS)


def try_fmt(v: str, fmt: str) -> bool:
    try:
        _dt.datetime.strptime(v.strip(), fmt)
        return True
    except ValueError:
        return False


def to_iso(v) -> str:
    if isinstance(v, _dt.datetime):
        return v.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(v, _dt.date):
        return v.strftime("%Y-%m-%d")
    for fmt in _DATE_FORMATS:
        try:
            return _dt.datetime.strptime(str(v).strip(), fmt).strftime(
                "%Y-%m-%dT%H:%M:%S"
            )
        except ValueError:
            continue
    return str(v)


def typed_column(name: str, vals: list) -> dict:
    """Return {name,type,values} with a normalized type."""
    nn = [v for v in vals if v is not None]
    if nn and all(isinstance(v, bool) for v in nn):
        return {
            "name": name,
            "type": "int64",
            "values": [None if v is None else int(v) for v in vals],
        }
    if nn and all(isinstance(v, int) for v in nn):
        return {"name": name, "type": "int64", "values": vals}
    if (
        nn
        and all(isinstance(v, (int, float)) for v in nn)
        and not all(is_date(v) for v in nn)
    ):
        return {"name": name, "type": "double", "values": vals}
    if nn and all(is_date(v) for v in nn):
        return {
            "name": name,
            "type": "date",
            "values": [None if v is None else to_iso(v) for v in vals],
        }
    return {
        "name": name,
        "type": "string",
        "values": [None if v is None else str(v) for v in vals],
    }


==================== FILE: src/agentic_bi/skeleton.py ====================

"""Generator of a "report skeleton for a query" — a PBIP project with visuals and filters.

Idea: a binary VertiPaq DataModel cannot be written from scratch, so the skeleton
is described config-driven in a textual PBIP (report.json + model.bim) and built
programmatically FOR A SPECIFIC QUERY. Folding into a binary .pbix and publishing
are separate steps (rebuild_pbix/publish_pbix).

This module is a **facade** over focused submodules:
    skeleton_visuals.py  - filters + visual builders (format verified on real .pbix)
    skeleton_assembly.py - report.json / model.bim / project files + build_skeleton

Scenario: KPI card (measure), chart (line/column: X axis + value), table
(columns/measures), page-level Categorical filters.
"""

from __future__ import annotations

from agentic_bi.skeleton_assembly import (  # noqa: F401
    build_model,
    build_report,
    build_skeleton,
    layout_from_report,
    main,
)
from agentic_bi.skeleton_visuals import (  # noqa: F401
    COL_AGG_FUNCTION,
    card_visual,
    chart_visual,
    page_filter,
    table_visual,
)
from agentic_bi.skeleton_visuals_extra import (  # noqa: F401
    kpi_band,
    scatter_visual,
    stacked_visual,
    treemap_visual,
)

__all__ = [
    "COL_AGG_FUNCTION",
    "card_visual",
    "chart_visual",
    "kpi_band",
    "page_filter",
    "scatter_visual",
    "stacked_visual",
    "table_visual",
    "treemap_visual",
    "build_model",
    "build_report",
    "build_skeleton",
    "layout_from_report",
    "main",
]

==================== FILE: src/agentic_bi/skeleton_assembly.py ====================

"""Report/model assembly for the PBIP skeleton: report.json, model.bim, files."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from agentic_bi.skeleton_visuals import (
    card_visual,
    chart_visual,
    page_filter,
    table_visual,
)

logger = logging.getLogger(__name__)


def build_report(sections: list[dict]) -> dict:
    """Assemble report.json from lists of sections.

    sections: [{name, displayName, width, height, filters:[page_filter], containers:[visual]}]
    """
    out_sections = []
    for s in sections:
        out_sections.append(
            {
                "name": s["name"],
                "displayName": s["displayName"],
                "filters": json.dumps(s.get("filters", []), ensure_ascii=False),
                "config": json.dumps(
                    {
                        "width": s.get("width", 1280),
                        "height": s.get("height", 800),
                        "background": {"color": "#FFFFFF"},
                    },
                    ensure_ascii=False,
                ),
                "visualContainers": s.get("containers", []),
            }
        )
    return {
        "version": "1.0",
        "config": json.dumps({"theme": "default", "filter": {"filter": None}}),
        "sections": out_sections,
    }


# ─── model ─────────────────────────────────────────────────


def build_model(tables: list[dict]) -> dict:
    """Assemble model.bim (like build._model_bim, but without empty DATATABLE
    partitions when an external source is set; the skeleton uses DATATABLE-empty)."""
    norm = []
    for t in tables or []:
        nt = dict(t)
        if "partitions" not in nt:
            cols = nt.get("columns", [])
            args = ", ".join(
                f'"{c["name"]}", STRING'
                if c.get("dataType") == "string"
                else f'"{c["name"]}", DOUBLE'
                for c in cols
            )
            nt["partitions"] = [
                {
                    "name": f"{t['name']}-1",
                    "mode": "import",
                    "source": {
                        "type": "calculated",
                        "expression": f"DATATABLE({args}, {{}})",
                    },
                }
            ]
        norm.append(nt)
    return {
        "name": "SemanticModel",
        "compatibilityLevel": 1606,
        "model": {
            "culture": "en-US",
            "annotations": [
                {
                    "name": "DefaultMeasureTable",
                    "value": (norm[0]["name"] if norm else "Data"),
                },
                {"name": "defaultPowerBIDataSourceVersion", "value": "powerBI_V3"},
            ],
            "tables": norm,
            "relationships": [],
        },
    }


def build_skeleton(
    out: Path,
    report_name: str,
    display_name: str,
    table: str,
    columns: list[dict],
    measures: list[dict],
    kpi: dict,
    chart_type: str,
    chart_axis: dict,
    chart_value: dict,
    table_fields: list[dict],
    filter_columns: list[str],
    page_name: str = "Page 1",
    measure_table: str | None = None,
) -> Path:
    """Build the query-driven PBIP skeleton project and return the .pbir path.

    Args:
        out: the project folder (created).
        report_name: the project name (for <name>.pbir / .Report / .Semantic).
        display_name: the page display name.
        table: the model table name.
        columns/measures: the model (as in build._model_bim).
        kpi: the field for the KPI card {"kind","property","display"}.
        chart_type: "lineChart" | "clusteredColumnChart".
        chart_axis/chart_value: the chart fields.
        table_fields: the table fields.
        filter_columns: columns for page-level Categorical filters.
        page_name: the section name.
        measure_table: if set - measures come from this table (alias "s") while
            columns come from `table`. As in the donor (measures in a separate table).
    """
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)

    # model
    measure_alias = "s" if measure_table else None
    model_tables = [
        {
            "name": table,
            "columns": columns,
            "measures": measures if not measure_table else [],
        }
    ]
    if measure_table:
        model_tables.append(
            {
                "name": measure_table,
                "columns": [],
                "measures": measures,
            }
        )
    model = build_model(model_tables)

    # visuals
    kpi_visual = card_visual(
        kpi, table, measure_table=measure_table, measure_alias=measure_alias
    )
    chart_visual_obj = chart_visual(
        chart_type,
        chart_axis,
        chart_value,
        table,
        measure_table=measure_table,
        measure_alias=measure_alias,
    )
    table_visual_obj = table_visual(
        table_fields, table, measure_table=measure_table, measure_alias=measure_alias
    )

    # page filters
    page_filters = [page_filter(c, table) for c in filter_columns]

    report = build_report(
        [
            {
                "name": page_name,
                "displayName": display_name,
                "width": 1280,
                "height": 800,
                "filters": page_filters,
                "containers": [kpi_visual, chart_visual_obj, table_visual_obj],
            }
        ]
    )

    # write out
    _write(out / f"{report_name}.Report", "report.json", report)
    semantic = out / f"{report_name}.Semantic"
    _write(semantic, "model.bim", model)
    _write(semantic, "definition.pbism", {"version": "1.0"})
    _write(
        out,
        f"{report_name}.pbir",
        {
            "version": "1.0",
            "reportConfig": json.dumps(
                {
                    "config": json.dumps(
                        {"theme": "default", "filter": {"filter": None}}
                    ),
                    "version": "1.0",
                },
                ensure_ascii=False,
            ),
        },
    )

    pbir = out / f"{report_name}.pbir"
    logger.info(
        "Skeleton built: %s (visuals: kpi+chart+table, filters: %s)",
        pbir,
        ", ".join(filter_columns) or "-",
    )
    # layout in .pbix format (for rebuild_pbix(layout=...))
    layout = layout_from_report(report, None)
    return pbir, layout


def layout_from_report(report: dict, base_layout: dict | None = None) -> dict:
    """Convert report.json (PBIP) into the .pbix layout format.

    report: a dict from `build_report`.
    base_layout: the donor layout (for id/filters/resourcePackages/config), from
        rebuild._extract_layout. If None - defaults are used.

    .pbix layout format (verified against a donor): top-level has `id`, `filters`,
    `resourcePackages`, `sections`, `config`, `layoutOptimization`; a section has
    `id`, `name`, `displayName`, `filters`, `ordinal`, `visualContainers`,
    `config`, `displayOption`, `width`, `height`.
    """
    base = base_layout or {}
    layout = {
        "id": base.get("id", 0),
        "filters": "[]",
        "resourcePackages": base.get("resourcePackages", []),
        "config": base.get(
            "config",
            '{"version":"5.54","themeCollection":{"baseTheme":{"name":"CY24SU05","version":"5.38","compatVersion":5}}}',
        ),
        "layoutOptimization": base.get("layoutOptimization", 0),
    }
    sections = []
    for i, sec in enumerate(report.get("sections", [])):
        sections.append(
            {
                "id": sec.get("id", f"ReportSection{i}"),
                "name": sec.get("name", f"ReportSection{i}"),
                "displayName": sec.get("displayName", "Page"),
                "filters": sec.get("filters", "[]"),
                "ordinal": i,
                "visualContainers": sec.get(
                    "containers", sec.get("visualContainers", [])
                ),
                "config": sec.get("config", ""),
                "displayOption": 1,
                "width": sec.get("width", 1280),
                "height": sec.get("height", 800),
            }
        )
    layout["sections"] = sections
    return layout


def _write(base: Path, name: str, data: dict) -> None:
    base.mkdir(parents=True, exist_ok=True)
    (base / name).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    # Example: a "behavior by groups" skeleton
    out = Path(__file__).parent / "output_files" / "skel_behavior"
    table = "Data"
    columns = [
        {"name": "segment", "dataType": "string"},
        {"name": "period_start", "dataType": "datetime"},
        {"name": "target", "dataType": "decimal"},
        {"name": "score", "dataType": "decimal"},
        {"name": "cnt", "dataType": "integer"},
    ]
    measures = [
        {"name": "TotalTarget", "expression": "SUM('Data'[target])"},
        {"name": "AvgScore", "expression": "AVERAGE('Data'[score])"},
        {"name": "Count", "expression": "COUNTROWS('Data')"},
    ]
    build_skeleton(
        out=out,
        report_name="skel_behavior",
        display_name="Behavior by groups",
        table=table,
        columns=columns,
        measures=measures,
        kpi={"kind": "measure", "property": "TotalTarget", "display": "Total target"},
        chart_type="lineChart",
        chart_axis={"kind": "column", "property": "period_start", "display": "Period"},
        chart_value={
            "kind": "measure",
            "property": "AvgScore",
            "display": "Average score",
        },
        table_fields=[
            {"kind": "column", "property": "segment", "display": "Segment"},
            {"kind": "measure", "property": "TotalTarget", "display": "Target"},
            {"kind": "measure", "property": "Count", "display": "Records"},
        ],
        filter_columns=["segment", "period_start"],
    )
    print("Done:", out)


if __name__ == "__main__":
    main()

==================== FILE: src/agentic_bi/board_fake.py ====================

"""Build and publish a sample board over real objects of the donor model.

The board is built config-driven (skeleton) and references EXISTING objects of
the donor's binary model (table fact_table, measures in kpi_measures,
columns period_start/metric/...), so it renders real data.

Steps:
  1. build_skeleton -> PBIP skeleton (KPI + chart + table + filters).
  2. layout_from_report -> layout in .pbix format.
  3. rebuild_pbix(src, out, layout=...) -> binary .pbix (DataModel from donor).
  4. publish_pbix -> publish to a Report Server.

Usage:
  uv run python -m agentic_bi.board_fake --src data/donor.pbix
  uv run python -m agentic_bi.board_fake --src data/donor.pbix --dry-run
  uv run python -m agentic_bi.board_fake --src data/donor.pbix --server host --folder /Target/Dev
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from agentic_bi.automate import verify_published
from agentic_bi.publish import publish_pbix
from agentic_bi.rebuild import _extract_layout, rebuild_pbix
from agentic_bi.skeleton import build_skeleton
from agentic_bi.validate_pbix import validate_pbix

logger = logging.getLogger(__name__)

BOARD_NAME = "sample_board"
TARGET_FOLDER = "/Target/Dev"
DONOR = "data/donor.pbix"

# Real objects of the donor model (table columns, measures).
TABLE = "fact_table"
MEASURE_TABLE = "kpi_measures"
MEASURES = [
    {"name": "metric_a", "expression": ""},
    {"name": "metric_b", "expression": ""},
]


def build_and_publish(
    src: str | Path = DONOR,
    server: str = "",
    folder: str = TARGET_FOLDER,
    dry_run: bool = False,
) -> dict:
    src = Path(src)
    out = Path(__file__).parent / "output_files" / f"{BOARD_NAME}.pbix"

    # These measures/columns already exist in the donor's binary model.
    columns = [
        {"name": "metric", "dataType": "string"},
        {"name": "period_start", "dataType": "datetime"},
        {"name": "segment", "dataType": "string"},
        {"name": "category", "dataType": "string"},
    ]

    skel_dir = out.parent / "skel_fake"
    _, layout = build_skeleton(
        out=skel_dir,
        report_name="skel_fake",
        display_name=BOARD_NAME,
        table=TABLE,
        columns=columns,
        measures=MEASURES,
        measure_table=MEASURE_TABLE,
        kpi={"kind": "measure", "property": "metric_a", "display": "Metric A"},
        chart_type="lineChart",
        chart_axis={"kind": "column", "property": "period_start", "display": "Period"},
        chart_value={"kind": "measure", "property": "metric_b", "display": "Metric B"},
        table_fields=[
            {"kind": "column", "property": "metric", "display": "Metric"},
            {"kind": "measure", "property": "metric_a", "display": "Metric A"},
            {"kind": "measure", "property": "metric_b", "display": "Metric B"},
        ],
        filter_columns=["category", "metric"],
    )

    # Enrich the layout with real resourcePackages/config from the donor (for
    # correct rendering of charts/tables), keeping our objects.
    base_layout, _ = _extract_layout(src)
    # do not override sections — only packages/config/themes from the donor
    if base_layout.get("resourcePackages"):
        layout["resourcePackages"] = base_layout["resourcePackages"]
    if base_layout.get("config"):
        layout["config"] = base_layout["config"]

    logger.info("Folding into .pbix: %s", out)
    out = rebuild_pbix(src, out, layout=layout)
    result = {"built": {"path": str(out), "size": out.stat().st_size}}

    # Validate the produced .pbix against the donor model BEFORE publishing.
    problems = validate_pbix(out)
    result["validate"] = {"ok": not problems, "problems": problems}
    if problems:
        logger.error(
            "%d layout problems (not publishing):\n- %s",
            len(problems),
            "\n- ".join(problems),
        )
        raise RuntimeError(f"layout does not match the donor model: {problems}")

    if dry_run:
        result["publish"] = {"skipped": "dry-run"}
        return result

    if not server:
        result["publish"] = {"skipped": "no server configured"}
        return result

    cfg = {
        "server": server,
        "base_path": "/reportserver",
        "api_prefix": "/api/v2.0",
        "timeout": 300,
    }
    res = publish_pbix(out, BOARD_NAME, folder, cfg)
    result["publish"] = res
    result["verify"] = verify_published(
        server, folder, BOARD_NAME, base="/reportserver", api="/api/v2.0"
    )
    return result


def main() -> None:
    p = argparse.ArgumentParser(description="Board over real donor-model objects")
    p.add_argument("--src", default=DONOR, help="donor .pbix")
    p.add_argument("--server", default="", help="Report Server host (for publishing)")
    p.add_argument("--folder", default=TARGET_FOLDER, help="target folder")
    p.add_argument(
        "--dry-run", action="store_true", help="build only, without publishing"
    )
    p.add_argument("--verbose", action="store_true")
    a = p.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if a.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )
    res = build_and_publish(
        src=a.src, server=a.server, folder=a.folder, dry_run=a.dry_run
    )
    print("\n=== RESULT ===")
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
