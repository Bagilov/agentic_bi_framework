"""Run the strict Desktop oracle on a `.pbix` through a Windows guest.

On Apple Silicon there is no native Power BI Desktop, so the authoritative
"does Desktop actually open this report and attach the model" check runs in a
Windows VM (`_engine_oracle.py`). WinRM runs in session 0, where Desktop never
brings up the engine, so the oracle is launched as an **interactive** scheduled
task (session 1) and its log is polled over WinRM.

Connection, staging and task plumbing live in `guest_transport`; this module only
carries the oracle-specific configuration contract and the run loop.

Everything environment-specific is configuration, never hardcoded:

| Value | Env var | Example |
|---|---|---|
| Guest WinRM endpoint | `AGENTIC_BI_GUEST_WINRM` | `http://<guest-ip>:5985/wsman` |
| Guest user / password | `AGENTIC_BI_GUEST_USER` / `AGENTIC_BI_GUEST_PASSWORD` | `<user>` / `***` |
| WinRM transport | `AGENTIC_BI_GUEST_TRANSPORT` | `ntlm` (default) |
| Guest Python (embeddable) | `AGENTIC_BI_GUEST_PYTHON` | `C:\\pbi\\py\\python.exe` |
| Staged framework root | `AGENTIC_BI_GUEST_ROOT` | `C:\\pbi\\abf` |
| Scratch/output dir | `AGENTIC_BI_GUEST_OUT` | `C:\\pbi\\out` |

Public API:
    GuestConfig                       - re-exported from `guest_transport`
    GuestConfig.from_env() -> ... | None   (None when not configured)
    GuestConfig.available() -> bool
    run_oracle(pbix, *, config=None, dest_name=None, hold=90, open_timeout=240) -> OracleResult
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from agentic_bi.guest_task_script import remove_script, run_token
from agentic_bi.guest_transport import (
    Deadline,
    GuestConfig,
    WinRMTransport,
    ps_quote,
)

# Oracle verdicts (see `_engine_oracle.py`).
VERDICTS = ("MODEL_LOADED", "NOT_MODEL_LOADED", "CRASH", "NOENGINE", "UI_ERROR")

logger = logging.getLogger(__name__)

_TASK_NAME = "agentic_bi_oracle"

__all__ = ["VERDICTS", "GuestConfig", "OracleResult", "run_oracle"]


@dataclass
class OracleResult:
    """The oracle verdict for one `.pbix`, with the raw log."""

    pbix: str
    verdict: str
    log: str

    @property
    def loaded(self) -> bool:
        """True when Desktop attached the model (the pass condition)."""
        return self.verdict == "MODEL_LOADED"


def _oracle_script(config: GuestConfig, dest: str, hold: int, open_timeout: int) -> str:
    """The interactive-task body that runs `_engine_oracle.py`.

    `dest` derives from the `.pbix` file name, which is not necessarily
    operator-controlled, so every value is rendered with `ps_quote`: a quote in a
    file name would otherwise close the literal and inject a statement into the
    highest-privilege interactive task.

    The body does **not** write the log. The task runner is the single owner of
    that file and captures this child's stdout and stderr; a second `Out-File`
    on the same path was refused by the runner's open handle (`FileShare.Read`),
    and for the oracle that was fatal: the `RESULT [VERDICT]` line never reached
    the log, so `_parse_verdict` returned None and `run_oracle` raised "no oracle
    verdict". `2>&1` stays, so native stderr still reaches the runner's redirect.
    """
    env_lines = [f"$env:PBI_RS_ORACLE_OPEN_TIMEOUT = {ps_quote(open_timeout)}"]
    if config.desktop:
        env_lines.append(f"$env:PBI_RS_DESKTOP = {ps_quote(config.desktop)}")
    if config.ws_root:
        env_lines.append(f"$env:PBI_RS_WS_ROOT = {ps_quote(config.ws_root)}")
    oracle = f"{config.root}\\src\\agentic_bi\\_engine_oracle.py"
    return (
        "\n".join(env_lines)
        + "\n"
        + f"& {ps_quote(config.python)} {ps_quote(oracle)} {ps_quote(dest)} {int(hold)} "
        "2>&1\n"
    )


def run_oracle(
    pbix: Path,
    *,
    config: GuestConfig | None = None,
    dest_name: str | None = None,
    hold: int = 90,
    open_timeout: int = 240,
    timeout: int = 900,
) -> OracleResult:
    """Upload `pbix` to the guest and return the strict Desktop oracle verdict.

    Args:
        pbix: the local `.pbix` to test.
        config: guest config; defaults to `GuestConfig.from_env()`.
        dest_name: file name on the guest (defaults to the local name).
        hold: seconds the model must stay attached.
        open_timeout: workspace-detection ceiling (cold ARM launch is slow).
        timeout: overall wall-clock ceiling for polling the verdict.

    Returns:
        OracleResult with the verdict and the raw oracle log.

    Raises:
        RuntimeError: when the guest is not configured or no verdict appears.
        ChainTimeout: when the verdict does not appear within `timeout`.
    """
    config = config or GuestConfig.from_env()
    if config is None:
        raise RuntimeError(
            "Windows guest not configured; set AGENTIC_BI_GUEST_WINRM, "
            "AGENTIC_BI_GUEST_USER and AGENTIC_BI_GUEST_PASSWORD"
        )
    pbix = Path(pbix)
    uploaded = dest_name or pbix.name
    # A per-run destination: two concurrent oracle runs on the same `.pbix` used
    # to upload onto one shared guest file, so one run could open the other's
    # half-written copy. The log and marker are per-run inside `run_task`.
    dest = f"{config.out}\\{Path(uploaded).stem}.{run_token()}.pbix"
    deadline = Deadline(timeout)
    transport = WinRMTransport(config)
    try:
        # `[IO.Directory]::CreateDirectory` instead of `New-Item -Path`: the raw
        # `-Path` here expanded `[`, `]` and `*` from the configured out dir as a
        # wildcard pattern, and `New-Item` itself is not the right tool on Windows
        # PowerShell 5.1. `CreateDirectory` is idempotent and has no wildcards.
        transport.ps(
            "$ErrorActionPreference='Stop'\n"
            f"[IO.Directory]::CreateDirectory({ps_quote(config.out)}) | Out-Null"
        )
        transport.push_file(pbix, dest, deadline)
        log, code = transport.run_task(
            name=_TASK_NAME,
            script=_oracle_script(config, dest, hold, open_timeout),
            deadline=deadline,
            poll=15.0,
            limit_min=15,
        )
    finally:
        # The uploaded copy is this run's own input; nothing reads it after the
        # verdict, so it is removed even when the task failed (the log, which is
        # the failure evidence, is kept by `run_task`). A whole `.pbix` per run
        # otherwise accumulates in the guest's output directory.
        try:
            transport.ps("$ErrorActionPreference='Stop'\n" + remove_script(dest))
        except Exception:  # noqa: BLE001 - cleanup must not mask the verdict
            logger.warning("could not remove the uploaded oracle copy %s", dest)
        finally:
            transport.close()
    if code != 0:
        raise RuntimeError(f"oracle task exited {code}; log:\n{log}")

    verdict = _parse_verdict(log)
    if verdict is None:
        raise RuntimeError(f"no oracle verdict within {timeout}s; log:\n{log}")
    return OracleResult(pbix=str(pbix), verdict=verdict, log=log)


def _parse_verdict(log: str) -> str | None:
    """Extract the last `RESULT [VERDICT]` from the oracle log."""
    last = None
    for line in log.splitlines():
        if "RESULT [" in line:
            inner = line.split("RESULT [", 1)[1].split("]", 1)[0].strip()
            if inner in VERDICTS:
                last = inner
    return last
