"""PowerShell source builders for the WinRM channel, kept inside its size cap.

Every script the channel sends reaches the guest as one
`powershell -EncodedCommand <base64>` line, and a line that is too long is
truncated by the guest ("The command line is too long") or garbled, which used to
surface as an unexplained non-zero exit far from the cause. The cap is therefore
enforced in exactly one place — `encoded_size`/`check_size`, called from
`WinRMChannel.ps` — and the chunked writer derives its payload budget from the
real command template for the target path, so no command this package emits can
be the one that overflows.

`MAX_ENCODED_COMMAND` is 6000. The Windows PowerShell command line tops out near
8191 characters and the encoded payload is what counts against it, so 6000 leaves
about 27% headroom for `powershell.exe`, `-NoProfile`, the WinRM wrapper and
quoting, while still carrying roughly 1.5 KiB of payload per chunk command.
The previous chunk limit was measured against the payload only, so the final
`Replace`/`Move` command for an 85-character path was ~2360 encoded characters
and was never checked at all.

Public API:
    MAX_ENCODED_COMMAND                     - the one cap every command satisfies
    encoded_size(script)                    - the payload length the guest sees
    check_size(script)                      - raise `StageError` over the cap
    publish_script(src, dst)                - atomic move of `src` onto `dst`
    publish_copy_script(src, dst)           - atomic copy, `src` survives
    replace_script(guest_path)              - atomic `<path>.tmp` -> `<path>`
    write_chunk_script(tmp, piece, offset=)  - one idempotent chunk write
    chunk_budget(guest_path)                - payload bytes that fit one chunk
    split_payload(data, budget)             - UTF-8-safe split, no empty piece
    parent_dir(guest_path)                  - guest directory to create first
"""

from __future__ import annotations

import base64
import ntpath

from agentic_bi.guest_types import StageError, ps_quote

MAX_ENCODED_COMMAND = 6000

#: Cap the chunk solver aims at, leaving headroom under the hard guard for the
#: growing offset literal and for the WinRM wrapper.
_CHUNK_CAP = MAX_ENCODED_COMMAND - 128

#: The UTF-8 preamble. Windows PowerShell 5.1 reads a `-File` script in the ANSI
#: code page unless the file starts with these bytes, and exactly one copy is
#: written: it is part of the first chunk, never emitted by an encoder.
BOM_BYTES = b"\xef\xbb\xbf"

_ENCODING = "utf-16-le"


def encoded_size(script: str) -> int:
    """Length of the `-EncodedCommand` payload `script` becomes on the guest.

    `winrm` encodes the script as UTF-16LE and base64-encodes it, and that base64
    string — not the character count of the script — is what the guest's command
    line carries and truncates.

    Raises:
        ValueError: when `script` is not a string (boundary validation).
    """
    if not isinstance(script, str):
        raise ValueError(
            f"a PowerShell script must be str, got {type(script).__name__}"
        )
    return len(base64.b64encode(script.encode(_ENCODING)))


def check_size(script: str) -> None:
    """Refuse a command the guest would truncate.

    Raises:
        StageError: when the encoded command exceeds `MAX_ENCODED_COMMAND`. The
            guard lives on the single path every script passes through, so a
            caller that builds a command from a long path (the final
            `Replace`/`Move`, `read_text`, `remove_script`, `extract_zip`) fails
            loudly here instead of having the guest run a cut-off script.
    """
    size = encoded_size(script)
    if size > MAX_ENCODED_COMMAND:
        raise StageError(
            f"PowerShell command is {size} encoded characters, over the "
            f"{MAX_ENCODED_COMMAND}-character cap; the guest would truncate it "
            f"(starts with {script[:60]!r})"
        )


