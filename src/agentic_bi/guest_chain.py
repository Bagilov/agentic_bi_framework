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

The CLI entry point (`agentic-bi-guest-dashboard`) lives in `guest_chain_cli`.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from agentic_bi.guest_chain_build import run_build
from agentic_bi.guest_task_script import remove_script
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
        """Build from the environment (guest vars + optional VM id/data).

        Raises:
            ValueError: when `AGENTIC_BI_CHAIN_TIMEOUT` is not a positive whole
                number. A bare `int(...)` failure escaped `main` as a traceback,
                while the CLI contract for a bad value is exit 2 and one line;
                a zero or negative budget failed later in `Deadline` with the
                same traceback and a message that named neither the variable nor
                the value.
        """
        guest = GuestConfig.from_env()
        if guest is None:
            return None
        raw_timeout = os.environ.get("AGENTIC_BI_CHAIN_TIMEOUT", "1800")
        try:
            timeout = int(raw_timeout)
        except ValueError as exc:
            raise ValueError(
                f"AGENTIC_BI_CHAIN_TIMEOUT must be a whole number of seconds, "
                f"got {raw_timeout!r}"
            ) from exc
        if timeout <= 0:
            raise ValueError(
                f"AGENTIC_BI_CHAIN_TIMEOUT must be positive, got {timeout}"
            )
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
            timeout=timeout,
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
    # The guest path of *this* chain's own build, so a concurrent chain that
    # publishes the shared output name cannot swap the artifact being pulled.
    guest_build: str | None = None
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
            "guest_build": self.guest_build,
            "log": self.log,
        }


def _run_oracle(
    config: ChainConfig, local_pbix: Path, deadline: Deadline, result: ChainResult
) -> None:
    """Run the strict Desktop oracle and fold its verdict into `result`."""
    from agentic_bi.desktop_oracle_guest import run_oracle

    # `int()` of a remaining budget under one second is 0, and `Deadline(0)`
    # raises `ValueError`: the oracle was then reported as `ERROR:ValueError`
    # (verdict ORACLE_FAILED) instead of TIMEOUT, and the log named a Python
    # exception rather than the exhausted budget.
    budget = int(deadline.remaining)
    if budget < 1:
        result.record("oracle", "no budget left for the Desktop oracle")
        result.verdict = TIMEOUT
        return
    try:
        oracle = run_oracle(
            local_pbix,
            config=config.guest,
            dest_name=local_pbix.name,
            hold=config.oracle_hold,
            open_timeout=budget,
            timeout=budget,
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
        # Pull this run's own build: the shared `<out>\<name>` copy is published
        # for humans and is last-writer-wins between concurrent chains. A build
        # without its own path would silently fall back to that shared name, so
        # the invariant is explicit instead of re-opening the race.
        if result.guest_build is None:
            result.record(
                "stage", "FAILED: run_build reported a build without its own path"
            )
            result.verdict = STAGE_FAILED
            return result
        source = result.guest_build
        size = transport.pull_file(source, local_pbix, deadline)
        result.pbix = local_pbix
        result.bytes_written = size
        result.record("pull", f"{size} B -> {local_pbix}")
        result.verdict = BUILT
        try:
            transport.ps("$ErrorActionPreference='Stop'\n" + remove_script(source))
        except Exception:  # noqa: BLE001 - cleanup must not mask the verdict
            logger.warning("could not remove this run's guest build %s", source)

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
            # Teardown must not replace a finished verdict with a traceback: a
            # `utmctl` timeout raises `subprocess.TimeoutExpired`, and the CLI
            # only prints the result object. Log it and keep the verdict.
            try:
                stopped = transport.vm.stop()
            except Exception:
                logger.warning(
                    "could not stop the VM %s", config.vm_uuid, exc_info=True
                )
            else:
                if stopped:
                    result.record("vm", "stopped (started by this chain)")
                else:
                    result.record("vm", "stop was not confirmed by utmctl")


__all__ = [
    "BUILT",
    "NOT_BUILT",
    "ORACLE_FAILED",
    "STAGE_FAILED",
    "TIMEOUT",
    "ChainConfig",
    "ChainResult",
    "build_dashboard",
]


if __name__ == "__main__":
    from agentic_bi.guest_chain_cli import main as _main

    raise SystemExit(_main())
