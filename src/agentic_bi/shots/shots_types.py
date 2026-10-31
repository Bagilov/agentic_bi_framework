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

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import tomllib

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
    def from_dict(cls, data: dict[str, Any]) -> FigureSpec:
        """Validate one spec mapping.

        Raises:
            ValueError: when `name`/`kind`/`source` are missing or a value is
                out of range. Every message names the offending field.
        """
        extra = set(data) - {
            "name",
            "kind",
            "source",
            "width",
            "height",
            "scale",
            "title",
            "columns",
            "point",
            "out",
            "settle_ms",
        }
        if extra:
            raise ValueError(f"figure: unknown key(s) {sorted(extra)}")
        name = _check_name(_require_str(data, "name"))
        source = _require_str(data, "source")
        kind = str(data.get("kind") or KIND_HTML).strip().lower()
        if kind not in KINDS:
            raise ValueError(f"figure '{name}': kind must be one of {sorted(KINDS)}")
        width = _positive_int(data.get("width", _DEFAULT_WIDTH), "width", name)
        height = _positive_int(data.get("height", _DEFAULT_HEIGHT), "height", name)
        columns = _positive_int(data.get("columns", _DEFAULT_COLUMNS), "columns", name)
        point = _positive_int(data.get("point", _DEFAULT_POINT), "point", name)
        settle = _positive_int(
            data.get("settle_ms", _DEFAULT_SETTLE_MS), "settle_ms", name
        )
        try:
            scale = float(data.get("scale", _DEFAULT_SCALE))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"figure '{name}': scale must be a number") from exc
        if scale <= 0:
            raise ValueError(f"figure '{name}': scale must be positive")
        return cls(
            name=name,
            kind=kind,
            source=source,
            width=width,
            height=height,
            scale=scale,
            title=str(data.get("title") or ""),
            columns=columns,
            point=point,
            out=_check_output_name(name, str(data.get("out") or "")),
            settle_ms=settle,
        )


def _require_str(data: dict[str, Any], key: str) -> str:
    """A non-empty string field, or a ValueError naming it."""
    value = str(data.get(key) or "").strip()
    if not value:
        raise ValueError(f"figure: '{key}' is required")
    return value


def _check_output_name(name: str, out: str) -> str:
    """Validate an explicit `out`: a bare file name inside the output directory.

    A plan is data, and `out` is written under the run's `--out-dir`; a value
    with a directory component, an absolute path or `..` would let a plan write
    outside that directory (or overwrite an unrelated file). Rejected rather
    than sanitized, so a mistake is visible instead of silently relocated.
    """
    if not out:
        return out
    candidate = Path(out)
    if candidate.is_absolute() or candidate.parent != Path("."):
        raise ValueError(f"figure '{name}': out must be a bare file name, got '{out}'")
    return out


def _check_name(name: str) -> str:
    """A figure name must be usable as a file stem (no separators, no `..`)."""
    if name in {".", ".."} or Path(name).parent != Path("."):
        raise ValueError(f"figure: name must be a bare identifier, got '{name}'")
    return name


def _positive_int(value: Any, key: str, name: str) -> int:
    """A positive integer field, or a ValueError naming it."""
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"figure '{name}': {key} must be an integer") from exc
    if number <= 0:
        raise ValueError(f"figure '{name}': {key} must be positive")
    return number


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
            ValueError: when `figures` is missing/empty, a spec is invalid, or
                two figures ask for the same output file.
        """
        base = Path(data.get("base_dir") or ".")
        if not base.is_absolute():
            # A relative base_dir is relative to the plan file, not to the
            # caller's CWD, so a plan and its sources travel together.
            base = Path(base_dir) / base
        raw_defaults = data.get("defaults") or {}
        if not isinstance(raw_defaults, dict):
            raise ValueError("plan: 'defaults' must be a mapping")
        raw_figures = data.get("figures")
        if not isinstance(raw_figures, list) or not raw_figures:
            raise ValueError("plan: 'figures' must be a non-empty list")
        specs: list[FigureSpec] = []
        for index, raw in enumerate(raw_figures):
            if not isinstance(raw, dict):
                raise ValueError(f"plan: figures[{index}] must be a mapping")
            merged = {**raw_defaults, **raw}
            specs.append(FigureSpec.from_dict(merged).with_source_dir(base))
        outs = [s.output_name() for s in specs]
        duplicates = sorted({name for name in outs if outs.count(name) > 1})
        if duplicates:
            raise ValueError(f"plan: duplicate output file(s) {duplicates}")
        return cls(figures=tuple(specs), base_dir=base)

    @classmethod
    def load(cls, path: str | Path) -> ShotPlan:
        """Load a plan from a `.json` or `.toml` file (by extension).

        The base directory defaults to the plan file's own directory, so sources
        are written relative to the plan and the set travels with it.
        """
        plan_path = Path(path)
        if plan_path.suffix.lower() == ".toml":
            data = tomllib.loads(plan_path.read_text(encoding="utf-8"))
        else:
            data = json.loads(plan_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("plan: top level must be a mapping")
        return cls.from_dict(data, base_dir=plan_path.parent)

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
