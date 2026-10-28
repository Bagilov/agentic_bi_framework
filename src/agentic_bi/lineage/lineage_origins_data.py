"""Built-in origin taxonomy constants and a neutral default origin map.

Replace DEFAULT_ORIGINS with your own map (or supply an ``origins.yaml``) to
adapt lineage to any dashboard without changing code.
"""

from __future__ import annotations

from dataclasses import dataclass, field

ORIGIN_LEVEL = 0
ORIGIN_LEVEL_LABEL = "0 · Origin"

# Display order of origin categories
ORIGIN_ORDER = [
    "origin-pipeline",
    "origin-manual",
    "origin-reference",
    "origin-etl",
    "origin-unknown",
]

# Human-readable category label (for PlantUML/Excel)
ORIGIN_LABEL = {
    "origin-pipeline": "INDUSTRIAL PIPELINE",
    "origin-manual": "MANUAL SOURCES (operators)",
    "origin-reference": "INLINE REFERENCE TABLES (M code)",
    "origin-etl": "ETL / LEGACY PROCESS",
    "origin-unknown": "OTHER / UNKNOWN",
}

# PlantUML node style (ref style, light palette)
ORIGIN_COLORS = {
    "origin-pipeline": "#d5e8d4",
    "origin-manual": "#ffe6cc",
    "origin-reference": "#e1d5e7",
    "origin-etl": "#f8cecc",
    "origin-unknown": "#f5f5f5",
}

# Sub-stages of the first stage: source -> processing -> load
ORIGIN_STAGE_ORDER = ["source", "process", "load"]
ORIGIN_STAGE_LABEL = {
    "source": "SOURCE",
    "process": "PROCESSING",
    "load": "LOAD",
}
ORIGIN_STAGE_COLORS = {
    "source": "#fff2cc",
    "process": "#dae8fc",
    "load": "#d5e8d4",
}


@dataclass
class Origin:
    """The origin of one source (generating process/repository).

    Fields:
        key: a stable origin identifier key.
        category: category (origin-pipeline/manual/reference/etl/unknown).
        label: a human-readable process/repository name.
        detail: details (repository, artifact, comment).
        tables: source-table names of the model belonging to this origin.
        stages: sub-stages of the first stage: [{stage, label, detail}, ...], where
            stage is one of {source, process, load}: from where -> processed by -> loaded to.
    """

    key: str
    category: str
    label: str
    detail: str | None = None
    tables: list[str] = field(default_factory=list)
    stages: list[dict] = field(default_factory=list)


# --------------------------------------------------------------------------- #
#  Neutral built-in origin map (sample - replace with your own)
# --------------------------------------------------------------------------- #
# Keys are model source-table names (as in the model table). The sample uses
# placeholder names that match no real donor: a pipeline-loaded fact table, a
# hand-maintained Excel share, a personal-drive reference file, and an inline
# M-code table. Supply your own via `agentic_bi.settings`-independent
# `origins.yaml` / a dict to `load_origins`, without changing code.
# stages: the chain "SOURCE -> PROCESSING -> LOAD" (source/process/load).
DEFAULT_ORIGINS: list[dict] = [
    {
        "key": "warehouse_pipeline",
        "category": "origin-pipeline",
        "label": "warehouse-pipeline",
        "detail": "industrial pipeline that builds the fact/mart source table",
        "tables": ["dim_sample"],
        "stages": [
            {
                "stage": "source",
                "label": "Registry (registry:excel)",
                "detail": "request forms -> 'registry.xlsx'",
            },
            {
                "stage": "process",
                "label": "combine (left join by id)",
                "detail": "merge registry and monitoring data",
            },
            {
                "stage": "load",
                "label": "sink:warehouse -> fact_sample",
                "detail": "Spark/Parquet -> warehouse table (+ load_dt)",
            },
        ],
    },
    {
        "key": "manual_share",
        "category": "origin-manual",
        "label": "Manual Excel · \\\\fileserver\\share\\team",
        "detail": "operator-maintained Excel files on a network share (no auto pipeline)",
        "tables": [
            "Status",
            "Time in queue",
            "Comments",
        ],
        "stages": [
            {
                "stage": "source",
                "label": "Operator Excel files",
                "detail": "\\\\fileserver\\share\\team\\*.xlsx: statuses, time, comments",
            },
            {
                "stage": "process",
                "label": "Manual maintenance (operator)",
                "detail": "edits are made by hand in Excel; no auto pipeline",
            },
            {
                "stage": "load",
                "label": "Power Query (Excel.Workbook)",
                "detail": "M code reads the network share directly into model tables",
            },
        ],
    },
    {
        "key": "personal_disk",
        "category": "origin-manual",
        "label": "Manual Excel · personal drive",
        "detail": "reference.xlsx - a hand-maintained reference table",
        "tables": ["Business line"],
        "stages": [
            {
                "stage": "source",
                "label": "reference.xlsx",
                "detail": "C:\\path\\to\\reference.xlsx",
            },
            {
                "stage": "process",
                "label": "Manual reference assembly",
                "detail": "the business-line/owner reference is assembled by hand",
            },
            {
                "stage": "load",
                "label": "Power Query (Excel.Workbook)",
                "detail": "M code reads the personal-drive file -> Business line table",
            },
        ],
    },
    {
        "key": "inline_reference",
        "category": "origin-reference",
        "label": "Inline reference table",
        "detail": "a constant inside the .pbix M code; no external source",
        "tables": ["Threshold"],
        "stages": [
            {
                "stage": "source",
                "label": "M-code constant",
                "detail": "data is embedded directly in the .pbix (base64)",
            },
            {
                "stage": "process",
                "label": "No processing",
                "detail": "a ready table; no external process/ETL",
            },
            {
                "stage": "load",
                "label": "Model table",
                "detail": "M code -> an inline dimension table in the VertiPaq model",
            },
        ],
    },
]
