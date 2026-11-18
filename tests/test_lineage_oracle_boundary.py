"""The Oracle boundary: the portal metadata database stays opaque.

The framework has no access to the Oracle database that backs a portal's
metadata (catalog, access grants, execution logs), and another deployment may
back it with another engine. These tests pin the contract:

- an Oracle source is detected by type only;
- the connection string from the M code never reaches the lineage output;
- the boundary note names the zone as outside the solution's perimeter and as
  deployment-specific;
- the diagram shows a generic Oracle store, and non-Oracle databases keep their
  own details.
"""

from __future__ import annotations

import json

import pytest

from agentic_bi.lineage.lineage_plantuml import PlantUmlMixin
from agentic_bi.lineage.lineage_sources import (
    ORACLE_BOUNDARY_NOTE,
    ORACLE_DETAIL,
    SourceMixin,
)

SECRET_EXPR = (
    'Oracle.Database("Host=db.internal.example;Service Name=PORTAL;'
    'User Id=svc_reader;Password=hunter2")'
)

LEAKS = (
    "db.internal.example",
    "PORTAL",
    "svc_reader",
    "hunter2",
    "Host=",
    "Service Name=",
)


class _Probe(SourceMixin):
    """`SourceMixin` without the rest of the lineage state."""


class _Diagram(PlantUmlMixin):
    """`PlantUmlMixin` without the rest of the lineage state."""


def _source(expr: str):
    return _Probe()._source_from_m(expr)


@pytest.mark.parametrize(
    "marker",
    ["Oracle.Database", "OracleDataAccess", "Oracle.ManagedDataAccess", "Odp.Net"],
)
def test_an_oracle_source_is_detected_by_type_only(marker: str) -> None:
    src = _source(f'{marker}("whatever")')
    assert src.type == "Oracle"
    assert src.detail == ORACLE_DETAIL
    assert src.status == "unresolved"
    assert src.error == ORACLE_BOUNDARY_NOTE
    assert src.path is None


def test_the_connection_string_never_reaches_the_source() -> None:
    src = _source(SECRET_EXPR)
    rendered = " ".join(str(v) for v in (src.type, src.detail, src.error, src.path))
    for leak in LEAKS:
        assert leak not in rendered


def test_the_boundary_note_names_the_zone_as_out_of_perimeter() -> None:
    note = ORACLE_BOUNDARY_NOTE.lower()
    assert "outside the perimeter" in note
    assert "deployment" in note


def test_the_exported_payload_carries_no_connection_details() -> None:
    src = _source(SECRET_EXPR)
    payload = json.dumps(
        {"type": src.type, "detail": src.detail, "error": src.error, "path": src.path}
    )
    for leak in LEAKS:
        assert leak not in payload


def test_the_diagram_shows_a_generic_oracle_store() -> None:
    assert _Diagram()._source_group(_source(SECRET_EXPR)) == "RDBMS (Oracle)"


def test_other_database_sources_keep_their_own_details() -> None:
    sql = _source('Sql.Database("srv", "db")')
    assert sql.type == "SQL Server"
    assert sql.detail == "srv / db"


ODBC_ORACLE_EXPR = (
    'Odbc.Query("DSN=OraclePortal;Uid=svc_reader;Pwd=hunter2", '
    '"SELECT * FROM SECRET_GRANTS JOIN ACCESS_LOG ON 1=1")'
)


def test_oracle_via_odbc_is_redacted_like_the_native_connector() -> None:
    # The ODBC branch runs first; an Oracle DSN must not echo the DSN or the
    # query's tables — they are the same deployment-specific zone.
    src = _source(ODBC_ORACLE_EXPR)
    assert src.type == "Oracle"
    assert src.detail == ORACLE_DETAIL
    assert src.error == ORACLE_BOUNDARY_NOTE
    rendered = " ".join(str(v) for v in (src.type, src.detail, src.error, src.path))
    for leak in (
        "OraclePortal",
        "svc_reader",
        "hunter2",
        "SECRET_GRANTS",
        "ACCESS_LOG",
    ):
        assert leak not in rendered


@pytest.mark.parametrize(
    "marker", ["ODP.NET", "oracle.database", "ORACLE.ManagedDataAccess"]
)
def test_oracle_markers_are_case_insensitive(marker: str) -> None:
    # M is case-insensitive, so the detection must be too.
    src = _source(f'{marker}("whatever")')
    assert src.type == "Oracle"
    assert src.detail == ORACLE_DETAIL


def test_a_non_oracle_odbc_source_keeps_its_details() -> None:
    src = _source('Odbc.Query("DSN=HiveProd", "SELECT * FROM events")')
    assert src.type == "ODBC"
    assert "HiveProd" in src.detail


def test_a_neutral_oracle_dsn_with_credentials_is_redacted() -> None:
    # The DSN name is deployment-chosen; credentials must not depend on it.
    expr = (
        'Odbc.Query("DSN=PORTAL;Uid=svc_reader;Pwd=hunter2", '
        '"SELECT * FROM SECRET_GRANTS")'
    )
    src = _source(expr)
    rendered = " ".join(str(v) for v in (src.type, src.detail, src.error, src.path))
    for leak in ("PORTAL", "svc_reader", "hunter2", "SECRET_GRANTS"):
        assert leak not in rendered


def test_an_oracle_driver_connection_string_is_redacted() -> None:
    expr = (
        'Odbc.Query("DRIVER={Oracle in OraClient19Home1};Dbq=portal;Uid=u;Pwd=p", '
        '"SELECT 1 FROM DUAL")'
    )
    src = _source(expr)
    assert src.type == "Oracle"
    assert src.detail == ORACLE_DETAIL
    rendered = " ".join(str(v) for v in (src.type, src.detail, src.error, src.path))
    assert "OraClient19Home1" not in rendered
    assert "Dbq" not in rendered


def test_a_non_oracle_odbc_with_credentials_is_redacted() -> None:
    expr = 'Odbc.Query("DSN=HiveProd;Uid=u;Pwd=p", "SELECT * FROM events")'
    src = _source(expr)
    rendered = " ".join(str(v) for v in (src.type, src.detail, src.error, src.path))
    for leak in ("HiveProd", "Uid", "Pwd", "events"):
        assert leak not in rendered
