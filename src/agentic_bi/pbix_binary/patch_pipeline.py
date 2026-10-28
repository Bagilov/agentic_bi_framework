"""Member-level patching of a `.pbix` container (equal and uneven length).

The `.pbix` is an OPC (zip) package whose `DataModel` member holds the binary
model (ABF, XPress9-framed). Two kinds of edits are supported:

* **Equal length** — an in-place byte substitution inside the ABF. Mutable
  offsets are untouched, so the buffer can be written straight back.
* **Uneven length** — replacing or adding a *member* whose payload differs in
  size. The ABF indexes no longer describe the buffer, so it is re-laid
  (`abf_relayout`) and re-framed (`abf_codec`), then swapped into the container.

The container swap is size-safe: it rewrites the CRC/size fields, the central
directory and the local-header offsets of every member stored after the
`DataModel` (which need not be the last member).

Patch kinds (a JSON spec is a list of objects):
    {"kind": "replace", "find": "<utf-16 text>", "with": "<same-length text>"}
    {"kind": "replace_hex", "find": "<hex>", "with": "<same-length hex>"}
    {"kind": "replace_member", "member": "<logical name>", "path": "<file>"}
    {"kind": "replace_member", "member": "<logical name>", "data": "<base64>"}

Equal-length patches must match exactly one site unless `occurrence` picks one
(`0`-based index) or `all` replaces every match; an ambiguous patch is an error
rather than a silent edit of the first match.

The written output is re-read and re-parsed before `apply_patches` returns, so a
patch can never report success while producing an unparseable `DataModel`.

Public API:
    PatchError
    classify_patches(patches) -> (even, uneven)
    apply_patches(pbix, patches, out) -> PatchReport
    swap_datamodel(template, datamodel, out) -> int  (re-exported)
"""

from __future__ import annotations

import base64
import json
import logging
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentic_bi.engine_container import swap_datamodel
from agentic_bi.pbix_binary import abf_codec, abf_relayout

logger = logging.getLogger(__name__)

__all__ = [
    "PatchError",
    "PatchReport",
    "apply_patches",
    "classify_patches",
    "load_spec",
    "swap_datamodel",
]


class PatchError(ValueError):
    """Raised for an invalid patch spec or an unmatchable pattern."""


@dataclass
class PatchReport:
    """Outcome of `apply_patches`: output path, size and an edit log."""

    out: Path
    size: int
    abf_size: int
    log: list[str] = field(default_factory=list)


def classify_patches(patches: list[dict[str, Any]]) -> tuple[list, list]:
    """Split patches into (equal-length pairs, uneven member patches).

    Equal-length patches stay byte-in-place; uneven member patches need a full
    container re-layout. A length-changing text/hex patch is rejected: it would
    shift the stream and silently corrupt the indexes.

    Raises:
        PatchError: for an unknown patch kind or a length-changing byte patch.
    """
    even: list[tuple[bytes, bytes, object]] = []
    uneven: list[dict[str, Any]] = []
    for patch in patches:
        kind = patch.get("kind", "replace")
        if kind in ("replace", "replace_hex"):
            if kind == "replace":
                find = patch["find"].encode("utf-16le")
                with_ = patch["with"].encode("utf-16le")
            else:
                find = bytes.fromhex(patch["find"])
                with_ = bytes.fromhex(patch["with"])
            if len(find) != len(with_):
                raise PatchError(
                    f"patch kind {kind!r} changes length; use 'replace_member' "
                    "for uneven-length content"
                )
            even.append((find, with_, patch.get("occurrence")))
        elif kind == "replace_member":
            uneven.append(patch)
        else:
            raise PatchError(f"unknown patch kind: {kind!r}")
    return even, uneven


def _member_payload(patch: dict[str, Any]) -> tuple[str, bytes]:
    member = patch.get("member") or patch.get("file")
    if not member:
        raise PatchError("'replace_member' needs a 'member' name")
    if "path" in patch:
        return member, Path(patch["path"]).read_bytes()
    if "data" in patch:
        return member, base64.b64decode(patch["data"])
    raise PatchError(f"'replace_member' {member!r} needs 'path' or 'data'")


def _occurrences(
    abf: bytes | bytearray, find: bytes, *, limit: int | None = None
) -> list[int]:
    """Up to `limit` start offsets where `find` occurs, scanned non-overlapping.

    The scan resumes at `start + len(find)`, so matches never overlap (an overlap
    would let `occurrence: "all"` rewrite bytes a previous match already rewrote)
    and a run of the same byte is not miscounted as many sites. `limit` stops the
    scan early: callers that only need "is it ambiguous" or "the n-th site" do not
    pay for a full-buffer enumeration of a short, repeated pattern.
    """
    offsets: list[int] = []
    start = 0
    while limit is None or len(offsets) < limit:
        start = abf.find(find, start)
        if start < 0:
            break
        offsets.append(start)
        start += len(find)
    return offsets


