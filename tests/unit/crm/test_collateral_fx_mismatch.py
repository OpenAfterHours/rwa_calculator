"""
Regression tests for P1.135 — collateral FX mismatch haircut under the full pipeline.

Under CRR Art. 224 (and identically under PRA PS1/26 Art. 224), the FX volatility
haircut (H_fx = 8% at the 10-day capital-market liquidation period) reduces
collateral value whenever the collateral currency differs from the exposure
currency. Before P1.135 was fixed, ``FXConverter.convert_collateral`` rewrote the
``currency`` column to the reporting currency without preserving an audit of the
pre-conversion currency, and ``_build_exposure_lookups`` sourced the
``exposure_currency`` column on collateral from the post-conversion exposure
``currency``. By the time ``HaircutCalculator.apply_haircuts`` compared
``currency != exposure_currency`` both sides were the reporting currency and
H_fx silently became 0.0 for every FX-mismatched secured exposure.

These tests pin the contract at two levels:

1. ``HaircutCalculator.apply_haircuts`` must honour ``original_currency`` when it
   is present on the collateral LazyFrame (the canonical post-FX-conversion
   state) and still fall back to ``currency`` when the audit column is absent.
2. Going through ``CRMProcessor.apply_crm`` with a real FX rate feed, a GBP
   exposure secured by USD cash collateral must have H_fx applied; the final
   exposure value after haircut must reflect the 8% FX haircut.

Why this matters: every FX-mismatched secured exposure was silently under-
reserving by 8% of the collateral value. Regression-guarding the LazyFrame path
is essential — the pre-existing ``calculate_single_haircut`` unit tests pass
``collateral_currency``/``exposure_currency`` directly as scalars and never
exercise the column-comparison branch that holds the bug.

References:
    CRR Art. 224 Table 4: H_fx = 8% (10-day liquidation period)
    PRA PS1/26 Art. 224: Identical FX mismatch treatment under Basel 3.1
    IMPLEMENTATION_PLAN.md P1.135 / P1.136
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.crm.haircuts import HaircutCalculator
from rwa_calc.engine.crm.processor import (
    _build_exposure_lookups,
    _join_collateral_to_lookups,
)


@pytest.fixture
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


def _cash_collateral_lf(
    *,
    collateral_currency: str,
    exposure_currency: str,
    original_currency: str | None,
    market_value: float = 100_000.0,
    liquidation_period_days: int = 10,
) -> pl.LazyFrame:
    """Build a minimal cash-collateral LazyFrame shaped like the state that
    enters ``HaircutCalculator.apply_haircuts`` (post FX conversion, post join
    with exposure lookups).

    ``original_currency`` is omitted when ``None`` so the fall-back branch that
    compares plain ``currency`` columns can be exercised.
    """
    data: dict[str, list[object]] = {
        "collateral_reference": ["COLL_001"],
        "collateral_type": ["cash"],
        "currency": [collateral_currency],
        "market_value": [market_value],
        "nominal_value": [market_value],
        "issuer_cqs": [None],
        "residual_maturity_years": [None],
        "exposure_currency": [exposure_currency],
        "liquidation_period_days": [liquidation_period_days],
        "is_eligible_financial_collateral": [True],
    }
    if original_currency is not None:
        data["original_currency"] = [original_currency]
    return pl.LazyFrame(data)


class TestApplyHaircutsHonoursOriginalCurrency:
    """HaircutCalculator.apply_haircuts: use ``original_currency`` when present."""

    def test_fx_mismatch_applied_when_original_currency_differs_post_conversion(
        self,
        crr_config: CalculationConfig,
    ) -> None:
        """P1.135 regression: after FX conversion both ``currency`` and
        ``exposure_currency`` are the reporting currency (GBP), but
        ``original_currency`` still records the USD collateral. H_fx must fire."""
        collateral = _cash_collateral_lf(
            collateral_currency="GBP",  # post FX conversion
            exposure_currency="GBP",  # post FX conversion via processor join
            original_currency="USD",  # pre-conversion audit
        )
        calc = HaircutCalculator(is_basel_3_1=False)
        result = calc.apply_haircuts(collateral, crr_config).collect()

        assert result["fx_haircut"][0] == pytest.approx(0.08)
        # 100,000 * (1 - 0.0 collateral haircut - 0.08 fx) = 92,000
        assert result["value_after_haircut"][0] == pytest.approx(92_000.0)

    def test_no_haircut_when_original_currencies_match(
        self,
        crr_config: CalculationConfig,
    ) -> None:
        """Same pre-conversion currency → no FX haircut even if columns exist."""
        collateral = _cash_collateral_lf(
            collateral_currency="GBP",
            exposure_currency="GBP",
            original_currency="GBP",
        )
        calc = HaircutCalculator(is_basel_3_1=False)
        result = calc.apply_haircuts(collateral, crr_config).collect()

        assert result["fx_haircut"][0] == pytest.approx(0.0)
        assert result["value_after_haircut"][0] == pytest.approx(100_000.0)

    def test_falls_back_to_currency_when_original_currency_absent(
        self,
        crr_config: CalculationConfig,
    ) -> None:
        """When ``original_currency`` is absent (e.g., legacy callers invoking
        ``apply_haircuts`` directly without going through ``FXConverter``), the
        calculator must still detect mismatch via the plain ``currency`` column."""
        collateral = _cash_collateral_lf(
            collateral_currency="USD",
            exposure_currency="GBP",
            original_currency=None,
        )
        calc = HaircutCalculator(is_basel_3_1=False)
        result = calc.apply_haircuts(collateral, crr_config).collect()

        assert result["fx_haircut"][0] == pytest.approx(0.08)
        assert result["value_after_haircut"][0] == pytest.approx(92_000.0)


class TestProcessorUsesPreConversionExposureCurrency:
    """``_build_exposure_lookups`` must prefer ``original_currency`` so that
    the ``exposure_currency`` column written onto collateral in
    ``_join_collateral_to_lookups`` carries the pre-FX-conversion currency."""

    def test_exposure_currency_on_collateral_is_pre_conversion_currency(
        self,
    ) -> None:
        """P1.135 regression at the processor level. Exposures flow in post-FX-
        conversion (currency=GBP) but retain original_currency=USD. The joined
        ``exposure_currency`` on collateral must match USD so that a downstream
        H_fx check against collateral's own original_currency can see mismatch.
        """
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["LOAN_A"],
                "counterparty_reference": ["CP001"],
                "currency": ["GBP"],  # post-conversion
                "original_currency": ["USD"],  # pre-conversion audit
                "ead_gross": [100_000.0],
                "maturity_date": [date(2030, 12, 31)],
            }
        )
        collateral = pl.LazyFrame(
            {
                "collateral_reference": ["COLL_001"],
                "beneficiary_reference": ["LOAN_A"],
                "beneficiary_type": ["loan"],
                "collateral_type": ["cash"],
                "currency": ["GBP"],
                "original_currency": ["USD"],
                "market_value": [79_000.0],
            }
        )
        direct_lookup, facility_lookup, cp_lookup = _build_exposure_lookups(exposures)
        joined = _join_collateral_to_lookups(
            collateral, direct_lookup, facility_lookup, cp_lookup
        ).collect()

        assert joined["exposure_currency"][0] == "USD"

    def test_exposure_currency_falls_back_to_currency_when_no_original(
        self,
    ) -> None:
        """When upstream didn't provide ``original_currency`` (e.g., a direct
        unit-test caller), the processor falls back to the plain ``currency``
        column so the legacy contract is preserved."""
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["LOAN_A"],
                "counterparty_reference": ["CP001"],
                "currency": ["USD"],
                "ead_gross": [100_000.0],
                "maturity_date": [date(2030, 12, 31)],
            }
        )
        collateral = pl.LazyFrame(
            {
                "collateral_reference": ["COLL_001"],
                "beneficiary_reference": ["LOAN_A"],
                "beneficiary_type": ["loan"],
                "collateral_type": ["cash"],
                "currency": ["GBP"],
                "market_value": [79_000.0],
            }
        )
        direct_lookup, facility_lookup, cp_lookup = _build_exposure_lookups(exposures)
        joined = _join_collateral_to_lookups(
            collateral, direct_lookup, facility_lookup, cp_lookup
        ).collect()

        assert joined["exposure_currency"][0] == "USD"
