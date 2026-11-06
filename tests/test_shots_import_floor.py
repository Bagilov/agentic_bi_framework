"""`shots` must import on Python 3.10, which has no `tomllib`.

The package floor is 3.10 (`requires-python = ">=3.10"`) and `tomli` is the
documented back-port, but it is only pulled in by the `dev` extra. An unguarded
`import tomllib` in `shots_validation` made `import agentic_bi.shots` raise
`ModuleNotFoundError` on the 3.10 CI leg, which took every `test_shots*` module
down at collection. The check runs in a subprocess with `tomllib` blocked, the
only way to exercise the fallback on a newer interpreter.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"

_SCRIPT = """
import sys


class _BlockTomllib:
    def find_spec(self, name, path, target=None):
        if name == "tomllib":
            raise ModuleNotFoundError("No module named 'tomllib'")
        return None


sys.meta_path.insert(0, _BlockTomllib())
import agentic_bi.shots
from agentic_bi.shots import ShotPlan

plan = ShotPlan.from_dict({"figures": [{"name": "a", "source": "a.html"}]})
assert plan.figures[0].name == "a"
print("ok")
"""


def test_package_imports_and_parses_a_plan_without_tomllib() -> None:
    env = {**os.environ, "PYTHONPATH": str(_SRC)}
    result = subprocess.run(
        [sys.executable, "-c", _SCRIPT],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
