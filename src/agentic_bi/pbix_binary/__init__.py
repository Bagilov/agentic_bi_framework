"""Binary DataModel (ABF) member editing for `.pbix` containers.

The binary VertiPaq `DataModel` is a closed, XPress9-framed format that cannot
be authored from scratch in Python — but it can be edited at the *member* level.
This subpackage is the single place that knows the DataModel framing and the ABF
index structures, so higher layers never touch raw offsets.

Modules:
    abf_model      - ABF member model + the two XML indexes (parse/serialize)
    abf_codec      - XPress9 framing of the DataModel member (compress/decompress)
    abf_relayout   - rebuild an ABF around arbitrary-length members, re-offsetting
    patch_pipeline - member-level patch pipeline (equal + uneven length) + zip swap
    patch_cli      - `agentic-bi-pbix-patch` command line

Typical use:

    from agentic_bi.pbix_binary import patch_pipeline

    report = patch_pipeline.apply_patches("template.pbix", [
        {"kind": "replace_member", "member": "metadata.sqlitedb",
         "path": "new_model.db"},
    ], "out.pbix")

Environment-agnostic: no hosts, shares or personal paths appear here; every
input is a parameter. The `xpress9` codec is optional (`pip install -e
".[binary]"`).
"""

from __future__ import annotations

from agentic_bi.pbix_binary.abf_codec import (
    DataModelCodecError,
    compress_datamodel,
    decompress_datamodel,
    xpress9_available,
)
from agentic_bi.pbix_binary.abf_relayout import (
    ABFIndex,
    ABFLayoutError,
    find_member,
    member_blob,
    parse_abf_index,
    relayout_abf,
)
from agentic_bi.pbix_binary.patch_pipeline import (
    PatchError,
    PatchReport,
    apply_patches,
    classify_patches,
    load_spec,
    swap_datamodel,
)

__all__ = [
    "ABFIndex",
    "ABFLayoutError",
    "DataModelCodecError",
    "PatchError",
    "PatchReport",
    "apply_patches",
    "classify_patches",
    "compress_datamodel",
    "decompress_datamodel",
    "find_member",
    "load_spec",
    "member_blob",
    "parse_abf_index",
    "relayout_abf",
    "swap_datamodel",
    "xpress9_available",
]
