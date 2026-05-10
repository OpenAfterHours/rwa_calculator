"""
P2.14 / CRR-A38: CRR Art. 128 high-risk class omitted via SI 2021/1078.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> SACalculator -> Aggregator

Key responsibilities:
- Validate that CRR Art. 128 (150% risk weight for high-risk items) is a dead letter
  under UK onshored CRR: exposures with entity_type "high_risk_venture_capital" and
  "high_risk_private_equity" must fall through to the residual/OTHER exposure class
  and receive a 100% risk weight, not the 150% Art. 128 treatment.
- Regression guard: confirm that PRA PS1/26 Basel 3.1 (effective 1 Jan 2027)
  re-introduces the 150% high-risk class as expected.

Bug (pre-fix): The engine applies a single high_risk risk weight table shared across
    both CRR and Basel 3.1 frameworks. Under UK CRR, SI 2021/1078 reg. 6(3)(a) omitted
    Art. 128 from the onshored text (effective 1 Jan 2022). The engine must return 100%
    (residual OTHER class) for CRR, not 150%.

Hand-calculations (CRR Art. 134 / OTHER fallthrough, reporting_date = 2024-12-31):
    Art. 128 omitted from UK CRR by SI 2021/1078 reg. 6(3)(a).
    entity_type=high_risk_venture_capital / high_risk_private_equity:
        → exposure class falls through to OTHER (residual), RW = 100%

    LN_VC_001: EAD = 1,000,000 GBP, RW = 1.00, RWA = 1,000,000
    LN_PE_002: EAD = 2,000,000 GBP, RW = 1.00, RWA = 2,000,000
    Loan-row total RWA = 3,000,000

    Pre-fix (Art. 128 applied under CRR): both rows return RW = 1.50, RWA = 4,500,000.

Hand-calculations (Basel 3.1 PRA PS1/26 Art. 128, reporting_date = 2027-06-30):
    Art. 128 re-introduced from 1 Jan 2027 at 150%.

    LN_VC_001: EAD = 1,000,000 GBP, RW = 1.50, RWA = 1,500,000
    LN_PE_002: EAD = 2,000,000 GBP, RW = 1.50, RWA = 3,000,000
    Loan-row total RWA = 4,500,000

Cross-framework delta: B31_total_rwa - CRR_total_rwa = 1,500,000 = 0.50 × total_ead.

Note on row count: the fixture includes committed facilities, so the SA results contain
    four rows (two loans + two facility undrawn rows). All per-row and aggregate assertions
    in this module target the two loan rows (LN_VC_001, LN_PE_002) only. The undrawn
    facility rows are omitted from the hand-calculation totals documented in p2_14.py.

References:
    - SI 2021/1078 reg. 6(3)(a): omission of Art. 128 from UK onshored CRR.
    - CRR Art. 128: high-risk items 150% (dead letter under UK CRR).
    - PRA PS1/26 Art. 128: re-introduction of high-risk 150% from 1 Jan 2027.
    - tests/fixtures/p2_14/p2_14.py: scenario constants and parquet builders.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p2_14"

# ---------------------------------------------------------------------------
# Scenario constants (single source of truth, mirrors p2_14.py)
# ---------------------------------------------------------------------------

_LOAN_VC = "LN_VC_001"  # high_risk_venture_capital, EAD=1,000,000 GBP
_LOAN_PE = "LN_PE_002"  # high_risk_private_equity,  EAD=2,000,000 GBP

_EAD_VC = 1_000_000.0
_EAD_PE = 2_000_000.0
_TOTAL_EAD = _EAD_VC + _EAD_PE  # 3,000,000

# Tolerances
_RW_TOL = 1e-6  # absolute on risk_weight
_RWA_TOL = 0.50  # £0.50 absolute on rwa_final

# ---------------------------------------------------------------------------
# CRR post-fix expected values (Art. 128 omitted → OTHER fallthrough, 100%)
# ---------------------------------------------------------------------------

_CRR_RW = 1.00
_CRR_RWA_VC = _EAD_VC * _CRR_RW  # 1,000,000
_CRR_RWA_PE = _EAD_PE * _CRR_RW  # 2,000,000
_CRR_TOTAL_RWA = _CRR_RWA_VC + _CRR_RWA_PE  # 3,000,000

# ---------------------------------------------------------------------------
# Basel 3.1 regression expected values (Art. 128 re-introduced, 150%)
# ---------------------------------------------------------------------------

_B31_RW = 1.50
_B31_RWA_VC = _EAD_VC * _B31_RW  # 1,500,000
_B31_RWA_PE = _EAD_PE * _B31_RW  # 3,000,000
_B31_TOTAL_RWA = _B31_RWA_VC + _B31_RWA_PE  # 4,500,000

# ---------------------------------------------------------------------------
# Pre-fix sentinel (what the engine currently returns for CRR)
# — engine uses Art. 128 150% under CRR, same as Basel 3.1 path
# ---------------------------------------------------------------------------

_BUGGY_CRR_RW = 1.50
_BUGGY_CRR_RWA_VC = _EAD_VC * _BUGGY_CRR_RW  # 1,500,000
_BUGGY_CRR_RWA_PE = _EAD_PE * _BUGGY_CRR_RW  # 3,000,000


# ---------------------------------------------------------------------------
# Shared bundle builder
# ---------------------------------------------------------------------------


def _build_bundle() -> RawDataBundle:
    """
    Load the P2.14 scenario parquets and assemble a RawDataBundle.

    Includes facilities (committed GBP loans) and the two loans.
    No collateral, guarantees, ratings, provisions, or FX — pure SA scenario.
    All amounts are GBP, so no FX conversion is required.
    """
    counterparties = pl.scan_parquet(_FIXTURES_DIR / "counterparty.parquet")
    loans = pl.scan_parquet(_FIXTURES_DIR / "loan.parquet")
    facilities = pl.scan_parquet(_FIXTURES_DIR / "facility.parquet")

    return RawDataBundle(
        facilities=facilities,
        loans=loans,
        counterparties=counterparties,
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
    )


def _extract_loan_row(sa_results: pl.LazyFrame, loan_ref: str) -> dict:
    """
    Filter SA results to a single row for loan_ref and return as a dict.

    Asserts exactly one row is found — the pipeline must not drop or duplicate
    the loan exposure.
    """
    df = sa_results.filter(pl.col("exposure_reference") == loan_ref).collect()
    assert len(df) == 1, (
        f"P2.14: expected exactly 1 SA row for {loan_ref}, got {len(df)}. "
        f"Pipeline may have dropped or duplicated the exposure."
    )
    return df.to_dicts()[0]


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def p2_14_crr_results() -> dict[str, dict]:
    """
    Run the P2.14 fixtures through the CRR SA pipeline once.

    Returns a mapping of loan_reference -> result row dict for both loan rows.
    Module-scoped to avoid repeated pipeline runs.

    Pre-fix: engine applies Art. 128 150% even under CRR (risk_weight=1.50).
    Post-fix: Art. 128 must be suppressed under CRR; exposures fall through to
    OTHER (residual) class at 100% (risk_weight=1.00).
    """
    # Arrange
    bundle = _build_bundle()
    config = CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        permission_mode=PermissionMode.STANDARDISED,
    )

    # Act
    results = PipelineOrchestrator().run_with_data(bundle, config)

    assert results.sa_results is not None, (
        "P2.14 CRR: SA results should not be None for SA-only config"
    )

    # Extract one dict per loan reference
    sa_lf = results.sa_results
    return {loan_ref: _extract_loan_row(sa_lf, loan_ref) for loan_ref in (_LOAN_VC, _LOAN_PE)}


@pytest.fixture(scope="module")
def p2_14_b31_results() -> dict[str, dict]:
    """
    Run the P2.14 fixtures through the Basel 3.1 SA pipeline once.

    Returns a mapping of loan_reference -> result row dict for both loan rows.
    Module-scoped to avoid repeated pipeline runs.

    This is the regression guard — Basel 3.1 must continue to apply 150%
    for high-risk exposures (PRA PS1/26 Art. 128).
    """
    # Arrange
    bundle = _build_bundle()
    config = CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 30),
        permission_mode=PermissionMode.STANDARDISED,
    )

    # Act
    results = PipelineOrchestrator().run_with_data(bundle, config)

    assert results.sa_results is not None, (
        "P2.14 B3.1: SA results should not be None for SA-only config"
    )

    # Extract one dict per loan reference
    sa_lf = results.sa_results
    return {loan_ref: _extract_loan_row(sa_lf, loan_ref) for loan_ref in (_LOAN_VC, _LOAN_PE)}


# ---------------------------------------------------------------------------
# CRR tests — assert Art. 128 is suppressed (post-fix, 100% risk weight)
# ---------------------------------------------------------------------------


class TestCRRArt128HighRiskUKOmitted:
    """
    P2.14 — CRR: Art. 128 high-risk class must be suppressed under UK CRR.

    SI 2021/1078 reg. 6(3)(a) omitted Art. 128 from the onshored CRR text
    with effect from 1 January 2022. Exposures with entity_types
    "high_risk_venture_capital" and "high_risk_private_equity" must therefore
    fall through to the residual OTHER exposure class at 100% risk weight.

    Pre-fix failures (engine applies Art. 128 under CRR):
      LN_VC_001: rw=1.50 (wrong), should be 1.00
      LN_PE_002: rw=1.50 (wrong), should be 1.00
    """

    # ------------------------------------------------------------------
    # LN_VC_001 — high_risk_venture_capital
    # ------------------------------------------------------------------

    def test_crr_vc_loan_exposure_class(self, p2_14_crr_results: dict[str, dict]) -> None:
        """
        LN_VC_001 must be classified as residual (OTHER) exposure class under CRR.

        SI 2021/1078: Art. 128 omitted → high_risk entity types fall through
        to the residual OTHER class.

        Arrange: LN_VC_001, entity_type=high_risk_venture_capital.
        Act:     full CRR SA pipeline, reporting_date=2024-12-31.
        Assert:  exposure_class_for_sa != "high_risk"
                 (post-fix: should be "other" or the residual class string).
        """
        # Arrange
        row = p2_14_crr_results[_LOAN_VC]

        # Assert — under CRR Art. 128 is omitted, so high_risk class is dead letter
        assert row["exposure_class_for_sa"] != "high_risk", (
            f"P2.14 CRR LN_VC_001: exposure_class_for_sa must not be 'high_risk' "
            f"under UK CRR (Art. 128 omitted by SI 2021/1078 reg. 6(3)(a)); "
            f"got '{row['exposure_class_for_sa']}'"
        )

    def test_crr_vc_loan_risk_weight(self, p2_14_crr_results: dict[str, dict]) -> None:
        """
        LN_VC_001 must receive 100% risk weight under CRR (residual OTHER class).

        Art. 128 is omitted → OTHER/residual fallthrough at 100%.

        Arrange: LN_VC_001, entity_type=high_risk_venture_capital, EAD=1,000,000 GBP.
        Act:     full CRR SA pipeline, reporting_date=2024-12-31.
        Assert:  risk_weight == 1.00.

        Pre-fix (Art. 128 applied under CRR): risk_weight = 1.50.
        """
        # Arrange
        row = p2_14_crr_results[_LOAN_VC]

        # Assert
        assert row["risk_weight"] == pytest.approx(_CRR_RW, abs=_RW_TOL), (
            f"P2.14 CRR LN_VC_001: expected risk_weight={_CRR_RW} "
            f"(UK CRR Art. 128 omitted by SI 2021/1078 → OTHER fallthrough 100%), "
            f"got {row['risk_weight']} "
            f"(pre-fix Art. 128 gives {_BUGGY_CRR_RW})"
        )

    def test_crr_vc_loan_rwa(self, p2_14_crr_results: dict[str, dict]) -> None:
        """
        RWA for LN_VC_001 = EAD × 100% = 1,000,000 under CRR.

        Arrange: LN_VC_001, EAD=1,000,000 GBP, RW=100%.
        Act:     full CRR SA pipeline, reporting_date=2024-12-31.
        Assert:  rwa_final == 1,000,000 ± £0.50.

        Pre-fix (Art. 128 at 150%): rwa_final = 1,500,000.
        """
        # Arrange
        row = p2_14_crr_results[_LOAN_VC]

        # Assert
        assert row["rwa_final"] == pytest.approx(_CRR_RWA_VC, abs=_RWA_TOL), (
            f"P2.14 CRR LN_VC_001: expected rwa_final={_CRR_RWA_VC:,.0f} "
            f"(EAD 1,000,000 × 100%), "
            f"got {row['rwa_final']:,.2f} "
            f"(pre-fix Art. 128: {_BUGGY_CRR_RWA_VC:,.0f})"
        )

    # ------------------------------------------------------------------
    # LN_PE_002 — high_risk_private_equity
    # ------------------------------------------------------------------

    def test_crr_pe_loan_exposure_class(self, p2_14_crr_results: dict[str, dict]) -> None:
        """
        LN_PE_002 must be classified as residual (OTHER) exposure class under CRR.

        SI 2021/1078: Art. 128 omitted → high_risk entity types fall through
        to the residual OTHER class.

        Arrange: LN_PE_002, entity_type=high_risk_private_equity.
        Act:     full CRR SA pipeline, reporting_date=2024-12-31.
        Assert:  exposure_class_for_sa != "high_risk".
        """
        # Arrange
        row = p2_14_crr_results[_LOAN_PE]

        # Assert — under CRR Art. 128 is omitted, so high_risk class is dead letter
        assert row["exposure_class_for_sa"] != "high_risk", (
            f"P2.14 CRR LN_PE_002: exposure_class_for_sa must not be 'high_risk' "
            f"under UK CRR (Art. 128 omitted by SI 2021/1078 reg. 6(3)(a)); "
            f"got '{row['exposure_class_for_sa']}'"
        )

    def test_crr_pe_loan_risk_weight(self, p2_14_crr_results: dict[str, dict]) -> None:
        """
        LN_PE_002 must receive 100% risk weight under CRR (residual OTHER class).

        Art. 128 is omitted → OTHER/residual fallthrough at 100%.

        Arrange: LN_PE_002, entity_type=high_risk_private_equity, EAD=2,000,000 GBP.
        Act:     full CRR SA pipeline, reporting_date=2024-12-31.
        Assert:  risk_weight == 1.00.

        Pre-fix (Art. 128 applied under CRR): risk_weight = 1.50.
        """
        # Arrange
        row = p2_14_crr_results[_LOAN_PE]

        # Assert
        assert row["risk_weight"] == pytest.approx(_CRR_RW, abs=_RW_TOL), (
            f"P2.14 CRR LN_PE_002: expected risk_weight={_CRR_RW} "
            f"(UK CRR Art. 128 omitted by SI 2021/1078 → OTHER fallthrough 100%), "
            f"got {row['risk_weight']} "
            f"(pre-fix Art. 128 gives {_BUGGY_CRR_RW})"
        )

    def test_crr_pe_loan_rwa(self, p2_14_crr_results: dict[str, dict]) -> None:
        """
        RWA for LN_PE_002 = EAD × 100% = 2,000,000 under CRR.

        Arrange: LN_PE_002, EAD=2,000,000 GBP, RW=100%.
        Act:     full CRR SA pipeline, reporting_date=2024-12-31.
        Assert:  rwa_final == 2,000,000 ± £0.50.

        Pre-fix (Art. 128 at 150%): rwa_final = 3,000,000.
        """
        # Arrange
        row = p2_14_crr_results[_LOAN_PE]

        # Assert
        assert row["rwa_final"] == pytest.approx(_CRR_RWA_PE, abs=_RWA_TOL), (
            f"P2.14 CRR LN_PE_002: expected rwa_final={_CRR_RWA_PE:,.0f} "
            f"(EAD 2,000,000 × 100%), "
            f"got {row['rwa_final']:,.2f} "
            f"(pre-fix Art. 128: {_BUGGY_CRR_RWA_PE:,.0f})"
        )

    # ------------------------------------------------------------------
    # Aggregate — loan-row total RWA
    # ------------------------------------------------------------------

    def test_crr_total_loan_rwa(self, p2_14_crr_results: dict[str, dict]) -> None:
        """
        Total loan-row RWA under CRR = 3,000,000 (both loans at 100%).

        Aggregate: RWA_VC + RWA_PE = 1,000,000 + 2,000,000 = 3,000,000.

        Arrange: LN_VC_001 + LN_PE_002, total EAD=3,000,000 GBP, RW=100%.
        Act:     full CRR SA pipeline, reporting_date=2024-12-31.
        Assert:  sum(rwa_final) == 3,000,000 ± £1.00.

        Pre-fix (Art. 128 at 150%): total_rwa = 4,500,000.
        """
        # Arrange
        total_rwa = sum(
            p2_14_crr_results[loan_ref]["rwa_final"] for loan_ref in (_LOAN_VC, _LOAN_PE)
        )

        # Assert
        assert total_rwa == pytest.approx(_CRR_TOTAL_RWA, abs=1.0), (
            f"P2.14 CRR total loan RWA: expected {_CRR_TOTAL_RWA:,.0f} "
            f"(3,000,000 EAD × 100%), "
            f"got {total_rwa:,.2f} "
            f"(pre-fix Art. 128 at 150% gives {_BUGGY_CRR_RWA_VC + _BUGGY_CRR_RWA_PE:,.0f})"
        )


# ---------------------------------------------------------------------------
# Basel 3.1 regression tests — 150% must remain intact after CRR fix
# ---------------------------------------------------------------------------


class TestB31Art128HighRiskUnchanged:
    """
    P2.14 regression guard — Basel 3.1 PRA PS1/26 Art. 128: high-risk exposures
    must continue to receive 150% risk weight after the CRR suppression fix.

    If the engine-implementer's fix incorrectly removes the B3.1 high-risk path,
    these tests will catch the regression.
    """

    # ------------------------------------------------------------------
    # LN_VC_001 — Basel 3.1 regression
    # ------------------------------------------------------------------

    def test_b31_vc_loan_risk_weight(self, p2_14_b31_results: dict[str, dict]) -> None:
        """
        B3.1: LN_VC_001 must receive 150% risk weight (Art. 128 re-introduced).

        PRA PS1/26 Art. 128: high-risk items 150% from 1 Jan 2027.

        Arrange: LN_VC_001, entity_type=high_risk_venture_capital, EAD=1,000,000 GBP.
        Act:     full Basel 3.1 SA pipeline, reporting_date=2027-06-30.
        Assert:  risk_weight == 1.50.
        """
        # Arrange
        row = p2_14_b31_results[_LOAN_VC]

        # Assert
        assert row["risk_weight"] == pytest.approx(_B31_RW, abs=_RW_TOL), (
            f"P2.14 B3.1 LN_VC_001: expected risk_weight={_B31_RW} "
            f"(PRA PS1/26 Art. 128 high-risk 150%), "
            f"got {row['risk_weight']}"
        )

    def test_b31_vc_loan_rwa(self, p2_14_b31_results: dict[str, dict]) -> None:
        """
        B3.1: RWA for LN_VC_001 = EAD × 150% = 1,500,000.

        Arrange: LN_VC_001, EAD=1,000,000 GBP, RW=150%.
        Act:     full Basel 3.1 SA pipeline, reporting_date=2027-06-30.
        Assert:  rwa_final == 1,500,000 ± £0.50.
        """
        # Arrange
        row = p2_14_b31_results[_LOAN_VC]

        # Assert
        assert row["rwa_final"] == pytest.approx(_B31_RWA_VC, abs=_RWA_TOL), (
            f"P2.14 B3.1 LN_VC_001: expected rwa_final={_B31_RWA_VC:,.0f} "
            f"(EAD 1,000,000 × 150%), "
            f"got {row['rwa_final']:,.2f}"
        )

    # ------------------------------------------------------------------
    # LN_PE_002 — Basel 3.1 regression
    # ------------------------------------------------------------------

    def test_b31_pe_loan_risk_weight(self, p2_14_b31_results: dict[str, dict]) -> None:
        """
        B3.1: LN_PE_002 must receive 150% risk weight (Art. 128 re-introduced).

        PRA PS1/26 Art. 128: high-risk items 150% from 1 Jan 2027.

        Arrange: LN_PE_002, entity_type=high_risk_private_equity, EAD=2,000,000 GBP.
        Act:     full Basel 3.1 SA pipeline, reporting_date=2027-06-30.
        Assert:  risk_weight == 1.50.
        """
        # Arrange
        row = p2_14_b31_results[_LOAN_PE]

        # Assert
        assert row["risk_weight"] == pytest.approx(_B31_RW, abs=_RW_TOL), (
            f"P2.14 B3.1 LN_PE_002: expected risk_weight={_B31_RW} "
            f"(PRA PS1/26 Art. 128 high-risk 150%), "
            f"got {row['risk_weight']}"
        )

    def test_b31_pe_loan_rwa(self, p2_14_b31_results: dict[str, dict]) -> None:
        """
        B3.1: RWA for LN_PE_002 = EAD × 150% = 3,000,000.

        Arrange: LN_PE_002, EAD=2,000,000 GBP, RW=150%.
        Act:     full Basel 3.1 SA pipeline, reporting_date=2027-06-30.
        Assert:  rwa_final == 3,000,000 ± £0.50.
        """
        # Arrange
        row = p2_14_b31_results[_LOAN_PE]

        # Assert
        assert row["rwa_final"] == pytest.approx(_B31_RWA_PE, abs=_RWA_TOL), (
            f"P2.14 B3.1 LN_PE_002: expected rwa_final={_B31_RWA_PE:,.0f} "
            f"(EAD 2,000,000 × 150%), "
            f"got {row['rwa_final']:,.2f}"
        )

    # ------------------------------------------------------------------
    # Aggregate — Basel 3.1 loan-row total RWA
    # ------------------------------------------------------------------

    def test_b31_total_loan_rwa(self, p2_14_b31_results: dict[str, dict]) -> None:
        """
        Total loan-row RWA under Basel 3.1 = 4,500,000 (both loans at 150%).

        Aggregate: RWA_VC + RWA_PE = 1,500,000 + 3,000,000 = 4,500,000.

        Arrange: LN_VC_001 + LN_PE_002, total EAD=3,000,000 GBP, RW=150%.
        Act:     full Basel 3.1 SA pipeline, reporting_date=2027-06-30.
        Assert:  sum(rwa_final) == 4,500,000 ± £1.00.
        """
        # Arrange
        total_rwa = sum(
            p2_14_b31_results[loan_ref]["rwa_final"] for loan_ref in (_LOAN_VC, _LOAN_PE)
        )

        # Assert
        assert total_rwa == pytest.approx(_B31_TOTAL_RWA, abs=1.0), (
            f"P2.14 B3.1 total loan RWA: expected {_B31_TOTAL_RWA:,.0f} "
            f"(3,000,000 EAD × 150%), "
            f"got {total_rwa:,.2f}"
        )


# ---------------------------------------------------------------------------
# Cross-framework delta
# ---------------------------------------------------------------------------


class TestP214CrossFrameworkDelta:
    """
    P2.14: Cross-framework RWA delta validates that the CRR fix (100%) and B3.1
    regression guard (150%) produce the expected 50% uplift on total EAD.

    B31_total_rwa - CRR_total_rwa = 0.50 × total_ead = 1,500,000.

    This test will only pass once both frameworks produce correct values.
    """

    def test_cross_framework_rwa_delta(
        self,
        p2_14_crr_results: dict[str, dict],
        p2_14_b31_results: dict[str, dict],
    ) -> None:
        """
        B31 loan RWA minus CRR loan RWA must equal 50% of total EAD = 1,500,000.

        delta = (B31_RW - CRR_RW) × total_EAD = (1.50 - 1.00) × 3,000,000 = 1,500,000.

        Arrange: loan rows from both CRR and Basel 3.1 runs.
        Act:     sum rwa_final across both loan rows per framework.
        Assert:  b31_total - crr_total == 1,500,000 ± £2.00.
        """
        # Arrange
        crr_total = sum(
            p2_14_crr_results[loan_ref]["rwa_final"] for loan_ref in (_LOAN_VC, _LOAN_PE)
        )
        b31_total = sum(
            p2_14_b31_results[loan_ref]["rwa_final"] for loan_ref in (_LOAN_VC, _LOAN_PE)
        )
        expected_delta = 0.50 * _TOTAL_EAD  # 1,500,000

        # Assert
        delta = b31_total - crr_total
        assert delta == pytest.approx(expected_delta, abs=2.0), (
            f"P2.14 cross-framework delta: "
            f"B31_total={b31_total:,.2f} - CRR_total={crr_total:,.2f} = {delta:,.2f}, "
            f"expected delta = {expected_delta:,.0f} (0.50 × {_TOTAL_EAD:,.0f} EAD)"
        )
