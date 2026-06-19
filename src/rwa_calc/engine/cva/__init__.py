"""
Credit Valuation Adjustment (CVA) risk engine subpackage — BA-CVA.

Pipeline position:
    OutputAggregator -> CVA stage (engine/stages/cva.py) -> AggregatedResultBundle

Key responsibilities:
- Compute the Basic Approach to CVA risk own-funds requirement and the
  resulting risk-weighted exposure amount (RWEA_CVA) for the reduced version
  of BA-CVA (no eligible CVA hedges):
      OFR_CVA  = DS_BA-CVA x K_reduced
      RWEA_CVA = OFR_CVA x 12.5
- Read all supervisory parameters (DS_BA-CVA, rho, the discount rate, the
  sector x credit-quality RW table) from the resolved rulepack — no engine
  module-scope regulatory scalars.

The CVA capital charge is Basel-3.1-only (PRA PS1/26 Credit Valuation
Adjustment Risk Part). Under CRR the ``cva_ba_cva`` pack Feature is absent /
False and the CVA stage is a clean no-op.

References:
- PRA PS1/26 CVA Part 4.2: reduced BA-CVA (DS_BA-CVA = 0.65, rho = 50%).
- PRA PS1/26 CVA Part 4.3: SCVA_c, DF_NS supervisory discount factor, alpha.
- PRA PS1/26 CVA Part 4.4: supervisory CVA risk weights (sector x IG/HY-NR).
- PRA PS1/26 Own Funds Part 4(b): own-funds -> RWEA multiplier (12.5).
"""

from __future__ import annotations

import logging

from rwa_calc.engine.cva.ba_cva import compute_ba_cva_rwa

logger = logging.getLogger(__name__)

__all__ = ["compute_ba_cva_rwa"]
