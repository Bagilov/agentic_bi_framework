"""The design: pages and the blocks on them (the only thing an agent authors).

A design is the "base structure" of a dashboard. Everything else - placement,
layout JSON, `.pbix`, verification - is derived from it deterministically, so
the same design always produces the same report.

Every field of a design is untrusted (JSON/YAML), so each one is normalized here
with an error that names the page, block and field. `validate.py` then checks
cross-references (model objects, duplicates, geometry) that need the whole tree.

Public API:
    VisualDesign(kind, table, ...).from_dict(raw, block_id="")
    PageDesign(name, title, width, height, visuals, filters).from_dict(raw, index)
    Design(name, model, pages).from_dict(raw) / .load(path)
    Design.expected_pages() / .visual_count() / .kinds()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agentic_bi.constructor.blocks import resolve_kind
from agentic_bi.constructor.model import load_mapping, norm_pos, str_or_none, strict_int
from agentic_bi.constructor.model_context import ModelContext

DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 800
MIN_WIDTH = 320
MIN_HEIGHT = 240


def _list_of_str(raw: object, field_name: str, kind: str) -> list[str]:
    """Read a list of names; a bare string must not split into characters."""
    if raw in (None, ""):
        return []
    if isinstance(raw, str) or not isinstance(raw, (list, tuple)):
        raise ValueError(f"{kind}: {field_name} must be a list of names")
    names = [str(item).strip() for item in raw]
    if any(not name for name in names):
        raise ValueError(f"{kind}: {field_name} contains an empty name")
    return names


def _norm_filters(raw: object, where: str) -> list[dict[str, object]]:
    """Read a filter list (kept as parsed objects; the constructor rejects them)."""
    if raw in (None, ""):
        return []
    if not isinstance(raw, (list, tuple)):
        raise ValueError(f"{where}: filters must be a list")
    out: list[dict[str, object]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"{where}: filters[{index}] must be an object")
        out.append(dict(item))
    return out


@dataclass
class VisualDesign:
    """One block of the design: a declarative visual."""

    kind: str
    table: str = ""
    columns: list[str] = field(default_factory=list)
    axis: str | None = None
    value: str | None = None
    measure: str | None = None
    agg: str = "sum"
    extra_values: list[str] = field(default_factory=list)
    title: str | None = None
    description: str | None = None
    tooltip: str | None = None
    pos: tuple[int, int, int, int] | None = None
    span: int | None = None
    filters: list[dict[str, object]] = field(default_factory=list)
    block_id: str = ""

    @classmethod
    def from_dict(cls, raw: object, block_id: str = "") -> VisualDesign:
        """Build a block from a JSON/YAML object.

        Raises:
            ValueError: the block is not an object, its `kind` is unknown, or a
                field has the wrong type.
        """
        if not isinstance(raw, dict):
            raise ValueError(
                f"visual {block_id!r} must be an object, got {type(raw).__name__}"
            )
        kind = resolve_kind(str(raw.get("kind") or ""))
        span = raw.get("span")
        if span is not None:
            try:
                span = int(span)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"{kind}: span must be an integer, got {span!r}"
                ) from exc
        return cls(
            kind=kind,
            table=str_or_none(raw.get("table")) or "",
            columns=_list_of_str(raw.get("columns"), "columns", kind),
            axis=str_or_none(raw.get("axis")),
            value=str_or_none(raw.get("value")),
            measure=str_or_none(raw.get("measure")),
            agg=str(raw.get("agg") or "sum").strip().lower(),
            extra_values=_list_of_str(raw.get("extra_values"), "extra_values", kind),
            title=str_or_none(raw.get("title")),
            description=str_or_none(raw.get("description")),
            tooltip=str_or_none(raw.get("tooltip")),
            pos=norm_pos(raw.get("pos"), kind),
            span=span,
            filters=_norm_filters(raw.get("filters"), f"visual {block_id!r}"),
            block_id=str(raw.get("id") or block_id).strip(),
        )

    def to_block(self) -> dict[str, object]:
        """Return the block as the dict `make_visual` consumes."""
        return {
            "kind": self.kind,
            "table": self.table,
            "columns": list(self.columns),
            "axis": self.axis,
            "value": self.value,
            "measure": self.measure,
            "agg": self.agg,
            "extra_values": list(self.extra_values),
            "title": self.title,
            "description": self.description,
            "tooltip": self.tooltip,
            "pos": self.pos,
        }


def _page_dim(raw: object, name: str, field_name: str, default: int) -> int:
    """Read one canvas dimension: absent keeps the default, zero is an error."""
    if raw is None:
        return default
    value = strict_int(raw, f"page {name!r}: {field_name}")
    if value <= 0:
        raise ValueError(f"page {name!r}: {field_name} must be positive, got {raw!r}")
    return value


@dataclass
class PageDesign:
    """One page: its name, canvas size, blocks and (rejected) page filters."""

    name: str
    title: str = ""
    width: int = DEFAULT_WIDTH
    height: int = DEFAULT_HEIGHT
    visuals: list[VisualDesign] = field(default_factory=list)
    filters: list[dict[str, object]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: object, index: int = 0) -> PageDesign:
        """Build a page from a JSON/YAML object.

        Raises:
            ValueError: the page is not an object, `visuals` is not a list, or
                `width`/`height` is not an integer.
        """
        if not isinstance(raw, dict):
            raise ValueError(
                f"page[{index}] must be an object, got {type(raw).__name__}"
            )
        name = str(raw.get("name") or f"page_{index + 1}").strip()
        visuals_raw = raw.get("visuals") or []
        if not isinstance(visuals_raw, (list, tuple)):
            raise ValueError(f"page {name!r}: visuals must be a list")
        width = _page_dim(raw.get("width"), name, "width", DEFAULT_WIDTH)
        height = _page_dim(raw.get("height"), name, "height", DEFAULT_HEIGHT)
        visuals = [
            VisualDesign.from_dict(visual, block_id=f"{name}_{j + 1}")
            for j, visual in enumerate(visuals_raw)
        ]
        return cls(
            name=name,
            title=str(raw.get("title") or name).strip(),
            width=width,
            height=height,
            visuals=visuals,
            filters=_norm_filters(raw.get("filters"), f"page {name!r}"),
        )


@dataclass
class Design:
    """The dashboard an agent authors: a model context plus pages."""

    name: str = "dashboard"
    model: ModelContext = field(default_factory=ModelContext)
    pages: list[PageDesign] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: object) -> Design:
        """Build a design from a JSON/YAML object.

        Raises:
            ValueError: the design is not an object or a page is malformed.
        """
        if not isinstance(raw, dict):
            raise ValueError("design must be an object")
        database = raw.get("database")
        model = ModelContext.from_dict(
            raw.get("model"), None if database is None else str(database)
        )
        pages_raw = raw.get("pages")
        if pages_raw is None:
            pages_raw = []
        elif not isinstance(pages_raw, (list, tuple)):
            raise ValueError("design.pages must be a list")
        pages = [PageDesign.from_dict(page, i) for i, page in enumerate(pages_raw)]
        return cls(
            name=str(raw.get("name") or "dashboard").strip(),
            model=model,
            pages=pages,
        )

    @classmethod
    def load(cls, path: str | Path) -> Design:
        """Load a design from a JSON/YAML file."""
        return cls.from_dict(load_mapping(path))

    def expected_pages(self) -> dict[str, int]:
        """Return the expected visual count per page title (for verification)."""
        return {page.title: len(page.visuals) for page in self.pages}

    def visual_count(self) -> int:
        """Return the total number of blocks in the design."""
        return sum(len(page.visuals) for page in self.pages)

    def kinds(self) -> set[str]:
        """Return the set of block kinds used anywhere in the design."""
        return {visual.kind for page in self.pages for visual in page.visuals}


__all__ = [
    "DEFAULT_HEIGHT",
    "DEFAULT_WIDTH",
    "MIN_HEIGHT",
    "MIN_WIDTH",
    "Design",
    "PageDesign",
    "VisualDesign",
]
