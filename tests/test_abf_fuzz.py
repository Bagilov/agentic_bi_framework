"""Mutation fuzzing of the ABF text layers (`abf_model`).

A `.pbix` is external input: a corrupted or truncated member must surface as a
*domain* error (`ET.ParseError`, i.e. a `SyntaxError`, or a `ValueError` from a
decode), never as `IndexError`, `KeyError`, `MemoryError` or an `AssertionError`.
An unstructured crash in a parser is what the plan calls out, because it turns a
bad file into a confusing traceback instead of a report the caller can act on.

Deterministic by construction: a fixed `random.Random(seed)` drives every
mutation, so a failure reproduces from the seed alone. No third-party fuzzer is
added (the project keeps its dependency set small and stdlib-first).
"""

from __future__ import annotations

import random
import xml.etree.ElementTree as ET

import pytest

from agentic_bi.pbix_binary.abf_model import (
    VFile,
    parse_backup_log,
    parse_virtual_directory,
    serialize_backup_log,
    serialize_virtual_directory,
)

# Domain errors a malformed document may legitimately raise. `ET.ParseError` is a
# `SyntaxError`; `UnicodeDecodeError` is a `ValueError`.
DOMAIN_ERRORS = (ET.ParseError, UnicodeDecodeError, ValueError)

SEED = 0xC0FFEE
ITERATIONS = 300


def _mutations(raw: bytes, rng: random.Random) -> list[bytes]:
    """A deterministic set of single-edit mutations of `raw`."""
    out: list[bytes] = []
    for _ in range(ITERATIONS):
        buf = bytearray(raw)
        op = rng.choice(("flip", "truncate", "insert", "delete"))
        if op == "flip" and buf:
            i = rng.randrange(len(buf))
            buf[i] ^= 1 << rng.randrange(8)
        elif op == "truncate" and buf:
            del buf[rng.randrange(len(buf)) :]
        elif op == "insert":
            buf[rng.randrange(len(buf) + 1) : 0] = bytes([rng.randrange(256)])
        elif op == "delete" and buf:
            del buf[rng.randrange(len(buf))]
        out.append(bytes(buf))
    return out


def _assert_only_domain_errors(parse, samples: list[bytes], label: str) -> int:
    """Parse each sample; return how many were accepted unchanged."""
    accepted = 0
    for i, sample in enumerate(samples):
        try:
            parse(sample)
            accepted += 1
        except DOMAIN_ERRORS:
            continue
        except Exception as exc:
            raise AssertionError(
                f"{label}: sample {i} raised {type(exc).__name__}: {exc!r}"
            ) from exc
    return accepted


def test_the_virtual_directory_never_raises_a_structural_error() -> None:
    raw = serialize_virtual_directory(
        [VFile(path=f"Data/m{i}.dat", size=i * 8, offset=i * 16) for i in range(4)]
    )
    rng = random.Random(SEED)
    accepted = _assert_only_domain_errors(
        parse_virtual_directory, _mutations(raw, rng), "virtual_directory"
    )
    # Most single-bit edits break the XML, but a handful stay valid text; the
    # point is that none of them crashes with a structural error.
    assert accepted < ITERATIONS


def test_the_backup_log_never_raises_a_structural_error() -> None:
    log = parse_backup_log(_backup_log_bytes())
    raw = serialize_backup_log(log)
    rng = random.Random(SEED + 1)
    _assert_only_domain_errors(parse_backup_log, _mutations(raw, rng), "backup_log")


def test_truncation_at_every_prefix_is_a_domain_error() -> None:
    """Every strict prefix of a valid document must fail as a domain error."""
    raw = serialize_virtual_directory([VFile(path="Data/m.dat", size=4096, offset=128)])
    for end in range(len(raw)):
        try:
            parse_virtual_directory(raw[:end])
        except DOMAIN_ERRORS:
            continue
        except Exception as exc:
            raise AssertionError(
                f"prefix len={end} raised {type(exc).__name__}"
            ) from exc


@pytest.mark.parametrize("size", [0, 1, 2, 8, 128])
def test_short_garbage_buffers_are_domain_errors(size: int) -> None:
    rng = random.Random(size)
    blob = bytes(rng.randrange(256) for _ in range(size))
    for parse in (parse_virtual_directory, parse_backup_log):
        with pytest.raises(DOMAIN_ERRORS):
            parse(blob)


def _backup_log_bytes() -> bytes:
    """A minimal engine-shaped backup_log document (UTF-16 with one BOM)."""
    root = ET.Element("BackupLog")
    groups = ET.SubElement(root, "FileGroups")
    node = ET.SubElement(groups, "FileGroup")
    ET.SubElement(node, "Class").text = "100069"
    ET.SubElement(node, "PersistLocationPath").text = "C:\\ws\\Data\\"
    file_list = ET.SubElement(node, "FileList")
    entry = ET.SubElement(file_list, "BackupFile")
    ET.SubElement(entry, "Path").text = "Data/m.dat"
    ET.SubElement(entry, "StoragePath").text = "Data\\m.dat"
    ET.SubElement(entry, "Size").text = "4096"
    ET.SubElement(entry, "LastWriteTime").text = "1700000000"
    return ("\ufeff" + ET.tostring(root, encoding="unicode")).encode("utf-16-le")
