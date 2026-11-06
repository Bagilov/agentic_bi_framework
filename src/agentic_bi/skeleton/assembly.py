"""Report/model assembly for the PBIP skeleton: report.json, model.bim, files."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import agentic_bi.paths as paths
from agentic_bi.skeleton.report_model import (
    build_model,
    build_report,
    layout_from_report,
)
from agentic_bi.skeleton.visuals import (
    card_visual,
    chart_visual,
    page_filter,
    table_visual,
)

logger = logging.getLogger(__name__)

__all__ = [
    "build_model",
    "build_report",
    "build_skeleton",
    "layout_from_report",
    "main",
]


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
) -> tuple[Path, dict]:
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


def _write(base: Path, name: str, data: dict) -> None:
    base.mkdir(parents=True, exist_ok=True)
    (base / name).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    # Example: a "behavior by groups" skeleton
    out = paths.output_dir("skel_behavior")
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
