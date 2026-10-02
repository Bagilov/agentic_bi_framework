"""Distortion markers and their scanning for DAX/M analysis."""
from __future__ import annotations

import re

# Markers in DAX indicating a distortion risk.
DAX_DISTORT_MARKERS = {
    "hardcoded_threshold": re.compile(r"<=?\s*0\.\d+|>=\s*0\.\d+|\b\d+\.\d{2,}\b"),
    "filter_all": re.compile(r"FILTER\s*\(\s*ALL"),
    "isblank_default": re.compile(r"ISBLANK\s*\("),
    "switch_const": re.compile(r"SWITCH\s*\("),
    "var_no_return": re.compile(r"VAR\b.+?RETURN\b", re.DOTALL),
    "format_column": re.compile(r"FORMAT\s*\("),
}

# Markers in Power Query M code indicating a risk.
M_DISTORT_MARKERS = {
    "hardcoded_path": re.compile(
        r"(C:|D:|E:|H:)[\\/]Users|File\.Contents\(\s*[\"']([A-Za-z]:|\\\\)"
    ),
    "local_now": re.compile(r"DateTime\.LocalNow|DateTime\.FixedLocalNow",
                            re.IGNORECASE),
    "fixed_date": re.compile(r"#date\(\s*\d{4}"),
    "file_share": re.compile(r"\\\\[A-Za-z0-9_.-]+\\[A-Za-z0-9_.-]+"),
}


def scan_markers(expr: str, markers: dict) -> list[str]:
    """Return the list of markers that fired for one expression."""
    return [name for name, pat in markers.items() if pat.search(expr)]
