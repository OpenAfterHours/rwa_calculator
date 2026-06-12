"""
Real-estate loan-split stage package (migration Phase 4 — mandatory stage anatomy).

Pipeline position:
    crm_processor -> re_splitter -> calculators

Layout:
- ``stage``    — the uniform ``run(ctx, rulepack, run_config)`` adapter
- ``splitter`` — ``RealEstateSplitter``: physical secured / residual row
  split for property-collateralised SA exposures (CRR Art. 125/126, B3.1
  Art. 124F/H), per-component allocation, audit frame, RE002-RE004
  diagnostics, and the ``re_split_exit`` producer seal
- ``flagging`` — ``flag_property_reclassification_candidates``: the
  candidate-flagging brain invoked by the classify stage
  (``stages/classify/classifier.py``); co-located here because the
  ``re_split_*`` candidate columns it emits are consumed only by the
  splitter

``rwa_calc.engine.re_splitter`` remains as a thin back-compat shim
re-exporting ``RealEstateSplitter`` from here. Split parameters stay in
the data layer (``data/tables/re_split_parameters.py`` — arch_check
check 5).

References:
- CRR Art. 124-126: RRE / CRE preferential treatment and partial security
- PRA PS1/26 Art. 124C-124L: B3.1 RE loan-splitting tables
- docs/plans/target-architecture-migration.md (Phase 4)
"""

from __future__ import annotations

from rwa_calc.engine.stages.re_split.flagging import (
    flag_property_reclassification_candidates as flag_property_reclassification_candidates,
)
from rwa_calc.engine.stages.re_split.splitter import (
    RealEstateSplitter as RealEstateSplitter,
)
from rwa_calc.engine.stages.re_split.stage import run as run
