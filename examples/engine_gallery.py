"""Example: build a one-page gallery of every supported visual kind (engine path).

Run (Windows + Power BI Desktop RS):
    cd agentic_bi_framework
    python examples/engine_gallery.py

The script:
  1. builds a model from examples/engine_sales.csv via the Desktop AS engine;
  2. assembles a single "Visual Gallery" page via engine_layout.build_gallery;
  3. validates it (visual_check) and checks the strict Desktop oracle.
"""

from __future__ import annotations

from pathlib import Path

from agentic_bi import visual_check
from agentic_bi.engine import EnginePipeline
from agentic_bi.engine import container as engine_container
from agentic_bi.engine import layout as engine_layout

_HERE = Path(__file__).resolve().parent
CSV = _HERE / "engine_sales.csv"
OUT = _HERE.parent / "output_files" / "examples_gallery.pbix"


def main() -> int:
    pipe = EnginePipeline()
    rows = pipe.load_rows(CSV)
    spec = pipe.build_spec(rows, table="Sales", database="SalesGallery")
    print(f"rows={len(rows)} cols={len(spec['tables'][0]['columns'])}")

    datamodel = pipe.build_datamodel(spec)
    layout = engine_layout.build_gallery(spec)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    engine_container.build_container(pipe.template, layout, datamodel, OUT)
    print(f"built {OUT} ({OUT.stat().st_size} B)")

    registry = {
        t["name"]: {"columns": [c["name"] for c in t["columns"]], "measures": []}
        for t in spec["tables"]
    }
    errors = visual_check.check_pbix(OUT, registry)
    print(f"visual_check errors: {len(errors)}")
    for e in errors:
        print("  -", e)

    verdict = pipe.run_oracle(OUT, hold=70)
    print(f"oracle: {verdict}")
    return 0 if (not errors and verdict == "MODEL_LOADED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
