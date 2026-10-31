"""Read page/visual geometry from a `.pbix` `Report/Layout` (stdlib only).

A guide needs three things per page: the canvas size, and for every visual its
box (`x/y/width/height` in design pixels) plus the metadata a human would want
on hover — visual type, projected fields, measures, visual filters and the DAX
of the measures it uses.

Everything is derived from `Report/Layout`, so no engine, no network and no
image analysis is involved: the same geometry is valid whether the picture comes
from a rendered portal, a Desktop screenshot or a test render. The untrusted
layout parsing lives in `guide_layout`.

Public API:
    GuideVisual          - one visual: identity, geometry, metadata
    GuidePage            - one page: name, canvas size, visuals
    GuideGeometry        - the whole report (source + pages)
    extract_page_geometry(pbix, measures=None) -> GuideGeometry
    load_measure_expressions(pbix) -> dict[str, str]   (needs pbixray)
    safe_name(name) -> str           (re-exported from guide_names)
    unique_stems(pages) -> list[str] (re-exported from guide_names)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentic_bi.board_guide import guide_layout as gl
from agentic_bi.board_guide.guide_names import safe_name, unique_stems

_DEFAULT_W, _DEFAULT_H = 1280.0, 720.0


@dataclass
class GuideVisual:
    """One visual: identity, its true box and the metadata shown on hover."""

    visual_type: str
    title: str = ""
    x: float = 0
    y: float = 0
    width: float = 0
    height: float = 0
    z: float = 0
    fields: list[str] = field(default_factory=list)
    measures: list[str] = field(default_factory=list)
    filters: list[str] = field(default_factory=list)
    dax: dict[str, str] = field(default_factory=dict)

    @property
    def label(self) -> str:
        """A human label: title, else first measure/field, else the type."""
        if self.title:
            return self.title
        if self.measures:
            return self.measures[0]
        if self.fields:
            return self.fields[0]
        return self.visual_type

    @property
    def has_data(self) -> bool:
        """Whether the visual projects any field or measure."""
        return bool(self.fields or self.measures)

    def hotspot(self, page_width: float, page_height: float) -> dict[str, float]:
        """The box as canvas percentages, so it overlays any screenshot scale.

        Percentages stay in `[0, 100]`: a visual whose box is unset, negative or
        (partly) outside the canvas is clamped to the visible area instead of
        producing a hotspot off-screen. A zero/negative canvas falls back to the
        default canvas.
        """
        w = page_width if page_width > 0 else _DEFAULT_W
        h = page_height if page_height > 0 else _DEFAULT_H
        left = min(max(self.x / w * 100.0, 0.0), 100.0)
        top = min(max(self.y / h * 100.0, 0.0), 100.0)
        width = min(max(self.width / w * 100.0, 0.0), 100.0 - left)
        height = min(max(self.height / h * 100.0, 0.0), 100.0 - top)
        return {"left": left, "top": top, "width": width, "height": height}

    def to_dict(self) -> dict[str, Any]:
        """A JSON-ready view (saved geometry and tests)."""
        return {
            "type": self.visual_type,
            "title": self.label,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "z": self.z,
            "fields": list(self.fields),
            "measures": list(self.measures),
            "filters": list(self.filters),
            "dax": dict(self.dax),
        }


@dataclass
class GuidePage:
    """One report page: its name, canvas size and visuals."""

    name: str
    width: float = _DEFAULT_W
    height: float = _DEFAULT_H
    ordinal: int = 0
    visuals: list[GuideVisual] = field(default_factory=list)

    @property
    def stem(self) -> str:
        """The safe stem used for `page_<stem>.png` / `guide_<stem>.html`."""
        return safe_name(self.name)

    def to_dict(self) -> dict[str, Any]:
        """A JSON-ready view of the page."""
        return {
            "displayName": self.name,
            "ordinal": self.ordinal,
            "width": self.width,
            "height": self.height,
            "visuals": [v.to_dict() for v in self.visuals],
        }


@dataclass
class GuideGeometry:
    """The whole report: its source name and every visible page."""

    source: str
    pages: list[GuidePage] = field(default_factory=list)

    @property
    def visual_count(self) -> int:
        """Total number of visuals across the report."""
        return sum(len(p.visuals) for p in self.pages)

    def to_dict(self) -> dict[str, Any]:
        """A JSON-ready view (the `--geometry-json` payload)."""
        return {"pbix": self.source, "pages": [p.to_dict() for p in self.pages]}


def _ordinal(value: Any) -> int:
    """A page ordinal as int; a non-numeric value (`"abc"`, a dict) gives 0."""
    if isinstance(value, bool):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _visual(vc: dict, measures: dict[str, str]) -> GuideVisual | None:
    """Build one visual from a container, or None when it is unreadable."""
    raw = vc.get("config")
    if not raw:
        return None
    try:
        cfg = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
    except (ValueError, TypeError):
        return None
    if not isinstance(cfg, dict):
        return None
    sv = gl.as_dict(cfg.get("singleVisual"))
    fields, names = gl.projections(sv)
    x, y, w, h, z = gl.position(vc, cfg)
    return GuideVisual(
        visual_type=str(gl.as_dict(sv).get("visualType") or "unknown"),
        title=gl.visual_title(cfg),
        x=round(x, 1),
        y=round(y, 1),
        width=round(w, 1),
        height=round(h, 1),
        z=z,
        fields=fields,
        measures=names,
        filters=gl.filter_refs(vc.get("filters")),
        dax={n: measures[n] for n in names if measures.get(n)},
    )


def extract_page_geometry(
    pbix: str | Path, measures: dict[str, str] | None = None
) -> GuideGeometry:
    """Build the typed geometry for every visible page of a `.pbix`.

    Args:
        pbix: the source `.pbix`.
        measures: optional `{measure name: "table :: expression"}` map; when
            given, each visual carries the DAX of the measures it references.

    Returns:
        A `GuideGeometry` in page order, visuals sorted top-left first.

    Raises:
        ValueError: when `Report/Layout` cannot be decoded.
    """
    layout = gl.load_layout(pbix)
    pages: list[GuidePage] = []
    for section in layout.get("sections") or []:
        if not isinstance(section, dict):
            continue
        if gl.is_hidden(section):
            continue
        page = GuidePage(
            name=str(section.get("displayName") or section.get("name") or "?"),
            width=gl.as_float(section.get("width")) or _DEFAULT_W,
            height=gl.as_float(section.get("height")) or _DEFAULT_H,
            ordinal=_ordinal(section.get("ordinal")),
        )
        containers = section.get("visualContainers") or []
        if not isinstance(containers, list):
            containers = []
        for vc in containers:
            if not isinstance(vc, dict):
                continue
            visual = _visual(vc, measures or {})
            if visual is not None:
                page.visuals.append(visual)
        page.visuals.sort(key=lambda v: (v.y, v.x))
        pages.append(page)
    return GuideGeometry(source=str(pbix), pages=pages)


def load_measure_expressions(pbix: str | Path) -> dict[str, str]:
    """Return `{measure name: "table :: expression"}` via `pbixray`.

    Optional: without `pbixray` (or when the model cannot be read) an empty map
    is returned and the guide shows measures without their DAX.
    """
    try:
        from agentic_bi.dax_detail import extract_measures
    except ImportError:  # pragma: no cover - dax_detail is always importable
        return {}
    try:
        rows = extract_measures(Path(pbix))
    except Exception:  # noqa: BLE001 - the decoder is optional and best-effort
        return {}
    out: dict[str, str] = {}
    for row in rows:
        name = (row.get("name") or "").strip()
        expr = (row.get("expr") or "").strip()
        if name and expr:
            out[name] = f"{row.get('table', '')} :: {expr}"
    return out


__all__ = [
    "GuideGeometry",
    "GuidePage",
    "GuideVisual",
    "extract_page_geometry",
    "load_measure_expressions",
    "safe_name",
    "unique_stems",
]
