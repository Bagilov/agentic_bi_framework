"""Staging and build-script tests for the guest chain (no VM involved).

`stage_framework` must produce an archive whose members sit at the root, and
`build_script` must quote every configured value, because the body runs in the
guest's highest-privilege interactive session.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from agentic_bi.guest_chain import ChainConfig
from agentic_bi.guest_chain_build import (
    build_script,
    stage_framework,
)
from agentic_bi.guest_types import GuestConfig


class TestStageFramework:
    def test_archives_the_runtime_at_the_archive_root(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        (repo / "src" / "pkg").mkdir(parents=True)
        (repo / "src" / "pkg" / "mod.py").write_text("x = 1\n", encoding="utf-8")
        (repo / "src" / "pkg" / "__pycache__").mkdir()
        (repo / "src" / "pkg" / "__pycache__" / "mod.pyc").write_bytes(b"\x00")
        (repo / "examples").mkdir()
        (repo / "examples" / "b.py").write_text("y = 2\n", encoding="utf-8")
        (repo / "README.md").write_text("hi\n", encoding="utf-8")
        (repo / "ignored").mkdir()
        (repo / "ignored" / "secret.txt").write_text("no\n", encoding="utf-8")

        dest = tmp_path / "abf.zip"
        stage_framework(repo, dest)
        names = set(zipfile.ZipFile(dest).namelist())

        assert names == {"src/pkg/mod.py", "examples/b.py", "README.md"}
        assert not any("__pycache__" in name for name in names)

    def test_accepts_a_string_repo_path(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        (repo / "src").mkdir(parents=True)
        (repo / "src" / "m.py").write_text("z = 3\n", encoding="utf-8")
        dest = tmp_path / "abf.zip"
        stage_framework(str(repo), dest)  # type: ignore[arg-type]
        assert "src/m.py" in zipfile.ZipFile(dest).namelist()


class TestBuildScript:
    def _config(self, **overrides) -> ChainConfig:
        guest = GuestConfig(winrm="http://guest:5985/wsman", user="u", password="p")
        defaults = dict(
            guest=guest,
            data=Path("examples/engine_sales.csv"),
            table="Sales",
            out=Path("output_files/board.pbix"),
        )
        defaults.update(overrides)
        return ChainConfig(**defaults)

    def test_pins_guest_root_and_runs_the_builder(self) -> None:
        script = build_script(self._config(), r"C:\pbi\out\board.pbix")
        assert r"$env:PYTHONPATH='C:\pbi\abf\src'" in script
        assert r"C:\pbi\abf\examples\engine_table_board.py" in script
        assert r"--table 'Sales'" in script
        assert "--title" not in script

    def test_groups_a_title_when_given(self) -> None:
        script = build_script(self._config(title="Q3 Sales"), r"C:\pbi\out\board.pbix")
        assert "--title 'Q3 Sales'" in script

    def test_quotes_a_hostile_table_so_it_cannot_inject(self) -> None:
        script = build_script(
            self._config(table="x'; Remove-Item C:\\ -Recurse; '"),
            r"C:\pbi\out\board.pbix",
        )
        assert "--table 'x''; Remove-Item C:\\ -Recurse; '''" in script
        assert "--table 'x';" not in script
