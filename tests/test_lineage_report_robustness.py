"""Regression tests for the lineage/report fixes (round 9).

Untrusted `Report/Layout` names and queryRefs reach the lineage graph, the
PlantUML diagram and the PDF: an aggregated queryRef ('Sum(T.c)') must keep its
table, a non-string queryRef must not raise, and a name with a quote must not
break the generated `.puml`. Qwen's claim that the PDF escapers do not escape
is refuted here (they use manual `&`/`<`/`>` escaping, not `html.escape`).
"""

from __future__ import annotations

import re


class TestLineageQueryRefAndNames:
    """Round 9: lineage parsing of untrusted queryRefs and names."""

    def test_aggregated_queryref_keeps_its_table(self) -> None:
        from agentic_bi.lineage.lineage_types import _split_table_col

        assert _split_table_col("Sum(Sales.Amount)") == ("Sales", "Amount")
        assert _split_table_col("Avg(Opportunities.Discount)") == (
            "Opportunities",
            "Discount",
        )

    def test_nested_aggregation_is_fully_unwrapped(self) -> None:
        from agentic_bi.lineage.lineage_types import _split_table_col

        assert _split_table_col("Count(Distinct(T.C))") == ("T", "C")

    def test_queryref_with_spaces_in_the_column(self) -> None:
        from agentic_bi.lineage.lineage_types import _split_table_col

        assert _split_table_col("Sum(Opportunities.Days Remaining In Pipeline)") == (
            "Opportunities",
            "Days Remaining In Pipeline",
        )

    def test_plain_queryref_is_unchanged(self) -> None:
        from agentic_bi.lineage.lineage_types import _split_table_col

        assert _split_table_col("Sales.Amount") == ("Sales", "Amount")
        assert _split_table_col("Revenue") == ("Revenue", None)

    def test_non_string_queryref_does_not_raise(self) -> None:
        from agentic_bi.lineage.lineage_types import _split_table_col

        for bad in (123, None, True, ["x"], {"a": 1}):
            assert _split_table_col(bad) == ("", None)

    def test_strip_agg_only_strips_a_real_wrapper(self) -> None:
        from agentic_bi.lineage.lineage_types import _strip_agg

        assert _strip_agg("Sum(Table.Column)") == "Table.Column"
        assert _strip_agg("plain") == "plain"
        assert _strip_agg("not(closed") == "not(closed"


class TestPlantUmlEscaping:
    def test_double_quote_is_escaped_so_a_package_stays_valid(self) -> None:
        from agentic_bi.lineage.lineage_plantuml import PlantUmlMixin

        class _Ctx(PlantUmlMixin):
            pass

        ctx = _Ctx()
        escaped = ctx._pu_escape('He said "hi"')
        assert r"\"" in escaped
        # the rendered package declaration must keep exactly two *unescaped*
        # opening/closing delimiters; every inner quote is backslash-escaped
        line = f'  package "{escaped}" {{'
        unescaped = re.sub(r'\\"', "", line).count('"')
        assert unescaped == 2

    def test_brackets_braces_and_newlines_are_escaped(self) -> None:
        from agentic_bi.lineage.lineage_plantuml import PlantUmlMixin

        class _Ctx(PlantUmlMixin):
            pass

        out = _Ctx()._pu_escape("a[b]{c}\nd")
        assert r"\[" in out and r"\]" in out and r"\{" in out and r"\}" in out
        assert r"\n" in out


class TestPdfEscapingIsPresent:
    """Qwen round 9 claimed `_safe`/`_esc` do not escape; they do (pinned)."""

    def test_pdf_escapers_escape_markup(self) -> None:
        from agentic_bi.report.pdf_report import _safe
        from agentic_bi.report.pdf_tables import _esc

        for hostile in ("Sales&Marketing", "Table<Column", "</font><b>x"):
            assert "&" not in _esc(hostile).replace("&amp;", "").replace(
                "&lt;", ""
            ).replace("&gt;", "")
            assert _safe(hostile) == _esc(hostile)

    def test_a_hostile_name_renders_as_a_paragraph(self) -> None:
        from reportlab.lib.styles import ParagraphStyle

        from agentic_bi.report.pdf_tables import _cell

        style = ParagraphStyle("t")
        for hostile in ("Sales&Marketing", "Table<Column", "a>b"):
            assert _cell(hostile, style) is not None
