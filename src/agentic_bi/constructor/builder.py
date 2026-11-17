"""The constructor: design + model context -> layout / `.pbix` + test report.

Public flow:

    design = Design.load("design.json")
    ctor = Constructor(design)
    ctor.validate_or_raise()
    ctor.build_donor("donor.pbix", "out/board.pbix")
    report = ctor.test("out/board.pbix")

No decision about what a page contains is made here: the constructor compiles
the structure it was given and then checks the artifact against it. Validation
runs on construction (or is deferred with `validate=False` and re-run later).

Public API:
    Constructor(design, context=None, validate=True)
"""

# Size exception (>300 lines): the facade owns one mutable build state
# (`_compiled`, `_values`, `_merged`, `_donor_registry`) whose transitions are
# the contract of `test()`. Splitting the class would duplicate that state and
# let a caller observe a half-updated one; the phase work already lives in
# `build_paths`, `rows` and `validate`.

from __future__ import annotations

import copy
import json
from pathlib import Path

from agentic_bi import validate_pbix
from agentic_bi.constructor.blocks import BLOCKS
from agentic_bi.constructor.build_paths import (
    build_donor as _build_donor,
)
from agentic_bi.constructor.build_paths import (
    build_engine as _build_engine,
)
from agentic_bi.constructor.build_paths import (
    build_from_data as _build_from_data,
)
from agentic_bi.constructor.design import Design
from agentic_bi.constructor.issues import (
    DesignError,
    Issue,
    has_errors,
    raise_for_errors,
)
from agentic_bi.constructor.layout import CompiledLayout, compile_design
from agentic_bi.constructor.model_context import ModelContext
from agentic_bi.constructor.report import TestReport
from agentic_bi.constructor.validate import validate_design
from agentic_bi.engine import verify as engine_verify


def layout_path_for(out: Path) -> Path:
    """Where a layout-only build writes its JSON, chosen by the output suffix."""
    if out.suffix.lower() == ".json":
        return out
    if out.suffix.lower() == ".pbix":
        return out.with_suffix(".layout.json")
    return out / "layout.json"


