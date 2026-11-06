"""Tests for `safe_stem`: confinement, Unicode names and reserved device names."""

from __future__ import annotations

import logging

from agentic_bi.report import plantuml_names


class TestSafeStemConfinement:
    def test_directory_components_are_stripped(self) -> None:
        assert plantuml_names.safe_stem("../../etc/passwd") == "passwd"

    def test_only_the_last_path_component_is_kept(self) -> None:
        assert plantuml_names.safe_stem("my diagram/v2") == "v2"

    def test_spaces_and_punctuation_become_underscores(self) -> None:
        assert plantuml_names.safe_stem("my diagram!") == "my_diagram"

    def test_an_empty_name_falls_back(self) -> None:
        assert plantuml_names.safe_stem("...") == "diagram"
        assert plantuml_names.safe_stem("", fallback="") == "diagram"

    def test_the_stem_is_bounded_and_truncation_stays_unique(self) -> None:
        first = plantuml_names.safe_stem("x" * 300)
        second = plantuml_names.safe_stem("x" * 299 + "y")
        assert len(first) <= 100
        assert first != second


class TestSafeStemUnicode:
    def test_a_non_ascii_name_is_preserved(self) -> None:
        assert plantuml_names.safe_stem("Отчёт 2024") == "Отчёт_2024"

    def test_a_fully_non_ascii_name_does_not_fall_back(self) -> None:
        assert plantuml_names.safe_stem("отчёт") == "отчёт"


class TestReservedDeviceNames:
    def test_windows_device_names_are_prefixed(self) -> None:
        assert plantuml_names.safe_stem("con") == "_con"
        assert plantuml_names.safe_stem("LPT1.png") == "_LPT1.png"
        assert plantuml_names.safe_stem("COM9.log") == "_COM9.log"

    def test_the_rename_is_logged(self, caplog) -> None:
        with caplog.at_level(logging.WARNING, logger=plantuml_names.__name__):
            plantuml_names.safe_stem("nul")
        assert "reserved Windows device" in caplog.text

    def test_com0_and_lpt0_are_not_treated_as_devices(self) -> None:
        assert plantuml_names.safe_stem("COM0") == "COM0"
        assert plantuml_names.safe_stem("LPT0") == "LPT0"
