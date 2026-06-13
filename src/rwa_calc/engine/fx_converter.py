"""
Back-compat shim for the FX conversion kernel.

The implementation moved to the stage package ``rwa_calc.engine.stages.fx``
(migration Phase 4 Slice 4): ``converter`` (``FXConverter`` +
``create_fx_converter``) and ``conversion`` (``convert_resolved_frames``,
the unify -> enrich seam step invoked by the hierarchy resolver). This
module remains only so historical imports
(``from rwa_calc.engine.fx_converter import FXConverter``) keep working;
new code should import from the stage package directly.

References:
- CRR Art. 224 / Art. 233(3)-(4): FX-mismatch haircuts consume the
  ``original_currency`` audit column preserved by the converter
- docs/plans/target-architecture-migration.md (Phase 4)
"""

from __future__ import annotations

import logging

from rwa_calc.engine.stages.fx.converter import (
    FXConverter as FXConverter,
)
from rwa_calc.engine.stages.fx.converter import (
    create_fx_converter as create_fx_converter,
)

logger = logging.getLogger(__name__)
