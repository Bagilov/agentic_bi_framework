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
    from agentic_bi.brand.audit import audit_pptx
    rep = audit_pptx("Presentation.pptx")
    print(rep.format())            # a readable report with locations
    rep.to_json("audit.json")      # a machine-readable result

CLI:
    python -m agentic_bi.brand.audit deck.pptx --config brand_config.yaml
    python -m agentic_bi.brand.audit deck.pptx --json report.json --fail-on error

Public API:
    AuditFinding   - a single non-compliance (rule/level/location/value)
    AuditReport    - the finding set + summary/format/to_json
    ThemeResolver  - resolves theme (scheme) colors to HEX
    audit_pptx(path, cfg=None)      -> AuditReport
    audit_document(path, cfg=None)  -> AuditReport   (pptx/docx/xlsx)

CLI exit codes: 0 normally (findings are reported, not fatal), 1 when `--fail-on`
is set and matched, 2 on a bad input (missing/unreadable document or config, an
unsupported format).
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from agentic_bi.brand.audit_eval import (
    evaluate_observations,
    limit_findings,
)
from agentic_bi.brand.audit_extract import (
    ThemeResolver,
    iter_pptx_observations,
)
from agentic_bi.brand.audit_types import (
    AuditFinding,
    AuditReport,
)
from agentic_bi.brand.config import BrandConfig
from agentic_bi.brand.eval import is_brand_font

logger = logging.getLogger(__name__)

PROG = "agentic-bi-brand-audit"


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
    except FileNotFoundError:
        raise
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


def _shown(path: str | Path) -> str:
    """Return `path` for a message: relative to CWD, never an absolute path."""
    p = Path(path)
    return str(p) if not p.is_absolute() else os.path.relpath(p, Path.cwd())


def _console_safe() -> None:
    """Keep a non-UTF-8 console (Windows cp1251/cp866) from raising on output."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(errors="backslashreplace")
        except (OSError, ValueError):  # a closed/replaced stream is not fatal
            pass


def main(argv: list[str] | None = None) -> int:
    import argparse

    from agentic_bi.cli_support import (
        EXIT_BAD_INPUT,
        EXIT_FAILED,
        EXIT_OK,
        fail,
        run_boundary,
    )

    _console_safe()
    ap = argparse.ArgumentParser(
        prog=PROG,
        description="Audit a document for brand-style compliance",
    )
    ap.add_argument("document", help="path to the .pptx to audit")
    ap.add_argument(
        "--config",
        default=None,
        metavar="YAML|JSON",
        help="brand config with the project overrides "
        "(default: the built-in brand defaults)",
    )
    ap.add_argument(
        "--json",
        dest="json_out",
        default=None,
        metavar="JSON",
        help="also write the findings as JSON here (default: not written)",
    )
    ap.add_argument(
        "--fail-on",
        choices=["error", "warning", "never"],
        default="never",
        help="exit 1 when findings of this level exist: error, warning, "
        "or never (default: never)",
    )
    args = ap.parse_args(argv)

    def body() -> int:
        document = Path(args.document)
        if not document.is_file():
            return fail(PROG, f"document not found: {_shown(document)}", EXIT_BAD_INPUT)
        try:
            cfg = (
                BrandConfig.load(args.config) if args.config else BrandConfig.default()
            )
            rep = audit_document(document, cfg)
        except RuntimeError as exc:
            # A missing optional integration (python-pptx, PyYAML) is a
            # configuration error, not a crash.
            return fail(PROG, str(exc), EXIT_BAD_INPUT)
        print(rep.format(max_findings=int(cfg.audit.get("max_findings", 0) or 0)))

        unreadable = [f for f in rep.findings if f.rule_id == "DOC-UNREADABLE"]
        if unreadable:
            return fail(
                PROG,
                f"{_shown(document)}: {unreadable[0].message}",
                EXIT_BAD_INPUT,
            )

        if args.json_out:
            rep.to_json(args.json_out)
            print(f"{PROG}: saved {_shown(args.json_out)}")

        if args.fail_on == "error" and rep.errors:
            return EXIT_FAILED
        if args.fail_on == "warning" and (rep.errors or rep.warnings):
            return EXIT_FAILED
        return EXIT_OK

    return run_boundary(body, prog=PROG)


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
