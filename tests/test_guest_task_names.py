"""Task names: unique per run, and safe as a file stem and a task name.

Two chains against the same guest used fixed task names (`agentic_bi_board`,
`agentic_bi_oracle`), so the second run unregistered the first one's live task,
overwrote its runner/payload and deleted its marker. The registered name and
**every** artifact name now carry one random per-run token (`run_paths`).

`name` also becomes a file stem under `config.out`, so it is validated against
path separators, control characters, Windows device names, a `.`/`..` component,
a leading/trailing dot or space, and the Task Scheduler / `MAX_PATH` length cap.
A `..` *inside* a name (`board..v2`) is a legal stem and stays allowed.
"""

from __future__ import annotations

import re

import pytest

from agentic_bi.guest_task import TaskRunnerMixin, check_name
from agentic_bi.guest_task_script import run_paths
from agentic_bi.guest_types import GuestConfig, StageError

_FORBIDDEN = re.compile(r'[\\/:*?"<>|]')
_TOKEN = re.compile(r"^[0-9a-f]{8}$")


class _Deadline:
    expired = False

    def slice(self, value: float) -> float:
        return 0.0


class _Guest:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.written: list[tuple[str, str]] = []
        self.marker = False

    def ps(self, script: str, **kw: object) -> str:
        self.calls.append(script)
        if "Register-ScheduledTask -TaskName" in script:
            self.marker = True
            return ""
        if "Get-Content -LiteralPath" in script:
            return "EXITCODE=0\r\n" if self.marker else ""
        if "Remove-Item -LiteralPath" in script:
            self.marker = False
            return ""
        if "'yes'" in script and "'no'" in script:
            path = script.split("Test-Path -LiteralPath '", 1)[1].split("'", 1)[0]
            if path.endswith("payload.ps1"):
                return "yes"
            return "yes" if self.marker else "no"
        return ""


def _runner(guest: _Guest) -> TaskRunnerMixin:
    runner = TaskRunnerMixin()
    runner.config = GuestConfig(
        winrm="http://guest:5985/wsman", user="u", password="p", out=r"C:\pbi\out"
    )
    runner.ps = guest.ps  # type: ignore[method-assign]
    runner.write_text = lambda path, text: guest.written.append((path, text))  # type: ignore[attr-defined]
    runner.read_text = lambda path: ""  # type: ignore[attr-defined]
    return runner


def _registered_tasks(calls: list[str]) -> list[str]:
    return [
        call.split("-TaskName '", 1)[1].split("'", 1)[0]
        for call in calls
        if "Register-ScheduledTask -TaskName" in call
    ]


def _run(runner: TaskRunnerMixin) -> None:
    runner.run_task(
        name="agentic_bi_board",
        script="Write-Output hi",
        deadline=_Deadline(),  # type: ignore[arg-type]
        poll=0,
    )


class TestTheTaskNameIsUniquePerRun:
    def test_two_runs_of_the_same_base_get_different_names(self) -> None:
        first = run_paths(r"C:\pbi\out", "agentic_bi_board").task
        second = run_paths(r"C:\pbi\out", "agentic_bi_board").task
        assert first != second

    def test_the_name_keeps_the_base_and_adds_a_token(self) -> None:
        name = run_paths(r"C:\pbi\out", "agentic_bi_board").task
        assert name.startswith("agentic_bi_board_")
        assert _TOKEN.match(name.rsplit("_", 1)[1])

    def test_the_name_is_legal_for_task_scheduler(self) -> None:
        name = run_paths(r"C:\pbi\out", "agentic_bi_oracle").task
        assert not _FORBIDDEN.search(name)
        assert name == name.rstrip(". ")
        assert ".." not in name

    def test_two_registered_tasks_do_not_share_a_name(self) -> None:
        guest = _Guest()
        runner = _runner(guest)
        _run(runner)
        _run(runner)
        tasks = _registered_tasks(guest.calls)
        assert len(tasks) == 2
        assert tasks[0] != tasks[1]
        assert all(not _FORBIDDEN.search(task) for task in tasks)

    def test_every_lifecycle_call_uses_the_suffixed_name(self) -> None:
        guest = _Guest()
        runner = _runner(guest)
        _run(runner)
        registered = _registered_tasks(guest.calls)[0]
        assert registered != "agentic_bi_board"
        names = re.findall(r"-TaskName '([^']*)'", "".join(guest.calls))
        assert len(names) >= 3, "unregister, register and the start all name it"
        assert set(names) == {registered}

    def test_the_artifact_files_carry_the_name_and_a_per_run_token(self) -> None:
        guest = _Guest()
        runner = _runner(guest)
        _run(runner)
        payload, script = (path for path, _ in guest.written)
        assert payload.startswith(r"C:\pbi\out\agentic_bi_board.")
        assert payload.endswith(".payload.ps1")
        assert script.startswith(r"C:\pbi\out\agentic_bi_board.")
        assert script.endswith(".ps1")
        assert script != r"C:\pbi\out\agentic_bi_board.ps1"


