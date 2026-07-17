"""
P1.272 — Art. 230(1) / CRR Art. 228(2): the FCM LGD* denominator uses E(1+HE).

The Foundation Collateral Method LGD* formula grosses the exposure up by its own
volatility haircut HE (PS1/26 Art. 230(1), verified verbatim; CRR Art. 228(2)
equivalently embeds HE in E*):

    E'    = E · (1 + HE)
    ES    = min(C, E')
    EU    = E' − ES = max(0, E' − C)
    LGD*  = (LGDS · ES + LGDU · EU) / E'

HE is non-zero only for SFT rows that lend out a debt security (Art. 223(5)), so
this affects FIRB SFT-style exposures only; every other row carries HE = 0 and is
unchanged. Before the fix the denominator used bare E, understating LGD* (the
unsecured-share denominator was too small).

Pipeline position:
    tests/unit — direct CRMProcessor.get_crm_unified_bundle drive.

References:
    - PS1/26 Art. 230(1): LGD* = LGDU·EU/(E(1+HE)) + LGDS·ES/(E(1+HE)).
    - CRR Art. 228(2) / Art. 223(5): E(1+HE) exposure gross-up.
    - IMPLEMENTATION_PLAN.md: P1.272.
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
from rwa_calc.domain.enums import ApproachType, ExposureClass, PermissionMode
from rwa_calc.engine.crm.processor import CRMProcessor

# E=10m, C=6m cash (LGDS=0), LGDU=0.45 senior. HE = 2% govt-bond haircut × sqrt(5/10).
_HE = 0.02 * (5.0 / 10.0) ** 0.5  # 0.0141421356...
_E = 10_000_000.0
_C = 6_000_000.0
_LGDU = 0.45
# Bare-E (pre-fix, buggy) LGD*:
LGD_STAR_BARE_E = _LGDU * (_E - _C) / _E  # 0.18
# Grossed-up E(1+HE) (Art. 230(1) correct) LGD*:
_E_ADJ = _E * (1.0 + _HE)
LGD_STAR_GROSSED_UP = _LGDU * (_E_ADJ - _C) / _E_ADJ  # 0.183765...

# Basel 3.1: senior corporate LGDU = 0.40 (Art. 161(1)(aa)); same HE.
_LGDU_B31 = 0.40
LGD_STAR_BARE_E_B31 = _LGDU_B31 * (_E - _C) / _E  # 0.16
LGD_STAR_GROSSED_UP_B31 = _LGDU_B31 * (_E_ADJ - _C) / _E_ADJ  # 0.163347...


@pytest.fixture
def processor() -> CRMProcessor:
    return CRMProcessor()


@pytest.fixture
def firb_crr_config() -> CalculationConfig:
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        permission_mode=PermissionMode.IRB,
    )


@pytest.fixture
def firb_b31_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(
        reporting_date=date(2030, 6, 30),
        permission_mode=PermissionMode.IRB,
    )


def _create_bundle(*, is_sft: bool) -> ClassifiedExposuresBundle:
    """FIRB senior corporate exposure lending a CQS1 govt bond (HE source), £6m
    cash collateral. ``is_sft`` toggles the Art. 223(5) exposure-side HE on/off.
    """
    exposures = pl.DataFrame(
        {
            "exposure_reference": ["EXP1"],
            "counterparty_reference": ["CP1"],
            "parent_facility_reference": [None],
            "exposure_class": [ExposureClass.CORPORATE.value],
            "approach": [ApproachType.FIRB.value],
            "drawn_amount": [_E],
            "ead_gross": [_E],
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
            "is_sft": [is_sft],
            "exposure_collateral_type": ["govt_bond"],
            "exposure_security_cqs": [1],
            "exposure_security_residual_maturity_years": [4.0],
        }
    ).lazy()
    exposures = exposures.with_columns(
        pl.col("parent_facility_reference").cast(pl.String),
        pl.col("exposure_security_cqs").cast(pl.Int8),
    )
    exposures = with_ancestor_facilities(exposures)

    collateral = normalise_collateral(
        pl.DataFrame(
            {
                "collateral_reference": ["CASH1"],
                "collateral_type": ["cash"],
                "currency": ["GBP"],
                "market_value": [_C],
                "value_after_maturity_adj": [_C],
                "beneficiary_type": ["loan"],
                "beneficiary_reference": ["EXP1"],
                "issuer_type": [None],
                "issuer_cqs": [None],
                "is_eligible_financial_collateral": [True],
                "is_eligible_irb_collateral": [True],
                "residual_maturity_years": [10.0],
                "liquidation_period_days": [10],
            },
            schema_overrides={"issuer_type": pl.String, "issuer_cqs": pl.Int8},
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


def _lgd_post_crm(result: CRMAdjustedBundle) -> float:
    row = result.exposures.collect().filter(pl.col("exposure_reference") == "EXP1")
    return row["lgd_post_crm"][0]


class TestFcmLgdStarHeGrossUp:
    """Art. 230(1): the LGD* denominator is E(1+HE), not bare E."""

    def test_sft_exposure_grosses_up_denominator(
        self, processor: CRMProcessor, firb_crr_config: CalculationConfig
    ) -> None:
        """LOAD-BEARING: an SFT exposure (HE>0) uses E(1+HE) → LGD* = 0.183765, not 0.18."""
        bundle = _create_bundle(is_sft=True)

        result = _run_crm(processor, firb_crr_config, bundle)

        assert _lgd_post_crm(result) == pytest.approx(LGD_STAR_GROSSED_UP, abs=1e-5)

    def test_sft_exposure_not_bare_e(
        self, processor: CRMProcessor, firb_crr_config: CalculationConfig
    ) -> None:
        """Anti-assert: the SFT LGD* must NOT equal the pre-fix bare-E value 0.18."""
        bundle = _create_bundle(is_sft=True)

        result = _run_crm(processor, firb_crr_config, bundle)

        assert abs(_lgd_post_crm(result) - LGD_STAR_BARE_E) > 1e-4

    def test_non_sft_exposure_unchanged(
        self, processor: CRMProcessor, firb_crr_config: CalculationConfig
    ) -> None:
        """Control: a non-SFT exposure has HE=0, so LGD* = bare-E value 0.18 (unchanged)."""
        bundle = _create_bundle(is_sft=False)

        result = _run_crm(processor, firb_crr_config, bundle)

        assert _lgd_post_crm(result) == pytest.approx(LGD_STAR_BARE_E, abs=1e-6)


class TestFcmLgdStarHeGrossUpB31:
    """Art. 230(1) under Basel 3.1: E(1+HE) gross-up with LGDU=0.40."""

    def test_sft_exposure_grosses_up_denominator(
        self, processor: CRMProcessor, firb_b31_config: CalculationConfig
    ) -> None:
        """LOAD-BEARING: B31 SFT exposure uses E(1+HE) → LGD* = 0.163347, not 0.16."""
        bundle = _create_bundle(is_sft=True)

        result = _run_crm(processor, firb_b31_config, bundle)

        assert _lgd_post_crm(result) == pytest.approx(LGD_STAR_GROSSED_UP_B31, abs=1e-5)

    def test_non_sft_exposure_unchanged(
        self, processor: CRMProcessor, firb_b31_config: CalculationConfig
    ) -> None:
        """Control: a B31 non-SFT exposure has HE=0, so LGD* = bare-E value 0.16."""
        bundle = _create_bundle(is_sft=False)

        result = _run_crm(processor, firb_b31_config, bundle)

        assert _lgd_post_crm(result) == pytest.approx(LGD_STAR_BARE_E_B31, abs=1e-6)


def _run_crm(
    processor: CRMProcessor,
    config: CalculationConfig,
    bundle: ClassifiedExposuresBundle,
) -> CRMAdjustedBundle:
    return processor.get_crm_unified_bundle(bundle, config)
