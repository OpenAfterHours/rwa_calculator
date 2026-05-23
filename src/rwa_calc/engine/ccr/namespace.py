"""
Polars LazyFrame namespace for Counterparty Credit Risk (SA-CCR) calculations.

Provides the fluent API that drives the SA-CCR EAD pipeline:

- ``lf.ccr.replacement_cost_unmargined()`` - RC = max(V - C, 0) per Art. 275(1)
- ``lf.ccr.adjusted_notional_ir()``        - IR adjusted notional per Art. 279b
- ``lf.ccr.supervisory_delta_linear()``    - Linear +/- 1 delta per Art. 279a
- ``lf.ccr.maturity_factor_unmargined()``  - MF = sqrt(min(M,1y)/1y), Art. 279c
- ``lf.ccr.pfe_ir_singleton()``            - PFE IR singleton per Art. 278/280
- ``lf.ccr.sa_ccr_ead(config)``            - EAD = alpha*(RC+PFE), Art. 274

Pipeline position:
    Classifier -> CCRCalculator -> CRMProcessor

CCRCalculator (added in a later batch) will be a thin orchestrator over this
namespace; it chains these methods in regulatory order.

Importing this module registers the ``ccr`` namespace with Polars.

Usage:
    import polars as pl
    import rwa_calc.engine.ccr  # Triggers namespace registration

    rc = netting_sets.ccr.replacement_cost_unmargined()

References:
- CRR Art. 274-280f: SA-CCR EAD calculation
"""

from __future__ import annotations

import logging
from datetime import date

import polars as pl

logger = logging.getLogger(__name__)


# =============================================================================
# LAZYFRAME NAMESPACE
# =============================================================================


@pl.api.register_lazyframe_namespace("ccr")
class CCRNamespace:
    """SA-CCR calculation namespace for Polars LazyFrames.

    Provides the fluent API that drives the SA-CCR EAD pipeline — replacement
    cost, adjusted notional, supervisory delta, maturity factor, potential
    future exposure, and final EAD. Each method delegates to the matching
    free function in the ``rwa_calc.engine.ccr`` subpackage.
    """

    def __init__(self, lf: pl.LazyFrame) -> None:
        self._lf = lf

    def replacement_cost_unmargined(self) -> pl.LazyFrame:
        """Delegate to :func:`rwa_calc.engine.ccr.rc.compute_rc_unmargined`."""
        from rwa_calc.engine.ccr.rc import compute_rc_unmargined

        return compute_rc_unmargined(self._lf)

    def replacement_cost_margined(self) -> pl.LazyFrame:
        """Delegate to :func:`rwa_calc.engine.ccr.rc.compute_rc_margined`."""
        from rwa_calc.engine.ccr.rc import compute_rc_margined

        return compute_rc_margined(self._lf)

    def adjusted_notional_ir(self, reporting_date: date) -> pl.LazyFrame:
        """Delegate to :func:`compute_adjusted_notional_ir`."""
        from rwa_calc.engine.ccr.adjusted_notional import compute_adjusted_notional_ir

        return compute_adjusted_notional_ir(self._lf, reporting_date)

    def supervisory_delta_linear(self) -> pl.LazyFrame:
        """Delegate to :func:`compute_supervisory_delta_linear`."""
        from rwa_calc.engine.ccr.supervisory_delta import compute_supervisory_delta_linear

        return compute_supervisory_delta_linear(self._lf)

    def maturity_factor_unmargined(self) -> pl.LazyFrame:
        """Delegate to :func:`compute_maturity_factor_unmargined`."""
        from rwa_calc.engine.ccr.maturity_factor import compute_maturity_factor_unmargined

        return compute_maturity_factor_unmargined(self._lf)

    def maturity_factor_margined(self) -> pl.LazyFrame:
        """Delegate to :func:`compute_maturity_factor_margined`."""
        from rwa_calc.engine.ccr.maturity_factor import compute_maturity_factor_margined

        return compute_maturity_factor_margined(self._lf)

    def pfe_ir_singleton(self) -> pl.LazyFrame:
        """Delegate to :func:`rwa_calc.engine.ccr.pfe.compute_pfe_ir_singleton`."""
        from rwa_calc.engine.ccr.pfe import compute_pfe_ir_singleton

        return compute_pfe_ir_singleton(self._lf)

    def sa_ccr_ead(self, config: object) -> pl.LazyFrame:
        """Delegate to :func:`rwa_calc.engine.ccr.sa_ccr.compute_ead`."""
        from rwa_calc.engine.ccr.sa_ccr import compute_ead

        return compute_ead(self._lf, config)  # type: ignore[arg-type]
