"""`VMController` behaviour: shelling out only for a real VM, and stop status.

`utmctl` is the whole world here, so `subprocess.run` is stubbed. The tests pin
two rules: nothing is executed when no VM id is configured, and `stop()` reports
success only when `utmctl` exited 0.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agentic_bi.guest_vm import VMController


class TestVMController:
    def test_unconfigured_controller_is_inert(self, monkeypatch) -> None:
        monkeypatch.setattr("agentic_bi.guest_vm.shutil.which", lambda _: None)
        vm = VMController("SOME-UUID")
        assert not vm.configured
        assert vm.status() == "unknown"
        vm.start()  # must not shell out
        vm.stop()

    def test_no_uuid_means_not_configured(self) -> None:
        assert not VMController(None).configured

    def test_no_uuid_never_shells_out(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "agentic_bi.guest_vm.shutil.which", lambda _name: "/usr/bin/utmctl"
        )
        calls: list[tuple[str, object]] = []

        def fake_spawn(*args: object, **kwargs: object) -> object:
            calls.append(("spawn", args))
            raise AssertionError("utmctl must not run without a VM id")

        monkeypatch.setattr("agentic_bi.guest_vm.subprocess.run", fake_spawn)
        monkeypatch.setattr("agentic_bi.guest_vm.subprocess.Popen", fake_spawn)
        vm = VMController(None)
        assert not vm.configured
        assert vm.status() == "unknown"
        vm.start()
        vm.stop()
        assert calls == []

    def test_stop_reports_success_only_on_a_zero_exit(
        self, monkeypatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A refused `utmctl stop` must not be recorded as a finished teardown.

        Measured before: the exit status was ignored, `logger.info("stopped VM")`
        ran anyway and the chain result said `vm: stopped`.
        """
        monkeypatch.setattr(
            "agentic_bi.guest_vm.shutil.which", lambda _name: "/usr/bin/utmctl"
        )

        def fake_run(argv: list[str], **kwargs: object) -> SimpleNamespace:
            if argv[1] == "status":
                return SimpleNamespace(stdout="started\n", stderr="", returncode=0)
            return SimpleNamespace(stdout="", stderr="permission denied", returncode=1)

        monkeypatch.setattr("agentic_bi.guest_vm.subprocess.run", fake_run)
        caplog.set_level("WARNING", logger="agentic_bi.guest_vm")
        assert VMController("uuid").stop() is False
        assert "failed (exit 1)" in caplog.text
        assert "permission denied" in caplog.text
        assert "stopped VM" not in caplog.text

    def test_stop_reports_success_on_a_zero_exit(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "agentic_bi.guest_vm.shutil.which", lambda _name: "/usr/bin/utmctl"
        )

        def fake_run(argv: list[str], **kwargs: object) -> SimpleNamespace:
            stdout = "started\n" if argv[1] == "status" else ""
            return SimpleNamespace(stdout=stdout, stderr="", returncode=0)

        monkeypatch.setattr("agentic_bi.guest_vm.subprocess.run", fake_run)
        assert VMController("uuid").stop() is True