class Constructor:
    """Assemble a dashboard from a declarative design and verify the artifact."""

    def __init__(
        self,
        design: Design | dict | str | Path,
        context: ModelContext | dict | None = None,
        *,
        validate: bool = True,
    ) -> None:
        if isinstance(design, Design):
            self.design = copy.deepcopy(design)
        elif isinstance(design, (str, Path)):
            self.design = Design.load(design)
        else:
            self.design = Design.from_dict(design)
        if context is not None:
            model = (
                context
                if isinstance(context, ModelContext)
                else ModelContext.from_dict(context)
            )
            self.design.model = copy.deepcopy(model)
        self._issues = validate_design(self.design)
        if validate:
            raise_for_errors(self._issues)
        self._compiled: CompiledLayout | None = None
        self._values: dict[str, list[dict[str, object]]] | None = None
        self._merged = False
        self._donor_registry: dict[str, dict[str, list[str]]] | None = None

    # -- design -------------------------------------------------------------
    @property
    def issues(self) -> list[Issue]:
        """Every validation finding (errors and warnings) of the design."""
        return list(self._issues)

    def invalidate(self) -> None:
        """Drop the compiled layout after the design was edited by hand."""
        self._compiled = None
        self._issues = validate_design(self.design)

    def validate_or_raise(self) -> None:
        """Raise `DesignError` when the design has errors."""
        raise_for_errors(self._issues)

    @property
    def compiled(self) -> CompiledLayout:
        """The compiled layout (built once, then cached)."""
        if self._compiled is None:
            self._compiled = compile_design(self.design)
        return self._compiled

    def layout(self) -> dict:
        """Return `Report/Layout` as a dict (nothing is written)."""
        return self.compiled.layout

    def layout_bytes(self) -> bytes:
        """Return `Report/Layout` encoded for the `.pbix` container."""
        return self.compiled.layout_bytes()

    def expected_pages(self) -> dict[str, int]:
        """Return the visual count per page that verification should find."""
        return self.compiled.page_counts()

    def expected_types(self) -> set[str]:
        """Return the engine visual types this design produces."""
        return {BLOCKS[kind].visual_type for kind in self.design.kinds()}

    def preview(self) -> dict[str, object]:
        """Return a compact placement preview (no artifact is built)."""
        compiled = self.compiled
        return {
            "name": self.design.name,
            "pages": [
                {
                    "name": page.name,
                    "title": page.title,
                    "width": page.width,
                    "height": page.height,
                    "visuals": [
                        {
                            "id": visual.block_id,
                            "kind": visual.kind,
                            "table": visual.table,
                            "pos": list(compiled.positions.get(visual.block_id, ())),
                        }
                        for visual in page.visuals
                    ],
                }
                for page in self.design.pages
            ],
        }

    def spec(
        self,
        values: dict[str, list[dict[str, object]]] | None = None,
        *,
        engine: bool = False,
    ) -> dict[str, object]:
        """Return the engine spec derived from the model context."""
        return self.design.model.to_spec(values, include_empty_measures=not engine)

    # -- build --------------------------------------------------------------
    def preflight(self, donor: str | Path) -> list[Issue]:
        """Compare the design with the donor's *actual* model before building.

        Closes the "the reference is in the context but not in the donor" class:
        such a `.pbix` opens, yet its visuals render blank. An unreadable donor
        model is a warning, not a blocker.
        """
        if not self.design.model.tables:
            return []
        try:
            real = ModelContext.from_pbix(Path(donor))
        except (OSError, ValueError) as exc:
            return [
                Issue(
                    "warning",
                    "donor_unreadable",
                    f"cannot read the donor model: {exc}",
                    "donor",
                )
            ]
        self._donor_registry = real.registry()
        issues: list[Issue] = []
        for page in self.design.pages:
            for visual in page.visuals:
                table = real.tables.get(visual.table)
                path = f"pages[{page.name}].visuals[{visual.block_id}]"
                if table is None:
                    issues.append(
                        Issue(
                            "error",
                            "donor_unknown_table",
                            f"table {visual.table!r} is not in the donor model",
                            path,
                        )
                    )
                    continue
                for column in [
                    *visual.columns,
                    *visual.extra_values,
                    visual.axis,
                    visual.value,
                ]:
                    if column and column not in table.columns:
                        issues.append(
                            Issue(
                                "error",
                                "donor_unknown_column",
                                f"{visual.table}.{column} is not in the donor model",
                                path,
                            )
                        )
                if visual.measure and visual.measure not in table.measures:
                    issues.append(
                        Issue(
                            "error",
                            "donor_unknown_measure",
                            f"{visual.table}.{visual.measure} is not a donor measure",
                            path,
                        )
                    )
        return issues

    def build_donor(
        self,
        donor: str | Path,
        out: str | Path,
        *,
        keep_donor_pages: bool = False,
        skip_preflight: bool = False,
    ) -> Path:
        """Build a `.pbix` on the donor's model (offline, no Desktop).

        Args:
            donor: a working `.pbix` that supplies the DataModel.
            out: where to write the result.
            keep_donor_pages: keep the donor pages and append this design's.
            skip_preflight: do not compare the design with the donor model.
        """
        self._merged = keep_donor_pages
        self._values = None
        self._donor_registry = None
        if not skip_preflight:
            try:
                raise_for_errors(self.preflight(donor))
            except DesignError:
                self._donor_registry = None
                raise
        try:
            return _build_donor(
                self.compiled, donor, out, keep_donor_pages=keep_donor_pages
            )
        except Exception:
            self._merged = False
            raise

    def build_engine(
        self, template: str | Path, datamodel: bytes | str | Path, out: str | Path
    ) -> Path:
        """Build a `.pbix` from a ready DataModel and this design's layout."""
        self._values = None
        self._merged = False
        self._donor_registry = None
        return _build_engine(self.compiled, template, datamodel, out)

    def build_from_data(
        self,
        data: object,
        template: str | Path,
        out: str | Path,
        *,
        table: str | None = None,
        desktop: str | None = None,
        work_dir: str | Path | None = None,
    ) -> Path:
        """Build the DataModel from rows in the Desktop engine, then the `.pbix`."""
        self._merged = False
        self._donor_registry = None
        result = _build_from_data(
            self.design,
            self.compiled,
            data,
            template,
            out,
            table=table,
            desktop=desktop,
            work_dir=work_dir,
        )
        return result

    # -- tests --------------------------------------------------------------
    def design_report(self) -> TestReport:
        """Return a report of design validation only (no artifact needed)."""
        report = TestReport(
            title=f"Constructor: {self.design.name}",
            meta={
                "pages": len(self.design.pages),
                "visuals": self.design.visual_count(),
                "model_tables": len(self.design.model.tables),
            },
        )
        for issue in self._issues:
            report.add(
                "design",
                f"{issue.code} @ {issue.path}".strip(),
                issue.severity != "error",
                issue.message,
                critical=issue.severity == "error",
                level=issue.severity,
            )
        return report

    def test(
        self,
        pbix: str | Path,
        *,
        model: bool = False,
        brand: bool = False,
        layout_checks: bool = True,
        check_registry: bool = True,
        expected_pages: dict[str, int] | None = None,
        merged: bool | None = None,
    ) -> TestReport:
        """Run the reverse checks of an artifact and return one report.

        Args:
            pbix: the built `.pbix`.
            model: read the model back (pbixray; slow).
            brand: compare the theme with the brand book.
            layout_checks: check layout and bindings; off for a merged donor
                build, whose other pages need not reference this context.
            check_registry: compare the whole layout with the context registry.
            expected_pages: expected visual count per page; the design's pages by
                default.
            merged: donor pages were kept; the last build's flag by default.
        """
        path = Path(pbix)
        if merged is None:
            merged = self._merged
        if merged:
            layout_checks = False
        report = self.design_report()
        report.meta.update(
            {
                "artifact": str(path),
                "model": "read-back" if model else "layout-only",
                "spec": "values" if self._values else "model-only",
                "merged": merged,
            }
        )
        if has_errors(self._issues):
            return report
        try:
            layout = engine_verify.load_layout(path)
        except (FileNotFoundError, ValueError) as exc:
            report.add("pbix", "layout readable", False, str(exc))
            return report
        registry = self._donor_registry or self.design.model.registry()
        registry_ok = (not merged) or bool(self._donor_registry)
        if check_registry and registry and registry_ok:
            problems = validate_pbix.validate_layout(layout, registry)
            report.add(
                "registry",
                "layout matches model context",
                not problems,
                "; ".join(problems[:5]),
            )
        pages = (
            expected_pages
            if expected_pages is not None
            else self.expected_pages()
            if layout_checks
            else None
        )
        verify = engine_verify.verify_pbix(
            path,
            self.spec(self._values),
            pages=pages,
            model=model,
            layout_checks=layout_checks,
            expected_types=self.expected_types(),
            brand=brand,
        )
        for check in verify.checks:
            report.add(
                "pbix", check.name, check.ok, check.detail, critical=check.critical
            )
        if merged:
            titles = {page.title for page in self.design.pages}
            own = {
                "sections": [
                    section
                    for section in layout.get("sections", [])
                    if section.get("displayName") in titles
                ]
            }
            for check in engine_verify.verify_bindings(own, self.spec(self._values)):
                report.add(
                    "merged",
                    check.name,
                    check.ok,
                    check.detail,
                    critical=check.critical,
                )
        return report

    def build_and_test(
        self,
        out: str | Path,
        *,
        donor: str | Path | None = None,
        template: str | Path | None = None,
        datamodel: bytes | Path | None = None,
        data: object | None = None,
        table: str | None = None,
        desktop: str | None = None,
        work_dir: str | Path | None = None,
        keep_donor_pages: bool = False,
        skip_preflight: bool = False,
        model: bool = False,
        brand: bool = False,
        report_path: str | Path | None = None,
    ) -> TestReport:
        """Build an artifact (donor / engine / data / layout-only) and test it.

        With no source, the design is only compiled: the layout JSON is written
        next to `out` and the report records its path.
        """
        target = Path(out)
        if data is not None:
            if template is None:
                raise ValueError("template= is required for data assembly")
            self.build_from_data(
                data,
                template,
                target,
                table=table,
                desktop=desktop,
                work_dir=work_dir,
            )
        elif datamodel is not None:
            if template is None:
                raise ValueError("template= is required for datamodel assembly")
            self.build_engine(template, datamodel, target)
        elif donor is not None:
            self.build_donor(
                donor,
                target,
                keep_donor_pages=keep_donor_pages,
                skip_preflight=skip_preflight,
            )
        else:
            layout_path = layout_path_for(target)
            layout_path.parent.mkdir(parents=True, exist_ok=True)
            layout_path.write_text(
                json.dumps(self.layout(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            report = self.design_report()
            report.meta["layout"] = str(layout_path)
            report.add(
                "layout",
                "design compiled",
                True,
                f"{len(self.design.pages)} pages, {self.design.visual_count()} visuals",
            )
            if report_path:
                report.write(report_path)
            return report
        merged = bool(donor is not None and keep_donor_pages)
        report = self.test(target, model=model, brand=brand, layout_checks=not merged)
        if report_path:
            report.write(report_path)
        return report


__all__ = ["Constructor", "DesignError", "layout_path_for"]
