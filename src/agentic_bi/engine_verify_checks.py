"""engine_verify_checks — moved to :mod:`agentic_bi.engine.verify_checks`.

Compatibility shim, kept for one release. This module *is* the moved module: the
name is rebound in :data:`sys.modules`, so ``from agentic_bi.engine_verify_checks import X``
(including private names) behaves exactly like importing
:mod:`agentic_bi.engine.verify_checks`. New code should use the new path directly.
"""

from __future__ import annotations

import sys

import agentic_bi.engine.verify_checks as _module

sys.modules[__name__] = _module
