"""Command-line front end for the one-shot guest dashboard chain.

Argument parsing, config overrides and the JSON verdict printer live here, so the
orchestrator module stays focused on the chain and its verdict.

Public API:
    main(argv) -> int   - run the chain once, print the JSON verdict
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from agentic_bi.guest_chain import ChainConfig, build_dashboard

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
        prog="agentic-bi-guest-dashboard",
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
    if args.timeout:
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


def main(argv: list[str] | None = None) -> int:
    """Run the chain once, print the JSON verdict, exit 0 only when ok."""
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    config = ChainConfig.from_env()
    if config is None:
        _emit(
            {
                "verdict": "NOT_CONFIGURED",
                "ok": False,
                "error": "set AGENTIC_BI_GUEST_WINRM, AGENTIC_BI_GUEST_USER, "
                "AGENTIC_BI_GUEST_PASSWORD",
            },
            None,
        )
        return 2
    _apply_overrides(config, args)
    try:
        result = build_dashboard(config)
    except RuntimeError as exc:
        _emit({"verdict": "NOT_CONFIGURED", "ok": False, "error": str(exc)}, None)
        return 2
    _emit(result.as_dict(), args.json)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
