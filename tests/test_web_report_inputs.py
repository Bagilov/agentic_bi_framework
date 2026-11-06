"""Boundary tests for malformed `Report/Layout` input to `web_report`.

The layout is untrusted: a container `config` may parse to a scalar or a list,
`singleVisual` may be a list, `projections` may be a list or carry non-object
entries, and `Report/Layout` may not be JSON at all. Every case must end on a
diagnostic issue (or a short `ValueError` at the CLI boundary), never on an
`AttributeError` traceback.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

import pytest

from agentic_bi.web_report import (
    inspect_layout,
    load_layout,
    render_html,
    write_html,
)
from agentic_bi.web_report.web_cli import main
from agentic_bi.web_report.web_model import ElementReport, PageReport


def _layout_with_config(config: Any) -> dict:
    return {
        "sections": [
            {
                "displayName": "P",
                "visualContainers": [
                    {
                        "x": 0,
                        "y": 0,
                        "width": 10,
                        "height": 10,
                        "config": config,
                        "filters": "[]",
                    }
                ],
            }
        ]
    }


def _layout_with_visual(single: Any) -> dict:
    return _layout_with_config(json.dumps({"singleVisual": single}))


def _codes(layout: dict) -> set[str]:
    model = inspect_layout(layout, source="l.pbix")
    assert len(model.elements) == 1
    return {i.check_id for i in model.elements[0].issues}


@pytest.mark.parametrize("config", ["5", "[1]", '"text"', 5, [1]])
def test_non_object_config_becomes_an_empty_config(config: Any):
    layout = _layout_with_config(config)
    model = inspect_layout(layout, source="l.pbix")
    assert len(model.elements) == 1
    assert model.elements[0].visual_type == "unknown"
    assert {i.check_id for i in model.elements[0].issues} == {"STRUCT-NO-SINGLEVISUAL"}


@pytest.mark.parametrize("single", [[1], "card", 7])
def test_non_object_single_visual_becomes_an_empty_visual(single: Any):
    assert _codes(_layout_with_visual(single)) == {"STRUCT-NO-SINGLEVISUAL"}


@pytest.mark.parametrize("projections", [[1], "Values", 5])
def test_non_object_projections_are_reported_not_fatal(projections: Any):
    codes = _codes(
        _layout_with_visual({"visualType": "card", "projections": projections})
    )
    assert "STRUCT-NO-PROJECTIONS" in codes


@pytest.mark.parametrize("refs", [[1], 5, ["a"]])
def test_non_object_projection_entries_are_skipped_with_a_diagnostic(refs: Any):
    layout = _layout_with_visual(
        {"visualType": "card", "projections": {"Values": refs}}
    )
    model = inspect_layout(layout, source="l.pbix")
    element = model.elements[0]
    assert element.fields == []
    assert element.roles == ["Values"]
    assert "STRUCT-BAD-PROJECTIONS" in {i.check_id for i in element.issues}


@pytest.mark.parametrize("visual_type", [[1], {"a": 1}, 5, True, "", None])
def test_non_string_visual_type_degrades_to_unknown(visual_type: Any):
    """`visualType` is used as a dict/set key and in `sorted()` by the renderer.

    A list or an object is unhashable and a number cannot be ordered against a
    string type, so either value used to raise a `TypeError` traceback inside
    `element_issues` or `_filter_options`.
    """
    layout = _layout_with_visual(
        {"visualType": visual_type, "projections": {"Values": []}}
    )
    model = inspect_layout(layout, source="l.pbix")
    element = model.elements[0]
    assert element.visual_type == "unknown"
    assert "STRUCT-UNKNOWN-TYPE" in {i.check_id for i in element.issues}
    markup = render_html(model)
    assert 'data-kind="unknown"' in markup
    assert '<option value="unknown">' in markup


def test_hostile_and_plain_visual_types_share_one_document():
    """The type filter sorts the type names, so mixing types must not raise."""
    layout = _layout_with_config(json.dumps({"singleVisual": {"visualType": 5}}))
    layout["sections"][0]["visualContainers"].append(
        {
            "x": 0,
            "y": 0,
            "width": 10,
            "height": 10,
            "config": json.dumps({"singleVisual": {"visualType": "card"}}),
            "filters": "[]",
        }
    )
    model = inspect_layout(layout, source="l.pbix")
    assert [e.visual_type for e in model.elements] == ["unknown", "card"]
    markup = render_html(model)
    assert '<option value="card">card</option>' in markup


def test_public_model_coerces_the_fields_used_as_keys():
    element = ElementReport(page=["P"], index=0, visual_type=["card"])
    assert element.page == "Page"
    assert element.visual_type == "unknown"
    assert element.label == "unknown #0"


def test_element_page_and_page_name_coerce_the_same_way():
    """Both sides of the page key must agree for a numeric `displayName`.

    `ElementReport.page` and `PageReport.name` are compared by the details
    table, the `data-page` filter and the client model; `_text` rendered `7` as
    `"page"` on one side and `_page_name` rendered `"7"` on the other, so the
    element never matched its page.
    """
    element = ElementReport(page=7, index=0, visual_type="card")
    page = PageReport(name=7)
    assert element.page == page.name == "7"
    assert ElementReport(page="", index=0, visual_type="card").page == "Page"
    assert PageReport(name="").name == "Page"


def test_malformed_config_at_the_cli_boundary_prints_no_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    pbix = tmp_path / "broken.pbix"
    layout = _layout_with_config("5")
    with zipfile.ZipFile(pbix, "w") as archive:
        archive.writestr("Report/Layout", json.dumps(layout).encode("utf-8"))
    out = tmp_path / "out" / "clone.html"
    rc = main(["--pbix", str(pbix), "--out", str(out)])
    captured = capsys.readouterr()
    assert rc == 0
    assert out.is_file()
    assert "Traceback" not in captured.err
    assert "AttributeError" not in captured.err


def _broken_pbix(path: Path, payload: bytes) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("Report/Layout", payload)
    return path


@pytest.mark.parametrize(
    "payload",
    [b"\xef\xbb\xbf{not json", b'{"sections":', b"\xff\xfe\x00\x00garbage"],
)
def test_broken_report_layout_names_the_file_and_the_member(tmp_path: Path, payload):
    pbix = _broken_pbix(tmp_path / "broken.pbix", payload)
    with pytest.raises(ValueError) as excinfo:
        load_layout(pbix)
    message = str(excinfo.value)
    assert str(pbix) in message
    assert "Report/Layout не разбирается как JSON" in message


def _deep_json(depth: int) -> bytes:
    return b"[" * depth + b"0" + b"]" * depth


def test_a_deeply_nested_layout_is_a_named_input_error(tmp_path: Path) -> None:
    """`json.loads` raises `RecursionError` (not `ValueError`) on deep nesting.

    The layout is untrusted, and `RecursionError` escaped the CLI boundary as
    exit 1 with a traceback, which the CLI contract forbids.
    """
    pbix = _broken_pbix(tmp_path / "deep.pbix", _deep_json(100_000))
    with pytest.raises(ValueError) as excinfo:
        load_layout(pbix)
    assert "Report/Layout не разбирается как JSON" in str(excinfo.value)


def test_a_deeply_nested_config_degrades_to_an_empty_element() -> None:
    layout: dict = {"sections": [{"displayName": "P", "visualContainers": []}]}
    layout["sections"][0]["visualContainers"] = [
        {
            "x": 0,
            "y": 0,
            "width": 10,
            "height": 10,
            "config": _deep_json(100_000).decode("ascii"),
            "filters": "[]",
        }
    ]
    model = inspect_layout(layout, source="deep.pbix")
    assert len(model.elements) == 1
    assert model.elements[0].visual_type == "unknown"


def test_a_deeply_nested_prototype_query_degrades_to_empty() -> None:
    layout: dict = {"sections": [{"displayName": "P", "visualContainers": []}]}
    layout["sections"][0]["visualContainers"] = [
        {
            "x": 0,
            "y": 0,
            "width": 10,
            "height": 10,
            "config": json.dumps(
                {
                    "singleVisual": {
                        "visualType": "card",
                        "prototypeQuery": _deep_json(100_000).decode("ascii"),
                    }
                }
            ),
            "filters": "[]",
        }
    ]
    model = inspect_layout(layout, source="deep.pbix")
    assert len(model.elements) == 1


def test_a_deeply_nested_filter_list_is_a_filter_finding() -> None:
    layout: dict = {"sections": [{"displayName": "P", "visualContainers": []}]}
    layout["sections"][0]["filters"] = _deep_json(100_000).decode("ascii")
    model = inspect_layout(layout, source="deep.pbix")
    assert [i.check_id for i in model.pages[0].filter_issues]


def test_the_cli_turns_a_deep_layout_into_one_short_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The documented contract is exit 2 with one line, never a traceback."""
    pbix = _broken_pbix(tmp_path / "deep.pbix", _deep_json(100_000))
    rc = main(["--pbix", str(pbix), "--out", str(tmp_path / "out.html")])
    err = capsys.readouterr().err
    assert rc == 2
    assert "Traceback" not in err
    assert "RecursionError" not in err
    assert len(err.strip().splitlines()) == 1


