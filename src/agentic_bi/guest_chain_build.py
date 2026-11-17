"""Guest build stage: stage the framework, run the builder, fetch the result.

The chain's middle stage, separated from the orchestrator so the verdict logic
stays readable. It owns the framework zip layout, the builder command line, and
the guest-side build invocation, but not the VM lifecycle or the oracle.

Public API:
    stage_framework(repo, dest_zip)      - zip the runtime pieces at archive root
    build_script(cfg, guest_pbix)        - the interactive-task body
    run_build(transport, cfg, deadline, result) -> bool
    tail(text, limit)                    - last characters, single-lined
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

from agentic_bi.guest_task_script import remove_script, run_token
from agentic_bi.guest_transport import Deadline, StageError, ps_quote
from agentic_bi.guest_types import desktop_bin
from agentic_bi.guest_winrm_commands import publish_copy_script

if TYPE_CHECKING:  # avoid a runtime cycle with the orchestrator
    from agentic_bi.guest_chain import ChainConfig, ChainResult
    from agentic_bi.guest_transport import GuestConfig, WinRMTransport

# Size exception (>300 lines): one stage's PowerShell templates and the
# ordering of the build steps read as a unit; splitting the module would put a
# command and the check that guards it in different files.

logger = logging.getLogger(__name__)

_TASK = "agentic_bi_board"
_RUNTIME = ("src", "examples", "templates", "pyproject.toml", "README.md")


def _ascii_entry(value: str, *, what: str) -> str:
    """Return `value` when it is ASCII-only, else raise `StageError` loudly.

    The embeddable interpreter reads `python312._pth` as ASCII (that is its
    format), so a non-ASCII entry such as a Cyrillic user or directory name can
    never resolve there. Windows PowerShell 5.1's default `Add-Content` encoding
    is ANSI, so writing it anyway would leave bytes the interpreter cannot import
    — and the failure would surface much later as a missing module. Refusing on
    the host, before anything is written, keeps the cause in the message.

    Raises:
        StageError: when `value` contains a non-ASCII character.
    """
    try:
        value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise StageError(
            f"{what} {value!r} is not ASCII: the embeddable interpreter reads "
            "`._pth` as ASCII, so the entry would be written as broken bytes. "
            "Use an ASCII guest root (e.g. C:\\pbi\\abf); nothing was written."
        ) from exc
    return value


def _register_on_path(guest: GuestConfig) -> str:
    """The PowerShell that puts `<root>\\src` on the embeddable interpreter's path.

    The `._pth` file sits next to the configured interpreter and the appended
    entry is the configured root, so overriding `AGENTIC_BI_GUEST_ROOT` or
    `AGENTIC_BI_GUEST_PYTHON` stays consistent (a hardcoded path here would keep
    pointing at the default root while the framework is staged elsewhere).

    The guest paths are Windows paths and the host may be macOS, so the
    interpreter directory is split on `\\` rather than with `pathlib` (whose
    separators are host-specific).

    Three properties are pinned here, because each one used to stage a silently
    broken interpreter:

    * every path argument is `-LiteralPath`: a configured root containing `[`,
      `]` or `*` is a legal path but a wildcard pattern to `-Path`;
    * a missing `._pth` is a loud `throw` **before** the read, instead of a
      `Select-String` on nothing and an `Add-Content` that creates a stray file
      next to the interpreter;
    * `-Pattern` is paired with `-SimpleMatch` (a Windows path is not a valid
      regex) and the entry is ASCII-checked on the host and written with
      `-Encoding ASCII`, never in the ANSI default that mangles non-ASCII bytes.

    Raises:
        StageError: when the source path to append is not ASCII.
    """
    py_dir = guest.python.rsplit("\\", 1)[0] if "\\" in guest.python else guest.python
    pth = f"{py_dir}\\python312._pth"
    src = _ascii_entry(f"{guest.root}\\src", what="guest source path")
    return (
        "$ErrorActionPreference='Stop'\n"
        f"$pth={ps_quote(pth)}\n"
        f"if (-not (Test-Path -LiteralPath $pth)) "
        f"{{ throw ('the interpreter path file ' + $pth + ' is missing; the "
        f"framework cannot be put on PYTHONPATH') }}\n"
        f"if (-not (Select-String -LiteralPath $pth -Pattern {ps_quote(src)} "
        f"-SimpleMatch -Quiet)) "
        f"{{ Add-Content -LiteralPath $pth -Value {ps_quote(src)} -Encoding ASCII }}\n"
    )


def chain_lock_script(out_dir: str, timeout: int) -> str:
    """The PowerShell that takes a per-guest chain lock, or refuses the run.

    The staging step is **not** idempotent: `extract_zip` removes the staged tree
    and `abf.zip` has one name per guest, so two chains that reach this stage at
    the same time corrupt each other (one wipes the tree the other's builder is
    importing from, and a concurrent upload makes the other's SHA-256 probe fail).
    Every other artifact is per-run; the staged framework cannot be, because the
    interpreter's `._pth` entry is global. A lock serialises the chains instead.

    `[IO.File]::Open(..., CreateNew, ...)` is an atomic `CreateFile`, so the two
    chains cannot both win. A lock older than `timeout` seconds is stale (the
    owning chain cannot outlive its own budget) and is taken over.

    Raises:
        StageError: never here; a live lock surfaces as a `ps()` failure.
    """
    lock = f"{out_dir}\\abf.chain.lock"
    timeout_ms = max(1, int(timeout)) * 1000
    return (
        "$ErrorActionPreference='Stop'\n"
        f"$lock={ps_quote(lock)}\n"
        "$tryNew = { param($p) "
        "$f=[IO.File]::Open($p,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,"
        "[IO.FileShare]::None); $b=[Text.Encoding]::UTF8.GetBytes("
        "([DateTime]::UtcNow.ToString('o'))); $f.Write($b,0,$b.Length); $f.Close() }\n"
        "$ok=$false\n"
        "if (-not (Test-Path -LiteralPath $lock)) { & $tryNew $lock; $ok=$true }\n"
        "if (-not $ok) {\n"
        "  $age=((Get-Date).ToUniversalTime() - "
        "(Get-Item -LiteralPath $lock).LastWriteTimeUtc).TotalMilliseconds\n"
        f"  if ($age -lt {timeout_ms}) {{ throw ('another guest chain holds ' + "
        "$lock + ' (' + [int]$age + ' ms old); refusing to stage concurrently') }\n"
        "  [IO.File]::Delete($lock)\n"
        "  & $tryNew $lock\n"
        "}\n"
    )


def tail(text: str, limit: int = 600) -> str:
    """The last `limit` characters of `text`, single-lined for the log."""
    flat = " ".join(text.split())
    return flat[-limit:]


def stage_framework(repo: Path, dest_zip: Path) -> None:
    """Zip the runtime pieces of `repo` at the archive root (no nesting level)."""
    repo = Path(repo)
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in _RUNTIME:
            src = repo / name
            if src.is_file():
                zf.write(src, name)
                continue
            for path in sorted(src.rglob("*")):
                if "__pycache__" in path.parts or path.suffix == ".pyc":
                    continue
                if path.is_file():
                    zf.write(path, str(path.relative_to(repo)))


def build_script(cfg: ChainConfig, guest_pbix: str) -> str:
    """The interactive-task body: run the builder, printing to stdout/stderr.

    Every interpolated value is rendered with `ps_quote`, so a builder name,
    table, title or path containing a quote cannot break out of its literal and
    inject a statement into the highest-privilege interactive task.

    Completion is signalled by the marker file the runner writes afterwards, not
    by a string in this output (see `WinRMTransport.run_task` for why).

    The body does **not** write the log: the runner is the single owner of that
    file and captures this child's stdout and stderr. A second `Out-File` on the
    same path holds it open with `FileShare.Read`, so the runner's redirect is
    refused and the whole builder output is lost. The merged `2>&1` stays, so
    native stderr reaches the runner's redirect as well.
    """
    guest = cfg.guest
    root = guest.root
    # `GuestConfig.desktop` is where the configuration says Desktop is installed
    # (`PBI_RS_DESKTOP`); `desktop_bin` accepts either the executable or the bin
    # directory, so one variable serves the build (PBI_RS_BIN) and the oracle.
    bin_dir = desktop_bin(guest.desktop)
    template = f"{root}\\templates\\template.pbix"
    src = f"{root}\\src"
    builder_path = f"{root}\\examples\\{cfg.builder}"
    data_path = f"{root}\\examples\\{Path(cfg.data).name}"
    title_flag = f" --title {ps_quote(cfg.title)}" if cfg.title else ""
    return (
        "$ErrorActionPreference='Continue'\n"
        f"$env:PBI_RS_BIN={ps_quote(bin_dir)}\n"
        f"$env:PBI_RS_TEMPLATE={ps_quote(template)}\n"
        f"$env:PYTHONPATH={ps_quote(src)}\n"
        f"& {ps_quote(guest.python)} {ps_quote(builder_path)} "
        f"--data {ps_quote(data_path)} "
        f"--table {ps_quote(cfg.table)} "
        f"--template {ps_quote(template)} "
        f"--out {ps_quote(guest_pbix)}{title_flag} 2>&1\n"
    )


def run_build(
    transport: WinRMTransport,
    cfg: ChainConfig,
    deadline: Deadline,
    result: ChainResult,
) -> bool:
    """Stage the framework, run the build task; True only on exit 0 + a new file.

    The build's own exit code is authoritative: a non-zero code is a failure even
    when a `.pbix` exists, because this run's own output path is deleted before
    the task starts so an earlier run's artifact cannot be mistaken for this one's.
    A failed run therefore leaves the previous **final** `.pbix` in place; the
    chain does not pull it because the verdict is already `NOT_BUILT`.

    The builder writes to a **per-run** path (`<stem>.<token>.pbix`), so the
    pre-run cleanup (`files_before`) can only ever delete this run's own file:
    two concurrent builds previously targeted the same final `.pbix`, and the
    second run's cleanup deleted the first run's freshly produced artifact. Only a
    finished, non-empty build is **copied** onto the caller's declared output
    (`<guest.out>\\<cfg.out.name>`), which stays a convenience for humans and is
    last-writer-wins between concurrent chains. The per-run file itself survives
    the publish, because that is exactly the path the chain pulls
    (`guest_chain.build_dashboard`); a move there deleted the pull source. The
    copy stages under this run's own token, so two concurrent publishes of the
    same declared name never share a staging file.

    The staging step itself is serialised by a guest lock (see
    `chain_lock_script`): `extract_zip` removes a shared tree, so concurrent
    chains would otherwise delete each other's framework mid-build.
    """
    tmp = Path(tempfile.mkdtemp(prefix="abf-chain-"))
    try:
        guest = cfg.guest
        # `-LiteralPath`: `guest.out` comes from the configuration and may contain
        # `[`/`]`/`*`, which `-Path` would read as a wildcard pattern. `Stop` makes
        # a failed creation a stage failure instead of a silent non-terminating
        # error that still exits 0.
        # `[IO.Directory]::CreateDirectory` instead of `New-Item -LiteralPath`:
        # idempotent, bare of wildcard semantics, and safe on Windows PowerShell
        # 5.1 (there `New-Item` does not document `-LiteralPath`, and a failed
        # parameter binding would break the whole staging stage).
        transport.ps(
            "$ErrorActionPreference='Stop'\n"
            f"[IO.Directory]::CreateDirectory({ps_quote(guest.out)}) | Out-Null\n"
        )
        # One chain per guest at a time: the staging tree and `abf.zip` are
        # shared, and `extract_zip` removes the tree another chain may be
        # importing from. Released in the `finally` below.
        lock = f"{guest.out}\\abf.chain.lock"
        transport.ps(chain_lock_script(guest.out, cfg.timeout))
        try:
            return _stage_and_build(transport, cfg, deadline, result, tmp)
        finally:
            try:
                transport.ps(remove_script(lock), attempts=1)
            except Exception:  # noqa: BLE001 - leaving the lock is a warning
                logger.warning("could not release the guest chain lock %s", lock)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _stage_and_build(
    transport: WinRMTransport,
    cfg: ChainConfig,
    deadline: Deadline,
    result: ChainResult,
    tmp: Path,
) -> bool:
    """Stage, build and publish; the body of `run_build` under the chain lock."""
    guest = cfg.guest
    zip_path = tmp / "abf.zip"
    stage_framework(cfg.repo, zip_path)
    entries = len(zipfile.ZipFile(zip_path).namelist())
    result.record("stage", f"framework {zip_path.stat().st_size} B, {entries} files")

    guest_zip = f"{guest.out}\\abf.zip"
    transport.push_file(zip_path, guest_zip, deadline)
    files = transport.extract_zip(guest_zip, guest.root, expected=entries)
    transport.ps(_register_on_path(guest))
    result.record("stage", f"framework extracted on guest ({files} files)")

    guest_pbix = f"{guest.out}\\{cfg.out.name}"
    token = run_token()
    build_pbix = f"{guest.out}\\{cfg.out.stem}.{token}.pbix"
    transport.push_file(
        Path(cfg.data).resolve(),
        f"{guest.root}\\examples\\{Path(cfg.data).name}",
        deadline,
    )
    log, code = transport.run_task(
        name=_TASK,
        script=build_script(cfg, build_pbix),
        files_before=remove_script(build_pbix),
        deadline=deadline,
    )
    result.record("build", f"exit={code} {tail(log)}")
    if code != 0:
        return False
    size = transport.ps(
        "$ErrorActionPreference='Stop'\n"
        f"if (Test-Path -LiteralPath {ps_quote(build_pbix)}) "
        f"{{ (Get-Item -LiteralPath {ps_quote(build_pbix)}).Length }} "
        "else { 0 }"
    )
    # A warning line before the number (`int("WARNING...")`) used to raise a
    # bare `ValueError`; the last all-digit line is the answer, exactly like
    # the file count in `extract_zip`.
    digits = [line.strip() for line in size.splitlines() if line.strip().isdigit()]
    if not digits:
        raise StageError(f"could not read the size of {build_pbix}: {tail(size)!r}")
    if not int(digits[-1]):
        result.record("build", "exit 0 but no .pbix produced")
        return False
    # The chain pulls `build_pbix` (this run's own file); the published copy
    # under the declared name is a convenience for humans and is
    # last-writer-wins between concurrent chains. The publish must be a
    # **copy**: a move consumed this file, so the pull that follows read a
    # missing path and wrote 0 bytes over the previous local artifact.
    result.guest_build = build_pbix
    transport.ps(publish_copy_script(build_pbix, guest_pbix, token=token))
    # Verify *this run's* file, not the shared published name: a concurrent
    # chain can overwrite `<out>\<name>` between publish and probe, so a size
    # there proves only that some build exists. A missing per-run file means
    # the publish consumed the pull source — the exact defect being guarded.
    kept = transport.ps(
        "$ErrorActionPreference='Stop'\n"
        f"if (Test-Path -LiteralPath {ps_quote(build_pbix)}) "
        f"{{ (Get-Item -LiteralPath {ps_quote(build_pbix)}).Length }} "
        "else { 0 }"
    )
    kept_digits = [line.strip() for line in kept.splitlines() if line.strip().isdigit()]
    if not kept_digits or not int(kept_digits[-1]):
        raise StageError(
            f"publishing {guest_pbix} consumed this run's build "
            f"{build_pbix}; the chain would pull a missing file: {tail(kept)!r}"
        )
    return True


__all__ = [
    "build_script",
    "chain_lock_script",
    "run_build",
    "stage_framework",
    "tail",
]
