"""Deterministic dashboard constructor: design + model context -> artifact.

A design is the "base structure" of a dashboard - pages and the blocks on them.
The constructor compiles it into `Report/Layout` (or a `.pbix` on a donor model
or a freshly built DataModel) and then verifies the artifact against the design,
so the same input always produces the same report.

Nothing environment-specific is baked in: the donor, the OPC template, the
Desktop executable and the working directory are arguments, never constants.

Public API:
    Design, PageDesign, VisualDesign, ModelContext, TableContext
    Constructor, compile_design, validate_design, catalog
    Check, TestReport, DesignError, Issue
    SCHEMA_VERSION, design_schema, context_schema, report_schema, get_schema

Example:
    from agentic_bi.constructor import Constructor, Design

    ctor = Constructor(Design.load("design.json"))
    ctor.build_donor("donor.pbix", "out/board.pbix")
    report = ctor.test("out/board.pbix")
    assert report.critical_ok, report.to_markdown()
"""

from __future__ import annotations

from agentic_bi.constructor.blocks import (
    AGGREGATIONS,
    ALIASES,
    BLOCKS,
    BlockSpec,
    catalog,
    make_visual,
    resolve_kind,
)
from agentic_bi.constructor.builder import Constructor, layout_path_for
from agentic_bi.constructor.design import (
    Design,
    PageDesign,
    VisualDesign,
)
from agentic_bi.constructor.issues import (
    DesignError,
    Issue,
    has_errors,
    raise_for_errors,
)
from agentic_bi.constructor.layout import (
    CompiledLayout,
    compile_design,
)
from agentic_bi.constructor.model import TableContext
from agentic_bi.constructor.model_context import ModelContext
from agentic_bi.constructor.report import SCHEMA_VERSION, Check, TestReport
from agentic_bi.constructor.schema import (
    context_schema,
    design_schema,
    get_schema,
    report_schema,
)
from agentic_bi.constructor.validate import validate_design

__all__ = [
    "AGGREGATIONS",
    "ALIASES",
    "BLOCKS",
    "SCHEMA_VERSION",
    "BlockSpec",
    "Check",
    "CompiledLayout",
    "Constructor",
    "Design",
    "DesignError",
    "Issue",
    "ModelContext",
    "PageDesign",
    "TableContext",
    "TestReport",
    "VisualDesign",
    "catalog",
    "compile_design",
    "context_schema",
    "design_schema",
    "get_schema",
    "has_errors",
    "layout_path_for",
    "make_visual",
    "raise_for_errors",
    "report_schema",
    "resolve_kind",
    "validate_design",
]
