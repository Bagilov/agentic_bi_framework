"""CLI: render the web clone of a `.pbix` dashboard.

Usage:
    agentic-bi-web-clone --pbix board.pbix --out board_clone.html
        [--registry registry.json] [--title "Board"]

`--registry` is a JSON `{table:{columns,measures}}` (adds model-membership
checks). Without it, checks run without the model layer; with `--model-registry`
the registry is read from the `.pbix` via `pbixray` when available.

Exit codes: 0 on success, 2 when the `.pbix` cannot be read.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agentic_bi.web_report import build_model, write_html
from agentic_bi.web_report.web_inspect import registry_from_pbix


def _load_registry(args: argparse.Namespace) -> dict | None:
    if args.registry:
        return json.loads(Path(args.registry).read_text(encoding="utf-8"))
    if args.model_registry:
        reg = registry_from_pbix(args.pbix)
        return reg or None
    return None


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: build the model and write the HTML clone."""
    ap = argparse.ArgumentParser(
        prog="agentic-bi-web-clone",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--pbix", required=True, help="source .pbix")
    ap.add_argument("--out", required=True, help="output .html")
    ap.add_argument(
        "--registry",
        default=None,
        help="model registry JSON {table:{columns,measures}}",
    )
    ap.add_argument(
        "--model-registry",
        action="store_true",
        help="read the registry from the .pbix via pbixray",
    )
    ap.add_argument("--title", default="Dashboard Web Clone")
    args = ap.parse_args(argv)

    try:
        registry = _load_registry(args)
        model = build_model(args.pbix, registry=registry)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    out = write_html(model, args.out, title=args.title)
    s = model.summary()
    print(f"wrote {out} ({out.stat().st_size} B)")
    print(
        f"pages={s['pages']} elements={s['elements']} issues={s['issues']} "
        f"(errors={s['error']} warnings={s['warning']} info={s['info']})"
    )
    if not model.fields_checked:
        print(
            "warning: model-membership checks were skipped (no registry: pass "
            "--registry/--model-registry or install pbixray); a clean result does "
            "not cover table/column/measure references",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
