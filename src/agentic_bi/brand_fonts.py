"""Brand fonts: family specifications, weights and the local font library.

This module is **organization-agnostic**: the families below are neutral
placeholders. Replace them with your own design tokens to enforce a real style.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class FontSpec:
    """A brand font and its roles."""

    family: str
    app: str
    embedded: str = ""  # family name as embedded in a document (e.g. get_fonts)


FONTS: tuple[FontSpec, ...] = (
    FontSpec("Brand Sans",
             "display, level 1-2 headings, short communications; "
             "geometric grotesque",
             embedded="BrandSans"),
    FontSpec("Brand Sans Text",
             "body text at large volumes (utilitarian), sub-brands "
             "(Brand Sans Text Medium low case, same size as in the logo)",
             embedded="BrandSansText"),
)

# Brand weights: Regular/Light (+ Italic) - text; Medium - emphasis and level
# 1-2 headings; Bold; Black - display.
BRAND_WEIGHTS = ("Light", "Regular", "Medium", "Bold", "Black")
BRAND_ITALIC = tuple(f"{w} Italic" for w in BRAND_WEIGHTS)
# Confirmed embedded families (visible via get_fonts).
EMBEDDED_BRAND_FONTS = ("Brand Sans Light", "Brand Sans Regular", "Brand Sans Medium",
                        "Brand Sans Bold", "Brand Sans Black", "Brand Sans Thin",
                        "Brand Sans Text Light", "Brand Sans Text Regular",
                        "Brand Sans Text Medium", "Brand Sans Text Bold",
                        "Brand Sans Text Black")

# Local font library in the repository (assets/fonts).
FONT_DIR = "assets/fonts/Brand Sans"
FONT_FILES: dict[str, str] = {
    **{f"Brand Sans Thin{w}": f"Brand Sans-Thin{w}.otf"
       for w in ("", " Italic")},
    **{f"Brand Sans Light{w}": f"Brand Sans-Light{w}.otf"
       for w in ("", " Italic")},
    **{f"Brand Sans Regular{w}": f"Brand Sans-Regular{w}.otf"
       for w in ("", " Italic")},
    **{f"Brand Sans Medium{w}": f"Brand Sans-Medium{w}.otf"
       for w in ("", " Italic")},
    **{f"Brand Sans Bold{w}": f"Brand Sans-Bold{w}.otf"
       for w in ("", " Italic")},
    **{f"Brand Sans Black{w}": f"Brand Sans-Black{w}.otf"
       for w in ("", " Italic")},
}


def font_catalog() -> list[dict]:
    """The catalog of brand fonts."""
    return [asdict(f) for f in FONTS]


def font_files(repo_root: str | None = None) -> dict[str, str]:
    """Map font name -> file path in the local library.

    Args:
        repo_root: repository root; defaults to the current working directory.
    """
    from pathlib import Path
    base = Path(repo_root) if repo_root else Path.cwd()
    return {name: str(base / FONT_DIR / fname)
            for name, fname in FONT_FILES.items()}


__all__ = [
    "FontSpec",
    "FONTS",
    "BRAND_WEIGHTS",
    "BRAND_ITALIC",
    "EMBEDDED_BRAND_FONTS",
    "FONT_DIR",
    "FONT_FILES",
    "font_catalog",
    "font_files",
]