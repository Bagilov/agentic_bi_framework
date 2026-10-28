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

import re
import subprocess
from pathlib import Path

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # Python 3.10 (the package floor) has no tomllib
    import tomli as tomllib

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = REPO_ROOT / "pyproject.toml"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

# Distribution names that must never appear in the declared dependencies: removed
# from PyPI, or renamed. The module may still be imported under the old name.
RETIRED_DISTRIBUTIONS = {"spnego"}

# The Windows-only Negotiate helper: it must carry a platform marker and the
# first correctly-versioned wheel, never the historically unsatisfiable `>=0.4`.
NEGOTIATE_DIST = "requests-negotiate-sspi"
NEGOTIATE_MIN = "0.5.2"


def _project() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]


def _pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def _load_ci_workflow() -> str:
    return CI_WORKFLOW.read_text(encoding="utf-8")


def _ci_step_blocks() -> list[str]:
    """Split the workflow into per-step text blocks, without requiring PyYAML.

    PyYAML is an optional (`spec`/`all`) dependency and the module contract is
    that the stdlib-only suite runs anywhere, so this does not import it. A
    GitHub step starts with `      - ` (6-space list item); everything indented
    deeper belongs to it. Returning whole blocks lets an assertion be scoped to
    the step that actually runs a given command, instead of matching a substring
    that any other step could satisfy.
    """
    blocks: list[str] = []
    current: list[str] = []
    for line in _load_ci_workflow().splitlines():
        if line.startswith("      - "):
            if current:
                blocks.append("\n".join(current))
            current = [line]
        elif current and (line.startswith("        ") or not line.strip()):
            current.append(line)
        elif current:
            blocks.append("\n".join(current))
            current = []
    if current:
        blocks.append("\n".join(current))
    return blocks


def _step_running(command: str) -> str:
    """Return the single CI step block whose `run` invokes `command`.

    Matching is scoped to the step's `run` value, so a step that merely mentions
    the command elsewhere (e.g. `pip install "mypy>=1.8"`) does not qualify.
    Both forms are handled: a one-line `run: mypy ...` and a `run: |` block whose
    first command line is `mypy ...`.
    """
    matches = []
    for block in _ci_step_blocks():
        for line in block.splitlines():
            stripped = line.strip()
            if not stripped.startswith("run:"):
                continue
            value = stripped[len("run:") :].strip()
            body_matches = value == command or value.startswith(f"{command} ")
            block_matches = value in ("|", ">") and any(
                inner.strip().startswith(command)
                for inner in block.splitlines()
                if inner.startswith("          ")
            )
            if body_matches or block_matches:
                matches.append(block)
                break
    assert len(matches) == 1, f"expected exactly one CI step running {command!r}"
    return matches[0]


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


def test_no_test_parameter_carries_a_huge_literal() -> None:
    """A large literal in `parametrize` breaks the suite on Windows.

    pytest writes the current test id into `PYTEST_CURRENT_TEST`, and Windows
    caps an environment variable at 32767 characters. A `parametrize` entry such
    as `b"y" * 100_000` therefore fails at teardown with
    `ValueError: the environment variable is longer than 32767 characters`
    (observed on the `windows-latest` CI leg, while Linux and macOS passed).

    Parameters are scanned structurally: any string/bytes constant, or constant
    `str/bytes * int` fold, that would render past the cap.
    """
    import ast

    limit = 8_000  # well under 32767, leaving room for the module/test prefix
    offenders: list[str] = []
    for path in sorted((REPO_ROOT / "tests").glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and getattr(node.func, "attr", "") == "parametrize"
            ):
                continue
            for arg in node.args:
                for sub in ast.walk(arg):
                    size: int | None = None
                    if isinstance(sub, ast.Constant) and isinstance(
                        sub.value, (str, bytes)
                    ):
                        size = len(sub.value)
                    elif (
                        isinstance(sub, ast.BinOp)
                        and isinstance(sub.op, ast.Mult)
                        and isinstance(sub.left, ast.Constant)
                        and isinstance(sub.right, ast.Constant)
                        and isinstance(sub.left.value, (str, bytes))
                        and isinstance(sub.right.value, int)
                    ):
                        size = len(sub.left.value) * sub.right.value
                    if size is not None and size >= limit:
                        offenders.append(f"{path.name}:{node.lineno} ~{size} chars")
    assert offenders == [], f"oversized parametrize literals: {offenders}"


