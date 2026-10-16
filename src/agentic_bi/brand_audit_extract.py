"""Observation extraction from a `.pptx` presentation (colors/fonts).

Reuses python-pptx (optional). Resolves both direct RGB colors and theme
(scheme) colors via the presentation theme, traverses groups and tables, and
emits flat observations with their location.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from agentic_bi.brand_config import BrandConfig, normalize_hex

logger = logging.getLogger(__name__)

_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_THEME_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme"

# Theme scheme slots (scheme tag -> key)
_SCHEME_TAGS = {
    "dk1": "dk1",
    "lt1": "lt1",
    "dk2": "dk2",
    "lt2": "lt2",
    "accent1": "accent1",
    "accent2": "accent2",
    "accent3": "accent3",
    "accent4": "accent4",
    "accent5": "accent5",
    "accent6": "accent6",
    "hlink": "hlink",
    "folHlink": "folHlink",
}

# MSO_THEME_COLOR semantic names -> scheme slot
_THEME_SLOT = {
    "DARK_1": "dk1",
    "LIGHT_1": "lt1",
    "DARK_2": "dk2",
    "LIGHT_2": "lt2",
    "TEXT_1": "dk1",
    "BACKGROUND_1": "lt1",
    "TEXT_2": "dk2",
    "BACKGROUND_2": "lt2",
    "ACCENT_1": "accent1",
    "ACCENT_2": "accent2",
    "ACCENT_3": "accent3",
    "ACCENT_4": "accent4",
    "ACCENT_5": "accent5",
    "ACCENT_6": "accent6",
    "HYPERLINK": "hlink",
    "FOLLOWED_HYPERLINK": "folHlink",
}


class ThemeResolver:
    """Resolve a presentation's theme (scheme) colors to HEX.

    Reads the master's ``ppt/theme/theme1.xml``: the ``clrScheme`` (dk1/lt1/
    accent1-6/hlink/...). Needed because most shapes use theme colors rather than
    direct RGB.
    """

    def __init__(self) -> None:
        self.slots: dict[str, str] = {}

    @classmethod
    def from_presentation(cls, prs) -> ThemeResolver:
        tr = cls()
        for master in prs.slide_masters:
            try:
                part = master.part.part_related_by(_THEME_REL)
                tr._parse(part.blob)
                if tr.slots:
                    return tr
            except Exception as exc:  # noqa: BLE001
                logger.debug("theme parse failed: %s", exc)
        return tr

    def _parse(self, blob: bytes) -> None:
        from lxml import etree

        try:
            root = etree.fromstring(blob)
        except Exception as exc:  # noqa: BLE001
            logger.debug("theme xml invalid: %s", exc)
            return
        scheme = root.find(f".//{{{_A_NS}}}clrScheme")
        if scheme is None:
            return
        for child in scheme:
            tag = etree.QName(child).localname
            key = _SCHEME_TAGS.get(tag)
            if not key:
                continue
            srgb = child.find(f"{{{_A_NS}}}srgbClr")
            sysc = child.find(f"{{{_A_NS}}}sysClr")
            val = ""
            if srgb is not None:
                val = srgb.get("val", "")
            elif sysc is not None:
                val = sysc.get("lastClr", "")
            if val:
                self.slots[key] = normalize_hex(val)

    def resolve(self, theme_color) -> str:
        """MSO_THEME_COLOR -> HEX ('' if it cannot be resolved)."""
        if theme_color is None:
            return ""
        slot = _THEME_SLOT.get(str(theme_color).split(".")[-1].split(" ")[0])
        if not slot:
            # sometimes it arrives as 'ACCENT_1 (5)'
            for name, s in _THEME_SLOT.items():
                if name in str(theme_color):
                    slot = s
                    break
        return self.slots.get(slot, "") if slot else ""

    def as_dict(self) -> dict:
        return dict(self.slots)


@dataclass
class Observation:
    """An observation: a color/font with a location and context."""

    kind: str  # text_color|fill|line|background|font|font_weight|font_size
    value: str
    location: str
    context: str = ""
    from_theme: bool = False


def color_hex(color_format, theme: ThemeResolver) -> tuple[str, bool]:
    """HEX + a 'from theme' flag from a ColorFormat ('' if not set)."""
    try:
        if color_format is None or color_format.type is None:
            return "", False
        name = str(color_format.type)
        if "RGB" in name:
            return normalize_hex(str(color_format.rgb)), False
        if "SCHEME" in name:
            h = theme.resolve(color_format.theme_color)
            return h, bool(h)
    except Exception as exc:  # noqa: BLE001 - theme/inherited color
        logger.debug("color resolve failed: %s", exc)
    return "", False


def iter_pptx_observations(
    prs, cfg: BrandConfig, theme: ThemeResolver
) -> list[Observation]:
    """Collect all observations from the presentation (including groups and tables)."""
    obs: list[Observation] = []
    for si, slide in enumerate(prs.slides, start=1):
        page = f"slide {si}"
        if cfg.audit.get("check_background", True):
            bg = _slide_background(slide, theme)
            if bg:
                obs.append(Observation("background", bg, f"{page} / background"))
        for shape in slide.shapes:
            obs.extend(_shape_observations(shape, page, cfg, theme))
    return obs


def _slide_background(slide, theme: ThemeResolver) -> str:
    try:
        fill = slide.background.fill
        if fill.type is not None and "SOLID" in str(fill.type):
            h, _ = color_hex(fill.fore_color, theme)
            return h
    except Exception as exc:  # noqa: BLE001
        logger.debug("slide background unavailable: %s", exc)
    return ""


def _is_placeholder(shape) -> bool:
    try:
        return bool(shape.is_placeholder)
    except Exception:  # noqa: BLE001
        return False


def _shape_observations(
    shape, page: str, cfg: BrandConfig, theme: ThemeResolver
) -> list[Observation]:
    """Observations for one shape (recursively into groups)."""
    obs: list[Observation] = []
    name = shape.name or str(shape.shape_type)
    loc = f"{page} / shape '{name}'"

    # group shapes: traverse nested ones
    try:
        if shape.shape_type is not None and "GROUP" in str(shape.shape_type):
            for child in shape.shapes:
                obs.extend(_shape_observations(child, loc, cfg, theme))
            return obs
    except Exception as exc:  # noqa: BLE001
        logger.debug("group traversal failed at %s: %s", loc, exc)

    # layout placeholders: do not check fill/line (inherited from the master)
    skip_style = _is_placeholder(shape) and cfg.audit.get(
        "ignore_layout_placeholders", True
    )

    if not skip_style and cfg.audit.get("check_fill_color", True):
        obs.extend(_paint_observations(shape, "fill", loc, theme))
    if not skip_style and cfg.audit.get("check_line_color", True):
        obs.extend(_paint_observations(shape, "line", loc, theme))

    if cfg.audit.get("check_text_color", True) or cfg.rules.get("check_fonts", True):
        if getattr(shape, "has_text_frame", False):
            obs.extend(_textframe_observations(shape.text_frame, loc, cfg, theme))
        if getattr(shape, "has_table", False):
            for ri, row in enumerate(shape.table.rows):
                for ci, cell in enumerate(row.cells):
                    obs.extend(
                        _textframe_observations(
                            cell.text_frame, f"{loc} / table[{ri}][{ci}]", cfg, theme
                        )
                    )
    return obs


def _paint_observations(
    shape, kind: str, loc: str, theme: ThemeResolver
) -> list[Observation]:
    try:
        if kind == "fill":
            fill = shape.fill
            if fill.type is not None and "SOLID" in str(fill.type):
                h, t = color_hex(fill.fore_color, theme)
                if h:
                    return [Observation("fill", h, f"{loc} / fill", from_theme=t)]
        else:
            h, t = color_hex(shape.line.color, theme)
            if h:
                return [Observation("line", h, f"{loc} / line", from_theme=t)]
    except Exception as exc:  # noqa: BLE001 - a shape may have no fill/line
        logger.debug("%s color unavailable at %s: %s", kind, loc, exc)
    return []


def _textframe_observations(
    tf, loc: str, cfg: BrandConfig, theme: ThemeResolver
) -> list[Observation]:
    obs: list[Observation] = []
    if tf is None:
        return obs
    for pi, para in enumerate(tf.paragraphs):
        for ri, run in enumerate(para.runs):
            rloc = f"{loc} / p{pi}r{ri}"
            if cfg.audit.get("check_text_color", True):
                h, t = color_hex(run.font.color, theme)
                if h:
                    obs.append(
                        Observation("text_color", h, f"{rloc} / text", from_theme=t)
                    )
            if cfg.rules.get("check_fonts", True):
                fname = run.font.name
                if fname:
                    obs.append(Observation("font", fname, f"{rloc} / font"))
                    obs.append(Observation("font_weight", fname, f"{rloc} / weight"))
                    if cfg.audit.get("check_font_size", False) and run.font.size:
                        size = round(run.font.size.pt, 1)
                        obs.append(
                            Observation("font_size", str(size), f"{rloc} / size")
                        )
    return obs


__all__ = [
    "ThemeResolver",
    "Observation",
    "color_hex",
    "iter_pptx_observations",
]
