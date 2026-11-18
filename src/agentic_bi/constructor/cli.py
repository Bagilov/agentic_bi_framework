"""Command line: design JSON/YAML -> layout / `.pbix` plus a test report.

Examples:

    # validate the design and write the layout only
    agentic-bi-constructor --design design.json --out out/

    # offline build on a donor model
    agentic-bi-constructor --design design.json --donor donor.pbix \
        --out out/board.pbix --report out/report.md

    # the block catalogue, as JSON
    agentic-bi-constructor --catalog

Exit codes follow the shared contract (`cli_support`): 0 the work succeeded,
1 it ran and the artifact failed its checks, 2 bad input or configuration.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import zipfile
from pathlib import Path

from agentic_bi.cli_support import run_boundary
from agentic_bi.constructor.builder import Constructor, layout_path_for
from agentic_bi.constructor.cli_output import (
    EXIT_BAD_INPUT,
    EXIT_OK,
    fail,
    finish,
    format_preview,
    guard_options,
)
from agentic_bi.constructor.design import Design
from agentic_bi.constructor.issues import DesignError
from agentic_bi.constructor.model_context import ModelContext
from agentic_bi.constructor.report import TestReport
from agentic_bi.engine import EnginePipeline

PROG = "agentic-bi-constructor"
logger = logging.getLogger(__name__)

_BUILD_OPTIONS = ("out", "data", "datamodel", "donor", "template", "layout")


def _console_safe() -> None:
    """Keep a non-UTF-8 console (Windows cp1251/cp866) from raising on output."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(errors="backslashreplace")
        except (OSError, ValueError):
            logger.debug("console stream is closed; output stays as-is")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG, description="Build a dashboard from a declarative design"
    )
    parser.add_argument("--design", help="JSON/YAML design (pages and blocks)")
    parser.add_argument("--context", help="JSON/YAML model context")
    parser.add_argument("--context-from", help="derive the context from a donor .pbix")
    parser.add_argument("--out", metavar="PATH", help="result: .pbix or a directory")
    parser.add_argument("--donor", help="donor .pbix (offline build)")
    parser.add_argument("--template", help="OPC template for an engine build")
    parser.add_argument("--datamodel", help="ready DataModel file for an engine build")
    parser.add_argument(
        "--data",
        action="append",
        default=[],
        metavar="TABLE=PATH",
        help="rows for a live build (CSV/JSON)",
    )
    parser.add_argument(
        "--keep-donor-pages",
        action="store_true",
        help="append the design to the donor pages instead of replacing them",
    )
    parser.add_argument(
        "--no-preflight",
        action="store_true",
        help="do not compare the design with the donor model",
    )
    parser.add_argument("--layout", help="where to save Report/Layout (JSON)")
    parser.add_argument("--report", help="where to save the report (.md/.json)")
    parser.add_argument(
        "--model-verify", action="store_true", help="read the model back (pbixray)"
    )
    parser.add_argument(
        "--brand", action="store_true", help="compare the theme with the brand book"
    )
    parser.add_argument(
        "--catalog", action="store_true", help="print the block catalogue and exit"
    )
    parser.add_argument(
        "--check", action="store_true", help="validate the design; write nothing"
    )
    parser.add_argument(
        "--preview", action="store_true", help="show the placement; write nothing"
    )
    parser.add_argument(
        "--schema",
        choices=("design", "context", "report"),
        help="print a JSON Schema and exit",
    )
    parser.add_argument("--json", action="store_true", help="report as JSON on stdout")
    parser.add_argument("--desktop", help="PBIDesktop.exe for a live build")
    parser.add_argument("--work-dir", help="engine working directory for a live build")
    return parser


def _load_context(path: str | None) -> ModelContext | None:
    if not path:
        return None
    return ModelContext.load(path)


