"""Bounded WinRM channel to the Windows guest: session, retries and readiness.

The guest is a UTM VM that may be booting, restarting, or whose engine holds
files open, so a one-shot call is never a readiness signal. This channel keeps a
single lazily-opened WinRM session, retries transient transport faults with a
fresh session, and exposes the small text helpers built on top of it. Every
script passes through `ps`, which refuses one whose `-EncodedCommand` payload
would exceed `MAX_ENCODED_COMMAND` instead of letting the guest truncate it.

Public API:
    new_session(config)   - one bounded WinRM session
    run_ps(session, s)    - decoded stdout of a PowerShell script
    WinRMChannel          - `session`, `ps`, `winrm_ready`, `ensure_vm`,
                            `write_text`, `read_text`
"""

from __future__ import annotations

import logging
import time

from agentic_bi.guest_types import (
    ChainTimeout,
    Deadline,
    GuestConfig,
    StageError,
    ps_quote,
)
from agentic_bi.guest_vm import VMController
from agentic_bi.guest_winrm_commands import (
    BOM_BYTES,
    check_size,
    chunk_budget,
    parent_dir,
    replace_script,
    split_payload,
    write_chunk_script,
)

logger = logging.getLogger(__name__)


def new_session(config: GuestConfig):
    """Open a bounded WinRM session (the timeouts stop a stalled read hanging)."""
    import winrm  # optional dependency, imported lazily

    return winrm.Session(
        config.winrm,
        auth=(config.user, config.password),
        transport=config.transport,
        operation_timeout_sec=60,
        read_timeout_sec=90,
    )


def _one_line(text: str, limit: int = 300) -> str:
    """Collapse whitespace and keep at most `limit` of the tail for an error."""
    flat = " ".join(text.split())
    return flat[-limit:] if len(flat) > limit else flat


def run_ps(session, script: str) -> str:
    """Run a PowerShell script over WinRM and return its decoded stdout.

    A non-zero exit status means the script failed (an unhandled terminating
    error, or an explicit `exit 1`). `winrm` reports that in `status_code`, not in
    the return value, so it is checked here: returning the stdout anyway would let
    a failed `Get-FileHash`, `Expand-Archive` or `Set-Content` look like a success
    and mask the fault until much later. Benign, locally-suppressed errors
    (`-EA SilentlyContinue`) keep the status at 0 and are unaffected.

    Raises:
        StageError: when the script exits non-zero; `std_err` is included.
    """
    result = session.run_ps(script)
    out = result.std_out.decode("utf-8", "replace")
    if result.status_code:
        err = result.std_err.decode("utf-8", "replace").strip()
        raise StageError(
            f"PowerShell failed (exit {result.status_code}): "
            f"{_one_line(err) or _one_line(out) or '<no output>'}"
        )
    return out


def _transient_errors() -> tuple[type[BaseException], ...]:
    """Exception types worth retrying: a booting/restarted guest drops NTLM.

    Right after the VM comes up, WinRM can accept a shell and then fail the NTLM
    handshake ("did not respond with NTLM challenge token"), so a single attempt is
    not a reliable readiness signal. `winrm` is optional, so its error classes are
    looked up lazily and folded in when present.
    """
    errors: list[type[BaseException]] = [PermissionError, OSError, TimeoutError]
    try:
        import winrm.exceptions as wx

        errors += [
            wx.WinRMTransportError,
            wx.WSManFaultError,
            wx.InvalidCredentialsError,
        ]
    except Exception:  # noqa: BLE001 - winrm is an optional dependency
        pass
    return tuple(errors)


