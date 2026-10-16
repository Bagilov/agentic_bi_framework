"""Web clone of a Power BI dashboard as an interactive **layout** with checks.

Builds a single self-contained HTML page that *looks like the original report*:
page tabs, and on each page every element is placed at its true `Report/Layout`
position/size and drawn with a mock glyph for its visual type (the real visuals
cannot be rendered without the engine). Each element is interactive — hovering
shows its metrics and the checks it violated, problem elements are outlined by
severity, and the filter panel (severity / page / visual type / check id) dims
everything that does not match, so problem spots can be isolated on the layout.
A collapsed section carries the flat metrics/issues table.

The shell and interactions follow the framework's own process-mining HTML report
style (dark theme, stats grid, slide-in filter panel, hover tooltips).

Modules:
    web_model    - typed model (pages, elements, issues, metrics)
    web_checks   - per-element checks
    web_inspect  - layout -> model (+ model registry via pbixray)
    web_mock     - mock SVG glyphs per visual type (board look)
    web_assets   - CSS/JS assets (dark shell, layout canvas, filters, popover)
    web_render   - model -> one HTML file (layout view)
    web_cli      - `agentic-bi-web-clone` command line

Typical use:

    from agentic_bi.web_report import build_model, write_html
    model = build_model("board.pbix")
    write_html(model, "output_files/board_clone.html")

Environment-agnostic: no hosts, shares or personal paths; every input is a
parameter. `pbixray` is optional (adds model-membership checks).
"""

from __future__ import annotations

from agentic_bi.web_report.web_checks import (
    NON_DATA_TYPES,
    element_issues,
    has_in_filter,
)
from agentic_bi.web_report.web_inspect import (
    build_model,
    inspect_layout,
    load_layout,
    registry_from_pbix,
)
from agentic_bi.web_report.web_model import (
    ElementMetrics,
    ElementReport,
    Issue,
    PageReport,
    Severity,
    WebReportModel,
)
from agentic_bi.web_report.web_render import render_html, write_html

__all__ = [
    "NON_DATA_TYPES",
    "ElementMetrics",
    "ElementReport",
    "Issue",
    "PageReport",
    "Severity",
    "WebReportModel",
    "build_model",
    "element_issues",
    "has_in_filter",
    "inspect_layout",
    "load_layout",
    "registry_from_pbix",
    "render_html",
    "write_html",
]
