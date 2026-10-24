"""End-to-end check of the two binary-layer defects through the real CLI.

Runs the shipped `agentic-bi-pbix-patch` (not an internal function) against a real
copy of `templates/template.pbix` and inspects the bytes it writes. Two scenarios:

* ``escape`` (D-1) — the donor's virtual directory holds a validly-escaped member
  path (an ``&amp;``, decoded by the parser to a real ``&``, as any workspace path
  like ``R&D`` would be). A legitimate uneven-member patch is applied.
* ``ambiguous`` (D-3) — a byte patch whose pattern matches thousands of sites,
  with no ``occurrence`` given.

For each scenario the same command is run against the pre-fix sources (a git
worktree at HEAD) and the working tree, and the resulting `.pbix` is opened and
verified independently. Prints a verdict per case.

Usage:
    python other/e2e-verification/binary_e2e.py <prefix-src-dir>
"""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
VENV_PY = REPO / ".venv" / "bin" / "python"
DONOR = REPO / "templates" / "template.pbix"
WORK = Path(__file__).resolve().parent / "bin"
PREFIX_SRC = Path(sys.argv[1]).resolve()

sys.path.insert(0, str(REPO / "src"))
from agentic_bi.pbix_binary import abf_codec, abf_relayout  # noqa: E402


def _escaped_donor(donor: Path, out: Path, storage: str, escaped: str) -> Path:
    """Copy `donor` with one vdir path swapped for an equal-length escaped form."""
    with zipfile.ZipFile(donor) as z:
        items = {n: z.read(n) for n in z.namelist()}
    abf = abf_codec.decompress_datamodel(items["DataModel"])
    idx = abf_relayout.parse_abf_index(abf)
    start, end = idx.header.vdir_offset, idx.header.vdir_offset + idx.header.vdir_size
    vdir = abf[start:end]
    if storage.encode() not in vdir:
        raise SystemExit(f"{storage!r} not found in the donor directory")
    mutated = bytearray(abf)
    mutated[start:end] = vdir.replace(storage.encode(), escaped.encode(), 1)
    abf_relayout.parse_abf_index(bytes(mutated))
    items["DataModel"] = abf_codec.compress_datamodel(bytes(mutated))
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for name, blob in items.items():
            dst.writestr(name, blob)
    return out


def _run_cli(src: Path, pbix: Path, spec: Path, out: Path) -> tuple[int, str]:
    """Invoke the real patch CLI with `src` first on `PYTHONPATH`."""
    env = {"PYTHONPATH": str(src), "PATH": "/usr/bin:/bin"}
    proc = subprocess.run(
        [
            str(VENV_PY),
            "-m",
            "agentic_bi.pbix_binary.patch_cli",
            "apply",
            "--pbix",
            str(pbix),
            "--spec",
            str(spec),
            "--out",
            str(out),
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO),
    )
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def _inspect(pbix: Path) -> str:
    """Independently judge the written file: 'ok' or the failure it represents."""
    if not pbix.exists():
        return "no file written"
    try:
        with zipfile.ZipFile(pbix) as z:
            if z.testzip() is not None:
                return "zip is corrupt"
            datamodel = z.read("DataModel")
    except Exception as exc:  # noqa: BLE001
        return f"not a readable zip: {type(exc).__name__}"
    try:
        abf = abf_codec.decompress_datamodel(datamodel)
    except Exception as exc:  # noqa: BLE001
        return f"DataModel will not decompress: {type(exc).__name__}"
    try:
        abf_relayout.parse_abf_index(abf)
    except Exception as exc:  # noqa: BLE001
        return f"DataModel is unparseable: {type(exc).__name__}: {exc}"
    return "ok"


def scenario_escape(work: Path) -> None:
    print("\n=== D-1: badly escaped virtual directory ===")
    donor = _escaped_donor(
        DONOR,
        work / "donor-escaped.pbix",
        _first_storage(DONOR),
        "A&amp;B_Storage_1234",
    )
    print(f"donor prepared: {donor.name} (one path holds a real '&')")
    spec = work / "escape.json"
    spec.write_text(
        json.dumps(
            {
                "patches": [
                    {
                        "kind": "replace_member",
                        "member": "metadata.sqlitedb",
                        "data": base64.b64encode(b"z" * 128).decode(),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    for label, src in (("pre-fix", PREFIX_SRC), ("post-fix", REPO / "src")):
        out = work / f"escape-{label}.pbix"
        code, log = _run_cli(src, donor, spec, out)
        print(f"  {label:8s} exit={code}  output={_inspect(out)}")
        if log:
            print(f"           cli said: {log.splitlines()[-1][:100]}")


def scenario_ambiguous(work: Path) -> None:
    print("\n=== D-3: ambiguous byte patch (many matching sites) ===")
    with zipfile.ZipFile(DONOR) as z:
        abf = abf_codec.decompress_datamodel(z.read("DataModel"))
    pattern = _safe_ambiguous(abf)
    sites = abf.count(pattern)
    print(f"pattern {pattern.hex()} matches {sites} sites in the donor")
    spec = work / "ambiguous.json"
    spec.write_text(
        json.dumps(
            {
                "patches": [
                    {
                        "kind": "replace_hex",
                        "find": pattern.hex(),
                        "with": (b"\xaa" * len(pattern)).hex(),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    for label, src in (("pre-fix", PREFIX_SRC), ("post-fix", REPO / "src")):
        out = work / f"ambiguous-{label}.pbix"
        code, log = _run_cli(src, DONOR, spec, out)
        changed = _count_changes(DONOR, out, pattern)
        print(
            f"  {label:8s} exit={code}  output={_inspect(out)}  sites edited={changed}"
        )
        if code != 0 and log:
            print(f"           cli said: {log.splitlines()[-1][:100]}")


def _count_changes(before: Path, after: Path, pattern: bytes) -> str:
    if not after.exists():
        return "n/a"
    try:
        with zipfile.ZipFile(before) as z:
            a0 = abf_codec.decompress_datamodel(z.read("DataModel"))
        with zipfile.ZipFile(after) as z:
            a1 = abf_codec.decompress_datamodel(z.read("DataModel"))
    except Exception:  # noqa: BLE001
        return "unreadable"
    marker = b"\xaa" * len(pattern)
    return f"{a0.count(pattern)} -> {a1.count(pattern)} (marker x{a1.count(marker)})"


def _first_storage(pbix: Path) -> str:
    with zipfile.ZipFile(pbix) as z:
        abf = abf_codec.decompress_datamodel(z.read("DataModel"))
    for vf in abf_relayout.parse_abf_index(abf).files:
        if len(vf.path) == 20:
            return vf.path
    raise SystemExit("no 20-char storage id in the donor")


def _safe_ambiguous(abf: bytes, width: int = 8) -> bytes:
    """A repeated zero/ff run whose single overwrite keeps the ABF parseable."""
    for candidate in (b"\x00", b"\xff"):
        pattern = candidate * width
        if abf.count(pattern) < 2:
            continue
        probe = bytearray(abf)
        start = probe.find(pattern)
        probe[start : start + width] = b"\xaa" * width
        try:
            abf_relayout.parse_abf_index(bytes(probe))
        except Exception:  # noqa: BLE001
            continue
        return pattern
    raise SystemExit("no structurally safe ambiguous pattern")


def main() -> int:
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)
    print(f"prefix sources: {PREFIX_SRC}")
    scenario_escape(WORK)
    scenario_ambiguous(WORK)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
