"""Reverse self-testing of a built `.pbix`.

Reads a produced `.pbix` back and checks that all required elements are present
on the pages and that the model returns the expected data. The module does not
need Desktop for structural checks; model reading is done via `pbixray` (if
installed).

This module is a **facade** over focused submodules:
    engine_verify_core.py   - CheckResult / VerifyReport + shared helpers
    engine_verify_checks.py - container/layout/bindings/filters/model-data checks
    engine_verify_brand.py  - report-theme extraction + brand-style comparison

Public API:
    CheckResult           - the result of one check
    VerifyReport          - a set of checks (+ summary/raise)
    verify_container(pbix)                       -> list[CheckResult]
    verify_layout(layout, spec, pages=None)      -> list[CheckResult]
    verify_bindings(layout, spec)                -> list[CheckResult]
    verify_safe_filters(layout)                  -> list[CheckResult]
    verify_model_data(pbix, spec, sample=50)     -> list[CheckResult]
    extract_report_theme(pbix)                   -> dict (fonts/colors/background)
    verify_brand(pbix, theme=None, strict=False) -> list[CheckResult]
    verify_pbix(pbix, spec, pages=None, strict=True, sample=50) -> VerifyReport

Regression guard: visual/page-level filters of the form `column IN (...)`
crash the pivot serializer on expand (`visitIn`/`serializeAll`), so
`verify_safe_filters` treats such filters as an error.

The final element-verification stage includes a **comparison with the brand
style** (`brand.py`): fonts, colors (palette, mandatory accent, at least 2
primary-range colors) and background (validity + WCAG contrast). By default
brand findings are soft (they do not fail the build); `brand_strict=True` makes
level-`error` violations critical.
"""

from __future__ import annotations

from pathlib import Path

from agentic_bi.engine_verify_core import (  # noqa: F401
    CheckResult,
    VerifyReport,
    load_layout,
    spec_objects,
)
from agentic_bi.engine_verify_checks import (  # noqa: F401
    verify_bindings,
    verify_container,
    verify_layout,
    verify_model_data,
    verify_safe_filters,
)
from agentic_bi.engine_verify_brand import (  # noqa: F401
    extract_report_theme,
    verify_brand,
)


def verify_pbix(pbix: Path, spec: dict,
                pages: dict[str, int] | None = None,
                sample: int = 50, model: bool = True,
                layout_checks: bool = True,
                expected_types: set[str] | None = None,
                brand: bool = True,
                brand_strict: bool = False) -> VerifyReport:
    """Full reverse check of a `.pbix`: container, layout, binding, data, brand.

    `layout_checks=False` skips the layout/binding checks (needed for a donor
    layout that references donor-model objects rather than spec objects).
    `brand=True` runs the final theme-vs-brand comparison (`verify_brand`);
    `brand_strict=True` makes level-`error` brand violations fail the build.
    """
    report = VerifyReport()
    pbix = Path(pbix)
    report.extend(verify_container(pbix))
    from agentic_bi.engine_verify_checks import _zip_ok
    if not pbix.exists() or not _zip_ok(pbix):
        return report

    layout = load_layout(pbix)
    if layout_checks:
        report.extend(verify_layout(layout, spec, pages=pages,
                                    expected_types=expected_types))
        report.extend(verify_bindings(layout, spec))
        report.extend(verify_safe_filters(layout))
    if model:
        report.extend(verify_model_data(pbix, spec, sample=sample))
    if brand:
        report.extend(verify_brand(pbix, strict=brand_strict))
    return report


__all__ = [
    "CheckResult",
    "VerifyReport",
    "load_layout",
    "spec_objects",
    "verify_container",
    "verify_layout",
    "verify_bindings",
    "verify_safe_filters",
    "verify_model_data",
    "verify_pbix",
    "extract_report_theme",
    "verify_brand",
]