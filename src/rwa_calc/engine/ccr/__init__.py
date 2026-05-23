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

This batch (P8.4) only delivers the scaffold and ``compute_rc_unmargined``;
all other formula bodies stub via ``NotImplementedError`` and will be filled
by P8.10 / P8.12 / P8.13 / P8.14 / P8.17 in subsequent batches.

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
from rwa_calc.engine.ccr.pfe import (  # noqa: E402
    compute_addon_per_asset_class,
    compute_pfe_ir_singleton,
)
from rwa_calc.engine.ccr.rc import compute_rc_margined, compute_rc_unmargined  # noqa: E402
from rwa_calc.engine.ccr.sa_ccr import compute_ead  # noqa: E402
from rwa_calc.engine.ccr.supervisory_delta import (  # noqa: E402
    compute_supervisory_delta_cdo_tranche,
    compute_supervisory_delta_linear,
    compute_supervisory_delta_option,
)

__all__ = [
    "assign_hedging_set",
    "assign_ir_maturity_bucket",
    "compute_addon_per_asset_class",
    "compute_adjusted_notional_ir",
    "compute_ead",
    "compute_maturity_factor_margined",
    "compute_maturity_factor_unmargined",
    "compute_pfe_ir_singleton",
    "compute_rc_margined",
    "compute_rc_unmargined",
    "compute_supervisory_delta_cdo_tranche",
    "compute_supervisory_delta_linear",
    "compute_supervisory_delta_option",
]
