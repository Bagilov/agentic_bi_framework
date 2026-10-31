"""Deterministic screenshots of HTML and captured console output.

Article and report figures are usually hand-made: a throwaway script per image, a
browser flag list copied around, no record of what produced what. `shots` makes
the figure set a first-class, reproducible object:

* a **plan** (`shots_types`) names every figure, its source and its exact render
  parameters, so nothing about an image lives in an ad-hoc script;
* a **renderer** (`shots_render`) owns the one headless-Chromium invocation and
  every flag, so a figure is byte-reproducible on any machine with a browser;
* a **terminal card** builder (`shots_terminal`) turns captured CLI text into a
  deterministic card — wrapping and sizing happen in Python, not in the browser;
* a **manifest** (`shots_manifest`) records each PNG's size, hash and parameters,
  and `verify` re-checks them, so a stale or hand-edited figure is caught.

Typical use:

    from agentic_bi.shots import ShotPlan, build_shots
    plan = ShotPlan.load("figures.toml")
    result = build_shots(plan, "output_files/figures")
    assert result.ok

    # or from the command line
    # agentic-bi-shots --plan figures.toml
    # agentic-bi-shots verify --manifest output_files/figures/manifest.json

Environment-agnostic: the browser is discovered, never hardcoded, and the plan
carries its own sources, so a figure set is reproducible without the script that
first produced it.
"""

from __future__ import annotations

from agentic_bi.shots.shots_build import BuildResult, build_shots
from agentic_bi.shots.shots_manifest import (
    RenderRecord,
    ShotManifest,
    read_manifest,
    sha256_file,
    verify_manifest,
    write_manifest,
)
from agentic_bi.shots.shots_render import (
    BrowserNotFound,
    RenderError,
    render_html_file,
    render_html_string,
)
from agentic_bi.shots.shots_terminal import build_terminal_html
from agentic_bi.shots.shots_types import (
    KIND_HTML,
    KIND_TERMINAL,
    KINDS,
    FigureSpec,
    ShotPlan,
)

__all__ = [
    "KINDS",
    "KIND_HTML",
    "KIND_TERMINAL",
    "BrowserNotFound",
    "BuildResult",
    "FigureSpec",
    "RenderError",
    "RenderRecord",
    "ShotManifest",
    "ShotPlan",
    "build_shots",
    "build_terminal_html",
    "read_manifest",
    "render_html_file",
    "render_html_string",
    "sha256_file",
    "verify_manifest",
    "write_manifest",
]
