"""
P1.140 — Basel 3.1 ADC classification derivation (Art. 124(3) / Art. 124K).

Pipeline position:
    Loader → HierarchyResolver → Classifier → CRMProcessor → SACalculator → Aggregator

Scenario design:
    ADC ("Acquisition, Development and Construction") exposures attract 150% RW
    under Basel 3.1 Art. 124K(1) unless specific qualifying conditions are met.

    The ADC flag on collateral may be supplied explicitly (is_adc=True/False) or
    must be derived by the engine from is_under_construction on the loan/facility
    plus the borrower type gate (corporate AND NOT natural-person).

    Two exposures are included:
        LN_ADC_SPV_001: corporate SPV, development_finance, is_under_construction=True
            → is_adc derived as True (corporate entity, non-natural-person)
            → exposure_class = CORPORATE, risk_weight = 1.50 (Art. 124K(1))
            → rwa = 10,000,000 × 1.50 = 15,000,000

        LN_ADC_NP_001: individual (natural-person), mortgage, is_under_construction=True
            → natural-person gate fails → is_adc derived as False
            → treated as residential mortgage (Art. 124F loan-splitting)
            → risk_weight ≠ 1.50

    Both collateral rows have is_adc=null — the derivation is the sole source.

Pre-fix (current) behaviour without derivation:
    is_adc = False for both → SPV falls through RE loan-splitting
    Total SPV rwa ≈ 4,925,000 (not 15,000,000). Test asserts 15,000,000 → FAILS.

Post-fix expected behaviour:
    is_adc derived = True for SPV → ADC 150% path fires
    Total SPV rwa = 15,000,000.

Regulatory references:
    - PRA PS1/26 Glossary p.3: ADC definition
    - PRA PS1/26 Art. 124(3) p.50: ADC routing
    - PRA PS1/26 Art. 124K(1) p.58: ADC risk weight = 150%
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.data.schemas import FACILITY_SCHEMA, LOAN_SCHEMA
from rwa_calc.engine.loader import ensure_columns
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_140"

# Exposure references (from fixture module constants)
_LOAN_SPV_REF = "LN_ADC_SPV_001"
_LOAN_NP_REF = "LN_ADC_NP_001"

# Expected post-fix values for SPV (the discriminating row)
# Art. 124K(1): ADC non-presold non-qualifying default RW = 150%
_EXPECTED_ADC_RISK_WEIGHT = 1.50
_EXPECTED_SPV_EAD = 10_000_000.0
_EXPECTED_SPV_RWA = 15_000_000.0  # 10,000,000 × 1.50
_EXPECTED_SPV_EXPOSURE_CLASS = "corporate"

# Pre-fix total SPV rwa (for documentation only — not asserted)
# Split into residential_mortgage (rw=0.20) and corporate_sme (rw=0.85)
# pre_fix_rwa ≈ 4,925,000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_bundle() -> RawDataBundle:
    """
    Construct a RawDataBundle from P1.140 parquets.

    The p1_140 loan and facility parquets carry the new is_under_construction
    column but are otherwise minimal (missing canonical optional columns).
    ensure_columns() extends them with all required defaults so the pipeline
    loader does not reject the frames.

    The collateral parquet has is_adc=null on both rows — the engine must
    derive the ADC flag from exposure-level attributes, not the collateral.
    """
    loan_base = pl.scan_parquet(_FIXTURES_DIR / "loan.parquet")
    loans = ensure_columns(loan_base, LOAN_SCHEMA)

    fac_base = pl.scan_parquet(_FIXTURES_DIR / "facility.parquet")
    facilities = ensure_columns(fac_base, FACILITY_SCHEMA)

    return make_raw_bundle(
        facilities=facilities,
        loans=loans,
        counterparties=pl.scan_parquet(_FIXTURES_DIR / "counterparty.parquet"),
        facility_mappings=pl.scan_parquet(_FIXTURES_DIR / "facility_mapping.parquet"),
        lending_mappings=pl.scan_parquet(_FIXTURES_DIR / "lending_mapping.parquet"),
        collateral=pl.scan_parquet(_FIXTURES_DIR / "collateral.parquet"),
    )


def _b31_config() -> CalculationConfig:
    """Basel 3.1 SA-only config with reporting_date=2027-06-30 (post-go-live)."""
    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 30),
        permission_mode=PermissionMode.STANDARDISED,
    )


# ---------------------------------------------------------------------------
# Module-scoped SA results fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def p1_140_sa_results() -> pl.DataFrame:
    """
    Run P1.140 fixtures through the Basel 3.1 SA pipeline and return SA results.

    Arrange: SPV (corporate, development_finance, is_under_construction=True) and
             NP (individual, mortgage, is_under_construction=True) with null is_adc
             on both collateral rows. B31 SA-only config, 2027-06-30.
    Act:     PipelineOrchestrator().run_with_data(bundle, config).sa_results.
    Return:  Collected SA results DataFrame for all assertions.
    """
    bundle = _build_bundle()
    config = _b31_config()
    results = PipelineOrchestrator().run_with_data(bundle, config)
    assert results.sa_results is not None, (
        "SA results should not be None — check PermissionMode.STANDARDISED config"
    )
    return results.sa_results.collect()


def _get_spv_rows(df: pl.DataFrame) -> pl.DataFrame:
    """
    Return all rows derived from LN_ADC_SPV_001.

    Post-fix: a single CORPORATE row (no RE loan-splitting when is_adc=True).
    Pre-fix:  two split rows (residential_mortgage + corporate_sme).
    Uses split_parent_id (== loan_reference when row is a RE-split child) or
    exposure_reference starts with the loan reference.
    """
    return df.filter(
        (pl.col("exposure_reference") == _LOAN_SPV_REF)
        | (pl.col("split_parent_id") == _LOAN_SPV_REF)
    )


def _get_spv_total_rwa(df: pl.DataFrame) -> float:
    """Return the summed rwa_final for all rows derived from LN_ADC_SPV_001."""
    return _get_spv_rows(df)["rwa_final"].sum()


def _get_np_row(df: pl.DataFrame) -> dict:
    """Return the single result row for LN_ADC_NP_001."""
    rows = df.filter(pl.col("exposure_reference") == _LOAN_NP_REF).to_dicts()
    assert len(rows) == 1, (
        f"Expected exactly 1 row for {_LOAN_NP_REF}, got {len(rows)}. "
        f"Rows: {df.select(['exposure_reference', 'split_parent_id']).to_dicts()}"
    )
    return rows[0]


# ---------------------------------------------------------------------------
# P1.140 acceptance test class
# ---------------------------------------------------------------------------


class TestB31P1140ADCClassificationDerivation:
    """
    P1.140: Basel 3.1 ADC classification derivation from is_under_construction flag.

    When is_adc is null on collateral, the engine must derive it from:
        - is_under_construction=True on the loan/facility
        - AND borrower is NOT a natural person (corporate gate)

    The discriminating row (LN_ADC_SPV_001) is a corporate SPV with
    development_finance product_type and is_under_construction=True.
    Post-fix: is_adc=True, exposure_class=corporate, risk_weight=1.50,
              rwa=15,000,000 (Art. 124K(1)).
    Pre-fix:  is_adc=False, RE loan-splitting fires, rwa≈4,925,000.

    The negative case (LN_ADC_NP_001) has is_under_construction=True but
    the borrower is a natural person — the corporate gate blocks ADC
    classification, so risk_weight ≠ 1.50.
    """

    # -------------------------------------------------------------------------
    # DISCRIMINATING ASSERTION — FAILS pre-fix
    # -------------------------------------------------------------------------

    def test_p1_140_spv_total_rwa_is_15m(self, p1_140_sa_results: pl.DataFrame) -> None:
        """
        P1.140 DISCRIMINATING: SPV ADC exposure total rwa = 15,000,000.

        Art. 124K(1) (PRA PS1/26): ADC exposure (non-presold, non-qualifying)
        receives 150% risk weight. EAD = £10,000,000 → rwa = £15,000,000.

        Pre-fix (current): is_adc derivation missing → is_adc=False → RE
            loan-splitting fires → total rwa ≈ 4,925,000. This test FAILS.
        Post-fix expected: is_adc=True → ADC 150% path → rwa = 15,000,000.

        Arrange: B31 SA-only config, SPV corporate development_finance loan
                 £10,000,000, is_under_construction=True, collateral is_adc=null.
        Act:     Sum rwa_final across all rows derived from LN_ADC_SPV_001.
        Assert:  total rwa_final ≈ 15,000,000 (abs=1e-3).
        """
        # Arrange
        total_rwa = _get_spv_total_rwa(p1_140_sa_results)

        # Assert — FAILS pre-fix (engine returns ≈ 4,925,000)
        assert total_rwa == pytest.approx(_EXPECTED_SPV_RWA, abs=1e-3), (
            f"P1.140: SPV ADC total rwa should be {_EXPECTED_SPV_RWA:,.0f} "
            f"(EAD £10m × Art. 124K(1) 150% ADC RW). "
            f"Got {total_rwa:,.0f}. "
            f"Pre-fix value ≈ 4,925,000: is_adc derivation not firing — "
            f"is_under_construction=True on loan is ignored, ADC flag stays False, "
            f"and RE loan-splitting is applied instead of the 150% ADC path."
        )

    def test_p1_140_spv_risk_weight_is_150_pct(self, p1_140_sa_results: pl.DataFrame) -> None:
        """
        P1.140 DISCRIMINATING: SPV ADC exposure risk_weight = 1.50.

        Art. 124K(1): ADC exposure default risk weight = 150%.
        Post-fix: single CORPORATE row with risk_weight=1.50.
        Pre-fix:  two RE-split rows with rw=0.20 and 0.85 — no row has 1.50.

        Arrange: B31 config, LN_ADC_SPV_001, is_adc derived True post-fix.
        Act:     Retrieve exposure_reference == LN_ADC_SPV_001 (post-fix single row).
        Assert:  risk_weight ≈ 1.50 (abs=1e-6).
        """
        # Arrange — post-fix: single row; pre-fix: no row with ref == _LOAN_SPV_REF
        rows = p1_140_sa_results.filter(pl.col("exposure_reference") == _LOAN_SPV_REF).to_dicts()

        # Pre-fix: no unsplit row exists (split_parent_id rows have different refs)
        # → assert will fail on the risk_weight check OR on the len check
        assert len(rows) == 1, (
            f"P1.140: expected exactly 1 unsplit row for {_LOAN_SPV_REF} "
            f"(ADC path does not split). Got {len(rows)} rows. "
            f"Pre-fix: loan is RE-split into 2 sub-rows, no unsplit row remains."
        )
        row = rows[0]

        # Assert
        assert row["risk_weight"] == pytest.approx(_EXPECTED_ADC_RISK_WEIGHT, abs=1e-6), (
            f"P1.140: SPV risk_weight should be {_EXPECTED_ADC_RISK_WEIGHT:.2f} "
            f"(Art. 124K(1) ADC 150%). Got {row['risk_weight']:.4f}."
        )

    def test_p1_140_spv_exposure_class_is_corporate(self, p1_140_sa_results: pl.DataFrame) -> None:
        """
        P1.140: SPV ADC exposure_class = corporate (not split into RE classes).

        ADC classification must suppress RE loan-splitting. Post-fix the SPV
        exposure routes to the corporate exposure class and receives 150% RW.
        Pre-fix the exposure is split into residential_mortgage + corporate_sme.

        Arrange: LN_ADC_SPV_001, post-fix single corporate row.
        Act:     exposure_class from the unsplit SPV row.
        Assert:  exposure_class == "corporate".
        """
        # Arrange
        rows = p1_140_sa_results.filter(pl.col("exposure_reference") == _LOAN_SPV_REF).to_dicts()

        assert len(rows) == 1, f"P1.140: expected exactly 1 unsplit SPV row. Got {len(rows)}."
        row = rows[0]

        # Assert
        assert row["exposure_class"] == _EXPECTED_SPV_EXPOSURE_CLASS, (
            f"P1.140: SPV exposure_class should be '{_EXPECTED_SPV_EXPOSURE_CLASS}' "
            f"(ADC path stays in corporate class). "
            f"Got {row['exposure_class']!r}. "
            f"Pre-fix: RE loan-splitting fires → classes are 'residential_mortgage' "
            f"and 'corporate_sme'."
        )

    def test_p1_140_spv_is_adc_is_true(self, p1_140_sa_results: pl.DataFrame) -> None:
        """
        P1.140 DISCRIMINATING: is_adc = True on the SPV row after derivation.

        The collateral row has is_adc=null. The engine must derive is_adc=True
        from is_under_construction=True on the loan + corporate (non-natural-person)
        borrower gate. Pre-fix: is_adc stays False (derivation not implemented).

        Arrange: LN_ADC_SPV_001, collateral is_adc=null, is_under_construction=True.
        Act:     ADC classification derivation in classifier or CRM processor.
        Assert:  is_adc == True on the SPV result row.
        """
        # Arrange — post-fix: single unsplit CORPORATE row with is_adc=True
        rows = p1_140_sa_results.filter(pl.col("exposure_reference") == _LOAN_SPV_REF).to_dicts()

        assert len(rows) == 1, f"P1.140: expected exactly 1 unsplit SPV row. Got {len(rows)}."
        row = rows[0]

        # Assert
        assert row["is_adc"] is True, (
            f"P1.140: is_adc should be True on the SPV row after derivation "
            f"(is_under_construction=True + corporate borrower). "
            f"Got is_adc={row['is_adc']!r}. "
            f"Pre-fix: derivation not implemented → is_adc=False remains from collateral."
        )

    def test_p1_140_spv_ead_is_10m(self, p1_140_sa_results: pl.DataFrame) -> None:
        """
        P1.140: SPV EAD = 10,000,000 (fully drawn, no interest, no CCF).

        Post-fix: single CORPORATE row, ead_final = 10,000,000.
        Pre-fix:  two RE-split rows with ead_final summing to 10,000,000
                  (5,500,000 + 4,500,000).

        Arrange: LN_ADC_SPV_001, drawn_amount=10,000,000, interest=0.
        Act:     ead_final from the unsplit ADC row.
        Assert:  ead_final ≈ 10,000,000 (abs=1e-3).
        """
        # Arrange
        rows = p1_140_sa_results.filter(pl.col("exposure_reference") == _LOAN_SPV_REF).to_dicts()

        assert len(rows) == 1, f"P1.140: expected exactly 1 unsplit SPV row. Got {len(rows)}."
        row = rows[0]

        # Assert
        assert row["ead_final"] == pytest.approx(_EXPECTED_SPV_EAD, abs=1e-3), (
            f"P1.140: SPV ead_final should be {_EXPECTED_SPV_EAD:,.0f}. "
            f"Got {row['ead_final']:,.0f}."
        )

    # -------------------------------------------------------------------------
    # NEGATIVE CASE — natural-person gate blocks ADC (regression guard)
    # -------------------------------------------------------------------------

    def test_p1_140_np_risk_weight_is_not_150_pct(self, p1_140_sa_results: pl.DataFrame) -> None:
        """
        P1.140 negative case: natural-person borrower does NOT get ADC 150% RW.

        The natural-person gate (corporate AND NOT natural-person) blocks is_adc
        derivation for LN_ADC_NP_001 even though is_under_construction=True.
        The NP mortgage is treated as a standard residential mortgage (Art. 124F).

        Arrange: LN_ADC_NP_001, individual borrower (is_natural_person=True),
                 is_under_construction=True, collateral is_adc=null.
        Act:     Pipeline SA results for NP mortgage row.
        Assert:  risk_weight != 1.50 (natural-person gate prevents ADC 150%).
        """
        # Arrange
        row = _get_np_row(p1_140_sa_results)

        # Assert — structural: NP should never receive 150% from ADC path
        assert row["risk_weight"] != pytest.approx(_EXPECTED_ADC_RISK_WEIGHT, abs=1e-4), (
            f"P1.140 negative case: NP mortgage risk_weight should NOT be "
            f"{_EXPECTED_ADC_RISK_WEIGHT:.2f} (natural-person gate must block ADC). "
            f"Got {row['risk_weight']:.4f}."
        )

    def test_p1_140_np_is_adc_is_false(self, p1_140_sa_results: pl.DataFrame) -> None:
        """
        P1.140 negative case: is_adc = False for natural-person borrower.

        Natural persons are excluded from the ADC corporate gate even when
        is_under_construction=True. The NP mortgage retains is_adc=False.

        Arrange: LN_ADC_NP_001, individual borrower.
        Act:     is_adc from the NP mortgage result row.
        Assert:  is_adc == False.
        """
        # Arrange
        row = _get_np_row(p1_140_sa_results)

        # Assert
        assert row["is_adc"] is False, (
            f"P1.140 negative case: NP mortgage should have is_adc=False "
            f"(natural-person gate blocks ADC). Got is_adc={row['is_adc']!r}."
        )

    # -------------------------------------------------------------------------
    # REGRESSION — EAD integrity across both exposures
    # -------------------------------------------------------------------------

    def test_p1_140_np_ead_is_250k(self, p1_140_sa_results: pl.DataFrame) -> None:
        """
        P1.140: NP mortgage EAD = 250,000 (fully drawn, interest=0).

        Arrange: LN_ADC_NP_001, drawn_amount=250,000, interest=0.
        Act:     ead_final from NP mortgage result row.
        Assert:  ead_final ≈ 250,000 (abs=1e-3).
        """
        # Arrange
        row = _get_np_row(p1_140_sa_results)

        # Assert
        assert row["ead_final"] == pytest.approx(250_000.0, abs=1e-3), (
            f"P1.140: NP ead_final should be 250,000, got {row['ead_final']:,.0f}."
        )