def test_py_typed_marker_is_shipped() -> None:
    """`py.typed` must exist, be tracked, and be declared as package data.

    Without the file the package is treated as untyped by a consumer's checker;
    without the package-data entry it exists in the tree but not in the wheel.
    Without the file being **tracked**, CI checks out a tree without it: this
    test would turn red there and every wheel built from that commit would omit
    the marker while `package-data` still claims it ships.
    """
    marker = REPO_ROOT / "src" / "agentic_bi" / "py.typed"
    assert marker.exists(), "src/agentic_bi/py.typed is missing"
    package_data = _pyproject()["tool"]["setuptools"]["package-data"]["agentic_bi"]
    assert "py.typed" in package_data, "py.typed is not declared as package data"

    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "src/agentic_bi/py.typed"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert tracked.returncode == 0, (
        "src/agentic_bi/py.typed is not tracked by git; `git add` it or CI and "
        "clean-clone wheels will not ship it"
    )


def test_runtime_script_data_is_declared_as_package_data() -> None:
    """`_engine_build.ps1` is spawned by `engine_host`, so it must ship.

    It is runtime data, not build input: the engine CLI reads it from the
    installed package, so excluding it would break `agentic-bi-engine`.
    """
    package_data = _pyproject()["tool"]["setuptools"]["package-data"]["agentic_bi"]
    assert "_engine_build.ps1" in package_data


def test_mypy_runs_in_ci_with_a_baseline_ratchet() -> None:
    """Stage 3: a type checker runs in CI, report-only but observably pinned.

    The step deliberately does not use `continue-on-error`; instead it compares
    the observed error count to `MYPY_BASELINE` and fails when the count grows,
    so a regression (or a silently zero-target run) cannot read as success. The
    assertions below are scoped to the `mypy` step so a flag somewhere else in
    the workflow cannot satisfy them.
    """
    mypy = _pyproject()["tool"]["mypy"]
    assert mypy["python_version"] == "3.10"
    assert "src/agentic_bi" in mypy["files"]
    assert mypy["ignore_missing_imports"] is True

    step = _step_running("mypy")
    # The ratchet is the observable contract: a baseline is declared and the
    # step compares against it, rather than being unconditionally non-blocking.
    assert "MYPY_BASELINE" in step, "the mypy step must declare a tracked baseline"
    assert "continue-on-error" not in step, (
        "the ratchet must be able to fail; report-only comes from the non-zero "
        "baseline, not from a blanket continue-on-error"
    )
    # A declared baseline that is never compared would make the step a no-op.
    baseline = re.search(r"MYPY_BASELINE:\s*\"?(\d+)\"?", step)
    assert baseline, "the mypy step must declare a numeric MYPY_BASELINE"
    assert re.search(r"-gt\s+\"?\$MYPY_BASELINE", step), (
        "the baseline must bound a comparison, not just be echoed"
    )
    # And the checker itself must be bounded, so the baseline is reproducible.
    dev = _project()["optional-dependencies"]["dev"]
    mypy_req = next(d for d in dev if _requirement_name(d) == "mypy")
    assert "<" in mypy_req, f"the mypy requirement must be bounded: {mypy_req!r}"


def test_dev_extra_declares_the_type_checker() -> None:
    dev = _project()["optional-dependencies"]["dev"]
    names = {_requirement_name(dep) for dep in dev}
    assert "mypy" in names


def test_ruff_selects_ble_and_ruf100() -> None:
    """`BLE` must be on so a new blind except cannot slip in, `RUF100` so a
    directive cannot outlive the code it suppressed."""
    select = _pyproject()["tool"]["ruff"]["lint"]["select"]
    assert "BLE" in select
    assert "RUF100" in select
