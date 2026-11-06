"""Host-side file staging for the guest chain, over a quiet single-file server.

The guest cannot reach the host filesystem directly, so the host serves **one
file** on its guest-reachable address and the guest fetches it (`push_file`); the
reverse direction is done over WinRM as chunked base64 (`pull_file`), because a
single WinRM read of a multi-megabyte file is slow and brittle.

The staging server is deliberately tight, because whatever it serves is fetched
and then executed on the guest:

* it binds the address the guest actually uses (not every interface) where that
  address is local;
* it serves exactly one file, at a per-run unguessable path — no directory
  listing, no sibling reads, and any other path is a 404;
* the transfer is verified: the guest checks a SHA-256 the host computed, so a
  truncated or corrupted fetch fails loudly instead of being staged and run.

Every server this mixin opens is tracked and closed on `close()`, so a chain can
never leak a listening socket.

Public API:
    StagingMixin.push_file(local, dest, deadline)
    StagingMixin.pull_file(guest_path, local, deadline)
    StagingMixin.close()
"""

from __future__ import annotations

import base64
import functools
import hashlib
import http.server
import logging
import secrets
import socket
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from agentic_bi.guest_types import Deadline, GuestConfig, StageError, ps_quote
from agentic_bi.guest_vm import host_reachable_ip

logger = logging.getLogger(__name__)


