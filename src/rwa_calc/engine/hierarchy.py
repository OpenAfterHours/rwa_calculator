"""
Back-compat shim for the hierarchy resolution stage.

The implementation moved to the stage package
``rwa_calc.engine.stages.hierarchy`` (migration Phase 4 Slice 2):
``resolver`` (HierarchyResolver recipe + delegators), ``graph``, ``ratings``,
``facility_undrawn``, ``unify``, ``enrich``, and the ``stage`` adapter.
This module remains only so historical imports
(``from rwa_calc.engine.hierarchy import HierarchyResolver``) keep working;
new code should import from the stage package directly.

References:
- CRR Art. 4(1)(39): Group of connected clients (hierarchy resolution)
- docs/plans/target-architecture-migration.md (Phase 4)
"""

from __future__ import annotations

import logging

from rwa_calc.engine.stages.hierarchy import (
    _FACILITY_QRRE_COUPLED_COLUMNS as _FACILITY_QRRE_COUPLED_COLUMNS,
)
from rwa_calc.engine.stages.hierarchy import (
    HierarchyResolver as HierarchyResolver,
)

logger = logging.getLogger(__name__)
