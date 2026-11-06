"""Names, per-run artifact paths and PowerShell sources for a guest task run.

Split out of `guest_task` so the transport mixin and the text it emits stay
readable, and so every artifact name is produced in exactly one place.

Three properties are pinned here:

* a `name` is both a Task Scheduler name and a file stem under `config.out`, so
  it is validated against separators, reserved device names, control characters
  and the Task Scheduler / `MAX_PATH` length ceiling;
* **every** artifact of a run (task, runner, payload, log, marker) carries one
  per-run token, so two runs with the same `name` never share a file;
* exactly **one** process owns the log: the runner redirects the child into it,
  and a payload never mentions it (a second `Out-File` on the same path hits the
  runner's `FileShare.Read` and is lost).

Public API:
    RunPaths, run_paths(out_dir, name), run_token()
    check_name(name), remove_script(*paths)
    runner_script(...), payload_footer(), parse_exitcode(marker)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import uuid4

from agentic_bi.guest_types import ps_quote
from agentic_bi.guest_winrm_commands import (
    MAX_ENCODED_COMMAND,
    encoded_size,
    replace_script,
)

# Size exception (>300 lines): the guest-side PowerShell surface (names,
# paths, payload footer, runner) is one contract; a caller must be able to read
# the name rules and the runner they feed in one place.

_MARKER_TOKEN = "EXITCODE="

# `Set-Content` terminates the value with a newline, so a complete marker is
# `EXITCODE=<n>\r\n` and nothing else. Requiring the terminator is what makes a
# read **mid-write** (`EXITCODE=1` of an unfinished `EXITCODE=10`) return None
# instead of the truncated prefix: the writer of a marker is atomic anyway, and
# the parser must not accept a shape the writer never produces.
_MARKER_RE = re.compile(r"(?:^|\n)" + re.escape(_MARKER_TOKEN) + r"(-?\d+)\r?\n\s*\Z")

# Characters `CreateFile` refuses in a file name (and a task name must not carry
# either): the Windows path separators, the reserved punctuation, and control
# characters. Device names are checked separately below, because their characters
# are perfectly legal.
_BAD_NAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')

# Windows device names: `C:\pbi\out\CON.ps1` cannot be created even though the
# characters are legal, and Task Scheduler refuses the name. The check applies to
# the stem before the first dot, because `CON.txt` is equally reserved. The
# console handles are device names too, and they are the ones a name like
# `CONOUT$` hits on the guest (`Set-Content` then targets the console).
#
# The superscript forms are reserved as well: Windows reads the ISO-8859-1
# digits `¹`, `²` and `³` as digits in `COM#`/`LPT#` (Microsoft's file-naming
# documentation gives `echo test > COM¹` as a failing example), so the plain
# `COM1..9` list alone left six holes.
_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CLOCK$", "CONIN$", "CONOUT$"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
    | {"COM\u00b9", "COM\u00b2", "COM\u00b3"}
    | {"LPT\u00b9", "LPT\u00b2", "LPT\u00b3"}
)

# A task name is additionally suffixed with `_<8 hex>`, and the artifact name is
# `<name>.<8 hex>.payload.ps1` under `config.out`. Task Scheduler breaks on names
# beyond ~238 characters, and Windows `MAX_PATH` is 260 for the whole path, so
# the base is capped well below either limit to leave room for the suffix and the
# out directory. Extended-length paths are not assumed anywhere.
#
# The limit counts UTF-16 code units, which is what Windows measures: an emoji is
# one code point but two units, so counting code points accepted a name whose
# artifact path was 12 units longer than the budget (measured: `"😀"*120`).
_MAX_NAME = 120


def run_token() -> str:
    """An opaque token unique to one run, legal in a file name and a task name.

    A host pid plus a coarse timestamp (the previous scheme) collides across two
    hosts that start in the same second, and a per-process counter collides
    across processes, so the token is random.
    """
    return uuid4().hex[:8]


@dataclass(frozen=True)
class RunPaths:
    """Every artifact path owned by exactly one `run_task` invocation."""

    task: str
    runner: str
    payload: str
    log: str
    marker: str


def remove_script(*paths: str) -> str:
    """PowerShell that deletes each path if it exists, and exits 0 otherwise.

    A bare `Remove-Item ... -EA SilentlyContinue` is not enough: on Windows
    PowerShell 5.1 (measured on the guest) `-EA SilentlyContinue` does not
    override `$ErrorActionPreference='Stop'`, so a missing target still makes the
    script exit 1 — and `run_ps` reports that as a stage failure. Returns an
    empty-string-tolerant script for any number of paths.

    Both commands take `-LiteralPath`: without it `Test-Path`/`Remove-Item` expand
    `[`, `]`, `*` and `?` as wildcards, and a task/marker name taken from the
    configuration may legitimately contain them (e.g. `board[1].pbix`). A wildcard
    match would then delete a *different* file, or report the target as absent
    while it is still there.
    """
    return "".join(
        f"if (Test-Path -LiteralPath {ps_quote(path)}) "
        f"{{ Remove-Item -LiteralPath {ps_quote(path)} -Recurse -Force }}\n"
        for path in paths
    )


def check_name(name: str) -> str:
    """Reject a `name` that would escape `config.out` or break a task name.

    `name` becomes both a file stem under `config.out` and a Task Scheduler name,
    so it is refused when it contains a path separator or any of `: * ? " < > |`,
    a control character, or a leading/trailing space or dot. A `.`/`..` name
    component is refused as well, because it would still walk a path out of the
    staging directory — while `..` *inside* a name (`board..v2`) is a legal,
    unambiguous file stem and stays allowed. Windows device names (`CON`, `NUL`,
    `AUX`, `PRN`, `COM1..9`, `LPT1..9`, including the superscript `COM¹..³` and
    `LPT¹..³` forms) are refused even though their characters are legal:
    `C:\\pbi\\out\\CON.ps1` cannot be created. Unicode is allowed, except a lone
    surrogate, which no UTF-16 name can carry.

    Raises:
        ValueError: when `name` is empty, unsafe, reserved, contains a lone
            surrogate, or is longer than `_MAX_NAME` (Task Scheduler and
            `MAX_PATH` limits, see `_MAX_NAME`).
    """
    if not isinstance(name, str) or not name.strip():
        raise ValueError("the task name must be a non-empty string")
    if _has_surrogate(name):
        raise ValueError(
            f"the task name {name!r} contains a lone UTF-16 surrogate; Windows "
            "names are UTF-16, so such a name cannot be created on the guest"
        )
    if _BAD_NAME_CHARS.search(name) or name in (".", "..") or name != name.strip(". "):
        raise ValueError(
            f"the task name {name!r} is not usable: it would either leave "
            'config.out or be refused by Task Scheduler (no \\ / : * ? " < > |, '
            "no control characters, no '.'/'..' component, no leading or "
            "trailing dot or space)"
        )
    # Windows strips trailing spaces before resolving a device name, so
    # `con .txt` is `CON` and is refused.
    if name.split(".", 1)[0].rstrip(" ").upper() in _RESERVED_NAMES:
        raise ValueError(
            f"the task name {name!r} is a reserved Windows device name "
            "(CON, PRN, AUX, NUL, CLOCK$, CONIN$, CONOUT$, COM1-9, LPT1-9, "
            "COM¹-³, LPT¹-³): neither the task nor its artifact file could be "
            "created"
        )
    units = _utf16_units(name)
    if units > _MAX_NAME:
        raise ValueError(
            f"the task name is {units} UTF-16 units, over the {_MAX_NAME} "
            "limit: Task Scheduler refuses names past ~238 characters and the "
            "per-run artifact path must stay inside the 260-character MAX_PATH"
        )
    return name


def _has_surrogate(text: str) -> bool:
    """True when `text` carries a lone UTF-16 surrogate code point.

    A Windows name is a UTF-16 string, and a lone surrogate has no valid
    encoding: `CreateFileW` cannot create such a file. The encoders refuse it
    too, but with `UnicodeEncodeError`, while `check_name` documents `ValueError`.
    """
    return any(0xD800 <= ord(char) <= 0xDFFF for char in text)


def _utf16_units(text: str) -> int:
    """The length Windows actually measures: UTF-16 code units, not code points.

    `surrogatepass` keeps a lone surrogate measurable instead of raising from
    the encoder; `check_name` refuses such a name before it gets here.
    """
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


#: Windows `MAX_PATH` for a fully qualified file name, in UTF-16 units.
_MAX_PATH = 260


def _check_artifact_paths(out_dir: str, name: str, paths: RunPaths) -> None:
    """Refuse a run whose artifacts cannot fit the guest's limits.

    `check_name` budgets the **name** only; the directory is the caller's. With a
    long `out_dir` the payload path exceeded `MAX_PATH` and the teardown command
    exceeded the encoded-command cap — and that teardown runs with `attempts=1`
    inside a broad `except`, so the over-cap command was swallowed as a warning
    and the run's payload/runner/marker stayed on the guest forever. Both limits
    are checked here, where the directory and the name are known together.

    Raises:
        ValueError: when an artifact path is too long or the cleanup command
            cannot be sent as one encoded command.
    """
    for label, path in (
        ("payload", paths.payload),
        ("runner", paths.runner),
        ("log", paths.log),
        ("marker", paths.marker),
    ):
        units = _utf16_units(path)
        if units >= _MAX_PATH:
            raise ValueError(
                f"the {label} path for {name!r} is {units} UTF-16 units "
                f"({path}); MAX_PATH on the guest is {_MAX_PATH}. Use a shorter "
                "AGENTIC_BI_GUEST_OUT or name"
            )
    cleanup = remove_script(
        paths.payload, paths.runner, paths.log, paths.marker, paths.marker + ".tmp"
    )
    size = encoded_size(cleanup)
    if size > MAX_ENCODED_COMMAND:
        raise ValueError(
            f"the cleanup command for {name!r} is {size} encoded characters, over "
            f"the {MAX_ENCODED_COMMAND} cap; it could never reach the guest, so "
            "the run's artifacts would leak. Use a shorter AGENTIC_BI_GUEST_OUT "
            "or name"
        )


def run_paths(out_dir: str, name: str) -> RunPaths:
    """The artifact paths of one run: all of them carry the same random token.

    Callers never build these strings themselves: two runs of the same `name`
    under the same `out_dir` previously shared the runner, payload, log and
    marker, so the second run overwrote the first one's payload and deleted its
    live marker and log. The final `.pbix` is not part of this set; it is the
    caller's declared output and is replaced only by a finished build.

    Raises:
        ValueError: when `name` is not a usable task/file stem (see `check_name`).
    """
    check_name(name)
    token = run_token()
    stem = f"{name}.{token}"
    paths = RunPaths(
        task=f"{name}_{token}",
        runner=f"{out_dir}\\{stem}.ps1",
        payload=f"{out_dir}\\{stem}.payload.ps1",
        log=f"{out_dir}\\{stem}.log",
        marker=f"{out_dir}\\{stem}.done",
    )
    _check_artifact_paths(out_dir, name, paths)
    return paths


def _exit_rule() -> str:
    """The shared "0 only on an explicit success" rule, as PowerShell lines.

    The **previous** rule let a stale `$LASTEXITCODE` outrank `$?`, which reported
    a payload ending on a failed cmdlet as success (`python ok; Set-Content <fail>`
    -> 0) and a payload whose native command failed followed by a successful
    cmdlet as its old code. This rule is evaluated after `$abfOk = $?`:

    * `$?` false -> `$LASTEXITCODE` when non-null and non-zero, else 1;
    * `$?` true -> `$LASTEXITCODE` when non-null and non-zero, else 0.

    Both callers (the payload footer and the runner) use exactly these statements,
    so the two stages cannot drift apart again.
    """
    return (
        "$abfOk = $?\n"
        "$abfCode = 0\n"
        "if (-not $abfOk) { $abfCode = 1 }\n"
        "if (($null -ne $LASTEXITCODE) -and ($LASTEXITCODE -ne 0)) "
        "{ $abfCode = $LASTEXITCODE }\n"
    )


def payload_footer() -> str:
    """The lines appended to every payload: fold the result into `exit N`.

    A payload `exit N` leaves the process before any trailing statement could
    run, and a payload ending on a failing native command must still be reported,
    so the exit code is folded into the process code here and read back from the
    marker by the runner. `$?` is captured first, while it still describes the
    payload's last statement.
    """
    return _exit_rule() + "exit $abfCode\n"


def _task_argument(runner: str) -> str:
    """The `powershell.exe` argument line that runs the task's `.ps1` runner.

    `-File` needs the path wrapped in double quotes (paths may contain spaces),
    and the whole line is later embedded in a single-quoted PowerShell literal,
    so an embedded `"` is backslash-escaped for the Windows command line.
    """
    safe = runner.replace('"', '\\"')
    return f'-NoProfile -ExecutionPolicy Bypass -File "{safe}"'


def runner_script(
    *, payload: str, log_path: str, marker_path: str, files_before: str = ""
) -> str:
    """The `.ps1` a scheduled task runs: clean up, run the payload, mark the code.

    Four properties are pinned here:

    * `$ErrorActionPreference='Stop'` is the **first** statement, so a refused
      cleanup is a terminating error instead of a silent non-terminating one;
    * the runner is the **only** owner of the log: it appends the child's stdout
      **and stderr** to it. The payload must not redirect to the same path — an
      `Out-File` holds the file open with `FileShare.Read`, so a second writer is
      refused and its whole output (for the oracle, the `RESULT [...]` line) is
      lost. `$LASTEXITCODE` is read immediately after the pipeline, which is
      still the child's code;
    * `$ErrorActionPreference` is `Continue` from just before the child pipeline
      until `Stop` is restored after the exit-code rule. That window is
      deliberate: a merged native stderr (`2>&1`) is a terminating
      `NativeCommandError` under `Stop`, and a refused `Out-File` (ACL, disk,
      missing directory) is a non-terminating error under `Continue` whose `$?`
      is then folded into a non-zero code by the rule below — instead of aborting
      the runner before the marker or reporting a fake success;
    * the payload is a **child** process, so its `exit N` leaves only that child.

    The marker is written atomically (`Set-Content` to `.tmp`, then an overwriting
    `[IO.File]::Move`), so a poll can never read a half-written `EXITCODE=`; the
    parser additionally requires the terminator the writer always emits.
    """
    cleanup = f"{files_before}\r\n" if files_before else ""
    return (
        "$ErrorActionPreference='Stop'\r\n"
        + remove_script(log_path, marker_path, marker_path + ".tmp").replace(
            "\n", "\r\n"
        )
        + cleanup
        + "$ErrorActionPreference='Continue'\r\n"
        + f"& powershell -NoProfile -ExecutionPolicy Bypass "
        f"-File {ps_quote(payload)} 2>&1 | "
        f"Out-File -LiteralPath {ps_quote(log_path)} -Append -Encoding utf8\r\n"
        + _exit_rule().replace("\n", "\r\n")
        + "$ErrorActionPreference='Stop'\r\n"
        + f"Set-Content -LiteralPath {ps_quote(marker_path + '.tmp')} -Value "
        f'("{_MARKER_TOKEN}" + $abfCode) -Encoding ascii\r\n'
        + replace_script(marker_path).replace("\n", "\r\n")
    )


def parse_exitcode(marker: str) -> int | None:
    """Parse the `EXITCODE=<n>` the task runner writes into its marker.

    Returns None when the marker is empty, lacks the token, carries anything
    after it, or was read mid-write. The runner writes the marker atomically and
    always terminates the value with a newline, so `EXITCODE=1` without that
    newline is a truncated read (`...=10` unfinished) and must keep polling
    instead of reporting the prefix as the code.
    """
    match = _MARKER_RE.search(marker)
    return int(match.group(1)) if match else None


__all__ = [
    "RunPaths",
    "check_name",
    "parse_exitcode",
    "payload_footer",
    "remove_script",
    "run_paths",
    "run_token",
    "runner_script",
]