class TestTheNameIsValidated:
    @pytest.mark.parametrize(
        "name",
        [
            "..",
            ".",
            "../escape",
            r"..\escape",
            r"a\b",
            "a/b",
            'a"b',
            "a|b",
            "a*b",
            "a?b",
            "a:b",
            "a<b",
            "a>b",
            "trailing.",
            "trailing ",
            " leading",
            ".hidden",
            "with\x00control",
            "",
            "   ",
        ],
    )
    def test_an_unsafe_name_is_refused(self, name: str) -> None:
        with pytest.raises(ValueError):
            check_name(name)

    @pytest.mark.parametrize(
        "name",
        [
            "CON",
            "con",
            "NUL.txt",
            "AUX",
            "PRN",
            "COM1",
            "com9",
            "LPT9.log",
            "CLOCK$",
            "CONIN$",
            "CONOUT$",
            "conin$.log",
            # Windows strips the trailing space before resolving the device
            "con .txt",
            # Windows reads these ISO-8859-1 superscripts as digits in device
            # names (the file-naming documentation lists them explicitly).
            "COM\u00b9",
            "COM\u00b2.txt",
            "com\u00b3",
            "LPT\u00b9",
            "LPT\u00b2.log",
            "lpt\u00b3",
        ],
    )
    def test_a_reserved_device_name_is_refused(self, name: str) -> None:
        with pytest.raises(ValueError, match="reserved"):
            check_name(name)

    @pytest.mark.parametrize("name", ["\ud800", "board\udfff", "\ud83dboard"])
    def test_a_lone_surrogate_is_a_value_error_not_an_encode_error(
        self, name: str
    ) -> None:
        """`check_name` documents `ValueError`; the UTF-16 count used to raise."""
        with pytest.raises(ValueError):
            check_name(name)

    def test_an_over_long_name_is_refused_with_the_limits_named(self) -> None:
        with pytest.raises(ValueError, match="MAX_PATH"):
            check_name("a" * 121)

    def test_the_limit_counts_utf16_units_not_code_points(self) -> None:
        """An emoji is one code point but two UTF-16 units, which Windows measures.

        Counting code points accepted `"😀" * 120` (120 "characters", 240 units),
        whose artifact path then overflowed the MAX_PATH budget.
        """
        with pytest.raises(ValueError, match="UTF-16"):
            check_name("\U0001f600" * 120)
        assert check_name("\U0001f600" * 60) == "\U0001f600" * 60

    @pytest.mark.parametrize(
        "name",
        [
            "agentic_bi_board",
            "agentic_bi_oracle",
            "board[1]",
            "board..v2",
            "Правление_2024",
            "console",
        ],
    )
    def test_a_plain_name_is_accepted(self, name: str) -> None:
        assert check_name(name) == name

    def test_run_task_refuses_before_touching_the_guest(self) -> None:
        guest = _Guest()
        runner = _runner(guest)
        with pytest.raises(ValueError, match="config.out"):
            runner.run_task(
                name="../escape",
                script="Write-Output hi",
                deadline=_Deadline(),  # type: ignore[arg-type]
                poll=0,
            )
        assert guest.calls == []
        assert guest.written == []

    def test_run_task_surfaces_a_value_error_for_a_lone_surrogate(self) -> None:
        guest = _Guest()
        runner = _runner(guest)
        with pytest.raises(ValueError):
            runner.run_task(
                name="\ud800",
                script="Write-Output hi",
                deadline=_Deadline(),  # type: ignore[arg-type]
                poll=0,
            )
        assert guest.calls == []
        assert guest.written == []


class TestTheMissingPayloadStillFails:
    def test_a_valid_name_alone_does_not_make_a_task(self) -> None:
        guest = _Guest()
        runner = _runner(guest)
        guest.marker = False
        runner.ps = lambda script, **kw: "no" if "'yes'" in script else ""  # type: ignore[method-assign]
        with pytest.raises(StageError, match="payload"):
            runner.run_task(
                name="board",
                script="Write-Output hi",
                deadline=_Deadline(),  # type: ignore[arg-type]
                poll=0,
            )


def test_a_long_out_dir_is_refused_before_the_run_starts():
    """`check_name` budgets the name; the directory can still break the limits.

    Measured: with `out` of 130 characters and a 120-unit name the teardown
    command was 6552 encoded characters (cap 6000) and the payload path was 272
    UTF-16 units (MAX_PATH 260). The over-cap teardown was swallowed by a broad
    `except`, so the payload/runner/marker leaked on the guest.
    """
    with pytest.raises(ValueError, match="MAX_PATH"):
        run_paths("C:\\" + "o" * 127, "n" * 120)


def test_a_short_out_dir_and_name_still_build_paths():
    paths = run_paths(r"C:\pbi\out", "board")
    assert paths.payload.startswith("C:\\pbi\\out\\board.")
