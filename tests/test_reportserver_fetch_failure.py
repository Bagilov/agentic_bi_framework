"""A failed Report Server read is a failure, not an empty server.

`ReportServerDiagnostics._get_json` returned `{}` for a 401/500/non-JSON body and
`walk_values` treated that as a single-entity response, so an unreadable root was
reported as one item of type `Unknown`, every entity set as `count: 1`, and
`agentic-bi-server` exited 0. The CLI also built its config outside any boundary,
so a mistyped field escaped as a traceback.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agentic_bi.reportserver.diagnostics import ReportServerDiagnostics, main
from agentic_bi.reportserver.odata import walk_values


def _resp(status: int, body: Any = None, content_type: str = "application/json"):
    class _R:
        status_code = status
        headers = {"Content-Type": content_type}

        def json(self) -> Any:
            return body

    return _R()


class _Net:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def get(self, url: str, params: object = None) -> Any:
        self.calls.append(url)
        return self.responses.pop(0) if self.responses else _resp(500)


def _diag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, responses: list[Any]):
    monkeypatch.chdir(tmp_path)
    diag = ReportServerDiagnostics({"server": "rs.example", "roots": ["/Team"]})
    diag.net = _Net(responses)  # type: ignore[assignment]
    return diag


class TestWalkValues:
    def test_a_failed_page_is_not_a_record(self) -> None:
        assert walk_values(lambda url, params: None, "http://x/Items") == []

    def test_an_empty_object_is_not_a_record(self) -> None:
        assert walk_values(lambda url, params: {}, "http://x/Items") == []

    def test_a_single_entity_is_still_one_record(self) -> None:
        item = {"Id": "1", "Name": "Sales"}
        assert walk_values(lambda url, params: item, "http://x/Items('1')") == [item]


class TestDiagnostics:
    def test_an_unauthorised_root_reports_zero_items_and_the_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        diag = _diag(tmp_path, monkeypatch, [_resp(401, content_type="text/html")])
        results = diag.run(["/Team"])
        assert results[0]["summary"]["total"] == 0
        assert results[0]["summary"]["errors"] == 1
        assert "HTTP 401" in results[0]["fetch_errors"][0]

    def test_the_cli_exits_one_when_a_root_could_not_be_read(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            "agentic_bi.reportserver.diagnostics._diag",
            ReportServerDiagnostics({"server": "rs.example", "roots": ["/Team"]}),
        )
        from agentic_bi.reportserver import diagnostics as mod

        mod._diag.net = _Net([_resp(500, content_type="text/html")])  # type: ignore[assignment]
        assert main(["--no-json"]) == 1
        assert "could not be read" in capsys.readouterr().err

    def test_a_mistyped_config_is_exit_two_with_one_line(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        monkeypatch.chdir(tmp_path)
        cfg = tmp_path / "reportserver_diagnostics_config.json"
        cfg.write_text('{"server": "rs.example", "timeout": "abc"}', encoding="utf-8")
        from agentic_bi.reportserver import diagnostics as mod
        from agentic_bi.reportserver import reportserver_client as client

        monkeypatch.setattr(client, "CONFIG_FILE", cfg)
        monkeypatch.setattr(mod, "CONFIG_FILE", cfg)
        monkeypatch.setattr(mod, "_diag", None)
        assert main(["--no-json"]) == 2
        captured = capsys.readouterr()
        assert "timeout" in captured.err
        assert "Traceback" not in captured.err
