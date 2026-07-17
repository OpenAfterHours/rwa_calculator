"""
P1.235 — Art. 199(2)/(5)/(6): FIRB Foundation Collateral Method eligibility gate.

Under the F-IRB Foundation Collateral Method (Art. 230 LGD* substitution), non-
financial collateral (real estate, receivables, other physical) may only reduce
LGD where the institution ATTESTS the collateral is IRB-eligible via the
``is_eligible_irb_collateral`` flag (Art. 199(2)/(5)/(6)). Unattested collateral
(flag False/unset) is not recognised: ``effectively_secured`` is zeroed and the
secured LGD reverts to the unsecured supervisory value (45% CRR / 40% B31 for a
senior corporate non-FSE). Art. 199(5) additionally caps receivables at a
1-year original maturity: a receivable whose ``original_maturity_years`` is
populated > 1 year is ineligible even if attested.

Each zeroed row accumulates one CRM014 data-quality WARNING (never raised).

Pipeline position:
    tests/unit — direct CRMProcessor.get_crm_unified_bundle drive.

References:
    - CRR Art. 199(2): eligible IRB collateral must satisfy the recognition
      conditions the institution attests to.
    - CRR Art. 199(5): receivables — 1-year maximum original maturity.
    - CRR Art. 199(6): other physical collateral eligibility conditions.
    - CRR Art. 161(1)(a): LGDU senior unsecured corporate = 45%.
    - PS1/26 Art. 161(1)(aa): LGDU senior unsecured non-FSE corporate = 40%.
    - IMPLEMENTATION_PLAN.md: P1.235 entry.
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
from rwa_calc.contracts.errors import ERROR_INELIGIBLE_IRB_COLLATERAL
from rwa_calc.domain.enums import ApproachType, ExposureClass, PermissionMode
from rwa_calc.engine.crm.processor import CRMProcessor

# =============================================================================
# Constants
# =============================================================================

CRR_LGDU_SENIOR: float = 0.45  # CRR Art. 161(1)(a) senior unsecured corporate
B31_LGDU_SENIOR: float = 0.40  # PS1/26 Art. 161(1)(aa) senior unsecured non-FSE
CRR_SECURED_LGD_FULL_RE: float = 0.378571  # P1.190 crr_full_re hand-calc (attested)

# =============================================================================
# Fixtures
# =============================================================================


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


# =============================================================================
# Helpers
# =============================================================================


def _create_bundle(
    collateral_type: str,
    *,
    is_eligible_irb_collateral: bool,
    original_maturity_years: float,
) -> ClassifiedExposuresBundle:
    """Build a single-loan F-IRB bundle with one non-financial collateral row.

    £10m senior corporate exposure, £10m collateral of ``collateral_type``.
    ``is_eligible_irb_collateral`` and ``original_maturity_years`` drive the
    Art. 199(2)/(5)/(6) gate under test.
    """
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
                "collateral_reference": ["COLL1"],
                "collateral_type": [collateral_type],
                "currency": ["GBP"],
                "market_value": [10_000_000.0],
                "value_after_maturity_adj": [10_000_000.0],
                "beneficiary_type": ["loan"],
                "beneficiary_reference": ["EXP1"],
                "maturity_date": [date(2035, 12, 31)],
                "issuer_type": [""],
                "issuer_cqs": [1],
                "is_main_index": [False],
                "is_eligible_financial_collateral": [False],
                "is_eligible_irb_collateral": [is_eligible_irb_collateral],
                "residual_maturity_years": [10.0],
                "original_maturity_years": [original_maturity_years],
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


def _run_crm(
    processor: CRMProcessor,
    config: CalculationConfig,
    bundle: ClassifiedExposuresBundle,
) -> CRMAdjustedBundle:
    """Run CRM processing and return the unified bundle (errors + exposures)."""
    return processor.get_crm_unified_bundle(bundle, config)


def _lgd_post_crm(result: CRMAdjustedBundle) -> float:
    collected = result.exposures.collect()
    row = collected.filter(pl.col("exposure_reference") == "EXP1")
    return row["lgd_post_crm"][0]


def _crm014_errors(result: CRMAdjustedBundle) -> list:
    return [e for e in result.crm_errors if e.code == ERROR_INELIGIBLE_IRB_COLLATERAL]


# =============================================================================
# Tests: attestation gate (Art. 199(2))
# =============================================================================


class TestAttestationGate:
    """Art. 199(2): only attested non-financial collateral reduces LGD."""

    def test_attested_re_collateral_reduces_lgd(
        self, processor: CRMProcessor, firb_crr_config: CalculationConfig
    ) -> None:
        """CRR: attested RE collateral is recognised — LGD falls below LGDU.

        Control for the gate: with is_eligible_irb_collateral=True the £10m RE
        collateral secures the exposure and LGD* = 0.378571 (P1.190 crr_full_re
        hand-calc: OC=1.4×, ES=7.143m, 0.45×0.286 + 0.35×0.714).
        """
        bundle = _create_bundle(
            "real_estate", is_eligible_irb_collateral=True, original_maturity_years=10.0
        )

        result = _run_crm(processor, firb_crr_config, bundle)

        assert _lgd_post_crm(result) == pytest.approx(CRR_SECURED_LGD_FULL_RE, abs=1e-3)

    def test_attested_re_collateral_emits_no_warning(
        self, processor: CRMProcessor, firb_crr_config: CalculationConfig
    ) -> None:
        """CRR: attested RE collateral emits no CRM014 warning."""
        bundle = _create_bundle(
            "real_estate", is_eligible_irb_collateral=True, original_maturity_years=10.0
        )

        result = _run_crm(processor, firb_crr_config, bundle)

        assert _crm014_errors(result) == []

    def test_unattested_re_collateral_reverts_to_lgdu_crr(
        self, processor: CRMProcessor, firb_crr_config: CalculationConfig
    ) -> None:
        """CRR LOAD-BEARING: unattested RE collateral reverts LGD to 45%.

        With is_eligible_irb_collateral=False the Art. 199(2) gate zeroes
        effectively_secured; the secured LGD reverts to LGDU = 45%.
        """
        bundle = _create_bundle(
            "real_estate", is_eligible_irb_collateral=False, original_maturity_years=10.0
        )

        result = _run_crm(processor, firb_crr_config, bundle)

        assert _lgd_post_crm(result) == pytest.approx(CRR_LGDU_SENIOR, abs=1e-6)

    def test_unattested_re_collateral_reverts_to_lgdu_b31(
        self, processor: CRMProcessor, firb_b31_config: CalculationConfig
    ) -> None:
        """B31 LOAD-BEARING: unattested RE collateral reverts LGD to 40%.

        PS1/26 Art. 161(1)(aa): senior unsecured non-FSE corporate LGDU = 40%.
        """
        bundle = _create_bundle(
            "real_estate", is_eligible_irb_collateral=False, original_maturity_years=10.0
        )

        result = _run_crm(processor, firb_b31_config, bundle)

        assert _lgd_post_crm(result) == pytest.approx(B31_LGDU_SENIOR, abs=1e-6)

    def test_unattested_re_collateral_emits_crm014(
        self, processor: CRMProcessor, firb_crr_config: CalculationConfig
    ) -> None:
        """Unattested collateral accumulates exactly one CRM014 warning (never raised)."""
        bundle = _create_bundle(
            "real_estate", is_eligible_irb_collateral=False, original_maturity_years=10.0
        )

        result = _run_crm(processor, firb_crr_config, bundle)

        warnings = _crm014_errors(result)
        assert len(warnings) == 1
        assert warnings[0].exposure_reference == "EXP1"
        assert warnings[0].regulatory_reference == "CRR Art. 199(2)/(5)/(6)"
        assert "not attested" in warnings[0].message


# =============================================================================
# Tests: receivables 1-year cap (Art. 199(5))
# =============================================================================


class TestReceivablesMaturityCap:
    """Art. 199(5): attested receivables are still ineligible above 1-year maturity."""

    def test_short_receivables_recognised(
        self, processor: CRMProcessor, firb_crr_config: CalculationConfig
    ) -> None:
        """Attested receivables with 0.5y original maturity are recognised (≤ 1 year)."""
        bundle = _create_bundle(
            "receivables", is_eligible_irb_collateral=True, original_maturity_years=0.5
        )

        result = _run_crm(processor, firb_crr_config, bundle)

        assert _lgd_post_crm(result) < CRR_LGDU_SENIOR
        assert _crm014_errors(result) == []

    def test_long_receivables_ineligible_despite_attestation(
        self, processor: CRMProcessor, firb_crr_config: CalculationConfig
    ) -> None:
        """LOAD-BEARING: attested receivables > 1y original maturity are ineligible.

        Art. 199(5): explicit data (original_maturity_years=2.0) contradicting the
        attestation wins conservatively — effectively_secured is zeroed and LGD
        reverts to LGDU = 45%.
        """
        bundle = _create_bundle(
            "receivables", is_eligible_irb_collateral=True, original_maturity_years=2.0
        )

        result = _run_crm(processor, firb_crr_config, bundle)

        assert _lgd_post_crm(result) == pytest.approx(CRR_LGDU_SENIOR, abs=1e-6)

    def test_long_receivables_emits_art_199_5_warning(
        self, processor: CRMProcessor, firb_crr_config: CalculationConfig
    ) -> None:
        """The receivables-maturity warning distinguishes Art. 199(5) from non-attestation."""
        bundle = _create_bundle(
            "receivables", is_eligible_irb_collateral=True, original_maturity_years=2.0
        )

        result = _run_crm(processor, firb_crr_config, bundle)

        warnings = _crm014_errors(result)
        assert len(warnings) == 1
        assert "exceeds 1 year" in warnings[0].message
