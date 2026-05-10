"""
P1.124: CRR Art. 237(2)(a) guarantee maturity ineligibility.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> SACalculator -> Aggregator

Key responsibilities:
- Confirm that a guarantee with original_maturity_years < 1.0 is rejected as ineligible
  per CRR Art. 237(2)(a) (minimum residual maturity of protection >= 1 year).
- Confirm that a guarantee with original_maturity_years >= 1.0 is accepted.

Two scenarios (one fixture run per parametrized case):

    GUAR_SHORT_P1124:    original_maturity_years=0.75  → INELIGIBLE → RWA = 1,000,000
    GUAR_ELIGIBLE_P1124: original_maturity_years=2.0   → ELIGIBLE   → RWA < 1,000,000

Defect under test (pre-fix):
    The CRM processor does not enforce CRR Art. 237(2)(a).  With GUAR_SHORT, the engine
    still applies the guarantee and substitutes the guarantor's RW (20%), yielding
    RWA ≈ 200,000 instead of the correct 1,000,000.

Hand-calculation (CRR, CalculationConfig.crr()):
    Loan EAD = 1,000,000 GBP (drawn_amount=1,000,000, interest=0)

    GUAR_SHORT (ineligible path):
        original_maturity_years = 0.75 < 1.0
        Art. 237(2)(a): residual maturity < 1 year → protection ineligible
        RW  = corporate CQS 4 = 100%
        RWA = 1,000,000 × 1.00 = 1,000,000

    GUAR_ELIGIBLE (eligible path):
        original_maturity_years = 2.0 >= 1.0
        Art. 237(2)(a): satisfied
        Substitution: RW of guarantor (institution GB CQS 1) = 20%
        guaranteed_portion > 0 and total RWA < 1,000,000

References:
    - CRR Art. 237(2)(a): minimum residual maturity of protection >= 1 year
    - CRR Art. 207: eligibility conditions for unfunded credit protection
    - tests/fixtures/p1_124/p1_124.py: fixture builder and scenario constants
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import cast

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_124"

# ---------------------------------------------------------------------------
# Constants from the fixture builder
# ---------------------------------------------------------------------------

from tests.fixtures.p1_124.p1_124 import (  # noqa: E402
    EXPECTED_RWA_INELIGIBLE,
    GUAR_ELIGIBLE_REF,
    GUAR_SHORT_REF,
    LOAN_EAD,
    LOAN_REF,
)

# ---------------------------------------------------------------------------
# Reporting date: after loan value_date (2026-01-01), before short guarantee
# expiry (2026-10-01), so residual maturity of GUAR_SHORT is <1y from here.
# ---------------------------------------------------------------------------
_REPORTING_DATE = date(2026, 6, 1)


# ---------------------------------------------------------------------------
# Helper — build a RawDataBundle for a single guarantee reference
# ---------------------------------------------------------------------------


def _make_bundle(guarantee_ref: str) -> RawDataBundle:
    """
    Construct a RawDataBundle for LOAN_001_P1124 with exactly one guarantee row.

    Args:
        guarantee_ref: Either GUAR_SHORT_REF or GUAR_ELIGIBLE_REF.

    Returns:
        RawDataBundle ready for pipeline execution.
    """
    single_guar = pl.scan_parquet(_FIXTURES_DIR / "guarantee.parquet").filter(
        pl.col("guarantee_reference") == guarantee_ref
    )
    return RawDataBundle(
        facilities=pl.LazyFrame(
            schema={
                "facility_reference": pl.String,
                "counterparty_reference": pl.String,
            }
        ),
        loans=pl.scan_parquet(_FIXTURES_DIR / "loan.parquet"),
        counterparties=pl.scan_parquet(_FIXTURES_DIR / "counterparty.parquet"),
        facility_mappings=pl.LazyFrame(
            schema={
                "parent_facility_reference": pl.String,
                "child_reference": pl.String,
                "child_type": pl.String,
            }
        ),
        lending_mappings=pl.LazyFrame(
            schema={
                "parent_counterparty_reference": pl.String,
                "child_counterparty_reference": pl.String,
            }
        ),
        ratings=pl.scan_parquet(_FIXTURES_DIR / "rating.parquet"),
        guarantees=single_guar,
    )


def _run_pipeline(guarantee_ref: str) -> pl.DataFrame:
    """
    Run the full CRR SA pipeline for the given guarantee scenario.

    Returns the SA results DataFrame (all rows, including guarantee sub-rows).
    """
    bundle = _make_bundle(guarantee_ref)
    config = CalculationConfig.crr(
        reporting_date=_REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )
    results = PipelineOrchestrator().run_with_data(bundle, config)
    assert results.sa_results is not None, "SA results must not be None for SA-only config"
    return cast(pl.DataFrame, results.sa_results.collect())


def _aggregate_by_parent(df: pl.DataFrame, parent_ref: str) -> dict:
    """
    Aggregate all sub-rows (guarantee split rows + remainder) for a parent exposure.

    Additive fields (rwa_final, guaranteed_portion, ead_final) are summed.
    The first value is used for non-additive fields.
    """
    sub_rows = df.filter(pl.col("parent_exposure_reference") == parent_ref)
    assert sub_rows.height > 0, (
        f"No SA result rows found with parent_exposure_reference='{parent_ref}'"
    )
    _additive = {"rwa_final", "guaranteed_portion", "unguaranteed_portion", "ead_final"}
    result: dict = {}
    for col_name in sub_rows.columns:
        if col_name in _additive:
            result[col_name] = sub_rows[col_name].sum()
        else:
            result[col_name] = sub_rows[col_name][0]
    return result


# ---------------------------------------------------------------------------
# Acceptance tests — P1.124 CRR Art. 237(2)(a) guarantee maturity ineligibility
# ---------------------------------------------------------------------------


class TestP1124Art2372aGuaranteeIneligibility:
    """
    P1.124: CRR Art. 237(2)(a) — guarantee with residual maturity < 1 year is ineligible.

    Two scenarios driven by a module-scoped pipeline fixture each:
      - GUAR_SHORT  (0.75y): ineligible → full borrower RWA (1,000,000)
      - GUAR_ELIGIBLE (2.0y): eligible  → CRM benefit applied (RWA < 1,000,000)
    """

    # -----------------------------------------------------------------------
    # Module-scoped pipeline results — one run per guarantee scenario
    # -----------------------------------------------------------------------

    @pytest.fixture(scope="class")
    def guar_short_results(self) -> dict:
        """
        SA pipeline result for LOAN_001_P1124 under GUAR_SHORT_P1124 (0.75y, ineligible).

        Aggregates all guarantee sub-rows (guaranteed split + remainder) by parent ref.
        """
        df = _run_pipeline(GUAR_SHORT_REF)
        return _aggregate_by_parent(df, LOAN_REF)

    @pytest.fixture(scope="class")
    def guar_eligible_results(self) -> dict:
        """
        SA pipeline result for LOAN_001_P1124 under GUAR_ELIGIBLE_P1124 (2.0y, eligible).

        Aggregates all guarantee sub-rows by parent ref.
        """
        df = _run_pipeline(GUAR_ELIGIBLE_REF)
        return _aggregate_by_parent(df, LOAN_REF)

    # -----------------------------------------------------------------------
    # GUAR_SHORT (ineligible) scenario — THIS FAILS TODAY (pre-fix)
    # -----------------------------------------------------------------------

    def test_p1_124_art_237_2a_short_maturity_guarantee_rwa_equals_full_borrower_rwa(
        self, guar_short_results: dict
    ) -> None:
        """
        CRR Art. 237(2)(a): guarantee with original_maturity_years=0.75 is ineligible.

        Arrange: LOAN_001_P1124 (GBP 1M, corp CQS4 100% RW) + GUAR_SHORT_P1124 (0.75y).
        Act:     full CRR SA pipeline.
        Assert:  total rwa_final == 1,000,000 (no CRM benefit — guarantee REJECTED).

        This test FAILS today because the engine applies the guarantee and returns
        rwa_final ≈ 200,000 (guarantor CQS 1, 20% RW) instead of 1,000,000.
        """
        # Arrange
        row = guar_short_results
        expected_rwa = EXPECTED_RWA_INELIGIBLE  # 1,000,000.0

        # Assert
        assert row["rwa_final"] == pytest.approx(expected_rwa, rel=1e-4), (
            f"P1.124 GUAR_SHORT: expected rwa_final={expected_rwa:,.0f} "
            f"(Art. 237(2)(a): 0.75y guarantee is ineligible → full borrower RW 100%), "
            f"got {row['rwa_final']:,.2f}"
        )

    def test_p1_124_art_237_2a_short_maturity_guarantee_portion_is_zero(
        self, guar_short_results: dict
    ) -> None:
        """
        CRR Art. 237(2)(a): ineligible guarantee must produce guaranteed_portion == 0.

        Arrange: GUAR_SHORT_P1124 (original_maturity_years=0.75 < 1.0).
        Act:     full CRR SA pipeline.
        Assert:  guaranteed_portion == 0.0 (no substitution applied).

        This test FAILS today because the engine assigns guaranteed_portion = 1,000,000.
        """
        # Arrange
        row = guar_short_results

        # Assert
        assert row["guaranteed_portion"] == pytest.approx(0.0, abs=1.0), (
            f"P1.124 GUAR_SHORT: expected guaranteed_portion=0.0 "
            f"(guarantee ineligible per Art. 237(2)(a)), "
            f"got {row['guaranteed_portion']:,.2f}"
        )

    # -----------------------------------------------------------------------
    # GUAR_ELIGIBLE (eligible) scenario — should PASS today (regression pin)
    # -----------------------------------------------------------------------

    def test_p1_124_art_237_2a_eligible_guarantee_produces_crm_benefit(
        self, guar_eligible_results: dict
    ) -> None:
        """
        CRR Art. 237(2)(a): guarantee with original_maturity_years=2.0 is eligible.

        Arrange: LOAN_001_P1124 + GUAR_ELIGIBLE_P1124 (2.0y).
        Act:     full CRR SA pipeline.
        Assert:  guaranteed_portion > 0 (substitution was applied).

        This test should PASS today — it confirms the engine does apply eligible
        guarantees and is retained as a regression pin.
        """
        # Arrange
        row = guar_eligible_results

        # Assert
        assert row["guaranteed_portion"] > 0.0, (
            f"P1.124 GUAR_ELIGIBLE: expected guaranteed_portion > 0 "
            f"(2.0y guarantee is eligible per Art. 237(2)(a)), "
            f"got {row['guaranteed_portion']:,.2f}"
        )

    def test_p1_124_art_237_2a_eligible_guarantee_reduces_rwa_below_full_borrower_rwa(
        self, guar_eligible_results: dict
    ) -> None:
        """
        CRR Art. 237(2)(a): eligible guarantee must reduce total RWA below unmitigated level.

        Arrange: LOAN_001_P1124 + GUAR_ELIGIBLE_P1124 (2.0y).
        Act:     full CRR SA pipeline.
        Assert:  rwa_final < 1,000,000 (some CRM benefit observed).

        This test should PASS today. Exact value is not pinned because the maturity
        mismatch adjustment (CRR Art. 238) is out of scope for this scenario.
        """
        # Arrange
        row = guar_eligible_results
        full_borrower_rwa = LOAN_EAD  # 1,000,000.0 (100% RW × EAD)

        # Assert
        assert row["rwa_final"] < full_borrower_rwa, (
            f"P1.124 GUAR_ELIGIBLE: expected rwa_final < {full_borrower_rwa:,.0f} "
            f"(eligible guarantee reduces RWA), "
            f"got {row['rwa_final']:,.2f}"
        )
