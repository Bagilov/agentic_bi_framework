"""Bad plan/manifest input for `shots`: exit 2 with a located message.

A plan is data written by a human, and a manifest can be truncated by a bad
merge. Both are *inputs*: the CLI must end on code 2 with a message naming the
file and position, never on a `JSONDecodeError`/`TypeError` traceback.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentic_bi.shots import ShotPlan, read_manifest
from agentic_bi.shots.shots_cli import main
from agentic_bi.shots.shots_types import FigureSpec


def _plan_file(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_missing_plan_names_the_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="file not found") as excinfo:
        ShotPlan.load(tmp_path / "gone.toml")
    assert "gone.toml" in str(excinfo.value)


def test_broken_json_plan_names_the_file_and_position(tmp_path: Path) -> None:
    path = _plan_file(tmp_path, "figures.json", '{"figures": [ , ]}')
    with pytest.raises(ValueError, match="invalid JSON at line") as excinfo:
        ShotPlan.load(path)
    assert "figures.json" in str(excinfo.value)


def test_broken_toml_plan_names_the_file(tmp_path: Path) -> None:
    path = _plan_file(tmp_path, "figures.toml", "[[figures]\nname = 'a'\n")
    with pytest.raises(ValueError, match="invalid TOML") as excinfo:
        ShotPlan.load(path)
    assert "figures.toml" in str(excinfo.value)


def test_unsupported_plan_format_is_reported_not_guessed(tmp_path: Path) -> None:
    path = _plan_file(tmp_path, "figures.yaml", "figures: []")
    with pytest.raises(ValueError, match="unsupported format"):
        ShotPlan.load(path)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"base_dir": ["src"]}, "'base_dir' must be a string path"),
        ({"defaults": "scale=2"}, "'defaults' must be a mapping"),
        ({"defaults": {"scal": 2}}, r"unknown key\(s\) in 'defaults'"),
        ({"figures": "a"}, "'figures' must be a non-empty list"),
        ({"figures": [42]}, "figures\\[0\\] must be a mapping"),
    ],
)
def test_plan_structure_errors_name_the_field(
    payload: dict[str, object], message: str
) -> None:
    data = dict(payload)
    if "figures" not in data:
        data["figures"] = [{"name": "a", "source": "a.html"}]
    with pytest.raises(ValueError, match=message):
        ShotPlan.from_dict(data)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"name": 42, "source": "a.html"}, "'name' must be a string"),
        ({"name": "a", "source": ["a.html"]}, "'source' must be a string"),
        ({"name": "a", "source": "a", "title": 7}, "'title' must be a string"),
        ({"name": "a", "source": "a", "width": True}, "width must be an integer"),
        ({"name": "a", "source": "a", "height": 10.5}, "height must be an integer"),
        ({"name": "a", "source": "a", "scale": "big"}, "scale must be a number"),
        ({"name": "a", "source": "a", "scale": float("nan")}, "scale must be finite"),
    ],
)
def test_figure_field_types_are_checked(
    payload: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        FigureSpec.from_dict(dict(payload))


def test_duplicate_figure_names_are_rejected(tmp_path: Path) -> None:
    """Two figures with one name make `--only` and `verify --plan` ambiguous."""
    path = _plan_file(
        tmp_path,
        "figures.toml",
        '[[figures]]\nname = "a"\nsource = "a.html"\n'
        '[[figures]]\nname = "a"\nsource = "b.html"\nout = "b.png"\n',
    )
    with pytest.raises(ValueError, match=r"duplicate figure name\(s\) \['a'\]"):
        ShotPlan.load(path)


def test_duplicate_names_are_named_with_the_plan_file(tmp_path: Path) -> None:
    path = _plan_file(
        tmp_path,
        "figures.json",
        json.dumps(
            {
                "figures": [
                    {"name": "a", "source": "a.html"},
                    {"name": "a", "source": "b.html", "out": "b.png"},
                ]
            }
        ),
    )
    with pytest.raises(ValueError) as excinfo:
        ShotPlan.load(path)
    assert "figures.json" in str(excinfo.value)
    assert "['a']" in str(excinfo.value)


def test_cli_rejects_duplicate_names_as_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _plan_file(
        tmp_path,
        "figures.toml",
        '[[figures]]\nname = "a"\nsource = "a.html"\n'
        '[[figures]]\nname = "a"\nsource = "b.html"\nout = "b.png"\n',
    )
    rc = main(["--plan", str(path), "--out-dir", str(tmp_path / "out")])
    captured = capsys.readouterr()
    assert rc == 2
    assert "duplicate figure name(s) ['a']" in captured.err
    assert "figures.toml" in captured.err
    assert "Traceback" not in captured.err


def test_plan_error_names_the_broken_figure(tmp_path: Path) -> None:
    """A bare `figure: 'source' is required` does not say which figure."""
    path = _plan_file(
        tmp_path,
        "figures.toml",
        '[[figures]]\nname = "ok"\nsource = "ok.html"\n[[figures]]\nname = "broken"\n',
    )
    with pytest.raises(ValueError) as excinfo:
        ShotPlan.load(path)
    message = str(excinfo.value)
    assert "figures.toml" in message
    assert "figure 'broken'" in message
    assert "'source' is required" in message


def test_plan_error_uses_the_index_when_the_name_is_missing(tmp_path: Path) -> None:
    path = _plan_file(
        tmp_path,
        "figures.toml",
        '[[figures]]\nname = "ok"\nsource = "ok.html"\n[[figures]]\nsource = "b.html"\n',
    )
    with pytest.raises(ValueError) as excinfo:
        ShotPlan.load(path)
    assert "figures[1]" in str(excinfo.value)
    assert "'name' is required" in str(excinfo.value)


def test_cli_reports_a_broken_plan_as_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _plan_file(tmp_path, "figures.json", "{ not json")
    rc = main(["--plan", str(path), "--out-dir", str(tmp_path / "out")])
    captured = capsys.readouterr()
    assert rc == 2
    assert "figures.json" in captured.err
    assert "Traceback" not in captured.err


def test_read_manifest_reports_a_missing_file_by_name(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="file not found") as excinfo:
        read_manifest(tmp_path / "gone.json")
    assert "gone.json" in str(excinfo.value)


def test_read_manifest_reports_broken_json_by_name(tmp_path: Path) -> None:
    path = _plan_file(tmp_path, "manifest.json", "{oops")
    with pytest.raises(ValueError, match="invalid JSON at line") as excinfo:
        read_manifest(path)
    assert "manifest.json" in str(excinfo.value)


def test_read_manifest_rejects_a_non_list_figures_field(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"figures": 5}), encoding="utf-8")
    with pytest.raises(ValueError, match="'figures' must be a list"):
        read_manifest(path)


def test_read_manifest_rejects_an_unknown_status(tmp_path: Path) -> None:
    record = {
        "name": "a",
        "kind": "html",
        "source": "a.html",
        "status": "exploded",
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"figures": [record]}), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown status"):
        read_manifest(path)


def test_a_skipped_record_does_not_need_a_png_or_hash(tmp_path: Path) -> None:
    record = {
        "name": "a",
        "kind": "html",
        "source": "a.html",
        "status": "skipped",
        "reason": "no Chromium browser found",
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"figures": [record]}), encoding="utf-8")
    manifest = read_manifest(path)
    assert manifest.figures[0].status == "skipped"
    assert manifest.figures[0].reason == "no Chromium browser found"


def test_cli_verify_reports_a_broken_manifest_as_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _plan_file(tmp_path, "manifest.json", "{ not json")
    rc = main(["verify", "--manifest", str(path)])
    captured = capsys.readouterr()
    assert rc == 2
    assert "manifest.json" in captured.err
    assert "Traceback" not in captured.err
