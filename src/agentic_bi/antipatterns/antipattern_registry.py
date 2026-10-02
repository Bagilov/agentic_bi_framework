"""Antipattern registry: definitions of all detected antipatterns."""
from __future__ import annotations

from dataclasses import dataclass


# --------------------------------------------------------------------------- #
#  Antipattern registry: id -> description
# --------------------------------------------------------------------------- #
@dataclass
class Antipattern:
    """A definition of one antipattern."""

    id: str
    name: str
    level: str            # source | measure | calc_column | table | board
    critical: bool
    detail: str
    fix: str


ANTIPATTERNS: list[Antipattern] = [
    # ---------- sources (M code) ----------
    Antipattern("m.hardcoded_paths", "Hardcoded file paths", "source",
                False, "A file path is hardcoded in M code (File.Contents('C:\\...'))",
                "Move the path into a Power Query parameter / environment config"),
    Antipattern("m.fixed_date", "Fixed date in a query", "source",
                False, "A literal date in an SQL template/M code (#date(2026,1,1), '2026-')",
                "Replace with dynamic period bounds via a parameter/calendar"),
    Antipattern("m.local_now", "DateTime.LocalNow() (unstable)", "source",
                False, "Using DateTime.LocalNow()/FixedLocalNow()",
                "For 'as of today' use a reporting-period parameter"),
    Antipattern("m.whole_table", "Reading a table without a source filter", "source",
                True, "SELECT * / no WHERE - the whole table is pulled into M",
                "Push WHERE/projection to the source (query folding)"),
    Antipattern("m.no_parameterization", "Hardcoded DSN/connection without a parameter", "source",
                False, "Odbc.Query('dsn=...', ...) with a hardcoded DSN in the text",
                "Parameterize the source, use shared wrapper functions"),
    Antipattern("m.heavy_steps", "Heavy M steps without folding", "source",
                True, "Multiple Table.AddColumn/Transform after the source",
                "Move processing to the source/mart, not M"),
    Antipattern("m.multi_source_union", "Assembly from many sources without a contract", "source",
                False, "Several File.Contents/Odbc.Query in one let",
                "A single contract/mart instead of gluing in M"),
    Antipattern("m.json_expand_fragile", "Expanding source JSON into fixed columns", "source",
                True, "JSON from the source is parsed into hardcoded columns; when the key "
                      "set in the source changes, the columns disappear and the refresh fails "
                      "with 'column wasn't found'",
                "Require a stable JSON contract from the source (a fixed key set or null "
                "instead of absence) and/or build columns dynamically from the actual keys "
                "(Record.FieldOrDefault, Table.ColumnNames); do not hardcode the columns"),

    # ---------- DAX measures ----------
    Antipattern("dax.calculate_no_filter", "CALCULATE without a filter (empty wrapper)", "measure",
                False, "CALCULATE(<expr>) without a context modifier",
                "Remove CALCULATE; keep it only with a real filter"),
    Antipattern("dax.row_scan", "Row-by-row iteration (SUMX/EARLIER/FILTER ALL)", "measure",
                True, "SUMX / EARLIER / FILTER(ALL()) in a measure",
                "Replace with native aggregates/context design"),
    Antipattern("dax.filter_all", "FILTER/ALL without need", "measure",
                True, "FILTER(ALL(...)) / ALL( removes context",
                "Use ALLEXCEPT/ALLSELECTED/REMOVEFILTERS surgically"),
    Antipattern("dax.crossjoin", "CROSSJOIN/GENERATE (Cartesian)", "measure",
                True, "CROSSJOIN( or GENERATE( in an expression",
                "Rework the model/mart instead of a Cartesian product"),
    Antipattern("dax.hardcoded_value", "Hardcoded thresholds in measure code", "measure",
                False, "A literal number/string inside IF/SWITCH",
                "Move thresholds into parameters/config/a table"),
    Antipattern("dax.measure_arith_ref", "Arithmetic over measure references", "measure",
                True, "'1 - [Measure]' / '[A] + [B]' without a filter context",
                "Wrap in CALCULATE / use a correct context"),
    Antipattern("dax.isblank_default", "IF(ISBLANK(x), '...', x) as a default", "measure",
                False, "IF(ISBLANK( <literal> )) for substitution",
                "Use COALESCE(x, default) or a type-safe measure"),
    Antipattern("dax.var_no_return", "Many VARs and one RETURN (branching)", "measure",
                False, "Several VARs, a single RETURN at the end",
                "Split into separate measures / simplify the logic"),
    Antipattern("dax.switch_const", "SWITCH over literals (measure bloat)", "measure",
                False, "SWITCH( SELECTEDVALUE( ... N constant branches)",
                "Parameterize the category selection instead of N branches"),

    # ---------- calculated columns ----------
    Antipattern("dax.format_column", "FORMAT() in a calculated column", "calc_column",
                True, "FORMAT(date/number) in dax_columns.Expression",
                "Format at the visual level, do not materialize a date string"),
    Antipattern("dax.calc_business_logic", "Business logic in a calculated column", "calc_column",
                True, "Complex IF/SWITCH in a business-table column",
                "Move to a measure/mart; a column materializes and slows things down"),
    Antipattern("dax.date_from_raw", "Date access without a calendar table", "calc_column",
                False, "YEAR([Date])/MONTH([Date]) over a raw date",
                "Use a calendar table with relationships"),

    # ---------- tables ----------
    Antipattern("dax.many_measures_table", "Table overloaded with measures", "table",
                False, ">30 measures in one table",
                "Group measures by subject table/folders"),
    Antipattern("dax.duplicate_measure_pattern", "Repeating same-type measures", "table",
                True, "N measures with the same CALCULATE(count(...)) template",
                "Parameterize SWITCH/dynamic category selection"),

    # ---------- dashboard ----------
    Antipattern("board.page_overload", "Page overloaded with visuals", "board",
                False, "n_visuals > 15 on a page",
                "Split the page, use bookmarks"),
    Antipattern("board.decor_heavy", "Many decorative elements", "board",
                False, "shape/textbox > 50% of page elements",
                "Move decor into the layout, do not mix it with data"),
    Antipattern("board.unbound_page", "Page without data", "board",
                False, "A page without any table bindings",
                "Remove it or explicitly mark it as a reference page"),
    Antipattern("board.color_overuse", "Palette overuse", "board",
                False, "Unique colors on a page > 10",
                "Reduce the palette to the brand one"),
]


def _registry() -> dict[str, Antipattern]:
    return {a.id: a for a in ANTIPATTERNS}


# --------------------------------------------------------------------------- #
#  Per-level detectors
