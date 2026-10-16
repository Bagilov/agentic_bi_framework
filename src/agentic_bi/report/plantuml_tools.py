"""PlantUML helpers: local validation and rendering of ``.puml`` diagrams.

Rendering is needed before the diagram is embedded into the PDF report, and
validation catches syntax errors before a broken diagram reaches a reader.

The ``plantuml.jar`` location is resolved from configuration only:

    PLANTUML_JAR      explicit path to the jar
    PLANTUML_JAR_DIR  directory to glob for ``plantuml-*.jar`` (newest wins)

No environment-specific default path is shipped. Running the jar requires Java
on ``PATH``.
"""

from __future__ import annotations

import glob
import os
import re
import subprocess
import tempfile
from pathlib import Path


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


def validate_text(puml_text: str, jar: str | None = None) -> tuple[bool, str]:
    """Validate PlantUML source text.

    Returns:
        ``(ok, message)``. ``ok`` is True when the diagram compiles.
    """
    jar = jar or find_plantuml_jar()
    if not jar:
        return False, "plantuml.jar not found; set PLANTUML_JAR"

    with tempfile.TemporaryDirectory() as td:
        src = Path(td, "input.puml")
        src.write_text(puml_text, encoding="utf-8")
        result = _run(jar, ["-checkonly", str(src)])
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


def render_png(
    puml_text: str, out_dir: str | Path, jar: str | None = None
) -> Path | None:
    """Render PlantUML to PNG. Returns the generated path or None."""
    jar = jar or find_plantuml_jar()
    if not jar:
        return None
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        src = Path(td, "input.puml")
        src.write_text(puml_text, encoding="utf-8")
        result = _run(jar, ["-tpng", "-o", str(out_dir.resolve()), str(src)])
    merged = (result.stdout or "") + (result.stderr or "")
    if result.returncode != 0 and "error" in merged.lower():
        return None
    pngs = sorted(out_dir.glob("*.png"))
    return pngs[0] if pngs else None