def _parse_data(items: list[str]) -> dict[str, list[dict[str, object]]]:
    """Parse repeated `TABLE=PATH` rows into `{table: rows}`.

    Raises:
        ValueError: an item is malformed, a table repeats, or the file is unreadable.
    """
    out: dict[str, list[dict[str, object]]] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"--data expects TABLE=PATH, got {item!r}")
        table, path = (part.strip() for part in item.split("=", 1))
        if not table or not path:
            raise ValueError(f"--data expects TABLE=PATH, got {item!r}")
        if table in out:
            raise ValueError(f"--data table is duplicated: {table!r}")
        try:
            rows = EnginePipeline.load_rows(Path(path))
            out[table] = [
                {str(key): value for key, value in row.items()} for row in rows
            ]
        except (OSError, ValueError) as exc:
            raise ValueError(f"--data {table}={path}: {exc}") from exc
    return out


def _run(args: argparse.Namespace) -> int:
    """Execute one parsed invocation (the body wrapped by `run_boundary`)."""
    guard = guard_options(args)
    if guard is not None:
        return guard
    try:
        design = Design.load(args.design)
    except (OSError, ValueError) as exc:
        return fail(args, f"cannot load design {args.design}: {exc}")
    try:
        context = (
            ModelContext.from_pbix(args.context_from)
            if args.context_from
            else _load_context(args.context)
        )
    except (OSError, ValueError) as exc:
        source = args.context_from or args.context
        return fail(args, f"cannot load context {source}: {exc}")
    ctor = Constructor(design, context, validate=False)
    out = Path(args.out) if args.out else None
    try:
        ctor.validate_or_raise()
    except DesignError as exc:
        report = ctor.design_report()
        report.add("design", "validation failed", False, str(exc))
        if not args.json:
            print(f"design validation failed: {exc}", file=sys.stderr)
        finish(report, args, None)
        return EXIT_BAD_INPUT
    return _execute(ctor, args, out)


def _execute(ctor: Constructor, args: argparse.Namespace, out: Path | None) -> int:
    """Run the requested mode once the design is known to be valid."""
    if args.preview:
        preview = ctor.preview()
        print(json.dumps(preview) if args.json else format_preview(preview))
        return EXIT_OK
    if args.check:
        report = ctor.design_report()
        report.add(
            "design",
            "design valid",
            True,
            f"{len(ctor.design.pages)} pages, {ctor.design.visual_count()} visuals",
        )
        return finish(report, args, None)
    try:
        data = _parse_data(args.data)
    except ValueError as exc:
        return fail(args, str(exc))
    target = out or Path("out")
    try:
        if data:
            report = ctor.build_and_test(
                target,
                template=args.template,
                data=data,
                desktop=args.desktop,
                work_dir=args.work_dir,
                model=args.model_verify,
                brand=args.brand,
            )
        elif args.datamodel:
            report = ctor.build_and_test(
                target,
                template=args.template,
                datamodel=Path(args.datamodel),
                model=args.model_verify,
                brand=args.brand,
            )
        elif args.donor:
            report = ctor.build_and_test(
                target,
                donor=args.donor,
                keep_donor_pages=args.keep_donor_pages,
                skip_preflight=args.no_preflight,
                model=args.model_verify,
                brand=args.brand,
            )
        else:
            layout_path = Path(args.layout) if args.layout else None
            report = _compile_only(ctor, target, layout_path)
    except (OSError, ValueError, zipfile.BadZipFile, KeyError) as exc:
        report = ctor.design_report()
        report.add("build", "assembly", False, f"{type(exc).__name__}: {exc}")
        finish(report, args, out)
        return EXIT_BAD_INPUT
    return finish(report, args, out)


def _compile_only(
    ctor: Constructor, out: Path | None, layout_path: Path | None
) -> TestReport:
    """Write the layout JSON and return the design report."""
    target = layout_path or layout_path_for(Path(out or "out"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(ctor.layout(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report = ctor.design_report()
    report.meta["layout"] = str(target)
    report.add(
        "layout",
        "design compiled",
        True,
        f"{len(ctor.design.pages)} pages, {ctor.design.visual_count()} visuals",
    )
    return report


def main(argv: list[str] | None = None) -> int:
    """Entry point: parse arguments, run the command, return its exit code."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    _console_safe()
    args = _parser().parse_args(argv)
    return run_boundary(lambda: _run(args), prog=PROG)


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())


__all__ = ["PROG", "main"]
