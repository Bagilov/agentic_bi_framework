"""Reporting and CLI over the brand metrics of dashboard pages."""

from __future__ import annotations

import logging
from pathlib import Path

from agentic_bi.lineage.lineage_brand_metrics import (
    _LEVEL_ORDER,
    brand_audit_pages,
    brand_label,
    page_brand_metrics,
    visual_brand_metrics,
)

_log = logging.getLogger(__name__)


def _as_page_list(audit: dict) -> list[dict]:
    """Normalize audit `pages` to a list [{name, metrics}] (dict or list)."""
    pages = audit.get("pages", []) or []
    if isinstance(pages, dict):
        return [{"name": k, "metrics": v or {}} for k, v in pages.items()]
    return pages


def format_report(audit: dict) -> str:
    """A human-readable summary report across all pages (text)."""
    s = audit.get("summary", {})
    lines = [
        "Brand-style compliance (page elements)",
        (
            f"  pages: {s.get('pages', 0)}  -  ok: {s.get('ok', 0)}, "
            f"warnings: {s.get('warnings', 0)}, errors: {s.get('errors', 0)}, "
            f"no data: {s.get('unknown', 0)}"
        ),
        (
            f"  averages: fonts {s.get('fonts_compliance')}%, "
            f"colors {s.get('colors_compliance')}%"
        ),
        "",
    ]
    pages = sorted(
        _as_page_list(audit),
        key=lambda r: -_LEVEL_ORDER.get((r.get("metrics") or {}).get("level", ""), 0),
    )
    for r in pages:
        m = r.get("metrics") or {}
        f, c = m.get("fonts", {}) or {}, m.get("colors", {}) or {}
        accent = "yes" if c.get("has_accent") else "no"
        msgs = [x.get("message", "") for x in m.get("findings", [])]
        note = "; ".join(msgs) or "-"
        lines.append(
            f"  [{m.get('level', ''):>7}] {r.get('name', ''):<32} "
            f"fonts {f.get('compliance') if f.get('compliance') is not None else '-'}%  "
            f"colors {c.get('compliance') if c.get('compliance') is not None else '-'}%  "
            f"accent: {accent}"
        )
        if note != "-":
            lines.append(f"           {note}")
    return "\n".join(lines)


def audit_pbix(pbix_path: str | Path, brand_config: str | Path | None = None) -> dict:
    """Run the brand metrics over a .pbix (via `PbiLineage`)."""
    from agentic_bi.lineage.pbi_lineage import PbiLineage

    with PbiLineage(str(pbix_path), brand_config=brand_config) as lg:
        data = lg.to_json(include_plantuml=False)
    return data.get("brand") or {"summary": {}, "pages": {}}


def audit_json(lineage_json: str | Path) -> dict:
    """Brand metrics from a ready lineage.json (the `brand` key)."""
    import json

    data = json.loads(Path(lineage_json).read_text(encoding="utf-8"))
    if data.get("brand"):
        return data["brand"]
    return brand_audit_pages(data.get("pages", []))


def _main(argv: list[str] | None = None) -> int:
    import argparse
    import json as _json

    ap = argparse.ArgumentParser(
        description="Dashboard brand-style compliance: metrics by page (fonts/colors)."
    )
    ap.add_argument("input", help="path to a .pbix or lineage.json")
    ap.add_argument(
        "--brand-config",
        default=None,
        help="brand rules config (default agentic_bi/brand_config.yaml)",
    )
    ap.add_argument(
        "--json", dest="json_out", default=None, help="save metrics to JSON"
    )
    args = ap.parse_args(argv)

    src = Path(args.input)
    if not src.exists():
        print(f"Input not found: {src}")
        return 2
    audit = (
        audit_json(src)
        if src.suffix.lower() in (".json",)
        else audit_pbix(src, args.brand_config)
    )
    print(format_report(audit))
    if args.json_out:
        Path(args.json_out).write_text(
            _json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\nJSON: {args.json_out}")
    s = audit.get("summary", {})
    return 1 if s.get("errors") else 0


__all__ = [
    "audit_json",
    "audit_pbix",
    "brand_audit_pages",
    "brand_label",
    "format_report",
    "page_brand_metrics",
    "visual_brand_metrics",
]


if __name__ == "__main__":
    raise SystemExit(_main())
