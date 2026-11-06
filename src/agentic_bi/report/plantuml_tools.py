"""PlantUML helpers: local validation, rendering and atomic export of diagrams.

The ``plantuml.jar`` location is resolved from configuration only
(``PLANTUML_JAR``, or the newest ``plantuml-*.jar`` in ``PLANTUML_JAR_DIR``); no
default path is shipped, and running the jar needs Java on ``PATH``.

Several ``@startuml ... @enduml`` blocks in one source make PlantUML emit one
image per block. :func:`render_png_ex` publishes every produced image under
deterministic names and returns the primary one plus a diagnostic string;
:func:`render_png` is the plain ``Path | None`` wrapper kept for callers that
only need the file (e.g. :mod:`agentic_bi.report.pdf_diagram`).

The implementation is split by responsibility: naming and header analysis live
in :mod:`agentic_bi.report.plantuml_names`, atomic publishing lives in
:mod:`agentic_bi.report.plantuml_publish`, and this module keeps the runner and
the public API.
"""

from __future__ import annotations

import glob
import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path

from agentic_bi.report.plantuml_names import (
    order_produced,
    prepare_source,
    safe_stem,
)
from agentic_bi.report.plantuml_publish import export_puml, publish_artifacts

logger = logging.getLogger(__name__)


def find_plantuml_jar() -> str | None:
    """Resolve the PlantUML jar from ``PLANTUML_JAR`` / ``PLANTUML_JAR_DIR``."""
    env = os.getenv("PLANTUML_JAR")
    if env and Path(env).exists():
        return env
    jar_dir = os.getenv("PLANTUML_JAR_DIR")
    if jar_dir:
        matches = sorted(glob.glob(str(Path(jar_dir, "plantuml-*.jar"))))
        if matches:
            return matches[-1]
    return None


def _run(
    jar: str, args: list[str], stdin_text: str | None = None
) -> subprocess.CompletedProcess:
    """Run the jar with a forced UTF-8 charset (Windows-safe for Unicode)."""
    cmd = [
        "java",
        "-Dfile.encoding=UTF-8",
        "-Dsun.jnu.encoding=UTF-8",
        "-jar",
        jar,
        "-charset",
        "UTF-8",
        *args,
    ]
    if stdin_text is not None:
        return subprocess.run(cmd, input=stdin_text, capture_output=True, text=True)
    return subprocess.run(cmd, capture_output=True, text=True)


def _diagnostic(result: subprocess.CompletedProcess) -> str:
    """Extract a short, user-facing PlantUML diagnostic from a run result."""
    merged = ((result.stdout or "") + (result.stderr or "")).strip()
    if not merged:
        return ""
    match = re.search(r"Error\s+line\s+\d+[^\n]*", merged, re.IGNORECASE)
    if match:
        return match.group(0).strip()
    return merged[-500:]


def validate_text(puml_text: str, jar: str | None = None) -> tuple[bool, str]:
    """Validate PlantUML source text.

    Returns:
        ``(ok, message)``. ``ok`` is True when the diagram compiles. A missing
        Java runtime is reported as a diagnostic instead of an exception.
    """
    jar = jar or find_plantuml_jar()
    if not jar:
        return False, "plantuml.jar not found; set PLANTUML_JAR"

    with tempfile.TemporaryDirectory() as td:
        src = Path(td, "input.puml")
        src.write_text(puml_text, encoding="utf-8")
        try:
            result = _run(jar, ["-checkonly", str(src)])
        except OSError as exc:
            return False, f"java not runnable: {exc}"
    merged = (result.stdout or "") + (result.stderr or "")
    if "error" in merged.lower():
        m = re.search(r"Error\s+line\s+(\d+)[^\n]*", merged, re.IGNORECASE)
        line = m.group(0).strip() if m else merged.strip()[-200:]
        return False, line
    if result.returncode != 0 and "some diagram" not in merged.lower():
        return False, merged.strip()[-300:]
    return True, "OK"


def validate_file(puml_path: str | Path, jar: str | None = None) -> tuple[bool, str]:
    """Validate a ``.puml`` file on disk."""
    text = Path(puml_path).read_text(encoding="utf-8")
    return validate_text(text, jar)


