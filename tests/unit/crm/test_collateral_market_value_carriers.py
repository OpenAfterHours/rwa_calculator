"""
Direct + pipeline unit tests for the D2/D4 per-category market-value carrier
defect, work item W2.

PS1/26 Annex II cols 0180/0190/0200/0210 (``ps1-26-annex-ii-reporting-instructions.pdf``
p.108) and CRR Annex II cols 0150-0210 (``crr-annex-ii-reporting-instructins.pdf``
pp.100-102) require a two-limb reporting basis per collateral category:
    - Foundation Collateral Method / FIRB rows: the ADJUSTED value C_i after
      volatility adjustments and maturity mismatch (Art. 223-224/237-238).
    - AIRB rows: the ESTIMATED MARKET VALUE (pre-haircut).

``engine/crm/collateral.py:1250-1257`` produces only the adjusted basis today
(``collateral_{financial,cash,re,receivables,other_physical}_value``, built by
``_sum6("_adj_*")`` summing ``adjusted_value`` -- post-haircut). Under Basel 3.1
the real-estate supervisory haircut is 40% (``rulebook/packs/b31.py:913``,
applied at ``engine/crm/haircuts.py:326-335``), so a 500,000 real-estate
pledge publishes as 300,000 where the AIRB instruction requires 500,000.
Under CRR the haircut is 0% (``rulebook/packs/crr.py:954``), which is the only
reason CRR happens to look right.

This work item adds six new market-value carriers mirroring the existing
``_adj_*`` per-category blend one-for-one, but summing ``market_value``
instead of ``adjusted_value``:

    collateral_financial_market_value       (twin: collateral_financial_value)
    collateral_cash_market_value             (twin: collateral_cash_value)
    collateral_re_market_value               (twin: collateral_re_value)
    collateral_receivables_market_value      (twin: collateral_receivables_value)
    collateral_other_physical_market_value   (twin: collateral_other_physical_value)
    collateral_life_insurance_market_value   (no twin today)

D4 (cash/deposit categorised ahead of financial, landing in a carrier no
template reads) is explicitly NOT re-routed here: the operator has decided
the cash/financial fold happens later, at the aggregator seal
(``reporting_crm_lgd_financial`` = financial + cash). This file therefore
keeps ``collateral_cash_market_value`` a distinct carrier, exactly like its
``collateral_cash_value`` twin, and does not test any folding behaviour.

References:
    CRR Art. 223-224, 230-231: Collateral haircuts and Foundation Collateral
        Method waterfall
    PS1/26 Annex II cols 0150-0210: CRM techniques in LGD estimates reporting
    CRR Annex II cols 0150-0210: same reporting split under CRR
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from tests.fixtures.resolved_bundle import make_classified_bundle
from tests.unit.crm._crm_bundles import empty_counterparty_lookup, normalise_collateral

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ApproachType, ExposureClass, PermissionMode
from rwa_calc.engine.crm.collateral import _apply_collateral_unified
from rwa_calc.engine.crm.processor import CRMProcessor

# =============================================================================
# Category constants
# =============================================================================

# collateral_type exemplar per CRM category (engine/crm/expressions.py::collateral_category_expr).
CATEGORY_TYPE_EXEMPLAR: dict[str, str] = {
    "financial": "financial_collateral",
    "cash": "cash",
    "real_estate": "real_estate",
    "receivables": "receivables",
    "other_physical": "other_physical",
    "life_insurance": "life_insurance",
}

# Distinct nonzero market values per category so a routing test can't pass by
# coincidence (e.g. every category defaulting to the same figure).
CATEGORY_MARKET_VALUES: dict[str, float] = {
    "financial": 50_000.0,
    "cash": 20_000.0,
    "real_estate": 500_000.0,
    "receivables": 30_000.0,
    "other_physical": 40_000.0,
    "life_insurance": 5_000.0,
}

# The new W2 carrier per category (does not exist yet -- additive contract).
NEW_MARKET_VALUE_CARRIER: dict[str, str] = {
    "financial": "collateral_financial_market_value",
    "cash": "collateral_cash_market_value",
    "real_estate": "collateral_re_market_value",
    "receivables": "collateral_receivables_market_value",
    "other_physical": "collateral_other_physical_market_value",
    "life_insurance": "collateral_life_insurance_market_value",
}

# The existing adjusted-value twin per category (None where no twin exists today).
ADJUSTED_TWIN_CARRIER: dict[str, str | None] = {
    "financial": "collateral_financial_value",
    "cash": "collateral_cash_value",
    "real_estate": "collateral_re_value",
    "receivables": "collateral_receivables_value",
    "other_physical": "collateral_other_physical_value",
    "life_insurance": None,
}


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def processor() -> CRMProcessor:
    return CRMProcessor()


@pytest.fixture
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        permission_mode=PermissionMode.IRB,
    )


@pytest.fixture
def b31_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(
        reporting_date=date(2030, 6, 30),
        permission_mode=PermissionMode.IRB,
    )


@pytest.fixture
def direct_config() -> CalculationConfig:
    """Config for direct ``_apply_collateral_unified`` calls.

    Haircuts are pre-supplied on the collateral fixture in these tests (no
    ``HaircutCalculator`` in the call path), so the CRR/B3.1 choice is
    immaterial here -- CRR is used for concreteness.
    """
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        permission_mode=PermissionMode.IRB,
    )


# =============================================================================
# Helpers -- full pipeline (CRMProcessor), used where the real haircut
# calculator must run so the CRR/B3.1 divergence is genuine, not asserted.
# =============================================================================


def _pledge_exposure(
    ref: str = "EXP1",
    cp_ref: str = "CP1",
    drawn: float = 1_000_000.0,
    maturity: date = date(2029, 12, 31),
) -> pl.LazyFrame:
    """Single senior corporate F-IRB loan (mirrors test_p1_235's proven shape)."""
    return (
        pl.DataFrame(
            {
                "exposure_reference": [ref],
                "counterparty_reference": [cp_ref],
                "parent_facility_reference": [None],
                "exposure_class": [ExposureClass.CORPORATE.value],
                "approach": [ApproachType.FIRB.value],
                "drawn_amount": [drawn],
                "ead_gross": [drawn],
                "lgd": [None],
                "pd": [0.02],
                "maturity_date": [maturity],
                "currency": ["GBP"],
                "seniority": ["senior"],
                "exposure_type": ["loan"],
                "nominal_amount": [0.0],
                "interest": [0.0],
                "undrawn_amount": [0.0],
                "risk_type": [None],
                "ccf_modelled": [None],
                "is_short_term_trade_lc": [False],
                "product_type": ["TERM_LOAN"],
                "value_date": [date(2024, 1, 1)],
                "book_code": ["BOOK1"],
                "is_sft": [False],
            }
        )
        .lazy()
        .with_columns(pl.col("parent_facility_reference").cast(pl.String))
    )


def _pledge_collateral(
    collateral_type: str,
    market_value: float,
    beneficiary_ref: str = "EXP1",
) -> pl.LazyFrame:
    """One production-shaped collateral row, pledged directly (mirrors test_p1_235).

    ``value_after_maturity_adj`` is set equal to ``market_value`` here purely
    for schema shape -- the real ``HaircutCalculator`` invoked by
    ``CRMProcessor`` recomputes ``value_after_haircut`` /
    ``value_after_maturity_adj`` unconditionally from ``market_value`` and the
    resolved regime pack, overwriting this placeholder.
    """
    return normalise_collateral(
        pl.DataFrame(
            {
                "collateral_reference": ["COLL1"],
                "collateral_type": [collateral_type],
                "currency": ["GBP"],
                "market_value": [market_value],
                "value_after_maturity_adj": [market_value],
                "beneficiary_type": ["loan"],
                "beneficiary_reference": [beneficiary_ref],
                "maturity_date": [date(2035, 12, 31)],
                "issuer_type": [""],
                "issuer_cqs": [1],
                "is_main_index": [False],
                "is_eligible_financial_collateral": [False],
                "is_eligible_irb_collateral": [True],
                "residual_maturity_years": [10.0],
                "original_maturity_years": [10.0],
                "liquidation_period_days": [10],
            }
        ).lazy()
    )


def _make_pledge_bundle(exposures: pl.LazyFrame, collateral: pl.LazyFrame):
    return make_classified_bundle(
        all_exposures=exposures,
        equity_exposures=None,
        collateral=collateral,
        guarantees=None,
        provisions=None,
        counterparty_lookup=empty_counterparty_lookup(),
        classification_audit=None,
        classification_errors=[],
    )


def _run_crm(
    processor: CRMProcessor,
    config: CalculationConfig,
    bundle,
) -> pl.DataFrame:
    result = processor.get_crm_unified_bundle(bundle, config)
    return result.exposures.collect()


# =============================================================================
# Helpers -- direct ``_apply_collateral_unified`` calls, used for the
# category-routing / multi-level / null-convention tests where the real
# haircut calculator is not needed (mirrors test_art169_lgd_modelling.py).
# =============================================================================


def _direct_exposure(
    ref: str,
    ead: float = 1_000_000.0,
    cp_ref: str = "CP001",
    facility_ref: str | None = None,
) -> dict:
    return {
        "exposure_reference": ref,
        "approach": ApproachType.FIRB.value,
        "lgd": 0.45,
        "lgd_pre_crm": 0.45,
        "lgd_post_crm": 0.45,
        "ead_gross": ead,
        "ead_pre_crm": ead,
        "seniority": "senior",
        "counterparty_reference": cp_ref,
        "currency": "GBP",
        "maturity_date": date(2035, 1, 1),
        "parent_facility_reference": facility_ref,
    }


def _direct_collateral_row(
    coll_ref: str,
    beneficiary_ref: str,
    collateral_type: str,
    market_value: float,
    beneficiary_type: str = "exposure",
) -> dict:
    """No-haircut collateral row: value_after_haircut == market_value, so the
    adjusted twin and the new market-value carrier coincide numerically here
    -- these tests isolate ROUTING/BLEND/NULL behaviour, not the haircut
    divergence (covered separately by the full-pipeline CRR/B3.1 tests).
    """
    return {
        "collateral_reference": coll_ref,
        "beneficiary_reference": beneficiary_ref,
        "beneficiary_type": beneficiary_type,
        "collateral_type": collateral_type,
        "market_value": market_value,
        "value_after_haircut": market_value,
        "value_after_maturity_adj": market_value,
        "is_eligible_financial_collateral": True,
        "is_eligible_irb_collateral": True,
    }


def _empty_cp_totals() -> pl.LazyFrame:
    return pl.LazyFrame(
        {
            "counterparty_reference": pl.Series([], dtype=pl.String),
            "_cp_ead_total": pl.Series([], dtype=pl.Float64),
        }
    )


def _run_direct(
    exposure_rows: list[dict],
    collateral_rows: list[dict],
    config: CalculationConfig,
) -> pl.DataFrame:
    # parent_facility_reference is all-null (Null dtype) whenever no test row
    # sets a facility_ref; force String so the facility-cascade join keys
    # (_anc_fac vs beneficiary_reference: String) resolve without a dtype error.
    exposures = (
        pl.DataFrame(exposure_rows)
        .lazy()
        .with_columns(pl.col("parent_facility_reference").cast(pl.String))
    )
    collateral = pl.DataFrame(collateral_rows).lazy()
    return _apply_collateral_unified(exposures, collateral, config, _empty_cp_totals()).collect()


# =============================================================================
# 1. Market-value carrier is the pre-haircut basis (the single most
#    important test: pins the CRR/B3.1 real-estate divergence as the
#    discriminator between the two reporting bases).
# =============================================================================


class TestMarketValueIsPreHaircutBasis:
    """D2: PS1/26 Annex II col 0190 AIRB limb requires the pre-haircut
    estimated market value, not the post-haircut adjusted value."""

    def test_b31_re_market_value_equals_pre_haircut_500k(
        self, processor: CRMProcessor, b31_config: CalculationConfig
    ) -> None:
        """Under B3.1 the 40% RE haircut reduces the adjusted basis to
        300,000, but the new market-value carrier must stay at the pledged
        500,000 (pre-haircut).
        """
        # Arrange
        exposures = _pledge_exposure()
        collateral = _pledge_collateral(collateral_type="real_estate", market_value=500_000.0)
        bundle = _make_pledge_bundle(exposures, collateral)

        # Act
        result = _run_crm(processor, b31_config, bundle)

        # Assert
        assert result["collateral_re_market_value"][0] == pytest.approx(500_000.0, rel=1e-6)


# =============================================================================
# 2. Regime invariance of the market basis
# =============================================================================


class TestRegimeInvarianceOfMarketBasis:
    """D2: the market-value carrier must be identical under CRR and B3.1 even
    though the adjusted twin diverges (0% vs 40% RE haircut) -- the
    disappearance of the CRR/B3.1 gap on the market basis is the proof."""

    def test_re_market_value_identical_under_crr_and_b31(
        self,
        processor: CRMProcessor,
        crr_config: CalculationConfig,
        b31_config: CalculationConfig,
    ) -> None:
        # Arrange
        exposures = _pledge_exposure()
        collateral = _pledge_collateral(collateral_type="real_estate", market_value=500_000.0)
        crr_bundle = _make_pledge_bundle(exposures, collateral)
        b31_bundle = _make_pledge_bundle(exposures, collateral)

        # Act
        crr_result = _run_crm(processor, crr_config, crr_bundle)
        b31_result = _run_crm(processor, b31_config, b31_bundle)

        # Assert
        crr_market = crr_result["collateral_re_market_value"][0]
        b31_market = b31_result["collateral_re_market_value"][0]
        assert crr_market == pytest.approx(500_000.0, rel=1e-6)
        assert b31_market == pytest.approx(crr_market, rel=1e-6)


# =============================================================================
# 3. Category routing is exclusive
# =============================================================================


class TestCategoryRoutingIsExclusive:
    """D2: a real-estate pledge must raise only the RE market-value carrier,
    leaving the other five at 0.0."""

    def test_real_estate_pledge_raises_only_re_market_value_carrier(
        self, direct_config: CalculationConfig
    ) -> None:
        # Arrange
        exposure = [_direct_exposure("EXP001")]
        collateral = [_direct_collateral_row("COLL1", "EXP001", "real_estate", 500_000.0)]

        # Act
        result = _run_direct(exposure, collateral, direct_config)

        # Assert
        assert result["collateral_re_market_value"][0] == pytest.approx(500_000.0, rel=1e-6)
        assert result["collateral_financial_market_value"][0] == pytest.approx(0.0, abs=1e-9)
        assert result["collateral_cash_market_value"][0] == pytest.approx(0.0, abs=1e-9)
        assert result["collateral_receivables_market_value"][0] == pytest.approx(0.0, abs=1e-9)
        assert result["collateral_other_physical_market_value"][0] == pytest.approx(0.0, abs=1e-9)
        assert result["collateral_life_insurance_market_value"][0] == pytest.approx(0.0, abs=1e-9)


# =============================================================================
# 4. Multi-level blend replication (facility-level pledge)
# =============================================================================


class TestMultiLevelBlendReplication:
    """D2: the new carrier must reuse the SAME facility pro-rata blend as its
    adjusted twin -- not a second, divergent allocation path."""

    def test_facility_level_re_pledge_adjusted_value_splits_pro_rata(
        self, direct_config: CalculationConfig
    ) -> None:
        """Regression pin: today's collateral_re_value facility cascade
        (600k/400k EAD split of a 500k pledge -> 300k/200k)."""
        # Arrange
        exposures = [
            _direct_exposure("EXP_A", ead=600_000.0, facility_ref="FAC1"),
            _direct_exposure("EXP_B", ead=400_000.0, facility_ref="FAC1"),
        ]
        collateral = [
            _direct_collateral_row(
                "COLL1", "FAC1", "real_estate", 500_000.0, beneficiary_type="facility"
            )
        ]

        # Act
        result = _run_direct(exposures, collateral, direct_config).sort("exposure_reference")

        # Assert
        exp_a = result.filter(pl.col("exposure_reference") == "EXP_A")
        exp_b = result.filter(pl.col("exposure_reference") == "EXP_B")
        assert exp_a["collateral_re_value"][0] == pytest.approx(300_000.0, rel=1e-6)
        assert exp_b["collateral_re_value"][0] == pytest.approx(200_000.0, rel=1e-6)

    def test_facility_level_re_pledge_market_value_splits_pro_rata_like_adjusted_twin(
        self, direct_config: CalculationConfig
    ) -> None:
        """The NEW carrier must reuse the identical pro-rata weights."""
        # Arrange
        exposures = [
            _direct_exposure("EXP_A", ead=600_000.0, facility_ref="FAC1"),
            _direct_exposure("EXP_B", ead=400_000.0, facility_ref="FAC1"),
        ]
        collateral = [
            _direct_collateral_row(
                "COLL1", "FAC1", "real_estate", 500_000.0, beneficiary_type="facility"
            )
        ]

        # Act
        result = _run_direct(exposures, collateral, direct_config).sort("exposure_reference")

        # Assert
        exp_a = result.filter(pl.col("exposure_reference") == "EXP_A")
        exp_b = result.filter(pl.col("exposure_reference") == "EXP_B")
        assert exp_a["collateral_re_market_value"][0] == pytest.approx(300_000.0, rel=1e-6)
        assert exp_b["collateral_re_market_value"][0] == pytest.approx(200_000.0, rel=1e-6)


# =============================================================================
# 5. Uncollateralized category matches the adjusted twin's null/zero
#    convention
# =============================================================================
#
# NOTE (flagged for the implementer / team lead): the proposal text for this
# assertion reads "nulls stay null ... never a 0.0 fill". Tracing the actual
# code shows the OPPOSITE is already true of every existing adjusted-value
# twin: the direct/counterparty families are explicitly `.fill_null(0.0)`-ed
# (collateral.py:1192-1203) and the facility cascade does the same
# (collateral.py:1591); Polars' own `.sum()` over an empty/all-null filtered
# group also returns 0.0, not null (verified empirically). So no existing
# adjusted twin ever actually surfaces a null for an uncollateralized
# category -- it is always 0.0. The test below therefore pins the concrete,
# code-grounded contract: the new carrier must match that established
# 0.0-never-null convention exactly (no stray null the twin doesn't already
# produce), rather than asserting a null-preserving code path that doesn't
# exist anywhere in this function today.
# =============================================================================


class TestUncollateralizedCategoryMatchesAdjustedTwinConvention:
    def test_receivables_market_value_is_zero_not_null_when_only_re_pledged(
        self, direct_config: CalculationConfig
    ) -> None:
        # Arrange
        exposure = [_direct_exposure("EXP001")]
        collateral = [_direct_collateral_row("COLL1", "EXP001", "real_estate", 500_000.0)]

        # Act
        result = _run_direct(exposure, collateral, direct_config)

        # Assert: regression pin -- the adjusted twin is already 0.0, never null.
        assert result["collateral_receivables_value"][0] == pytest.approx(0.0, abs=1e-9)
        assert result["collateral_receivables_value"].is_null()[0] is False
        # The new carrier must follow the identical convention.
        assert result["collateral_receivables_market_value"][0] == pytest.approx(0.0, abs=1e-9)
        assert result["collateral_receivables_market_value"].is_null()[0] is False


# =============================================================================
# 6. Regression guard: existing collateral_*_value carriers are untouched
# =============================================================================


class TestRegressionGuardAdjustedValueCarrierUnchanged:
    """D2: this work item is purely additive -- every existing
    collateral_*_value carrier keeps its current value."""

    def test_crr_re_adjusted_value_still_500k_zero_haircut(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        # Arrange
        exposures = _pledge_exposure()
        collateral = _pledge_collateral(collateral_type="real_estate", market_value=500_000.0)
        bundle = _make_pledge_bundle(exposures, collateral)

        # Act
        result = _run_crm(processor, crr_config, bundle)

        # Assert
        assert result["collateral_re_value"][0] == pytest.approx(500_000.0, rel=1e-6)

    def test_b31_re_adjusted_value_still_300k_after_40pct_haircut(
        self, processor: CRMProcessor, b31_config: CalculationConfig
    ) -> None:
        # Arrange
        exposures = _pledge_exposure()
        collateral = _pledge_collateral(collateral_type="real_estate", market_value=500_000.0)
        bundle = _make_pledge_bundle(exposures, collateral)

        # Act
        result = _run_crm(processor, b31_config, bundle)

        # Assert
        assert result["collateral_re_value"][0] == pytest.approx(300_000.0, rel=1e-6)

    @pytest.mark.parametrize(
        "category", [c for c, twin in ADJUSTED_TWIN_CARRIER.items() if twin is not None]
    )
    def test_category_adjusted_twins_isolated_no_cross_contamination(
        self, direct_config: CalculationConfig, category: str
    ) -> None:
        """All six categories pledged at once: each existing adjusted twin
        carries only its own category's value (no cross-contamination)."""
        # Arrange
        exposure = [_direct_exposure("EXP001")]
        collateral = [
            _direct_collateral_row(
                f"COLL_{cat}", "EXP001", CATEGORY_TYPE_EXEMPLAR[cat], CATEGORY_MARKET_VALUES[cat]
            )
            for cat in CATEGORY_TYPE_EXEMPLAR
        ]

        # Act
        result = _run_direct(exposure, collateral, direct_config)

        # Assert
        twin = ADJUSTED_TWIN_CARRIER[category]
        # The parametrize filters `twin is not None`; narrow it for the checker.
        assert twin is not None
        assert result[twin][0] == pytest.approx(CATEGORY_MARKET_VALUES[category], rel=1e-6)
