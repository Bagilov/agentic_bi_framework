"""CLI: build a figure set from a plan, and verify a built set.

Usage:
    agentic-bi-shots --plan figures.toml --out-dir output_files/figures
    agentic-bi-shots build  --plan figures.toml [--only a b] [--no-strict]
    agentic-bi-shots verify --manifest output_files/figures/manifest.json
    agentic-bi-shots verify --manifest … --plan figures.toml   # also check coverage

The `build` subcommand is implicit: a bare flag list is treated as `build`, so
the common case needs no subcommand. Exit codes: 0 on success, 1 when a figure
failed or a set drifted, 2 on a bad plan or an unreadable input.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from agentic_bi.cli_support import run_boundary
from agentic_bi.shots.shots_build import build_shots
from agentic_bi.shots.shots_manifest import read_manifest, verify_manifest
from agentic_bi.shots.shots_types import ShotPlan


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
        "--no-strict",
        action="store_true",
        help="skip (warn) instead of failing on a missing source",
    )


def _build(args: argparse.Namespace) -> int:
    plan = ShotPlan.load(args.plan).selected(args.only)
    result = build_shots(
        plan,
        args.out_dir,
        browser_executable=args.browser,
        plan_path=str(Path(args.plan).resolve()),
        strict=not args.no_strict,
    )
    for name, message in result.failures:
        print(f"FAILED {name}: {message}", file=sys.stderr)
    print(
        f"rendered={len(result.manifest.figures)} "
        f"failed={len(result.failures)} out={result.out_dir}"
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
        print(f"figures={len(manifest.figures)} problems={len(problems)}")
    return 1 if problems else 0


def _parser() -> argparse.ArgumentParser:
    """Build the two-level CLI: an optional `build`/`verify` subcommand."""
    ap = argparse.ArgumentParser(
        prog="agentic-bi-shots",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = ap.add_subparsers(dest="command")
    build = sub.add_parser("build", help="render the plan's figures")
    _add_build_args(build)
    verify = sub.add_parser("verify", help="check a built set against its manifest")
    verify.add_argument("--manifest", required=True)
    verify.add_argument("--root", default=None, help="base dir for relative PNGs")
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
        return run_boundary(lambda: _verify(args), prog="agentic-bi-shots")
    return run_boundary(lambda: _build(args), prog="agentic-bi-shots")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
