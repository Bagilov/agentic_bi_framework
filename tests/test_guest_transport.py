"""Offline tests for the guest transport: staging server, integrity, PS failures.

These exercise the host-side pieces of the chain that never touch a VM: the
single-file staging server, the SHA-256 integrity check on `push_file`, and the
non-zero-exit handling in `run_ps`. The chain verdict, budget and build-script
logic live in `test_guest_chain.py`.
"""

from __future__ import annotations

import functools
import hashlib
import http.server
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from agentic_bi.guest_staging import _SingleFileHandler
from agentic_bi.guest_transport import (
    Deadline,
    GuestConfig,
    StageError,
    WinRMTransport,
    run_ps,
)


class TestStagingServerServesOneFile:
    """The staging server must expose exactly one file at its token path."""

    def test_serves_the_file_for_the_token_and_404s_everything_else(
        self, tmp_path: Path
    ) -> None:
        secret = tmp_path / "abf.zip"
        secret.write_bytes(b"payload-bytes")
        sibling = tmp_path / "secret.txt"
        sibling.write_text("private\n", encoding="utf-8")
        token = "tok-123"
        handler = functools.partial(_SingleFileHandler, file_path=secret, token=token)
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        port = server.server_address[1]
        base = f"http://127.0.0.1:{port}"
        try:
            with urllib.request.urlopen(f"{base}/{token}/abf.zip") as resp:
                assert resp.read() == b"payload-bytes"
            for bad in ("/", "/secret.txt", f"/{token}/secret.txt", "/abf.zip"):
                with pytest.raises(urllib.error.HTTPError) as err:
                    urllib.request.urlopen(f"{base}{bad}")
                assert err.value.code == 404
        finally:
            server.shutdown()
            server.server_close()


class TestPushFileVerifiesIntegrity:
    """A missing or wrong guest hash must fail loudly, never pass silently."""

    def _transport(self, responses) -> WinRMTransport:
        transport = WinRMTransport.__new__(WinRMTransport)
        transport.config = GuestConfig(
            winrm="http://127.0.0.1:5985/wsman", user="u", password="p"
        )
        transport._init_staging()
        transport.ps = lambda script, **kw: next(responses)  # type: ignore[method-assign]
        return transport

    def test_missing_hash_is_a_stage_error(self, tmp_path: Path) -> None:
        local = tmp_path / "abf.zip"
        local.write_bytes(b"payload")
        transport = self._transport(iter(["", ""]))
        with pytest.raises(StageError, match="produced no hash"):
            transport.push_file(local, r"C:\pbi\abf.zip", Deadline(30))

    def test_wrong_hash_is_a_stage_error(self, tmp_path: Path) -> None:
        local = tmp_path / "abf.zip"
        local.write_bytes(b"payload")
        transport = self._transport(iter(["", "deadbeef"]))
        with pytest.raises(StageError, match="failed SHA-256 verification"):
            transport.push_file(local, r"C:\pbi\abf.zip", Deadline(30))

    def test_matching_hash_passes(self, tmp_path: Path) -> None:
        local = tmp_path / "abf.zip"
        local.write_bytes(b"payload")
        digest = hashlib.sha256(b"payload").hexdigest()
        transport = self._transport(iter(["", digest]))
        transport.push_file(local, r"C:\pbi\abf.zip", Deadline(30))


class TestRunPsSurfacesFailure:
    """A non-zero guest exit must raise, not masquerade as an empty success."""

    class _Result:
        def __init__(self, out: bytes, err: bytes, code: int) -> None:
            self.std_out = out
            self.std_err = err
            self.status_code = code

    def _session(self, result: _Result) -> object:
        return type("S", (), {"run_ps": lambda self, _s: result})()

    def test_zero_status_returns_stdout(self) -> None:
        session = self._session(self._Result(b"ok\r\n", b"", 0))
        assert run_ps(session, "x") == "ok\r\n"

    def test_non_zero_status_raises_with_stderr(self) -> None:
        session = self._session(self._Result(b"", b"Get-FileHash : not found", 1))
        with pytest.raises(StageError, match="not found"):
            run_ps(session, "x")
