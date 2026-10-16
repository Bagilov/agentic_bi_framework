"""Build a one-table board `.pbix` and place it anywhere (Desktop, output dir).

Minimal copy-paste reproduction of "make a board with a single table visual".
Runs the full engine path on Windows + Power BI Desktop; on other hosts pass a
prebuilt DataModel (workflow A in docs/DEVELOPMENT_MACOS.md).

Windows (run from an interactive session, not a headless WinRM session 0):

    python examples/engine_table_board.py --data examples/engine_sales.csv \
        --table Sales --out "%USERPROFILE%\\Desktop\\sales_table_dashboard.pbix"

macOS with a prebuilt model:

    python examples/engine_table_board.py --data examples/engine_sales.csv \
        --table Sales --datamodel model.abf --template templates/template.pbix \
        --out output_files/sales_table_board.pbix
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

from agentic_bi import engine_container, engine_layout
from agentic_bi.engine import DEFAULT_TEMPLATE, PBI_RS, EnginePipeline
from agentic_bi.engine_layout import Visual


def copy_members_for(template: Path) -> list[str]:
    """COPY_MEMBERS intersected with the template, minus Layout/DataModel."""
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
    ap.add_argument("--table", required=True, help="table name for the model")
    ap.add_argument("--out", required=True, help="output .pbix path")
    ap.add_argument(
        "--template",
        default=str(DEFAULT_TEMPLATE),
        help="classic donor .pbix that contains Report/Layout",
    )
    ap.add_argument(
        "--datamodel", default=None, help="prebuilt DataModel (.abf); skips the engine"
    )
    ap.add_argument(
        "--desktop",
        default=PBI_RS,
        help="Power BI Desktop executable (Windows engine mode)",
    )
    ap.add_argument("--title", default=None, help="visible table title")
    args = ap.parse_args()

    out = Path(args.out)
    template = Path(args.template)
    pipe = EnginePipeline(template=template, desktop=args.desktop)
    rows = pipe.load_rows(Path(args.data))
    spec = pipe.build_spec(rows, table=args.table, database=out.stem or "Board")
    columns = [c["name"] for c in spec["tables"][0]["columns"]]

    if args.datamodel:
        datamodel = Path(args.datamodel).read_bytes()
    elif sys.platform == "win32":
        datamodel = pipe.build_datamodel(spec)
    else:
        raise SystemExit(
            "needs --datamodel on non-Windows hosts "
            "(the AS engine requires Windows + Power BI Desktop)"
        )

    table = Visual(
        "table",
        args.table,
        columns=columns,
        title=args.title or f"{args.table} test data",
    )
    layout = engine_layout.build_report([(args.table, [table])])

    out.parent.mkdir(parents=True, exist_ok=True)
    engine_container.build_container(
        template, layout, datamodel, out, copy_members=copy_members_for(template)
    )
    print(
        json.dumps(
            {
                "out": str(out),
                "bytes": out.stat().st_size,
                "table": args.table,
                "rows": len(rows),
                "columns": columns,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
