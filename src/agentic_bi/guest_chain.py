"""Terminating chain: build a test dashboard in the Windows guest, end to end.

A single bounded call turns "make a test dashboard" into finished artifacts: it
brings the VM up, stages the framework, runs the engine build **in the guest's
interactive session** (Desktop brings up its AS engine only in session 1), pulls
the `.pbix` back to the host, optionally runs the strict Desktop oracle, and
always tears everything down — the interactive task is unregistered and the VM is
stopped only if this chain is what started it.

Nothing can hang: every stage shares one `Deadline`, and every stage's teardown
runs in a `finally`, so the process returns one verdict and never leaves a
registered task or a leaked HTTP server behind. Environment-specific values
(guest endpoint, VM id, paths) are configuration, never hardcoded.

The staging/build mechanics live in `guest_chain_build`; this module owns the
configuration, the verdict and the CLI.

Public API:
    ChainConfig.from_env()            - guest + build configuration
    ChainResult                       - verdict, artifacts and the stage log
    build_dashboard(config) -> ChainResult
    main(argv) -> int                 - CLI (`agentic-bi-guest-dashboard`)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from agentic_bi.guest_chain_build import run_build
from agentic_bi.guest_transport import (
    ChainTimeout,
    Deadline,
    GuestConfig,
    StageError,
    WinRMTransport,
)

logger = logging.getLogger(__name__)

# Chain outcome tokens (the process always ends on exactly one of these).
BUILT = "BUILT"
NOT_BUILT = "NOT_BUILT"
STAGE_FAILED = "STAGE_FAILED"
ORACLE_FAILED = "ORACLE_FAILED"
TIMEOUT = "TIMEOUT"


@dataclass
class ChainConfig:
    """Everything the chain needs: the guest plus the build request."""

    guest: GuestConfig
    data: Path
    table: str
    out: Path
    repo: Path = field(default_factory=lambda: Path.cwd())
    vm_uuid: str | None = None
    builder: str = "engine_table_board.py"
    timeout: int = 1800
    oracle: bool = False
    oracle_hold: int = 90
    stop_vm_on_exit: bool = True
    title: str | None = None

    @classmethod
    def from_env(cls) -> ChainConfig | None:
        """Build from the environment (guest vars + optional VM id/data)."""
        guest = GuestConfig.from_env()
        if guest is None:
            return None
        repo = Path(os.environ.get("AGENTIC_BI_REPO", Path.cwd())).resolve()
        return cls(
            guest=guest,
            data=Path(
                os.environ.get(
                    "AGENTIC_BI_DATA", repo / "examples" / "engine_sales.csv"
                )
            ),
            table=os.environ.get("AGENTIC_BI_TABLE", "Sales"),
            out=Path(
                os.environ.get(
                    "AGENTIC_BI_OUT", repo / "output_files" / "guest_board.pbix"
                )
            ),
            repo=repo,
            vm_uuid=os.environ.get("AGENTIC_BI_VM_UUID"),
            builder=os.environ.get("AGENTIC_BI_BUILDER", "engine_table_board.py"),
            timeout=int(os.environ.get("AGENTIC_BI_CHAIN_TIMEOUT", "1800")),
            oracle=os.environ.get("AGENTIC_BI_ORACLE", "") not in ("", "0", "false"),
            title=os.environ.get("AGENTIC_BI_TITLE"),
        )


@dataclass
class ChainResult:
    """The chain's single verdict, with artifacts and a per-stage log."""

    verdict: str
    pbix: Path | None = None
    bytes_written: int = 0
    oracle: str | None = None
    log: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True only when the board was built and (when enabled) opened in Desktop."""
        if self.verdict == BUILT:
            return self.oracle in (None, "MODEL_LOADED")
        return False

    def record(self, stage: str, detail: str) -> None:
        """Append one stage line to the log."""
        self.log.append(f"{stage}: {detail}")

    def as_dict(self) -> dict:
        """A JSON-friendly summary."""
        return {
            "verdict": self.verdict,
            "ok": self.ok,
            "pbix": str(self.pbix) if self.pbix else None,
            "bytes": self.bytes_written,
            "oracle": self.oracle,
            "log": self.log,
        }


def _run_oracle(
    config: ChainConfig, local_pbix: Path, deadline: Deadline, result: ChainResult
) -> None:
    """Run the strict Desktop oracle and fold its verdict into `result`."""
    from agentic_bi.desktop_oracle_guest import run_oracle

    try:
        oracle = run_oracle(
            local_pbix,
            config=config.guest,
            dest_name=local_pbix.name,
            hold=config.oracle_hold,
            open_timeout=int(deadline.remaining),
            timeout=int(deadline.remaining),
        )
        result.oracle = oracle.verdict
        result.record("oracle", oracle.verdict)
        if not oracle.loaded:
            result.verdict = ORACLE_FAILED
    except Exception as exc:  # noqa: BLE001 - oracle failure is a verdict
        result.oracle = f"ERROR:{type(exc).__name__}"
        result.record("oracle", f"{type(exc).__name__}: {exc}")
        result.verdict = ORACLE_FAILED


def build_dashboard(config: ChainConfig | None = None) -> ChainResult:
    """Run the whole chain once and return a single verdict; always terminates.

    Args:
        config: chain configuration; defaults to `ChainConfig.from_env()`.

    Returns:
        ChainResult whose `verdict` is one of BUILT / NOT_BUILT /
        ORACLE_FAILED / TIMEOUT. `log` carries per-stage detail.
    """
    config = config or ChainConfig.from_env()
    if config is None:
        raise RuntimeError(
            "guest not configured; set AGENTIC_BI_GUEST_WINRM, "
            "AGENTIC_BI_GUEST_USER and AGENTIC_BI_GUEST_PASSWORD"
        )
    deadline = Deadline(config.timeout)
    result = ChainResult(verdict=TIMEOUT)
    transport = WinRMTransport(config.guest, vm_uuid=config.vm_uuid)
    try:
        note = transport.ensure_vm(deadline)
        result.record("vm", note)
        try:
            built = run_build(transport, config, deadline, result)
        except ChainTimeout as exc:
            result.record("timeout", str(exc))
            result.verdict = TIMEOUT
            return result
        except StageError as exc:
            result.record("stage", f"FAILED: {exc}")
            result.verdict = STAGE_FAILED
            return result
        if not built:
            result.verdict = NOT_BUILT
            return result

        local_pbix = Path(config.out).resolve()
        size = transport.pull_file(
            f"{config.guest.out}\\{local_pbix.name}", local_pbix, deadline
        )
        result.pbix = local_pbix
        result.bytes_written = size
        result.record("pull", f"{size} B -> {local_pbix}")
        result.verdict = BUILT

        if config.oracle:
            _run_oracle(config, local_pbix, deadline, result)
        return result
    except ChainTimeout as exc:
        result.record("timeout", str(exc))
        result.verdict = TIMEOUT
        return result
    except Exception as exc:  # noqa: BLE001 - the chain always ends on a verdict
        result.record("error", f"{type(exc).__name__}: {exc}")
        result.verdict = STAGE_FAILED
        return result
    finally:
        transport.close()
        if config.stop_vm_on_exit and transport.started_vm:
            transport.vm.stop()
            result.record("vm", "stopped (started by this chain)")


if __name__ == "__main__":
    from agentic_bi.guest_chain_cli import main as _main

    raise SystemExit(_main())
