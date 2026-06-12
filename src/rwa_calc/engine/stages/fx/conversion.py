"""
Resolved-frame FX conversion step for the hierarchy unify -> enrich seam.

Pipeline position:
    HierarchyResolver.resolve: unify -> convert_resolved_frames -> enrich

Key responsibilities:
- ``convert_resolved_frames``: run the five ``FXConverter`` conversions
  (unified exposures + the four optional side frames: collateral,
  guarantees, provisions, equity exposures) in one pass and return the
  converted frames.
- The placement is load-bearing: ``convert_exposures`` needs the unified
  frame (``original_amount`` reads drawn + interest + nominal together),
  while LTV / property-coverage / lending-group totals and the
  classifier's GBP thresholds downstream assume reporting-currency
  amounts — so conversion must run after unify and before enrich.

References:
- CRR Art. 224 / Art. 233(3)-(4): downstream FX-mismatch haircuts read the
  ``original_currency`` audit column preserved here
- docs/plans/target-architecture-migration.md (Phase 4)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from rwa_calc.engine.stages.fx.converter import FXConverter

if TYPE_CHECKING:
    import polars as pl

    from rwa_calc.contracts.config import CalculationConfig

logger = logging.getLogger(__name__)


def convert_resolved_frames(
    exposures: pl.LazyFrame,
    collateral: pl.LazyFrame | None,
    guarantees: pl.LazyFrame | None,
    provisions: pl.LazyFrame | None,
    equity_exposures: pl.LazyFrame | None,
    fx_rates: pl.LazyFrame | None,
    config: CalculationConfig,
) -> tuple[
    pl.LazyFrame,
    pl.LazyFrame | None,
    pl.LazyFrame | None,
    pl.LazyFrame | None,
    pl.LazyFrame | None,
]:
    """Convert the unified exposures and the four optional side frames.

    Args:
        exposures: Unified exposure frame (post hierarchy unify)
        collateral: Optional collateral frame
        guarantees: Optional guarantees frame
        provisions: Optional provisions frame
        equity_exposures: Optional equity exposures frame
        fx_rates: FX rates with currency_from, currency_to, rate columns
        config: Calculation configuration with base_currency

    Returns:
        Tuple of (exposures, collateral, guarantees, provisions,
        equity_exposures) with amounts converted to the reporting currency
        and ``original_currency`` audit columns added; ``None`` side frames
        pass through as ``None``.
    """
    fx_converter = FXConverter()
    exposures = fx_converter.convert_exposures(exposures, fx_rates, config)
    collateral = (
        fx_converter.convert_collateral(collateral, fx_rates, config)
        if collateral is not None
        else None
    )
    guarantees = (
        fx_converter.convert_guarantees(guarantees, fx_rates, config)
        if guarantees is not None
        else None
    )
    provisions = (
        fx_converter.convert_provisions(provisions, fx_rates, config)
        if provisions is not None
        else None
    )
    equity_exposures = (
        fx_converter.convert_equity_exposures(equity_exposures, fx_rates, config)
        if equity_exposures is not None
        else None
    )
    return exposures, collateral, guarantees, provisions, equity_exposures
