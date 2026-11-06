"""CLI: build a figure set from a plan, and verify a built set.

Usage:
    agentic-bi-shots --plan figures.toml --out-dir output_files/figures
    agentic-bi-shots build  --plan figures.toml [--only a b] [--no-strict]
    agentic-bi-shots verify --manifest output_files/figures/manifest.json
    agentic-bi-shots verify --manifest … --plan figures.toml   # also check coverage

The `build` subcommand is implicit: a bare flag list is treated as `build`, so
the common case needs no subcommand.

Exit codes:
    0  every requested figure was produced and/or the set has no drift;
    1  a requested figure was not produced (failed or skipped) or the set
       drifted from its manifest;
    2  a bad plan/manifest or an unreadable input.

The summary is three short lines (built/skipped/failed, manifest, output
directory) with relative paths; warnings and errors go to stderr and are never
mixed into the summary.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from agentic_bi.cli_support import run_boundary
from agentic_bi.shots.shots_build import BuildResult, build_shots
from agentic_bi.shots.shots_manifest import verify_manifest
from agentic_bi.shots.shots_store import read_manifest
from agentic_bi.shots.shots_types import ShotPlan

_PROG = "agentic-bi-shots"
_MAX_NAMES = 5


def _rel(path: str | Path) -> str:
    """A path for the console: relative when it is under the CWD, else absolute.

    A directory outside the CWD used to print as `../../../../../var/folders/…`
    — technically relative but unreadable. A target under the CWD keeps the
    short form; anything else is printed as an absolute path, which is what a
    reader can act on.
    """
    target = Path(path)
    try:
        relative = target.resolve().relative_to(Path.cwd().resolve())
    except (ValueError, OSError):
        return target.as_posix()
    return relative.as_posix() or "."


def _add_build_args(parser: argparse.ArgumentParser) -> None:
    """Add the shared build arguments to a parser."""
    parser.add_argument("--plan", required=True, help="figure plan (.toml or .json)")
    parser.add_argument(
        "--out-dir",
        default="output_files/figures",
        help="output directory for PNGs and the manifest",
    )
    parser.add_argument("--only", nargs="*", default=None, help="render only these")
    parser.add_argument("--browser", default=None, help="explicit Chromium path")
    parser.add_argument(
        "--manifest-name",
        default="manifest.json",
        help="manifest file name inside --out-dir (default: manifest.json)",
    )
    parser.add_argument(
        "--no-strict",
        action="store_true",
        help="leave a figure with a missing source out of the manifest (warn) "
        "instead of failing the build",
    )


def _report_skipped(result: BuildResult) -> None:
    """One stderr warning per skip reason, with a bounded figure list."""
    by_reason: dict[str, list[str]] = {}
    for name, reason in result.skipped:
        by_reason.setdefault(reason, []).append(name)
    for reason, names in by_reason.items():
        shown = ", ".join(names[:_MAX_NAMES])
        if len(names) > _MAX_NAMES:
            shown += f", +{len(names) - _MAX_NAMES}"
        print(
            f"warning: skipped {len(names)} figure(s) [{shown}]: {reason}",
            file=sys.stderr,
        )


def _build(args: argparse.Namespace) -> int:
    plan = ShotPlan.load(args.plan).selected(args.only)
    result = build_shots(
        plan,
        args.out_dir,
        browser_executable=args.browser,
        manifest_name=args.manifest_name,
        plan_path=args.plan,
        strict=not args.no_strict,
    )
    for name, message in result.failures:
        print(f"error: figure '{name}': {message}", file=sys.stderr)
    _report_skipped(result)
    print(
        f"figures: {result.built} built, {len(result.skipped)} skipped, "
        f"{len(result.failures)} failed"
    )
    print(f"out: {_rel(result.out_dir)}")
    print(f"manifest: {_rel(result.out_dir / args.manifest_name)}")
    if result.failures:
        print(
            f"{_PROG}: error: {len(result.failures)} requested figure(s) were "
            "not produced (see above)",
            file=sys.stderr,
        )
    elif result.skipped:
        print(
            f"{_PROG}: error: {len(result.skipped)} requested figure(s) were "
            "not produced; install the missing tool or drop them from the plan",
            file=sys.stderr,
        )
    return 0 if result.ok else 1


def _verify(args: argparse.Namespace) -> int:
    manifest = read_manifest(args.manifest)
    plan = ShotPlan.load(args.plan) if args.plan else None
    problems = verify_manifest(manifest, root=args.root, plan=plan)
    for problem in problems:
        print(f"DRIFT {problem}", file=sys.stderr)
    if args.json:
        payload = {
            "figures": len(manifest.figures),
            "problems": problems,
            "ok": not problems,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"figures: {len(manifest.figures)} checked, {len(problems)} problem(s)")
        print(f"manifest: {_rel(args.manifest)}")
    if problems:
        print(
            f"{_PROG}: error: {len(problems)} problem(s) found (see DRIFT above)",
            file=sys.stderr,
        )
    return 1 if problems else 0


def _parser() -> argparse.ArgumentParser:
    """Build the two-level CLI: an optional `build`/`verify` subcommand."""
    ap = argparse.ArgumentParser(
        prog=_PROG,
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = ap.add_subparsers(dest="command")
    build = sub.add_parser("build", help="render the plan's figures")
    _add_build_args(build)
    verify = sub.add_parser("verify", help="check a built set against its manifest")
    verify.add_argument("--manifest", required=True)
    verify.add_argument(
        "--root",
        default=None,
        help="base dir for relative PNG names (default: the manifest's directory)",
    )
    verify.add_argument(
        "--plan",
        default=None,
        help="also check the manifest covers every figure in this plan",
    )
    verify.add_argument("--json", action="store_true")
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point: build or verify a figure set."""
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = _parser()
    if not argv:
        ap.print_help(sys.stderr)
        return 2
    # A bare flag list means the implicit `build` subcommand.
    command = argv[0] if argv[0] in {"build", "verify"} else "build"
    args = ap.parse_args(argv if command == argv[0] else [command, *argv])

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if command == "verify":
        return run_boundary(lambda: _verify(args), prog=_PROG)
    return run_boundary(lambda: _build(args), prog=_PROG)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