def test_an_oversized_report_layout_is_refused_before_decode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hostile `.pbix` may declare a multi-gigabyte `Report/Layout`.

    `z.read` decompressed the member into memory with no bound, so the loader
    that was hardened for malformed input still died on a zip bomb. The declared
    size is rejected before any decompression.
    """
    pbix = _broken_pbix(tmp_path / "bomb.pbix", b"x" * 200)
    monkeypatch.setattr("agentic_bi.web_report.web_inspect._MAX_LAYOUT_BYTES", 100)
    with pytest.raises(ValueError, match="over the 100-byte limit"):
        load_layout(pbix)


@pytest.mark.parametrize(
    "prototype",
    [
        {
            "Select": [
                {
                    "Name": ["x"],
                    "Column": {
                        "Property": "amount",
                        "Expression": {"SourceRef": {"Source": "Sales"}},
                    },
                }
            ]
        },
        {
            "From": [{"Name": ["a"], "Entity": "Sales"}],
            "Select": [
                {
                    "Name": "x",
                    "Column": {
                        "Property": "amount",
                        "Expression": {"SourceRef": {"Source": ["Sales"]}},
                    },
                }
            ],
        },
    ],
)
def test_a_non_scalar_prototype_name_is_a_diagnostic_not_a_crash(
    prototype: dict,
) -> None:
    """A list where a name belongs is unhashable, and used to abort the clone.

    Measured before: `{"Name": ["x"]}` raised `TypeError: unhashable type: 'list'`
    from the `select_names` set, and a list `SourceRef.Source` did the same as a
    dict key — the whole document failed on one malformed visual.
    """
    layout: dict = {"sections": [{"displayName": "P", "visualContainers": []}]}
    layout["sections"][0]["visualContainers"] = [
        {
            "x": 0,
            "y": 0,
            "width": 10,
            "height": 10,
            "config": json.dumps(
                {
                    "singleVisual": {
                        "visualType": "card",
                        "prototypeQuery": prototype,
                        "projections": {"Values": [{"queryRef": "Sum(Sales.amount)"}]},
                    }
                }
            ),
            "filters": "[]",
        }
    ]
    model = inspect_layout(
        layout, source="p.pbix", registry={"Sales": {"columns": ["amount"]}}
    )
    assert model.elements[0].visual_type == "card"


def test_a_lone_surrogate_does_not_stop_the_document(tmp_path: Path) -> None:
    """`"\\ud800"` is legal JSON and no UTF-8 file can hold it.

    Measured before: `write_html` raised `UnicodeEncodeError` and produced no
    document at all for a page named with a lone surrogate.
    """
    layout = {"sections": [{"displayName": "A\ud800B", "visualContainers": []}]}
    model = inspect_layout(layout, source="s.pbix")
    out = tmp_path / "clone.html"
    write_html(model, out)
    assert out.is_file()
    assert "\ufffd" in out.read_text(encoding="utf-8")


def test_a_corrupt_deflate_member_is_a_named_input_error(tmp_path: Path) -> None:
    """`zlib.error` is not a `ValueError`, so it escaped as a traceback."""
    pbix = tmp_path / "corrupt.pbix"
    with zipfile.ZipFile(pbix, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("Report/Layout", json.dumps({"sections": []}).encode())
    raw = bytearray(pbix.read_bytes())
    raw[40] ^= 0xFF
    pbix.write_bytes(bytes(raw))
    with pytest.raises(ValueError) as excinfo:
        load_layout(pbix)
    assert str(pbix) in str(excinfo.value)


def test_a_member_that_fails_to_decompress_is_a_named_input_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A CRC can be intact while the deflate stream is not: `zlib.error` escapes.

    `zipfile` raises `zlib.error` from `read()` on a corrupt stream, and that is
    not a `ValueError`, so the documented "short input error, never a traceback"
    contract broke for a `.pbix` damaged in the middle of a member.
    """
    import zlib

    pbix = tmp_path / "stream.pbix"
    with zipfile.ZipFile(pbix, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("Report/Layout", json.dumps({"sections": []}).encode())

    def boom(_self: object, _name: object) -> object:
        raise zlib.error("Error -3 while decompressing data")

    monkeypatch.setattr(zipfile.ZipFile, "open", boom)
    with pytest.raises(ValueError, match="не читается"):
        load_layout(pbix)
