"""Unit tests for the CRM022 Art. 230 minimum-collateralisation diagnostic.

CRR Art. 230(2) Table 5 sets a minimum required collateralisation level C* of 30%
of the exposure for real-estate and other-physical collateral. Below it the
exposure is treated as **fully unsecured** — correct capital, but until CRM022 it
was applied with no diagnostic at all: the preparer saw a populated collateral
column, an LGD at the supervisory unsecured value, and nothing joining the two.
That silence is what turned a supported query into a defect investigation.

Scope of the warning, and what each test pins:
- CRR F-IRB only. PS1/26 Art. 230(1) removes C*/C** entirely, so the diagnostic
  is gated on the same ``firb_min_collateralisation_threshold_applies`` Feature as
  the threshold itself and cannot fire under Basel 3.1.
- It must NOT restate a drop that Art. 199 already caused — an unattested pledge
  is CRM014's business, and double-reporting one cause as two would mislead.
- It must stay silent when the threshold is met, or the diagnostic is noise.

References:
- CRR Art. 230(2) Table 5: C* minimum collateralisation, C** over-collateralisation
- CRR Art. 231: sequential-fill waterfall the zeroed amount would have fed
- CRR Art. 161(1)(a): the 45% senior unsecured LGD the exposure reverts to
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from tests.fixtures.resolved_bundle import make_classified_bundle
from tests.unit.crm._crm_bundles import normalise_collateral, with_ancestor_facilities

from rwa_calc.contracts.bundles import (
    ClassifiedExposuresBundle,
    CRMAdjustedBundle,
    create_empty_counterparty_lookup,
)
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import ERROR_BELOW_MIN_COLLATERALISATION
from rwa_calc.domain.enums import ApproachType, ExposureClass, PermissionMode
from rwa_calc.engine.crm.processor import CRMProcessor

# =============================================================================
# Constants
# =============================================================================

EAD: float = 1_000_000.0
CRR_LGDU_SENIOR: float = 0.45  # CRR Art. 161(1)(a)
BELOW_C_STAR: float = 200_000.0  # C/E = 20% < 30%
ABOVE_C_STAR: float = 400_000.0  # C/E = 40% >= 30%

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


# =============================================================================
# Helpers
# =============================================================================


def _bundle(
    *,
    collateral_type: str = "real_estate",
    market_value: float = BELOW_C_STAR,
    attested: bool = True,
    approach: ApproachType = ApproachType.FIRB,
    lgd: float | None = None,
) -> ClassifiedExposuresBundle:
    """One £1m senior corporate-SME exposure with one non-financial pledge."""
    exposures = pl.DataFrame(
        {
            "exposure_reference": ["EXP1"],
            "counterparty_reference": ["CP1"],
            "parent_facility_reference": [None],
            "exposure_class": [ExposureClass.CORPORATE_SME.value],
            "approach": [approach.value],
            "drawn_amount": [EAD],
            "ead_gross": [EAD],
            "lgd": [lgd],
            "pd": [0.02],
            "maturity_date": [date(2029, 12, 31)],
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
    ).lazy()
    exposures = exposures.with_columns(pl.col("parent_facility_reference").cast(pl.String))
    exposures = with_ancestor_facilities(exposures)

    collateral = normalise_collateral(
        pl.DataFrame(
            {
                "collateral_reference": ["COLL1"],
                "collateral_type": [collateral_type],
                "currency": ["GBP"],
                "market_value": [market_value],
                "value_after_maturity_adj": [market_value],
                "beneficiary_type": ["loan"],
                "beneficiary_reference": ["EXP1"],
                "maturity_date": [date(2035, 12, 31)],
                "issuer_type": [""],
                "issuer_cqs": [1],
                "is_main_index": [False],
                "is_eligible_financial_collateral": [False],
                "is_eligible_irb_collateral": [attested],
                "residual_maturity_years": [10.0],
                "original_maturity_years": [15.0],
                "liquidation_period_days": [10],
            }
        ).lazy()
    )

    return make_classified_bundle(
        all_exposures=exposures,
        equity_exposures=None,
        collateral=collateral,
        guarantees=None,
        provisions=None,
        counterparty_lookup=create_empty_counterparty_lookup(),
        classification_audit=None,
        classification_errors=[],
    )


def _crm022(result: CRMAdjustedBundle) -> list:
    return [e for e in result.crm_errors if e.code == ERROR_BELOW_MIN_COLLATERALISATION]


def _lgd(result: CRMAdjustedBundle) -> float:
    collected = result.exposures.collect()
    return collected.filter(pl.col("exposure_reference") == "EXP1")["lgd_post_crm"][0]


# =============================================================================
# Tests: the diagnostic fires where the threshold silently dropped collateral
# =============================================================================


class TestBelowThresholdIsReported:
    """C/E below C* reverts LGD to unsecured — and now says so."""

    def test_real_estate_below_c_star_emits_crm022(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """A £200k property on a £1m exposure is 20% — below the 30% C*."""
        result = processor.get_crm_unified_bundle(_bundle(), crr_config)

        assert len(_crm022(result)) == 1

    def test_the_warning_names_the_exposure_and_the_shortfall(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """A diagnostic the preparer cannot act on is not a diagnostic."""
        result = processor.get_crm_unified_bundle(_bundle(), crr_config)

        warning = _crm022(result)[0]
        assert "EXP1" in warning.message
        assert "real estate" in warning.message
        assert "30" in warning.message
        assert warning.regulatory_reference is not None
        assert "230" in warning.regulatory_reference

    def test_the_lgd_it_explains_is_the_unsecured_value(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """The warning and the number must describe the same event."""
        result = processor.get_crm_unified_bundle(_bundle(), crr_config)

        assert _lgd(result) == pytest.approx(CRR_LGDU_SENIOR, abs=1e-6)
        assert len(_crm022(result)) == 1

    def test_other_physical_below_c_star_emits_crm022(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """Art. 230 Table 5 gives other physical collateral the same 30% C*."""
        result = processor.get_crm_unified_bundle(
            _bundle(collateral_type="other_physical"), crr_config
        )

        warning = _crm022(result)[0]
        assert "other physical" in warning.message


# =============================================================================
# Tests: the diagnostic stays silent everywhere else
# =============================================================================


class TestSilentWhereItShouldBe:
    """Four ways the warning must not fire, each a distinct false-positive risk."""

    def test_above_c_star_is_not_reported(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """Anti-degenerate: 40% clears the threshold, so there is nothing to explain."""
        result = processor.get_crm_unified_bundle(_bundle(market_value=ABOVE_C_STAR), crr_config)

        assert _crm022(result) == []
        assert _lgd(result) < CRR_LGDU_SENIOR

    def test_basel_3_1_never_reports_it(
        self, processor: CRMProcessor, b31_config: CalculationConfig
    ) -> None:
        """PS1/26 Art. 230(1) removes C* entirely — the same 20% pledge is recognised."""
        result = processor.get_crm_unified_bundle(_bundle(), b31_config)

        assert _crm022(result) == []
        assert _lgd(result) < CRR_LGDU_SENIOR

    def test_unattested_collateral_is_crm014_not_crm022(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """Art. 199 already zeroed it, so C* never bound; one cause, one code."""
        result = processor.get_crm_unified_bundle(_bundle(attested=False), crr_config)

        assert _crm022(result) == []

    def test_airb_own_estimate_is_not_reported(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """C* gates the Foundation formula; an A-IRB row's own LGD never reads it."""
        result = processor.get_crm_unified_bundle(
            _bundle(approach=ApproachType.AIRB, lgd=0.30), crr_config
        )

        assert _crm022(result) == []
