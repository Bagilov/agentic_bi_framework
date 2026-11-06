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
import math
import re
import zipfile
import zlib
from pathlib import Path
from typing import Any

from agentic_bi.layout_meta import decode_layout
from agentic_bi.web_report.web_checks import element_issues, visual_type
from agentic_bi.web_report.web_filter_checks import filter_issues as page_filter_issues
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

#: Largest `Report/Layout` member this loader will decompress. A layout is JSON
#: for one report, so real files are a few MiB at most; a zip bomb declaring a
#: multi-gigabyte member would otherwise be read into memory before any JSON
#: check runs. `ZipInfo.file_size` is attacker-controlled, so the read itself is
#: bounded too.
# Size exception (>300 lines): the untrusted-layout reader, its coercions and the
# model registry belong together; a validated field and the report it lands in
# must be readable in one pass.

_MAX_LAYOUT_BYTES = 64 * 1024 * 1024


# ─── layout helpers ───────────────────────────────────────────


def _decode_layout(raw: bytes) -> dict:
    return decode_layout(raw)


def load_layout(pbix: str | Path) -> dict:
    """Read and decode `Report/Layout` from a `.pbix`.

    Raises:
        ValueError: the file is not a zip container, it has no readable
            `Report/Layout` member, that member is not JSON, or it decompresses
            past `_MAX_LAYOUT_BYTES` (a `.pbix` is untrusted input, and an
            unbounded read of a hostile member would exhaust memory).
            `BadZipFile`, `KeyError` and decoder/JSON errors are translated so
            the CLI boundary reports a short input error that names the file
            instead of a bare `JSONDecodeError` or a traceback.
    """
    try:
        with zipfile.ZipFile(pbix) as z:
            info = z.getinfo("Report/Layout")
            if info.file_size > _MAX_LAYOUT_BYTES:
                raise ValueError(
                    f"{pbix}: Report/Layout is {info.file_size} B, over the "
                    f"{_MAX_LAYOUT_BYTES}-byte limit"
                )
            with z.open(info) as member:
                raw = member.read(_MAX_LAYOUT_BYTES + 1)
    except zipfile.BadZipFile as exc:
        raise ValueError(f"{pbix}: не zip-контейнер .pbix ({exc})") from exc
    except KeyError as exc:
        raise ValueError(f"{pbix}: в контейнере нет Report/Layout") from exc
    except (zlib.error, EOFError, RuntimeError) as exc:
        # A corrupt deflate stream, a truncated member or an encrypted one is
        # input damage, not a framework bug: translate it so the CLI reports one
        # short line instead of ending on a `zlib.error` traceback.
        raise ValueError(f"{pbix}: Report/Layout не читается ({exc})") from exc
    if len(raw) > _MAX_LAYOUT_BYTES:
        raise ValueError(
            f"{pbix}: Report/Layout is larger than the {_MAX_LAYOUT_BYTES}-byte limit"
        )
    try:
        return _decode_layout(raw)
    except (ValueError, RecursionError) as exc:
        raise ValueError(f"{pbix}: Report/Layout не разбирается как JSON") from exc


def _visual_title(cfg: dict) -> str:
    """Best-effort title of a visual from its `objects.title` literal."""
    try:
        props = cfg["singleVisual"]["objects"]["title"][0]["properties"]
        literal = props["text"]["expr"]["Literal"]["Value"]
        return str(literal).strip("'")
    except (KeyError, IndexError, TypeError):
        return ""


def _projected_fields(sv: dict) -> tuple[list[str], list[str]]:
    """Return (fields, roles) from the visual's projections.

    `projections`, each role's reference list and each reference come from the
    untrusted layout: a list-typed `projections`, a scalar role and a non-object
    reference are ignored instead of raising `AttributeError`.
    """
    projections = sv.get("projections")
    if not isinstance(projections, dict):
        return [], []
    fields: list[str] = []
    roles: list[str] = []
    for role, refs in projections.items():
        roles.append(role)
        if not isinstance(refs, list):
            continue
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            qref = ref.get("queryRef")
            if isinstance(qref, str) and qref:
                fields.append(qref)
    return fields, roles


def _num(value: Any) -> float:
    """Coerce a layout coordinate to a finite float, tolerating bad values.

    The layout is untrusted: a string `"abc"`, a nested object, `NaN` or `inf` in
    `x`/`y`/`width`/`height` must not abort the whole inspection (or overflow the
    later `int()` cast), so an unparsable/non-finite value counts as 0.
    """
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def _page_dim(value: Any, default: float) -> float:
    """A positive finite page dimension, else the report default."""
    number = _num(value)
    return number if number > 0 else default


def _count_filters(raw: Any) -> int:
    if not raw or raw == "[]":
        return 0
    try:
        flts = json.loads(raw)
    except (ValueError, TypeError, RecursionError):
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
    if not isinstance(layout, dict):
        return model

    sections = layout.get("sections") or []
    if not isinstance(sections, list):
        sections = []
    for ordinal, sec in enumerate(sections):
        if not isinstance(sec, dict):
            continue
        page = PageReport(
            name=sec.get("displayName") or f"Page {sec.get('ordinal', 0)}",
            width=_page_dim(sec.get("width"), 1280),
            height=_page_dim(sec.get("height"), 1050),
            filter_issues=page_filter_issues(sec.get("filters", "[]")),
        )
        visuals = sec.get("visualContainers") or []
        if not isinstance(visuals, list):
            visuals = []
        for idx, vc in enumerate(visuals):
            if not isinstance(vc, dict):
                continue
            page.elements.append(
                _element(vc, idx, page.name, registry, page_ordinal=ordinal)
            )
        model.pages.append(page)
    return model


def _element(
    vc: dict,
    idx: int,
    page: str,
    registry: dict | None,
    *,
    page_ordinal: int = 0,
) -> ElementReport:
    """Build one `ElementReport`; a malformed `config` degrades to an empty one.

    The container `config` is untrusted JSON: it may parse to a scalar, a list or
    an object whose `singleVisual` is not an object. Each of those becomes `{}`
    so the element still gets its structural diagnostics instead of aborting the
    whole inspection with an `AttributeError`.

    `page_ordinal` qualifies the element key: a report may hold two pages with
    the same display name, and `page#index` alone made their elements collide.
    """
    raw_cfg = vc.get("config", "")
    cfg_text = (
        raw_cfg if isinstance(raw_cfg, str) else json.dumps(raw_cfg, ensure_ascii=False)
    )
    try:
        cfg = json.loads(cfg_text or "{}")
    except (ValueError, TypeError, RecursionError):
        cfg = {}
    if not isinstance(cfg, dict):
        cfg = {}
    sv = cfg.get("singleVisual")
    if not isinstance(sv, dict):
        sv = {}
    fields, roles = _projected_fields(sv)
    colors, fonts = _usage_counts(cfg_text)
    element = ElementReport(
        page=page,
        index=idx,
        visual_type=visual_type(sv),
        title=_visual_title(cfg),
        x=_num(vc.get("x")),
        y=_num(vc.get("y")),
        width=_num(vc.get("width")),
        height=_num(vc.get("height")),
        fields=fields,
        roles=roles,
        colors=colors,
        fonts=fonts,
        visual_filters=_count_filters(vc.get("filters", "[]")),
        page_ordinal=page_ordinal,
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
