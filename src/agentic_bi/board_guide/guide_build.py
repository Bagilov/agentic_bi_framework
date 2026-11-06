"""Write a board guide: resolve each page's screenshot, then render the HTML.

`build_guide` is the orchestrator of the visual half: it maps every page to its
`page_<stem>.png`, writes one annotated document per usable page and an index
that explains what was skipped and why. The screenshot itself is an input (a
Desktop capture, a CI artifact, a manual set or `guide_capture`), never produced
here.

Public API:
    PageSource       - one page plus its image (or the reason it is skipped)
    resolve_pages(geometry, screenshots, ...) -> list[PageSource]
    build_guide(geometry, out_dir, ...) -> list[Path]
"""

from __future__ import annotations

import math
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from agentic_bi.board_guide.guide_geometry import GuideGeometry, GuidePage
from agentic_bi.board_guide.guide_hotspots import (
    DEFAULT_CANVAS_HEIGHT,
    DEFAULT_CANVAS_WIDTH,
)
from agentic_bi.board_guide.guide_names import unique_stems
from agentic_bi.board_guide.guide_png import png_size
from agentic_bi.board_guide.guide_render import render_index_html, render_page_html

_NO_SHOTS = "скриншот не задан (нет --shots и --src-prefix)"
_ASPECT_TOLERANCE = 0.01


@dataclass(frozen=True)
class PageSource:
    """One page, the `src` of its screenshot, and why it may be unavailable.

    `skip` is empty exactly when the page is usable, so a caller can branch on
    one field instead of re-checking the filesystem. `warning` is a non-fatal
    problem with a usable screenshot (an aspect mismatch) that belongs in the
    index next to the page.
    """

    page: GuidePage
    stem: str
    image: str = ""
    skip: str = ""
    warning: str = ""

    @property
    def ready(self) -> bool:
        """Whether the page has a usable screenshot to annotate."""
        return not self.skip


def _as_src(candidate: Path, out_dir: Path | None) -> str:
    """The `<img src>` for a found PNG: relative to the HTML, forward slashes."""
    if out_dir is None:
        return str(candidate)
    try:
        return Path(os.path.relpath(candidate, out_dir)).as_posix()
    except ValueError:  # different drives (Windows): keep the absolute path
        return str(candidate)


def _resolve_image(stem: str, screenshots: Path | str | None) -> tuple[str, str]:
    """`(image, reason)` for a page stem: a found PNG or a human reason."""
    if screenshots is None:
        return "", _NO_SHOTS
    if isinstance(screenshots, str) and "://" in screenshots:
        return f"{screenshots.rstrip('/')}/page_{stem}.png", ""
    candidate = Path(screenshots) / f"page_{stem}.png"
    if not candidate.is_file():
        return "", f"нет файла {candidate.name}"
    if candidate.stat().st_size == 0:
        return "", f"пустой файл {candidate.name} (0 байт)"
    if png_size(candidate) is None:
        return "", f"файл {candidate.name} не PNG (нет сигнатуры/IHDR)"
    return str(candidate), ""


def _canvas_side(value: float, default: float) -> float:
    """A finite, positive canvas side for the aspect comparison."""
    return value if math.isfinite(value) and value > 0 else default


def _aspect_warning(
    page: GuidePage,
    width: int,
    height: int,
    area: tuple[float, float] | None,
) -> str:
    """Non-fatal notes for a screenshot that would shift every hotspot.

    Hotspots are canvas percentages of the image container, so an image whose
    aspect ratio differs from the page canvas (a crop, an `area` clip, portal
    letterboxing) moves them silently. The tolerance is 1% of the canvas ratio,
    well below the smallest real difference and above PNG/pixel rounding.
    """
    canvas_w = _canvas_side(page.width, DEFAULT_CANVAS_WIDTH)
    canvas_h = _canvas_side(page.height, DEFAULT_CANVAS_HEIGHT)
    target = canvas_w / canvas_h
    actual = width / height
    notes: list[str] = []
    if abs(actual - target) / target > _ASPECT_TOLERANCE:
        notes.append(
            f"аспект скриншота {width}×{height} ({actual:.3f}) не совпадает с "
            f"канвасом {canvas_w:.0f}×{canvas_h:.0f} ({target:.3f}) больше чем "
            "на 1%: hotspots сместятся"
        )
    if area is not None and area[0] > 0 and area[1] > 0:
        area_ratio = area[0] / area[1]
        if abs(area_ratio - target) / target > _ASPECT_TOLERANCE:
            notes.append(
                f"область захвата {area[0]:.0f}×{area[1]:.0f} ({area_ratio:.3f}) "
                "не совпадает с канвасом больше чем на 1%: сетка гайда и "
                "скриншот расходятся"
            )
    return "; ".join(notes)


