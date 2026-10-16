"""Shared builders for the `web_report` tests.

Not a test module: it only provides in-memory `Report/Layout` constructors so the
check tests and the render tests agree on one layout shape.
"""

from __future__ import annotations

import json
import re


def make_layout(visuals: list[dict], page: str = "P", width: int = 1280) -> dict:
    """A minimal `Report/Layout` with one page holding `visuals`."""
    return {
        "sections": [
            {
                "displayName": page,
                "width": width,
                "height": 720,
                "visualContainers": visuals,
            }
        ]
    }


def select_of(name: str) -> dict:
    """Build a realistic Select entry from a queryRef string.

    ``Sum(T.c)`` -> an Aggregation select; ``T.c`` -> a Column select. Anything
    else (a bare name) becomes a plain ``{"Name": ...}`` placeholder.
    """
    m = re.match(r"^([A-Za-z]+)\((.+)\.(.+)\)$", name)
    if m:
        return {
            "Name": name,
            "Aggregation": {
                "Function": 0,
                "Expression": {
                    "Column": {
                        "Expression": {"SourceRef": {"Source": "t"}},
                        "Property": m.group(3),
                    }
                },
            },
        }
    if "." in name:
        _table, prop = name.rsplit(".", 1)
        return {
            "Name": name,
            "Column": {
                "Expression": {"SourceRef": {"Source": "t"}},
                "Property": prop,
            },
        }
    return {"Name": name}


def make_container(
    visual_type: str,
    projections: dict,
    selects: list[str],
    x: int = 20,
    title: str = "",
) -> dict:
    """A minimal visualContainer with a prototypeQuery and projections."""
    objects = {}
    if title:
        objects["title"] = [
            {"properties": {"text": {"expr": {"Literal": {"Value": f"'{title}'"}}}}}
        ]
    cfg = {
        "singleVisual": {
            "visualType": visual_type,
            "projections": projections,
            "prototypeQuery": {
                "From": [{"Name": "t", "Entity": "Sales", "Type": 0}],
                "Select": [select_of(n) for n in selects],
            },
            "objects": objects,
        },
    }
    return {
        "x": x,
        "y": 20,
        "width": 400,
        "height": 300,
        "config": json.dumps(cfg),
        "filters": "[]",
    }


def raw_container(cfg: dict, filters: str = "[]") -> dict:
    """A container from a raw config dict (for malformed/decorative cases)."""
    return {
        "x": 0,
        "y": 0,
        "width": 100,
        "height": 100,
        "config": json.dumps(cfg),
        "filters": filters,
    }
