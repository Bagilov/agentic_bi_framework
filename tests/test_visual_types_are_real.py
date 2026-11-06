"""Every generated visualType must be one Power BI Desktop actually renders.

The gallery once emitted `stackedColumnChart`/`stackedBarChart`. Desktop has no
such built-in visual: it treats the name as an uninstalled *custom* visual and
renders «Visual error: … add it to this report first: stackedColumnChart». That
was found by reading the guest window's automation tree, not by looking at a
screenshot: a board built from the rich example showed exactly one such row while
all other 17 visuals rendered.

The same round of measurement showed the real `templates/template.pbix` board
must stay certifiable: it uses `barChart` with a `Rows` projection and several
composite/custom visuals (`lineStackedColumnComboChart`, `ribbonChart`,
`keyDriversVisual`, `decompositionTreeVisual`, `FlowVisual_*`) whose roles are
outside the built-in catalogue.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from agentic_bi import visual_check
from agentic_bi.engine import layout as engine_layout
from agentic_bi.engine.layout_visual import _VISUAL_TYPES
from agentic_bi.web_report import web_mock

# Desktop rejects these names (measured on the guest: one "Visual error" each).
INVENTED = ("stackedColumnChart", "stackedBarChart")
PACKAGE_ROOT = Path(engine_layout.__file__).parents[1]
REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = REPO_ROOT / "templates" / "template.pbix"
SOURCE_ROOTS = (PACKAGE_ROOT, REPO_ROOT / "examples", REPO_ROOT / "tests")
SOURCE_SUFFIXES = (".py", ".json", ".yaml", ".yml", ".toml", ".html", ".ts", ".tsx")
SKIPPED_PARTS = frozenset({"build", "node_modules", ".venv", "__pycache__", "other"})
SELF = Path(__file__).resolve()

GALLERY_COLUMNS = [
    {"name": "region", "type": "string"},
    {"name": "product", "type": "string"},
    {"name": "amount", "type": "double"},
    {"name": "qty", "type": "int64"},
    {"name": "sale_date", "type": "date"},
]


def _registry_from_layout(layout: dict) -> dict:
    """Model objects the layout itself references.

    The report's TMDL model is not parsed here (no `pbixray` dependency), so the
    registry is derived from the report's own `prototypeQuery.Select` items:
    table/column/measure membership becomes tautological, while role, type and
    queryRef checks stay real - which is what these regressions cover.
    """
    registry: dict[str, dict[str, set[str]]] = {}
    for _, single in _visuals(layout):
        query = single.get("prototypeQuery") or {}
        aliases = {f.get("Name"): f.get("Entity") for f in (query.get("From") or [])}
        for select in query.get("Select") or []:
            if not isinstance(select, dict):
                continue
            for kind, bucket in (("Column", "columns"), ("Measure", "measures")):
                if kind in select:
                    spec = select[kind]
                    source = spec.get("Expression", {}).get("SourceRef") or {}
                    entity = aliases.get(source.get("Source")) or source.get("Entity")
                    _add(registry, entity, bucket, spec.get("Property"))
            if "Aggregation" in select:
                col = (select["Aggregation"].get("Expression") or {}).get("Column")
                if not col:
                    continue
                source = col.get("Expression", {}).get("SourceRef") or {}
                entity = aliases.get(source.get("Source")) or source.get("Entity")
                _add(registry, entity, "columns", col.get("Property"))
    return {
        k: {b: sorted(v) for b, v in buckets.items()} for k, buckets in registry.items()
    }


def _visuals(layout: dict) -> list[tuple[str, dict]]:
    """`(sec{i}/vis{j}, singleVisual)` for every visual container of a layout."""
    return [
        (
            f"sec{si}/vis{vi}",
            json.loads(vc.get("config", "{}") or "{}").get("singleVisual") or {},
        )
        for si, sec in enumerate(layout.get("sections", []))
        for vi, vc in enumerate(sec.get("visualContainers", []))
    ]


def _add(registry: dict, entity: str | None, bucket: str, prop: str | None) -> None:
    if entity is None or prop is None:
        return
    registry.setdefault(entity, {}).setdefault(bucket, set()).add(prop)


@pytest.mark.skipif(not TEMPLATE.exists(), reason="donor template is absent")
class TestTemplateSampleIsCertifiable:
    """The repository's own donor board must not be rejected by the validator."""

    def _errors(self) -> tuple[dict, list[str]]:
        layout = visual_check.layout_from_pbix(TEMPLATE)
        return layout, visual_check.check_layout(layout, _registry_from_layout(layout))

    def test_bar_chart_rows_role_is_accepted(self) -> None:
        # Regression: `Rows` was dropped from ALLOWED["barChart"], so the donor's
        # sec4/vis1 (page "Pipeline Trends") failed with "role 'Rows' not
        # allowed" although the sample carries it next to Category + Y.
        layout, errors = self._errors()
        rows_bar = [
            where
            for where, single in _visuals(layout)
            if single.get("visualType") == "barChart"
            and "Rows" in (single.get("projections") or {})
        ]
        assert rows_bar, "the donor no longer exercises barChart+Rows; fix the guard"
        assert [e for e in errors if "barChart role 'Rows'" in e] == []

    def test_composite_and_custom_types_are_not_unknown(self) -> None:
        layout, errors = self._errors()
        emitted = {single.get("visualType") for _, single in _visuals(layout)}
        composite = {
            "lineStackedColumnComboChart",
            "ribbonChart",
            "keyDriversVisual",
            "decompositionTreeVisual",
        }
        assert composite <= emitted, "the donor no longer exercises composite visuals"
        assert any(
            isinstance(name, str) and name.startswith("FlowVisual_") for name in emitted
        )
        assert [e for e in errors if "unknown visualType" in e] == []

    def test_an_unknown_builtin_type_is_still_an_error(self) -> None:
        layout = {
            "sections": [
                {
                    "visualContainers": [
                        {
                            "config": json.dumps(
                                {"singleVisual": {"visualType": "inventedVisual"}}
                            ),
                            "filters": "[]",
                        }
                    ]
                }
            ]
        }
        errors = visual_check.check_layout(layout, {})
        assert "sec0/vis0: unknown visualType 'inventedVisual'" in errors


