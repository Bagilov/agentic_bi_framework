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

from agentic_bi.engine.layout_visual import Visual, _container

logger = logging.getLogger(__name__)

_THEME = "CY24SU05"


def build_report(pages: list[tuple[str, list[Visual]]], report_id: int = 0) -> bytes:
    """Return the bytes of `Report/Layout` for pages = [(name, [Visual, ...])].

    At least one page is required: a report with zero sections has no
    `boundSection` for its pod and is not a valid Power BI layout, so an empty
    `pages` is a `ValueError` rather than an `IndexError` further down.
    """
    if not pages:
        raise ValueError("a report needs at least one page")
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
    tables = spec.get("tables") or []
    if not tables:
        raise ValueError("a gallery needs at least one table in the spec")
    table = tables[0]
    return build_report([(page_name, gallery_visuals(table["name"], table["columns"]))])


def build_layout_from_spec(
    spec: dict, visuals: list[Visual] | None = None, page_name: str | None = None
) -> bytes:
    """Assemble a report from the pipeline spec.

    `spec` is the **engine** spec (`{"tables": [{"name", "columns"}]}`, built by
    `engine.EnginePipeline.build_spec`), not the declarative `spec.DashboardSpec`
    (which is turned into a `board.Board`, then a layout, by `spec_to_board`).
    The two are different objects; do not feed one to the other.

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
