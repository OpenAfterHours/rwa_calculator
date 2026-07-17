"""
P1.239/P1.240 — Art. 200(a)/232(2): third-party deposit, F-IRB deferral.

Under the SA the covered part takes the holder institution's risk weight (pinned
in the acceptance twins). Under F-IRB the substitution analogue is a deferred
follow-up, so a third-party deposit gives NO CRM benefit — it is excluded from
the LGD* collateral input (NOT valued at 0% cash) and raises one CRM017 warning.
A null holder (own-bank deposit) is unaffected.

Pipeline position:
    tests/unit — direct CRMProcessor.get_crm_unified_bundle drive.

References:
    - CRR Art. 200(a)/232(2): third-party deposit as other funded protection.
    - IMPLEMENTATION_PLAN.md: P1.239/P1.240.
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
from rwa_calc.contracts.errors import ERROR_THIRD_PARTY_DEPOSIT_FIRB_DEFERRED
from rwa_calc.domain.enums import ApproachType, ExposureClass, PermissionMode
from rwa_calc.engine.crm.processor import CRMProcessor

CRR_LGDU_SENIOR: float = 0.45


@pytest.fixture
def processor() -> CRMProcessor:
    return CRMProcessor()


@pytest.fixture
def firb_crr_config() -> CalculationConfig:
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31), permission_mode=PermissionMode.IRB
    )


def _create_bundle(held_by: str | None) -> ClassifiedExposuresBundle:
    exposures = pl.DataFrame(
        {
            "exposure_reference": ["EXP1"],
            "counterparty_reference": ["CP1"],
            "parent_facility_reference": [None],
            "exposure_class": [ExposureClass.CORPORATE.value],
            "approach": [ApproachType.FIRB.value],
            "drawn_amount": [10_000_000.0],
            "ead_gross": [10_000_000.0],
            "lgd": [None],
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
                "collateral_reference": ["DEP1"],
                "collateral_type": ["cash"],
                "currency": ["GBP"],
                "market_value": [6_000_000.0],
                "value_after_maturity_adj": [6_000_000.0],
                "beneficiary_type": ["loan"],
                "beneficiary_reference": ["EXP1"],
                "issuer_type": ["institution"],
                "issuer_cqs": [2],
                "is_eligible_financial_collateral": [True],
                "is_eligible_irb_collateral": [True],
                "held_by_counterparty_reference": [held_by],
                "residual_maturity_years": [10.0],
                "liquidation_period_days": [10],
            },
            schema_overrides={"held_by_counterparty_reference": pl.String},
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


def _run(processor: CRMProcessor, config: CalculationConfig, bundle) -> CRMAdjustedBundle:
    return processor.get_crm_unified_bundle(bundle, config)


def _row(result: CRMAdjustedBundle) -> dict:
    return (
        result.exposures.collect().filter(pl.col("exposure_reference") == "EXP1").row(0, named=True)
    )


def _crm017(result: CRMAdjustedBundle) -> list:
    return [e for e in result.crm_errors if e.code == ERROR_THIRD_PARTY_DEPOSIT_FIRB_DEFERRED]


class TestThirdPartyDepositFirbDeferral:
    """F-IRB: a third-party deposit is excluded from LGD* (no benefit) + CRM017."""

    def test_own_bank_deposit_reduces_firb_lgd(
        self, processor: CRMProcessor, firb_crr_config: CalculationConfig
    ) -> None:
        """Control: an own-bank cash deposit (null holder) still reduces F-IRB LGD."""
        result = _run(processor, firb_crr_config, _create_bundle(None))
        row = _row(result)
        assert row["total_collateral_for_lgd"] > 0
        assert row["lgd_post_crm"] < CRR_LGDU_SENIOR
        assert _crm017(result) == []

    def test_third_party_deposit_excluded_from_lgd_star(
        self, processor: CRMProcessor, firb_crr_config: CalculationConfig
    ) -> None:
        """LOAD-BEARING: a third-party deposit contributes nothing to LGD* (excluded)."""
        result = _run(processor, firb_crr_config, _create_bundle("BANK_H"))
        row = _row(result)
        assert row["total_collateral_for_lgd"] == pytest.approx(0.0, abs=1e-6)
        assert row["lgd_post_crm"] == pytest.approx(CRR_LGDU_SENIOR, abs=1e-6)

    def test_third_party_deposit_emits_crm017(
        self, processor: CRMProcessor, firb_crr_config: CalculationConfig
    ) -> None:
        """The F-IRB deferral raises exactly one CRM017 warning."""
        result = _run(processor, firb_crr_config, _create_bundle("BANK_H"))
        warnings = _crm017(result)
        assert len(warnings) == 1
        assert warnings[0].exposure_reference == "EXP1"
        assert warnings[0].regulatory_reference == "CRR Art. 200(a)/232(2)"
