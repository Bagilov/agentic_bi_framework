"""CLI: full pipeline automation — build `.pbix` -> publish to Report Server.

The pipeline steps themselves live in `agentic_bi.automate_pipeline`; this
module maps command line flags onto them and prints the result summary.

Usage:
  # build + structure check only, without publishing
  uv run python -m agentic_bi.automate --dry-run

  # full run: build + publish to the configured folder + verify
  uv run python -m agentic_bi.automate --src donor.pbix --name "My Report" \
      --folder "/Target/Folder"

Environment-specific values (server host, base path, target folder, donor path)
are NOT baked in: pass them via CLI flags or a config dict.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import agentic_bi.paths as paths
from agentic_bi.automate_pipeline import (
    DEFAULT_COL,
    DEFAULT_DISPLAY,
    DEFAULT_FOLDER,
    DEFAULT_MEASURE,
    DEFAULT_NAME,
    DEFAULT_TABLE,
    _odata_quote,
    run,
    run_from_skeleton,
    verify_published,
)

__all__ = [
    "DEFAULT_COL",
    "DEFAULT_DISPLAY",
    "DEFAULT_FOLDER",
    "DEFAULT_MEASURE",
    "DEFAULT_NAME",
    "DEFAULT_SRC",
    "DEFAULT_TABLE",
    "_odata_quote",
    "main",
    "run",
    "run_from_skeleton",
    "verify_published",
]

# Defaults are intentionally neutral: override via CLI/config.
DEFAULT_SRC = "data/donor.pbix"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build + publish a .pbix to Report Server"
    )
    parser.add_argument(
        "--src", default=DEFAULT_SRC, help="donor .pbix (source of truth for DataModel)"
    )
    parser.add_argument(
        "--out",
        default=None,
        help="where to build the .pbix (default output_files/<name>.pbix)",
    )
    parser.add_argument(
        "--name", default=DEFAULT_NAME, help="report name on the server (without .pbix)"
    )
    parser.add_argument(
        "--folder", default=DEFAULT_FOLDER, help="target folder on the server"
    )
    parser.add_argument(
        "--display", default=DEFAULT_DISPLAY, help="page name in the layout"
    )
    parser.add_argument(
        "--table",
        default=None,
        help=f"model table in the layout (default: {DEFAULT_TABLE})",
    )
    parser.add_argument(
        "--col",
        default=None,
        help=f"model column in the layout (default: {DEFAULT_COL})",
    )
    parser.add_argument(
        "--measure",
        default=None,
        help=f"model measure in the layout (default: {DEFAULT_MEASURE})",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="build only, without publishing"
    )
    parser.add_argument(
        "--skeleton",
        action="store_true",
        help="generate a query-driven skeleton (build_skeleton) instead of a single-visual layout",
    )
    parser.add_argument("--verbose", action="store_true", help="verbose logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    out = (
        Path(args.out)
        if args.out
        else paths.output_dir(f"{args.name.strip().removesuffix('.pbix')}.pbix")
    )

    if args.skeleton:
        res = run_from_skeleton(
            src=Path(args.src),
            out=out,
            name=args.name,
            folder=args.folder,
            cfg=None,
            dry_run=args.dry_run,
        )
    else:
        res = run(
            src=Path(args.src),
            out=out,
            name=args.name,
            folder=args.folder,
            display_name=args.display,
            table=args.table,
            col=args.col,
            measure=args.measure,
            dry_run=args.dry_run,
        )
    import json

    print("\n=== RESULT ===")
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
