"""Failure reasons and console paths must not depend on where a run happened.

A reason is stored in the manifest, so the same plan built into `rel-a` and
`rel-b` has to record the same text, and no absolute path may appear even when
the output directory is absolute or symlinked (`/tmp` is `/private/tmp` on
macOS). The old normalization stripped only the resolved root, while the message
carried the path as given, so the run's directory leaked into the manifest.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from agentic_bi.board_guide import guide_capture
from agentic_bi.shots import ShotPlan, build_shots, shots_build
from agentic_bi.shots.shots_cli import _rel, main
from agentic_bi.shots.shots_records import portable
from agentic_bi.shots.shots_render import RenderError
from agentic_bi.shots.shots_types import FigureSpec


def _plan(tmp_path: Path) -> ShotPlan:
    src = tmp_path / "src"
    src.mkdir(exist_ok=True)
    (src / "card.html").write_text("<body>card</body>", encoding="utf-8")
    return ShotPlan.from_dict(
        {
            "base_dir": str(src),
            "figures": [{"name": "card", "source": "card.html"}],
        }
    )


def _failing_renderer(monkeypatch: pytest.MonkeyPatch) -> None:
    """A renderer whose error names the output path the way a tool would."""
    monkeypatch.setattr(
        guide_capture, "find_browser_executable", lambda explicit=None: "/bin/true"
    )

    def fake_render(
        spec: FigureSpec, out_dir: Path, browser: str | None
    ) -> tuple[Path, int, int]:
        out = out_dir / spec.output_name()
        raise RenderError(f"no screenshot at {out} (browser exit 1)")

    monkeypatch.setattr(shots_build, "_render_one", fake_render)


def test_portable_strips_every_spelling_of_a_root(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(out, target_is_directory=True)
    base = tmp_path / "src"
    base.mkdir()

    assert portable(f"no screenshot at {out}/a.png", out, base) == (
        "no screenshot at a.png"
    )
    assert portable(f"no screenshot at {alias}/a.png", alias, base) == (
        "no screenshot at a.png"
    )
    assert portable(f"no screenshot at {out.resolve()}/a.png", alias, base) == (
        "no screenshot at a.png"
    )
    assert portable(f"no screenshot at {base}/a.html", out, base) == (
        "no screenshot at a.html"
    )
    assert portable("no screenshot at rel/a.png", Path("rel"), base) == (
        "no screenshot at a.png"
    )


def test_portable_leaves_a_bare_dot_root_alone(tmp_path: Path) -> None:
    """Skipping `.` matters: stripping it would eat every sentence period."""
    message = "no screenshot at a.png (browser exit 1)"
    assert portable(message, Path("."), tmp_path) == message


def test_reason_is_identical_for_two_relative_out_dirs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Measured bug: `rel-a` and `rel-b` produced different manifests."""
    _failing_renderer(monkeypatch)
    plan = _plan(tmp_path)
    monkeypatch.chdir(tmp_path)
    first = build_shots(plan, Path("rel-a"))
    second = build_shots(plan, Path("rel-b"))
    text_a = (first.out_dir / "manifest.json").read_text(encoding="utf-8")
    text_b = (second.out_dir / "manifest.json").read_text(encoding="utf-8")
    assert text_a == text_b
    assert "rel-a" not in text_a
    assert "rel-b" not in text_b


def test_absolute_symlinked_out_dir_leaves_no_absolute_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The message uses the directory as given; the resolver sees the target."""
    _failing_renderer(monkeypatch)
    real = tmp_path / "real-out"
    real.mkdir()
    alias = tmp_path / "alias-out"
    alias.symlink_to(real, target_is_directory=True)

    result = build_shots(_plan(tmp_path), alias)

    text = (result.out_dir / "manifest.json").read_text(encoding="utf-8")
    assert str(tmp_path) not in text
    assert str(alias) not in text
    assert str(real) not in text
    assert str(tmp_path) not in result.failures[0][1]


def test_tmp_symlinked_root_is_stripped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real `/tmp` root: `/tmp` resolves to `/private/tmp` on macOS.

    This is the exact measured repro; it is skipped where `/tmp` is not a
    symlink, because then the as-given and resolved spellings already match.
    """
    if not Path("/tmp").is_symlink():
        pytest.skip("this platform's /tmp is not a symlink")
    _failing_renderer(monkeypatch)
    out = Path("/tmp") / f"abf-shots-portable-{tmp_path.name}"
    try:
        result = build_shots(_plan(tmp_path), out)
        text = (result.out_dir / "manifest.json").read_text(encoding="utf-8")
        assert str(out) not in text
        assert "/private" not in text
    finally:
        shutil.rmtree(out, ignore_errors=True)


def test_cli_stderr_carries_no_absolute_out_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _failing_renderer(monkeypatch)
    src = tmp_path / "src"
    src.mkdir(exist_ok=True)
    (src / "card.html").write_text("<body></body>", encoding="utf-8")
    (tmp_path / "plan.json").write_text(
        '{"base_dir": "src", "figures": [{"name": "card", "source": "card.html"}]}',
        encoding="utf-8",
    )
    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)

    rc = main(["--plan", str(tmp_path / "plan.json"), "--out-dir", str(alias)])

    captured = capsys.readouterr()
    assert rc == 1
    assert "no screenshot at card.png" in captured.err
    assert str(tmp_path) not in captured.err
    assert "Traceback" not in captured.err


def test_console_path_outside_the_cwd_is_absolute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`../../../../../var/folders/…` is relative but useless; print the path."""
    work = tmp_path / "work"
    work.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(work)
    assert _rel(elsewhere) == elsewhere.as_posix()
    assert _rel(work / "out") == "out"
    assert _rel(work) == "."
