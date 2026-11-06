"""Typed shot plan: declarative figure specs for the screenshot pipeline.

A *shot* is one PNG produced deterministically from a text or HTML source by a
headless Chromium. The plan is the single source of truth for a figure set: it
names every figure, points at its source, and fixes the exact render parameters.
Nothing about a figure lives in an ad-hoc script, so a shot can be reproduced —
and its bytes verified by hash — without re-reading whatever produced it.

Two kinds are supported:

* ``html`` — the source is an HTML file (a report clone, a board guide page, a
  hand-written card) rendered as-is;
* ``terminal`` — the source is plain text (a captured CLI run) wrapped into a
  terminal card by `agentic_bi.shots.shots_terminal`.

Public API:
    KIND_HTML, KIND_TERMINAL, KINDS, MIN_WINDOW_HEIGHT
    FigureSpec        - one figure: identity, source, render parameters
    ShotPlan          - an ordered figure set + its base directory
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from agentic_bi.shots.shots_validation import (
    FIGURE_KEYS,
    check_name,
    check_output_name,
    figure_label,
    optional_str,
    parse_plan,
    plan_base,
    positive_int,
    positive_scale,
    require_str,
)

KIND_HTML = "html"
KIND_TERMINAL = "terminal"
KINDS = frozenset({KIND_HTML, KIND_TERMINAL})

# Headless Chromium will not lay out a window shorter than this (measured on the
# shipped build: see `docs/SHOTS.md` §7). Below the floor the *layout viewport*
# is clamped while the saved PNG still has the requested height, so the bottom
# of the page is cut off with no error. The renderer raises every window to this
# floor; a card that wants to be shorter is padded with its own background.
MIN_WINDOW_HEIGHT = 144

_DEFAULT_WIDTH = 1000
_DEFAULT_HEIGHT = 640
_DEFAULT_SCALE = 2.0
_DEFAULT_COLUMNS = 88
_DEFAULT_POINT = 13
_DEFAULT_SETTLE_MS = 250


@dataclass(frozen=True)
class FigureSpec:
    """One figure to render.

    Attributes:
        name: the logical id; also the default output stem.
        kind: ``html`` or ``terminal``.
        source: the source file, relative to the plan's base directory.
        width: viewport width in CSS pixels.
        height: viewport height in CSS pixels.
        scale: device scale factor (`--force-device-scale-factor`).
        title: the terminal card's title-bar label; ignored for `html` figures,
            whose heading belongs to the source document itself.
        columns: terminal wrap width, an upper bound of 96.
        point: terminal font point size.
        out: explicit output file name; defaults to ``<name>.png``.
        settle_ms: the browser's virtual time budget in milliseconds.
    """

    name: str
    kind: str
    source: str
    width: int = _DEFAULT_WIDTH
    height: int = _DEFAULT_HEIGHT
    scale: float = _DEFAULT_SCALE
    title: str = ""
    columns: int = _DEFAULT_COLUMNS
    point: int = _DEFAULT_POINT
    out: str = ""
    settle_ms: int = _DEFAULT_SETTLE_MS

    def output_name(self) -> str:
        """The PNG file name for this figure (a bare name, never a path)."""
        return self.out or f"{self.name}.png"

    def with_source_dir(self, base: Path) -> FigureSpec:
        """Return a copy whose `source` is resolved against `base`."""
        return replace(self, source=str((base / self.source).resolve()))

    def to_dict(self) -> dict[str, Any]:
        """A JSON-ready view of the spec (round-trips `from_dict`)."""
        return {
            "name": self.name,
            "kind": self.kind,
            "source": self.source,
            "width": self.width,
            "height": self.height,
            "scale": self.scale,
            "title": self.title,
            "columns": self.columns,
            "point": self.point,
            "out": self.out,
            "settle_ms": self.settle_ms,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, where: str = "figure") -> FigureSpec:
        """Validate one spec mapping.

        Args:
            data: the figure mapping (defaults already merged in).
            where: the figure's label for error messages; a plan passes
                `figure 'a'` or `figures[2]` so a multi-figure plan says which
                figure is broken instead of a bare `figure:`.

        Raises:
            ValueError: when `name`/`kind`/`source` are missing or a value is
                out of range. Every message names the figure and the field.
        """
        extra = set(data) - FIGURE_KEYS
        if extra:
            raise ValueError(f"{where}: unknown key(s) {sorted(extra)}")
        name = check_name(require_str(data, "name", where))
        source = require_str(data, "source", where)
        kind = optional_str(data, "kind", name).lower() or KIND_HTML
        if kind not in KINDS:
            raise ValueError(f"figure '{name}': kind must be one of {sorted(KINDS)}")
        width = positive_int(data.get("width", _DEFAULT_WIDTH), "width", name)
        height = positive_int(data.get("height", _DEFAULT_HEIGHT), "height", name)
        columns = positive_int(data.get("columns", _DEFAULT_COLUMNS), "columns", name)
        point = positive_int(data.get("point", _DEFAULT_POINT), "point", name)
        settle = positive_int(
            data.get("settle_ms", _DEFAULT_SETTLE_MS), "settle_ms", name
        )
        scale = positive_scale(data.get("scale", _DEFAULT_SCALE), name)
        return cls(
            name=name,
            kind=kind,
            source=source,
            width=width,
            height=height,
            scale=scale,
            title=optional_str(data, "title", name).strip(),
            columns=columns,
            point=point,
            out=check_output_name(name, optional_str(data, "out", name)),
            settle_ms=settle,
        )


def _reject_duplicates(what: str, values: list[str]) -> None:
    """Reject two figures that claim the same `name` or the same output file.

    A duplicated name is not cosmetic: `--only` selects by name, so it would
    build both figures, `verify --plan` matches by name, so coverage would be
    ambiguous, and the manifest would carry two records that a reader cannot
    tell apart. A duplicated output file makes two figures fight over one PNG.
    """
    duplicates = sorted({value for value in values if values.count(value) > 1})
    if duplicates:
        raise ValueError(f"plan: duplicate {what} {duplicates}")


def _located(plan_path: Path, message: str) -> str:
    """Prefix a plan error with the plan file, without saying `plan` twice."""
    label = f"plan '{plan_path}'"
    if message.startswith(label):
        return message
    if message.startswith("plan: "):
        return f"{label}: {message[len('plan: ') :]}"
    return f"{label}: {message}"


@dataclass(frozen=True)
class ShotPlan:
    """An ordered figure set plus the directory its sources are relative to.

    Attributes:
        figures: the figures, in render order.
        base_dir: the directory `source` paths resolve against.
    """

    figures: tuple[FigureSpec, ...]
    base_dir: Path = Path(".")

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, base_dir: str | Path = ".") -> ShotPlan:
        """Build a plan from a parsed mapping.

        The mapping is ``{"base_dir": ..., "defaults": {...}, "figures": [...]}``;
        only `figures` is required. Defaults are applied first, then the figure's
        own keys win.

        Raises:
            ValueError: when `figures` is missing/empty, a spec is invalid, two
                figures share a name, or two figures ask for the same output
                file.
        """
        base = plan_base(data.get("base_dir"), base_dir)
        raw_defaults = data.get("defaults") or {}
        if not isinstance(raw_defaults, dict):
            raise ValueError("plan: 'defaults' must be a mapping")
        extra = set(raw_defaults) - FIGURE_KEYS
        if extra:
            raise ValueError(f"plan: unknown key(s) in 'defaults' {sorted(extra)}")
        raw_figures = data.get("figures")
        if not isinstance(raw_figures, list) or not raw_figures:
            raise ValueError("plan: 'figures' must be a non-empty list")
        specs: list[FigureSpec] = []
        for index, raw in enumerate(raw_figures):
            if not isinstance(raw, dict):
                raise ValueError(f"plan: figures[{index}] must be a mapping")
            merged = {**raw_defaults, **raw}
            specs.append(
                FigureSpec.from_dict(
                    merged, where=figure_label(index, merged)
                ).with_source_dir(base)
            )
        _reject_duplicates("figure name(s)", [s.name for s in specs])
        _reject_duplicates("output file name(s)", [s.output_name() for s in specs])
        return cls(figures=tuple(specs), base_dir=base)

    @classmethod
    def load(cls, path: str | Path) -> ShotPlan:
        """Load a plan from a `.json` or `.toml` file (by extension).

        The base directory defaults to the plan file's own directory, so sources
        are written relative to the plan and the set travels with it.

        Every failure here is a *bad input* (exit code 2 via `cli_support`), so
        it is raised as a `ValueError` that names the file and the position:
        a bare `JSONDecodeError` message does not say which plan was read.
        """
        plan_path = Path(path)
        suffix = plan_path.suffix.lower()
        if suffix not in {".toml", ".json"}:
            raise ValueError(
                f"plan '{plan_path}': unsupported format "
                f"'{suffix or plan_path.name}', expected .toml or .json"
            )
        try:
            text = plan_path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ValueError(f"plan '{plan_path}': file not found") from exc
        except UnicodeDecodeError as exc:
            raise ValueError(f"plan '{plan_path}': not valid UTF-8") from exc
        except OSError as exc:
            raise ValueError(
                f"plan '{plan_path}': cannot read ({exc.strerror or exc})"
            ) from exc
        try:
            data = parse_plan(text, plan_path, suffix)
            return cls.from_dict(data, base_dir=plan_path.parent)
        except ValueError as exc:
            raise ValueError(_located(plan_path, str(exc))) from exc

    def to_dict(self) -> dict[str, Any]:
        """A JSON-ready view of the plan (round-trips `from_dict`)."""
        return {
            "base_dir": str(self.base_dir),
            "figures": [f.to_dict() for f in self.figures],
        }

    def selected(self, names: list[str] | None) -> ShotPlan:
        """Return a plan restricted to `names`, keeping render order.

        Raises:
            ValueError: when a requested name is not in the plan.
        """
        if not names:
            return self
        wanted = {n.strip() for n in names if n.strip()}
        known = {f.name for f in self.figures}
        missing = sorted(wanted - known)
        if missing:
            raise ValueError(f"plan: unknown figure(s) {missing}")
        return replace(self, figures=tuple(f for f in self.figures if f.name in wanted))


__all__ = [
    "KINDS",
    "KIND_HTML",
    "KIND_TERMINAL",
    "FigureSpec",
    "ShotPlan",
]
