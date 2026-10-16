"""Brand palette: color specifications and the primary/additional ranges.

This module is **organization-agnostic**: the palette below is a set of neutral
placeholders. Replace them with your own design tokens to enforce a real style.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ColorSpec:
    """A single brand color."""

    name: str
    hex: str
    role: str = ""
    ref: str = ""  # external reference (e.g. a swatch code), optional
    cmyk: str = ""
    rgb: tuple[int, int, int] | None = None
    mandatory: bool = False
    approx: bool = False  # True = RGB/HEX not authoritative, approximated

    def __post_init__(self) -> None:
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", self.hex):
            raise ValueError(f"bad hex: {self.hex!r}")
        if self.rgb is None:
            object.__setattr__(
                self,
                "rgb",
                (
                    int(self.hex[1:3], 16),
                    int(self.hex[3:5], 16),
                    int(self.hex[5:7], 16),
                ),
            )


# Primary range ("Primary colors").
# NOTE: neutral placeholders - replace with your own design tokens.
PALETTE_PRIMARY: tuple[ColorSpec, ...] = (
    ColorSpec(
        name="Accent Red",
        hex="#D32F2F",
        role="primary accent - MANDATORY for use",
        ref="",
        cmyk="",
        rgb=(211, 47, 47),
        mandatory=True,
    ),
    ColorSpec(
        name="Black",
        hex="#000000",
        role="black",
        ref="",
        cmyk="C-0 M-0 Y-0 K-100",
        rgb=(0, 0, 0),
    ),
    ColorSpec(
        name="Grey Dark",
        hex="#4A4A4A",
        role="grey (dark)",
        ref="",
        cmyk="",
        rgb=(74, 74, 74),
    ),
    ColorSpec(
        name="Grey Light",
        hex="#D9D9D9",
        role="grey (light)",
        ref="",
        cmyk="",
        rgb=(217, 217, 217),
    ),
)

# Additional palette ("Additional colors").
# RGB/HEX may be approximated; flagged approx=True.
PALETTE_ADDITIONAL: tuple[ColorSpec, ...] = (
    ColorSpec(
        name="Violet",
        hex="#6020C0",
        role="sub-brands / complement to the primary range",
        ref="",
        approx=True,
    ),
    ColorSpec(
        name="Silver",
        hex="#A7A9AB",
        role="sub-brands / complement to the primary range (special effect)",
        ref="",
        approx=True,
    ),
    ColorSpec(
        name="Teal",
        hex="#00E0E0",
        role="sub-brands / complement to the primary range",
        ref="",
        approx=True,
    ),
)

_ALL_HEX: dict[str, ColorSpec] = {
    c.hex.lower(): c for c in (*PALETTE_PRIMARY, *PALETTE_ADDITIONAL)
}
_ALL_BY_NAME: dict[str, ColorSpec] = {
    c.name: c for c in (*PALETTE_PRIMARY, *PALETTE_ADDITIONAL)
}


__all__ = [
    "ColorSpec",
    "PALETTE_PRIMARY",
    "PALETTE_ADDITIONAL",
]
