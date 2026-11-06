"""Offline tests for the strict Desktop oracle's error-dialog probe.

`_engine_oracle` runs on the Windows guest, so the probe is never executed on a
host. Its window walk is pure logic once `_User32` is replaced by a fake: the
probe must report an error dialog only for a *visible* window whose title
mentions the desktop's "wrong ..." message, and must keep enumerating other
windows either way.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from agentic_bi import _engine_oracle


class _FakeUser32:
    """A `_User32` stand-in: window titles keyed by handle."""

    def __init__(self, titles: dict[int, str], visible: set[int]) -> None:
        self._titles = titles
        self._visible = visible

    def is_visible(self, hwnd: int) -> bool:
        return hwnd in self._visible

    def text_length(self, hwnd: int) -> int:
        return len(self._titles.get(hwnd, ""))

    def window_text(self, hwnd: int, size: int) -> str:
        return self._titles.get(hwnd, "")[: size - 1]

    def enum_windows(self, proc: Callable[[int, int], bool]) -> None:
        for hwnd in sorted(self._titles):
            if not proc(hwnd, 0):
                break


def test_dialog_detects_a_visible_wrong_password_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeUser32({1: "Please check your credentials - wrong password"}, {1})
    monkeypatch.setattr(_engine_oracle, "_User32", lambda: fake)
    assert _engine_oracle._dialog() is True


def test_dialog_ignores_hidden_and_unrelated_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hidden error window, or a visible but unrelated one, is not an error."""

    fake = _FakeUser32({1: "wrong password", 2: "Power BI Desktop"}, {2})
    monkeypatch.setattr(_engine_oracle, "_User32", lambda: fake)
    assert _engine_oracle._dialog() is False
