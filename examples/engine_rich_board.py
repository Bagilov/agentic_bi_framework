"""Build an enriched one-table board: many visual kinds + DAX measures.

This is the "stage 2" companion to ``engine_table_board.py`` (the simple
single-table board). Same engine path, but the model gets measures and the page
gets a spread of semantically appropriate visuals.

Windows (interactive session):

    python examples/engine_rich_board.py --data examples/engine_sales.csv \
        --table Sales --out "%USERPROFILE%\\Desktop\\sales_rich_board.pbix"

macOS with a prebuilt model:

    python examples/engine_rich_board.py --data examples/engine_sales.csv \
        --table Sales --datamodel model.abf --template templates/template.pbix \
        --out output_files/sales_rich_board.pbix
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

from agentic_bi.engine import DEFAULT_TEMPLATE, PBI_RS, EnginePipeline
from agentic_bi.engine import container as engine_container
from agentic_bi.engine import layout as engine_layout
from agentic_bi.engine.layout import Visual

# Measures are added to the model next to the columns. Keep them meaningful for
# the numeric columns of the table (adjust names/expressions per data set).
MEASURES = [
    ("Total Amount", "SUM(Sales[amount])"),
    ("Total Qty", "SUM(Sales[qty])"),
    ("Orders", "COUNTROWS(Sales)"),
    ("Avg Amount", "AVERAGE(Sales[amount])"),
    ("Amount per Unit", "DIVIDE(SUM(Sales[amount]), SUM(Sales[qty]))"),
]


def build_visuals(table: str) -> list[Visual]:
    """A spread of visual kinds with roles that fit a sales-like table."""
    return [
        Visual("card", table, measure="Total Amount", title="Total Amount"),
        Visual("card", table, measure="Orders", title="Orders"),
        Visual("card", table, measure="Avg Amount", title="Avg Amount"),
        Visual(
            "kpi",
            table,
            measure="Total Amount",
            trend="sale_date",
            title="Amount trend",
        ),
        Visual("gauge", table, measure="Avg Amount", title="Avg Amount"),
        Visual("slicer", table, axis="region", title="Region"),
        Visual(
            "column",
            table,
            axis="region",
            measure="Total Amount",
            title="Amount by region",
        ),
        Visual(
            "bar", table, axis="product", measure="Total Qty", title="Qty by product"
        ),
        Visual(
            "line",
            table,
            axis="sale_date",
            measure="Total Amount",
            title="Amount over time",
        ),
        Visual(
            "area", table, axis="sale_date", measure="Total Qty", title="Qty over time"
        ),
        Visual(
            "pie",
            table,
            axis="region",
            measure="Total Amount",
            title="Amount share by region",
        ),
        Visual(
            "donut", table, axis="product", measure="Orders", title="Orders by product"
        ),
        Visual(
            "treemap",
            table,
            axis="product",
            measure="Total Amount",
            title="Amount by product",
        ),
        Visual(
            "funnel", table, axis="region", measure="Total Qty", title="Qty by region"
        ),
        Visual(
            "stackedColumn",
            table,
            axis="region",
            series="product",
            measure="Total Amount",
            title="Amount by region/product",
        ),
        Visual(
            "waterfall",
            table,
            axis="region",
            measure="Total Amount",
            title="Waterfall by region",
        ),
        Visual(
            "matrix",
            table,
            columns=["region", "product"],
            measure="Total Amount",
            title="Region x product",
        ),
        Visual(
            "table",
            table,
            columns=["id", "region", "product", "amount", "qty", "sale_date"],
            title="Detail",
        ),
    ]


def copy_members_for(template: Path) -> list[str]:
    names = set(zipfile.ZipFile(template).namelist())
    return [
        m
        for m in engine_container.COPY_MEMBERS
        if m in names and m not in ("Report/Layout", "DataModel")
    ]


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--data", required=True, help="CSV/JSON input")
    ap.add_argument("--table", required=True)
    ap.add_argument("--out", required=True, help="output .pbix path")
    ap.add_argument("--template", default=str(DEFAULT_TEMPLATE))
    ap.add_argument(
        "--datamodel", default=None, help="prebuilt DataModel (.abf); skips the engine"
    )
    ap.add_argument("--desktop", default=PBI_RS)
    ap.add_argument("--page", default="Sales Overview")
    args = ap.parse_args()

    out = Path(args.out)
    template = Path(args.template)
    pipe = EnginePipeline(template=template, desktop=args.desktop)
    rows = pipe.load_rows(Path(args.data))
    spec = pipe.build_spec(rows, table=args.table, database=out.stem or "Board")
    spec["measures"] = [
        {"table": args.table, "name": n, "expression": e} for n, e in MEASURES
    ]

    if args.datamodel:
        datamodel = Path(args.datamodel).read_bytes()
    elif sys.platform == "win32":
        datamodel = pipe.build_datamodel(spec)
    else:
        raise SystemExit("needs --datamodel on non-Windows hosts")

    visuals = build_visuals(args.table)
    w, h, gap, cols = 300, 200, 20, 4
    for i, vis in enumerate(visuals):
        vis.pos = (20 + (i % cols) * (w + gap), 20 + (i // cols) * (h + gap), w, h)
    layout = engine_layout.build_report([(args.page, visuals)])

    out.parent.mkdir(parents=True, exist_ok=True)
    engine_container.build_container(
        template, layout, datamodel, out, copy_members=copy_members_for(template)
    )
    print(
        json.dumps(
            {
                "out": str(out),
                "bytes": out.stat().st_size,
                "rows": len(rows),
                "visuals": len(visuals),
                "measures": [n for n, _ in MEASURES],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
