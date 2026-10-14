"""Run the strict Desktop oracle on a `.pbix` through a Windows guest.

On Apple Silicon there is no native Power BI Desktop, so the authoritative
"does Desktop actually open this report and attach the model" check runs in a
Windows VM (`_engine_oracle.py`). WinRM runs in session 0, where Desktop never
brings up the engine, so the oracle is launched as an **interactive** scheduled
task (session 1) and its log is polled over WinRM.

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
    GuestConfig.from_env() -> GuestConfig | None   (None when not configured)
    GuestConfig.available() -> bool
    run_oracle(pbix, *, config=None, dest_name=None, hold=90, open_timeout=240) -> OracleResult

`run_oracle` serves the file from an ephemeral host HTTP server bound to the
interface the guest can reach, has the guest fetch it with `Invoke-WebRequest`,
runs the oracle in an interactive task and returns the verdict.

Note on transport: a `.pbix` cannot be pushed inline over WinRM. Long
`-encodedcommand` payloads are silently truncated by the guest's command-line
limit, and base64 chunking via `Add-Content` hits the same wall. The reliable
path (also used in `docs/DEVELOPMENT_MACOS.md`) is host HTTP -> guest fetch.
"""

from __future__ import annotations

import functools
import http.server
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Oracle verdicts (see `_engine_oracle.py`).
VERDICTS = ("MODEL_LOADED", "NOT_MODEL_LOADED", "CRASH", "NOENGINE", "UI_ERROR")

_TASK_NAME = "agentic_bi_oracle"


@dataclass(frozen=True)
class GuestConfig:
    """Where and how to reach the Windows guest that runs the oracle."""

    winrm: str
    user: str
    password: str
    transport: str = "ntlm"
    python: str = r"C:\pbi\py\python.exe"
    root: str = r"C:\pbi\abf"
    out: str = r"C:\pbi\out"
    desktop: str | None = None
    ws_root: str | None = None

    @classmethod
    def from_env(cls) -> GuestConfig | None:
        """Build the config from the environment, or None when unset."""
        endpoint = os.environ.get("AGENTIC_BI_GUEST_WINRM")
        user = os.environ.get("AGENTIC_BI_GUEST_USER")
        password = os.environ.get("AGENTIC_BI_GUEST_PASSWORD")
        if not (endpoint and user and password):
            return None
        return cls(
            winrm=endpoint,
            user=user,
            password=password,
            transport=os.environ.get("AGENTIC_BI_GUEST_TRANSPORT", "ntlm"),
            python=os.environ.get("AGENTIC_BI_GUEST_PYTHON", cls.python),
            root=os.environ.get("AGENTIC_BI_GUEST_ROOT", cls.root),
            out=os.environ.get("AGENTIC_BI_GUEST_OUT", cls.out),
            desktop=os.environ.get("PBI_RS_DESKTOP"),
            ws_root=os.environ.get("PBI_RS_WS_ROOT"),
        )

    @staticmethod
    def available() -> bool:
        """True when the guest is configured via the environment."""
        return GuestConfig.from_env() is not None


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


def _session(config: GuestConfig):
    import winrm  # optional dependency, imported lazily

    # Bound every WinRM round trip so a stalled read cannot hang the stage; the
    # operation timeout must exceed a single PowerShell invocation.
    return winrm.Session(
        config.winrm,
        auth=(config.user, config.password),
        transport=config.transport,
        operation_timeout_sec=60,
        read_timeout_sec=90,
    )


def _run_ps(session, script: str) -> str:
    result = session.run_ps(script)
    return result.std_out.decode("utf-8", "replace")


def _host_reachable_ip(config: GuestConfig) -> str:
    """The host IP the guest should fetch from (gateway of the guest's subnet).

    Overridable with `AGENTIC_BI_HOST_IP` when the guest reaches the host by a
    different address (bridged/host-only networks, port forwarding).
    """
    explicit = os.environ.get("AGENTIC_BI_HOST_IP")
    if explicit:
        return explicit
    # WinRM host:port -> derive the gateway as the same first three octets + ".1".
    host = config.winrm.split("//", 1)[-1].split(":", 1)[0]
    parts = host.split(".")
    if len(parts) == 4:
        return ".".join(parts[:3] + ["1"])
    return host


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    """A directory server that does not log each request to stderr."""

    def log_message(self, *args, **kwargs) -> None:  # noqa: D102
        return