def resolve_pages(
    geometry: GuideGeometry,
    screenshots: str | Path | None = None,
    *,
    src_prefix: str | None = None,
    out_dir: str | Path | None = None,
    capture_areas: Mapping[str, tuple[float, float]] | None = None,
) -> list[PageSource]:
    """Pair every page with its screenshot, or with the reason it has none.

    Stems come from the **full** page list (`unique_stems`), exactly as the
    capture tool names the files, so `page_<stem>.png` and `guide_<stem>.html`
    cannot drift apart. A local PNG is checked for the PNG signature and for an
    aspect ratio matching the canvas; `capture_areas` (stem -> rendered area
    size) additionally checks the area the capture was clipped to.
    """
    out = Path(out_dir) if out_dir is not None else None
    resolved: list[PageSource] = []
    for page, stem in zip(geometry.pages, unique_stems(geometry.pages), strict=True):
        if src_prefix:
            image = f"{src_prefix.rstrip('/')}/page_{stem}.png"
            resolved.append(PageSource(page, stem, image))
            continue
        image, reason = _resolve_image(stem, screenshots)
        if not image:
            resolved.append(PageSource(page, stem, "", reason))
            continue
        dims = png_size(image)
        warning = (
            _aspect_warning(page, dims[0], dims[1], (capture_areas or {}).get(stem))
            if dims is not None
            else ""
        )
        resolved.append(PageSource(page, stem, _as_src(Path(image), out), "", warning))
    return resolved


def build_guide(
    geometry: GuideGeometry,
    out_dir: str | Path,
    screenshots: str | Path | None = None,
    *,
    src_prefix: str | None = None,
    title: str = "Board guide",
    on_skip: Callable[[str, str], None] | None = None,
    capture_areas: Mapping[str, tuple[float, float]] | None = None,
) -> list[Path]:
    """Write the index and one HTML per page that has a screenshot.

    Args:
        geometry: the extracted page/visual geometry.
        out_dir: the output directory (HTML is written here).
        screenshots: a local directory to discover `page_<stem>.png` in. Pages
            without a matching, non-empty screenshot are skipped (and listed in
            the index), so a partial capture still produces a usable guide.
        src_prefix: overrides the `<img src>` prefix (e.g. an `http://` base or
            a relative directory); when given, every page is emitted.
        title: the index title.
        on_skip: called with `(page name, reason)` for every skipped page, so
            the CLI can report it without re-reading the filesystem.
        capture_areas: `{stem: (width, height)}` of the rendered page area each
            screenshot was clipped to; a ratio that differs from the canvas gets
            a warning in the index.

    Returns:
        The list of written paths (page files first, then the index).
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    sources = resolve_pages(
        geometry,
        screenshots,
        src_prefix=src_prefix,
        out_dir=out,
        capture_areas=capture_areas,
    )
    rows: list[tuple[str, str, int]] = []
    skipped: list[tuple[str, str]] = []
    warnings: list[tuple[str, str]] = []
    saved: list[Path] = []
    for source in sources:
        if not source.ready:
            skipped.append((source.page.name, source.skip))
            if on_skip is not None:
                on_skip(source.page.name, source.skip)
            continue
        if source.warning:
            warnings.append((source.page.name, source.warning))
        page_file = out / f"guide_{source.stem}.html"
        page_file.write_text(
            render_page_html(source.page, source.image, title=source.page.name),
            encoding="utf-8",
        )
        saved.append(page_file)
        rows.append((source.page.name, page_file.name, len(source.page.visuals)))

    index = out / "index.html"
    index.write_text(
        render_index_html(
            rows,
            geometry.source,
            title=title,
            skipped=skipped,
            warnings=warnings,
        ),
        encoding="utf-8",
    )
    saved.append(index)
    return saved


__all__ = ["PageSource", "build_guide", "resolve_pages"]
