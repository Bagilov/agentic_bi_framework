"""Brand-compliance metrics of a dashboard page's elements.

Embedded in the data-lineage process: for each page it computes the compliance
of the **used fonts and colors** with the brand style. The result is compliance
percentages (fonts/colors), a level (`ok`/`warning`/`error`/`unknown`) and a
list of `color`/`font` findings.

This module is a **facade** over:
    lineage_brand_metrics.py - the metric computation
    lineage_brand_report.py  - the human-readable report + CLI

The single source of rules is :class:`agentic_bi.brand_config.BrandConfig`
(palette/ΔRGB tolerance/`allow_extra`/fonts/weights/severity). It is the same
config as the document audit (`brand_audit.py`), so tolerances and severity are
set in one place (`brand_config.yaml`).

The metrics go into:
- the `PbiLineage.to_json()` JSON -> the `brand` key (+ `pages[].brand`);
- the PlantUML diagram, layer 7 "Elements and palette" (metrics on the page node).

Neutral colors (R==G==B) are not violations. The primary accent is recognized
with a "near-accent" tolerance.

Public API:
    page_brand_metrics(page, cfg=None)  -> dict  - metrics of one page
    visual_brand_metrics(visual, cfg=None) -> dict - metrics of one visual
    brand_audit_pages(pages, cfg=None)  -> dict  - metrics of all pages + summary
    brand_label(metrics)                -> str   - a string for PlantUML/report
    format_report(audit)                -> str   - a human-readable report
    audit_pbix(path) / audit_json(path) -> dict  - run over a .pbix / lineage.json
"""

from __future__ import annotations

from agentic_bi.lineage.lineage_brand_metrics import (  # noqa: F401
    brand_audit_pages,
    brand_label,
    page_brand_metrics,
    visual_brand_metrics,
)
from agentic_bi.lineage.lineage_brand_report import (  # noqa: F401
    audit_json,
    audit_pbix,
    format_report,
)
from agentic_bi.lineage.lineage_brand_report import _main

__all__ = ["audit_json", "audit_pbix", "brand_audit_pages", "brand_label",
           "format_report", "page_brand_metrics", "visual_brand_metrics"]


if __name__ == "__main__":
    raise SystemExit(_main())