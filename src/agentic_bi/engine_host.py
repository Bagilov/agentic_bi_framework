"""engine_host — moved to :mod:`agentic_bi.engine.host`.

Compatibility shim, kept for one release. This module *is* the moved module: the
name is rebound in :data:`sys.modules`, so ``from agentic_bi.engine_host import X``
(including private names) behaves exactly like importing
:mod:`agentic_bi.engine.host`. New code should use the new path directly.
"""

from __future__ import annotations

import sys

import agentic_bi.engine.host as _module

sys.modules[__name__] = _module
