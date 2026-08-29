"""
FX conversion domain package.

Pipeline position:
    hierarchy (unify) -> FX conversion -> hierarchy (enrich)

Layout:
- ``converter``  — ``FXConverter``: the stateless five-method conversion
  kernel (exposures / collateral / guarantees / provisions / equity) plus
  the ``create_fx_converter`` factory
- ``conversion`` — ``convert_resolved_frames``: the unify -> enrich seam
  step invoked by ``engine/hierarchy/resolver.py`` (the ordering is
  load-bearing — enrichment and classifier thresholds assume
  reporting-currency amounts)

**FX is not a pipeline stage.** It has no ``run`` adapter and no slot in
``engine/registry.py``; it is a kernel called from inside the hierarchy
resolver. It lived under ``engine/stages/`` until the S1 move, pinned in
``arch_check.STAGE_PACKAGES_WITHOUT_RUN`` precisely because it could not
satisfy the stage contract — that pin is gone, and the package now sits
alongside the other domains under ``engine/``.

This package is the only home of the FX conversion kernel; import
``FXConverter`` from here and its ``create_fx_converter`` factory from
``engine.fx.converter``. ``engine/fx_rate_sync.py`` (EUR/GBP rate sync
consumed by the pipeline facade) is deliberately not part of this package.

References:
- CRR Art. 224 / Art. 233(3)-(4): downstream FX-mismatch haircuts read the
  ``original_currency`` audit column this conversion preserves
- docs/plans/architecture-review-2026-08-29.md §2 (the stages/domain split)
"""

from __future__ import annotations

from rwa_calc.engine.fx.conversion import (
    convert_resolved_frames as convert_resolved_frames,
)
from rwa_calc.engine.fx.converter import FXConverter as FXConverter
