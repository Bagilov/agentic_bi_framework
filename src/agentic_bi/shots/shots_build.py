"""Build a figure set from a declarative plan: render, then manifest.

This is the orchestrator: it walks the plan, dispatches each figure to the right
renderer (`shots_terminal` for captured console text, `shots_render` for HTML),
hashes every output and writes a manifest. Failures and skips are collected, not
fatal per figure, so one broken figure or a missing browser never kills the run:
the manifest records what happened and the rest still builds.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from agentic_bi.shots.shots_manifest import (
    STATUS_FAILED,
    STATUS_OK,
    STATUS_SKIPPED,
    RenderRecord,
    ShotManifest,
    sha256_file,
)
from agentic_bi.shots.shots_records import (
    discard_stale,
    portable,
    record_unbuilt,
    source_label,
)
from agentic_bi.shots.shots_render import (
    BrowserNotFound,
    RenderError,
    render_html_file,
    render_html_string,
    window_height,
)
from agentic_bi.shots.shots_store import write_manifest
from agentic_bi.shots.shots_terminal import build_terminal_html
from agentic_bi.shots.shots_types import KIND_TERMINAL, FigureSpec, ShotPlan

logger = logging.getLogger(__name__)

# One reason for every figure when the only external tool is absent, so the
# stderr line names the fix once instead of per figure.
NO_BROWSER = (
    "no Chromium browser found (install Chrome/Chromium, set GUIDE_CHROME "
    "or pass --browser)"
)


@dataclass
class BuildResult:
    """The outcome of one figure-set build.

    Attributes:
        manifest: what was written (every requested figure, with its status).
        out_dir: where the PNGs and the manifest were written.
        failures: `(figure name, error message)` for every figure that failed.
        skipped: `(figure name, reason)` for figures not attempted, e.g. because
            no browser is installed. A skip is not a crash: the manifest records
            it, the rest of the set still builds, and the CLI explains it.
    """

    manifest: ShotManifest
    out_dir: Path
    failures: list[tuple[str, str]] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)

    @property
    def built(self) -> int:
        """How many figures were actually produced."""
        return sum(1 for figure in self.manifest.figures if figure.built)

    @property
    def ok(self) -> bool:
        """Whether every requested figure was produced."""
        return not self.failures and not self.skipped


def _render_one(
    spec: FigureSpec, out_dir: Path, browser: str | None
) -> tuple[Path, int, int]:
    """Render one figure and return `(png, viewport_width, viewport_height)`.

    For a terminal figure the card sizes itself (wrapping and height come from
    the text), so the viewport is set to the exact card size and `width`/`height`
    in the spec are ignored — otherwise the PNG would be a full window with the
    card floating in it. For an HTML figure the spec's viewport is used as given,
    raised to the browser's minimum window height like every other render.

    Raises:
        RenderError: when a terminal source is empty or is not UTF-8 text, so the
            reason is reported per figure instead of a decoder traceback.
    """
    out_png = out_dir / spec.output_name()
    source = Path(spec.source)
    if spec.kind == KIND_TERMINAL:
        try:
            text = source.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise RenderError(f"{source.name}: not valid UTF-8 text") from exc
        if not text.strip():
            raise RenderError(f"{source.name}: empty source, no console output")
        html_text, card_w, card_h = build_terminal_html(
            text,
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
        plan_path: the plan file the run came from (only its name is recorded).
        strict: when true, a figure whose source is missing is a failure; when
            false it is left out of the manifest with a warning (the caller
            accepts a smaller set, and `verify --plan` still reports the gap).

    Returns:
        The `BuildResult`; `failures` and `skipped` list any figure that did not
        render, and `manifest` records the status of every requested figure.
    """
    from agentic_bi.board_guide.guide_capture import find_browser_executable

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    browser = find_browser_executable(browser_executable)

    records: list[RenderRecord] = []
    failures: list[tuple[str, str]] = []
    skipped: list[tuple[str, str]] = []

    if not browser:
        # The one external tool is missing: every figure is skipped for the same
        # reason, and none of them waits on a browser timeout.
        for spec in plan.figures:
            skipped.append((spec.name, NO_BROWSER))
            discard_stale(out, spec)
            records.append(
                record_unbuilt(spec, plan.base_dir, STATUS_SKIPPED, NO_BROWSER)
            )
        manifest = write_manifest(
            records, out / manifest_name, browser="", plan=plan_path, root=out
        )
        return BuildResult(
            manifest=manifest, out_dir=out, failures=failures, skipped=skipped
        )

    for spec in plan.figures:
        if not Path(spec.source).exists():
            message = f"source not found: {source_label(spec, plan.base_dir)}"
            discard_stale(out, spec)
            if not strict:
                logger.warning("figure '%s': %s", spec.name, message)
                continue
            failures.append((spec.name, message))
            records.append(record_unbuilt(spec, plan.base_dir, STATUS_FAILED, message))
            continue
        try:
            png, view_w, view_h = _render_one(spec, out, browser_executable)
        except BrowserNotFound as exc:
            # The browser disappeared mid-run: that is a missing tool, not a
            # failure of this figure, and the remaining figures will see it too.
            reason = portable(str(exc), out, plan.base_dir)
            skipped.append((spec.name, reason))
            discard_stale(out, spec)
            records.append(record_unbuilt(spec, plan.base_dir, STATUS_SKIPPED, reason))
            logger.warning("figure '%s' skipped: %s", spec.name, reason)
            continue
        except Exception as exc:  # noqa: BLE001 - one figure must not kill the run
            reason = portable(str(exc), out, plan.base_dir)
            failures.append((spec.name, reason))
            discard_stale(out, spec)
            records.append(record_unbuilt(spec, plan.base_dir, STATUS_FAILED, reason))
            logger.error("figure '%s' failed: %s", spec.name, reason)
            continue
        records.append(
            RenderRecord(
                name=spec.name,
                kind=spec.kind,
                source=source_label(spec, plan.base_dir),
                png=spec.output_name(),
                width=view_w,
                height=view_h,
                scale=spec.scale,
                sha256=sha256_file(png),
                bytes=png.stat().st_size,
                status=STATUS_OK,
            )
        )
        logger.info("figure '%s' -> %s (%dx%d)", spec.name, png.name, view_w, view_h)

    manifest = write_manifest(
        records, out / manifest_name, browser=browser, plan=plan_path, root=out
    )
    return BuildResult(
        manifest=manifest, out_dir=out, failures=failures, skipped=skipped
    )


__all__ = ["BuildResult", "NO_BROWSER", "build_shots"]
