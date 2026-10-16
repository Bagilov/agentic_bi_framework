#!/usr/bin/env python3
"""Run the framework test build.

Thin wrapper around `agentic_bi.test_build`. Cross-platform when a prebuilt
DataModel is supplied via `--datamodel`; uses the Power BI Desktop AS engine on
Windows otherwise.

    python scripts/test_build.py --data examples/engine_sales.csv --table Sales \
        --template templates/template.pbix --datamodel model.abf \
        --out output_files/test_build.pbix --report output_files/test_build.json
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agentic_bi.test_build import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
