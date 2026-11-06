"""Field validation for a shot plan (untrusted TOML/JSON input).

A plan is written by hand, so every field is checked against an explicit rule
and every failure is a `ValueError` that names the figure (or the plan key) and
what was expected. Two classes of bug are closed here:

* type confusion — `name = 42` used to become the string `"42"`, `width = true`
  became `1 px`; both are now rejected;
* an unlocated error — a `JSONDecodeError` from the plan file said only
  "Expecting value", so the caller could not tell which plan was broken.

Public API:
    FIGURE_KEYS                - every key a figure (or `defaults`) may carry
    figure_label(index, data)  - `figure 'a'` / `figures[2]` for error messages
    require_str(data, key, where) - a required non-empty string field
    optional_str(data, key, name)
    check_name(name)           - a bare file stem
    check_output_name(name, out)
    positive_int(value, key, name)
    positive_scale(value, name)
    plan_base(raw, base_dir)   - the source directory of a plan
    parse_plan(text, path, suffix) -> dict
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # Python 3.10 (the package floor) has no tomllib
    import tomli as tomllib

FIGURE_KEYS = frozenset(
    {
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
)


def figure_label(index: int, data: dict[str, Any]) -> str:
    """The most specific label for one figure in a plan.

    A plan can hold dozens of figures, so `figure: 'source' is required` does not
    say which one. The name is used when the figure has one; otherwise the index
    is, because a figure whose `name` is missing has no name to report.
    """
    raw = data.get("name")
    if isinstance(raw, str) and raw.strip():
        return f"figure '{raw.strip()}'"
    return f"figures[{index}]"


def require_str(data: dict[str, Any], key: str, where: str = "figure") -> str:
    """A non-empty string field, or a ValueError naming the figure and the key.

    Args:
        data: the figure mapping.
        key: the required field name.
        where: the figure's label (`figure 'a'` or `figures[2]`), so a plan with
            many figures says which one is broken.
    """
    value = data.get(key)
    if value is None:
        raise ValueError(f"{where}: '{key}' is required")
    if not isinstance(value, str):
        raise ValueError(
            f"{where}: '{key}' must be a string, got {type(value).__name__}"
        )
    text = value.strip()
    if not text:
        raise ValueError(f"{where}: '{key}' is required")
    return text


def optional_str(data: dict[str, Any], key: str, name: str) -> str:
    """An optional string field: absent/None is empty, a non-string is an error."""
    value = data.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(
            f"figure '{name}': '{key}' must be a string, got {type(value).__name__}"
        )
    return value


def check_name(name: str) -> str:
    """A figure name must be usable as a file stem (no separators, no `..`)."""
    if name in {".", ".."} or Path(name).parent != Path("."):
        raise ValueError(f"figure: name must be a bare identifier, got '{name}'")
    return name


def check_output_name(name: str, out: str) -> str:
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


def positive_int(value: Any, key: str, name: str) -> int:
    """A positive integer field, or a ValueError naming it.

    `bool` and a fractional float are rejected instead of being coerced:
    `width = true` would otherwise silently render at 1 px.
    """
    if isinstance(value, bool) or (isinstance(value, float) and not value.is_integer()):
        raise ValueError(f"figure '{name}': {key} must be an integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"figure '{name}': {key} must be an integer") from exc
    if number <= 0:
        raise ValueError(f"figure '{name}': {key} must be positive")
    return number


def positive_scale(value: Any, name: str) -> float:
    """A finite, positive device scale factor."""
    if isinstance(value, bool):
        raise ValueError(f"figure '{name}': scale must be a number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"figure '{name}': scale must be a number") from exc
    if not math.isfinite(number):
        raise ValueError(f"figure '{name}': scale must be finite")
    if number <= 0:
        raise ValueError(f"figure '{name}': scale must be positive")
    return number


def plan_base(raw: Any, base_dir: str | Path) -> Path:
    """The directory sources resolve against: `base_dir` relative to the plan."""
    if raw is None or raw == "":
        base = Path(".")
    elif isinstance(raw, str):
        base = Path(raw)
    else:
        raise ValueError(
            f"plan: 'base_dir' must be a string path, got {type(raw).__name__}"
        )
    # A relative base_dir is relative to the plan file, not to the caller's
    # CWD, so a plan and its sources travel together.
    return base if base.is_absolute() else Path(base_dir) / base


def parse_plan(text: str, plan_path: Path, suffix: str) -> dict[str, Any]:
    """Parse plan text, turning a syntax error into a located `ValueError`."""
    if suffix == ".toml":
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise ValueError(f"plan '{plan_path}': invalid TOML ({exc})") from exc
    else:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"plan '{plan_path}': invalid JSON at line {exc.lineno} "
                f"column {exc.colno}: {exc.msg}"
            ) from exc
    if not isinstance(data, dict):
        raise ValueError(f"plan '{plan_path}': top level must be a mapping")
    return data


__all__ = [
    "FIGURE_KEYS",
    "check_name",
    "check_output_name",
    "figure_label",
    "optional_str",
    "parse_plan",
    "plan_base",
    "positive_int",
    "positive_scale",
    "require_str",
]
