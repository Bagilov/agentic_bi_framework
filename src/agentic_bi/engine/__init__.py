"""Engine subpackage: build a `.pbix` via the Power BI Desktop RS AS engine.

The engine (`msmdsrv.exe`) performs the canonical model serialization, so the
binary VertiPaq `DataModel` is valid; the report layout is built from scratch.

This package is a **facade** over the focused modules that used to sit at the
package root:

    core.py          - `EnginePipeline` (the pipeline itself)
    host.py          - Desktop discovery, port probing, script/oracle transport
    container.py     - .pbix container assembly and DataModel swap
    layout*.py       - layout / visual / query construction
    verify*.py       - the reverse self-test (container, bindings, model, brand)
    types.py         - column type coercion
    cli.py           - the `agentic-bi-engine` command

It re-exports the historical public API, so `from agentic_bi.engine import
EnginePipeline` is unchanged. The old module paths (`agentic_bi.engine_container`,
`agentic_bi.engine_layout`, ...) still resolve through one-release shims.
"""

from __future__ import annotations

from agentic_bi.engine.core import (
    DEFAULT_TEMPLATE,
    PBI_RS,
    WS_ROOT,
    EnginePipeline,
)

__all__ = ["DEFAULT_TEMPLATE", "PBI_RS", "WS_ROOT", "EnginePipeline"]
