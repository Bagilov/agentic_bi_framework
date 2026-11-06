"""Every documented way to run a command must actually resolve.

A console entry point is a public API surface: `pyproject.toml` declares the
`agentic-bi-*` commands, and the docs additionally show `python -m
agentic_bi.<module>` invocations. Both can rot silently — a renamed module, a
`main` moved out of a package `__init__`, or a documented module that was never
registered — and nothing in the test suite noticed until this file existed.

The checks here are deliberately static (import-based, no subprocess, no
network) so they run on every platform and stay fast.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
DOC_FILES = ("README.md", "docs/FRAMEWORK.md", "docs/IMPLEMENTATION.md")

_PARAM = r"^([A-Za-z_]\w*)\s*=\s*([\"'])(.+?)\2\s*$"


def _scripts_block() -> list[tuple[str, str]]:
    """Return `(command, target)` pairs declared under `[project.scripts]`."""
    text = PYPROJECT.read_text(encoding="utf-8")
    if "[project.scripts]" not in text:
        return []
    block = text.split("[project.scripts]", 1)[1].split("\n[", 1)[0]
    pairs: list[tuple[str, str]] = []
    for line in block.splitlines():
        match = re.match(_PARAM, line.strip())
        if match:
            pairs.append((match.group(1), match.group(3)))
    return pairs


def _documented_modules() -> list[str]:
    """Return every `agentic_bi.<module>` the docs tell a user to run."""
    found: set[str] = set()
    pattern = re.compile(r"python[0-9.]*\s+-m\s+(agentic_bi[\w.]*)")
    for name in DOC_FILES:
        path = ROOT / name
        if not path.exists():
            continue
        found.update(pattern.findall(path.read_text(encoding="utf-8")))
    return sorted(found)


class TestConsoleScriptsResolve:
    """Each declared `agentic-bi-*` command points at a real callable `main`."""

    @pytest.mark.parametrize(("command", "target"), _scripts_block())
    def test_the_target_module_imports_and_exposes_main(
        self, command: str, target: str
    ) -> None:
        module_name, _, attr = target.partition(":")
        module = importlib.import_module(module_name)
        entry = getattr(module, attr, None)
        assert callable(entry), f"{command}: {target} is not callable"

    @pytest.mark.parametrize(("command", "target"), _scripts_block())
    def test_the_command_name_follows_the_agentic_bi_prefix(
        self, command: str, target: str
    ) -> None:
        assert command.startswith("agentic-bi-"), command

    def test_every_command_name_is_unique(self) -> None:
        names = [command for command, _ in _scripts_block()]
        assert len(names) == len(set(names))


class TestDocumentedModulesAreRunnable:
    """A `python -m agentic_bi.x` line in the docs must not be a dead end."""

    def test_the_docs_mention_at_least_one_module(self) -> None:
        assert _documented_modules(), "no documented python -m invocations found"

    def test_each_documented_module_imports_and_has_main(self) -> None:
        broken: list[str] = []
        for name in _documented_modules():
            try:
                module = importlib.import_module(name)
            except Exception as exc:  # noqa: BLE001 - report, do not stop at the first
                broken.append(f"{name}: import failed ({type(exc).__name__}: {exc})")
                continue
            if not callable(getattr(module, "main", None)):
                broken.append(f"{name}: no callable main()")
        assert broken == []

    def test_each_documented_module_has_a_source_file(self) -> None:
        """`python -m` needs an importable module, not just an importable name."""
        for name in _documented_modules():
            spec = importlib.util.find_spec(name)
            assert spec is not None, f"{name}: not importable as a module"
            assert spec.origin, f"{name}: no source file"


class TestSiblingModulesAgree:
    """The package's `main`-bearing modules are the only ones scripts may target."""

    def test_no_script_targets_a_private_module(self) -> None:
        for command, target in _scripts_block():
            module_name = target.partition(":")[0]
            leaf = module_name.rsplit(".", 1)[-1]
            assert not leaf.startswith("_"), f"{command}: private module {module_name}"
