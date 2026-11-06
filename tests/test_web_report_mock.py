"""Mock glyph tests for `web_report`: the glyphs use theme tokens, not literals.

A fixed dark fill for the donut hole painted a dark disc on the light canvas, so
the mock must not embed literal colors; theme tokens follow light/dark/print.
"""

from __future__ import annotations

import re
from pathlib import Path

import agentic_bi.web_report.web_mock as web_mock

_HEX_LITERAL = re.compile(r"#[0-9A-Fa-f]{3,8}\b")


def test_mock_source_has_no_literal_colors():
    source = Path(web_mock.__file__).read_text(encoding="utf-8")
    assert _HEX_LITERAL.findall(source) == []


def test_donut_hole_uses_a_theme_token():
    body = web_mock.mock_body("donutChart")
    assert 'fill="var(--surface-2)"' in body
    assert 'fill="#' not in body