def _serve_directory(directory: Path) -> tuple[http.server.ThreadingHTTPServer, str]:
    """Start a host HTTP server for `directory`; return (server, base_url)."""
    handler = functools.partial(_QuietHandler, directory=str(directory))
    server = http.server.ThreadingHTTPServer(("0.0.0.0", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    return server, f"{port}"


def _fetch_via_host(config: GuestConfig, session, pbix: Path, dest: str) -> None:
    """Serve `pbix` from the host and have the guest fetch it to `dest`.

    Replaces the unreliable inline-WinRM upload: the guest pulls the file over
    HTTP from the host address it can already reach (its gateway / WinRM host).
    """
    server, port = _serve_directory(pbix.parent)
    try:
        host_ip = _host_reachable_ip(config)
        url = f"http://{host_ip}:{port}/{pbix.name}"
        _run_ps(
            session,
            "$ErrorActionPreference = 'Stop'\n"
            f"Invoke-WebRequest -UseBasicParsing -TimeoutSec 60 '{url}' "
            f"-OutFile '{dest}'\n"
            f"\"fetched {dest} \" + (Get-Item '{dest}').Length\n",
        )
    finally:
        server.shutdown()
        server.server_close()


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
    """
    config = config or GuestConfig.from_env()
    if config is None:
        raise RuntimeError(
            "Windows guest not configured; set AGENTIC_BI_GUEST_WINRM, "
            "AGENTIC_BI_GUEST_USER and AGENTIC_BI_GUEST_PASSWORD"
        )
    pbix = Path(pbix)
    dest = f"{config.out}\\{dest_name or pbix.name}"

    session = _session(config)
    _run_ps(
        session, f"New-Item -ItemType Directory -Force -Path '{config.out}' | Out-Null"
    )
    _fetch_via_host(config, session, pbix, dest)

    env_lines = [f'$env:PBI_RS_ORACLE_OPEN_TIMEOUT = "{open_timeout}"']
    if config.desktop:
        env_lines.append(f'$env:PBI_RS_DESKTOP = "{config.desktop}"')
    if config.ws_root:
        env_lines.append(f'$env:PBI_RS_WS_ROOT = "{config.ws_root}"')
    env_block = "\n".join(env_lines)

    log_file = f"{config.out}\\oracle_{pbix.stem}.log"
    script = (
        f"$log = '{log_file}'\n"
        f"Remove-Item $log -Force -ErrorAction SilentlyContinue\n"
        f"{env_block}\n"
        f"& '{config.python}' '{config.root}\\src\\agentic_bi\\_engine_oracle.py' "
        f"'{dest}' {hold} *> $log\n"
        '"=== done ===" | Out-File -Encoding utf8 -Append $log\n'
    )
    runner = f"{config.out}\\oracle_{pbix.stem}.ps1"
    _run_ps(
        session, f"Set-Content -Path '{runner}' -Value @'\n{script}\n'@ -Encoding utf8"
    )

    task_ps = (
        f"Unregister-ScheduledTask -TaskName '{_TASK_NAME}' -Confirm:$false "
        "-ErrorAction SilentlyContinue\n"
        f"$act = New-ScheduledTaskAction -Execute 'powershell.exe' "
        f"-Argument '-NoProfile -ExecutionPolicy Bypass -File \"{runner}\"'\n"
        f"$pr = New-ScheduledTaskPrincipal -UserId $env:USERNAME "
        "-LogonType Interactive -RunLevel Highest\n"
        f"$set = New-ScheduledTaskSettingsSet "
        "-ExecutionTimeLimit (New-TimeSpan -Minutes 15)\n"
        f"Register-ScheduledTask -TaskName '{_TASK_NAME}' -Action $act "
        "-Principal $pr -Settings $set -Force | Out-Null\n"
        f"Start-ScheduledTask -TaskName '{_TASK_NAME}'\n"
    )
    _run_ps(session, task_ps)

    log = ""
    deadline = time.time() + timeout
    while time.time() < deadline:
        log = _run_ps(
            session,
            f"if (Test-Path '{log_file}') {{ Get-Content '" + log_file + "' -Raw }",
        )
        if "=== done ===" in log:
            break
        time.sleep(15)
    _run_ps(
        session,
        f"Unregister-ScheduledTask -TaskName '{_TASK_NAME}' "
        "-Confirm:$false -ErrorAction SilentlyContinue",
    )

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
