"""Example: build a `.pbix` from CSV with a custom visual set (engine path).

Run (Windows + Power BI Desktop RS):
    cd agentic_bi_framework
    python examples/engine_custom_visuals.py

The script:
  1. builds a model from examples/engine_sales.csv via the Desktop AS engine;
  2. assembles the report from scratch (table + card + columns + pie);
  3. checks that it opens with the strict oracle.
"""

from __future__ import annotations

from pathlib import Path

from agentic_bi.engine import EnginePipeline
from agentic_bi.engine import container as engine_container
from agentic_bi.engine import layout as engine_layout
from agentic_bi.engine.layout import Visual

_HERE = Path(__file__).resolve().parent
CSV = _HERE / "engine_sales.csv"
OUT = _HERE.parent / "output_files" / "examples_custom.pbix"


def main() -> int:
    pipe = EnginePipeline()

    rows = pipe.load_rows(CSV)
    spec = pipe.build_spec(rows, table="Sales", database="SalesExample")
    print(f"rows={len(rows)} cols={len(spec['tables'][0]['columns'])}")

    datamodel = pipe.build_datamodel(spec)

    visuals = [
        Visual(
            "table",
            "Sales",
            columns=["id", "region", "product", "amount", "sale_date"],
            title="Sales",
        ),
        Visual("card", "Sales", value="amount", agg="sum", title="Amount"),
        Visual("card", "Sales", value="qty", agg="avg", title="Avg qty"),
        Visual(
            "column",
            "Sales",
            axis="region",
            value="amount",
            agg="sum",
            title="Amount by region",
        ),
        Visual(
            "pie",
            "Sales",
            axis="product",
            value="amount",
            agg="count",
            title="Share by product",
        ),
    ]
    layout = engine_layout.build_report([("Sales", visuals)])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    engine_container.build_container(pipe.template, layout, datamodel, OUT)
    print(f"built {OUT} ({OUT.stat().st_size} B)")

    verdict = pipe.run_oracle(OUT, hold=70)
    print(f"oracle: {verdict}")
    return 0 if verdict == "MODEL_LOADED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
