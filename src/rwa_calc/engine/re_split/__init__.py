"""
Real-estate loan-split domain package.

Pipeline position:
    crm_processor -> re_splitter -> calculators

Layout:
- ``splitter`` — ``RealEstateSplitter``: physical secured / residual row
  split for property-collateralised SA exposures (CRR Art. 125/126, B3.1
  Art. 124F/H), per-component allocation, audit frame, RE002-RE004
  diagnostics, and the ``re_split_exit`` producer seal
- ``flagging`` — ``flag_property_reclassification_candidates``: the
  candidate-flagging brain invoked by the classify stage
  (``engine/classify/classifier.py``); co-located here because the
  ``re_split_*`` candidate columns it emits are consumed only by the
  splitter

The ``run(ctx, rulepack, run_config)`` adapter that wires this domain into the
fold lives at ``engine/stages/re_split.py``, not here: ``engine/stages/`` is
the wiring layer and holds nothing else. This package is the only home of the
RE loan-splitter domain; import ``RealEstateSplitter`` from here. Split
parameters live in ``params.py``, resolving their LTV caps from the rulepack
(``re_split_{rre,cre}_secured_ltv_cap`` in packs/{crr,b31}.py).

References:
- CRR Art. 124-126: RRE / CRE preferential treatment and partial security
- PRA PS1/26 Art. 124C-124L: B3.1 RE loan-splitting tables
- docs/plans/architecture-review-2026-08-29.md §2 (the stages/domain split)
"""

from __future__ import annotations

from rwa_calc.engine.re_split.flagging import (
    flag_property_reclassification_candidates as flag_property_reclassification_candidates,
)
from rwa_calc.engine.re_split.splitter import (
    RealEstateSplitter as RealEstateSplitter,
)
