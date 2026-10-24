"""Audit a document for compliance with the brand style.

Quickly locate places that deviate from the style guide: colors (text/fill/line/
background), fonts (family/weight/size) and rules (mandatory accent, at least 2
primary-range colors, "2 of 3" base elements). Driven by a
:class:`brand_config.BrandConfig` (defaults from :mod:`brand`).

This module is a thin facade + public entry points; the work lives in:
    brand_audit_types.py   - AuditFinding / AuditReport
    brand_audit_extract.py - ThemeResolver + observation extraction from .pptx
    brand_audit_eval.py    - evaluation of observations against the rules

Supported:
    - direct RGB colors and **theme (scheme) colors** (resolved via theme1.xml);
    - nested group shapes (recursively);
    - tables (cell -> paragraph -> run);
    - font weights and sizes.

Example:
    from agentic_bi.brand_audit import audit_pptx
    rep = audit_pptx("Presentation.pptx")
    print(rep.format())            # a readable report with locations
    rep.to_json("audit.json")      # a machine-readable result

CLI:
    python -m agentic_bi.brand_audit deck.pptx --config brand_config.yaml
    python -m agentic_bi.brand_audit deck.pptx --json report.json --fail-on error

Public API:
    AuditFinding   - a single non-compliance (rule/level/location/value)
    AuditReport    - the finding set + summary/format/to_json
    ThemeResolver  - resolves theme (scheme) colors to HEX
    audit_pptx(path, cfg=None)      -> AuditReport
    audit_document(path, cfg=None)  -> AuditReport   (pptx/docx/xlsx)

CLI exit codes: 0 normally (findings are reported, not fatal), 1 when `--fail-on`
is set and matched, 2 on a bad input (unreadable config / unsupported format).
"""

from __future__ import annotations

import logging
from pathlib import Path

from agentic_bi.brand_audit_eval import (  # noqa: F401
    evaluate_observations,
    limit_findings,
)
from agentic_bi.brand_audit_extract import (  # noqa: F401
    ThemeResolver,
    iter_pptx_observations,
)
from agentic_bi.brand_audit_types import (  # noqa: F401
    AuditFinding,
    AuditReport,
)
from agentic_bi.brand_config import BrandConfig
from agentic_bi.brand_eval import is_brand_font  # noqa: F401 (public re-export)

logger = logging.getLogger(__name__)


def audit_pptx(path: str | Path, cfg: BrandConfig | None = None) -> AuditReport:
    """Check a `.pptx` presentation for brand compliance."""
    cfg = cfg or BrandConfig.default()
    rep = AuditReport(path=str(path))
    try:
        from pptx import Presentation
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "python-pptx is required: uv pip install python-pptx"
        ) from exc
    try:
        prs = Presentation(str(path))
    except Exception as exc:  # noqa: BLE001 - corrupted/non-pptx file
        logger.warning("could not open %s: %s", path, exc)
        rep.add(
            AuditFinding(
                "DOC-UNREADABLE",
                "error",
                "document",
                str(path),
                f"File does not open as .pptx: {exc}",
                str(path),
            )
        )
        return rep
    theme = (
        ThemeResolver.from_presentation(prs)
        if cfg.audit.get("resolve_theme_colors", True)
        else ThemeResolver()
    )
    obs = iter_pptx_observations(prs, cfg, theme)
    rep.theme = theme.as_dict()
    rep.stats = {
        "slides": len(prs.slides),
        "color_observations": sum(1 for o in obs if o.kind != "font"),
        "font_observations": sum(1 for o in obs if o.kind == "font"),
        "theme_slots": len(theme.slots),
    }
    rep.stats["theme_colors_resolved"] = sum(1 for o in obs if o.from_theme)
    evaluate_observations(obs, cfg, rep)
    limit_findings(rep, cfg)
    return rep


def audit_document(path: str | Path, cfg: BrandConfig | None = None) -> AuditReport:
    """Check a document by extension (.pptx/.docx/.xlsx)."""
    ext = Path(path).suffix.lower()
    if ext == ".pptx":
        return audit_pptx(path, cfg)
    raise NotImplementedError(f"format {ext!r} is not supported yet (.pptx only)")


def main(argv: list[str] | None = None) -> int:
    import argparse

    from agentic_bi.cli_support import run_boundary

    ap = argparse.ArgumentParser(
        prog="agentic-bi-brand-audit",
        description="Audit a document for brand-style compliance",
    )
    ap.add_argument("document", help="path to a .pptx")
    ap.add_argument("--config", default=None, help="brand_config.yaml/json")
    ap.add_argument("--json", dest="json_out", default=None, help="save JSON")
    ap.add_argument(
        "--fail-on",
        choices=["error", "warning", "never"],
        default="never",
        help="exit code 1 on findings of this level",
    )
    args = ap.parse_args(argv)

    def body() -> int:
        cfg = BrandConfig.load(args.config) if args.config else BrandConfig.default()
        rep = audit_document(args.document, cfg)
        print(rep.format(max_findings=int(cfg.audit.get("max_findings", 0) or 0)))
        if args.json_out:
            rep.to_json(args.json_out)
            print(f"\nJSON: {args.json_out}")

        if args.fail_on == "error" and rep.errors:
            return 1
        if args.fail_on == "warning" and (rep.errors or rep.warnings):
            return 1
        return 0

    return run_boundary(body, prog="agentic-bi-brand-audit")


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AuditFinding",
    "AuditReport",
    "ThemeResolver",
    "audit_document",
    "audit_pptx",
    "is_brand_font",
]