def _select_offsets(
    abf: bytes | bytearray, find: bytes, occurrence: object
) -> list[int]:
    """Resolve which occurrence(s) of `find` a patch applies to.

    Raises:
        PatchError: when `find` is absent, when multiple sites match and neither
            `occurrence` nor `all` says which to take, or when `occurrence` is
            out of range. Guessing (first match) is what silently edits the wrong
            bytes, so ambiguity is an error here.
    """
    if occurrence == "all":
        offsets = _occurrences(abf, find)
        if not offsets:
            raise PatchError(f"pattern not found: {find[:40]!r}")
        return offsets
    if occurrence is None:
        offsets = _occurrences(abf, find, limit=2)
        if not offsets:
            raise PatchError(f"pattern not found: {find[:40]!r}")
        if len(offsets) > 1:
            total = len(_occurrences(abf, find))
            raise PatchError(
                f"pattern {find[:40]!r} matches {total} sites; set "
                "'occurrence' (0-based index) or 'all' to choose"
            )
        return offsets
    if isinstance(occurrence, bool) or not isinstance(occurrence, int):
        raise PatchError(f"'occurrence' must be an int or 'all', got {occurrence!r}")
    if occurrence < 0:
        raise PatchError(f"'occurrence' must be >= 0, got {occurrence}")
    offsets = _occurrences(abf, find, limit=occurrence + 1)
    if not offsets:
        raise PatchError(f"pattern not found: {find[:40]!r}")
    if occurrence >= len(offsets):
        total = len(_occurrences(abf, find))
        raise PatchError(f"'occurrence' {occurrence} out of range ({total} match(es))")
    return [offsets[occurrence]]


def _apply_even(
    abf: bytearray, even: list[tuple[bytes, bytes, object]], log: list[str]
) -> None:
    for find, with_, occurrence in even:
        for index in _select_offsets(abf, find, occurrence):
            abf[index : index + len(find)] = with_
            log.append(f"replace: {len(find)} B at offset {index}")


def _verify_output(out: Path) -> None:
    """Re-read the written `.pbix` and confirm its `DataModel` still parses.

    `swap_datamodel` only proves the archive is a valid zip; this proves the
    model inside it is intact. It is the guard that turns any future writer bug
    (e.g. an unescaped member path) into a loud failure instead of a file that
    Power BI cannot open.

    Raises:
        PatchError: when the output cannot be re-read or its ABF index is broken.
    """
    try:
        with zipfile.ZipFile(out) as z:
            datamodel = z.read("DataModel")
        abf = abf_codec.decompress_datamodel(datamodel)
        abf_relayout.parse_abf_index(abf)
    except PatchError:
        raise
    except Exception as exc:
        raise PatchError(f"written .pbix failed self-verification: {exc}") from exc


def apply_patches(pbix: Path, patches: list[dict[str, Any]], out: Path) -> PatchReport:
    """Apply a patch list to a `.pbix` and write `out`.

    Equal-length patches are applied in place on the decompressed ABF; uneven
    member patches trigger one re-layout of the whole buffer. The result is
    re-framed and swapped into a copy of the container, then re-read and verified
    before returning.

    Args:
        pbix: the source `.pbix` (its DataModel is the base).
        patches: the patch list (see the module docstring for kinds).
        out: the destination `.pbix`.

    Returns:
        PatchReport with the output path, container/ABF sizes and an edit log.

    Raises:
        PatchError: on an invalid spec, an unmatched or ambiguous pattern, or an
            output that fails self-verification.
    """
    pbix = Path(pbix)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)

    even, uneven = classify_patches(patches)
    datamodel = _read_member(pbix, "DataModel")
    abf = bytearray(abf_codec.decompress_datamodel(datamodel))
    log: list[str] = []

    _apply_even(abf, even, log)

    if uneven:
        replace: dict[str, bytes] = {}
        for patch in uneven:
            member, payload = _member_payload(patch)
            replace[member] = payload
            log.append(f"replace_member {member}: {len(payload)} B")
        result = abf_relayout.relayout_abf(bytes(abf), replace=replace)
        abf = bytearray(result.data)
        log.extend(result.log)

    new_datamodel = abf_codec.compress_datamodel(bytes(abf))
    size = swap_datamodel(pbix, new_datamodel, out)
    _verify_output(out)
    logger.info("apply_patches: %s -> %s (%d B)", pbix.name, out.name, size)
    return PatchReport(out=out, size=size, abf_size=len(abf), log=log)


def load_spec(path: Path) -> list[dict[str, Any]]:
    """Load a patch list from a JSON document (`{"patches": [...]}` or a list)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    patches = data.get("patches") if isinstance(data, dict) else data
    if not isinstance(patches, list):
        raise PatchError("patch spec must be a list or {'patches': [...]}")
    return patches


def _read_member(pbix: Path, name: str) -> bytes:
    with zipfile.ZipFile(pbix) as z:
        return z.read(name)
