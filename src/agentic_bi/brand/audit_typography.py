"""Typography rules for the document brand audit (family / weight / size).

Split out of `brand_audit_eval` (which owns colour, contrast, background and
document-level rules) to keep both modules within the file-size budget.

Public API:
    eval_font(o, cfg, rep, ignore_fonts, fallback, allowed_fonts, allowed_weights)
    eval_font_size(o, cfg, rep)
"""

from __future__ import annotations

from agentic_bi.brand.audit_extract import Observation
from agentic_bi.brand.audit_math import font_weight as _font_weight
from agentic_bi.brand.audit_types import AuditReport
from agentic_bi.brand.config import BrandConfig
from agentic_bi.brand.eval import is_brand_font


def _is_allowed_font(name: str, allowed: set[str], fallback: set[str]) -> bool:
    """Whether a family is allowed: a brand family or a system fallback."""
    low = str(name).lower().strip()
    if not low:
        return True
    if is_brand_font(low):
        # brand font - but must match a specific allowed family
        return any(a in low for a in allowed)
    return any(fb in low for fb in fallback)


def eval_font(
    o: Observation,
    cfg: BrandConfig,
    rep: AuditReport,
    ignore_fonts: set[str],
    fallback: set[str],
    allowed_fonts: set[str],
    allowed_weights: set[str],
    emit,
) -> None:
    """Evaluate a family/weight observation.

    `emit` is the finding constructor of the caller (`brand_audit_eval._mk`), which
    applies the severity and enable/disable rules.
    """
    if not cfg.rules.get("check_fonts", True):
        return
    fn = o.value.lower().strip()
    if o.kind == "font":
        if fn in ignore_fonts:
            return
        if _is_allowed_font(o.value, allowed_fonts, fallback):
            return
        emit(
            rep,
            cfg,
            "FONT-FAMILY-BRAND",
            None,
            "font",
            o.location,
            f"Family '{o.value}' is not a brand one.",
            o.value,
            "allowed: brand fonts or a system fallback",
        )
    elif o.kind == "font_weight":
        if not allowed_weights or not is_brand_font(o.value):
            return  # only check weight for brand families
        w = _font_weight(o.value)
        if w and w not in allowed_weights:
            emit(
                rep,
                cfg,
                "FONT-WEIGHT-ALLOWED",
                None,
                "font",
                o.location,
                f"Disallowed weight '{w}' on {o.value}.",
                o.value,
                "allowed: " + ", ".join(cfg.weights),
            )


def eval_font_size(o: Observation, cfg: BrandConfig, rep: AuditReport, emit) -> None:
    """Check the font-size step (non-designer values)."""
    if not cfg.audit.get("check_font_size", False):
        return
    try:
        size = float(o.value)
    except ValueError:
        return
    step = int(cfg.check_size_step or 0)
    if step and round(size / step) != size / step:
        emit(
            rep,
            cfg,
            "FONT-SIZE-STEP",
            "info",
            "font",
            o.location,
            f"Size {size}pt is not a multiple of {step}pt (non-designer step).",
            o.value,
        )


__all__ = ["eval_font", "eval_font_size"]
