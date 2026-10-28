"""skeleton_assembly — moved to :mod:`agentic_bi.skeleton.assembly`.

Compatibility shim, kept for one release. This module *is* the moved module: the
name is rebound in :data:`sys.modules`, so ``from agentic_bi.skeleton_assembly import X``
(including private names) behaves exactly like importing
:mod:`agentic_bi.skeleton.assembly`. New code should use the new path directly.
"""

from __future__ import annotations

import sys

import agentic_bi.skeleton.assembly as _module

sys.modules[__name__] = _module


if __name__ == "__main__":  # pragma: no cover
    _module.main()
