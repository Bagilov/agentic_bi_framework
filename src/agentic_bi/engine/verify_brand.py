"""Brand-style comparison of a report theme (`extract_report_theme`, `verify_brand`)."""

from __future__ import annotations

import json
import logging
import re
import zipfile
from pathlib import Path

from agentic_bi.engine.verify_core import CheckResult, _check
from agentic_bi.layout_meta import decode_layout

logger = logging.getLogger(__name__)


# ─── style guide (final element comparison) ────────────────────

# Report theme in a .pbix: Report/Layout.theme -> JSON name + registered resources.
_THEME_MEMBER_RE = re.compile(r"^(Report/StaticResources/.*/[^/]+\.json)$")
_VIS_HEX_RE = re.compile(r"#([0-9A-Fa-f]{6})\b")
_VIS_FONT_RE = re.compile(r'"fontFamily"\s*:\s*"([^"]+)"')
# Primary accent and a "near-accent" tolerance (dashboards often use #D0302A / #D3212A
# instead of the canonical #D32F2F).
_BRAND_ACCENT = (0xD3, 0x2F, 0x2F)
_ACCENT_TOLERANCE = 20


def _is_near_brand_accent(hex_color: str) -> bool:
    """Whether a color is close to the primary accent #D32F2F (within tolerance)."""
    try:
        r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    except (ValueError, IndexError):
        return False
    return (
        abs(r - _BRAND_ACCENT[0]) <= _ACCENT_TOLERANCE
        and abs(g - _BRAND_ACCENT[1]) <= _ACCENT_TOLERANCE
        and abs(b - _BRAND_ACCENT[2]) <= _ACCENT_TOLERANCE
    )


def extract_report_theme(pbix: Path) -> dict:
    """Extract the report theme from a `.pbix`: fonts, colors, background.

    Colors and fonts are taken from the **actually used** visual settings
    (`visualContainers[].config`), while background/text come from the report
    theme (`Report/Layout.theme` -> JSON in `Report/StaticResources/**`). Returns
    a dict in the `brand.check_brand_compliance` format:

        {"colors": {"visual_0": "#D32F2F", "accent": "#D32F2F", ...},
         "fonts": ["Verdana", "Segoe UI", ...],
         "background": "#FFFFFF",
         "text_color": "#252423",
         "has_logo": True,
         "theme_name": "CY23SU02"}

    If the theme is not found, returns an empty dict. The ``accent`` key is added if
    one of the used colors is close to the primary accent.
    """
    pbix = Path(pbix)
    with zipfile.ZipFile(pbix) as z:
        names = z.namelist()
        try:
            layout = decode_layout(z.read("Report/Layout"))
        except (KeyError, ValueError):
            return {}
        theme_name = layout.get("theme")
        cand = None
        if theme_name:
            cand = next(
                (
                    n
                    for n in names
                    if n.endswith(theme_name) and _THEME_MEMBER_RE.match(n)
                ),
                None,
            )
        if cand is None:
            cand = next((n for n in names if _THEME_MEMBER_RE.match(n)), None)
        theme = {}
        if cand is not None:
            try:
                theme = json.loads(z.read(cand).decode("utf-8"))
            except (KeyError, ValueError):
                theme = {}

    # --- colors/fonts actually used in the visuals ---
    used_colors: dict[str, int] = {}
    used_fonts: dict[str, int] = {}
    for sec in layout.get("sections", []):
        for vc in sec.get("visualContainers", []):
            cfg = vc.get("config", "")
            text = cfg if isinstance(cfg, str) else json.dumps(cfg, ensure_ascii=False)
            for m in _VIS_HEX_RE.finditer(text):
                h = "#" + m.group(1).upper()
                used_colors[h] = used_colors.get(h, 0) + 1
            for m in _VIS_FONT_RE.finditer(text):
                used_fonts[m.group(1)] = used_fonts.get(m.group(1), 0) + 1

    colors: dict[str, str] = {}
    for h in sorted(used_colors, key=lambda k: -used_colors[k]):
        colors[h] = h  # key = the HEX itself: violation messages stay readable
    # if there is a near-accent, record the 'accent' key with the canonical value
    if any(_is_near_brand_accent(h) for h in used_colors):
        colors["accent"] = "#D32F2F"

    fonts = list(used_fonts)
    # add theme fonts as fallback context (when visuals do not set them)
    for cls in (theme.get("textClasses") or {}).values():
        ff = cls.get("fontFace") if isinstance(cls, dict) else None
        if ff and ff not in fonts:
            fonts.append(ff)

    text_color = None
    for cls in (theme.get("textClasses") or {}).values():
        if isinstance(cls, dict) and cls.get("color"):
            text_color = cls["color"]
            break

    has_logo = any("logo" in n.lower() for n in names)
    return {
        "colors": colors,
        "fonts": fonts,
        "background": theme.get("background"),
        "text_color": text_color,
        "has_logo": has_logo,
        "theme_name": theme.get("name") or (str(theme_name) if theme_name else None),
    }


def verify_brand(
    pbix: Path, theme: dict | None = None, strict: bool = False
) -> list[CheckResult]:
    """Compare the report theme with the brand style guide (`brand.py`).

    Checks fonts (Brand Sans/Text), colors (palette, mandatory accent, at least 2
    primary-range colors) and background (validity + WCAG contrast). Every brand
    finding becomes a `CheckResult`; criticality is
    `critical=strict and level=="error"` (soft by default so brand preferences
    do not fail the build).

    Args:
        pbix: path to the `.pbix` (used if `theme` is not passed).
        theme: an already extracted theme (avoids re-reading the archive).
        strict: make level-`error` violations critical.
    """
    from agentic_bi.brand import check_brand_compliance  # local import: optional

    theme = theme if theme is not None else extract_report_theme(pbix)
    if not theme:
        return [
            _check(
                "brand: report theme found",
                False,
                "no registered report theme in the .pbix",
                critical=False,
            )
        ]
    report = check_brand_compliance(
        colors=theme.get("colors"),
        fonts=theme.get("fonts"),
        background=theme.get("background"),
        text_color=theme.get("text_color"),
        has_logo=bool(theme.get("has_logo")),
    )
    out: list[CheckResult] = []
    name = theme.get("theme_name") or "report"
    findings = report.get("findings", [])
    if not findings:
        out.append(_check(f"brand: theme '{name}' complies", True, critical=False))
        return out
    for f in findings:
        critical = bool(strict and f.get("level") == "error")
        out.append(
            _check(
                f"brand: {f.get('rule_id')}",
                False,
                f"[{f.get('level')}] {f.get('message')}",
                critical=critical,
            )
        )
    return out
