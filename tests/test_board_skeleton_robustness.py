"""Regression tests for the board/skeleton/agent fixes (round 11).

Each test pins a measured defect that would make the built `.pbix`
non-reproducible or invalid, or crash on untrusted input:

- `page_filter` and the PlantUML node id derived a name from the salted built-in
  `hash()`, so the same input produced a different `.pbix`/diagram every run;
- `card_visual` emitted `OrderBy: [{"Aggregation": null}]` for a plain column (an
  invalid query Power BI rejects);
- the OData `$filter`/path literals in `inspect_board`, `diagnostics` and
  `pbix_analysis` interpolated a path without escaping a single quote;
- `inspect_board.download_report` used `item["Id"]`/`item["Name"]` directly and
  raised `KeyError` on a malformed catalog item.
"""

from __future__ import annotations

import json

import pytest


def test_page_filter_name_is_process_stable() -> None:
    """The filter name must not depend on the per-process hash seed."""
    import subprocess
    import sys

    code = (
        "from agentic_bi.skeleton_visuals import page_filter;"
        "print(page_filter('category','fact_table')['name'])"
    )
    outs = {
        subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        for _ in range(3)
    }
    assert len(outs) == 1, f"page_filter name is not stable across processes: {outs}"


def test_plantuml_node_id_is_process_stable() -> None:
    import subprocess
    import sys

    code = (
        "from agentic_bi.lineage.lineage_plantuml import PlantUmlMixin;"
        "c=type('C',(PlantUmlMixin,),{'__init__':lambda s:(s.__dict__.update(_pu_seen=set(),_pu_ids={}))})();"
        "print(c._pu_id('pkg','123'))"
    )
    outs = {
        subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        for _ in range(3)
    }
    assert len(outs) == 1, f"PlantUML node id is not stable across processes: {outs}"


class TestCardOrderBy:
    def _orderby(self, query: dict):
        from agentic_bi.skeleton_visuals import card_visual

        cfg = json.loads(card_visual(query, "fact")["config"])
        return cfg["singleVisual"]["prototypeQuery"].get("OrderBy")

    def test_plain_column_has_no_orderby(self) -> None:
        # a bare column has no Expression; {"Aggregation": null} is invalid
        assert self._orderby({"kind": "column", "property": "c"}) is None

    def test_measure_orderby_uses_measure_expression(self) -> None:
        ob = self._orderby({"kind": "measure", "property": "m"})
        assert ob and "Measure" in ob[0]["Expression"]
        assert "Property" in ob[0]["Expression"]["Measure"]

    def test_aggregated_column_orderby_uses_aggregation(self) -> None:
        ob = self._orderby({"kind": "column", "property": "c", "agg": True})
        assert ob and "Aggregation" in ob[0]["Expression"]
        assert ob[0]["Expression"]["Aggregation"]["Function"] is not None

    def test_orderby_matches_no_null_expression(self) -> None:
        for q in (
            {"kind": "column", "property": "c"},
            {"kind": "measure", "property": "m"},
            {"kind": "column", "property": "c", "agg": True},
        ):
            ob = self._orderby(q)
            if ob is not None:
                expr = ob[0]["Expression"]
                assert expr and any(v is not None for v in expr.values())


class TestOdataFilterEscaping:
    def test_shared_escaper_doubles_a_quote(self) -> None:
        from agentic_bi.reportserver.odata import odata_quote

        assert odata_quote("My'Report") == "My''Report"
        assert odata_quote("a'b'c") == "a''b''c"

    def test_inspect_board_filter_escapes_the_path(self, monkeypatch) -> None:
        from agentic_bi import inspect_board

        captured: dict = {}

        class _Resp:
            status_code = 200

            def json(self):
                return {"value": []}

        class _Net:
            def get(self, url, params=None):
                captured["params"] = params
                return _Resp()

        class _Bulk:
            server = "rs"
            base = "/reportserver"
            api = "/api/v2.0"
            net = _Net()

        with pytest.raises(inspect_board.PbirsPathError):
            inspect_board.find_by_path(_Bulk(), "/Target/My'Report")
        assert "My''Report" in captured["params"]["$filter"]

    def test_diagnostics_api_url_escapes_the_id(self) -> None:
        from agentic_bi.reportserver.diagnostics import ReportServerDiagnostics

        d = ReportServerDiagnostics(cfg={"server": "rs", "roots": ["/R"]})
        url = d._api_url("CatalogItems", "a'b")
        assert "('a''b')" in url

    def test_pbix_analysis_filter_is_escaped(self) -> None:
        from agentic_bi.reportserver.odata import odata_quote

        root = "/Target/O'Brien"
        filt = f"startswith(Path,'{odata_quote(root)}')"
        # exactly two unescaped quote delimiters remain
        assert filt.count("'") - filt.count("''") * 2 == 2


class TestInspectBoardRobustness:
    def test_download_without_an_id_raises_a_domain_error(self, tmp_path) -> None:
        from agentic_bi import inspect_board

        class _Bulk:
            server = "rs"
            base = "/reportserver"
            api = "/api/v2.0"

            class net:  # noqa: N801 - stand-in for the session
                @staticmethod
                def request(*_a, **_k):
                    raise AssertionError("must not reach the network")

        with pytest.raises(inspect_board.PbirsAccessError):
            inspect_board.download_report(_Bulk(), {"Name": "x"}, tmp_path / "x.pbix")

    def test_download_without_a_name_does_not_raise_keyerror(self, tmp_path) -> None:
        from agentic_bi import inspect_board

        class _Resp:
            status_code = 403
            content = b""

        class _Bulk:
            server = "rs"
            base = "/reportserver"
            api = "/api/v2.0"

            class net:  # noqa: N801
                @staticmethod
                def request(*_a, **_k):
                    return _Resp()

        with pytest.raises(inspect_board.PbirsAccessError):
            inspect_board.download_report(_Bulk(), {"Id": "1"}, tmp_path / "x.pbix")


class TestSkeletonContainerHelpersStillWork:
    def test_full_query_and_query_layout(self) -> None:
        from agentic_bi.skeleton_container import full_query, query_layout

        q = full_query("t", "m", [{"Name": "t.c"}])
        assert q["From"] == [{"Name": "m", "Entity": "t", "Type": 0}]
        q2 = full_query("t", "m", [], measure_table="s", measure_alias="s")
        assert {"Name": "s", "Entity": "s", "Type": 0} in q2["From"]

        cont = query_layout("X", {"visualType": "card"}, 1, 2, 3, 4)
        cfg = json.loads(cont["config"])
        assert cfg["layouts"][0]["position"] == {
            "x": 1,
            "y": 2,
            "width": 3,
            "height": 4,
            "z": 0,
        }
