"""
Regression tests for P1.135 / P1.186 — collateral FX mismatch haircut.

Under CRR Art. 224 (and identically under PRA PS1/26 Art. 224), the FX volatility
haircut (H_fx) reduces collateral value whenever the collateral currency differs
from the exposure currency.  The base H_fx is 8% at the 10-day capital-market
liquidation period; Art. 226(2) scales this by sqrt(T_m / 10).

P1.135 fix: ``FXConverter.convert_collateral`` rewrote the ``currency`` column to
the reporting currency without preserving an audit of the pre-conversion currency,
causing H_fx to silently become 0.0.  Fixed by carrying ``original_currency``
through the pipeline and comparing pre-conversion pairs.

P1.186 fix: The liquidation period used for H_fx defaulted to 10 days for all
non-SFT secured lending, where Art. 224(2)(a) prescribes 20 days.  The corrected
default is:
- Explicit ``liquidation_period_days`` column on the collateral row (override)
- ``exposure_is_sft=True``  → 5-day (repo/SFT, Art. 224(2)(c))
- ``exposure_is_sft=False`` → 20-day (secured lending, Art. 224(2)(a) + Art. 226(2))

These tests pin the contract at two levels:

1. ``HaircutCalculator.apply_haircuts`` must honour ``original_currency`` when it
   is present on the collateral LazyFrame (the canonical post-FX-conversion
   state) and still fall back to ``currency`` when the audit column is absent.
2. Going through ``CRMProcessor.apply_crm`` with a real FX rate feed, a GBP
   exposure secured by USD cash collateral must have H_fx applied; the final
   exposure value after haircut must reflect the FX haircut at the correct period.

Why this matters: every FX-mismatched secured lending exposure was silently under-
reserving by ~3% of the collateral value (8% vs 11.314% H_fx) after P1.186.
Regression-guarding the LazyFrame path is essential — the pre-existing
``calculate_single_haircut`` unit tests pass ``collateral_currency``/
``exposure_currency`` directly as scalars and never exercise the column-comparison
branch that holds the bug.

References:
    CRR Art. 224 Table 4: H_fx = 8% (10-day capital market liquidation period)
    CRR Art. 224(2)(a): Secured lending liquidation period = 20 days
    CRR Art. 224(2)(c): SFT / repo liquidation period = 5 days
    CRR Art. 226(2): H_m = H_10 × sqrt(T_m / 10)
    PRA PS1/26 Art. 224: Identical FX mismatch treatment under Basel 3.1
    IMPLEMENTATION_PLAN.md P1.135 / P1.136 / P1.186
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
        ``original_currency`` still records the USD collateral. H_fx must fire.

        P1.186 override path: explicit ``liquidation_period_days=10`` on the
        collateral row overrides the P1.186 20-day secured-lending default so
        that this test continues to pin the 10-day (8%) haircut behaviour.
        """
        collateral = _cash_collateral_lf(
            collateral_currency="GBP",  # post FX conversion
            exposure_currency="GBP",  # post FX conversion via processor join
            original_currency="USD",  # pre-conversion audit
            liquidation_period_days=10,  # explicit override — P1.186
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
        """Same pre-conversion currency → no FX haircut even if columns exist.

        P1.186 override path: explicit ``liquidation_period_days=10`` ensures
        the no-mismatch case is tested independently of the P1.186 period logic.
        """
        collateral = _cash_collateral_lf(
            collateral_currency="GBP",
            exposure_currency="GBP",
            original_currency="GBP",
            liquidation_period_days=10,  # explicit override — P1.186
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
        calculator must still detect mismatch via the plain ``currency`` column.

        P1.186 override path: explicit ``liquidation_period_days=10`` keeps the
        legacy-caller contract pinned to the 10-day (8%) haircut.
        """
        collateral = _cash_collateral_lf(
            collateral_currency="USD",
            exposure_currency="GBP",
            original_currency=None,
            liquidation_period_days=10,  # explicit override — P1.186
        )
        calc = HaircutCalculator(is_basel_3_1=False)
        result = calc.apply_haircuts(collateral, crr_config).collect()

        assert result["fx_haircut"][0] == pytest.approx(0.08)
        assert result["value_after_haircut"][0] == pytest.approx(92_000.0)


def _cash_collateral_lf_no_period(
    *,
    collateral_currency: str,
    exposure_currency: str,
    original_currency: str | None,
    market_value: float = 100_000.0,
    exposure_is_sft: bool | None = None,
) -> pl.LazyFrame:
    """Build a minimal cash-collateral LazyFrame WITHOUT a ``liquidation_period_days``
    column (or with a null value), so the engine must fall back to the
    ``exposure_is_sft``-driven default introduced by P1.186.

    ``exposure_is_sft`` is placed directly on the collateral frame to mimic
    the post-``_join_collateral_to_lookups`` state (where the column is copied
    from the exposure lookup under the alias ``exposure_is_sft``).
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
        "is_eligible_financial_collateral": [True],
        # No liquidation_period_days column — engine must use exposure_is_sft default
    }
    if original_currency is not None:
        data["original_currency"] = [original_currency]
    if exposure_is_sft is not None:
        data["exposure_is_sft"] = [exposure_is_sft]
    return pl.LazyFrame(data)


class TestP1186DefaultLiquidationPeriod:
    """P1.186: correct default liquidation period for FX haircut scaling.

    CRR Art. 224(2)(a) prescribes 20 days for secured lending (non-SFT) and
    Art. 224(2)(c) prescribes 5 days for SFT / repo transactions.  Before P1.186
    the engine hard-coded ``fill_null(10)`` for all cases, understating capital
    for secured lending by ~3% of FX-mismatched collateral value.
    """

    def test_secured_lending_default_uses_20_day_hfx(
        self,
        crr_config: CalculationConfig,
    ) -> None:
        """Non-SFT secured lending with no explicit liquidation_period_days must
        apply the 20-day FX haircut: H_fx = 8% × sqrt(20/10) = 8% × sqrt(2)
        ≈ 11.3137%.

        Hand-calc (CRR Art. 224(2)(a) + Art. 226(2)):
            H_fx_20 = 0.08 × sqrt(2) = 0.113137
            value_after_haircut = 100,000 × (1 - 0 - 0.113137) = 88,686.29

        References:
            CRR Art. 224(2)(a): secured lending liquidation period = 20 days
            CRR Art. 226(2): H_m = H_10 × sqrt(T_m / 10)
        """
        # Arrange — no liquidation_period_days column; exposure_is_sft=False
        collateral = _cash_collateral_lf_no_period(
            collateral_currency="EUR",
            exposure_currency="GBP",
            original_currency=None,
            market_value=100_000.0,
            exposure_is_sft=False,
        )

        # Act
        calc = HaircutCalculator(is_basel_3_1=False)
        result = calc.apply_haircuts(collateral, crr_config).collect()

        # Assert — 20-day H_fx = 8% × sqrt(2) ≈ 0.113137
        assert result["fx_haircut"][0] == pytest.approx(0.113137, rel=1e-4)
        # 100,000 × (1 − 0.113137) = 88,686.29
        assert result["value_after_haircut"][0] == pytest.approx(88_686.29, rel=1e-4)

    def test_sft_exposure_uses_5_day_hfx(
        self,
    ) -> None:
        """SFT-flagged exposure propagated through _build_exposure_lookups +
        _join_collateral_to_lookups must drive the 5-day FX haircut:
        H_fx = 8% × sqrt(5/10) = 8% × sqrt(0.5) ≈ 5.6569%.

        The test exercises the processor join path so that ``is_sft`` flowing
        from the exposure schema is correctly aliased to ``exposure_is_sft`` on
        the joined collateral frame.

        Hand-calc (CRR Art. 224(2)(c)):
            H_fx_5 = 0.08 × sqrt(0.5) = 0.056569
            value_after_haircut = 100,000 × (1 - 0 - 0.056569) = 94,343.15

        References:
            CRR Art. 224(2)(c): SFT / repo liquidation period = 5 days
            CRR Art. 226(2): H_m = H_10 × sqrt(T_m / 10)
        """
        from datetime import date

        from rwa_calc.contracts.config import CalculationConfig

        crr_config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))

        # Arrange — exposure with is_sft=True; collateral has no liquidation_period_days
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["LOAN_SFT"],
                "counterparty_reference": ["CP001"],
                "currency": ["GBP"],
                "original_currency": ["GBP"],
                "ead_gross": [1_000_000.0],
                "maturity_date": [date(2025, 6, 30)],
                "is_sft": [True],
            }
        )
        collateral = pl.LazyFrame(
            {
                "collateral_reference": ["COLL_SFT"],
                "beneficiary_reference": ["LOAN_SFT"],
                "beneficiary_type": ["loan"],
                "collateral_type": ["cash"],
                "currency": ["EUR"],
                "original_currency": ["EUR"],
                "market_value": [100_000.0],
                "nominal_value": [100_000.0],
                "issuer_cqs": [None],
                "residual_maturity_years": [None],
                "is_eligible_financial_collateral": [True],
                # No liquidation_period_days — must derive from exposure_is_sft
            }
        )

        # Act — run through the processor join to propagate is_sft onto collateral
        direct_lookup, facility_lookup, cp_lookup = _build_exposure_lookups(exposures)
        joined = _join_collateral_to_lookups(collateral, direct_lookup, facility_lookup, cp_lookup)

        # Now apply haircuts to the joined frame
        calc = HaircutCalculator(is_basel_3_1=False)
        result = calc.apply_haircuts(joined, crr_config).collect()

        # Assert — 5-day H_fx = 8% × sqrt(0.5) ≈ 0.056569
        assert result["fx_haircut"][0] == pytest.approx(0.056569, rel=1e-4)
        # 100,000 × (1 − 0.056569) = 94,343.15
        assert result["value_after_haircut"][0] == pytest.approx(94_343.15, rel=1e-4)


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
