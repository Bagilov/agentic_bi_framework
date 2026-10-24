"""Regression tests for the publication gate fixes (brand audit + `.pbix` verify).

Each test pins one measured defect that could turn the gate false-green or crash
it on a real report:

- `luminance`/`contrast` used to raise on a non-hex colour (unknown background);
- an unknown background used to be treated as white, silently passing a
  light-on-dark contrast violation;
- `font_weight` used to miss "Extra Bold" split by a space;
- `Report/Layout` was decoded as UTF-16LE only, so a UTF-8 layout crashed;
- decorative visuals (`shape`/`textbox`/...) used to fail "all visuals have
  projections", and a `singleVisualGroup` container used to raise `KeyError`.
"""

from __future__ import annotations

import json
import zipfile

import pytest

from agentic_bi.brand_audit_eval import evaluate_observations
from agentic_bi.brand_audit_extract import Observation
from agentic_bi.brand_audit_math import contrast, font_weight, is_neutral, luminance
from agentic_bi.brand_audit_types import AuditReport
from agentic_bi.brand_config import BrandConfig
from agentic_bi.engine_verify_checks import verify_bindings, verify_layout
from agentic_bi.engine_verify_core import load_layout
from agentic_bi.layout_meta import (
    DECORATIVE_VISUAL_TYPES,
    decode_layout,
    decode_layout_with_encoding,
    iter_layout_visuals,
)
from agentic_bi.visual_check import check_layout


def _layout_with(containers: list[dict]) -> dict:
    return {"sections": [{"displayName": "P", "visualContainers": containers}]}


def _container(cfg: dict) -> dict:
    return {"config": json.dumps(cfg), "filters": "[]"}


class TestColorMathIsStrictNotCrashing:
    def test_luminance_raises_on_non_hex(self) -> None:
        for bad in ("", "nope", "rgb(1,2,3)", "#12345"):
            with pytest.raises(ValueError):
                luminance(bad)

    def test_contrast_raises_on_non_hex(self) -> None:
        with pytest.raises(ValueError):
            contrast("#000000", "not-a-color")

    def test_is_neutral_is_false_not_an_error_on_non_hex(self) -> None:
        assert is_neutral("nope") is False

    def test_font_weight_ignores_separators(self) -> None:
        assert font_weight("Brand Sans Extra Bold") == "extrabold"
        assert font_weight("BrandSans-ExtraBold") == "extrabold"
        assert font_weight("Brand Sans ExtraBold") == "extrabold"


class TestUnknownBackgroundIsReportedNotAssumedWhite:
    # A light chromatic colour: low contrast against white, so the difference
    # between "assume white" and "report un-assessed" is observable.
    _LIGHT = "#EECC00"

    def test_unknown_background_yields_a_finding_instead_of_a_silent_pass(
        self,
    ) -> None:
        rep = AuditReport(path="x")
        obs = [Observation("text_color", self._LIGHT, "slide 1 / body")]
        evaluate_observations(obs, BrandConfig.default(), rep)
        # A light text on an unknown (possibly light) background must not pass
        # silently: it is flagged as un-assessed, not compared against white.
        contrast_findings = [f for f in rep.findings if f.rule_id == "BG-CONTRAST"]
        assert len(contrast_findings) == 1
        assert "could not be assessed" in contrast_findings[0].message

    def test_known_background_measures_contrast(self) -> None:
        rep = AuditReport(path="x")
        obs = [
            Observation("text_color", self._LIGHT, "slide 1 / body"),
            Observation("background", "#FFFFFF", "slide 1 / background"),
        ]
        evaluate_observations(obs, BrandConfig.default(), rep)
        contrast_findings = [f for f in rep.findings if f.rule_id == "BG-CONTRAST"]
        assert len(contrast_findings) == 1
        assert "could not be assessed" not in contrast_findings[0].message

    def test_neutral_text_is_not_contrast_checked(self) -> None:
        rep = AuditReport(path="x")
        obs = [Observation("text_color", "#000000", "slide 1 / body")]
        evaluate_observations(obs, BrandConfig.default(), rep)
        assert "BG-CONTRAST" not in [f.rule_id for f in rep.findings]


class TestLayoutDecoding:
    def test_decodes_utf16le_without_bom(self) -> None:
        raw = json.dumps({"sections": []}).encode("utf-16-le")
        assert decode_layout(raw) == {"sections": []}
        assert decode_layout_with_encoding(raw)[1] == "utf-16le"

    def test_decodes_utf16_with_bom(self) -> None:
        raw = json.dumps({"sections": []}).encode("utf-16")
        assert decode_layout(raw) == {"sections": []}

    def test_decodes_utf8_layout(self) -> None:
        raw = json.dumps({"sections": []}).encode("utf-8")
        assert decode_layout(raw) == {"sections": []}

    def test_undecodable_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            decode_layout(b"\x00\x01not json at all")

    def test_load_layout_reads_a_utf8_layout_from_a_pbix(self, tmp_path) -> None:
        pbix = tmp_path / "utf8.pbix"
        payload = json.dumps({"sections": []}).encode("utf-8")
        with zipfile.ZipFile(pbix, "w") as z:
            z.writestr("Report/Layout", payload)
        assert load_layout(pbix) == {"sections": []}


