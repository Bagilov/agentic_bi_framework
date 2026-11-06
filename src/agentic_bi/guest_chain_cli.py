"""Command-line front end for the one-shot guest dashboard chain.

Argument parsing, config overrides and the JSON verdict printer live here, so the
orchestrator module stays focused on the chain and its verdict.

Exit codes: 0 when the board is built (and, with `--oracle`, opened), 1 for any
other verdict, 2 when the configuration is missing or unusable.

Public API:
    main(argv) -> int   - run the chain once, print the JSON verdict
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from agentic_bi.cli_support import EXIT_BAD_INPUT, EXIT_FAILED, EXIT_OK, run_boundary
from agentic_bi.guest_chain import ChainConfig, build_dashboard

PROG = "agentic-bi-guest-dashboard"

# (attribute, caster) applied from parsed args over the environment-derived config.
_OVERRIDES: tuple[tuple[str, type], ...] = (
    ("data", Path),
    ("table", str),
    ("out", Path),
    ("repo", Path),
    ("vm_uuid", str),
    ("builder", str),
)


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog=PROG,
        description=(
            "Build a test dashboard in the Windows guest (one terminating chain)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--data", help="CSV/JSON input (default: examples/engine_sales.csv)"
    )
    ap.add_argument("--table", help="table name in the model")
    ap.add_argument("--out", help="output .pbix path on the host")
    ap.add_argument("--repo", help="framework root to stage (default: cwd)")
    ap.add_argument("--vm-uuid", help="UTM VM id to start/stop (optional)")
    ap.add_argument("--builder", help="builder script in examples/ to run")
    ap.add_argument("--timeout", type=int, help="overall wall-clock budget (s)")
    ap.add_argument("--title", help="visible table title")
    ap.add_argument("--oracle", action="store_true", help="also run the Desktop oracle")
    ap.add_argument("--keep-vm", action="store_true", help="do not stop the VM on exit")
    ap.add_argument("--json", help="write the JSON verdict to this path")
    return ap


def _apply_overrides(config: ChainConfig, args: argparse.Namespace) -> None:
    """Apply CLI arguments over the environment-derived config."""
    for name, caster in _OVERRIDES:
        value = getattr(args, name)
        if value:
            setattr(config, name, caster(value))
    if args.timeout is not None:
        # An explicit non-positive budget is a bad input, not "unset": the old
        # truthiness test silently ignored `--timeout 0` and let a negative value
        # reach `Deadline`, which raised a traceback out of the CLI.
        if args.timeout <= 0:
            raise ValueError(
                f"--timeout must be a positive number of seconds, got {args.timeout}"
            )
        config.timeout = args.timeout
    if args.title:
        config.title = args.title
    if args.oracle:
        config.oracle = True
    if args.keep_vm:
        config.stop_vm_on_exit = False


def _emit(payload: dict, json_path: str | None) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    print(text)
    if json_path:
        try:
            Path(json_path).parent.mkdir(parents=True, exist_ok=True)
            Path(json_path).write_text(text, encoding="utf-8")
        except OSError as exc:
            print(
                f"warning: could not write the verdict to {json_path}: {exc}",
                file=sys.stderr,
            )


def _run(args: argparse.Namespace) -> int:
    """Command body: resolve the configuration, run the chain, print a verdict.

    `--json` is honored on every path that reaches a verdict, including
    `NOT_CONFIGURED`: the earlier version passed `None` there, so a CI job that
    read the verdict file got nothing whenever the environment was incomplete and
    had to scrape stdout. A rejected budget (`--timeout -5`) stops before the
    run, so there is no verdict to write.
    """
    config = ChainConfig.from_env()
    if config is None:
        _emit(
            {
                "verdict": "NOT_CONFIGURED",
                "ok": False,
                "error": "set AGENTIC_BI_GUEST_WINRM, AGENTIC_BI_GUEST_USER, "
                "AGENTIC_BI_GUEST_PASSWORD",
            },
            args.json,
        )
        return EXIT_BAD_INPUT
    _apply_overrides(config, args)
    try:
        result = build_dashboard(config)
    except RuntimeError as exc:
        _emit({"verdict": "NOT_CONFIGURED", "ok": False, "error": str(exc)}, args.json)
        return EXIT_BAD_INPUT
    _emit(result.as_dict(), args.json)
    return EXIT_OK if result.ok else EXIT_FAILED


def main(argv: list[str] | None = None) -> int:
    """Run the chain once, print the JSON verdict, exit 0 only when ok.

    A configuration the user can fix (`AGENTIC_BI_CHAIN_TIMEOUT=abc`,
    `--timeout -5`) ends on one stderr line and exit 2 through `run_boundary`
    instead of a `ValueError` traceback.
    """
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    return run_boundary(lambda: _run(args), prog=PROG)


if __name__ == "__main__":
    raise SystemExit(main())
