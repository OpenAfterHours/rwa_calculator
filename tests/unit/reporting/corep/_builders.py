"""Shared COREP test builders (Phase 7 Sn split of test_corep.py).

Cross-family LazyFrame factories consumed by more than one per-template
test file (and by test_p4_20_c0802_internal_grades.py). Single-family
builders are co-located with their template file.
"""

from __future__ import annotations

import polars as pl


def _sa_results() -> pl.LazyFrame:
    """Synthetic SA results with multiple exposure classes and risk weights."""
    return pl.LazyFrame(
        {
            "exposure_reference": [
                "SA_CORP_1",
                "SA_CORP_2",
                "SA_CORP_3",
                "SA_INST_1",
                "SA_RETAIL_1",
                "SA_RETAIL_2",
                "SA_SOVN_1",
            ],
            "approach_applied": [
                "standardised",
                "standardised",
                "standardised",
                "standardised",
                "standardised",
                "standardised",
                "standardised",
            ],
            "exposure_class": [
                "corporate",
                "corporate",
                "corporate_sme",
                "institution",
                "retail_other",
                "retail_other",
                "central_govt_central_bank",
            ],
            "drawn_amount": [1000.0, 2000.0, 500.0, 3000.0, 200.0, 300.0, 5000.0],
            "undrawn_amount": [500.0, 0.0, 100.0, 0.0, 50.0, 0.0, 0.0],
            "ead_final": [1200.0, 2000.0, 550.0, 3000.0, 225.0, 300.0, 5000.0],
            "rwa_final": [1200.0, 2000.0, 467.5, 600.0, 168.75, 225.0, 0.0],
            "risk_weight": [1.00, 1.00, 0.85, 0.20, 0.75, 0.75, 0.00],
            "scra_provision_amount": [10.0, 20.0, 5.0, 0.0, 2.0, 3.0, 0.0],
            "gcra_provision_amount": [5.0, 10.0, 2.5, 15.0, 1.0, 1.5, 0.0],
            "collateral_adjusted_value": [100.0, 0.0, 50.0, 0.0, 0.0, 0.0, 0.0],
            "guaranteed_portion": [0.0, 500.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "sa_cqs": [3, 0, 0, 2, 0, 0, 1],
            "counterparty_reference": [
                "CP_A",
                "CP_B",
                "CP_C",
                "CP_D",
                "CP_E",
                "CP_F",
                "CP_G",
            ],
        }
    )


def _irb_results() -> pl.LazyFrame:
    """Synthetic IRB results with PD, LGD, maturity, and EL data."""
    return pl.LazyFrame(
        {
            "exposure_reference": [
                "IRB_CORP_1",
                "IRB_CORP_2",
                "IRB_SME_1",
                "IRB_INST_1",
                "IRB_RETAIL_1",
            ],
            "approach_applied": [
                "foundation_irb",
                "foundation_irb",
                "foundation_irb",
                "foundation_irb",
                "advanced_irb",
            ],
            "exposure_class": [
                "corporate",
                "corporate",
                "corporate_sme",
                "institution",
                "retail_mortgage",
            ],
            "drawn_amount": [5000.0, 3000.0, 1000.0, 2000.0, 4000.0],
            "undrawn_amount": [1000.0, 0.0, 500.0, 0.0, 0.0],
            "ead_final": [5500.0, 3000.0, 1200.0, 2000.0, 4000.0],
            "rwa_final": [3850.0, 1800.0, 780.0, 600.0, 1200.0],
            "risk_weight": [0.70, 0.60, 0.65, 0.30, 0.30],
            "pd_floored": [0.005, 0.01, 0.02, 0.002, 0.003],
            "lgd_floored": [0.45, 0.45, 0.45, 0.45, 0.15],
            "irb_maturity_m": [2.5, 3.0, 2.5, 1.5, 20.0],
            "expected_loss": [12.375, 13.5, 10.8, 1.8, 1.8],
            "irb_capital_k": [0.056, 0.048, 0.052, 0.024, 0.024],
            "provision_held": [15.0, 10.0, 8.0, 3.0, 2.5],
            "el_shortfall": [0.0, 3.5, 2.8, 0.0, 0.0],
            "el_excess": [2.625, 0.0, 0.0, 1.2, 0.7],
            "scra_provision_amount": [10.0, 5.0, 3.0, 2.0, 1.0],
            "gcra_provision_amount": [5.0, 5.0, 5.0, 1.0, 1.5],
            "counterparty_reference": ["CP_X", "CP_Y", "CP_Z", "CP_W", "CP_V"],
        }
    )


def _sa_results_with_phase2_cols() -> pl.LazyFrame:
    """SA results with Phase 2 columns: bs_type, supporting factors, default_status."""
    return pl.LazyFrame(
        {
            "exposure_reference": [
                "SA_CORP_1",
                "SA_CORP_2",
                "SA_CORP_3",
                "SA_INST_1",
                "SA_RETAIL_1",
                "SA_RETAIL_2",
                "SA_SOVN_1",
                "SA_DEF_1",
            ],
            "approach_applied": ["standardised"] * 8,
            "exposure_class": [
                "corporate",
                "corporate",
                "corporate_sme",
                "institution",
                "retail_other",
                "retail_other",
                "central_govt_central_bank",
                "corporate",
            ],
            "drawn_amount": [1000.0, 2000.0, 500.0, 3000.0, 200.0, 300.0, 5000.0, 800.0],
            "undrawn_amount": [500.0, 0.0, 100.0, 0.0, 50.0, 0.0, 0.0, 0.0],
            "ead_final": [1200.0, 2000.0, 550.0, 3000.0, 225.0, 300.0, 5000.0, 800.0],
            "rwa_final": [1140.0, 1900.0, 467.5, 600.0, 168.75, 225.0, 0.0, 1200.0],
            "risk_weight": [1.00, 1.00, 0.85, 0.20, 0.75, 0.75, 0.00, 1.50],
            "scra_provision_amount": [10.0, 20.0, 5.0, 0.0, 2.0, 3.0, 0.0, 5.0],
            "gcra_provision_amount": [5.0, 10.0, 2.5, 15.0, 1.0, 1.5, 0.0, 3.0],
            "collateral_adjusted_value": [100.0, 0.0, 50.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "guaranteed_portion": [0.0, 500.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "sa_cqs": [3, 0, 0, 2, 0, 0, 1, None],
            "counterparty_reference": [
                "CP_A",
                "CP_B",
                "CP_C",
                "CP_D",
                "CP_E",
                "CP_F",
                "CP_G",
                "CP_H",
            ],
            # Phase 2 columns
            "bs_type": ["ONB", "ONB", "ONB", "ONB", "ONB", "ONB", "ONB", "ONB"],
            "default_status": [False, False, False, False, False, False, False, True],
            "sme_supporting_factor_eligible": [
                False,
                False,
                True,
                False,
                False,
                False,
                False,
                False,
            ],
            "sme_supporting_factor_applied": [
                False,
                False,
                True,
                False,
                False,
                False,
                False,
                False,
            ],
            "infrastructure_factor_applied": [
                True,
                False,
                False,
                False,
                False,
                False,
                False,
                False,
            ],
            "rwa_pre_factor": [
                1200.0,
                2000.0,
                550.0,
                600.0,
                168.75,
                225.0,
                0.0,
                1200.0,
            ],
        }
    )


def _irb_results_with_phase2_cols() -> pl.LazyFrame:
    """IRB results with Phase 2 columns for defaulted/LFSE testing."""
    return pl.LazyFrame(
        {
            "exposure_reference": [
                "IRB_CORP_1",
                "IRB_CORP_2",
                "IRB_SME_1",
                "IRB_INST_1",
                "IRB_RETAIL_1",
                "IRB_DEF_1",
            ],
            "approach_applied": [
                "foundation_irb",
                "foundation_irb",
                "foundation_irb",
                "foundation_irb",
                "advanced_irb",
                "foundation_irb",
            ],
            "exposure_class": [
                "corporate",
                "corporate",
                "corporate_sme",
                "institution",
                "retail_mortgage",
                "corporate",
            ],
            "drawn_amount": [5000.0, 3000.0, 1000.0, 2000.0, 4000.0, 600.0],
            "undrawn_amount": [1000.0, 0.0, 500.0, 0.0, 0.0, 0.0],
            "ead_final": [5500.0, 3000.0, 1200.0, 2000.0, 4000.0, 600.0],
            "rwa_final": [3850.0, 1800.0, 780.0, 600.0, 1200.0, 900.0],
            "risk_weight": [0.70, 0.60, 0.65, 0.30, 0.30, 1.50],
            "pd_floored": [0.005, 0.01, 0.02, 0.002, 0.003, 1.0],
            "lgd_floored": [0.45, 0.45, 0.45, 0.45, 0.15, 0.45],
            "irb_maturity_m": [2.5, 3.0, 2.5, 1.5, 20.0, 2.5],
            "expected_loss": [12.375, 13.5, 10.8, 1.8, 1.8, 270.0],
            "irb_capital_k": [0.056, 0.048, 0.052, 0.024, 0.024, 0.12],
            "provision_held": [15.0, 10.0, 8.0, 3.0, 2.5, 50.0],
            "el_shortfall": [0.0, 3.5, 2.8, 0.0, 0.0, 0.0],
            "el_excess": [2.625, 0.0, 0.0, 1.2, 0.7, 0.0],
            "scra_provision_amount": [10.0, 5.0, 3.0, 2.0, 1.0, 10.0],
            "gcra_provision_amount": [5.0, 5.0, 5.0, 1.0, 1.5, 5.0],
            "counterparty_reference": ["CP_X", "CP_Y", "CP_Z", "CP_W", "CP_V", "CP_DEF"],
            "default_status": [False, False, False, False, False, True],
            "bs_type": ["ONB", "ONB", "ONB", "ONB", "ONB", "ONB"],
            "cp_apply_fi_scalar": [False, False, False, True, False, False],
        }
    )


def _combined_results() -> pl.LazyFrame:
    """Combined SA + IRB results for full template generation."""
    sa = _sa_results().collect()
    irb = _irb_results().collect()
    return pl.concat([sa, irb], how="diagonal_relaxed").lazy()


def _get_total_row(df: pl.DataFrame) -> pl.DataFrame:
    """Get the TOTAL EXPOSURES row (row_ref == '0010') from a per-class DataFrame."""
    return df.filter(pl.col("row_ref") == "0010")


def _sa_results_with_currency_mismatch() -> pl.LazyFrame:
    """SA results with currency mismatch multiplier tracking for COREP row 0380.

    Row order: SA_RET_1 (retail_other, mismatch), SA_RET_2 (retail_other, no mismatch),
               SA_MORT_1 (retail_mortgage, mismatch), SA_CORP_1 (corporate, no mismatch).

    P1.94g: adds risk_weight_pre_currency_mismatch column.
        SA_RET_1:  rw_pre=0.75 (base retail RW before 1.5× multiplier)
        SA_RET_2:  rw_pre=0.75 (no mismatch → pre == post)
        SA_MORT_1: rw_pre=0.75 (base mortgage RW before 1.5× multiplier)
        SA_CORP_1: rw_pre=1.0  (no mismatch → pre == post)
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["SA_RET_1", "SA_RET_2", "SA_MORT_1", "SA_CORP_1"],
            "approach_applied": ["standardised"] * 4,
            "exposure_class": ["retail_other", "retail_other", "retail_mortgage", "corporate"],
            "drawn_amount": [100.0, 200.0, 500.0, 3000.0],
            "undrawn_amount": [0.0, 0.0, 0.0, 0.0],
            "ead_final": [100.0, 200.0, 500.0, 3000.0],
            "rwa_final": [112.5, 150.0, 375.0, 3000.0],
            "risk_weight": [1.125, 0.75, 0.75, 1.0],
            "risk_weight_pre_currency_mismatch": [0.75, 0.75, 0.75, 1.0],
            "sa_cqs": [None, None, None, 3],
            "currency_mismatch_multiplier_applied": [True, False, True, False],
        }
    )
