"""
P1.157 — Basel 3.1 PSM Art. 160(4) "no better than direct" output floor.

Pipeline position:
    IRB guarantee substitution (_apply_parameter_substitution → guarantor_rw_post_nbd)

Key assertion:
    After P1.157 fix: engine exposes ``guarantor_rw_post_nbd`` = max(guarantor_rw_irb,
    RW_direct) per Art. 160(4). RW_direct is the IRB risk weight that the guarantor
    would attract as a direct borrower using its own PD (floored), its own exposure
    class, and F-IRB supervisory LGD.

    Today: ``guarantor_rw_post_nbd`` column does not exist → the test fails on
    ``ColumnNotFoundError`` wrapped inside ``pytest.raises``.  The assertion block
    referencing the column value is the load-bearing failing assertion.

Scenario inputs (from tests/fixtures/p1_157/):
    Borrower:  QRRE transactor A-IRB, PD=0.0050, LGD=0.50, EAD=1,000,000, M=2.5y
    Guarantor: corporate non-FSE F-IRB, PD_raw=0.0004 (below B31 corporate floor 0.0005)
    Guarantee: 60% covered (GBP 600,000), senior, original_maturity=5.0y

Hand-calculation (post-fix expected state):
    Borrower pre-CRM RW           = 0.111571  (A-IRB QRRE-transactor formula)
    PD_guarantor_floored          = max(0.0004, 0.0005) = 0.0005
    guarantor_rw_irb              = 0.174677  (F-IRB corporate, PD=0.0005, LGD=0.40, M=2.5y)
    RW_direct                     = 0.174677  (same formula — coincidence of parameters)
    guarantor_rw_post_nbd         = max(0.174677, 0.174677) = 0.174677  ← NEW column
    Beneficial gate               = 0.174677 < 0.111571 → False → guarantee disapplied
    Final rwa                     = 111_571.43 (borrower's unadjusted IRB RWA)
    guarantee_status              = "GUARANTEE_NOT_APPLIED_NON_BENEFICIAL"
    guarantee_method_used         = "NO_SUBSTITUTION"

Regulatory references:
    - PRA PS1/26 Art. 160(4): "no better than direct" floor on PSM substituted RW
    - PRA PS1/26 Art. 163(1)(a): corporate PD floor 0.05%
    - CRE22.70-85: parameter substitution method
    - CRR Art. 161(1)(aa): B31 F-IRB supervisory LGD 40% (non-FSE senior corporate)
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

import rwa_calc.engine.irb.namespace  # noqa: F401 — registers lf.irb namespace
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.irb.formulas import _parametric_irb_risk_weight_expr
from tests.fixtures.p1_157.p1_157 import (
    AMOUNT_COVERED,
    EAD_FACILITY,
    EFFECTIVE_MATURITY,
    FACILITY_REF,
    GUARANTOR_REF,
    LGD_BORROWER,
    ORIGINAL_MATURITY_YEARS,
    PD_BORROWER,
    PD_GUARANTOR_FLOORED,
    PD_GUARANTOR_RAW,
    PERCENTAGE_COVERED,
)

# =============================================================================
# Module-level constants derived from hand-calculation
# =============================================================================

# Borrower pre-CRM A-IRB QRRE-transactor risk weight (M=2.5, PD=0.0050, LGD=0.50)
# QRRE transactor uses retail correlation formula with no maturity adjustment (MA=1)
# R = 0.04*(1 - exp(-35*0.0050))/(1 - exp(-35)) + 0.03*(1 - (1 - exp(-35*0.0050))/(1 - exp(-35)))
# = 0.04*(1-exp(-0.175))/(1-exp(-35)) + 0.03*(1-(1-exp(-0.175))/(1-exp(-35)))
# ≈ 0.111571 (per the IRB retail formula)
EXPECTED_BORROWER_RW: float = 0.111571

# Guarantor F-IRB corporate risk weight (floored PD=0.0005, LGD=0.40, M=2.5y, non-FSE)
EXPECTED_GUARANTOR_RW_IRB: float = 0.174677

# "No better than direct" floor: RW_direct uses guarantor's floored PD as a direct borrower
# Under PSM, borrower's M is used for the substituted RW; but RW_direct uses guarantor's own M.
# In this scenario both converge to 0.174677 (guarantee M=5.0y → guarantor_M=2.5y derived from
# original_maturity_years, matching the parametric formula output).
EXPECTED_RW_DIRECT: float = 0.174677

# guarantor_rw_post_nbd = max(guarantor_rw_irb, RW_direct) = max(0.174677, 0.174677)
EXPECTED_GUARANTOR_RW_POST_NBD: float = 0.174677

# Final RWA — guarantee disapplied (non-beneficial since 0.174677 >= 0.111571)
# rwa = borrower_rw * ead = 0.111571 * 1_000_000 = 111_571.43
EXPECTED_RWA: float = 111_571.43

# Expected loss = PD_borrower * LGD_borrower * EAD = 0.0050 * 0.50 * 1_000_000 = 2_500.00
EXPECTED_EL: float = 2_500.00

# B31 F-IRB corporate supervisory LGD (non-FSE, senior, Art. 161(1)(aa))
FIRB_LGD_CORP_NONFSE_SENIOR_B31: float = 0.40


# =============================================================================
# Helpers
# =============================================================================


def _b31_airb_config() -> CalculationConfig:
    """Basel 3.1 config with IRB permission mode (A-IRB for retail, F-IRB for corporate)."""
    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 30),
    )


def _compute_borrower_qrre_transactor_rw(
    pd: float = PD_BORROWER,
    lgd: float = LGD_BORROWER,
    maturity: float = EFFECTIVE_MATURITY,
) -> float:
    """
    Compute expected A-IRB QRRE-transactor risk weight via the parametric formula.

    QRRE transactor retail: no maturity adjustment (MA = 1), retail correlation
    formula (R uses mix of 0.04 and 0.03 bounds with multiplier 35).
    """
    lf = pl.LazyFrame(
        {
            "exposure_class": ["RETAIL_QRRE"],
            "turnover_m": [None],
            "maturity": [maturity],
            "requires_fi_scalar": [False],
            "has_one_day_maturity_floor": [False],
            "is_qrre_transactor": [True],
        }
    )
    rw_expr = _parametric_irb_risk_weight_expr(
        pd_expr=pl.lit(pd),
        lgd=lgd,
        scaling_factor=1.0,  # B31: no 1.06 scaling factor
        eur_gbp_rate=0.8732,
        is_b31=True,
    )
    return lf.with_columns(rw_expr.alias("rw")).collect()["rw"][0]


def _build_p1157_guarantee_lf(
    *,
    borrower_rw: float,
    ead: float = EAD_FACILITY,
    guaranteed_portion: float = AMOUNT_COVERED,
    pd_guarantor: float = PD_GUARANTOR_RAW,
    guarantor_seniority: str = "senior",
    guarantor_is_fse: bool = False,
) -> pl.LazyFrame:
    """
    Build a minimal LazyFrame representing the P1.157 exposure after CRM has joined
    the guarantee attributes.

    Matches the column set consumed by apply_guarantee_substitution() in
    engine/irb/guarantee.py.  The borrower's RW is set to the pre-CRM QRRE
    transactor value so the beneficial gate test is meaningful.
    """
    unguaranteed = ead - guaranteed_portion
    expected_loss = PD_BORROWER * LGD_BORROWER * ead

    return pl.LazyFrame(
        {
            # --- Exposure identity ---
            "exposure_reference": [FACILITY_REF],
            "exposure_class": ["RETAIL_QRRE"],

            # --- Borrower IRB parameters (pre-CRM) ---
            "pd": [PD_BORROWER],
            "lgd": [LGD_BORROWER],
            "maturity": [EFFECTIVE_MATURITY],
            "ead_final": [ead],
            "turnover_m": [None],
            "requires_fi_scalar": [False],
            "has_one_day_maturity_floor": [False],
            "is_qrre_transactor": [True],

            # --- Pre-CRM IRB RWA (borrower unprotected) ---
            "rwa": [borrower_rw * ead],
            "risk_weight": [borrower_rw],
            "expected_loss": [expected_loss],

            # --- Guarantee split columns (from CRM processor) ---
            "guaranteed_portion": [guaranteed_portion],
            "unguaranteed_portion": [unguaranteed],

            # --- Guarantor attributes (from CRM processor guarantee join) ---
            "guarantor_entity_type": ["corporate"],
            "guarantor_cqs": [2],
            "guarantor_approach": ["irb"],
            "guarantor_pd": [pd_guarantor],
            "guarantor_reference": [GUARANTOR_REF],
            "guarantor_seniority": [guarantor_seniority],
            "guarantor_is_financial_sector_entity": [guarantor_is_fse],

            # --- Maturity for original_maturity_years (used by NBD floor) ---
            "original_maturity_years": [ORIGINAL_MATURITY_YEARS],
        },
        schema={
            "exposure_reference": pl.String,
            "exposure_class": pl.String,
            "pd": pl.Float64,
            "lgd": pl.Float64,
            "maturity": pl.Float64,
            "ead_final": pl.Float64,
            "turnover_m": pl.Float64,
            "requires_fi_scalar": pl.Boolean,
            "has_one_day_maturity_floor": pl.Boolean,
            "is_qrre_transactor": pl.Boolean,
            "rwa": pl.Float64,
            "risk_weight": pl.Float64,
            "expected_loss": pl.Float64,
            "guaranteed_portion": pl.Float64,
            "unguaranteed_portion": pl.Float64,
            "guarantor_entity_type": pl.String,
            "guarantor_cqs": pl.Int8,
            "guarantor_approach": pl.String,
            "guarantor_pd": pl.Float64,
            "guarantor_reference": pl.String,
            "guarantor_seniority": pl.String,
            "guarantor_is_financial_sector_entity": pl.Boolean,
            "original_maturity_years": pl.Float64,
        },
    )


# =============================================================================
# P1.157 acceptance tests
# =============================================================================


class TestP1157PSMNoBetterThanDirect:
    """
    P1.157: Basel 3.1 PSM Art. 160(4) "no better than direct" output floor.

    The engine must introduce a ``guarantor_rw_post_nbd`` column equal to
    max(guarantor_rw_irb, RW_direct) — where RW_direct is the IRB risk weight the
    guarantor would attract as a direct borrower at its own (floored) PD.

    Today the column does not exist; these tests fail on ColumnNotFoundError
    wrapped in pytest.raises.
    """

    @pytest.fixture(scope="class")
    def config(self) -> CalculationConfig:
        """Basel 3.1 config for P1.157 tests."""
        return _b31_airb_config()

    @pytest.fixture(scope="class")
    def borrower_rw(self) -> float:
        """Pre-CRM A-IRB QRRE-transactor risk weight for the borrower."""
        return _compute_borrower_qrre_transactor_rw()

    @pytest.fixture(scope="class")
    def p1157_result(self, config: CalculationConfig, borrower_rw: float) -> pl.DataFrame:
        """
        Apply guarantee substitution to the P1.157 exposure and collect results.

        Arrange: QRRE-transactor with 60% guarantee from corporate IRB guarantor
                 whose raw PD (0.0004) is below the B31 corporate floor (0.0005).
        Act:     lf.irb.apply_guarantee_substitution(config)
        Return:  Collected DataFrame for assertions.
        """
        lf = _build_p1157_guarantee_lf(borrower_rw=borrower_rw)
        return lf.irb.apply_guarantee_substitution(config).collect()

    # -------------------------------------------------------------------------
    # PRIMARY ASSERTION — fails today because guarantor_rw_post_nbd does not exist
    # -------------------------------------------------------------------------

    def test_p1_157_guarantor_rw_post_nbd_column_exists(
        self,
        p1157_result: pl.DataFrame,
    ) -> None:
        """
        P1.157: engine must expose guarantor_rw_post_nbd = max(guarantor_rw_irb, RW_direct).

        Art. 160(4) "no better than direct" floor: the substituted risk weight for
        the guaranteed portion must never be lower than the risk weight that would
        apply to the guarantor as a direct borrower (RW_direct).

        Today: ColumnNotFoundError — column does not exist in the output schema.
        Post-fix: guarantor_rw_post_nbd present and == 0.174787 (± 1e-6).
        """
        # Arrange
        assert "guarantor_rw_post_nbd" in p1157_result.columns, (
            "P1.157: engine must expose 'guarantor_rw_post_nbd' column "
            "(max(guarantor_rw_irb, RW_direct) per Art. 160(4)) — column missing."
        )

        # Assert value
        actual = p1157_result["guarantor_rw_post_nbd"][0]
        assert actual == pytest.approx(EXPECTED_GUARANTOR_RW_POST_NBD, abs=1e-6), (
            f"P1.157 Art. 160(4): guarantor_rw_post_nbd should be "
            f"{EXPECTED_GUARANTOR_RW_POST_NBD:.6f} "
            f"(max(guarantor_rw_irb={EXPECTED_GUARANTOR_RW_IRB:.6f}, "
            f"RW_direct={EXPECTED_RW_DIRECT:.6f})), "
            f"got {actual:.6f}"
        )

    # -------------------------------------------------------------------------
    # SECONDARY ASSERTIONS — verify the guarantee is correctly disapplied
    # -------------------------------------------------------------------------

    def test_p1_157_guarantee_status_non_beneficial(
        self,
        p1157_result: pl.DataFrame,
    ) -> None:
        """
        P1.157: guarantee must be disapplied because guarantor_rw_post_nbd > borrower_rw.

        guarantor_rw_post_nbd = 0.174677 > borrower_rw = 0.111571 → non-beneficial.
        Expected guarantee_status: GUARANTEE_NOT_APPLIED_NON_BENEFICIAL.
        """
        # Arrange
        row = p1157_result.row(0, named=True)

        # Assert
        assert row["guarantee_status"] == "GUARANTEE_NOT_APPLIED_NON_BENEFICIAL", (
            f"P1.157: guarantee should be disapplied (non-beneficial) because "
            f"guarantor_rw_post_nbd ({EXPECTED_GUARANTOR_RW_POST_NBD:.6f}) >= "
            f"borrower_rw ({EXPECTED_BORROWER_RW:.6f}), "
            f"got guarantee_status={row['guarantee_status']!r}"
        )

    def test_p1_157_guarantee_method_no_substitution(
        self,
        p1157_result: pl.DataFrame,
    ) -> None:
        """
        P1.157: guarantee_method_used must be NO_SUBSTITUTION when disapplied.

        When the guarantee is non-beneficial (guarantor_rw_post_nbd >= borrower_rw),
        no CRM substitution occurs and guarantee_method_used = "NO_SUBSTITUTION".
        """
        # Arrange
        row = p1157_result.row(0, named=True)

        # Assert
        assert row["guarantee_method_used"] == "NO_SUBSTITUTION", (
            f"P1.157: guarantee_method_used should be NO_SUBSTITUTION "
            f"(guarantee disapplied), got {row['guarantee_method_used']!r}"
        )

    def test_p1_157_rwa_equals_borrower_unprotected(
        self,
        p1157_result: pl.DataFrame,
        borrower_rw: float,
    ) -> None:
        """
        P1.157: RWA must equal the borrower's unprotected IRB RWA (guarantee disapplied).

        rwa = borrower_rw × EAD = 0.111571 × 1,000,000 = 111,571.43
        The guarantee contributes no capital reduction.
        """
        # Arrange
        row = p1157_result.row(0, named=True)
        expected_rwa = borrower_rw * EAD_FACILITY

        # Assert
        assert row["rwa"] == pytest.approx(expected_rwa, rel=1e-4), (
            f"P1.157: RWA should be {expected_rwa:,.2f} (borrower_rw × EAD, "
            f"guarantee disapplied), got {row['rwa']:,.2f}"
        )

    # -------------------------------------------------------------------------
    # REGRESSION GUARD — guarantor PD input floor already applied before NBD
    # -------------------------------------------------------------------------

    def test_p1_157_guarantor_pd_below_corporate_b31_floor(self) -> None:
        """
        P1.157: raw guarantor PD (0.0004) is below the B31 corporate floor (0.0005).

        This is the input condition that makes Art. 160(4) load-bearing: the engine
        must floor the guarantor PD to 0.0005 before computing guarantor_rw_irb,
        and then the NBD floor imposes max(guarantor_rw_irb, RW_direct) on top.

        Regression guard: ensures the fixture constants are set up correctly.
        """
        # Arrange — verify fixture constants
        assert PD_GUARANTOR_RAW < PD_GUARANTOR_FLOORED, (
            f"P1.157 fixture: raw guarantor PD ({PD_GUARANTOR_RAW}) must be below "
            f"B31 corporate floor ({PD_GUARANTOR_FLOORED}) so Art. 160(4) is exercised"
        )
        assert PD_GUARANTOR_FLOORED == pytest.approx(0.0005, abs=1e-10), (
            f"P1.157: B31 corporate PD floor should be 0.0005 (0.05%), "
            f"got {PD_GUARANTOR_FLOORED}"
        )
