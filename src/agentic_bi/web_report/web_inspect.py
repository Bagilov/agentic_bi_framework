"""Inspect a `.pbix` report element by element and collect issues.

This adapts the "one record per element with a tooltip of its metrics" idea from
the process-mining HTML report to the structure of a Power BI `Report/Layout`:
every `visualContainer` becomes an `ElementReport` carrying its identity,
geometry, projected fields and the checks it failed (see `web_checks`).

Public API:
    build_model(pbix, registry=None) -> WebReportModel
    inspect_layout(layout, registry=None, source=...) -> WebReportModel
    load_layout(pbix) -> dict
    registry_from_pbix(pbix) -> dict          (needs pbixray)
"""

from __future__ import annotations

import json
import logging
import re
import zipfile
from pathlib import Path
from typing import Any

from agentic_bi.web_report.web_checks import element_issues
from agentic_bi.web_report.web_model import (
    ElementReport,
    PageReport,
    WebReportModel,
)

logger = logging.getLogger(__name__)

_HEX_RE = re.compile(r"#([0-9A-Fa-f]{6})\b")
# `fontFamily` appears either as a plain string or as a literal expression
# (`"fontFamily": {"expr": {"Literal": {"Value": "'Brand Sans'"}}}`).
_FONT_RE = re.compile(r'"fontFamily"\s*:\s*"([^"]+)"')
_FONT_LITERAL_RE = re.compile(
    r'"fontFamily"\s*:\s*\{\s*"expr"\s*:\s*\{\s*"Literal"\s*:\s*\{\s*'
    r'"Value"\s*:\s*"\'?([^"\']+)\'?"'
)


# ─── layout helpers ───────────────────────────────────────────


def _decode_layout(raw: bytes) -> dict:
    for enc in ("utf-16-le", "utf-8-sig", "utf-8"):
        try:
            return json.loads(raw.decode(enc))
        except Exception:  # noqa: BLE001
            continue
    raise ValueError("cannot decode Report/Layout")


def load_layout(pbix: str | Path) -> dict:
    """Read and decode `Report/Layout` from a `.pbix`."""
    with zipfile.ZipFile(pbix) as z:
        return _decode_layout(z.read("Report/Layout"))


def _visual_title(cfg: dict) -> str:
    """Best-effort title of a visual from its `objects.title` literal."""
    try:
        props = cfg["singleVisual"]["objects"]["title"][0]["properties"]
        literal = props["text"]["expr"]["Literal"]["Value"]
        return str(literal).strip("'")
    except (KeyError, IndexError, TypeError):
        return ""


def _projected_fields(sv: dict) -> tuple[list[str], list[str]]:
    """Return (fields, roles) from the visual's projections."""
    fields: list[str] = []
    roles: list[str] = []
    for role, refs in (sv.get("projections") or {}).items():
        roles.append(role)
        for ref in refs:
            qref = ref.get("queryRef")
            if qref:
                fields.append(qref)
    return fields, roles


def _count_filters(raw: Any) -> int:
    if not raw or raw == "[]":
        return 0
    try:
        flts = json.loads(raw)
    except (ValueError, TypeError):
        return 1
    return len(flts) if isinstance(flts, list) else 1


def _usage_counts(text: str) -> tuple[int, int]:
    """Distinct colors (HEX) and font families referenced in a config blob."""
    colors = {m.group(1).upper() for m in _HEX_RE.finditer(text)}
    fonts = {m.group(1) for m in _FONT_RE.finditer(text)}
    fonts |= {m.group(1) for m in _FONT_LITERAL_RE.finditer(text)}
    return len(colors), len(fonts)


# ─── model assembly ───────────────────────────────────────────


def inspect_layout(
    layout: dict, registry: dict | None = None, source: str = "<layout>"
) -> WebReportModel:
    """Turn a decoded `Report/Layout` into a `WebReportModel`."""
    model = WebReportModel(source=source, fields_checked=registry is not None)
    model.checks_run = ["structure", "binding", "filter"]
    if registry is not None:
        model.checks_run.append("model-membership")

    for sec in layout.get("sections", []):
        page = PageReport(
            name=sec.get("displayName") or f"Page {sec.get('ordinal', 0)}",
            width=float(sec.get("width") or 1280),
            height=float(sec.get("height") or 1050),
        )
        for idx, vc in enumerate(sec.get("visualContainers", [])):
            page.elements.append(_element(vc, idx, page.name, registry))
        model.pages.append(page)
    return model


def _element(vc: dict, idx: int, page: str, registry: dict | None) -> ElementReport:
    raw_cfg = vc.get("config", "")
    cfg_text = (
        raw_cfg if isinstance(raw_cfg, str) else json.dumps(raw_cfg, ensure_ascii=False)
    )
    try:
        cfg = json.loads(cfg_text or "{}")
    except (ValueError, TypeError):
        cfg = {}
    sv = cfg.get("singleVisual") or {}
    fields, roles = _projected_fields(sv)
    colors, fonts = _usage_counts(cfg_text)
    element = ElementReport(
        page=page,
        index=idx,
        visual_type=sv.get("visualType") or "unknown",
        title=_visual_title(cfg),
        x=float(vc.get("x") or 0),
        y=float(vc.get("y") or 0),
        width=float(vc.get("width") or 0),
        height=float(vc.get("height") or 0),
        fields=fields,
        roles=roles,
        colors=colors,
        fonts=fonts,
        visual_filters=_count_filters(vc.get("filters", "[]")),
    )
    element.issues = element_issues(sv, vc, roles, registry)
    return element


def build_model(pbix: str | Path, registry: dict | None = None) -> WebReportModel:
    """Build the `WebReportModel` for a `.pbix` (single entry point)."""
    pbix = Path(pbix)
    layout = load_layout(pbix)
    return inspect_layout(layout, registry=registry, source=pbix.name)


def registry_from_pbix(pbix: str | Path) -> dict:
    """Build a `{table:{columns,measures}}` registry via `pbixray`.

    Returns an empty dict when `pbixray` is unavailable; callers then skip the
    model-membership checks (the clone still works, just without that category).
    """
    try:
        from pbixray import PBIXRay
    except ImportError:
        logger.info("pbixray not installed; skipping model membership checks")
        return {}
    registry: dict[str, dict[str, list[str]]] = {}
    with PBIXRay(str(pbix)) as pb:
        for table in pb.tables:
            try:
                columns = list(pb.get_table(table).columns)
            except Exception:  # noqa: BLE001 - decoder is best-effort
                columns = []
            registry[table] = {"columns": columns, "measures": []}
        try:
            for row in pb.dax_measures.itertuples():
                table = getattr(row, "TableName", None)
                name = getattr(row, "Name", None)
                if table in registry and name:
                    registry[table]["measures"].append(name)
        except Exception:  # noqa: BLE001
            pass
    return registry
