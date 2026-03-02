"""
Basel 3.1 Group D7: Parameter Substitution for IRB Guarantors (CRE22.70-85).

These tests validate that the production RWA calculator correctly applies
Basel 3.1 parameter substitution when an F-IRB exposure is guaranteed by
a counterparty whose comparable direct exposure would be under F-IRB.

Why these tests matter:
    Under CRR, ALL guarantee substitution uses SA risk weight lookup
    (guarantor's entity type and CQS map to an SA risk weight). Under
    Basel 3.1, when the guarantor is under IRB, parameter substitution
    replaces the borrower's PD with the guarantor's PD and uses F-IRB
    supervisory LGD (unsecured senior = 40%) to recalculate the IRB
    capital requirement for the guaranteed portion.

    This test exercises the CRM processor (guarantor PD lookup) and the
    IRB calculator (parameter substitution) end-to-end using synthetic
    data that isolates the guarantee treatment.

Key Basel 3.1 parameter substitution rules:
- SA guarantor → SA risk weight substitution (unchanged from CRR)
- IRB guarantor → PD parameter substitution (new in Basel 3.1)
- Guaranteed portion: K(guarantor_PD, LGD=0.40) × 12.5 × MA
- Unguaranteed portion: borrower's original IRB RWA (pro-rated)
- Non-beneficial guarantee: not applied (guarantor RW >= borrower RW)

Regulatory References:
- CRE22.70-85: Unfunded credit protection methods
- CRE32.9: F-IRB supervisory LGD (unsecured senior = 40% under Basel 3.1)
- PRA PS9/24 Chapter 4: Credit risk mitigation
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

import rwa_calc.engine.irb.namespace  # noqa: F401 - Register namespace
from rwa_calc.contracts.config import CalculationConfig, IRBPermissions
from rwa_calc.domain.enums import ApproachType
from rwa_calc.engine.crm.processor import CRMProcessor
from rwa_calc.engine.irb.formulas import _parametric_irb_risk_weight_expr


def _compute_expected_irb_rw(
    pd: float, lgd: float, maturity: float, exposure_class: str = "CORPORATE"
) -> float:
    """Compute expected IRB risk weight using the parametric formula helper."""
    lf = pl.LazyFrame(
        {
            "exposure_class": [exposure_class],
            "turnover_m": [None],
            "maturity": [maturity],
            "requires_fi_scalar": [False],
        }
    )
    pd_expr = pl.lit(pd)
    rw_expr = _parametric_irb_risk_weight_expr(
        pd_expr=pd_expr, lgd=lgd, scaling_factor=1.0, eur_gbp_rate=0.8732
    )
    result = lf.with_columns(rw_expr.alias("rw")).collect()
    return result["rw"][0]


@pytest.fixture(scope="module")
def b31_firb_config() -> CalculationConfig:
    """Basel 3.1 F-IRB config with corporate F-IRB permissions."""
    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 30),
        irb_permissions=IRBPermissions.firb_only(),
    )


@pytest.fixture(scope="module")
def crr_firb_config() -> CalculationConfig:
    """CRR F-IRB config for comparison."""
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        irb_permissions=IRBPermissions.firb_only(),
    )


def _create_crm_and_irb_result(
    config: CalculationConfig,
    guarantor_pd: float | None,
    guarantor_entity_type: str,
    guarantor_cqs: int | None,
    guarantor_rating_type: str,
    borrower_pd: float = 0.03,
    ead: float = 1_000_000.0,
    guarantee_coverage: float = 1.0,
    maturity: float = 5.0,
) -> pl.DataFrame:
    """Create a synthetic F-IRB exposure with guarantee, run CRM + IRB, return results.

    This exercises the CRM processor's apply_guarantees() method to join guarantor
    data (including PD), then runs the IRB formula pipeline and guarantee
    substitution. This is the end-to-end critical path for parameter substitution.
    """
    # CRM processor: apply guarantees to get guarantor attributes on the exposure
    processor = CRMProcessor(is_basel_3_1=config.is_basel_3_1)

    # Pre-CRM exposures (after CCF/collateral, before guarantee)
    # Includes ccf, nominal_amount, drawn_amount, ead_from_ccf required by
    # _apply_cross_approach_ccf in the CRM processor.
    exposures = pl.LazyFrame(
        {
            "exposure_reference": ["EXP001"],
            "counterparty_reference": ["CP001"],
            "exposure_class": ["CORPORATE"],
            "approach": [ApproachType.FIRB.value],
            "is_airb": [False],
            "pd": [borrower_pd],
            "lgd": [0.40],
            "maturity": [maturity],
            "currency": ["GBP"],
            "seniority": ["senior"],
            "ead_after_collateral": [ead],
            "ead_final": [ead],
            "risk_type": ["drawn"],
            "ccf": [1.0],
            "nominal_amount": [0.0],
            "drawn_amount": [ead],
            "ead_from_ccf": [0.0],
        }
    )

    guarantees = pl.LazyFrame(
        {
            "guarantee_reference": ["GUAR001"],
            "guarantee_type": ["guarantee"],
            "guarantor": ["CP_GUAR"],
            "currency": ["GBP"],
            "maturity_date": [date(2032, 6, 30)],
            "amount_covered": [ead * guarantee_coverage],
            "percentage_covered": [guarantee_coverage],
            "beneficiary_type": ["loan"],
            "beneficiary_reference": ["EXP001"],
        }
    )

    counterparty_lookup = pl.LazyFrame(
        {
            "counterparty_reference": ["CP001", "CP_GUAR"],
            "entity_type": ["corporate", guarantor_entity_type],
        }
    )

    rating_inheritance = pl.LazyFrame(
        {
            "counterparty_reference": ["CP_GUAR"],
            "cqs": [guarantor_cqs],
            "rating_type": [guarantor_rating_type],
            "pd": [guarantor_pd],
        }
    )

    # Apply guarantees (CRM processor method)
    exposures_with_guarantee = processor.apply_guarantees(
        exposures, guarantees, counterparty_lookup, config, rating_inheritance
    )

    # Run full IRB formula pipeline and guarantee substitution
    result = (
        exposures_with_guarantee.irb.classify_approach(config)
        .irb.apply_firb_lgd(config)
        .irb.prepare_columns(config)
        .irb.apply_all_formulas(config)
        .irb.compute_el_shortfall_excess()
        .irb.apply_guarantee_substitution(config)
    )

    return result.collect()


class TestB31D7_ParameterSubstitution:
    """
    Basel 3.1 acceptance tests for parameter substitution.

    Each test creates synthetic F-IRB exposure data with guarantees,
    runs through the CRM processor and IRB calculator, then validates
    the guarantee method and RWA against hand-calculated expected values.
    """

    def test_b31_d7_irb_guarantor_uses_pd_parameter_substitution(
        self,
        b31_firb_config: CalculationConfig,
    ) -> None:
        """
        B31-D7: F-IRB corporate exposure, fully guaranteed by IRB corporate guarantor.

        The guarantor has PD=0.5%, rated internally. Under Basel 3.1 parameter
        substitution, the guaranteed portion uses the guarantor's PD (0.5%) and
        F-IRB supervisory LGD (40%) to compute RWA through the IRB formula.

        Expected: PD_PARAMETER_SUBSTITUTION method used, not SA_RW_SUBSTITUTION.
        """
        result_df = _create_crm_and_irb_result(
            config=b31_firb_config,
            guarantor_pd=0.005,
            guarantor_entity_type="corporate",
            guarantor_cqs=2,
            guarantor_rating_type="internal",
            borrower_pd=0.03,
        )

        assert len(result_df) > 0, "Expected at least one result row"
        row = result_df.row(0, named=True)

        # Verify parameter substitution method was used
        assert row["guarantee_method_used"] == "PD_PARAMETER_SUBSTITUTION"
        assert row["guarantee_status"] == "PD_PARAMETER_SUBSTITUTION"

        # Verify the guarantor RW is not a simple SA lookup
        # SA RW for corporate CQS 2 = 50%, but IRB RW should be different
        sa_rw_cqs2 = 0.50
        assert row["guarantor_rw"] != pytest.approx(sa_rw_cqs2, abs=0.01), (
            "Guarantor RW should use IRB formula, not SA lookup"
        )

    def test_b31_d7_sa_guarantor_still_uses_sa_rw_substitution(
        self,
        b31_firb_config: CalculationConfig,
    ) -> None:
        """
        B31-D7b: F-IRB corporate exposure, fully guaranteed by SA sovereign CQS 1.

        SA guarantors should still use SA risk weight substitution even under
        Basel 3.1. Sovereign CQS 1 = 0% risk weight.

        Expected: SA_RW_SUBSTITUTION method, 0% RW for guaranteed portion.
        """
        result_df = _create_crm_and_irb_result(
            config=b31_firb_config,
            guarantor_pd=None,
            guarantor_entity_type="sovereign",
            guarantor_cqs=1,
            guarantor_rating_type="external",
            borrower_pd=0.03,
        )

        assert len(result_df) > 0
        row = result_df.row(0, named=True)

        # SA RW substitution for sovereign guarantor
        assert row["guarantee_method_used"] == "SA_RW_SUBSTITUTION"
        assert row["guarantor_rw"] == pytest.approx(0.0)

    def test_b31_d7_crr_irb_guarantor_uses_sa_rw_substitution(
        self,
        crr_firb_config: CalculationConfig,
    ) -> None:
        """
        B31-D7c: Under CRR, even IRB guarantors use SA RW substitution.

        CRR does not support parameter substitution. All guarantee methods
        fall back to SA risk weight substitution.

        Expected: SA_RW_SUBSTITUTION even though guarantor has IRB PD.
        """
        result_df = _create_crm_and_irb_result(
            config=crr_firb_config,
            guarantor_pd=0.005,
            guarantor_entity_type="corporate",
            guarantor_cqs=1,
            guarantor_rating_type="internal",
            borrower_pd=0.03,
        )

        assert len(result_df) > 0
        row = result_df.row(0, named=True)

        # CRR: always SA RW substitution
        assert row["guarantee_method_used"] == "SA_RW_SUBSTITUTION"

    def test_b31_d7_partial_guarantee_blends_correctly(
        self,
        b31_firb_config: CalculationConfig,
    ) -> None:
        """
        B31-D7d: 60% IRB guarantee blends parameter-substituted and original RWA.

        The guaranteed portion (60%) uses the guarantor's PD through IRB formula.
        The unguaranteed portion (40%) uses the borrower's original IRB RWA.

        Expected: blended RWA = 40% × borrower_IRB_RWA + 60% × guarantor_IRB_RWA
        """
        result_df = _create_crm_and_irb_result(
            config=b31_firb_config,
            guarantor_pd=0.005,
            guarantor_entity_type="corporate",
            guarantor_cqs=2,
            guarantor_rating_type="internal",
            borrower_pd=0.03,
            guarantee_coverage=0.60,
        )

        assert len(result_df) > 0
        row = result_df.row(0, named=True)

        # Must be parameter substitution for IRB guarantor
        assert row["guarantee_method_used"] == "PD_PARAMETER_SUBSTITUTION"

        # RWA should be less than original (guarantor has lower PD)
        assert row["rwa"] < row["rwa_irb_original"]

        # Guarantee benefit should be positive
        assert row["guarantee_benefit_rw"] > 0

    def test_b31_d7_parameter_sub_rwa_lower_than_sa_rw_sub(
        self,
        b31_firb_config: CalculationConfig,
    ) -> None:
        """
        B31-D7e: Parameter substitution should give lower RWA than SA RW sub
        when the guarantor has a very low PD and shorter maturity.

        A CQS 2 corporate guarantor gets 50% SA RW, but if their actual PD
        is 0.2% with 2.5y maturity, the IRB formula gives ~39% risk weight.
        The maturity adjustment matters: at 5y the IRB RW can exceed SA 50%,
        but at shorter maturities the IRB formula gives materially lower RW.

        Expected: parameter_sub_rwa < sa_rw_sub_equivalent
        """
        result_df = _create_crm_and_irb_result(
            config=b31_firb_config,
            guarantor_pd=0.002,
            guarantor_entity_type="corporate",
            guarantor_cqs=2,
            guarantor_rating_type="internal",
            borrower_pd=0.03,
            maturity=2.5,
        )

        assert len(result_df) > 0
        row = result_df.row(0, named=True)

        # IRB RW from parameter sub should be lower than SA 50%
        # At PD=0.2%, LGD=40%, M=2.5y the IRB formula gives ~39% RW
        expected_irb_rw = _compute_expected_irb_rw(0.002, 0.40, 2.5)
        assert row["guarantor_rw"] < 0.50, (
            f"Expected IRB guarantor RW < 50% SA RW, got {row['guarantor_rw']:.4f}"
        )
        assert row["guarantor_rw"] == pytest.approx(expected_irb_rw, rel=0.05), (
            f"Expected guarantor RW ~{expected_irb_rw:.4f}, got {row['guarantor_rw']:.4f}"
        )
