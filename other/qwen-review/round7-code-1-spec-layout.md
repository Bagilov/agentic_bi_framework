# Bundle 1: declarative spec -> layout path

Each section is one source file, path relative to repo root.

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
    """Normalize a field dict into the board.col()/measure() format."""
    kind = f.get("kind", "column")
    if kind == "measure":
        return measure(f["property"], f.get("display"))
    return col(f["property"], f.get("display"), agg=f.get("agg"))


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
    return PageSpec(
        name=p.get("name"),
        title=p.get("title"),
        header=p.get("header"),
        filters=p.get("filters", []),
        elements=[_parse_element(e) for e in p.get("elements", [])],
    )


def from_dict(d: dict) -> DashboardSpec:
    """Build a spec from a dict (after YAML/JSON)."""
    dash = d.get("dashboard", d)
    pages = [_parse_page(p) for p in dash.get("pages", [])]
    return DashboardSpec(
        name=dash["name"],
        table=dash.get("table", "fact_table"),
        measure_table=dash.get("measure_table"),
        pages=pages,
        quality=d.get("quality", {}),
        deploy=d.get("deploy", {}),
        control=d.get("control", {}),
        support=d.get("support", {}),
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
            page.header(ps.header, pos=ps.header and None)
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


def validate_spec(spec: DashboardSpec) -> list[str]:
    """Structural validation of a spec; returns problems (empty = ok)."""
    problems: list[str] = []
    if not spec.name:
        problems.append("Missing dashboard.name")
    if not spec.table:
        problems.append("Missing dashboard.table")
    if not spec.pages:
        problems.append("No pages (dashboard.pages) — the board is empty")
    for p in spec.pages:
        if not p.name:
            problems.append("Page without name")
        for el in p.elements:
            if el.type == "kpi" and not el.field:
                problems.append(f"{p.name}/kpi: missing field")
            if el.type == "chart" and (not el.axis or not el.value):
                problems.append(f"{p.name}/chart: axis and value are required")
            if el.type == "table" and not el.fields:
                problems.append(f"{p.name}/table: missing fields")
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

==================== FILE: src/agentic_bi/engine_layout.py ====================

"""Build `Report/Layout` for a `.pbix` assembled from scratch.

Several visual types are supported (donor visuals are not used):
    table   - tableEx with all columns
    matrix  - pivotTable (hierarchical pivot / mindmap tree, stepped)
    card    - KPI card
    column  - column chart (category + value)
    bar     - bar chart
    line    - line chart
    pie     - pie chart
    donut   - donut chart
    slicer  - slicer (dropdown) by a column

Public API:
    Visual(kind, table, columns=..., axis=..., value=..., agg="sum", title=...,
           pos=..., filters=...)
    build_report(pages) -> bytes
    build_layout(table, columns, page_name=None) -> bytes
    build_layout_from_spec(spec, visuals=None, page_name=None) -> bytes

Aggregations (agg): sum, avg, min, max, count, count_nonnull, median, stddev, var.

Visual-level filters (`Visual.filters`) are supported, but the `column IN (...)`
form (Condition.In) is NOT generated: it crashes the pivot serializer on expand
(`visitIn`/`serializeAll`). For a slicer/cross-filter use `slicer` + `matrix` on
the same table.
"""

from __future__ import annotations

import json
import logging
import uuid

from agentic_bi.engine_layout_visual import Visual, _container

logger = logging.getLogger(__name__)

_THEME = "CY24SU05"


def build_report(pages: list[tuple[str, list[Visual]]], report_id: int = 0) -> bytes:
    """Return the bytes of `Report/Layout` for pages = [(name, [Visual, ...])]."""
    sections = []
    for ordinal, (page_name, visuals) in enumerate(pages):
        w, h, cols = 620, 300, 2
        containers = []
        for i, v in enumerate(visuals):
            if v.pos is not None:
                x, y, vw, vh = v.pos
            else:
                x = 20 + (i % cols) * (w + 20)
                y = 20 + (i // cols) * (h + 20)
                vw, vh = w, h
            containers.append(_container(v, x, y, vw, vh))
        page_w = max([1280] + [c["x"] + c["width"] + 20 for c in containers])
        page_h = max([1050] + [c["y"] + c["height"] + 20 for c in containers])
        sections.append(
            {
                "id": uuid.uuid4().int % 100000000,
                "name": uuid.uuid4().hex[:20],
                "displayName": page_name,
                "filters": "[]",
                "ordinal": ordinal,
                "visualContainers": containers,
                "config": json.dumps({"objects": {}, "visibility": 1}),
                "displayOption": 3,
                "width": page_w,
                "height": page_h,
            }
        )
    layout = {
        "id": report_id,
        "resourcePackages": [
            {
                "resourcePackage": {
                    "name": "SharedResources",
                    "type": 2,
                    "disabled": False,
                    "items": [
                        {
                            "type": 202,
                            "path": f"BaseThemes/{_THEME}.json",
                            "name": _THEME,
                        }
                    ],
                }
            }
        ],
        "sections": sections,
        "config": json.dumps(
            {
                "version": "5.54",
                "themeCollection": {
                    "baseTheme": {"name": _THEME, "version": "5.54", "type": 2}
                },
                "activeSectionIndex": 0,
                "defaultDrillFilterOtherVisuals": True,
                "linguisticSchemaSyncVersion": 2,
                "settings": {
                    "useNewFilterPaneExperience": True,
                    "allowChangeFilterTypes": True,
                    "useStylableVisualContainerHeader": True,
                    "queryLimitOption": 6,
                    "exportDataMode": 1,
                    "useDefaultAggregateDisplayName": True,
                    "useEnhancedTooltips": True,
                },
                "objects": {
                    "section": [
                        {
                            "properties": {
                                "verticalAlignment": {
                                    "expr": {"Literal": {"Value": "'Top'"}}
                                }
                            }
                        }
                    ],
                    "outspacePane": [
                        {
                            "properties": {
                                "expanded": {"expr": {"Literal": {"Value": "false"}}}
                            }
                        }
                    ],
                },
            }
        ),
        "layoutOptimization": 0,
        "pods": [{"name": "Pod", "boundSection": sections[0]["name"], "config": "{}"}],
    }
    return json.dumps(layout, ensure_ascii=False).encode("utf-16-le")


def build_layout(
    table: str, columns: list[tuple[str, str]], page_name: str | None = None
) -> bytes:
    """Compatibility: a single page with a tableEx over `columns`."""
    return build_report(
        [
            (
                page_name or table,
                [Visual("table", table, columns=[c[0] for c in columns])],
            )
        ]
    )


def _auto_visuals(table: str, cols: list[dict]) -> list[Visual]:
    """Auto-select visuals for a table: table + cards + column + pie."""
    names = [c["name"] for c in cols]
    nums = [c["name"] for c in cols if c.get("type") in ("int64", "double")]
    cats = [c["name"] for c in cols if c.get("type") == "string"]
    visuals = [Visual("table", table, columns=names, title=f"{table} (table)")]
    for n in nums[:2]:
        visuals.append(Visual("card", table, value=n, agg="sum", title=f"Sum {n}"))
    if cats and nums:
        visuals.append(
            Visual(
                "column",
                table,
                axis=cats[0],
                value=nums[0],
                agg="sum",
                title=f"{nums[0]} by {cats[0]}",
            )
        )
        visuals.append(
            Visual(
                "pie",
                table,
                axis=cats[0],
                value=nums[0],
                agg="sum",
                title=f"{nums[0]} share by {cats[0]}",
            )
        )
    return visuals


def _classify_columns(
    columns: list,
) -> tuple[list[str], list[str], list[str], list[str]]:
    """Split columns (dicts or names) into (names, numeric, categorical, dates)."""
    names: list[str] = []
    nums: list[str] = []
    cats: list[str] = []
    dates: list[str] = []
    for c in columns:
        if isinstance(c, dict):
            n, t = c.get("name"), c.get("type")
        else:
            n, t = c, None
        if not n:
            continue
        names.append(n)
        if t in ("int64", "double"):
            nums.append(n)
        elif t == "date":
            dates.append(n)
        elif t == "string":
            cats.append(n)
    return names, nums, cats, dates


def gallery_visuals(table: str, columns: list) -> list[Visual]:
    """One example of every supported visual kind, laid out as a gallery page.

    Column roles are inferred: numeric -> value, string -> category, date ->
    axis/trend. `columns` may be spec column dicts ({name,type}) or plain names.
    """
    names, nums, cats, dates = _classify_columns(columns)
    num = nums or names
    cat = cats or names
    date = dates or cat
    if not num:
        raise ValueError("gallery_visuals: table has no numeric column for values")
    v1 = num[0]
    v2 = num[1] if len(num) > 1 else num[0]
    c1 = cat[0] if cat else v1
    d1 = date[0] if date else c1

    W, H, GAP, COLS = 600, 320, 40, 4
    specs = [
        Visual("table", table, columns=names, title="tableEx — all columns"),
        Visual(
            "matrix",
            table,
            columns=cat[:2] or [c1],
            value=v1,
            agg="sum",
            title="pivotTable — rows + value",
        ),
        Visual("card", table, value=v1, agg="sum", title="card — Sum"),
        Visual("card", table, value=v1, agg="avg", title="card — Avg"),
        Visual("card", table, value=v1, agg="max", title="card — Max"),
        Visual("card", table, value=v1, agg="count", title="card — Count"),
        Visual("slicer", table, axis=c1, title=f"slicer — {c1}"),
        Visual("column", table, axis=c1, value=v1, title="columnChart"),
        Visual("bar", table, axis=c1, value=v1, title="barChart"),
        Visual("line", table, axis=d1, value=v1, title="lineChart"),
        Visual("area", table, axis=d1, value=v1, title="areaChart"),
        Visual("pie", table, axis=c1, value=v1, title="pieChart"),
        Visual("donut", table, axis=c1, value=v2, title="donutChart"),
        Visual("treemap", table, axis=c1, value=v1, title="treemap"),
        Visual("funnel", table, axis=c1, value=v2, title="funnel"),
        Visual("waterfall", table, axis=c1, value=v1, title="waterfallChart"),
        Visual("stackedColumn", table, axis=c1, value=v1, title="stackedColumnChart"),
        Visual("stackedBar", table, axis=c1, value=v1, title="stackedBarChart"),
        Visual("scatter", table, x=v1, y=v2, title="scatterChart"),
        Visual("gauge", table, value=v1, title="gauge"),
        Visual("kpi", table, value=v1, trend=d1, title="kpi"),
    ]
    for i, vis in enumerate(specs):
        vis.pos = (20 + (i % COLS) * (W + GAP), 20 + (i // COLS) * (H + GAP), W, H)
    return specs


def build_gallery(spec: dict, page_name: str = "Visual Gallery") -> bytes:
    """Single-page gallery of every supported visual kind for the first table."""
    table = spec["tables"][0]
    return build_report([(page_name, gallery_visuals(table["name"], table["columns"]))])


def build_layout_from_spec(
    spec: dict, visuals: list[Visual] | None = None, page_name: str | None = None
) -> bytes:
    """Assemble a report from the pipeline spec.

    With `visuals` they are put on one page; otherwise visuals are auto-selected
    (table + cards + column + pie) for each table.
    """
    if visuals is not None:
        return build_report([(page_name or "Report", visuals)])
    pages = [
        (page_name or t["name"], _auto_visuals(t["name"], t["columns"]))
        for t in spec["tables"]
    ]
    return build_report(pages)

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

