"""Host-environment discovery and process plumbing for the engine pipeline.

`engine.EnginePipeline` is about *what* to build; this module is about *where* it
runs: locating Power BI Desktop, the Analysis Services workspace root, checking
that the engine port is alive, and running the PowerShell build / oracle scripts.

Nothing here is hardcoded to a machine: the Desktop executable, the workspace
root and the donor template are resolved from environment variables
(`PBI_RS_DESKTOP`, `PBI_RS_WS_ROOT`, `PBI_RS_TEMPLATE`) first, then from the
usual per-user locations.

Public API:
    PBI_RS                     - resolved Desktop executable (str)
    WS_ROOT                    - resolved AnalysisServicesWorkspaces root (Path)
    DEFAULT_TEMPLATE           - donor `.pbix` path (Path)
    default_desktop()          - resolve the Desktop executable
    ws_root()                  - resolve the workspace root
    port_alive(port)           - is something listening on 127.0.0.1:port
    kill_desktop()             - stop PBIDesktop/msmdsrv before a clean start
    wait_port(root, timeout)   - newest live engine port under `root`
    run_engine_build(ps1, spec_path, abf) -> str
    run_oracle(pbix, hold) -> str
"""

from __future__ import annotations

import logging
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

import agentic_bi.paths as paths

logger = logging.getLogger(__name__)

# Desktop executable and AS workspace root. Both prefer the RS build (the
# framework's historical target) and fall back to the regular Desktop, and can
# be pinned with PBI_RS_DESKTOP / PBI_RS_WS_ROOT.
_DESKTOP_SUBPATHS = (
    r"Microsoft Power BI Desktop RS\bin\PBIDesktop.exe",
    r"Microsoft Power BI Desktop\bin\PBIDesktop.exe",
)
_WS_DIRS = ("Power BI Desktop SSRS", "Power BI Desktop")

# The PowerShell build script and the oracle helper stay at the package root
# (declared in `[tool.setuptools.package-data]`), so resolve them from the
# package directory, not this subpackage.
_PKG_DIR = Path(__file__).resolve().parents[1]
ENGINE_PS1 = _PKG_DIR / "_engine_build.ps1"
ORACLE_PY = _PKG_DIR / "_engine_oracle.py"


def default_desktop() -> str:
    """Return the Power BI Desktop executable path (env > probe > RS default)."""
    env = os.environ.get("PBI_RS_DESKTOP")
    if env:
        return env
    for sub in _DESKTOP_SUBPATHS:
        exe = Path(r"C:\Program Files") / sub
        if exe.exists():
            return str(exe)
    return r"C:\Program Files\Microsoft Power BI Desktop RS\bin\PBIDesktop.exe"


def ws_root() -> Path:
    """Return the AnalysisServicesWorkspaces root (env > probe > SSRS default)."""
    env = os.environ.get("PBI_RS_WS_ROOT")
    if env:
        return Path(env)
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    base = local / "Microsoft"
    for name in _WS_DIRS:
        cand = base / name / "AnalysisServicesWorkspaces"
        if cand.exists():
            return cand
    return base / _WS_DIRS[0] / "AnalysisServicesWorkspaces"


PBI_RS = default_desktop()
WS_ROOT = ws_root()
DEFAULT_TEMPLATE = Path(os.environ.get("PBI_RS_TEMPLATE", "templates/template.pbix"))


def port_alive(port: int) -> bool:
    """True when something accepts TCP connections on `127.0.0.1:port`."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def kill_desktop() -> None:
    """Stop any running Desktop/engine so the next start is clean."""
    for img in ("PBIDesktop.exe", "msmdsrv.exe"):
        subprocess.run(["taskkill", "/F", "/IM", img], capture_output=True)
    time.sleep(4)


def wait_port(root: Path | None = None, timeout: int = 60) -> int:
    """Return the newest *live* engine port found under `root`.

    Raises:
        TimeoutError: when no live port shows up within `timeout` seconds.
    """
    root = root or ws_root()
    t0 = time.time()
    while time.time() - t0 < timeout:
        ws = sorted(root.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
        for w in ws:
            port_file = w / "Data" / "msmdsrv.port.txt"
            if not port_file.exists():
                continue
            try:
                port = int(port_file.read_text().replace("\x00", "").strip())
            except ValueError:
                continue
            # Skip stale workspaces whose port is no longer listening.
            if port_alive(port):
                return port
        time.sleep(1)
    raise TimeoutError(f"engine port not found under {root}")


def run_engine_build(spec_path: Path, abf: Path, port: int | None = None) -> str:
    """Run `_engine_build.ps1` (one retry) and return the console tail.

    `port` is the live engine port from `wait_port()`; passing it avoids a race in
    the script, which would otherwise re-derive the port from the newest workspace
    by mtime and could pick a just-closed workspace whose port is already dead.

    The engine does not always start on the first attempt, so a missing output is
    retried once before failing.

    Raises:
        RuntimeError: when the `.abf` output was not produced.
    """
    cmd = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(ENGINE_PS1),
        "-Spec",
        str(spec_path),
        "-Out",
        str(abf),
    ]
    if port:
        cmd += ["-Port", str(port)]
    proc = None
    for attempt in (1, 2):
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if abf.exists():
            return (proc.stdout or "")[-400:]
        if attempt == 1:
            time.sleep(15)
    logger.error("engine build failed: %s", (proc.stdout or "")[-400:])
    raise RuntimeError(
        f"engine build failed:\n{(proc.stdout or '')[-400:]}\n"
        f"{(proc.stderr or '')[-400:]}"
    )


def run_oracle(pbix: Path, hold: int) -> str:
    """Strict open check of `pbix` in Desktop RS; return the verdict token.

    The child runs from a scratch directory, not from the package: the oracle
    only reads the absolute `pbix` it is given, so its cwd must not be tied to
    where the source happens to live (a read-only install has no writable cwd).
    """
    proc = subprocess.run(
        [sys.executable, str(ORACLE_PY), str(pbix.resolve()), str(hold)],
        cwd=str(paths.scratch_dir("_run")),
        capture_output=True,
        text=True,
        timeout=hold + 120,
    )
    verdicts = re.findall(r"RESULT\s*\[([A-Z_]+)\]", proc.stdout + proc.stderr)
    return verdicts[-1] if verdicts else "NO_RESULT"
