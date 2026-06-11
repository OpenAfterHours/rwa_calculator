"""
Art. 222 FCSM — Simple Method election must apply on the production (unified) pipeline.

Pipeline position:
    RawDataBundle -> Loader -> HierarchyResolver -> Classifier -> CRMProcessor
        (get_crm_unified_bundle) -> SACalculator -> Aggregator

Bug site (pre-fix):
    CRMProcessor.get_crm_adjusted_bundle (legacy/test-facing path) calls
    compute_fcsm_columns() and undo_sa_ead_reduction() when
    config.crm_collateral_method == CRMCollateralMethod.SIMPLE. The production
    pipeline (engine/pipeline.py) calls get_crm_unified_bundle instead, which
    never invokes either function. A firm electing the Financial Collateral
    Simple Method therefore silently receives Comprehensive Method treatment
    (EAD reduction by haircut-adjusted collateral) instead of Art. 222 risk
    weight substitution: SACalculator.apply_fcsm_rw_substitution early-returns
    because fcsm_collateral_value is absent from the unified frame.

Scenario: two GBP 1M drawn corporate loans (unrated -> SA RW 100%), each
collateralised by an eligible corporate bond (issuer CQS 2 -> SA RW 50%):

    LN_FCSM_FULL: collateral market value 1,000,000 (full coverage)
    LN_FCSM_PART: collateral market value   600,000 (60% coverage)

Hand calculation (CRR, CalculationConfig.crr(crm_collateral_method=SIMPLE)):
    Both loans: EAD = drawn = 1,000,000; unsecured RW = 1.00 (Art. 122 unrated)
    Collateral item RW = max(FCSM floor 0.20, corporate CQS 2 RW 0.50) = 0.50
    Art. 222 does NOT reduce EAD — ead_final stays 1,000,000.

    LN_FCSM_FULL (secured_pct = 1,000,000 / 1,000,000 = 1.00):
        blended_rw = 1.00 x 0.50 + 0.00 x 1.00 = 0.50
        rwa = 1,000,000 x 0.50 = 500,000

    LN_FCSM_PART (secured_pct = 600,000 / 1,000,000 = 0.60):
        blended_rw = 0.60 x 0.50 + 0.40 x 1.00 = 0.70
        rwa = 1,000,000 x 0.70 = 700,000

Pre-fix unified-path behaviour (incorrect — Comprehensive applied instead):
    EAD is reduced by the haircut-adjusted bond value, risk_weight stays 1.00,
    and fcsm_collateral_value never reaches the SA calculator. For LN_FCSM_FULL
    that yields rwa far below 500,000 with ead_final far below 1,000,000.

References:
    - CRR Art. 222: Financial Collateral Simple Method (RW substitution, no EAD
      reduction; 20% floor per Art. 222(3))
    - CRR Art. 122 Table 5: corporate CQS 2 = 50%; unrated corporate = 100%
    - src/rwa_calc/engine/crm/processor.py: get_crm_unified_bundle (bug site)
    - src/rwa_calc/engine/crm/simple_method.py: compute_fcsm_columns,
      undo_sa_ead_reduction
    - tests/acceptance/crr/test_p1_104_art_239_1_fcsm_maturity_eligibility.py:
      component-level FCSM semantics this test lifts to the full pipeline
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import COLLATERAL_SCHEMA, COUNTERPARTY_SCHEMA, LOAN_SCHEMA
from rwa_calc.domain.enums import CRMCollateralMethod, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

_REPORTING_DATE = date(2026, 6, 1)

_CP_FULL = "CP_FCSM_UNI_FULL"
_CP_PART = "CP_FCSM_UNI_PART"
_LOAN_FULL = "LN_FCSM_UNI_FULL"
_LOAN_PART = "LN_FCSM_UNI_PART"

_DRAWN = 1_000_000.0
_COLLATERAL_FULL = 1_000_000.0  # full coverage
_COLLATERAL_PART = 600_000.0  # 60% coverage

# Corporate CQS 2 collateral RW = max(0.20 FCSM floor, 0.50) = 0.50 (Art. 222(3))
_COLLATERAL_RW = 0.50
# Unrated corporate borrower RW = 1.00 (CRR Art. 122)
_UNSECURED_RW = 1.00

# Expected Simple Method outputs (Art. 222: RW substitution, no EAD reduction)
_EXPECTED_EAD_FINAL = _DRAWN  # 1,000,000 — EAD must NOT be reduced
_EXPECTED_RW_FULL = _COLLATERAL_RW  # 1.00 x 0.50 + 0.00 x 1.00 = 0.50
_EXPECTED_RWA_FULL = _DRAWN * _EXPECTED_RW_FULL  # 500,000
_SECURED_PCT_PART = _COLLATERAL_PART / _DRAWN  # 0.60
_EXPECTED_RW_PART = _SECURED_PCT_PART * _COLLATERAL_RW + (1 - _SECURED_PCT_PART) * _UNSECURED_RW
_EXPECTED_RWA_PART = _DRAWN * _EXPECTED_RW_PART  # 700,000


# ---------------------------------------------------------------------------
# Bundle assembly (in-memory; loan-only scenario with direct collateral)
# ---------------------------------------------------------------------------


def _build_bundle() -> RawDataBundle:
    """Assemble the two-loan FCSM scenario as an in-memory RawDataBundle."""
    counterparties = pl.DataFrame(
        [
            {
                "counterparty_reference": ref,
                "counterparty_name": f"FCSM Unified Path Test {ref}",
                "entity_type": "corporate",
                "country_code": "GB",
                "default_status": False,
                "apply_fi_scalar": False,
                "is_financial_sector_entity": False,
            }
            for ref in (_CP_FULL, _CP_PART)
        ],
        schema=dtypes_of(COUNTERPARTY_SCHEMA),
    ).lazy()

    loans = pl.DataFrame(
        [
            {
                "loan_reference": loan_ref,
                "counterparty_reference": cp_ref,
                "currency": "GBP",
                "value_date": date(2026, 1, 1),
                "maturity_date": date(2031, 1, 1),
                "drawn_amount": _DRAWN,
                "interest": 0.0,
                "seniority": "senior",
            }
            for loan_ref, cp_ref in ((_LOAN_FULL, _CP_FULL), (_LOAN_PART, _CP_PART))
        ],
        schema=dtypes_of(LOAN_SCHEMA),
    ).lazy()

    collateral = pl.DataFrame(
        [
            {
                "collateral_reference": coll_ref,
                "collateral_type": "bond",
                "currency": "GBP",
                "market_value": market_value,
                "beneficiary_type": "loan",
                "beneficiary_reference": loan_ref,
                "issuer_type": "corporate",
                "issuer_cqs": 2,
                "is_eligible_financial_collateral": True,
            }
            for coll_ref, loan_ref, market_value in (
                ("COLL_FCSM_UNI_FULL", _LOAN_FULL, _COLLATERAL_FULL),
                ("COLL_FCSM_UNI_PART", _LOAN_PART, _COLLATERAL_PART),
            )
        ],
        schema=dtypes_of(COLLATERAL_SCHEMA),
    ).lazy()

    return RawDataBundle(
        facilities=pl.LazyFrame(
            schema={"facility_reference": pl.String, "counterparty_reference": pl.String}
        ),
        loans=loans,
        counterparties=counterparties,
        collateral=collateral,
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


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def fcsm_unified_sa_rows() -> dict[str, dict]:
    """
    Run the FCSM scenario through the full production pipeline; rows by loan ref.

    Arrange:
        - Counterparties: two unrated GB corporates (SA RW 100%)
        - Loans: two GBP 1M drawn loans, one per counterparty
        - Collateral: eligible corporate bonds (issuer CQS 2), market values
          1,000,000 (full coverage) and 600,000 (60% coverage), direct
          beneficiary_type='loan'
        - Config: CRR, STANDARDISED, crm_collateral_method=SIMPLE

    Act: PipelineOrchestrator().run_with_data — this exercises the unified CRM
    path (get_crm_unified_bundle), i.e. exactly what production runs.
    """
    # Arrange
    bundle = _build_bundle()
    config = CalculationConfig.crr(
        reporting_date=_REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
        crm_collateral_method=CRMCollateralMethod.SIMPLE,
    )

    # Act
    results = PipelineOrchestrator().run_with_data(bundle, config)

    assert results.sa_results is not None, "SA results should not be None for SA-only config"
    df = results.sa_results.collect()

    rows: dict[str, dict] = {}
    for loan_ref in (_LOAN_FULL, _LOAN_PART):
        matched = df.filter(pl.col("exposure_reference") == loan_ref).to_dicts()
        assert len(matched) == 1, (
            f"FCSM unified: expected exactly 1 SA row for {loan_ref}, got {len(matched)}"
        )
        rows[loan_ref] = matched[0]
    return rows


# ---------------------------------------------------------------------------
# Acceptance tests — Art. 222 semantics on the production pipeline
# ---------------------------------------------------------------------------


class TestArt222FCSMUnifiedPipelineFullCoverage:
    """
    Art. 222 Simple Method on the production pipeline — fully covered loan.

    LN_FCSM_UNI_FULL is 100% covered by a 50%-RW corporate bond. Under FCSM the
    secured portion takes the collateral RW and the EAD is untouched.

    Pre-fix: the unified CRM path never computes fcsm_* columns, so the SA
    calculator's apply_fcsm_rw_substitution early-returns and the Comprehensive
    EAD reduction is left in place (risk_weight 1.00, EAD reduced).
    """

    def test_fcsm_full_coverage_risk_weight_substituted(
        self, fcsm_unified_sa_rows: dict[str, dict]
    ) -> None:
        """
        Art. 222(1): secured portion gets the collateral RW — blended RW = 0.50.

        Arrange: 1M loan (RW 1.00) fully covered by CQS 2 corporate bond (RW 0.50).
        Act:     full production pipeline with SIMPLE election.
        Assert:  risk_weight == 0.50.
        """
        # Arrange
        row = fcsm_unified_sa_rows[_LOAN_FULL]

        # Assert
        assert row["risk_weight"] == pytest.approx(_EXPECTED_RW_FULL, abs=1e-6), (
            f"FCSM unified (full coverage): risk_weight should be "
            f"{_EXPECTED_RW_FULL:.2f} (Art. 222 substitution: 1.00 secured x 0.50), "
            f"got {row['risk_weight']:.4f}. "
            f"Pre-fix: unified CRM path never computes fcsm_* columns, RW stays 1.00."
        )

    def test_fcsm_full_coverage_ead_not_reduced(
        self, fcsm_unified_sa_rows: dict[str, dict]
    ) -> None:
        """
        Art. 222 does not reduce EAD — ead_final must stay 1,000,000.

        Arrange: as above.
        Act:     full production pipeline with SIMPLE election.
        Assert:  ead_final == 1,000,000 (undo_sa_ead_reduction applied).

        Pre-fix: the Comprehensive Method's SA EAD reduction is never undone on
        the unified path, so ead_final is reduced by the haircut-adjusted bond.
        """
        # Arrange
        row = fcsm_unified_sa_rows[_LOAN_FULL]

        # Assert
        assert row["ead_final"] == pytest.approx(_EXPECTED_EAD_FINAL, rel=1e-9), (
            f"FCSM unified (full coverage): ead_final should be "
            f"{_EXPECTED_EAD_FINAL:,.0f} (Art. 222 substitutes RW, never reduces EAD), "
            f"got {row['ead_final']:,.2f}. "
            f"Pre-fix: Comprehensive EAD reduction is applied instead."
        )

    def test_fcsm_full_coverage_rwa(self, fcsm_unified_sa_rows: dict[str, dict]) -> None:
        """
        RWA = EAD x blended RW = 1,000,000 x 0.50 = 500,000.

        Arrange: as above.
        Act:     full production pipeline with SIMPLE election.
        Assert:  rwa_final == 500,000.
        """
        # Arrange
        row = fcsm_unified_sa_rows[_LOAN_FULL]

        # Assert
        assert row["rwa_final"] == pytest.approx(_EXPECTED_RWA_FULL, rel=1e-6), (
            f"FCSM unified (full coverage): rwa_final should be {_EXPECTED_RWA_FULL:,.0f} "
            f"(1,000,000 x 0.50 blended RW), got {row['rwa_final']:,.2f} "
            f"(ead_final={row['ead_final']:,.2f} x risk_weight={row['risk_weight']:.4f})."
        )


class TestArt222FCSMUnifiedPipelinePartialCoverage:
    """
    Art. 222 Simple Method on the production pipeline — 60% covered loan.

    LN_FCSM_UNI_PART is 60% covered, so the blended RW mixes the collateral RW
    (secured portion) with the borrower RW (unsecured remainder):
        blended_rw = 0.60 x 0.50 + 0.40 x 1.00 = 0.70
    """

    def test_fcsm_partial_coverage_blended_risk_weight(
        self, fcsm_unified_sa_rows: dict[str, dict]
    ) -> None:
        """
        Art. 222(2): unsecured remainder keeps the borrower RW — blended RW = 0.70.

        Arrange: 1M loan (RW 1.00), 600k CQS 2 corporate bond collateral (RW 0.50).
        Act:     full production pipeline with SIMPLE election.
        Assert:  risk_weight == 0.70.
        """
        # Arrange
        row = fcsm_unified_sa_rows[_LOAN_PART]

        # Assert
        assert row["risk_weight"] == pytest.approx(_EXPECTED_RW_PART, abs=1e-6), (
            f"FCSM unified (60% coverage): risk_weight should be {_EXPECTED_RW_PART:.2f} "
            f"(0.60 x 0.50 + 0.40 x 1.00), got {row['risk_weight']:.4f}. "
            f"Pre-fix: unified CRM path never computes fcsm_* columns, RW stays 1.00."
        )

    def test_fcsm_partial_coverage_ead_not_reduced(
        self, fcsm_unified_sa_rows: dict[str, dict]
    ) -> None:
        """
        Art. 222 does not reduce EAD — ead_final must stay 1,000,000.

        Arrange: as above.
        Act:     full production pipeline with SIMPLE election.
        Assert:  ead_final == 1,000,000.
        """
        # Arrange
        row = fcsm_unified_sa_rows[_LOAN_PART]

        # Assert
        assert row["ead_final"] == pytest.approx(_EXPECTED_EAD_FINAL, rel=1e-9), (
            f"FCSM unified (60% coverage): ead_final should be {_EXPECTED_EAD_FINAL:,.0f}, "
            f"got {row['ead_final']:,.2f}. "
            f"Pre-fix: Comprehensive EAD reduction is applied instead."
        )

    def test_fcsm_partial_coverage_rwa(self, fcsm_unified_sa_rows: dict[str, dict]) -> None:
        """
        RWA = EAD x blended RW = 1,000,000 x 0.70 = 700,000.

        Arrange: as above.
        Act:     full production pipeline with SIMPLE election.
        Assert:  rwa_final == 700,000.
        """
        # Arrange
        row = fcsm_unified_sa_rows[_LOAN_PART]

        # Assert
        assert row["rwa_final"] == pytest.approx(_EXPECTED_RWA_PART, rel=1e-6), (
            f"FCSM unified (60% coverage): rwa_final should be {_EXPECTED_RWA_PART:,.0f} "
            f"(1,000,000 x 0.70 blended RW), got {row['rwa_final']:,.2f} "
            f"(ead_final={row['ead_final']:,.2f} x risk_weight={row['risk_weight']:.4f})."
        )
