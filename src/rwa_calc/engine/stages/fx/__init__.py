"""
FX conversion stage package (migration Phase 4 — code seam landed; registry
promotion deferred to a later slice).

Pipeline position:
    hierarchy (unify) -> FX conversion -> hierarchy (enrich)

Layout:
- ``converter``  — ``FXConverter``: the stateless five-method conversion
  kernel (exposures / collateral / guarantees / provisions / equity) plus
  the ``create_fx_converter`` factory
- ``conversion`` — ``convert_resolved_frames``: the unify -> enrich seam
  step invoked by ``stages/hierarchy/resolver.py`` (the ordering is
  load-bearing — enrichment and classifier thresholds assume
  reporting-currency amounts)

``rwa_calc.engine.fx_converter`` remains as a thin back-compat shim
re-exporting ``FXConverter`` and ``create_fx_converter`` from here.
``engine/fx_rate_sync.py`` (EUR/GBP rate sync consumed by the pipeline
facade) is deliberately not part of this package.

References:
- CRR Art. 224 / Art. 233(3)-(4): downstream FX-mismatch haircuts read the
  ``original_currency`` audit column this stage preserves
- docs/plans/target-architecture-migration.md (Phase 4)
"""

from __future__ import annotations

from rwa_calc.engine.stages.fx.conversion import (
    convert_resolved_frames as convert_resolved_frames,
)
from rwa_calc.engine.stages.fx.converter import FXConverter as FXConverter
