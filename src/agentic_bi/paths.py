"""Runtime-writable locations for the framework's inputs and outputs.

Nothing here resolves against the *package directory*. In a read-only install
(``site-packages`` under a system prefix, a container image, a wheel owned by
another user) writing next to the source fails with ``PermissionError`` before
any real work happens — verified on ``EnginePipeline()``, whose constructor
creates its work directory eagerly.

Two distinct kinds of location, kept apart on purpose:

* **Deliverables** are CWD-relative (``output_files/``), so a user finds them
  where they ran the command. This matches the existing CLIs
  (``agentic-bi-antipatterns``, ``agentic-bi-lineage``).
* **Scratch space** lives under the system temp directory, because it is
  machine state (build staging, subprocess cwd), not an artifact to keep.

Public API:
    OUTPUT_FILES               - the CWD-relative deliverable root name
    output_dir(*parts)         - `output_files/<parts...>` (CWD-relative)
    ensure_dir(path)           - mkdir -p, returning the path
    scratch_dir(name)          - a writable per-command scratch directory
"""

from __future__ import annotations

import tempfile
from pathlib import Path

OUTPUT_FILES = "output_files"

_SCRATCH_ROOT = "agentic_bi"


def output_dir(*parts: str) -> Path:
    """Return ``output_files/<parts...>`` relative to the current directory.

    Args:
        *parts: path components appended to the deliverable root.

    Returns:
        The composed, CWD-relative path. The directory is *not* created.
    """
    return Path(OUTPUT_FILES).joinpath(*parts)


def ensure_dir(path: Path) -> Path:
    """Create `path` (and parents) when missing and return it unchanged."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def scratch_dir(name: str = "_work") -> Path:
    """Return a writable scratch directory under the system temp directory.

    The location is per-user and stable across calls (so a retry reuses the same
    staging area), but never inside the package.

    Args:
        name: subdirectory name under the framework's temp root.

    Returns:
        The created, writable directory.
    """
    return ensure_dir(Path(tempfile.gettempdir()) / _SCRATCH_ROOT / name)


__all__ = ["OUTPUT_FILES", "ensure_dir", "output_dir", "scratch_dir"]
