"""Shared fixtures for the `agentic_bi` test suite.

The binary tests need a real `.pbix` (the DataModel codec and ABF indexes only
exist inside a container). The framework ships one at
`templates/template.pbix`; when it is absent the binary tests are skipped rather
than failed, so the stdlib-only suite still runs anywhere.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = REPO_ROOT / "templates" / "template.pbix"


@pytest.fixture(scope="session")
def template_pbix() -> Path:
    """Path to the shipped donor `.pbix` (skips the test when it is missing)."""
    if not TEMPLATE.exists():
        pytest.skip(f"donor template not found: {TEMPLATE}")
    return TEMPLATE


@pytest.fixture
def template_copy(template_pbix: Path, tmp_path: Path) -> Path:
    """A writable copy of the donor `.pbix` in a temp directory."""
    dst = tmp_path / "template.pbix"
    shutil.copy2(template_pbix, dst)
    return dst