def publish_script(src: str, dst: str) -> str:
    """PowerShell that moves `src` onto `dst` atomically, keeping `dst` valid.

    The target is either the previous complete file or the new complete file: it
    is never absent because of this helper. `[IO.File]::Replace` is the atomic
    overwrite on .NET Framework — the **three-argument** `[IO.File]::Move`
    overload is .NET Core only, and Windows PowerShell 5.1 runs on .NET
    Framework, so every move here is the two-argument form. When a volume does
    not implement replace semantics, the fallback renames the target to
    `<dst>.bak`, moves the new file in, and renames the backup back before
    rethrowing if that move fails; the original `Replace` failure is preserved by
    `throw`, not swallowed.

    Every removal is guarded by `Test-Path`: `-EA SilentlyContinue` does not
    override an enclosing `$ErrorActionPreference='Stop'` for a cmdlet that
    cannot find its target, and a throwing cleanup would abort the fallback
    before the new file is in place.

    Paths are assigned to `$s`/`$d`/`$bak` so each appears once per literal: an
    earlier version repeated a quoted path seven times, and a long path alone
    pushed a single command over the encoded-command cap.

    Args:
        src: the file to move into place (usually a `<path>.tmp` staging file).
        dst: the final path.

    Returns:
        The PowerShell source, without a `$ErrorActionPreference` preamble.
    """
    bak = f"{dst}.bak"
    return (
        f"$s={ps_quote(src)}\n"
        f"$d={ps_quote(dst)}\n"
        f"$b={ps_quote(bak)}\n"
        "if ([IO.File]::Exists($d)) {\n"
        "  try { [IO.File]::Replace($s,$d,$null) }\n"
        "  catch {\n"
        f"    if (Test-Path -LiteralPath $b) {{ Remove-Item -LiteralPath $b -Force }}\n"
        "    [IO.File]::Move($d,$b)\n"
        "    try { [IO.File]::Move($s,$d) }\n"
        "    catch { [IO.File]::Move($b,$d); throw }\n"
        f"    if (Test-Path -LiteralPath $b) {{ Remove-Item -LiteralPath $b -Force }}\n"
        "  }\n"
        "} else { [IO.File]::Move($s,$d) }\n"
    )


def publish_copy_script(src: str, dst: str, *, token: str | None = None) -> str:
    """PowerShell that copies `src` onto `dst` atomically, keeping `src`.

    `publish_script` is a **move**, and a build stage that used it deleted the
    per-run `.pbix` before the chain could pull it: `pull_file` then read a
    missing path as an empty file, wrote 0 bytes over the previous good local
    artifact and still reported `BUILT`. This copies to a staging name next to
    `dst` first, so a half-written copy never becomes the published file, and
    then applies the same atomic `Replace`/`Move` as `publish_script`.

    The copy is `[IO.File]::Copy` with the `overwrite` overload, which exists on
    .NET Framework (unlike the three-argument `Move`), so it is safe on Windows
    PowerShell 5.1. A failed copy removes its partial staging file and rethrows,
    so the failure is loud instead of leaving a truncated `.publish.tmp` behind.

    The staging name must be unique per chain, so `token` (the same run token the
    build used) is appended: two chains publishing the same declared name
    otherwise share `<dst>.publish.tmp`, and the `FileShare.None` copy of one plus
    the cleanup `Remove-Item` of the other fails a publish that was fine on its
    own.

    Args:
        src: the finished file to copy; it remains in place for the caller.
        dst: the published path.
        token: an ASCII alphanumeric run token that makes the staging name unique;
            None keeps the single-chain `<dst>.publish.tmp` name.

    Raises:
        ValueError: when `token` is not ASCII alphanumeric (it becomes part of a
            guest file name and must not carry separators or quoting).

    Returns:
        The PowerShell source, which carries its own `$ErrorActionPreference`
        preamble and can be sent as one command.
    """
    if token is not None and not (token.isascii() and token.isalnum()):
        raise ValueError(f"a publish token must be ASCII alphanumeric, got {token!r}")
    suffix = f".{token}" if token else ""
    tmp = f"{dst}{suffix}.publish.tmp"
    return (
        "$ErrorActionPreference='Stop'\n"
        f"$src={ps_quote(src)}\n"
        f"$stg={ps_quote(tmp)}\n"
        "try { [IO.File]::Copy($src,$stg,$true) }\n"
        "catch {\n"
        "  if ([IO.File]::Exists($stg)) "
        "{ Remove-Item -LiteralPath $stg -Force }\n"
        "  throw\n"
        "}\n" + publish_script(tmp, dst)
    )


def replace_script(guest_path: str) -> str:
    """PowerShell that moves `<guest_path>.tmp` onto `guest_path` atomically.

    The `<path>.tmp` staging convention this wraps is used by `write_text`; see
    :func:`publish_script` for the actual guarantee.
    """
    return publish_script(f"{guest_path}.tmp", guest_path)


