"""Multi-page PDF lineage report: diagram + flat matrix + brand audit.

The subpackage turns a ``PbiLineage.to_json()`` dict into a printable PDF. It is
environment-agnostic and consumes the lineage model already shipped in
``agentic_bi.lineage``.

Public API:
    - :func:`lineage_to_table` - flat level matrix rows
    - :class:`LineageTable` - dataframe + Excel export of the matrix
    - :func:`build_report` - assemble and write the multi-page PDF
    - :func:`validate_text`, :func:`render_png` - PlantUML validation/rendering

The PDF builder needs the ``report`` optional extra (reportlab, Pillow); the
matrix and PlantUML helpers only need the standard library (Excel needs pandas).
"""

from agentic_bi.report.lineage_brand_cols import BRAND_LEVEL_LABEL
from agentic_bi.report.lineage_matrix import COLUMNS, LEVEL, lineage_to_table
from agentic_bi.report.lineage_table import LineageTable, load_json
from agentic_bi.report.plantuml_tools import (
    find_plantuml_jar,
    render_png,
    validate_file,
    validate_text,
)


def build_report(*args, **kwargs):
    """Build the multi-page PDF report (lazy: needs the ``report`` extra)."""
    from agentic_bi.report.pdf_report import build_report as _build

    return _build(*args, **kwargs)


__all__ = [
    "BRAND_LEVEL_LABEL",
    "COLUMNS",
    "LEVEL",
    "LineageTable",
    "build_report",
    "find_plantuml_jar",
    "lineage_to_table",
    "load_json",
    "render_png",
    "validate_file",
    "validate_text",
]