class _SingleFileHandler(http.server.BaseHTTPRequestHandler):
    """Serve exactly one file at one secret path; everything else is a 404.

    A stock directory handler would list (and serve) every sibling of the pushed
    file to anyone who can route to the host, so the path is checked against the
    per-run token and the directory itself is never exposed.
    """

    server_version = "abf-stage/1"
    protocol_version = "HTTP/1.1"

    def __init__(self, *args, file_path: Path, token: str, **kwargs) -> None:
        self._file_path = file_path
        self._token = token
        self._url_path = f"/{token}/{file_path.name}"
        super().__init__(*args, **kwargs)

    def log_message(self, *args, **kwargs) -> None:
        return

    def do_GET(self) -> None:  # BaseHTTPRequestHandler API name
        """Return the staged file only for the exact tokenized path."""
        if self.path.split("?", 1)[0] != self._url_path:
            self.send_error(404, "Not Found")
            return
        payload = self._file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class StagingMixin:
    """Host->guest and guest->host file transfer, plus server teardown."""

    if TYPE_CHECKING:
        # The composed `WinRMTransport` inherits `config`/`ps` from `WinRMChannel`,
        # but this mixin is checked on its own, so those members are declared here.
        # The signatures are copied verbatim from `WinRMChannel` on purpose: an
        # override that differs there would make the composed class's bases
        # incompatible.
        config: GuestConfig

        def ps(self, script: str, *, attempts: int = 4) -> str: ...

    _servers: list[http.server.ThreadingHTTPServer]

    def _init_staging(self) -> None:
        """Create the server registry (called from the transport's `__init__`)."""
        self._servers = []

    def _bind_address(self) -> str:
        """The address to serve on: the guest-reachable IP when it is local.

        `AGENTIC_BI_HOST_IP` can name an address this host does not own (e.g. a
        forwarded/aliased address); binding it would fail, so a local bindability
        probe decides, and the fallback is logged rather than silent.
        """
        host = host_reachable_ip(self.config)
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.bind((host, 0))
            return host
        except OSError:
            logger.warning(
                "staging: %s is not a local address; falling back to all interfaces "
                "(the per-run token still scopes access to one file)",
                host,
            )
            return "0.0.0.0"
        finally:
            probe.close()

    def _serve(
        self, file_path: Path, token: str
    ) -> tuple[http.server.ThreadingHTTPServer, int]:
        handler = functools.partial(
            _SingleFileHandler, file_path=file_path, token=token
        )
        server = http.server.ThreadingHTTPServer((self._bind_address(), 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self._servers.append(server)
        return server, server.server_address[1]

    def _stop_server(self, server: http.server.ThreadingHTTPServer) -> None:
        server.shutdown()
        server.server_close()
        if server in self._servers:
            self._servers.remove(server)

    def push_file(self, local: Path, dest: str, deadline: Deadline) -> None:
        """Serve `local` from the host and have the guest fetch it to `dest`.

        The guest verifies a SHA-256 computed here, so a corrupted transfer is a
        loud `StageError` rather than a silently truncated staged file.
        """
        local = Path(local)
        digest = hashlib.sha256(local.read_bytes()).hexdigest()
        token = secrets.token_urlsafe(24)
        server, port = self._serve(local, token)
        try:
            url = f"http://{host_reachable_ip(self.config)}:{port}/{token}/{local.name}"
            self.ps(
                "$ErrorActionPreference='Stop'\n"
                f"Invoke-WebRequest -UseBasicParsing -TimeoutSec 120 {ps_quote(url)} "
                f"-OutFile {ps_quote(dest)}\n"
            )
        finally:
            self._stop_server(server)
        # The budget is checked *after* the server is closed and outside the
        # `finally`: a `check` inside it replaced a specific fetch error (an
        # unreachable URL, a refused write) with a generic timeout whenever the
        # clock had also run out, hiding the real cause.
        deadline.check("push")
        actual = self.ps(
            "$ErrorActionPreference='Stop'\n"
            f"(Get-FileHash -LiteralPath {ps_quote(dest)} -Algorithm SHA256).Hash"
        )
        reported = [ln.strip().lower() for ln in actual.splitlines() if ln.strip()]
        if not reported:
            raise StageError(
                f"staged {dest}: SHA-256 verification produced no hash "
                "(the file is missing or unreadable on the guest)"
            )
        if reported[-1] != digest:
            raise StageError(
                f"staged {dest} failed SHA-256 verification "
                f"(expected {digest[:12]}…, got {reported[-1][:12]}…)"
            )

    def pull_file(
        self,
        guest_path: str,
        local: Path,
        deadline: Deadline,
        *,
        chunk: int = 384 * 1024,
    ) -> int:
        """Fetch `guest_path` to `local` as base64, chunked and deadline-bounded.

        `Get-Item` takes `-LiteralPath`, so a staged path containing `[`, `]` or
        `*` is measured as the file it is instead of being read as a wildcard
        pattern (which would fail with "no match" and abort the pull).

        The size probe runs under `$ErrorActionPreference='Stop'` and an empty
        answer is refused **before** `local` is written: a missing guest path
        used to produce an empty stdout, a `0` total and a 0-byte local file,
        which replaced the caller's previous good artifact while the stage still
        reported success. Only an all-digit line is accepted as the size: a
        warning line or a non-terminating error on stdout otherwise reached
        `int()` and escaped as a bare `ValueError`, which the chain reported as
        `error: ValueError: invalid literal ...` instead of naming the file.

        Raises:
            StageError: when the guest file is missing, empty or its size cannot
                be read.
        """
        answer = self.ps(
            "$ErrorActionPreference='Stop'\n"
            f"(Get-Item -LiteralPath {ps_quote(guest_path)}).Length"
        )
        digits = [
            line.strip() for line in answer.splitlines() if line.strip().isdigit()
        ]
        total = int(digits[-1]) if digits else 0
        if total <= 0:
            raise StageError(
                f"{guest_path}: the guest file is missing or empty, or its size "
                f"is unreadable ({' '.join(answer.split())[:120]!r}); refusing to "
                f"overwrite {Path(local).name}"
            )
        out = bytearray()
        offset = 0
        while offset < total:
            deadline.check("pull")
            b64 = self.ps(
                f"$fs=[IO.File]::OpenRead({ps_quote(guest_path)});"
                f"$fs.Seek({int(offset)},'Begin');"
                f"$b=New-Object byte[] {chunk};"
                f"$n=$fs.Read($b,0,{chunk});$fs.Close();"
                f"[Convert]::ToBase64String($b,0,$n)"
            )
            raw = b64.strip().splitlines()
            if not raw:
                # An empty answer is a short read; the length check after the
                # loop turns it into a loud `StageError` instead of writing a
                # truncated file (and instead of `IndexError` on `raw[-1]`).
                break
            blob = base64.b64decode(raw[-1] or "")
            if not blob:
                break
            out += blob
            offset += len(blob)
        if len(out) != total:
            raise StageError(
                f"{guest_path}: pulled {len(out)} of {total} B; refusing to write "
                f"a truncated {Path(local).name}"
            )
        local = Path(local)
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes(bytes(out))
        return len(out)

    def close(self) -> None:
        """Release host resources; safe to call more than once."""
        for server in list(self._servers):
            try:
                self._stop_server(server)
            except Exception:
                logger.debug("server already stopped", exc_info=True)