def write_chunk_script(tmp: str, piece: bytes, *, offset: int) -> str:
    """PowerShell that writes one base64-encoded chunk at a fixed byte `offset`.

    The write is **idempotent**: the file is opened for update, trimmed back to
    `offset` and then written from there, so a retried command (WinRM retries up
    to four times on a lost response) rewrites the same bytes instead of
    appending a duplicate block. The previous implementation used
    `AppendAllText`, where a retry silently doubled a ~1.5 KiB slice and left a
    payload that no longer parsed.

    A file shorter than `offset` means an earlier chunk is missing; that throws
    instead of padding the gap with zero bytes.

    `tmp` is an already-quoted PowerShell literal. The UTF-8 BOM (when the caller
    wants one) travels **inside** the first piece, not as an encoder side effect,
    so the reassembled file has exactly one preamble and every write is raw.

    Raises:
        ValueError: when `piece` is not bytes or `offset` is negative.
    """
    if not isinstance(piece, bytes):
        raise ValueError(f"a chunk must be bytes, got {type(piece).__name__}")
    if offset < 0:
        raise ValueError(f"a chunk offset must not be negative, got {offset}")
    b64 = base64.b64encode(piece).decode("ascii")
    return (
        "$ErrorActionPreference='Stop'\n"
        f"$chunk=[Convert]::FromBase64String('{b64}')\n"
        f"$fs=[IO.File]::Open({tmp},[IO.FileMode]::OpenOrCreate,"
        "[IO.FileAccess]::Write)\n"
        "try {\n"
        f"  if ($fs.Length -lt {offset}) "
        f'{{ throw "chunk gap: file is $($fs.Length) B, expected {offset} B" }}\n'
        f"  $fs.SetLength({offset})\n"
        f"  $fs.Seek({offset},'Begin') | Out-Null\n"
        "  $fs.Write($chunk,0,$chunk.Length)\n"
        "} finally { $fs.Close() }\n"
    )


def chunk_budget(guest_path: str, *, tmp: str | None = None) -> int:
    """UTF-8 payload bytes one chunk command can carry for `guest_path`.

    Derived from the real template, so it accounts for the temp path length, the
    writer/encoder literal and the UTF-16 doubling of the script. The limit is
    solved exactly: the encoded size is `4*ceil(raw/3)` for `raw` UTF-16LE bytes,
    so `overhead + 2*b64 <= 3*(MAX_ENCODED_COMMAND // 4)` bounds the base64
    string, and the byte count whose base64 fits inside that bound is returned.

    Raises:
        StageError: when the path is so long that even an empty chunk command
            would exceed the cap, i.e. the write could not be performed at all.
    """
    quoted_tmp = ps_quote(f"{guest_path}.tmp" if tmp is None else tmp)
    overhead = max(
        len(write_chunk_script(quoted_tmp, b"", offset=0).encode(_ENCODING)),
        len(write_chunk_script(quoted_tmp, b"", offset=9_999_999).encode(_ENCODING)),
    )
    # Leave a margin below the hard cap instead of solving to exactly
    # `MAX_ENCODED_COMMAND`: the offset literal appears twice and grows with the
    # file, so a command that only just fits would fail on the last chunk.
    allowance = 3 * (_CHUNK_CAP // 4) - overhead
    budget = 3 * ((allowance // 2) // 4)
    if budget < 4:
        raise StageError(
            f"{guest_path}: the path is too long to write in chunks inside the "
            f"{MAX_ENCODED_COMMAND}-character encoded-command cap"
        )
    return budget


def split_payload(data: bytes, budget: int) -> list[bytes]:
    """Split encoded UTF-8 `data` into pieces of at most `budget` bytes.

    A character is never split across two chunks: when the cut would land on a
    continuation byte (`10xxxxxx`) the boundary moves back to the start of that
    character, so every piece decodes on its own instead of becoming a
    replacement character on the guest.

    Raises:
        ValueError: when `budget` is below 4 — smaller than the widest UTF-8
            character, where the boundary walk could collapse `end` onto `start`
            and append an empty piece forever — or when a piece would be empty.
    """
    if budget < 4:
        raise ValueError(
            f"chunk budget {budget} is too small: a UTF-8 character needs up to "
            "4 bytes, and a smaller budget can make no progress"
        )
    pieces: list[bytes] = []
    start = 0
    while start < len(data):
        end = min(start + budget, len(data))
        while end > start and end < len(data) and data[end] & 0xC0 == 0x80:
            end -= 1
        if end <= start:
            raise ValueError(f"chunking made no progress at byte {start}")
        pieces.append(data[start:end])
        start = end
    return pieces


def parent_dir(guest_path: str) -> str | None:
    """The guest directory to create before writing `guest_path`, or None.

    Guest paths are Windows paths, so they are split with `ntpath`: a plain
    `rsplit("\\\\")` returned `C:` for `C:\\file.ps1` (creating the drive's
    *current* directory) and returned nothing at all for a path written with
    forward slashes. A bare filename and a drive-relative `C:file.ps1` have no
    directory component and yield None.

    Raises:
        ValueError: when `guest_path` is empty (boundary validation).
    """
    if not guest_path:
        raise ValueError("a guest path must not be empty")
    head = ntpath.dirname(guest_path.replace("/", ntpath.sep))
    if not head or head in (".", ".."):
        return None
    drive, _ = ntpath.splitdrive(head)
    if head == drive:
        return None
    return head


__all__ = [
    "BOM_BYTES",
    "MAX_ENCODED_COMMAND",
    "check_size",
    "chunk_budget",
    "encoded_size",
    "parent_dir",
    "publish_copy_script",
    "publish_script",
    "replace_script",
    "split_payload",
    "write_chunk_script",
]