class TestDecorativeVisualsAndGroups:
    def test_decorative_visuals_need_no_projections(self) -> None:
        layout = _layout_with(
            [
                _container({"singleVisual": {"visualType": vt}})
                for vt in ("shape", "textbox", "image", "pageNavigator")
            ]
        )
        checks = {c.name: c.ok for c in verify_layout(layout, {})}
        assert checks["all data visuals have projections"] is True

    def test_data_visual_without_projections_still_fails(self) -> None:
        layout = _layout_with([_container({"singleVisual": {"visualType": "card"}})])
        check = next(
            c
            for c in verify_layout(layout, {})
            if c.name == "all data visuals have projections"
        )
        assert check.ok is False

    def test_single_visual_group_is_skipped_not_a_keyerror(self) -> None:
        layout = _layout_with(
            [
                _container({"singleVisualGroup": {"displayName": "G"}}),
                _container({"singleVisual": {"visualType": "card"}}),
            ]
        )
        assert len(list(iter_layout_visuals(layout))) == 2
        assert verify_layout(layout, {})

    def test_container_without_config_is_skipped(self) -> None:
        layout = _layout_with(
            [{"x": 1}, _container({"singleVisual": {"visualType": "shape"}})]
        )
        assert len(list(iter_layout_visuals(layout))) == 1

    def test_static_checker_accepts_decorative_visuals(self) -> None:
        layout = _layout_with(
            [
                _container({"singleVisual": {"visualType": "shape"}}),
                _container({"singleVisualGroup": {"displayName": "G"}}),
            ]
        )
        assert not [
            e
            for e in check_layout(layout, {})
            if "has no projections" in e or "no visualType" in e
        ]

    def test_decorative_set_is_the_single_source_of_truth(self) -> None:
        from agentic_bi.web_report.web_checks import NON_DATA_TYPES

        assert NON_DATA_TYPES is DECORATIVE_VISUAL_TYPES


class TestBindingNameCase:
    def test_table_case_mismatch_is_not_a_false_positive(self) -> None:
        qref = "Sum(sales.amount)"
        cfg = {
            "singleVisual": {
                "visualType": "card",
                "projections": {"Values": [{"queryRef": qref}]},
                "prototypeQuery": {
                    "From": [{"Name": "t", "Entity": "sales"}],
                    "Select": [{"Name": qref}],
                },
            }
        }
        layout = _layout_with([_container(cfg)])
        spec = {
            "tables": [{"name": "Sales", "columns": [{"name": "amount"}]}],
            "measures": [],
        }
        assert [c.ok for c in verify_bindings(layout, spec)] == [True]

    def test_column_case_mismatch_is_not_a_false_positive(self) -> None:
        qref = "Sum(Sales.AMOUNT)"
        cfg = {
            "singleVisual": {
                "visualType": "card",
                "projections": {"Values": [{"queryRef": qref}]},
                "prototypeQuery": {
                    "From": [{"Name": "t", "Entity": "Sales"}],
                    "Select": [{"Name": qref}],
                },
            }
        }
        layout = _layout_with([_container(cfg)])
        spec = {
            "tables": [{"name": "Sales", "columns": [{"name": "amount"}]}],
            "measures": [],
        }
        assert [c.ok for c in verify_bindings(layout, spec)] == [True]

    def test_missing_table_still_fails(self) -> None:
        qref = "Sum(Nope.amount)"
        cfg = {
            "singleVisual": {
                "visualType": "card",
                "projections": {"Values": [{"queryRef": qref}]},
                "prototypeQuery": {
                    "From": [{"Name": "t", "Entity": "Nope"}],
                    "Select": [{"Name": qref}],
                },
            }
        }
        layout = _layout_with([_container(cfg)])
        spec = {
            "tables": [{"name": "Sales", "columns": [{"name": "amount"}]}],
            "measures": [],
        }
        assert [c.ok for c in verify_bindings(layout, spec)] == [False]


class TestUnresolvedPaintIsReported:
    def test_unresolved_paint_becomes_a_finding_not_a_silent_skip(self) -> None:
        rep = AuditReport(path="x")
        obs = [
            Observation(
                "unresolved_paint",
                "",
                "slide 1 / shape 'X' / fill",
                "fill type GRADIENT",
            )
        ]
        evaluate_observations(obs, BrandConfig.default(), rep)
        assert "PAINT-UNRESOLVED" in [f.rule_id for f in rep.findings]

    def test_paint_unresolved_is_in_the_rule_catalog(self) -> None:
        from agentic_bi.brand_rules import rule_catalog

        assert any(r["id"] == "PAINT-UNRESOLVED" for r in rule_catalog("color"))


class TestThemePathIsHardenedToo:
    def test_theme_with_non_hex_color_does_not_raise(self) -> None:
        from agentic_bi.brand import check_brand_compliance

        report = check_brand_compliance(
            colors={"visual_0": "#D32F2F", "x": "rgb(1,2,3)"},
            fonts=["Brand Sans"],
            background="#ffffff",
            text_color="#000000",
            has_logo=False,
        )
        assert "findings" in report

    def test_non_hex_text_color_reports_un_assessed_contrast(self) -> None:
        from agentic_bi.brand import check_brand_compliance

        report = check_brand_compliance(
            colors={"visual_0": "#D32F2F"},
            fonts=["Brand Sans"],
            background="#ffffff",
            text_color="rgb(0,0,0)",
            has_logo=False,
        )
        contrast = [f for f in report["findings"] if f["rule_id"] == "BG-CONTRAST"]
        assert contrast and "could not be assessed" in contrast[0]["message"]

    def test_luminance_still_raises_on_non_hex(self) -> None:
        from agentic_bi.brand_eval_background import contrast_ratio

        with pytest.raises(ValueError):
            contrast_ratio("nope", "#ffffff")
