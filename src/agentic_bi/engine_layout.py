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
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_THEME = "CY24SU05"

# QOM AggregationFunction codes
_AGG_FUNC = {"sum": 0, "avg": 1, "average": 1, "min": 2, "max": 3, "count": 4,
             "count_nonnull": 5, "median": 6, "stddev": 7, "var": 8}
_AGG_LABEL = {"sum": "Sum", "avg": "Avg", "average": "Avg", "min": "Min",
              "max": "Max", "count": "Count", "count_nonnull": "Count",
              "median": "Median", "stddev": "StDev", "var": "Var"}

_VISUAL_TYPES = {
    "table": "tableEx",
    "matrix": "pivotTable",
    "card": "card",
    "column": "columnChart",
    "bar": "barChart",
    "line": "lineChart",
    "pie": "pieChart",
    "donut": "donutChart",
    "slicer": "slicer",
}



from agentic_bi.engine_layout_visual import (  # noqa: F401
    _AGG_FUNC,
    _AGG_LABEL,
    _VISUAL_TYPES,
    Visual,
    _agg_ref,
    _col_ref,
    _container,
    _src,
    _visual_config,
)
def build_report(pages: list[tuple[str, list[Visual]]],
                 report_id: int = 0) -> bytes:
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
        sections.append({
            "name": uuid.uuid4().hex[:20],
            "displayName": page_name,
            "filters": "[]",
            "ordinal": ordinal,
            "visualContainers": containers,
            "config": json.dumps({"objects": {}, "visibility": 1}),
            "displayOption": 3,
            "width": page_w,
            "height": page_h,
        })
    layout = {
        "id": report_id,
        "resourcePackages": [{
            "resourcePackage": {
                "name": "SharedResources", "type": 2, "disabled": False,
                "items": [{"type": 202, "path": f"BaseThemes/{_THEME}.json",
                           "name": _THEME}],
            }
        }],
        "sections": sections,
        "config": json.dumps({
            "version": "5.54",
            "themeCollection": {"baseTheme": {"name": _THEME,
                                              "version": "5.54", "type": 2}},
            "activeSectionIndex": 0,
            "defaultDrillFilterOtherVisuals": True,
            "linguisticSchemaSyncVersion": 2,
            "settings": {"useNewFilterPaneExperience": True,
                         "allowChangeFilterTypes": True,
                         "useStylableVisualContainerHeader": True,
                         "queryLimitOption": 6, "exportDataMode": 1,
                         "useDefaultAggregateDisplayName": True,
                         "useEnhancedTooltips": True},
            "objects": {"section": [{"properties": {"verticalAlignment": {"expr":
                {"Literal": {"Value": "'Top'"}}}}}],
                "outspacePane": [{"properties": {"expanded": {"expr":
                    {"Literal": {"Value": "false"}}}}}]},
        }),
        "layoutOptimization": 0,
        "pods": [{"name": "Pod", "boundSection": sections[0]["name"],
                  "config": "{}"}],
    }
    return json.dumps(layout, ensure_ascii=False).encode("utf-16-le")


def build_layout(table: str, columns: list[tuple[str, str]],
                 page_name: str | None = None) -> bytes:
    """Compatibility: a single page with a tableEx over `columns`."""
    return build_report([(page_name or table,
                          [Visual("table", table,
                                  columns=[c[0] for c in columns])])])


def _auto_visuals(table: str, cols: list[dict]) -> list[Visual]:
    """Auto-select visuals for a table: table + cards + column + pie."""
    names = [c["name"] for c in cols]
    nums = [c["name"] for c in cols if c.get("type") in ("int64", "double")]
    cats = [c["name"] for c in cols if c.get("type") == "string"]
    visuals = [Visual("table", table, columns=names, title=f"{table} (table)")]
    for n in nums[:2]:
        visuals.append(Visual("card", table, value=n, agg="sum",
                              title=f"Sum {n}"))
    if cats and nums:
        visuals.append(Visual("column", table, axis=cats[0], value=nums[0],
                              agg="sum", title=f"{nums[0]} by {cats[0]}"))
        visuals.append(Visual("pie", table, axis=cats[0], value=nums[0],
                              agg="sum", title=f"{nums[0]} share by {cats[0]}"))
    return visuals


def build_layout_from_spec(spec: dict, visuals: list[Visual] | None = None,
                           page_name: str | None = None) -> bytes:
    """Assemble a report from the pipeline spec.

    With `visuals` they are put on one page; otherwise visuals are auto-selected
    (table + cards + column + pie) for each table.
    """
    if visuals is not None:
        return build_report([(page_name or "Report", visuals)])
    pages = [(page_name or t["name"], _auto_visuals(t["name"], t["columns"]))
             for t in spec["tables"]]
    return build_report(pages)