"""Tests for the figure manifest (`shots`).

A manifest is the record of what a run produced and the input `verify` checks; a
hand-edited or truncated one must arrive as a reported bad input, never as a
`KeyError`/`TypeError` traceback. The manifest hashing needs no browser, so this
module always runs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentic_bi.shots import (
    RenderRecord,
    ShotPlan,
    read_manifest,
    sha256_file,
    verify_manifest,
    write_manifest,
)


def test_sha256_file_and_verify_detects_drift(tmp_path: Path) -> None:
    png = tmp_path / "a.png"
    png.write_bytes(b"hello")
    digest = sha256_file(png)
    assert digest == sha256_file(png)
    manifest = write_manifest(
        [
            RenderRecord(
                name="a",
                kind="html",
                source="a.html",
                png=str(png),
                width=10,
                height=10,
                scale=1.0,
                sha256=digest,
                bytes=5,
            )
        ],
        tmp_path / "manifest.json",
        browser="chrome",
    )
    assert verify_manifest(manifest) == []
    png.write_bytes(b"tampered")
    problems = verify_manifest(manifest)
    assert len(problems) == 1
    assert "hash mismatch" in problems[0]


def test_verify_reports_missing_file(tmp_path: Path) -> None:
    manifest = write_manifest([], tmp_path / "m.json", browser="chrome")
    manifest.figures.append(
        RenderRecord(
            name="ghost",
            kind="html",
            source="g.html",
            png=str(tmp_path / "gone.png"),
            width=1,
            height=1,
            scale=1.0,
            sha256="0" * 64,
            bytes=0,
        )
    )
    assert "missing file" in verify_manifest(manifest)[0]


def test_verify_alone_accepts_a_partial_set(tmp_path: Path) -> None:
    """Without a plan, `verify` checks only what the manifest records."""
    manifest = write_manifest([], tmp_path / "m.json", browser="chrome")
    assert verify_manifest(manifest) == []


def test_verify_with_a_plan_flags_figures_missing_from_the_manifest(
    tmp_path: Path,
) -> None:
    """`verify --plan` closes the gap where `--only`/`--no-strict` shrinks a set.

    The recorded set can be intact and still not be the set the plan asked for;
    a plan-aware verify must report the figures that never made it in.
    """
    plan = ShotPlan.from_dict(
        {
            "figures": [
                {"name": "a", "source": "a.html"},
                {"name": "b", "source": "b.html"},
            ]
        }
    )
    png = tmp_path / "a.png"
    png.write_bytes(b"a")
    manifest = write_manifest(
        [
            RenderRecord(
                name="a",
                kind="html",
                source="a.html",
                png=str(png),
                width=1,
                height=1,
                scale=1.0,
                sha256=sha256_file(png),
                bytes=1,
            )
        ],
        tmp_path / "m.json",
        browser="chrome",
    )
    assert verify_manifest(manifest) == []
    problems = verify_manifest(manifest, plan=plan)
    assert len(problems) == 1
    assert "b: in the plan but not in the manifest" in problems[0]


def test_verify_with_a_fully_built_plan_reports_nothing(tmp_path: Path) -> None:
    plan = ShotPlan.from_dict({"figures": [{"name": "a", "source": "a.html"}]})
    png = tmp_path / "a.png"
    png.write_bytes(b"a")
    manifest = write_manifest(
        [
            RenderRecord(
                name="a",
                kind="html",
                source="a.html",
                png=str(png),
                width=1,
                height=1,
                scale=1.0,
                sha256=sha256_file(png),
                bytes=1,
            )
        ],
        tmp_path / "m.json",
        browser="chrome",
    )
    assert verify_manifest(manifest, plan=plan) == []


def test_read_manifest_round_trips(tmp_path: Path) -> None:
    write_manifest([], tmp_path / "m.json", browser="chrome", plan="p.toml")
    back = read_manifest(tmp_path / "m.json")
    assert back.browser == "chrome"
    assert back.plan == "p.toml"


def test_read_manifest_rejects_malformed_figure_as_value_error(tmp_path: Path) -> None:
    """A truncated or hand-edited manifest is bad input, not a crash.

    `verify` maps `ValueError` to exit code 2; a raw `KeyError` from a missing
    field used to escape as a traceback instead.
    """
    path = tmp_path / "m.json"
    for broken in (
        {"figures": [{"name": "a"}]},
        {"figures": ["not-a-mapping"]},
        {"figures": [{"name": "a", "kind": "html", "source": "s", "png": "p"}]},
    ):
        path.write_text(json.dumps(broken), encoding="utf-8")
        with pytest.raises(ValueError):
            read_manifest(path)


def test_read_manifest_rejects_bad_field_type(tmp_path: Path) -> None:
    path = tmp_path / "m.json"
    figure = {
        "name": "a",
        "kind": "html",
        "source": "s",
        "png": "p",
        "width": "wide",
        "height": 1,
        "scale": 1.0,
        "sha256": "0" * 64,
        "bytes": 1,
    }
    path.write_text(json.dumps({"figures": [figure]}), encoding="utf-8")
    with pytest.raises(ValueError, match="bad field value"):
        read_manifest(path)
