"""brand_audit_types — moved to :mod:`agentic_bi.brand.audit_types`.

Compatibility shim, kept for one release. This module *is* the moved module: the
name is rebound in :data:`sys.modules`, so ``from agentic_bi.brand_audit_types import X``
(including private names) behaves exactly like importing
:mod:`agentic_bi.brand.audit_types`. New code should use the new path directly.
"""

from __future__ import annotations

import sys

import agentic_bi.brand.audit_types as _module

sys.modules[__name__] = _module
