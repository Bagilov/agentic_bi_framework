"""End-to-end: build a board `.pbix`, then edit it with the uneven patch method.

This is the integration case for the binary layer. It

1. builds a two-page board layout from the donor model objects (`engine_layout`),
2. folds it into a `.pbix` with the donor `DataModel` (`engine_container`),
3. reverse-tests the board (`engine_verify`: container/layout/bindings/filters),
4. edits the *binary* DataModel through `patch_pipeline.apply_patches` — an
   uneven `metadata.sqlitedb` replacement — and
5. re-verifies the edited `.pbix` and the re-read model (`pbixray`).

The report is written to `output_files/` so the built artifact can be inspected.
"""

from __future__ import annotations

import base64
import json
import zipfile
from pathlib import Path

import pytest

from agentic_bi import engine_container, engine_layout, engine_verify
from agentic_bi.engine_layout import Visual
from agentic_bi.pbix_binary import abf_codec, abf_relayout
from agentic_bi.pbix_binary.patch_pipeline import apply_patches

pytest.importorskip("xpress9", reason="the 'xpress9' codec is optional")

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "output_files"

# Model objects taken from the donor template (see templates/template.pbix).
TABLE = "Opportunities"
CATEGORY = "Sales Stage"
VALUE = "Probability"


def _board_layout() -> bytes:
    """A two-page board over real donor objects (no donor visuals reused)."""
    overview = [
        Visual("card", TABLE, value=VALUE, agg="avg", title="Avg probability"),
        Visual("card", TABLE, value="Value", agg="sum", title="Pipeline value"),
        Visual(
            "column",
            TABLE,
            axis=CATEGORY,
            value="Value",
            agg="sum",
            title="Value by stage",
        ),
        Visual(
            "pie",
            TABLE,
            axis=CATEGORY,
            value="Value",
            agg="sum",
            title="Value share by stage",
        ),
    ]
    details = [
        Visual(
            "table",
            TABLE,
            columns=["Sales Stage", "Status", "Value", "Probability", "Discount"],
            title="Opportunity details",
        ),
        Visual("slicer", TABLE, axis="Status", title="Status"),
        Visual("slicer", TABLE, axis=CATEGORY, title="Stage"),
    ]
    return engine_layout.build_report([("Overview", overview), ("Details", details)])


def _build_board(template: Path, out: Path) -> dict:
    with zipfile.ZipFile(template) as z:
        names = set(z.namelist())
        datamodel = z.read("DataModel")
    copy_members = [
        m
        for m in engine_container.COPY_MEMBERS
        if m in names and m not in ("Report/Layout", "DataModel")
    ]
    engine_container.build_container(
        template, _board_layout(), datamodel, out, copy_members=copy_members
    )
    return {"out": str(out), "bytes": out.stat().st_size}


def _spec() -> dict:
    """A build spec listing the objects the board references."""
    return {
        "database": "Board",
        "tables": [
            {
                "name": TABLE,
                "columns": [
                    {"name": "Sales Stage", "type": "string", "values": []},
                    {"name": "Status", "type": "string", "values": []},
                    {"name": "Value", "type": "double", "values": []},
                    {"name": "Probability", "type": "double", "values": []},
                    {"name": "Discount", "type": "double", "values": []},
                ],
            },
        ],
        "measures": [],
    }


def test_build_board_and_reverse_verify(template_pbix: Path, tmp_path: Path):
    out = tmp_path / "board.pbix"
    info = _build_board(template_pbix, out)
    assert Path(info["out"]).exists()

    report = engine_verify.verify_pbix(
        out, _spec(), pages={"Overview": 4, "Details": 3}, model=False
    )
    assert report.critical_ok(), report.format()
    assert report.passed > 0


def test_board_pbix_is_editable_with_uneven_patch(template_pbix: Path, tmp_path: Path):
    board = tmp_path / "board.pbix"
    _build_board(template_pbix, board)

    with zipfile.ZipFile(board) as z:
        abf = abf_codec.decompress_datamodel(z.read("DataModel"))
    index = abf_relayout.parse_abf_index(abf)
    storage = index.storage_of("metadata.sqlitedb")
    assert storage is not None
    payload = abf_relayout.member_blob(abf, storage) + b"\x00" * 4096

    edited = tmp_path / "board_edited.pbix"
    report = apply_patches(
        board,
        [
            {
                "kind": "replace_member",
                "member": "metadata.sqlitedb",
                "data": base64.b64encode(payload).decode(),
            }
        ],
        edited,
    )
    assert edited.stat().st_size == report.size

    with zipfile.ZipFile(edited) as z:
        assert z.testzip() is None
        edited_abf = abf_codec.decompress_datamodel(z.read("DataModel"))
    new_index = abf_relayout.parse_abf_index(edited_abf)
    rebuilt = abf_relayout.member_blob(
        edited_abf, new_index.storage_of("metadata.sqlitedb")
    )
    assert len(rebuilt) == len(payload)

    # The board layout is untouched by the binary edit.
    check = engine_verify.verify_pbix(
        edited, _spec(), pages={"Overview": 4, "Details": 3}, model=False
    )
    assert check.critical_ok(), check.format()


def test_board_model_reads_back_after_patch(template_pbix: Path, tmp_path: Path):
    pytest.importorskip("pbixray", reason="model read-back needs pbixray")
    from pbixray import PBIXRay

    board = tmp_path / "board.pbix"
    _build_board(template_pbix, board)
    with zipfile.ZipFile(board) as z:
        abf = abf_codec.decompress_datamodel(z.read("DataModel"))
    storage = abf_relayout.parse_abf_index(abf).storage_of("metadata.sqlitedb")
    payload = abf_relayout.member_blob(abf, storage) + b"\x00" * 2048

    edited = tmp_path / "board_readback.pbix"
    apply_patches(
        board,
        [
            {
                "kind": "replace_member",
                "member": "metadata.sqlitedb",
                "data": base64.b64encode(payload).decode(),
            }
        ],
        edited,
    )

    model = PBIXRay(str(edited))
    assert TABLE in set(model.tables)
    assert TABLE in set(model.schema["TableName"])
    assert model.dax_measures is not None


def test_write_board_artifact_for_inspection(template_pbix: Path):
    """Materialize the built board (and a summary) under output_files/."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    board = OUTPUT_DIR / "board_binary_demo.pbix"
    _build_board(template_pbix, board)

    with zipfile.ZipFile(board) as z:
        abf = abf_codec.decompress_datamodel(z.read("DataModel"))
    storage = abf_relayout.parse_abf_index(abf).storage_of("metadata.sqlitedb")
    payload = abf_relayout.member_blob(abf, storage) + b"\x00" * 4096
    edited = OUTPUT_DIR / "board_binary_demo_edited.pbix"
    report = apply_patches(
        board,
        [
            {
                "kind": "replace_member",
                "member": "metadata.sqlitedb",
                "data": base64.b64encode(payload).decode(),
            }
        ],
        edited,
    )

    summary = {
        "board": {"path": str(board), "bytes": board.stat().st_size},
        "edited": {
            "path": str(edited),
            "bytes": report.size,
            "abf_bytes": report.abf_size,
            "edits": report.log,
        },
    }
    (OUTPUT_DIR / "board_binary_demo.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    assert board.exists() and edited.exists()
