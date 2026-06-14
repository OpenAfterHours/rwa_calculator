"""
Pins for the S11c FX-threshold migration (the FX trap).

Phase 5 S11c moves the regulatory monetary thresholds off
``config.thresholds`` (a RegulatoryThresholds dataclass FX-converted at
construction) onto the rulepack: the FX-INVARIANT regulatory values live in the
``regulatory_thresholds`` FormulaParams, and the engine applies the per-run
EUR/GBP rate via ``engine/thresholds.py::regulatory_threshold``, gated by the
``regulatory_thresholds_fx_derived`` Feature.

The decisive byte-identity proof is that the engine accessor reproduces
``RegulatoryThresholds.crr(rate)`` / ``.basel_3_1(rate)`` EXACTLY at ANY rate —
including non-default rates the 10k×4 parity gate never exercises (it ships no
fx_rates table, so it runs only at the default 0.8732 and is blind to this
path). These parametrised pins ARE that coverage.

References:
- CRR Art. 123 / 123A / 501 / 4(1)(146): EUR monetary thresholds.
- PRA PS1/26 Art. 147(5A) / 147A(1)(d) / 153(4): native GBP thresholds.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from rwa_calc.contracts.config import RegulatoryThresholds
from rwa_calc.engine.thresholds import regulatory_threshold
from rwa_calc.rulebook.resolve import resolve

_CRR_PACK = resolve("crr", date(2026, 1, 1))
_B31_PACK = resolve("b31", date(2027, 1, 1))

_FIELDS = (
    "sme_turnover_threshold",
    "sme_balance_sheet_threshold",
    "sme_exposure_threshold",
    "large_corporate_revenue_threshold",
    "retail_max_exposure",
    "qrre_max_limit",
    "lfse_total_assets_threshold",
)
# Default rate plus non-default rates the production FX-sync can produce.
_RATES = (Decimal("0.8732"), Decimal("0.95"), Decimal("0.50"), Decimal("1.0"))


def test_fx_derived_feature_per_regime() -> None:
    # Arrange / Act / Assert
    assert _CRR_PACK.feature("regulatory_thresholds_fx_derived") is True
    assert _B31_PACK.feature("regulatory_thresholds_fx_derived") is False


@pytest.mark.parametrize("rate", _RATES)
@pytest.mark.parametrize("field", _FIELDS)
def test_crr_threshold_matches_config_at_rate(field: str, rate: Decimal) -> None:
    # CRR thresholds = EUR base × rate, reproduced exactly at any rate.
    expected = getattr(RegulatoryThresholds.crr(eur_gbp_rate=rate), field)
    assert regulatory_threshold(_CRR_PACK, field, rate) == expected


@pytest.mark.parametrize("rate", _RATES)
@pytest.mark.parametrize("field", _FIELDS)
def test_b31_threshold_is_native_gbp_frozen(field: str, rate: Decimal) -> None:
    # B31 thresholds are native GBP (sme_balance_sheet frozen at the default
    # 0.8732 — B31 never FX-syncs), so the accessor IGNORES the rate.
    expected = getattr(RegulatoryThresholds.basel_3_1(eur_gbp_rate=Decimal("0.8732")), field)
    assert regulatory_threshold(_B31_PACK, field, rate) == expected


def test_sme_size_threshold_is_fx_rate_driven_end_to_end() -> None:
    """End-to-end wiring guard: the SME size boundary must move with eur_gbp_rate.

    The 10k×4 parity gate ships no fx_rates table, so it runs only at the
    default 0.8732 and is BLIND to the FX path — a static pack scalar (ignoring
    the rate) would pass that gate yet break production. This test fails such a
    regression: 48m GBP turnover sits above CRR 50m×0.8732 (=43.66m → not SME)
    but below 50m×0.99 (=49.5m → SME), so ``is_sme`` flips with the rate exactly
    as ``config.thresholds`` did before S11c.
    """
    import polars as pl

    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.engine.stages.classify.attributes import is_sme_by_size_expr

    frame = pl.LazyFrame({"sme_size_metric_gbp": [48_000_000.0], "sme_size_source": ["turnover"]})
    cfg_low = CalculationConfig.crr(
        reporting_date=date(2025, 12, 31), eur_gbp_rate=Decimal("0.8732")
    )
    cfg_high = CalculationConfig.crr(
        reporting_date=date(2025, 12, 31), eur_gbp_rate=Decimal("0.99")
    )

    is_sme_low = frame.with_columns(is_sme_by_size_expr(cfg_low).alias("x")).collect()["x"][0]
    is_sme_high = frame.with_columns(is_sme_by_size_expr(cfg_high).alias("x")).collect()["x"][0]

    assert not is_sme_low  # 48m > 43.66m → not SME at 0.8732
    assert is_sme_high  # 48m < 49.5m → SME at 0.99
