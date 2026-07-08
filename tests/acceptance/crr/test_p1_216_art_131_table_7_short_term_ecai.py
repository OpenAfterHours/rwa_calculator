"""
P1.216: CRR Art. 131 Table 7 — short-term ECAI risk weights (institution + corporate).

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> SACalculator -> Aggregator

Key responsibilities:
- Validate CRR Art. 131 Table 7: exposures carrying a dedicated issue-specific
  short-term credit assessment (``is_short_term=True``, loan-scoped rating) must be
  risk-weighted from Table 7, not from the generic Art. 120(2) Table 4 short-term-
  maturity branch (institution leg) or the plain Art. 122 long-term
  ``corporate_risk_weights`` join (corporate leg).
- Two legs isolate the exact pre-fix divergence at different CQS bands:
    Leg A — institution, CQS 3: Table 4 (pre-fix) = 20% vs Table 7 (correct) = 100%.
    Leg B — corporate, CQS 4: Art. 122 base join (pre-fix) = 100% vs Table 7 = 150%.

Hand-calculation (CRR, CalculationConfig.crr(reporting_date=date(2025, 12, 31))):

    Leg A — Institution (CP_INST_ST7 / LN_INST_ST7), CQS 3:
        EAD = drawn_amount + interest = 1,000,000 + 0 = 1,000,000
        RW (correct, Table 7 Art. 131)    = 1.00  -> RWA = 1,000,000, K = 80,000
        RW (pre-fix, Table 4 Art. 120(2)) = 0.20  -> RWA =   200,000 (understated 5x)

    Leg B — Corporate (CP_CORP_ST7 / LN_CORP_ST7), CQS 4:
        EAD = drawn_amount + interest = 1,000,000 + 0 = 1,000,000
        RW (correct, Table 7 Art. 131)  = 1.50  -> RWA = 1,500,000, K = 120,000
        RW (pre-fix, Art. 122 base join) = 1.00  -> RWA = 1,000,000 (understated 50pp)

References:
    - CRR Art. 131, Table 7: short-term credit assessment risk weights
      (institutions and corporates) — 20/50/100/150/150/150 for CQS 1-6.
    - docs/specifications/crr/sa-risk-weights.md:631-653.
    - CRR Art. 120(2) Table 4: institution short-term general (contrastive, pre-fix path).
    - CRR Art. 122: corporate long-term risk weights (contrastive, pre-fix fallback).
    - tests/fixtures/p1_216/p1_216.py: scenario constants and parquet builders.
    - docs/plans/compliance-audit-crr-111-241-rectification.md:104-128 (WS1, P1.216 cluster).
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
from tests.acceptance.sa_bundle import build_sa_loan_bundle
from tests.fixtures.p1_216.p1_216 import (
    ART122_FALLBACK_RISK_WEIGHT_CORP,
    EXPECTED_RISK_WEIGHT_CORP,
    EXPECTED_RISK_WEIGHT_INST,
    EXPECTED_RWA_CORP,
    EXPECTED_RWA_INST,
    LOAN_REF_CORP,
    LOAN_REF_INST,
    REPORTING_DATE,
    TABLE4_FALLBACK_RISK_WEIGHT_INST,
)

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_216"

# ---------------------------------------------------------------------------
# Scenario constants (single source of truth, matches p1_216.py)
# ---------------------------------------------------------------------------

_EAD = 1_000_000.0

# ---------------------------------------------------------------------------
# Module-scoped pipeline fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def p1_216_sa_results() -> dict[str, dict]:
    """
    Run the P1.216 fixtures through the CRR SA pipeline once.

    Builds the shared loan-only RawDataBundle (counterparty/loan/rating parquets,
    no facilities/facility_mappings/lending_mappings rows) and runs a
    ``CalculationConfig.crr`` SA-only pipeline. Returns a mapping of
    loan_reference -> result row dict for both legs.

    Module-scoped to run the pipeline once and reuse results across all test
    methods in this module.
    """
    # Arrange
    bundle = build_sa_loan_bundle(_FIXTURES_DIR)
    config = CalculationConfig.crr(
        reporting_date=REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )

    # Act
    results = PipelineOrchestrator().run_with_data(bundle, config)

    assert results.sa_results is not None, "SA results should not be None for SA-only config"

    df = results.sa_results.collect()
    out: dict[str, dict] = {}
    for loan_ref in (LOAN_REF_INST, LOAN_REF_CORP):
        rows = df.filter(pl.col("exposure_reference") == loan_ref).to_dicts()
        assert len(rows) == 1, f"P1.216: expected exactly 1 SA row for {loan_ref}, got {len(rows)}"
        out[loan_ref] = rows[0]
    return out


# ---------------------------------------------------------------------------
# P1.216 acceptance tests — Leg A (institution, CQS 3)
# ---------------------------------------------------------------------------


class TestP1216Art131Table7ShortTermInstitution:
    """
    P1.216 Leg A — CRR Art. 131 Table 7: short-term ECAI institution, CQS 3 -> RW 100%.

    Pre-fix failure: engine routes via Art. 120(2) Table 4 (residual-maturity-gated),
    returning risk_weight=0.20 / rwa_final=200,000 instead of Table 7's 1.00 / 1,000,000.
    """

    def test_p1_216_institution_exposure_class(self, p1_216_sa_results: dict[str, dict]) -> None:
        """
        SA classifier routes entity_type=bank to exposure_class 'institution'.

        Arrange: CP_INST_ST7, entity_type=bank, loan-scoped short-term rating CQS 3.
        Act:     full CRR SA pipeline.
        Assert:  exposure_class == 'institution'.
        """
        # Arrange
        row = p1_216_sa_results[LOAN_REF_INST]

        # Assert
        assert row["exposure_class"].lower() == "institution", (
            f"P1.216 Leg A: expected exposure_class='institution', got {row['exposure_class']!r}"
        )

    def test_p1_216_institution_approach_applied(self, p1_216_sa_results: dict[str, dict]) -> None:
        """
        SA-only config routes the institution exposure to 'standardised' approach.

        Arrange: PermissionMode.STANDARDISED, no internal rating on CP_INST_ST7.
        Act:     full CRR SA pipeline.
        Assert:  approach_applied == 'standardised'.
        """
        # Arrange
        row = p1_216_sa_results[LOAN_REF_INST]

        # Assert
        assert row["approach_applied"] == "standardised", (
            f"P1.216 Leg A: expected approach_applied='standardised', "
            f"got {row['approach_applied']!r}"
        )

    def test_p1_216_institution_ead(self, p1_216_sa_results: dict[str, dict]) -> None:
        """
        EAD = drawn_amount + interest = 1,000,000 + 0 = 1,000,000 (no CCF, no CRM).

        Arrange: GBP 1,000,000 drawn, interest=0, no collateral.
        Act:     full CRR SA pipeline.
        Assert:  ead_final == 1,000,000.
        """
        # Arrange
        row = p1_216_sa_results[LOAN_REF_INST]

        # Assert
        assert row["ead_final"] == pytest.approx(_EAD, rel=1e-4), (
            f"P1.216 Leg A: expected ead_final={_EAD:,.0f}, got {row['ead_final']:,.2f}"
        )

    def test_p1_216_institution_risk_weight_is_table_7(
        self, p1_216_sa_results: dict[str, dict]
    ) -> None:
        """
        CRR Art. 131 Table 7: short-term ECAI institution, CQS 3 -> RW = 100%.

        The loan-scoped rating carries ``is_short_term=True``, so Table 7 must
        apply regardless of the residual-maturity gate that drives the pre-fix
        Art. 120(2) Table 4 branch (which would give 20% at CQS 3).

        Arrange: CP_INST_ST7, CQS 3, loan-scoped short-term external rating.
        Act:     full CRR SA pipeline.
        Assert:  risk_weight == 1.00 (not the Table 4 fallback 0.20).
        """
        # Arrange
        row = p1_216_sa_results[LOAN_REF_INST]

        # Assert
        assert row["risk_weight"] == pytest.approx(EXPECTED_RISK_WEIGHT_INST, abs=1e-4), (
            f"P1.216 Leg A: expected risk_weight={EXPECTED_RISK_WEIGHT_INST:.2f} "
            f"(CRR Art. 131 Table 7, CQS 3 = 100%), got {row['risk_weight']:.4f} "
            f"(engine still applies Table 4 fallback = "
            f"{TABLE4_FALLBACK_RISK_WEIGHT_INST:.2f})"
        )

    def test_p1_216_institution_rwa(self, p1_216_sa_results: dict[str, dict]) -> None:
        """
        RWA = EAD x RW = 1,000,000 x 1.00 = 1,000,000 (Table 7).

        Failure mode before fix: RWA = 1,000,000 x 0.20 = 200,000 (Table 4 path).

        Arrange: EAD=1,000,000, expected RW=1.00 (Art. 131 Table 7, CQS 3).
        Act:     full CRR SA pipeline.
        Assert:  rwa_final == 1,000,000.
        """
        # Arrange
        row = p1_216_sa_results[LOAN_REF_INST]

        # Assert
        assert row["rwa_final"] == pytest.approx(EXPECTED_RWA_INST, rel=1e-4), (
            f"P1.216 Leg A: expected rwa_final={EXPECTED_RWA_INST:,.0f} "
            f"(EAD x 100% Table 7), got {row['rwa_final']:,.2f}"
        )


# ---------------------------------------------------------------------------
# P1.216 acceptance tests — Leg B (corporate, CQS 4)
# ---------------------------------------------------------------------------


class TestP1216Art131Table7ShortTermCorporate:
    """
    P1.216 Leg B — CRR Art. 131 Table 7: short-term ECAI corporate, CQS 4 -> RW 150%.

    Pre-fix failure: engine routes via the plain Art. 122 long-term
    ``corporate_risk_weights`` join, returning risk_weight=1.00 / rwa_final=1,000,000
    instead of Table 7's 1.50 / 1,500,000.
    """

    def test_p1_216_corporate_exposure_class(self, p1_216_sa_results: dict[str, dict]) -> None:
        """
        SA classifier routes entity_type=corporate to exposure_class 'corporate'.

        Arrange: CP_CORP_ST7, entity_type=corporate (non-SME), loan-scoped
                 short-term rating CQS 4.
        Act:     full CRR SA pipeline.
        Assert:  exposure_class == 'corporate'.
        """
        # Arrange
        row = p1_216_sa_results[LOAN_REF_CORP]

        # Assert
        assert row["exposure_class"].lower() == "corporate", (
            f"P1.216 Leg B: expected exposure_class='corporate', got {row['exposure_class']!r}"
        )

    def test_p1_216_corporate_approach_applied(self, p1_216_sa_results: dict[str, dict]) -> None:
        """
        SA-only config routes the corporate exposure to 'standardised' approach.

        Arrange: PermissionMode.STANDARDISED, no internal rating on CP_CORP_ST7.
        Act:     full CRR SA pipeline.
        Assert:  approach_applied == 'standardised'.
        """
        # Arrange
        row = p1_216_sa_results[LOAN_REF_CORP]

        # Assert
        assert row["approach_applied"] == "standardised", (
            f"P1.216 Leg B: expected approach_applied='standardised', "
            f"got {row['approach_applied']!r}"
        )

    def test_p1_216_corporate_ead(self, p1_216_sa_results: dict[str, dict]) -> None:
        """
        EAD = drawn_amount + interest = 1,000,000 + 0 = 1,000,000 (no CCF, no CRM).

        Arrange: GBP 1,000,000 drawn, interest=0, no collateral.
        Act:     full CRR SA pipeline.
        Assert:  ead_final == 1,000,000.
        """
        # Arrange
        row = p1_216_sa_results[LOAN_REF_CORP]

        # Assert
        assert row["ead_final"] == pytest.approx(_EAD, rel=1e-4), (
            f"P1.216 Leg B: expected ead_final={_EAD:,.0f}, got {row['ead_final']:,.2f}"
        )

    def test_p1_216_corporate_risk_weight_is_table_7(
        self, p1_216_sa_results: dict[str, dict]
    ) -> None:
        """
        CRR Art. 131 Table 7: short-term ECAI corporate, CQS 4 -> RW = 150%.

        The loan-scoped rating carries ``is_short_term=True``, so Table 7 must
        apply instead of the plain Art. 122 ``corporate_risk_weights`` base join
        (which would give 100% at CQS 4).

        Arrange: CP_CORP_ST7, CQS 4, loan-scoped short-term external rating.
        Act:     full CRR SA pipeline.
        Assert:  risk_weight == 1.50 (not the Art. 122 base-join fallback 1.00).
        """
        # Arrange
        row = p1_216_sa_results[LOAN_REF_CORP]

        # Assert
        assert row["risk_weight"] == pytest.approx(EXPECTED_RISK_WEIGHT_CORP, abs=1e-4), (
            f"P1.216 Leg B: expected risk_weight={EXPECTED_RISK_WEIGHT_CORP:.2f} "
            f"(CRR Art. 131 Table 7, CQS 4 = 150%), got {row['risk_weight']:.4f} "
            f"(engine still applies Art. 122 base-join fallback = "
            f"{ART122_FALLBACK_RISK_WEIGHT_CORP:.2f})"
        )

    def test_p1_216_corporate_rwa(self, p1_216_sa_results: dict[str, dict]) -> None:
        """
        RWA = EAD x RW = 1,000,000 x 1.50 = 1,500,000 (Table 7).

        Failure mode before fix: RWA = 1,000,000 x 1.00 = 1,000,000 (Art. 122 base join).

        Arrange: EAD=1,000,000, expected RW=1.50 (Art. 131 Table 7, CQS 4).
        Act:     full CRR SA pipeline.
        Assert:  rwa_final == 1,500,000.
        """
        # Arrange
        row = p1_216_sa_results[LOAN_REF_CORP]

        # Assert
        assert row["rwa_final"] == pytest.approx(EXPECTED_RWA_CORP, rel=1e-4), (
            f"P1.216 Leg B: expected rwa_final={EXPECTED_RWA_CORP:,.0f} "
            f"(EAD x 150% Table 7), got {row['rwa_final']:,.2f}"
        )
