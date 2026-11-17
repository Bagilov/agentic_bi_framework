"""Assembly paths: donor, engine and live-data builds from a compiled layout.

Three ways to get a `.pbix` out of a design, each with its own source of truth:

* **donor** - reuse an existing report's DataModel and replace (or extend) the
  layout; offline, no Desktop needed;
* **engine** - combine a caller-supplied `.pbix` OPC template with a ready
  `DataModel` file or bytes;
* **data** - build the DataModel from rows through the Desktop engine, then
  assemble as "engine".

Everything here is deterministic and input-checked: a missing template, an
empty DataModel or a row that does not match the declared column type raises a
located `ValueError` instead of producing a broken artifact.

Public API:
    engine_problems(design) -> list[str]
    merge_into_donor(donor, layout) -> dict
    build_donor(compiled, donor, out, keep_donor_pages=False) -> Path
    build_engine(compiled, template, datamodel, out) -> Path
    build_from_data(design, compiled, data, template, out, ...) -> Path
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from agentic_bi.constructor.design import Design
from agentic_bi.constructor.layout import CompiledLayout
from agentic_bi.constructor.rows import Rows, coerce_value, normalize_rows
from agentic_bi.engine import PBI_RS, EnginePipeline
from agentic_bi.engine.container import build_container
from agentic_bi.engine.verify import load_layout
from agentic_bi.rebuild import rebuild_pbix

logger = logging.getLogger(__name__)


def engine_problems(design: Design) -> list[str]:
    """Return why a live engine build is impossible (empty list when it can run).

    The Tabular engine rejects non-ASCII object names, and a measure without DAX
    drops out of the spec, which leaves its visual blank without an error.
    """
    problems: list[str] = []
    for table in design.model.tables.values():
        for name in (table.name, *table.columns, *table.measures):
            if not str(name).isascii():
                problems.append(f"non-ASCII model name {name!r}")
    for page in design.pages:
        for visual in page.visuals:
            if not visual.measure:
                continue
            context_table = design.model.tables.get(visual.table)
            expression = (
                context_table.measures.get(visual.measure, "") if context_table else ""
            )
            if not expression.strip():
                problems.append(
                    f"measure {visual.table}.{visual.measure} has no DAX "
                    f"(visual {visual.block_id})"
                )
    return list(dict.fromkeys(problems))


def merge_into_donor(donor: Path, layout: dict) -> dict:
    """Append the compiled pages to a donor layout and return the merged dict.

    Raises:
        ValueError: the donor layout has non-list `sections`/`pods`, or its
            `config` is not a JSON object.
    """
    merged = load_layout(donor)
    sections = merged.setdefault("sections", [])
    if not isinstance(sections, list):
        raise ValueError("donor layout sections must be a list")
    base = max((int(s.get("ordinal", -1)) for s in sections), default=-1) + 1
    pods = merged.get("pods") or []
    if not isinstance(pods, list):
        raise ValueError("donor layout pods must be a list")
    used = {p.get("name") for p in pods if isinstance(p, dict)}
    for offset, section in enumerate(layout["sections"]):
        section = dict(section)
        section["ordinal"] = base + offset
        sections.append(section)
        name = f"Pod{section['ordinal']}"
        suffix = 1
        while name in used:
            name = f"Pod{section['ordinal']}_{suffix}"
            suffix += 1
        used.add(name)
        pods.append({"name": name, "boundSection": section["name"], "config": "{}"})
    merged["pods"] = pods
    try:
        config = json.loads(merged.get("config") or "{}")
    except (TypeError, ValueError) as exc:
        raise ValueError("donor layout config is not valid JSON") from exc
    if not isinstance(config, dict):
        raise ValueError("donor layout config must be a JSON object")
    config["activeSectionIndex"] = base
    merged["config"] = json.dumps(config, ensure_ascii=False)
    return merged


def build_donor(
    compiled: CompiledLayout,
    donor: str | Path,
    out: str | Path,
    *,
    keep_donor_pages: bool = False,
) -> Path:
    """Assemble `out` from the donor DataModel and this design's layout."""
    source = Path(donor)
    layout = compiled.layout
    if keep_donor_pages:
        layout = merge_into_donor(source, layout)
    return rebuild_pbix(source, Path(out), layout=layout)


def build_engine(
    compiled: CompiledLayout,
    template: str | Path,
    datamodel: bytes | str | Path,
    out: str | Path,
) -> Path:
    """Assemble `out` from an OPC template plus a ready `DataModel`.

    Raises:
        FileNotFoundError: the template or the DataModel file is missing.
        ValueError: the DataModel is empty.
    """
    template_path = Path(template)
    if not template_path.exists():
        raise FileNotFoundError(f"OPC template not found: {template_path}")
    if isinstance(datamodel, (str, Path)):
        datamodel_path = Path(datamodel)
        if not datamodel_path.is_file():
            raise FileNotFoundError(f"DataModel not found: {datamodel_path}")
        payload = datamodel_path.read_bytes()
    elif isinstance(datamodel, (bytes, bytearray)):
        payload = bytes(datamodel)
    else:
        raise TypeError("datamodel must be bytes or a path")
    if not payload:
        raise ValueError("datamodel is empty")
    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    build_container(template_path, compiled.layout_bytes(), payload, out_path)
    return out_path


def build_from_data(
    design: Design,
    compiled: CompiledLayout,
    data: object,
    template: str | Path,
    out: str | Path,
    *,
    table: str | None = None,
    desktop: str | None = None,
    work_dir: str | Path | None = None,
) -> Path:
    """Build the DataModel from rows in the Desktop engine, then assemble `out`.

    Raises:
        ValueError: the model context cannot be built by the engine, or the rows
            do not match it.
    """
    problems = engine_problems(design)
    if problems:
        raise ValueError("engine build is not possible: " + "; ".join(problems))
    values = normalize_rows(design, data, table)
    spec = design.model.to_spec(values, include_empty_measures=False)
    pipeline = EnginePipeline(
        template=Path(template),
        desktop=desktop or PBI_RS,
        work_dir=None if work_dir is None else Path(work_dir),
    )
    datamodel = pipeline.build_datamodel(spec)
    return build_engine(compiled, template, datamodel, out)


__all__ = [
    "Rows",
    "build_donor",
    "build_engine",
    "build_from_data",
    "coerce_value",
    "engine_problems",
    "merge_into_donor",
    "normalize_rows",
]
