"""Robustness tests: malformed `Report/Layout` must degrade, never raise.

`Report/Layout` is untrusted: any node may be a string, list or number. A crash
here would escape the CLI boundary (which only turns `ValueError`/`OSError` into
exit 2) as a traceback with exit 1.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from agentic_bi.board_guide import extract_page_geometry
from agentic_bi.board_guide.guide_layout import as_dict, as_float, load_layout


def _write_pbix(path: Path, layout: object, encoding: str = "utf-16-le") -> Path:
    payload = json.dumps(layout, ensure_ascii=False).encode(encoding)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Report/Layout", payload)
    return path


def test_extract_geometry_tolerates_malformed_layout_shapes(
    tmp_path: Path,
) -> None:
    """Non-dict `sections`/`ordinal`/`visualContainers` must not raise."""
    bad_layouts = [
        {"sections": "junk"},
        {"sections": [1, 2]},
        {
            "sections": [
                {"displayName": "P", "ordinal": {"a": 1}, "visualContainers": []}
            ]
        },
        {"sections": [{"displayName": "P", "visualContainers": "junk"}]},
        {"sections": None},
    ]
    for i, layout in enumerate(bad_layouts):
        geom = extract_page_geometry(_write_pbix(tmp_path / f"bad{i}.pbix", layout))
        assert isinstance(geom.pages, list)


def test_page_survives_malformed_visual_shapes(tmp_path: Path) -> None:
    """A single malformed visual must be skipped, not abort the whole guide."""
    containers = [
        {"x": 0, "y": 0, "config": json.dumps({"singleVisual": "junk"})},
        {"x": 0, "y": 0, "config": json.dumps({"singleVisual": {"objects": "junk"}})},
        {"x": 0, "y": 0, "config": json.dumps({"singleVisual": {"vcObjects": "junk"}})},
        {
            "x": 0,
            "y": 0,
            "config": json.dumps({"singleVisual": {"prototypeQuery": [1, 2]}}),
        },
        {"x": 0, "y": 0, "config": json.dumps({"layouts": ["junk"]})},
        {
            "x": 0,
            "y": 0,
            "config": json.dumps({"singleVisual": {}}),
            "filters": json.dumps(
                [
                    {
                        "expression": {"Column": {"Property": "r"}},
                        "filter": {"Where": "junk"},
                    }
                ]
            ),
        },
    ]
    layout = {"sections": [{"displayName": "P", "visualContainers": containers}]}
    geom = extract_page_geometry(_write_pbix(tmp_path / "b.pbix", layout))
    assert len(geom.pages) == 1
    assert geom.visual_count == 6


def test_layout_top_level_not_an_object_is_empty(tmp_path: Path) -> None:
    """A bare list/scalar layout decodes to an empty mapping, not a crash."""
    for i, layout in enumerate([[1, 2, 3], "junk", 42]):
        loaded = load_layout(_write_pbix(tmp_path / f"top{i}.pbix", layout))
        assert loaded == {}


def test_as_dict_and_as_float_guards() -> None:
    assert as_dict({"a": 1}) == {"a": 1}
    assert as_dict("junk") == {}
    assert as_dict(None) == {}
    assert as_float("nan") == 0.0
    assert as_float("inf") == 0.0
    assert as_float("-inf", default=7.0) == 7.0
    assert as_float("12.5") == 12.5
