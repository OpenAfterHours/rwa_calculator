"""
Counterparty Credit Risk (CCR) engine subpackage — SA-CCR EAD calculation.

Pipeline position:
    Classifier -> CCRCalculator -> CRMProcessor

Key responsibilities:
- Compute SA-CCR Exposure at Default (EAD) per CRR Art. 274:
      EAD = alpha * (RC + PFE)
- Decompose the calculation into orthogonal stages: replacement cost (RC),
  potential future exposure (PFE), per-trade adjusted notional, supervisory
  delta, and maturity factor.

The SA-CCR formula bodies (replacement cost, adjusted notional, supervisory
delta, maturity factor, per-asset-class add-on, and final EAD) are implemented
across the ``rwa_calc.engine.ccr`` submodules.

Importing this package triggers registration of the ``ccr`` Polars LazyFrame
namespace via the sibling ``namespace`` module.

References:
- CRR Art. 274: SA-CCR EAD = alpha * (RC + PFE)
- CRR Art. 275: Replacement cost (margined / unmargined)
- CRR Art. 278: Potential future exposure
- CRR Art. 279a: Supervisory delta
- CRR Art. 279b: Adjusted notional (interest rate / FX)
- CRR Art. 279c: Maturity factor
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Importing the namespace module triggers @pl.api.register_lazyframe_namespace
# so that ``lf.ccr.*`` is available to callers as soon as the package loads.
from rwa_calc.engine.ccr import namespace as _namespace  # noqa: E402, F401
from rwa_calc.engine.ccr.adjusted_notional import compute_adjusted_notional_ir  # noqa: E402
from rwa_calc.engine.ccr.hedging_sets import (  # noqa: E402
    assign_hedging_set,
    assign_ir_maturity_bucket,
)
from rwa_calc.engine.ccr.maturity_factor import (  # noqa: E402
    compute_maturity_factor_margined,
    compute_maturity_factor_unmargined,
)
from rwa_calc.engine.ccr.pfe import compute_addon_per_asset_class  # noqa: E402
from rwa_calc.engine.ccr.pipeline_adapter import ccr_rows_to_exposures  # noqa: E402
from rwa_calc.engine.ccr.rc import compute_rc_margined, compute_rc_unmargined  # noqa: E402
from rwa_calc.engine.ccr.sa_ccr import (  # noqa: E402
    apply_legal_enforceability_gate,
    compute_ead,
)
from rwa_calc.engine.ccr.supervisory_delta import (  # noqa: E402
    compute_supervisory_delta_cdo_tranche,
    compute_supervisory_delta_linear,
    compute_supervisory_delta_option,
)
from rwa_calc.engine.ccr.wwr import apply_wwr_gate  # noqa: E402

__all__ = [
    "apply_legal_enforceability_gate",
    "apply_wwr_gate",
    "assign_hedging_set",
    "assign_ir_maturity_bucket",
    "ccr_rows_to_exposures",
    "compute_addon_per_asset_class",
    "compute_adjusted_notional_ir",
    "compute_ead",
    "compute_maturity_factor_margined",
    "compute_maturity_factor_unmargined",
    "compute_rc_margined",
    "compute_rc_unmargined",
    "compute_supervisory_delta_cdo_tranche",
    "compute_supervisory_delta_linear",
    "compute_supervisory_delta_option",
]
