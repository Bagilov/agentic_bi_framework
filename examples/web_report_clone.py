"""Example: build the web clone of a dashboard and inspect per-element checks.

The clone is a single self-contained HTML file: a summary grid, a sortable
metrics table (one row per element with its issues), and a vis-network graph
where hovering an element shows its metrics and the checks it violated. See
`agentic_bi.web_report` and docs/IMPLEMENTATION.md §17.

Run (no Desktop, no network needed except the vis-network CDN):

    python examples/web_report_clone.py

    # clone an arbitrary report, reading the model registry from the .pbix
    python examples/web_report_clone.py --pbix path/to/report.pbix

    # supply an explicit registry (skips pbixray)
    python examples/web_report_clone.py --pbix report.pbix --registry reg.json

By default it clones the shipped donor `templates/template.pbix` and writes
`output_files/template_clone.html`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agentic_bi.web_report import build_model, write_html
from agentic_bi.web_report.web_inspect import registry_from_pbix

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
DEFAULT_PBIX = _ROOT / "templates" / "template.pbix"
DEFAULT_OUT = _ROOT / "output_files" / "template_clone.html"


def _load_registry(path: Path, explicit: Path | None) -> dict | None:
    """Explicit registry file wins; else read the model from the .pbix."""
    if explicit is not None:
        return json.loads(explicit.read_text(encoding="utf-8"))
    reg = registry_from_pbix(path)
    return reg or None


def _print_findings(model) -> None:
    """Show the per-element issues (what the clone surfaces on hover)."""
    print(
        f"pages={len(model.pages)} elements={len(model.elements)} "
        f"issues={model.issues} {model.by_severity()}"
    )
    for element in model.elements:
        if not element.issues:
            continue
        marks = ", ".join(f"{i.check_id}({i.severity})" for i in element.issues)
        print(f"  {element.key:<16} {element.visual_type:<22} {marks}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--pbix",
        default=str(DEFAULT_PBIX),
        help="source .pbix (default: the shipped donor template)",
    )
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="output .html")
    ap.add_argument(
        "--registry",
        default=None,
        help="explicit registry JSON {table:{columns,measures}}",
    )
    ap.add_argument(
        "--no-model",
        action="store_true",
        help="skip model-membership checks (no pbixray)",
    )
    args = ap.parse_args()

    pbix = Path(args.pbix)
    registry = (
        None
        if args.no_model
        else _load_registry(pbix, Path(args.registry) if args.registry else None)
    )

    model = build_model(pbix, registry=registry)
    out = write_html(model, args.out, title=f"Clone · {pbix.name}")
    print(f"model registry: {'yes' if registry else 'no'}")
    _print_findings(model)
    print(f"wrote {out} ({out.stat().st_size} B)")
    print("open the .html in a browser; hover an element on the layout for its checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