class WinRMChannel:
    """A bounded, retrying WinRM channel with a lazily-opened session."""

    def __init__(self, config: GuestConfig, *, vm_uuid: str | None = None) -> None:
        self.config = config
        self.vm = VMController(vm_uuid)
        self.started_vm = False
        self._session = None

    def session(self):
        """The lazily-opened WinRM session."""
        if self._session is None:
            self._session = new_session(self.config)
        return self._session

    def ps(self, script: str, *, attempts: int = 4) -> str:
        """Run a PowerShell script, retrying transient guest/transport failures.

        A freshly booted (or restarted) guest can accept a WinRM shell yet fail the
        NTLM handshake, so a one-shot call is not a reliable readiness signal. Each
        retry drops the cached session and backs off briefly.

        The size guard runs before the first attempt and is not retried: an
        oversized command fails identically every time, and the guest would have
        run a truncated script instead of raising.

        Raises:
            StageError: when the encoded command exceeds `MAX_ENCODED_COMMAND`.
        """
        check_size(script)
        errors = _transient_errors()
        last: BaseException | None = None
        for attempt in range(1, attempts + 1):
            try:
                return run_ps(self.session(), script)
            except errors as exc:
                last = exc
                logger.debug("ps attempt %d/%d failed: %s", attempt, attempts, exc)
                self._session = None
                if attempt < attempts:
                    time.sleep(min(2.0 * attempt, 8.0))
        raise last  # type: ignore[misc]  # the loop always sets it before falling out

    def winrm_ready(self, deadline: Deadline) -> bool:
        """True once two consecutive probes succeed within `deadline`.

        A single success is not enough right after a boot: WinRM can answer once and
        then fail the next NTLM handshake while the service stabilizes, so readiness
        requires the answer to hold across a short gap.
        """
        while not deadline.expired:
            try:
                self.ps("Write-Output ok", attempts=1)
                time.sleep(deadline.slice(3.0))
                self.ps("Write-Output ok", attempts=1)
                return True
            except Exception as exc:  # noqa: BLE001 - the guest may still be booting
                logger.debug("winrm not ready: %s", exc)
                time.sleep(deadline.slice(5.0))
        return False

    def ensure_vm(self, deadline: Deadline) -> str:
        """Ensure the VM is up and WinRM answers; return a human note.

        Raises:
            ChainTimeout: when WinRM never becomes ready within `deadline`.
        """
        note = "vm control not configured"
        if self.vm.configured:
            if self.vm.status() != "started":
                self.started_vm = True
                self.vm.start()
            note = f"vm {self.vm.status()}"
        if not self.winrm_ready(deadline):
            raise ChainTimeout("vm: WinRM did not become ready")
        return note

    @staticmethod
    def _chunks(data: bytes, budget: int) -> list[bytes]:
        """Split encoded UTF-8 `data`; the rules live in `split_payload`."""
        return split_payload(data, budget)

    def _discard(self, quoted_tmp: str) -> None:
        """Best-effort removal of a half-written temp file; never raises."""
        try:
            self.ps(
                "$ErrorActionPreference='Stop'\n"
                f"if (Test-Path -LiteralPath {quoted_tmp}) "
                f"{{ Remove-Item -LiteralPath {quoted_tmp} -Force }}\n"
            )
        except Exception:  # noqa: BLE001 - the original write error is what matters
            logger.warning("could not discard the partial write %s", quoted_tmp)

    def write_text(self, guest_path: str, text: str) -> None:
        """Write `text` to `guest_path` as UTF-8: atomically, in small chunks.

        Chunking is required, not cosmetic: a single base64 blob for a script of
        a couple of kilobytes already exceeds the guest's encoded-command limit
        and the write fails with "The command line is too long". The path is
        `ps_quote`d as usual.

        **The first chunk carries a UTF-8 BOM, and only the first one.** Windows
        PowerShell 5.1 reads a `-File` script as ANSI (the current code page)
        unless it starts with a BOM, so a Cyrillic title or path in the payload
        was silently mangled while the `.pbix` was still built. Later chunks must
        not repeat the BOM (`Add-Content -Encoding UTF8` writes one on *every*
        call, which put U+FEFF in the middle of the source and broke parsing), so
        they append with a preamble-less `UTF8Encoding`.

        The content goes to `<path>.tmp` and is moved onto `<path>` at the end, so
        a write that dies half-way cannot leave a truncated `.ps1` behind for the
        guest to execute. An empty `text` still creates an empty (BOM-less) file.

        Both the chunk writes and the final move are sized against the same
        encoded-command cap, but separately: the chunk budget is derived from the
        real chunk template for this path, and the move is checked **up front**
        on the exact command string that is sent — preamble included, because
        those 30 characters are part of what the guest's command line carries.
        A path that fits every chunk yet overflows the move would otherwise
        upload every byte and only then fail, wasting the whole transfer.

        Raises:
            StageError: when `text` is not UTF-8 encodable (a lone surrogate), or
                when the path is too long for any command to stay under the cap.
        """
        try:
            data = text.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise StageError(
                f"{guest_path}: text is not UTF-8 encodable "
                f"({exc.reason} at index {exc.start}); a lone surrogate cannot be "
                "written to the guest"
            ) from exc
        final = "$ErrorActionPreference='Stop'\n" + replace_script(guest_path)
        check_size(final)
        tmp = ps_quote(f"{guest_path}.tmp")
        parent = parent_dir(guest_path)
        if parent:
            # `[IO.Directory]::CreateDirectory` instead of `New-Item -LiteralPath`:
            # it is idempotent, has no wildcard semantics at all, and does not
            # depend on a `-LiteralPath` parameter whose availability on Windows
            # PowerShell 5.1 is in doubt (a missing parameter binding fails the
            # whole staging stage).
            self.ps(
                "$ErrorActionPreference='Stop'\n"
                f"[IO.Directory]::CreateDirectory({ps_quote(parent)}) | Out-Null\n"
            )
        pieces = self._chunks(data, chunk_budget(guest_path))
        try:
            if not pieces:
                empty = (
                    "$ErrorActionPreference='Stop'\n"
                    f"[IO.File]::WriteAllBytes({tmp},(New-Object byte[] 0))\n"
                    + replace_script(guest_path)
                )
                check_size(empty)
                self.ps(empty)
                return
            offset = 0
            for index, piece in enumerate(pieces):
                blob = BOM_BYTES + piece if index == 0 else piece
                self.ps(write_chunk_script(tmp, blob, offset=offset))
                offset += len(blob)
            self.ps(final)
        except Exception:
            self._discard(tmp)
            raise

    def read_text(self, guest_path: str) -> str:
        """Read a small text file from the guest (empty string when missing)."""
        return self.ps(
            f"if (Test-Path -LiteralPath {ps_quote(guest_path)}) "
            f"{{ Get-Content -LiteralPath {ps_quote(guest_path)} -Raw }}"
        )


__all__ = ["WinRMChannel", "new_session", "run_ps"]
