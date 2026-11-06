"""Byte-stable manifests for `shots`.

A figure set is rebuilt from the same plan on different machines and in
different output directories, so the manifest cannot depend on the clock, on an
absolute install path or on the order a dict happens to serialize in. These
tests build twice through the real orchestrator with a fake renderer, so they run
without Chromium.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentic_bi.board_guide import guide_capture
from agentic_bi.shots import (
    ShotPlan,
    build_shots,
    read_manifest,
    shots_build,
    verify_manifest,
)
from agentic_bi.shots.shots_render import RenderError
from agentic_bi.shots.shots_types import FigureSpec

_BROWSER = "/opt/browsers/Google Chrome.app/Contents/MacOS/Google Chrome"


def _plan(tmp_path: Path) -> ShotPlan:
    src = tmp_path / "src"
    src.mkdir()
    (src / "run.txt").write_text("All checks passed!", encoding="utf-8")
    (src / "card.html").write_text("<body>card</body>", encoding="utf-8")
    return ShotPlan.from_dict(
        {
            "base_dir": str(src),
            "figures": [
                {"name": "run", "kind": "terminal", "source": "run.txt"},
                {"name": "card", "kind": "html", "source": "card.html"},
            ],
        }
    )


def _fake_toolchain(monkeypatch: pytest.MonkeyPatch) -> None:
    """A browser name and a renderer that writes deterministic fake bytes."""
    monkeypatch.setattr(
        guide_capture, "find_browser_executable", lambda explicit=None: _BROWSER
    )

    def fake_render(
        spec: FigureSpec, out_dir: Path, browser: str | None
    ) -> tuple[Path, int, int]:
        png = out_dir / spec.output_name()
        png.write_bytes(b"fake-png:" + spec.name.encode("utf-8"))
        return png, spec.width, spec.height

    monkeypatch.setattr(shots_build, "_render_one", fake_render)


def test_two_runs_write_identical_manifest_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_toolchain(monkeypatch)
    plan = _plan(tmp_path)
    first = build_shots(plan, tmp_path / "out-a", plan_path="plan/figures.toml")
    second = build_shots(plan, tmp_path / "out-b", plan_path="plan/figures.toml")
    text_a = (first.out_dir / "manifest.json").read_text(encoding="utf-8")
    text_b = (second.out_dir / "manifest.json").read_text(encoding="utf-8")
    assert text_a == text_b
    assert first.manifest.figures[0].sha256 == second.manifest.figures[0].sha256


def test_manifest_has_no_paths_timestamps_or_installed_tool_details(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_toolchain(monkeypatch)
    result = build_shots(_plan(tmp_path), tmp_path / "out", plan_path="/home/u/f.toml")
    text = (result.out_dir / "manifest.json").read_text(encoding="utf-8")
    payload = json.loads(text)
    assert str(tmp_path) not in text
    assert "/opt/browsers" not in text
    assert payload["generated"] == ""
    assert payload["browser"] == "Google Chrome"
    assert payload["plan"] == "f.toml"
    assert payload["figures"][0]["png"] == "run.png"
    assert payload["figures"][0]["source"] == "run.txt"


def test_manifest_records_figures_in_plan_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_toolchain(monkeypatch)
    result = build_shots(_plan(tmp_path), tmp_path / "out")
    assert [figure.name for figure in result.manifest.figures] == ["run", "card"]


def test_relative_png_names_verify_against_the_manifest_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A set can be moved: names are relative to the manifest, not to the CWD."""
    _fake_toolchain(monkeypatch)
    result = build_shots(_plan(tmp_path), tmp_path / "out")
    moved = tmp_path / "moved"
    result.out_dir.rename(moved)
    manifest = read_manifest(moved / "manifest.json")
    assert verify_manifest(manifest) == []


def test_write_manifest_records_only_name_and_plan_basename(tmp_path: Path) -> None:
    from agentic_bi.shots import write_manifest

    manifest = write_manifest(
        [], tmp_path / "m.json", browser=_BROWSER, plan="/home/u/figures.toml"
    )
    assert manifest.browser == "Google Chrome"
    assert manifest.plan == "figures.toml"
    assert manifest.root == str(tmp_path)


def test_windows_style_paths_are_reduced_to_a_name(tmp_path: Path) -> None:
    from agentic_bi.shots import write_manifest

    manifest = write_manifest(
        [],
        tmp_path / "m.json",
        browser=r"C:\Program Files\Chrome\Application\chrome.exe",
        plan=r"C:\plans\figures.toml",
    )
    assert manifest.browser == "chrome.exe"
    assert manifest.plan == "figures.toml"


def test_failure_reason_is_plan_relative_not_absolute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An error message lands in the manifest: it must not bake in a home path."""
    monkeypatch.setattr(
        guide_capture, "find_browser_executable", lambda explicit=None: "/bin/true"
    )
    src = tmp_path / "src"
    src.mkdir()
    plan = ShotPlan.from_dict(
        {"base_dir": str(src), "figures": [{"name": "gone", "source": "gone.html"}]}
    )
    result = build_shots(plan, tmp_path / "out")
    assert result.failures[0][1] == "source not found: gone.html"
    assert result.manifest.figures[0].source == "gone.html"
    text = (result.out_dir / "manifest.json").read_text(encoding="utf-8")
    assert str(tmp_path) not in text


def test_render_error_reason_has_no_absolute_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reason names the PNG as the renderer wrote it, not as it resolves.

    The earlier version of this test passed while the bug was live:
    `pytest.tmp_path` on macOS is already `/private/var/…`, so the written and
    the resolved root were the same string. A symlinked output directory
    separates them, which is exactly what leaked a machine path into the
    manifest for an absolute `--out-dir`.
    """
    monkeypatch.setattr(
        guide_capture, "find_browser_executable", lambda explicit=None: "/bin/true"
    )
    real = tmp_path / "real-out"
    real.mkdir()
    alias = tmp_path / "alias-out"
    alias.symlink_to(real, target_is_directory=True)

    def fake_render(
        spec: FigureSpec, out_dir: Path, browser: str | None
    ) -> tuple[Path, int, int]:
        raise RenderError(f"no screenshot at {out_dir / spec.output_name()}")

    monkeypatch.setattr(shots_build, "_render_one", fake_render)
    result = build_shots(_plan(tmp_path), alias)
    assert result.failures
    text = (result.out_dir / "manifest.json").read_text(encoding="utf-8")
    assert str(tmp_path) not in text
    assert str(alias) not in text
    assert str(tmp_path) not in result.failures[0][1]


def test_directory_source_reason_has_no_absolute_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The OS error text names the file absolutely; the manifest must not."""
    monkeypatch.setattr(
        guide_capture, "find_browser_executable", lambda explicit=None: "/bin/true"
    )
    src = tmp_path / "src"
    (src / "not-a-file.txt").mkdir(parents=True)
    plan = ShotPlan.from_dict(
        {
            "base_dir": str(src),
            "figures": [{"name": "d", "kind": "terminal", "source": "not-a-file.txt"}],
        }
    )
    result = build_shots(plan, tmp_path / "out")
    assert result.failures, "a directory source must fail"
    text = (result.out_dir / "manifest.json").read_text(encoding="utf-8")
    assert str(tmp_path) not in text
    assert str(tmp_path) not in result.failures[0][1]
