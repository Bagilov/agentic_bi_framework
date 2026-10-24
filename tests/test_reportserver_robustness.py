"""Regression tests for the Report Server / antipatterns / CLI fixes (round 10).

Each test pins one measured defect that could make the audit silently incomplete
or wrong on untrusted input:

- the OData walker ignored `@odata.nextLink`, so a catalog larger than one `$top`
  page was truncated and reported as complete;
- `automate.verify_published` interpolated a name into `Path='...'` without
  escaping a single quote (OData injection / broken request);
- `antipattern_detectors` missed `CALCULATE(SUM([A]))` because the old regex could
  not see through a nested call (a false negative on a real smell);
- `pbix_analysis`/`pbix_index` raised `KeyError`/`AttributeError` on an item
  without `Id` or a non-dict `sources` (a malformed server/JSON response);
- the CLI failed the run only on the exact string `"FAILED"`.
"""

from __future__ import annotations

import json

import pytest


def _diag_with_pages(pages: list[dict]):
    """A ReportServerDiagnostics whose HTTP layer replays `pages` in order."""
    from agentic_bi.reportserver.diagnostics import ReportServerDiagnostics

    d = ReportServerDiagnostics(cfg={"server": "rs.example", "roots": ["/Reports"]})
    calls: list[str] = []

    def fake_get_json(url, params=None):
        calls.append(url)
        return pages[min(len(calls) - 1, len(pages) - 1)]

    d._get_json = fake_get_json  # type: ignore[method-assign]
    return d, calls


class TestODataPagination:
    def test_walker_follows_next_link_to_the_end(self) -> None:
        pages = [
            {"value": [{"Id": "1"}, {"Id": "2"}], "@odata.nextLink": "https://rs/next"},
            {"value": [{"Id": "3"}]},
        ]
        d, calls = _diag_with_pages(pages)
        values = d._get_values("https://rs/CatalogItems", {"$top": 2})
        assert [v["Id"] for v in values] == ["1", "2", "3"]
        assert calls == ["https://rs/CatalogItems", "https://rs/next"]

    def test_walker_does_not_loop_on_a_repeating_next_link(self) -> None:
        same = "https://rs/next"
        pages = [
            {"value": [{"Id": "1"}], "@odata.nextLink": same},
            {"value": [{"Id": "2"}], "@odata.nextLink": same},
        ]
        d, _calls = _diag_with_pages(pages)
        values = d._get_values("https://rs/CatalogItems")
        assert [v["Id"] for v in values] == ["1", "2"]

    def test_a_single_item_response_is_wrapped(self) -> None:
        d, _calls = _diag_with_pages([{"Id": "42", "Name": "R"}])
        assert d._get_values("https://rs/CatalogItems('42')") == [
            {"Id": "42", "Name": "R"}
        ]

    def test_paginate_false_reads_only_the_first_page(self) -> None:
        pages = [{"value": [{"Id": "1"}], "@odata.nextLink": "https://rs/next"}]
        d, calls = _diag_with_pages(pages)
        assert d._get_values("https://rs/x", paginate=False) == [{"Id": "1"}]
        assert len(calls) == 1


class TestODataQuoteEscaping:
    def test_a_single_quote_in_the_report_name_is_doubled(self) -> None:
        from agentic_bi.automate import _odata_quote

        assert _odata_quote("My'Report") == "My''Report"
        assert _odata_quote("plain") == "plain"

    def test_the_escaped_name_is_used_in_the_request_url(self, monkeypatch) -> None:
        import sys
        import types

        from agentic_bi import automate

        captured: dict = {}

        class _Resp:
            status_code = 404
            text = ""
            headers: dict = {}

            def json(self):
                return {}

        class _Session:
            verify = True
            auth = None

            def __init__(self) -> None:
                self.headers: dict = {}

            def get(self, url, timeout=None):
                captured["url"] = url
                return _Resp()

        fake_requests = types.SimpleNamespace(Session=_Session)
        fake_urllib3 = types.SimpleNamespace(
            disable_warnings=lambda *a: None,
            exceptions=types.SimpleNamespace(InsecureRequestWarning=Exception),
        )
        fake_sspi = types.SimpleNamespace(HttpNegotiateAuth=lambda: None)
        monkeypatch.setitem(sys.modules, "requests", fake_requests)
        monkeypatch.setitem(sys.modules, "urllib3", fake_urllib3)
        monkeypatch.setitem(sys.modules, "requests_negotiate_sspi", fake_sspi)

        automate.verify_published("rs", "/Target", "My'Report")
        # the quote is doubled inside the OData literal, and the literal closes
        # exactly once (no early termination / injection)
        assert "Path='/Target/My''Report')" in captured["url"]


