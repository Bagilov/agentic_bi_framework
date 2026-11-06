"""CLI: build a Power BI **PBIP project** (text-based) that opens in Desktop.

The project file tree — root `.pbir`, report page and semantic model — is
assembled by `agentic_bi.pbip_project`; this module owns the command line.

CLI:
    python -m agentic_bi.build --out output_files/demo_events
    python -m agentic_bi.build --out output_files/blank --no-visuals

CLI exit codes (see :mod:`agentic_bi.cli_support`): 0 when the project is
written, 2 on a bad output path (an input that cannot be written).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import agentic_bi.paths as paths
from agentic_bi.pbip_project import (
    _empty_report,
    _model_bim,
    _pbir,
    _report_with_visuals,
    _visual_placeholder,
    _write_json,
    build_pbip,
)

__all__ = [
    "DEMO_TABLES",
    "PROG",
    "_console_safe",
    "_empty_report",
    "_model_bim",
    "_pbir",
    "_project_files",
    "_report_with_visuals",
    "_shown",
    "_visual_placeholder",
    "_write_json",
    "build_pbip",
    "main",
]

PROG = "agentic_bi.build"

DEMO_TABLES: list[dict] = [
    {
        "name": "Events",
        "columns": [
            {"name": "case", "dataType": "string"},
            {"name": "status", "dataType": "string"},
            {"name": "dur", "dataType": "decimal"},
        ],
        "measures": [
            {"name": "Count", "expression": "COUNTROWS('Events')"},
            {"name": "AvgDur", "expression": "AVERAGE('Events'[dur])"},
        ],
    }
]


def _shown(path: str | Path) -> str:
    """Return `path` for a message: relative to CWD, never an absolute path."""
    p = Path(path)
    return str(p) if not p.is_absolute() else os.path.relpath(p, Path.cwd())


def _console_safe() -> None:
    """Keep a non-UTF-8 console (Windows cp1251/cp866) from raising on output."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(errors="backslashreplace")
        except (OSError, ValueError):  # a closed/replaced stream is not fatal
            pass


def _project_files(root: Path) -> list[Path]:
    """Return the files a PBIP project at `root` consists of."""
    name = root.name
    return [
        root / f"{name}.pbir",
        root / f"{name}.Report" / "report.json",
        root / f"{name}.Semantic" / "model.bim",
        root / f"{name}.Semantic" / "definition.pbism",
    ]


def main(argv: list[str] | None = None) -> int:
    from agentic_bi.cli_support import EXIT_OK, run_boundary

    _console_safe()
    ap = argparse.ArgumentParser(
        prog=PROG,
        description="Build a PBIP project (report + model) that Power BI Desktop opens.",
    )
    ap.add_argument(
        "--out",
        default=str(paths.output_dir("demo_events")),
        metavar="DIR",
        help="target project folder; the entry point is <out>/<folder>.pbir "
        "(default: output_files/demo_events)",
    )
    ap.add_argument(
        "--display",
        default="Demo: events",
        help="report and page display name (default: %(default)s)",
    )
    ap.add_argument(
        "--no-visuals",
        action="store_true",
        help="write an empty page without the sample Count card",
    )
    args = ap.parse_args(argv)

    def body() -> int:
        out = Path(args.out)
        build_pbip(
            out,
            display_name=args.display,
            tables=DEMO_TABLES,
            with_visuals=not args.no_visuals,
        )
        files = _project_files(out)
        visuals = 0 if args.no_visuals else 1
        print(f"{PROG}: 1 page(s), {visuals} visual(s), {len(files)} file(s) -> OK")
        for path in files:
            print(f"  {_shown(path)}")
        return EXIT_OK

    return run_boundary(body, prog=PROG)


if __name__ == "__main__":
    raise SystemExit(main())
