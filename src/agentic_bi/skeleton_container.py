"""Shared wrappers for assembling a PBIP visual container.

Kept separate from `skeleton_visuals` so that module (and this one) stay within
the file-size budget while both `skeleton_visuals` and `skeleton_visuals_extra`
share the container/query wrappers.

Public API:
    query_layout(name, single, x, y, w, h) -> dict  - a positioned container
    full_query(table, source, selects, ...) -> dict  - prototypeQuery From+Select
"""

from __future__ import annotations

import json


def query_layout(name: str, single: dict, x: int, y: int, w: int, h: int) -> dict:
    """Wrap a singleVisual into a visual container with a position."""
    return {
        "config": json.dumps(
            {
                "name": name,
                "layouts": [
                    {
                        "id": 0,
                        "position": {"x": x, "y": y, "width": w, "height": h, "z": 0},
                    }
                ],
                "singleVisual": single,
            },
            ensure_ascii=False,
        ),
        "filters": "[]",
        "tabOrder": 0,
    }


def full_query(
    table: str,
    source: str,
    selects: list[dict],
    measure_table: str | None = None,
    measure_alias: str | None = None,
) -> dict:
    """prototypeQuery From + Select (a shared wrapper)."""
    _from = [{"Name": source, "Entity": table, "Type": 0}]
    if measure_alias:
        _from.append({"Name": measure_alias, "Entity": measure_table, "Type": 0})
    return {"Version": 2, "From": _from, "Select": selects}


__all__ = ["query_layout", "full_query"]
