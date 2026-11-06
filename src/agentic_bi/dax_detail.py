"""Deep DAX/M analysis of a `.pbix` for data-distortion diagnostics.

Covers the inline techniques from real cases: extracting from a `.pbix` all DAX
measures with full expressions, calculated columns, Power Query M code and
markers indicating a distortion risk (hardcoded thresholds, FILTER(ALL), fixed
dates/paths, LocalNow). Returns a JSON-serializable dict.

Usage (CLI):
    python -m agentic_bi.dax_detail "C:\\\\path\\\\to\\\\report.pbix" -o out.json
    python -m agentic_bi.dax_detail "C:\\\\path\\\\to\\\\report.pbix" --summary

CLI exit codes (see :mod:`agentic_bi.cli_support`): 0 when the analysis ran
(whatever it found), 2 on a bad input (missing/unreadable `.pbix`, unwritable
output path).

As an API:
    from agentic_bi.dax_detail import analyze_dax_detail
    data = analyze_dax_detail("C:/path/to/report.pbix")

This module owns the command-line entry point and the rendering of a result
(counts, summary, output file); the extraction itself lives in
`agentic_bi.dax_detail_extract` and is re-exported here.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import agentic_bi.paths as paths
from agentic_bi.dax_detail_extract import (
    _extract_thresholds as _extract_thresholds,
)
from agentic_bi.dax_detail_extract import (
    _flatten_exprs as _flatten_exprs,
)
from agentic_bi.dax_detail_extract import (
    _scan_markers as _scan_markers,
)
from agentic_bi.dax_detail_extract import (
    analyze_dax_detail,
    build_distort_index,
    extract_calc_columns,
    extract_measures,
    extract_power_query,
)
from agentic_bi.dax_detail_extract import (
    logger as logger,
)

PROG = "agentic_bi.dax_detail"
OUT_DIR = paths.output_dir()


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


def main(argv: list[str] | None = None) -> int:
    from agentic_bi.cli_support import EXIT_BAD_INPUT, EXIT_OK, fail, run_boundary

    _console_safe()
    p = argparse.ArgumentParser(
        prog=PROG,
        description="DAX/M analysis of a .pbix: measures, columns, M, distortion risks",
    )
    p.add_argument("pbix", help="path to the .pbix artifact")
    p.add_argument(
        "-o",
        "--out",
        default=None,
        metavar="JSON",
        help="write the JSON result here "
        "(default: output_files/dax_detail/<name>_dax.json)",
    )
    p.add_argument(
        "--no-antipatterns",
        action="store_true",
        help="do not attach the antipattern summary (default: attached)",
    )
    p.add_argument(
        "--summary",
        action="store_true",
        help="print only the counts, without the JSON dump or the output file",
    )
    args = p.parse_args(argv)

    def body() -> int:
        try:
            data = analyze_dax_detail(
                args.pbix, run_antipatterns=not args.no_antipatterns
            )
        except ImportError as exc:
            # The deep extraction needs the optional `readback` extra.
            return fail(
                PROG,
                f"deep DAX extraction needs the readback extra (pbixray): {exc}",
                EXIT_BAD_INPUT,
            )
        summary = data["summary"]
        counts = (
            f"{summary['measures_total']} measure(s), "
            f"{summary['calc_columns_total']} calculated column(s), "
            f"{len(summary['power_query_tables'])} Power Query table(s)"
        )

        if args.summary:
            print(f"{PROG}: {counts} -> OK")
            for level, markers in data["distort"].items():
                if not markers:
                    continue
                print(f"[{level}]")
                for marker, names in markers.items():
                    print(f"   {marker}: {len(names)}")
            return EXIT_OK

        out_path = (
            Path(args.out)
            if args.out
            else OUT_DIR / "dax_detail" / f"{Path(args.pbix).stem}_dax.json"
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(json.dumps(data, ensure_ascii=False, indent=2))
        print(f"{PROG}: {counts} -> OK")
        print(f"Saved: {_shown(out_path)}")
        return EXIT_OK

    return run_boundary(body, prog=PROG)


__all__ = [
    "OUT_DIR",
    "PROG",
    "analyze_dax_detail",
    "build_distort_index",
    "extract_calc_columns",
    "extract_measures",
    "extract_power_query",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
