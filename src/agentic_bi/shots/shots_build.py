"""Build a figure set from a declarative plan: render, then manifest.

This is the orchestrator: it walks the plan, dispatches each figure to the right
renderer (`shots_terminal` for captured console text, `shots_render` for HTML),
hashes every output and writes a manifest. Failures are collected, not fatal
per figure, so a broken figure is reported and the rest still build.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from agentic_bi.shots.shots_manifest import (
    RenderRecord,
    ShotManifest,
    sha256_file,
    write_manifest,
)
from agentic_bi.shots.shots_render import (
    render_html_file,
    render_html_string,
    window_height,
)
from agentic_bi.shots.shots_terminal import build_terminal_html
from agentic_bi.shots.shots_types import KIND_TERMINAL, FigureSpec, ShotPlan

logger = logging.getLogger(__name__)


@dataclass
class BuildResult:
    """The outcome of one figure-set build.

    Attributes:
        manifest: what was written (only the figures that rendered).
        out_dir: where the PNGs were written.
        failures: `(figure name, error message)` for every figure that failed.
    """

    manifest: ShotManifest
    out_dir: Path
    failures: list[tuple[str, str]]

    @property
    def ok(self) -> bool:
        """Whether every figure rendered."""
        return not self.failures


def _render_one(
    spec: FigureSpec, out_dir: Path, browser: str | None
) -> tuple[Path, int, int]:
    """Render one figure and return `(png, viewport_width, viewport_height)`.

    For a terminal figure the card sizes itself (wrapping and height come from
    the text), so the viewport is set to the exact card size and `width`/`height`
    in the spec are ignored — otherwise the PNG would be a full window with the
    card floating in it. For an HTML figure the spec's viewport is used as given,
    raised to the browser's minimum window height like every other render.
    """
    out_png = out_dir / spec.output_name()
    source = Path(spec.source)
    if spec.kind == KIND_TERMINAL:
        html_text, card_w, card_h = build_terminal_html(
            source.read_text(encoding="utf-8"),
            title=spec.title or spec.name,
            columns=spec.columns,
            point=spec.point,
        )
        render_html_string(
            html_text,
            out_png,
            width=card_w,
            height=card_h,
            scale=spec.scale,
            settle_ms=spec.settle_ms,
            browser_executable=browser,
        )
        return out_png, card_w, card_h
    view_h = window_height(spec.height)
    render_html_file(
        source,
        out_png,
        width=spec.width,
        height=view_h,
        scale=spec.scale,
        settle_ms=spec.settle_ms,
        browser_executable=browser,
    )
    return out_png, spec.width, view_h


def build_shots(
    plan: ShotPlan,
    out_dir: str | Path,
    *,
    browser_executable: str | None = None,
    manifest_name: str = "manifest.json",
    plan_path: str = "",
    strict: bool = True,
) -> BuildResult:
    """Render every figure in `plan` and write a manifest.

    Args:
        plan: the figures to render.
        out_dir: the output directory (PNGs + the manifest).
        browser_executable: an explicit Chromium path.
        manifest_name: the manifest file name.
        plan_path: the plan file the run came from (recorded in the manifest).
        strict: when true, a figure whose source is missing is a failure; when
            false it is skipped with a warning.

    Returns:
        The `BuildResult`; its `failures` lists any figure that did not render.
    """
    from agentic_bi.board_guide.guide_capture import find_browser_executable

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    browser = find_browser_executable(browser_executable) or ""

    records: list[RenderRecord] = []
    failures: list[tuple[str, str]] = []
    for spec in plan.figures:
        if not Path(spec.source).exists():
            message = f"source not found: {spec.source}"
            if strict:
                failures.append((spec.name, message))
                continue
            logger.warning("figure '%s': %s", spec.name, message)
            continue
        try:
            png, view_w, view_h = _render_one(spec, out, browser_executable)
        except Exception as exc:  # noqa: BLE001 - one figure must not kill the run
            failures.append((spec.name, str(exc)))
            logger.error("figure '%s' failed: %s", spec.name, exc)
            continue
        records.append(
            RenderRecord(
                name=spec.name,
                kind=spec.kind,
                source=Path(spec.source).name,
                png=str(png),
                width=view_w,
                height=view_h,
                scale=spec.scale,
                sha256=sha256_file(png),
                bytes=png.stat().st_size,
            )
        )
        logger.info("figure '%s' -> %s (%dx%d)", spec.name, png.name, view_w, view_h)

    manifest = write_manifest(
        records, out / manifest_name, browser=browser, plan=plan_path
    )
    return BuildResult(manifest=manifest, out_dir=out, failures=failures)


__all__ = ["BuildResult", "build_shots"]
