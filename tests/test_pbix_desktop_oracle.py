"""Mandatory-stage test: open a built board in Power BI Desktop (via guest).

On Apple Silicon the only authoritative "Desktop opens this report" check runs
in a Windows guest (`desktop_oracle_guest`). These tests are **gated**: they run
only when the guest is configured through the environment (see
`desktop_oracle_guest.GuestConfig`), and are skipped otherwise so the suite stays
green on a plain macOS host.

Set up the gate (example values; never commit real credentials):

    export AGENTIC_BI_GUEST_WINRM="http://<guest-ip>:5985/wsman"
    export AGENTIC_BI_GUEST_USER="<user>"
    export AGENTIC_BI_GUEST_PASSWORD="<password>"
    export PBI_RS_DESKTOP='C:\\Program Files\\Microsoft Power BI Desktop\\bin\\PBIDesktop.exe'
    export PBI_RS_WS_ROOT="$LOCALAPPDATA\\Microsoft\\Power BI Desktop\\AnalysisServicesWorkspaces"

Then: `.venv/bin/python -m pytest tests/test_pbix_desktop_oracle.py -v`.
"""

from __future__ import annotations

import base64
import zipfile
from pathlib import Path

import pytest

from agentic_bi import engine_container, engine_layout
from agentic_bi.desktop_oracle_guest import GuestConfig, run_oracle
from agentic_bi.engine_layout import Visual
from agentic_bi.pbix_binary import abf_codec, abf_relayout
from agentic_bi.pbix_binary.patch_pipeline import apply_patches

pytest.importorskip("xpress9", reason="the 'xpress9' codec is optional")

pytestmark = pytest.mark.skipif(
    not GuestConfig.available(),
    reason="Windows guest not configured (AGENTIC_BI_GUEST_* env vars)",
)

TABLE = "Opportunities"
CATEGORY = "Sales Stage"
VALUE = "Value"


def _build_board(template: Path, out: Path) -> Path:
    with zipfile.ZipFile(template) as z:
        names = set(z.namelist())
        datamodel = z.read("DataModel")
    copy_members = [
        m
        for m in engine_container.COPY_MEMBERS
        if m in names and m not in ("Report/Layout", "DataModel")
    ]
    overview = [
        Visual("card", TABLE, value="Probability", agg="avg", title="Avg probability"),
        Visual("card", TABLE, value=VALUE, agg="sum", title="Pipeline value"),
        Visual(
            "column",
            TABLE,
            axis=CATEGORY,
            value=VALUE,
            agg="sum",
            title="Value by stage",
        ),
        Visual(
            "pie",
            TABLE,
            axis=CATEGORY,
            value=VALUE,
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
    layout = engine_layout.build_report([("Overview", overview), ("Details", details)])
    engine_container.build_container(
        template, layout, datamodel, out, copy_members=copy_members
    )
    return out


def _uneven_patch(src: Path, out: Path) -> Path:
    """Edit the binary DataModel with the uneven member path (sqlite +slack)."""
    with zipfile.ZipFile(src) as z:
        abf = abf_codec.decompress_datamodel(z.read("DataModel"))
    storage = abf_relayout.parse_abf_index(abf).storage_of("metadata.sqlitedb")
    assert storage is not None
    payload = abf_relayout.member_blob(abf, storage) + b"\x00" * 4096
    apply_patches(
        src,
        [
            {
                "kind": "replace_member",
                "member": "metadata.sqlitedb",
                "data": base64.b64encode(payload).decode(),
            }
        ],
        out,
    )
    return out


def test_built_board_opens_in_desktop(template_pbix: Path, tmp_path: Path):
    board = _build_board(template_pbix, tmp_path / "board.pbix")
    result = run_oracle(board, dest_name="board.pbix", hold=90, open_timeout=240)
    assert result.loaded, f"verdict={result.verdict}\n{result.log}"


def test_uneven_patched_board_opens_in_desktop(template_pbix: Path, tmp_path: Path):
    board = _build_board(template_pbix, tmp_path / "board.pbix")
    edited = _uneven_patch(board, tmp_path / "board_patched.pbix")
    result = run_oracle(
        edited, dest_name="board_patched.pbix", hold=90, open_timeout=240
    )
    assert result.loaded, f"verdict={result.verdict}\n{result.log}"
