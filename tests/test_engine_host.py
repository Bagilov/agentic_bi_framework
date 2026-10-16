"""Host discovery and plumbing of the engine (`engine_host`).

Everything here is environment-driven and must work on any OS: the Desktop
executable, the AS workspace root and the donor template come from environment
variables first, and `port_alive`/`wait_port` are pure socket/filesystem logic.
No test needs Windows or Power BI Desktop.
"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from agentic_bi import engine_host


def test_desktop_env_override_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PBI_RS_DESKTOP", r"D:\pbi\PBIDesktop.exe")
    assert engine_host.default_desktop() == r"D:\pbi\PBIDesktop.exe"


def test_desktop_falls_back_to_rs_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PBI_RS_DESKTOP", raising=False)
    monkeypatch.setattr(engine_host, "_DESKTOP_SUBPATHS", ())
    assert engine_host.default_desktop().endswith("PBIDesktop.exe")
    assert "Power BI Desktop" in engine_host.default_desktop()


def test_ws_root_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PBI_RS_WS_ROOT", str(tmp_path))
    assert engine_host.ws_root() == tmp_path


def test_ws_root_probes_existing_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PBI_RS_WS_ROOT", raising=False)
    local = tmp_path / "Local"
    target = (
        local / "Microsoft" / "Power BI Desktop SSRS" / "AnalysisServicesWorkspaces"
    )
    target.mkdir(parents=True)
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    assert engine_host.ws_root() == target


def test_ws_root_returns_conventional_path_when_nothing_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PBI_RS_WS_ROOT", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "absent"))
    root = engine_host.ws_root()
    assert root.name == "AnalysisServicesWorkspaces"
    assert root.is_absolute()


def test_template_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom = tmp_path / "donor.pbix"
    monkeypatch.setenv("PBI_RS_TEMPLATE", str(custom))
    import importlib

    reloaded = importlib.reload(engine_host)
    try:
        assert reloaded.DEFAULT_TEMPLATE == custom
    finally:
        monkeypatch.delenv("PBI_RS_TEMPLATE", raising=False)
        importlib.reload(engine_host)


def test_port_alive_detects_listening_socket() -> None:
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        assert engine_host.port_alive(port) is True
    finally:
        srv.close()


def test_port_alive_false_for_closed_port() -> None:
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    srv.close()
    assert engine_host.port_alive(port) is False


def _make_workspace(root: Path, name: str, port_text: str) -> Path:
    ws = root / name / "Data"
    ws.mkdir(parents=True)
    (ws / "msmdsrv.port.txt").write_text(port_text)
    return ws


def test_wait_port_skips_stale_and_returns_live(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    live = srv.getsockname()[1]
    try:
        _make_workspace(tmp_path, "stale", "1")
        _make_workspace(tmp_path, "live", f"{live}\x00")
        assert engine_host.wait_port(tmp_path, timeout=5) == live
    finally:
        srv.close()


def test_wait_port_times_out_when_nothing_listens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_workspace(tmp_path, "stale", "1")
    with pytest.raises(TimeoutError):
        engine_host.wait_port(tmp_path, timeout=1)


def test_kill_desktop_invokes_taskkill(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return object()

    monkeypatch.setattr(engine_host.subprocess, "run", fake_run)
    monkeypatch.setattr(engine_host.time, "sleep", lambda _s: None)
    engine_host.kill_desktop()
    assert [c[3] for c in calls] == ["PBIDesktop.exe", "msmdsrv.exe"]
    assert all("/F" in c and "/IM" in c for c in calls)


def test_run_engine_build_returns_output_tail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    abf = tmp_path / "out.abf"

    class _Proc:
        stdout = "engine done"
        stderr = ""

    def fake_run(cmd, **kwargs):
        abf.write_bytes(b"abf")
        return _Proc()

    monkeypatch.setattr(engine_host.subprocess, "run", fake_run)
    assert engine_host.run_engine_build(tmp_path / "spec.json", abf) == "engine done"


def test_run_engine_build_retries_then_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    abf = tmp_path / "out.abf"
    attempts: list[int] = []

    class _Proc:
        stdout = "boom"
        stderr = "err"

    def fake_run(cmd, **kwargs):
        attempts.append(1)
        return _Proc()

    monkeypatch.setattr(engine_host.subprocess, "run", fake_run)
    monkeypatch.setattr(engine_host.time, "sleep", lambda _s: None)
    with pytest.raises(RuntimeError, match="engine build failed"):
        engine_host.run_engine_build(tmp_path / "spec.json", abf)
    assert len(attempts) == 2


def test_run_oracle_parses_last_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Proc:
        stdout = "RESULT[MODEL_LOADED]\nRESULT[CLOSE_OK]"
        stderr = ""

    monkeypatch.setattr(engine_host.subprocess, "run", lambda *a, **k: _Proc())
    assert engine_host.run_oracle(tmp_path / "b.pbix", hold=1) == "CLOSE_OK"


def test_run_oracle_reports_no_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Proc:
        stdout = ""
        stderr = ""

    monkeypatch.setattr(engine_host.subprocess, "run", lambda *a, **k: _Proc())
    assert engine_host.run_oracle(tmp_path / "b.pbix", hold=1) == "NO_RESULT"


@pytest.mark.parametrize("port_text", ["not-a-number", ""])
def test_wait_port_ignores_unparseable_port_then_times_out(
    tmp_path: Path, port_text: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_workspace(tmp_path, "ws", port_text)
    with pytest.raises(TimeoutError):
        engine_host.wait_port(tmp_path, timeout=1)


def test_pipeline_reexports_host_defaults() -> None:
    from agentic_bi import engine

    assert engine.PBI_RS == engine_host.PBI_RS
    assert engine.DEFAULT_TEMPLATE == engine_host.DEFAULT_TEMPLATE
    assert engine.WS_ROOT == engine_host.WS_ROOT


def test_pipeline_oracle_delegates_to_host(monkeypatch: pytest.MonkeyPatch) -> None:
    from agentic_bi import engine

    monkeypatch.setattr(engine_host, "run_oracle", lambda pbix, hold: "DELEGATED")
    assert engine.EnginePipeline.run_oracle(Path("x.pbix"), 5) == "DELEGATED"
