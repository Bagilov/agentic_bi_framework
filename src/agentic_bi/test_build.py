"""Test build: assemble a `.pbix` from a CSV and validate it end-to-end.

This is the framework's self-test entry point. It runs fully offline for the
layout/validation part when a DataModel (`.abf`) is supplied, and builds the
model with the Power BI Desktop AS engine on Windows when `--datamodel` is
omitted (Windows only).

Examples:
    # cross-platform: reuse a prebuilt model + template
    python -m agentic_bi.test_build \
        --data examples/engine_sales.csv --table Sales \
        --template templates/template.pbix --datamodel model.abf \
        --out output_files/test_build.pbix --report output_files/test_build.json

    # on Windows + Power BI Desktop: build the model via the engine
    python -m agentic_bi.test_build --data sales.csv --table Sales \
        --template templates/template.pbix --out out.pbix

Exit code is non-zero if the visual check or a critical verification fails.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import zipfile
from pathlib import Path

from agentic_bi import engine_container, engine_layout, engine_verify, visual_check
from agentic_bi.engine import DEFAULT_TEMPLATE, PBI_RS, EnginePipeline

logger = logging.getLogger(__name__)


def registry_from_spec(spec: dict) -> dict:
    """Build a {table:{columns,measures}} registry from a build spec."""
    return {
        t["name"]: {
            "columns": [c["name"] for c in t["columns"]],
            "measures": [
                m["name"]
                for m in spec.get("measures", [])
                if m.get("table") == t["name"]
            ],
        }
        for t in spec["tables"]
    }


def copy_members_for(template: Path) -> list[str]:
    """COPY_MEMBERS intersected with the template, minus Layout/DataModel."""
    names = set(zipfile.ZipFile(template).namelist())
    return [
        m
        for m in engine_container.COPY_MEMBERS
        if m in names and m not in ("Report/Layout", "DataModel")
    ]


def build_layout(spec: dict, mode: str) -> bytes:
    """Return Report/Layout bytes for the requested mode."""
    if mode == "gallery":
        return engine_layout.build_gallery(spec)
    return engine_layout.build_layout_from_spec(spec)


def run(args: argparse.Namespace) -> dict:
    data = Path(args.data)
    template = Path(args.template)
    out = Path(args.out)

    pipe = EnginePipeline(template=template, desktop=args.desktop)
    rows = pipe.load_rows(data)
    spec = pipe.build_spec(rows, table=args.table, database=args.database)
    logger.info("rows=%d cols=%d", len(rows), len(spec["tables"][0]["columns"]))

    layout = build_layout(spec, args.layout)

    if args.datamodel:
        datamodel = Path(args.datamodel).read_bytes()
    elif sys.platform == "win32":
        # Windows + Power BI Desktop: build the model via the AS engine.
        datamodel = pipe.build_datamodel(spec)
    else:
        raise SystemExit(
            "test build needs a DataModel: pass --datamodel <model.abf> on "
            "non-Windows hosts (the AS engine requires Windows + Power BI Desktop)"
        )

    out.parent.mkdir(parents=True, exist_ok=True)
    engine_container.build_container(
        template, layout, datamodel, out, copy_members=copy_members_for(template)
    )

    registry = (
        json.loads(Path(args.registry).read_text())
        if args.registry
        else registry_from_spec(spec)
    )
    visual_errors = visual_check.check_pbix(out, registry)
    report = engine_verify.verify_pbix(out, spec, model=args.model, layout_checks=True)

    result = {
        "out": str(out),
        "bytes": out.stat().st_size,
        "rows": len(rows),
        "layout": args.layout,
        "datamodel_bytes": len(datamodel),
        "visual_errors": visual_errors,
        "verify_ok": report.critical_ok(),
        "verify_passed": report.passed,
        "verify_failed": report.failed,
        "verify_critical_failed": [c.name for c in report.critical_failures],
        "verify_soft_failed": [c.name for c in report.soft_failures],
    }
    return result


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Build and validate a .pbix test build.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--data", required=True, help="CSV/JSON input")
    ap.add_argument("--table", required=True)
    ap.add_argument("--out", required=True, help="output .pbix")
    ap.add_argument("--template", default=str(DEFAULT_TEMPLATE))
    ap.add_argument(
        "--datamodel", default=None, help="prebuilt DataModel (.abf); skips the engine"
    )
    ap.add_argument(
        "--desktop",
        default=PBI_RS,
        help="Power BI Desktop executable (Windows engine mode)",
    )
    ap.add_argument("--database", default=None)
    ap.add_argument("--layout", choices=["gallery", "auto"], default="gallery")
    ap.add_argument(
        "--registry",
        default=None,
        help="JSON model registry; default: derived from the spec",
    )
    ap.add_argument(
        "--model",
        action="store_true",
        help="also read the model back via pbixray (needs readback)",
    )
    ap.add_argument("--report", default=None, help="write the JSON result here")
    args = ap.parse_args()
    if not args.database:
        args.database = Path(args.out).stem + "_db"

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    result = run(args)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(text, encoding="utf-8")

    ok = not result["visual_errors"] and result["verify_ok"]
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
