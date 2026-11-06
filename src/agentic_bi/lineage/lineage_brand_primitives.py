"""Token, config and finding primitives of the brand-compliance metrics.

These helpers turn the raw lineage tokens of a page/visual (``hex#D32F2F``,
``theme#0``, font names) into normalized colours and fonts, load the single
source of rules (:class:`agentic_bi.brand.config.BrandConfig`) and build the
finding dicts. The metric functions themselves live in
:mod:`agentic_bi.lineage.lineage_brand_metrics`.
"""

from __future__ import annotations

import logging
from pathlib import Path

_log = logging.getLogger(__name__)

# Font placeholders in the visual config (not real fonts).
_PLACEHOLDER_FONTS = {"+mn-lt", "+mj-lt", "+mn-ea", "+mj-ea", "themefont", ""}


def _load_config():
    """Lazy import of `BrandConfig` (no hard dependency) + YAML load."""
    pkg_dir = Path(__file__).resolve().parents[1]
    from agentic_bi.brand.config import BrandConfig

    yaml_path = pkg_dir / "brand_config.yaml"
    if yaml_path.exists():
        try:
            return BrandConfig.load(yaml_path)
        except Exception as exc:  # noqa: BLE001 - config optional, default() exists
            _log.debug("brand_config.yaml load failed: %s", exc)
    return BrandConfig.default()


def _hex_from(token: str) -> str:
    """Extract '#rrggbb' from a lineage token ('hex#D32F2F', 'theme#0')."""
    if not token or not isinstance(token, str):
        return ""
    i = token.find("#")
    if i < 0:
        return ""
    v = token[i + 1 :].strip()
    if len(v) >= 6:
        v = v[:6]
    if len(v) != 6:
        return ""
    try:
        int(v, 16)
    except ValueError:
        return ""
    return "#" + v.lower()


def _is_neutral(hex_color: str) -> bool:
    h = hex_color.lstrip("#")
    return h[0:2] == h[2:4] == h[4:6]


def _clean_fonts(fonts: list[str] | None) -> list[str]:
    seen: list[str] = []
    for f in fonts or []:
        name = str(f).replace("\ufffd", "").strip()
        if name.lower() in _PLACEHOLDER_FONTS:
            continue
        if name and name not in seen:
            seen.append(name)
    return seen


def _pct(part: int, total: int) -> int | None:
    if total <= 0:
        return None
    return round(100 * part / total)


def _allow_extra(cfg) -> set[str]:
    """Normalize the config's `allow_extra` to lowercase '#rrggbb' (case-insensitive)."""
    out = set()
    for c in getattr(cfg, "allow_extra", []) or []:
        h = _hex_from(str(c)) or (str(c) if str(c).startswith("#") else "")
        if h:
            out.add(h.lower())
    return out


def _finding(
    rule_id: str, level: str, category: str, message: str, detail: str = ""
) -> dict:
    return {
        "rule_id": rule_id,
        "level": level,
        "category": category,
        "message": message,
        "detail": detail,
    }
