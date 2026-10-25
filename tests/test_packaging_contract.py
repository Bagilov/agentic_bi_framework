"""Packaging contract: every declared extra must be resolvable and honest.

Two install blockers were found by measurement, not by reading:

* `server-native` declared `spnego>=0.4`. That distribution no longer exists on
  PyPI (404); the module `spnego` is now provided by `pyspnego`. Any environment
  installing `[all]` or `[server-native]` failed to resolve.
* `server` declared `requests-negotiate-sspi>=0.4`. Every sdist up to 0.5.0
  declares its own version as `0.0.0`, so the constraint is unsatisfiable and pip
  answers with `resolution-too-deep` after exhausting its backtracking budget
  (measured: the whole `[all]` extra became uninstallable). The package also
  depends on `pywin32`, which ships Windows-only wheels, so a Linux leg cannot
  install it at all.

These tests read the declared metadata and assert the fixed shape, so the
mistakes cannot come back unnoticed.
"""

from __future__ import annotations

from pathlib import Path

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # Python 3.10 (the package floor) has no tomllib
    import tomli as tomllib

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = REPO_ROOT / "pyproject.toml"

# Distribution names that must never appear in the declared dependencies: removed
# from PyPI, or renamed. The module may still be imported under the old name.
RETIRED_DISTRIBUTIONS = {"spnego"}

# The Windows-only Negotiate helper: it must carry a platform marker and the
# first correctly-versioned wheel, never the historically unsatisfiable `>=0.4`.
NEGOTIATE_DIST = "requests-negotiate-sspi"
NEGOTIATE_MIN = "0.5.2"


def _project() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]


def _requirement_name(requirement: str) -> str:
    """Return the distribution name of a PEP 508 requirement string."""
    for sep in ("[", ">", "<", "=", "!", "~", ";", " "):
        requirement = requirement.split(sep, 1)[0]
    return requirement.strip().lower().replace("_", "-")


def _all_declared_requirements() -> list[tuple[str, str]]:
    project = _project()
    pairs: list[tuple[str, str]] = [
        ("dependencies", dep) for dep in project.get("dependencies", [])
    ]
    for group, deps in project.get("optional-dependencies", {}).items():
        pairs.extend((group, dep) for dep in deps)
    return pairs


def _requirements_for(name: str) -> list[tuple[str, str]]:
    """Every (group, requirement) whose distribution name is `name`."""
    return [
        (group, dep)
        for group, dep in _all_declared_requirements()
        if _requirement_name(dep) == name
    ]


def test_no_retired_distribution_is_declared() -> None:
    offenders = [
        (group, dep)
        for group, dep in _all_declared_requirements()
        if _requirement_name(dep) in RETIRED_DISTRIBUTIONS
    ]
    assert offenders == [], f"retired distributions declared: {offenders}"


def test_negotiate_helper_is_windows_marked_and_not_the_broken_pin() -> None:
    """`requests-negotiate-sspi` must be `>=0.5.2` and `sys_platform == 'win32'`."""
    declared = _requirements_for(NEGOTIATE_DIST)
    assert declared, "the Windows Negotiate helper must still be declared"
    for group, dep in declared:
        assert "win32" in dep, f"{group}: missing the Windows marker in {dep!r}"
        assert "0.5.2" in dep, f"{group}: broken pin in {dep!r}"
        assert ">=0.4" not in dep, f"{group}: unsatisfiable 0.4 pin returned in {dep!r}"


def test_pywin32_dependency_is_never_declared_directly() -> None:
    """`pywin32` arrives only through the marked Windows helper."""
    offenders = [
        dep
        for _g, dep in _all_declared_requirements()
        if "win32" in _requirement_name(dep)
    ]
    assert offenders == [], f"pywin32 must not be declared directly: {offenders}"


def test_server_native_uses_the_live_spnego_distribution() -> None:
    groups = _project()["optional-dependencies"]
    assert "pyspnego" in {_requirement_name(d) for d in groups["server-native"]}


def test_spnego_provider_is_declared_in_all() -> None:
    groups = _project()["optional-dependencies"]
    names = {_requirement_name(d) for d in groups["all"]}
    assert "pyspnego" in names


def test_every_extra_requirement_has_a_name_and_no_pin_gap() -> None:
    for group, dep in _all_declared_requirements():
        name = _requirement_name(dep)
        assert name, f"{group}: empty requirement name in {dep!r}"
        assert name == name.lower(), f"{group}: {dep!r} is not lower-cased"


def test_ci_workflow_exists_and_covers_the_matrix() -> None:
    workflow = REPO_ROOT / ".github" / "workflows" / "ci.yml"
    assert workflow.exists(), "CI workflow is missing"
    text = workflow.read_text(encoding="utf-8")
    assert "3.10" in text and "3.12" in text
    assert "ubuntu-latest" in text and "windows-latest" in text
    assert "ruff check" in text
    assert "ruff format --check" in text
    assert "pytest" in text
    # The test job must install the dev extra too: the Python 3.10 leg needs
    # `tomli`, which only the `dev` extra pulls in.
    assert ".[all,dev]" in text


def test_python_floor_modules_are_importable_here() -> None:
    """Everything the suite imports must exist on the declared floor (3.10).

    `tomllib` is 3.11+, so `tests/test_packaging_contract.py` guards it with a
    `tomli` fallback. CI caught the un-guarded version: the 3.10 leg failed to
    collect while 3.12 passed.
    """
    source = (REPO_ROOT / "tests" / "test_packaging_contract.py").read_text(
        encoding="utf-8"
    )
    assert "except ModuleNotFoundError" in source
    assert "import tomli as tomllib" in source