def _produced_pngs(work: Path) -> list[Path]:
    """PNGs the jar wrote inside `work` (a ``@startuml ../x`` header cannot escape)."""
    root = work.resolve()
    found: list[Path] = []
    for candidate in work.rglob("*.png"):
        try:
            if candidate.resolve().is_relative_to(root):
                found.append(candidate)
        except OSError:
            continue
    return found


def _non_empty(path: Path) -> bool:
    try:
        return path.stat().st_size > 0
    except OSError:
        return False


def render_png_ex(
    puml_text: str,
    out_dir: str | Path,
    jar: str | None = None,
    *,
    name: str = "diagram",
) -> tuple[Path | None, str]:
    """Render PlantUML to PNG and return ``(primary_path, diagnostic)``.

    Headers are made unique before the jar runs (:func:`prepare_source`), so the
    jar never overwrites one block's image with another's and the primary always
    corresponds to the first block in source order. Only files that really live
    inside the private work directory are considered; each produced file must be
    non-empty to be published, and success is taken from the staged file that
    was moved (never from a re-read of ``out_dir``, which would race).

    Several blocks yield ``<name>.png``, ``<name>_2.png``, ... in source order;
    leftover suffixed files from an earlier, larger run are removed after the new
    set lands, using the artifact manifest rather than guessing by name.

    Publishing never crosses a filesystem boundary directly: every image is
    copied into ``out_dir`` and renamed from there, so a disk-full or I/O error
    leaves the previous artifact untouched. Any ``OSError`` of the publish phase
    becomes a diagnostic, which lets the CLI report exit code 1 (negative
    result) instead of 2 (bad input).

    Args:
        puml_text: the PlantUML source (``@startuml`` ... ``@enduml``).
        out_dir: the directory to write the PNG files into.
        jar: an explicit ``plantuml.jar``; resolved from the environment when
            omitted.
        name: the requested output stem; sanitized so it cannot escape `out_dir`.

    Returns:
        ``(<out_dir>/<name>.png, "")`` on success. On failure ``(None, reason)``
        where reason is the PlantUML diagnostic, a configuration hint when the
        jar or Java is missing, or the publish diagnostic when the images could
        not be placed.
    """
    jar = jar or find_plantuml_jar()
    if not jar:
        return None, "plantuml.jar not found; set PLANTUML_JAR (and install Java)"
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = safe_stem(name)
    prepared = prepare_source(puml_text)
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        src = work / f"{stem}.puml"
        src.write_text(prepared.text, encoding="utf-8")
        try:
            result = _run(jar, ["-tpng", "-o", str(work), str(src)])
        except OSError as exc:
            return None, f"java not runnable: {exc}"
        if result.returncode != 0:
            return None, _diagnostic(result) or (
                f"PlantUML exited with code {result.returncode}"
            )
        produced = order_produced(_produced_pngs(work), prepared.names, work)
        if not produced:
            return None, _diagnostic(result) or "PlantUML produced no PNG"
        publishable = [path for path in produced if _non_empty(path)]
        if not publishable:
            return None, "PlantUML produced only empty PNG files"
        try:
            targets = publish_artifacts(publishable, out_dir, stem)
        except OSError as exc:
            return None, f"could not publish diagram: {exc}"
    if len(targets) > 1:
        logger.warning(
            "PlantUML source has %d diagrams; wrote %s (returning %s)",
            len(targets),
            ", ".join(target.name for target in targets),
            targets[0].name,
        )
    return targets[0], ""


def render_png(
    puml_text: str,
    out_dir: str | Path,
    jar: str | None = None,
    *,
    name: str = "diagram",
) -> Path | None:
    """Render PlantUML to PNG: the primary path, or None.

    Thin wrapper over :func:`render_png_ex`; see it for naming and publishing.
    """
    primary, _ = render_png_ex(puml_text, out_dir, jar, name=name)
    return primary


__all__ = [
    "export_puml",
    "find_plantuml_jar",
    "render_png",
    "render_png_ex",
    "safe_stem",
    "validate_file",
    "validate_text",
]
