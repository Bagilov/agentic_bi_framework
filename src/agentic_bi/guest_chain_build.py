"""Guest build stage: stage the framework, run the builder, fetch the result.

The chain's middle stage, separated from the orchestrator so the verdict logic
stays readable. It owns the framework zip layout, the builder command line, and
the guest-side build invocation, but not the VM lifecycle or the oracle.

Public API:
    stage_framework(repo, dest_zip)      - zip the runtime pieces at archive root
    build_script(cfg, guest_pbix, log)   - the interactive-task body
    run_build(transport, cfg, deadline, result) -> bool
    tail(text, limit)                    - last characters, single-lined
"""

from __future__ import annotations

import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

from agentic_bi.guest_transport import Deadline, ps_quote

if TYPE_CHECKING:  # avoid a runtime cycle with the orchestrator
    from agentic_bi.guest_chain import ChainConfig, ChainResult
    from agentic_bi.guest_transport import GuestConfig, WinRMTransport

_TASK = "agentic_bi_board"
_RUNTIME = ("src", "examples", "templates", "pyproject.toml", "README.md")


def _register_on_path(guest: GuestConfig) -> str:
    """The PowerShell that puts `<root>\\src` on the embeddable interpreter's path.

    The `._pth` file sits next to the configured interpreter and the appended
    entry is the configured root, so overriding `AGENTIC_BI_GUEST_ROOT` or
    `AGENTIC_BI_GUEST_PYTHON` stays consistent (a hardcoded path here would keep
    pointing at the default root while the framework is staged elsewhere).

    The guest paths are Windows paths and the host may be macOS, so the
    interpreter directory is split on `\\` rather than with `pathlib` (whose
    separators are host-specific).
    """
    py_dir = guest.python.rsplit("\\", 1)[0] if "\\" in guest.python else guest.python
    pth = f"{py_dir}\\python312._pth"
    src = f"{guest.root}\\src"
    return (
        f"$pth={ps_quote(pth)}\n"
        f"if (-not (Select-String -Path $pth -Pattern {ps_quote(src)} -Quiet)) "
        f"{{ Add-Content $pth {ps_quote(src)} }}\n"
    )


def tail(text: str, limit: int = 600) -> str:
    """The last `limit` characters of `text`, single-lined for the log."""
    flat = " ".join(text.split())
    return flat[-limit:]


def stage_framework(repo: Path, dest_zip: Path) -> None:
    """Zip the runtime pieces of `repo` at the archive root (no nesting level)."""
    repo = Path(repo)
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in _RUNTIME:
            src = repo / name
            if src.is_file():
                zf.write(src, name)
                continue
            for path in sorted(src.rglob("*")):
                if "__pycache__" in path.parts or path.suffix == ".pyc":
                    continue
                if path.is_file():
                    zf.write(path, str(path.relative_to(repo)))


def build_script(cfg: ChainConfig, guest_pbix: str, log_path: str) -> str:
    """The interactive-task body: run the builder and log its output.

    Every interpolated value is rendered with `ps_quote`, so a builder name,
    table, title or path containing a quote cannot break out of its literal and
    inject a statement into the highest-privilege interactive task.

    Completion is signalled by the marker file the runner writes afterwards, not
    by a string in this log (see `WinRMTransport.run_task` for why).
    """
    guest = cfg.guest
    root = guest.root
    bin_dir = r"C:\Program Files\Microsoft Power BI Desktop\bin"
    template = f"{root}\\templates\\template.pbix"
    src = f"{root}\\src"
    builder_path = f"{root}\\examples\\{cfg.builder}"
    data_path = f"{root}\\examples\\{Path(cfg.data).name}"
    title_flag = f" --title {ps_quote(cfg.title)}" if cfg.title else ""
    return (
        "$ErrorActionPreference='Continue'\n"
        f"$env:PBI_RS_BIN={ps_quote(bin_dir)}\n"
        f"$env:PBI_RS_TEMPLATE={ps_quote(template)}\n"
        f"$env:PYTHONPATH={ps_quote(src)}\n"
        f"& {ps_quote(guest.python)} {ps_quote(builder_path)} "
        f"--data {ps_quote(data_path)} "
        f"--table {ps_quote(cfg.table)} "
        f"--template {ps_quote(template)} "
        f"--out {ps_quote(guest_pbix)}{title_flag} *> {ps_quote(log_path)}\n"
    )


def run_build(
    transport: WinRMTransport,
    cfg: ChainConfig,
    deadline: Deadline,
    result: ChainResult,
) -> bool:
    """Stage the framework, run the build task; True only on exit 0 + a new file.

    The build's own exit code is authoritative: a non-zero code is a failure even
    when a `.pbix` of the right name exists, because the output is deleted before
    the task starts so an earlier run's artifact cannot be mistaken for this one's.
    """
    tmp = Path(tempfile.mkdtemp(prefix="abf-chain-"))
    try:
        guest = cfg.guest
        transport.ps(
            f"New-Item -ItemType Directory -Force -Path {ps_quote(guest.out)} "
            "| Out-Null"
        )
        zip_path = tmp / "abf.zip"
        stage_framework(cfg.repo, zip_path)
        entries = len(zipfile.ZipFile(zip_path).namelist())
        result.record(
            "stage", f"framework {zip_path.stat().st_size} B, {entries} files"
        )

        guest_zip = f"{guest.out}\\abf.zip"
        transport.push_file(zip_path, guest_zip, deadline)
        files = transport.extract_zip(guest_zip, guest.root, expected=entries)
        transport.ps(_register_on_path(guest))
        result.record("stage", f"framework extracted on guest ({files} files)")

        guest_pbix = f"{guest.out}\\{cfg.out.name}"
        log_path = f"{guest.out}\\{_TASK}.log"
        marker_path = f"{guest.out}\\{_TASK}.done"
        transport.push_file(
            Path(cfg.data).resolve(),
            f"{guest.root}\\examples\\{Path(cfg.data).name}",
            deadline,
        )
        log, code = transport.run_task(
            name=_TASK,
            script=build_script(cfg, guest_pbix, log_path),
            log_path=log_path,
            marker_path=marker_path,
            files_before=f"Remove-Item {ps_quote(guest_pbix)} -Force -EA SilentlyContinue",
            deadline=deadline,
        )
        result.record("build", f"exit={code} {tail(log)}")
        if code != 0:
            return False
        size = transport.ps(
            f"if (Test-Path {ps_quote(guest_pbix)}) "
            f"{{ (Get-Item {ps_quote(guest_pbix)}).Length }} else {{ 0 }}"
        )
        if not int((size.strip().splitlines() or ["0"])[-1]):
            result.record("build", "exit 0 but no .pbix produced")
            return False
        return True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


__all__ = ["build_script", "run_build", "stage_framework", "tail"]
