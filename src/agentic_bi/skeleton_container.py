"""skeleton_container — moved to :mod:`agentic_bi.skeleton.container`.

Compatibility shim, kept for one release. This module *is* the moved module: the
name is rebound in :data:`sys.modules`, so ``from agentic_bi.skeleton_container import X``
(including private names) behaves exactly like importing
:mod:`agentic_bi.skeleton.container`. New code should use the new path directly.
"""

from __future__ import annotations

import sys

import agentic_bi.skeleton.container as _module

sys.modules[__name__] = _module
