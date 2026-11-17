"""One Desktop path configuration serves the build and the oracle.

`PBI_RS_DESKTOP` is documented as the executable, while the engine build needs
the bin directory (`PBI_RS_BIN`) and the oracle spawns the executable. Feeding a
directory to `subprocess.Popen` fails with WinError 5 "Access is denied" and the
traceback never names the real problem (measured on the guest), so both stages
accept either form through one pair of helpers.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentic_bi._engine_oracle import _default_desktop
from agentic_bi.guest_chain import ChainConfig
from agentic_bi.guest_chain_build import build_script
from agentic_bi.guest_types import (
    DEFAULT_DESKTOP_BIN,
    GuestConfig,
    desktop_bin,
    desktop_exe,
)

BIN = r"C:\Program Files\Microsoft Power BI Desktop\bin"
EXE = BIN + r"\PBIDesktop.exe"


class TestPathHelpers:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (BIN, BIN),
            (EXE, BIN),
            (BIN + "\\", BIN),
            ("  " + BIN + "  ", BIN),
            (BIN.upper(), BIN.upper()),
            (None, DEFAULT_DESKTOP_BIN),
            ("", DEFAULT_DESKTOP_BIN),
        ],
    )
    def test_the_bin_directory_accepts_either_form(
        self, raw: str | None, expected: str
    ) -> None:
        assert desktop_bin(raw) == expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (EXE, EXE),
            (BIN, EXE),
            (BIN + "\\", EXE),
            (EXE.upper(), EXE.upper()),
            (None, DEFAULT_DESKTOP_BIN + r"\PBIDesktop.exe"),
        ],
    )
    def test_the_executable_accepts_either_form(
        self, raw: str | None, expected: str
    ) -> None:
        assert desktop_exe(raw) == expected


class TestOracleResolution:
    def test_a_directory_in_the_environment_becomes_the_executable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PBI_RS_DESKTOP", BIN)
        assert _default_desktop() == EXE

    def test_an_executable_in_the_environment_is_kept(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PBI_RS_DESKTOP", EXE)
        assert _default_desktop() == EXE


class TestBuildScript:
    def _script(self, desktop: str | None) -> str:
        config = ChainConfig(
            guest=GuestConfig(
                winrm="http://guest:5985/wsman",
                user="u",
                password="p",
                root=r"C:\pbi\abf",
                out=r"C:\pbi\out",
                desktop=desktop,
            ),
            data=Path("sales.csv"),
            table="Sales",
            out=Path("output_files/board.pbix"),
        )
        return build_script(config, r"C:\pbi\out\board.pbix")

    def test_a_directory_configures_the_engine_bin_dir(self) -> None:
        assert r"$env:PBI_RS_BIN='" + BIN + "'" in self._script(BIN)

    def test_an_executable_configures_the_parent_directory(self) -> None:
        assert r"$env:PBI_RS_BIN='" + BIN + "'" in self._script(EXE)

    def test_an_unset_desktop_falls_back_to_the_default_bin(self) -> None:
        assert DEFAULT_DESKTOP_BIN in self._script(None)