class TestLayoutFromPbixErrors:
    def test_missing_report_layout_raises_value_error(self, tmp_path: Path) -> None:
        import zipfile

        broken = tmp_path / "broken.pbix"
        with zipfile.ZipFile(broken, "w") as zf:
            zf.writestr("Version", "1.0")
        with pytest.raises(ValueError, match="Report/Layout is missing"):
            visual_check.layout_from_pbix(broken)

    def test_a_real_pbix_opens_without_leaking_the_archive(self) -> None:
        if not TEMPLATE.exists():
            pytest.skip("donor template is absent")
        assert visual_check.layout_from_pbix(TEMPLATE)


class TestNoInventedVisualTypes:
    """The invented stacked names are gone from every producer."""

    def test_engine_mapping_shares_charts_with_their_plain_kind(self) -> None:
        assert _VISUAL_TYPES["stackedColumn"] == "columnChart"
        assert _VISUAL_TYPES["stackedBar"] == "barChart"
        assert _VISUAL_TYPES["column"] == "clusteredColumnChart"
        assert _VISUAL_TYPES["bar"] == "clusteredBarChart"

    def test_no_mapping_value_is_an_invented_name(self) -> None:
        assert not set(_VISUAL_TYPES.values()) & set(INVENTED)

    def test_web_mock_does_not_know_the_invented_names(self) -> None:
        assert not set(web_mock._CATEGORY) & set(INVENTED)

    def test_web_mock_still_maps_the_real_containers(self) -> None:
        assert web_mock.category("columnChart") == "column"
        assert web_mock.category("clusteredColumnChart") == "column"
        assert web_mock.category("barChart") == "bar"
        assert web_mock.category("clusteredBarChart") == "bar"

    def test_visual_check_does_not_accept_the_invented_names(self) -> None:
        for name in INVENTED:
            assert name not in visual_check.ALLOWED
            assert name not in visual_check.REQUIRED


class TestGalleryTypesAreReal:
    """Every gallery visual maps to a type the validator recognises."""

    def test_all_gallery_visuals_pass_the_role_tables(self) -> None:
        visuals = engine_layout.gallery_visuals("Sales", GALLERY_COLUMNS)
        kinds = {v.kind for v in visuals}
        assert {"stackedColumn", "stackedBar"} <= kinds
        for v in visuals:
            vtype = _VISUAL_TYPES[v.kind]
            assert vtype in visual_check.ALLOWED, f"{v.kind} -> unknown {vtype}"
            required = visual_check.REQUIRED.get(vtype, [])
            assert required, f"{v.kind} -> {vtype} has no REQUIRED roles"
            allowed = visual_check.ALLOWED[vtype]
            assert set(required) <= allowed, f"{v.kind} -> {required} not in {allowed}"

    def test_gallery_titles_do_not_advertise_a_missing_visual(self) -> None:
        columns = [
            {"name": "region", "type": "string"},
            {"name": "amount", "type": "double"},
        ]
        titles = [
            v.title or "" for v in engine_layout.gallery_visuals("Sales", columns)
        ]
        joined = " ".join(titles)
        for name in INVENTED:
            assert name not in joined


class TestSkeletonStackedVisualUsesARealType:
    """The skeleton builder emits a type Desktop renders."""

    def test_stacked_visual_type_is_column_chart(self) -> None:
        from agentic_bi.skeleton import visuals_extra

        axis = {"kind": "column", "property": "region", "display": "Region"}
        value = {"kind": "measure", "property": "Total", "display": "Total"}
        container = visuals_extra.stacked_visual(axis, value, None, "Sales")
        config = container.get("config", container)
        if isinstance(config, str):
            config = json.loads(config)
        assert config["singleVisual"]["visualType"] == "columnChart"


def _emitted_strings(path: Path) -> list[str]:
    """String literals of a Python file, excluding docstrings.

    Docstrings/comments may legitimately *discuss* the invented names; a string
    constant can reach `Report/Layout`, so only constants are inspected. This
    sees f-strings and concatenations that a quoted-literal regex missed.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    docstrings: set[int] = set()
    body_owners = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(node, body_owners) or not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
            docstrings.add(id(first.value))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def test_no_source_file_emits_an_invented_name() -> None:
    offenders: list[tuple[str, str]] = []
    for root in SOURCE_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if (
                not path.is_file()
                or path.suffix not in SOURCE_SUFFIXES
                or path.resolve() == SELF
                or SKIPPED_PARTS & set(path.parts)
            ):
                continue
            if path.suffix == ".py":
                payloads = _emitted_strings(path)
            else:
                payloads = [path.read_text(encoding="utf-8")]
            for payload in payloads:
                for name in INVENTED:
                    if name in payload:
                        offenders.append((str(path.relative_to(REPO_ROOT)), name))
    assert offenders == []


def test_docs_do_not_advertise_an_invented_type() -> None:
    offenders = []
    for path in (REPO_ROOT / "docs").glob("*.md"):
        text = path.read_text(encoding="utf-8")
        for name in INVENTED:
            if name in text:
                offenders.append((path.name, name))
    assert offenders == []
