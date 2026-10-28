"""skeleton_visuals_extra — moved to :mod:`agentic_bi.skeleton.visuals_extra`.

Compatibility shim, kept for one release. This module *is* the moved module: the
name is rebound in :data:`sys.modules`, so ``from agentic_bi.skeleton_visuals_extra import X``
(including private names) behaves exactly like importing
:mod:`agentic_bi.skeleton.visuals_extra`. New code should use the new path directly.
"""

from __future__ import annotations

import sys

import agentic_bi.skeleton.visuals_extra as _module

sys.modules[__name__] = _module