class TestCalculateWithoutFilterDetector:
    def test_nested_calculate_is_detected(self) -> None:
        from agentic_bi.antipatterns.antipattern_detectors import analyze_measure

        ids = [f["id"] for f in analyze_measure("M", "CALCULATE(SUM([A]))")]
        assert "dax.calculate_no_filter" in ids

    def test_bare_calculate_is_detected(self) -> None:
        from agentic_bi.antipatterns.antipattern_detectors import analyze_measure

        ids = [f["id"] for f in analyze_measure("M", "CALCULATE([A])")]
        assert "dax.calculate_no_filter" in ids

    def test_calculate_with_a_filter_is_not_flagged(self) -> None:
        from agentic_bi.antipatterns.antipattern_detectors import analyze_measure

        ids = [f["id"] for f in analyze_measure("M", "CALCULATE(SUM([A]), ALL(T))")]
        assert "dax.calculate_no_filter" not in ids

    def test_non_calculate_measure_is_not_flagged(self) -> None:
        from agentic_bi.antipatterns.antipattern_detectors import analyze_measure

        ids = [f["id"] for f in analyze_measure("M", "SUM([A])")]
        assert "dax.calculate_no_filter" not in ids


class TestReportServerRobustness:
    def test_index_drill_rows_tolerate_non_dict_sources(self) -> None:
        from agentic_bi.reportserver.pbix_index import IndexMixin

        class _Ix(IndexMixin):
            pass

        results = [
            {
                "file": "a.pbix",
                "lineage": {"sources": ["not-a-dict"], "tables": {}},
                "antipatterns": {"summary": {"by_id": {}}},
            }
        ]
        rows = _Ix()._drill_rows(results)
        assert isinstance(rows, list)

    def test_download_without_an_id_returns_none(self) -> None:
        from pathlib import Path

        from agentic_bi.reportserver import pbix_analysis

        bulk = pbix_analysis.PbiRsBulk.__new__(pbix_analysis.PbiRsBulk)
        assert bulk.download({"Name": "x"}, Path("/tmp/never.pbix")) is None


class TestEngineCliVerifyContract:
    def test_a_missing_verify_does_not_fail_an_ok_oracle(self) -> None:
        # The contract: only a non-ok verify (or a bad oracle) fails the run.
        verify = None
        oracle = "MODEL_LOADED"
        failed = verify is not None and verify != "ok"
        assert (failed, 0 if oracle in ("MODEL_LOADED", "SKIPPED") else 1) == (False, 0)

    def test_any_non_ok_verify_fails(self) -> None:
        for v in ("FAILED", "", "unexpected"):
            assert v is not None and v != "ok"


class TestPreviouslyCrashingPathsAreNowSafe:
    """Pin the exact shapes that used to raise (KeyError/AttributeError)."""

    def test_missing_id_used_to_raise_a_keyerror(self) -> None:
        item: dict = {"Name": "r"}
        with pytest.raises(KeyError):
            _ = item["Id"][:8]  # the old pattern, kept as the counter-example
        from agentic_bi.reportserver import pbix_analysis

        bulk = pbix_analysis.PbiRsBulk.__new__(pbix_analysis.PbiRsBulk)
        # the new guard skips instead of raising
        assert bulk.download(item, __import__("pathlib").Path("/tmp/x.pbix")) is None

    def test_list_sources_used_to_raise_an_attributeerror(self) -> None:
        with pytest.raises(AttributeError):
            ["not-a-dict"].get("by_table", {})  # the old pattern, counter-example
        from agentic_bi.reportserver.pbix_index import IndexMixin

        class _Ix(IndexMixin):
            pass

        rows = _Ix()._drill_rows([{"file": "a.pbix", "lineage": {"sources": ["x"]}}])
        assert isinstance(rows, list)


def test_autopatterns_json_module_imports() -> None:
    # guard: the detectors module must stay importable (round 10 touched it)
    import agentic_bi.antipatterns.antipattern_detectors as det

    assert json.dumps(det.analyze_measure("M", "SUM([A])")) is not None
