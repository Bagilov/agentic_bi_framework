"""CLI presentation helpers: option guards, error output and the report summary.

Kept apart from the command flow in `cli` so the flow reads as a sequence of
phases (parse -> guard -> load -> validate -> build -> report) without being
interleaved with formatting. Every usage error leaves through `fail`, which is
JSON-aware (`--json` turns it into an object) and returns exit code 2; `finish`
saves and prints a report and returns 0 or 1 from its critical checks.

Public API:
    fail(args, message, code=EXIT_BAD_INPUT) -> int
    finish(report, args, out) -> int
    format_preview(preview) -> str
    guard_options(args) -> int | None
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from agentic_bi.cli_support import EXIT_BAD_INPUT, EXIT_FAILED, EXIT_OK
from agentic_bi.constructor.blocks import catalog
from agentic_bi.constructor.report import TestReport
from agentic_bi.constructor.schema import get_schema

PROG = "agentic-bi-constructor"
_BUILD_OPTIONS = ("out", "data", "datamodel", "donor", "template", "layout")


def fail(args: argparse.Namespace, message: str, code: int = EXIT_BAD_INPUT) -> int:
    """Emit one usage/input error (JSON-aware) and return its exit code."""
    if args.json:
        print(json.dumps({"ok": False, "exit": code, "error": message}))
    else:
        print(f"{PROG}: {message}", file=sys.stderr)
    return code


def format_preview(preview: dict[str, object]) -> str:
    """Render the placement preview as a Markdown table."""
    lines = [
        f"# {preview.get('name', 'dashboard')}",
        "",
        "| page | id | kind | table | x | y | w | h |",
        "|---|---|---|---|---:|---:|---:|---:|",
    ]
    pages = preview.get("pages")
    for page in pages if isinstance(pages, list) else []:
        if not isinstance(page, dict):
            continue
        visuals = page.get("visuals")
        for visual in visuals if isinstance(visuals, list) else []:
            if not isinstance(visual, dict):
                continue
            x, y, w, h = visual.get("pos") or ("", "", "", "")
            lines.append(
                f"| {page.get('title')} | {visual.get('id')} | {visual.get('kind')} "
                f"| {visual.get('table')} | {x} | {y} | {w} | {h} |"
            )
    return "\n".join(lines)


def _report_path(args: argparse.Namespace, out: Path) -> Path:
    """Default report path: next to the artifact, or inside the output directory."""
    if out.suffix.lower() in (".pbix", ".json"):
        return out.with_suffix(".report.md")
    return out / "constructor_report.md"


def finish(report: TestReport, args: argparse.Namespace, out: Path | None) -> int:
    """Save the report when asked, print the summary and return the exit code."""
    report_path: Path | None = None
    if args.report:
        report_path = report.write(args.report)
    elif out is not None and report.critical_ok:
        report_path = report.write(_report_path(args, out))
    if args.json:
        print(report.to_json())
    else:
        print(
            f"{report.passed} passed, {len(report.failed)} failed, "
            f"{len(report.warnings)} warnings"
        )
        for check in report.failed:
            print(f"FAIL {check.group}/{check.name}: {check.detail}")
        for check in report.warnings:
            print(f"WARN {check.group}/{check.name}: {check.detail}")
        if report_path is not None:
            print(f"Saved: {os.path.relpath(report_path, Path.cwd())}")
    return EXIT_OK if report.critical_ok else EXIT_FAILED


def guard_options(args: argparse.Namespace) -> int | None:
    """Reject incompatible option combinations; `None` means the call is valid."""
    build_opts = any(getattr(args, name) for name in _BUILD_OPTIONS)
    if args.catalog:
        if args.design or build_opts or args.check or args.preview or args.schema:
            return fail(args, "--catalog cannot be combined with build options")
        print(json.dumps(catalog(), indent=2))
        return EXIT_OK
    if args.schema:
        if args.design or build_opts or args.check or args.preview:
            return fail(args, "--schema cannot be combined with other options")
        print(json.dumps(get_schema(args.schema), indent=2))
        return EXIT_OK
    if not args.design:
        return fail(args, "--design is required (or use --catalog/--schema)")
    if args.check and args.preview:
        return fail(args, "use only one of --check, --preview")
    if (args.check or args.preview) and build_opts:
        mode = "--check" if args.check else "--preview"
        return fail(args, f"{mode} writes no artifact; build options are not allowed")
    if not args.check and not args.preview and not args.out:
        return fail(args, "--out is required (or use --check/--preview)")
    if args.layout and (args.data or args.datamodel or args.donor):
        return fail(args, "--layout is only supported for a compile-only build")
    sources = [bool(args.data), bool(args.datamodel), bool(args.donor)]
    if sum(sources) > 1:
        return fail(args, "use only one of --data, --datamodel, --donor")
    if args.keep_donor_pages and not args.donor:
        return fail(args, "--keep-donor-pages requires --donor")
    if (args.data or args.datamodel) and not args.template:
        return fail(args, "--template is required with --data/--datamodel")
    if args.context and args.context_from:
        return fail(args, "use only one of --context, --context-from")
    if args.context_from and args.data:
        return fail(args, "--context-from cannot be combined with --data")
    return None


__all__ = [
    "EXIT_BAD_INPUT",
    "EXIT_OK",
    "fail",
    "finish",
    "format_preview",
    "guard_options",
]
