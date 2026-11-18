"""The model context object: tables, relationships and the engine build spec.

`ModelContext` is the contract between a design and a `.pbix`. It is built
either from a JSON/YAML description or read back from an existing report
(`from_pbix`, optional `pbixray`), and it answers three questions:

* `registry()` - what objects a layout may reference (used by `validate_pbix`);
* `to_spec()` - what the engine should build (tables, types, measures, links);
* `from_dict()` - whether the description itself is well formed.

Public API:
    ModelContext(database, tables, relationships)
    ModelContext.from_dict(raw, database=None) / .load(path) / .from_pbix(pbix)
    ModelContext.registry() -> {table: {"columns": [...], "measures": [...]}}
    ModelContext.to_spec(values=None, include_empty_measures=True) -> dict
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agentic_bi.constructor.model import (
    DEFAULT_DATABASE,
    TECH_TABLE_PREFIXES,
    TableContext,
    load_mapping,
    pbixray_type,
    relationship_record,
)
from agentic_bi.engine.core import database_name


@dataclass
class ModelContext:
    """The model a design refers to, plus how to build it.

    Relationships are many-to-one links with a fixed cardinality:
    `fromTable`/`fromColumn` is the *many* side and `toTable`/`toColumn` the
    *one* side (the engine build script creates them with exactly that
    cardinality, so a reversed declaration filters in the wrong direction).
    """

    database: str = DEFAULT_DATABASE
    tables: dict[str, TableContext] = field(default_factory=dict)
    relationships: list[dict[str, object]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: object, database: str | None = None) -> ModelContext:
        """Build the context from a JSON/YAML object.

        Raises:
            ValueError: `raw` is not an object, a table declaration is
                malformed, or a count/relationship entry has the wrong shape.
        """
        if raw is not None and not isinstance(raw, dict):
            raise ValueError(f"model must be an object, got {type(raw).__name__}")
        body: dict[str, object] = dict(raw or {}) if isinstance(raw, dict) else {}
        tables_raw = body.get("tables") or {}
        tables: dict[str, TableContext] = {}
        if isinstance(tables_raw, dict):
            for key, value in tables_raw.items():
                name = str(key).strip()
                if not name:
                    raise ValueError("table name is empty")
                if name in tables:
                    raise ValueError(f"duplicate table name {name!r}")
                tables[name] = TableContext.from_dict(name, value or {})
        elif isinstance(tables_raw, list):
            for item in tables_raw:
                if not isinstance(item, dict) or not item.get("name"):
                    raise ValueError(f"bad table declaration: {item!r}")
                name = str(item["name"]).strip()
                if not name:
                    raise ValueError("table name is empty")
                if name in tables:
                    raise ValueError(f"duplicate table name {name!r}")
                tables[name] = TableContext.from_dict(name, item)
        else:
            raise ValueError("model.tables must be an object or a list")

        relationships_raw = body.get("relationships") or []
        if not isinstance(relationships_raw, list):
            raise ValueError("model.relationships must be a list")
        relationships: list[dict[str, object]] = []
        for index, rel in enumerate(relationships_raw):
            if not isinstance(rel, dict):
                raise ValueError(f"model.relationships[{index}] must be an object")
            relationships.append(dict(rel))
        name = str(database or body.get("database") or DEFAULT_DATABASE).strip()
        return cls(
            database=name or DEFAULT_DATABASE,
            tables=tables,
            relationships=relationships,
        )

    @classmethod
    def load(cls, path: str | Path) -> ModelContext:
        """Load the context from a JSON/YAML file."""
        return cls.from_dict(load_mapping(path))

    @classmethod
    def from_pbix(
        cls,
        pbix: str | Path,
        *,
        database: str = DEFAULT_DATABASE,
        with_expressions: bool = True,
    ) -> ModelContext:
        """Derive the context from the embedded model of a `.pbix` (pbixray).

        Desktop's technical date tables are skipped; column types come from the
        pandas dtype of the read-back schema, measure expressions from
        `dax_measures`, links from `relationships`.

        Raises:
            FileNotFoundError: the file does not exist.
            ValueError: there is no readable model, or pbixray is not installed.
        """
        path = Path(pbix)
        if not path.exists():
            raise FileNotFoundError(f".pbix not found: {path}")
        try:
            import pbixray
        except ImportError as exc:
            raise ValueError(
                "pbixray is required to derive the model context from a .pbix"
            ) from exc
        try:
            model = pbixray.PBIXRay(str(path))
        except Exception as exc:
            raise ValueError(f"cannot read the model from {path.name}: {exc}") from exc
        try:
            tables: dict[str, TableContext] = {}
            for raw_name in model.tables:
                name = str(raw_name).strip()
                if not name or name.startswith(TECH_TABLE_PREFIXES):
                    continue
                tables[name] = TableContext(name=name)
            for _, row in model.schema.iterrows():
                table_name = str(row.get("TableName") or "").strip()
                column = str(row.get("ColumnName") or "").strip()
                if table_name in tables and column:
                    tables[table_name].columns[column] = pbixray_type(
                        row.get("PandasDataType")
                    )
            for _, row in model.dax_measures.iterrows():
                table_name = str(row.get("TableName") or "").strip()
                measure = str(row.get("Name") or "").strip()
                if table_name in tables and measure:
                    expression = str(row.get("Expression") or "")
                    tables[table_name].measures[measure] = (
                        expression if with_expressions else ""
                    )
            relationships: list[dict[str, object]] = []
            for _, row in model.relationships.iterrows():
                record = relationship_record(dict(row.to_dict()))
                if (
                    record
                    and record["fromTable"] in tables
                    and record["toTable"] in tables
                ):
                    relationships.append(record)
        finally:
            model.close()
        return cls(database=database, tables=tables, relationships=relationships)

    def registry(self) -> dict[str, dict[str, list[str]]]:
        """Return the object registry used by `validate_pbix.validate_layout`."""
        return {
            name: {"columns": list(t.columns), "measures": list(t.measures)}
            for name, t in self.tables.items()
        }

    def to_spec(
        self,
        values: dict[str, list[dict[str, object]]] | None = None,
        *,
        include_empty_measures: bool = True,
    ) -> dict[str, object]:
        """Return the engine build spec for this model.

        Args:
            values: rows per table (a live build); empty for a donor build.
            include_empty_measures: keep measures without DAX, which the layout
                binding checks still expect to exist.

        Raises:
            ValueError: `values` names an unknown table or holds a non-object row.
        """
        rows_by_table = values or {}
        if not isinstance(rows_by_table, dict):
            raise ValueError("values must be {table: rows}")
        unknown = set(rows_by_table) - set(self.tables)
        if unknown:
            raise ValueError(f"values contain unknown tables: {sorted(unknown)}")
        for name, rows in rows_by_table.items():
            if not isinstance(rows, (list, tuple)):
                raise ValueError(f"values[{name!r}] must be a list of rows")
            for index, row in enumerate(rows):
                if not isinstance(row, dict):
                    raise ValueError(f"values[{name!r}][{index}] must be an object")
        tables: list[dict[str, object]] = []
        for name, table in self.tables.items():
            rows = rows_by_table.get(name) or []
            columns: list[dict[str, object]] = [
                {
                    "name": column,
                    "type": typ,
                    "values": [row.get(column) for row in rows],
                }
                for column, typ in table.columns.items()
            ]
            tables.append({"name": name, "columns": columns})
        measures = [
            {"table": name, "name": measure, "expression": expression}
            for name, table in self.tables.items()
            for measure, expression in table.measures.items()
            if expression or include_empty_measures
        ]
        return {
            "database": database_name(self.database),
            "tables": tables,
            "measures": measures,
            "relationships": list(self.relationships),
        }


__all__ = ["ModelContext"]
