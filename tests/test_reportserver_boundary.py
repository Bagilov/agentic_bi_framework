"""Boundary validation of the Report Server config and HTTP/JSON responses.

The config file and the OData catalog are untrusted input: a mistyped value or a
malformed response must fail with a short `ValueError` that names the field,
before the caller dereferences it (`Path(None)`, `payload.get` on a list).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentic_bi.reportserver import reportserver_client as client
from agentic_bi.reportserver.catalog import catalog_values, item_str


class TestConfigValues:
    def test_string_default_and_explicit(self) -> None:
        assert client.config_str({}, "server", "rs") == "rs"
        assert client.config_str({"server": "host"}, "server", "rs") == "host"

    def test_string_rejects_a_number(self) -> None:
        with pytest.raises(
            ValueError, match=r"config field 'server': expected string, got int"
        ):
            client.config_str({"server": 5}, "server", "")

    def test_float_accepts_an_int(self) -> None:
        assert client.config_float({"timeout": 60}, "timeout", 1.0) == 60.0

    def test_float_rejects_a_bool(self) -> None:
        with pytest.raises(ValueError, match="expected number, got bool"):
            client.config_float({"timeout": True}, "timeout", 1.0)

    def test_float_rejects_a_string(self) -> None:
        with pytest.raises(ValueError, match="expected number, got str"):
            client.config_float({"timeout": "60"}, "timeout", 1.0)

    def test_bool_accepts_and_rejects(self) -> None:
        assert (
            client.config_bool({"include_hidden": False}, "include_hidden", True)
            is False
        )
        with pytest.raises(ValueError, match="expected boolean, got str"):
            client.config_bool({"include_hidden": "yes"}, "include_hidden", True)

    def test_str_list_is_empty_when_absent(self) -> None:
        assert client.config_str_list({}, "roots") == []

    def test_str_list_rejects_a_bare_string(self) -> None:
        with pytest.raises(ValueError, match="expected a list of strings, got str"):
            client.config_str_list({"roots": "Reports"}, "roots")

    def test_str_list_rejects_a_non_string_item(self) -> None:
        with pytest.raises(ValueError, match="expected a list of strings, got list"):
            client.config_str_list({"roots": ["Reports", 3]}, "roots")


@pytest.fixture()
def config_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    path = tmp_path / "reportserver_diagnostics_config.json"
    monkeypatch.setattr(client, "CONFIG_FILE", path)
    return path


class TestLoadConfig:
    def test_values_override_the_defaults(self, config_file: Path) -> None:
        config_file.write_text(json.dumps({"server": "rs.local", "timeout": 5}))
        cfg = client.load_config()
        assert cfg["server"] == "rs.local"
        assert cfg["timeout"] == 5

    def test_a_null_value_keeps_the_default(self, config_file: Path) -> None:
        config_file.write_text(json.dumps({"server": None}))
        assert client.load_config()["server"] == ""

    def test_an_absent_file_falls_back_to_defaults(self, config_file: Path) -> None:
        assert client.load_config()["api_prefix"] == "/api/v2.0"

    def test_a_non_object_document_falls_back_to_defaults(
        self, config_file: Path
    ) -> None:
        config_file.write_text("[]")
        assert client.load_config()["output_dir"] == "output_files/rs_diagnostics"

    def test_invalid_json_falls_back_to_defaults(self, config_file: Path) -> None:
        config_file.write_text("{ not json")
        assert client.load_config()["server"] == ""


class TestConfigConsumers:
    def test_a_mistyped_output_dir_is_a_value_error(
        self, config_file: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.chdir(tmp_path)
        config_file.write_text(json.dumps({"output_dir": 5}))
        with pytest.raises(ValueError, match="config field 'output_dir'"):
            client.result_out_path("/Reports")

    def test_result_out_path_creates_the_directory(
        self, config_file: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.chdir(tmp_path)
        config_file.write_text(json.dumps({"output_dir": "out/rs"}))
        out = client.result_out_path("/Reports")
        assert out.parent == Path("out/rs")
        assert out.name.endswith(".json")

    def test_a_mistyped_json_prefix_is_a_value_error(
        self, config_file: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.chdir(tmp_path)
        config_file.write_text(json.dumps({"json_prefix": 5}))
        with pytest.raises(ValueError, match="config field 'json_prefix'"):
            client.build_json_name("/Reports")


class TestCatalogResponse:
    def test_a_valid_page_is_read(self) -> None:
        payload = {"value": [{"Id": "1"}, {"Id": "2"}]}
        assert catalog_values(payload, "/R") == [{"Id": "1"}, {"Id": "2"}]

    def test_an_empty_page_is_accepted(self) -> None:
        assert catalog_values({"value": []}, "/R") == []

    def test_a_non_object_payload_is_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"catalog /R: expected a JSON object"):
            catalog_values([], "/R")

    def test_a_missing_value_list_is_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"expected a 'value' list, got NoneType"):
            catalog_values({}, "/R")

    def test_a_non_list_value_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="expected a 'value' list, got dict"):
            catalog_values({"value": {"Id": "1"}}, "/R")

    def test_non_object_items_are_skipped(self) -> None:
        assert catalog_values({"value": [1, {"Id": "2"}]}, "/R") == [{"Id": "2"}]

    def test_item_str_keeps_strings_and_defaults_the_rest(self) -> None:
        assert item_str({"Path": "/R/x"}, "Path") == "/R/x"
        assert item_str({"Path": 5}, "Path") == ""
        assert item_str({}, "Path") == ""
