"""
P1.184: CRR Art. 117(1) — non-named MDB institution-table routing.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> SACalculator -> Aggregator

Key responsibilities:
- Validate CRR Art. 117(1): non-named MDB exposures must be risk-weighted using the
  institution risk-weight tables (Art. 120 Table 3 for rated, Art. 121 Table 5 for
  unrated sovereign-derived), NOT the dedicated Table 2B that was introduced by
  PRA PS1/26 Art. 117(1)(a) for Basel 3.1 only.
- Validate CRR Art. 117(2): named MDB exposures (entity_type="mdb_named") receive 0%
  unconditionally under both frameworks.
- Regression guard: confirm that Basel 3.1 continues to route non-named MDBs through
  Table 2B (the B3.1 dedicated MDB risk weight table).

Bug (pre-fix): The engine routes CRR non-named MDB exposures through MDB_RISK_WEIGHTS_TABLE_2B
    (CQS 2 = 30%, unrated = 50%), which are the PRA PS1/26 Art. 117(1)(a) values.
    Under CRR, non-named MDBs should use the Art. 120 institution table (CQS 2 = 50%,
    CRR institution unrated → sovereign-derived per Art. 121).

Hand-calculations (CRR Art. 117(1), reporting_date = 2026-06-30):

  L_MDB_RATED (CP_MDB_RATED_CQS2, institution_cqs=2):
    Institution table (Art. 120 Table 3): CQS 2 → 50%
    EAD: 1,000,000 KES × 1.0 (KES/GBP) = 1,000,000 GBP
    RWA: 1,000,000 × 0.50 = 500,000
    Pre-fix (Table 2B CQS 2 = 30%): RWA = 300,000

  L_MDB_UNRATED_SOV1 (CP_MDB_UNRATED_SOV1, no institution_cqs, sovereign_cqs=1):
    Art. 121 Table 5, sovereign CQS 1 → 20%
    EAD: 1,000,000 HNL × 1.0 (HNL/GBP) = 1,000,000 GBP
    RWA: 1,000,000 × 0.20 = 200,000
    Pre-fix (Table 2B unrated = 50%): RWA = 500,000

  L_MDB_UNRATED_NOSOV (CP_MDB_UNRATED_NOSOV, no institution_cqs, no sovereign_cqs):
    Art. 121 fallback (no sovereign CQS): 100%
    EAD: 1,000,000 USD × 0.79 (USD/GBP) = 790,000 GBP
    RWA: 790,000 × 1.00 = 790,000
    Pre-fix (Table 2B unrated = 50%): RWA = 395,000

  L_MDB_NAMED (CP_MDB_NAMED, entity_type="mdb_named"):
    Art. 117(2): named MDB → 0% unconditional
    EAD: 1,000,000 GBP
    RWA: 0 (both CRR and B3.1)

Hand-calculations (Basel 3.1 PRA PS1/26 Art. 117(1)(a) Table 2B, regression guard):

  L_MDB_RATED (institution_cqs=2):
    Table 2B: CQS 2 → 30%
    EAD: 1,000,000 GBP
    RWA: 1,000,000 × 0.30 = 300,000

  L_MDB_UNRATED_SOV1 (no institution_cqs, sovereign_cqs=1):
    Table 2B unrated row: 50%  (sovereign_cqs does NOT override for MDBs under B3.1)
    EAD: 1,000,000 GBP
    RWA: 1,000,000 × 0.50 = 500,000

  L_MDB_UNRATED_NOSOV (no institution_cqs, no sovereign_cqs):
    Table 2B unrated row: 50%
    EAD: 790,000 GBP
    RWA: 790,000 × 0.50 = 395,000

  L_MDB_NAMED: 0% → RWA = 0

FX note:
  Per-fixture fx_rates.parquet used (KES/HNL → GBP = 1.0, USD → GBP = 0.79).
  EAD for L_MDB_UNRATED_NOSOV = 790,000 GBP under both frameworks.

References:
    - CRR Art. 117(1): non-named MDB treated as institution (Art. 120/121 tables)
    - CRR Art. 117(2): named MDB list → 0%
    - CRR Art. 120 Table 3: rated institution risk weights (CQS 2 = 50%)
    - CRR Art. 121 Table 5: unrated institution sovereign-derived (sov CQS 1 = 20%)
    - PRA PS1/26 Art. 117(1)(a): Basel 3.1 dedicated Table 2B (CQS 2 = 30%, unrated = 50%)
    - tests/fixtures/p1_184/p1_184.py: scenario constants and parquet builders
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest
from tests.fixtures.raw_bundle import make_raw_bundle

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_184"

# ---------------------------------------------------------------------------
# Scenario constants (single source of truth, mirrors p1_184.py)
# ---------------------------------------------------------------------------

_LOAN_RATED = "L_MDB_RATED"  # rated non-named MDB, institution_cqs=2
_LOAN_UNRATED_SOV1 = "L_MDB_UNRATED_SOV1"  # unrated non-named MDB, sovereign_cqs=1
_LOAN_UNRATED_NOSOV = "L_MDB_UNRATED_NOSOV"  # unrated non-named MDB, no sovereign
_LOAN_NAMED = "L_MDB_NAMED"  # named MDB (entity_type=mdb_named)

# Tolerances
_RW_TOL = 1e-6  # absolute on risk_weight
_RWA_TOL = 0.50  # £0.50 absolute on rwa_final (covers FX rounding)

# ---------------------------------------------------------------------------
# CRR after-fix expected values (Art. 117(1) → institution tables)
# ---------------------------------------------------------------------------

# L_MDB_RATED: Art. 120 Table 3, CQS 2 = 50%
# EAD = 1,000,000 KES × 1.0 KES/GBP = 1,000,000 GBP
_CRR_RW_RATED = 0.50
_CRR_RWA_RATED = 500_000.0

# L_MDB_UNRATED_SOV1: Art. 121 Table 5, sovereign CQS 1 = 20%
# EAD = 1,000,000 HNL × 1.0 HNL/GBP = 1,000,000 GBP
_CRR_RW_UNRATED_SOV1 = 0.20
_CRR_RWA_UNRATED_SOV1 = 200_000.0

# L_MDB_UNRATED_NOSOV: Art. 121 fallback (no sovereign CQS) = 100%
# EAD = 1,000,000 USD × 0.79 USD/GBP = 790,000 GBP
_CRR_RW_UNRATED_NOSOV = 1.00
_CRR_RWA_UNRATED_NOSOV = 790_000.0

# L_MDB_NAMED: Art. 117(2) named MDB = 0%
_CRR_RW_NAMED = 0.00
_CRR_RWA_NAMED = 0.0

# ---------------------------------------------------------------------------
# Basel 3.1 regression expected values (PRA PS1/26 Art. 117(1)(a) Table 2B)
# ---------------------------------------------------------------------------

# L_MDB_RATED: Table 2B CQS 2 = 30%
# EAD = 1,000,000 GBP
_B31_RW_RATED = 0.30
_B31_RWA_RATED = 300_000.0

# L_MDB_UNRATED_SOV1: Table 2B unrated row = 50% (sovereign_cqs does NOT override MDB path)
# EAD = 1,000,000 GBP
_B31_RW_UNRATED_SOV1 = 0.50
_B31_RWA_UNRATED_SOV1 = 500_000.0

# L_MDB_UNRATED_NOSOV: Table 2B unrated row = 50%
# EAD = 790,000 GBP
_B31_RW_UNRATED_NOSOV = 0.50
_B31_RWA_UNRATED_NOSOV = 395_000.0

# L_MDB_NAMED: Art. 117(2) named MDB = 0%
_B31_RW_NAMED = 0.00
_B31_RWA_NAMED = 0.0

# ---------------------------------------------------------------------------
# Pre-fix sentinel (what the engine currently returns for CRR)
# — identical to the Basel 3.1 Table 2B path, since the bug routes CRR through Table 2B
# ---------------------------------------------------------------------------

_BUGGY_CRR_RW_RATED = 0.30  # Table 2B CQS 2 (wrong for CRR; should be 0.50)
_BUGGY_CRR_RWA_RATED = 300_000.0
_BUGGY_CRR_RW_UNRATED_SOV1 = 0.50  # Table 2B unrated (wrong for CRR; should be 0.20)
_BUGGY_CRR_RWA_UNRATED_SOV1 = 500_000.0
_BUGGY_CRR_RW_UNRATED_NOSOV = 0.50  # Table 2B unrated (wrong for CRR; should be 1.00)
_BUGGY_CRR_RWA_UNRATED_NOSOV = 395_000.0


# ---------------------------------------------------------------------------
# Shared bundle builder
# ---------------------------------------------------------------------------


def _build_bundle() -> RawDataBundle:
    """
    Load the P1.184 scenario parquets and assemble a RawDataBundle.

    Uses the per-fixture fx_rates.parquet which pins:
      KES/GBP = 1.0, HNL/GBP = 1.0, USD/GBP = 0.79, GBP/GBP = 1.0.

    No facilities, collateral, guarantees, ratings or other optional tables —
    this is a pure SA scenario.
    """
    counterparties = pl.scan_parquet(_FIXTURES_DIR / "counterparty.parquet")
    loans = pl.scan_parquet(_FIXTURES_DIR / "loan.parquet")
    fx_rates = pl.scan_parquet(_FIXTURES_DIR / "fx_rates.parquet")

    return make_raw_bundle(
        facilities=pl.LazyFrame(
            schema={"facility_reference": pl.String, "counterparty_reference": pl.String}
        ),
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
        fx_rates=fx_rates,
    )


def _extract_row(sa_results: pl.LazyFrame, loan_ref: str) -> dict:
    """
    Filter SA results to a single row for loan_ref and return as a dict.

    Asserts exactly one row is found — the pipeline must not drop or duplicate
    MDB rows.
    """
    df = sa_results.filter(pl.col("exposure_reference") == loan_ref).collect()
    assert len(df) == 1, (
        f"P1.184: expected exactly 1 SA row for {loan_ref}, got {len(df)}. "
        f"Pipeline may have dropped or split the MDB exposure."
    )
    return df.to_dicts()[0]


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def p1_184_crr_results() -> dict[str, dict]:
    """
    Run the P1.184 fixtures through the CRR SA pipeline once.

    Returns a mapping of loan_reference -> result row dict for all four
    MDB loans. Module-scoped to avoid repeated pipeline runs.

    Pre-fix: the engine routes all non-named MDB exposures through Table 2B
    (CQS 2 = 30%, unrated = 50%) even under CRR.
    Post-fix: non-named MDBs must use institution tables (CRR Art. 120/121).
    """
    # Arrange
    bundle = _build_bundle()
    config = CalculationConfig.crr(
        reporting_date=date(2026, 6, 30),
        permission_mode=PermissionMode.STANDARDISED,
    )

    # Act
    results = PipelineOrchestrator().run_with_data(bundle, config)

    assert results.sa_results is not None, (
        "P1.184 CRR: SA results should not be None for SA-only config"
    )

    # Extract one dict per loan reference
    sa_lf = results.sa_results
    return {
        loan_ref: _extract_row(sa_lf, loan_ref)
        for loan_ref in (_LOAN_RATED, _LOAN_UNRATED_SOV1, _LOAN_UNRATED_NOSOV, _LOAN_NAMED)
    }


@pytest.fixture(scope="module")
def p1_184_b31_results() -> dict[str, dict]:
    """
    Run the P1.184 fixtures through the Basel 3.1 SA pipeline once.

    Returns a mapping of loan_reference -> result row dict for all four
    MDB loans. Module-scoped to avoid repeated pipeline runs.

    This is the regression guard — Basel 3.1 must continue to route non-named
    MDBs through Table 2B (PRA PS1/26 Art. 117(1)(a)).
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
        "P1.184 B3.1: SA results should not be None for SA-only config"
    )

    # Extract one dict per loan reference
    sa_lf = results.sa_results
    return {
        loan_ref: _extract_row(sa_lf, loan_ref)
        for loan_ref in (_LOAN_RATED, _LOAN_UNRATED_SOV1, _LOAN_UNRATED_NOSOV, _LOAN_NAMED)
    }


# ---------------------------------------------------------------------------
# CRR tests — assert Art. 117(1) institution-table routing (after fix)
# ---------------------------------------------------------------------------


class TestCRRMDBNonNamedUsesInstitutionTable:
    """
    P1.184 — CRR Art. 117(1): non-named MDB exposures must use institution
    risk-weight tables (Art. 120 Table 3 for rated, Art. 121 Table 5 for
    unrated sovereign-derived), not the Basel 3.1 dedicated Table 2B.

    Pre-fix failures (engine routes CRR through Table 2B):
      L_MDB_RATED:          rw=0.30 (wrong), should be 0.50
      L_MDB_UNRATED_SOV1:   rw=0.50 (wrong), should be 0.20
      L_MDB_UNRATED_NOSOV:  rw=0.50 (wrong), should be 1.00
    """

    # ------------------------------------------------------------------
    # L_MDB_RATED — rated non-named MDB, institution_cqs=2
    # ------------------------------------------------------------------

    def test_crr_mdb_rated_cqs2_risk_weight(self, p1_184_crr_results: dict[str, dict]) -> None:
        """
        Rated non-named MDB (CQS 2) must receive 50% RW under CRR Art. 120 Table 3.

        Art. 117(1): non-named MDB → institution treatment.
        Art. 120 Table 3: institution CQS 2 → 50%.

        Pre-fix (Table 2B): risk_weight = 0.30 (Basel 3.1 CQS 2 value, wrong for CRR).

        Arrange: L_MDB_RATED, institution_cqs=2, EAD=1,000,000 GBP.
        Act:     full CRR SA pipeline.
        Assert:  risk_weight == 0.50.
        """
        # Arrange
        row = p1_184_crr_results[_LOAN_RATED]

        # Assert
        assert row["risk_weight"] == pytest.approx(_CRR_RW_RATED, abs=_RW_TOL), (
            f"P1.184 CRR L_MDB_RATED: expected risk_weight={_CRR_RW_RATED} "
            f"(CRR Art. 120 Table 3, institution CQS 2 = 50%), "
            f"got {row['risk_weight']} "
            f"(pre-fix Table 2B gives {_BUGGY_CRR_RW_RATED})"
        )

    def test_crr_mdb_rated_cqs2_rwa(self, p1_184_crr_results: dict[str, dict]) -> None:
        """
        RWA for rated non-named MDB = EAD × 50% = 500,000.

        Arrange: L_MDB_RATED, EAD=1,000,000 GBP (KES 1m × FX 1.0), RW=50%.
        Act:     full CRR SA pipeline.
        Assert:  rwa_final == 500,000 ± £0.50.

        Pre-fix (Table 2B CQS 2 = 30%): rwa_final = 300,000.
        """
        # Arrange
        row = p1_184_crr_results[_LOAN_RATED]

        # Assert
        assert row["rwa_final"] == pytest.approx(_CRR_RWA_RATED, abs=_RWA_TOL), (
            f"P1.184 CRR L_MDB_RATED: expected rwa_final={_CRR_RWA_RATED:,.0f} "
            f"(EAD 1,000,000 × 50%), "
            f"got {row['rwa_final']:,.2f} "
            f"(pre-fix Table 2B: {_BUGGY_CRR_RWA_RATED:,.0f})"
        )

    # ------------------------------------------------------------------
    # L_MDB_UNRATED_SOV1 — unrated non-named MDB, sovereign_cqs=1
    # ------------------------------------------------------------------

    def test_crr_mdb_unrated_sov1_risk_weight(self, p1_184_crr_results: dict[str, dict]) -> None:
        """
        Unrated non-named MDB with sovereign CQS 1 must receive 20% via Art. 121 Table 5.

        Art. 117(1): non-named MDB → institution treatment.
        Art. 121 Table 5: sovereign CQS 1 → 20% (sovereign-derived unrated institution).

        Pre-fix (Table 2B unrated = 50%): risk_weight = 0.50 (flat, ignores sovereign CQS).

        Arrange: L_MDB_UNRATED_SOV1, no institution_cqs, sovereign_cqs=1.
        Act:     full CRR SA pipeline.
        Assert:  risk_weight == 0.20.
        """
        # Arrange
        row = p1_184_crr_results[_LOAN_UNRATED_SOV1]

        # Assert
        assert row["risk_weight"] == pytest.approx(_CRR_RW_UNRATED_SOV1, abs=_RW_TOL), (
            f"P1.184 CRR L_MDB_UNRATED_SOV1: expected risk_weight={_CRR_RW_UNRATED_SOV1} "
            f"(CRR Art. 121 Table 5, sovereign CQS 1 → 20%), "
            f"got {row['risk_weight']} "
            f"(pre-fix Table 2B unrated gives {_BUGGY_CRR_RW_UNRATED_SOV1})"
        )

    def test_crr_mdb_unrated_sov1_rwa(self, p1_184_crr_results: dict[str, dict]) -> None:
        """
        RWA for unrated non-named MDB (sovereign CQS 1) = EAD × 20% = 200,000.

        Arrange: L_MDB_UNRATED_SOV1, EAD=1,000,000 GBP (HNL 1m × FX 1.0), RW=20%.
        Act:     full CRR SA pipeline.
        Assert:  rwa_final == 200,000 ± £0.50.

        Pre-fix (Table 2B unrated = 50%): rwa_final = 500,000.
        """
        # Arrange
        row = p1_184_crr_results[_LOAN_UNRATED_SOV1]

        # Assert
        assert row["rwa_final"] == pytest.approx(_CRR_RWA_UNRATED_SOV1, abs=_RWA_TOL), (
            f"P1.184 CRR L_MDB_UNRATED_SOV1: expected rwa_final={_CRR_RWA_UNRATED_SOV1:,.0f} "
            f"(EAD 1,000,000 × 20%), "
            f"got {row['rwa_final']:,.2f} "
            f"(pre-fix Table 2B unrated: {_BUGGY_CRR_RWA_UNRATED_SOV1:,.0f})"
        )

    # ------------------------------------------------------------------
    # L_MDB_UNRATED_NOSOV — unrated non-named MDB, no sovereign CQS
    # ------------------------------------------------------------------

    def test_crr_mdb_unrated_nosov_risk_weight(self, p1_184_crr_results: dict[str, dict]) -> None:
        """
        Unrated non-named MDB with no sovereign CQS must receive 100% (Art. 120 unrated fallback).

        Art. 117(1): non-named MDB → institution treatment.
        Art. 120 / Art. 121: when no sovereign CQS is available, unrated institution → 100%.

        Pre-fix (Table 2B unrated = 50%): risk_weight = 0.50.

        Arrange: L_MDB_UNRATED_NOSOV, no institution_cqs, no sovereign_cqs.
        Act:     full CRR SA pipeline.
        Assert:  risk_weight == 1.00.
        """
        # Arrange
        row = p1_184_crr_results[_LOAN_UNRATED_NOSOV]

        # Assert
        assert row["risk_weight"] == pytest.approx(_CRR_RW_UNRATED_NOSOV, abs=_RW_TOL), (
            f"P1.184 CRR L_MDB_UNRATED_NOSOV: expected risk_weight={_CRR_RW_UNRATED_NOSOV} "
            f"(CRR Art. 120 unrated fallback = 100%), "
            f"got {row['risk_weight']} "
            f"(pre-fix Table 2B unrated gives {_BUGGY_CRR_RW_UNRATED_NOSOV})"
        )

    def test_crr_mdb_unrated_nosov_rwa(self, p1_184_crr_results: dict[str, dict]) -> None:
        """
        RWA for unrated non-named MDB (no sovereign) = EAD × 100% = 790,000.

        FX: 1,000,000 USD × 0.79 USD/GBP = 790,000 GBP.
        RWA = 790,000 × 1.00 = 790,000.

        Arrange: L_MDB_UNRATED_NOSOV, EAD=790,000 GBP (USD 1m × FX 0.79), RW=100%.
        Act:     full CRR SA pipeline.
        Assert:  rwa_final == 790,000 ± £0.50.

        Pre-fix (Table 2B unrated = 50%): rwa_final = 395,000.
        """
        # Arrange
        row = p1_184_crr_results[_LOAN_UNRATED_NOSOV]

        # Assert
        assert row["rwa_final"] == pytest.approx(_CRR_RWA_UNRATED_NOSOV, abs=_RWA_TOL), (
            f"P1.184 CRR L_MDB_UNRATED_NOSOV: expected rwa_final={_CRR_RWA_UNRATED_NOSOV:,.0f} "
            f"(EAD 790,000 GBP × 100%), "
            f"got {row['rwa_final']:,.2f} "
            f"(pre-fix Table 2B unrated: {_BUGGY_CRR_RWA_UNRATED_NOSOV:,.0f})"
        )

    # ------------------------------------------------------------------
    # L_MDB_NAMED — named MDB (entity_type=mdb_named), CRR
    # ------------------------------------------------------------------

    def test_crr_named_mdb_zero_risk_weight(self, p1_184_crr_results: dict[str, dict]) -> None:
        """
        Named MDB (entity_type='mdb_named') must receive 0% RW under CRR Art. 117(2).

        Art. 117(2): named MDB list → 0% unconditional (institution_cqs=1 is irrelevant).

        Arrange: L_MDB_NAMED, entity_type=mdb_named, institution_cqs=1, EAD=1,000,000 GBP.
        Act:     full CRR SA pipeline.
        Assert:  risk_weight == 0.00 and rwa_final == 0.
        """
        # Arrange
        row = p1_184_crr_results[_LOAN_NAMED]

        # Assert — both risk_weight and rwa_final
        assert row["risk_weight"] == pytest.approx(_CRR_RW_NAMED, abs=_RW_TOL), (
            f"P1.184 CRR L_MDB_NAMED: expected risk_weight=0.00 "
            f"(CRR Art. 117(2) named MDB → 0%), got {row['risk_weight']}"
        )
        assert row["rwa_final"] == pytest.approx(_CRR_RWA_NAMED, abs=_RWA_TOL), (
            f"P1.184 CRR L_MDB_NAMED: expected rwa_final=0, got {row['rwa_final']}"
        )


# ---------------------------------------------------------------------------
# Basel 3.1 regression tests — Table 2B must remain intact after CRR fix
# ---------------------------------------------------------------------------


class TestB31MDBTable2BUnchanged:
    """
    P1.184 regression guard — Basel 3.1 Art. 117(1)(a): non-named MDB exposures
    must continue to use the dedicated Table 2B (CQS 2 = 30%, unrated = 50%)
    after the CRR institution-routing fix is applied.

    If the engine-implementer's fix incorrectly changes the B3.1 path, these
    tests will catch the regression.
    """

    # ------------------------------------------------------------------
    # L_MDB_RATED — rated non-named MDB, Table 2B CQS 2 = 30%
    # ------------------------------------------------------------------

    def test_b31_mdb_rated_cqs2_risk_weight(self, p1_184_b31_results: dict[str, dict]) -> None:
        """
        B3.1: rated non-named MDB (CQS 2) → Table 2B = 30%.

        PRA PS1/26 Art. 117(1)(a): dedicated MDB Table 2B, CQS 2 = 30%.

        Arrange: L_MDB_RATED, institution_cqs=2, EAD=1,000,000 GBP.
        Act:     full Basel 3.1 SA pipeline.
        Assert:  risk_weight == 0.30.
        """
        # Arrange
        row = p1_184_b31_results[_LOAN_RATED]

        # Assert
        assert row["risk_weight"] == pytest.approx(_B31_RW_RATED, abs=_RW_TOL), (
            f"P1.184 B3.1 L_MDB_RATED: expected risk_weight={_B31_RW_RATED} "
            f"(PRA PS1/26 Art. 117(1)(a) Table 2B, CQS 2 = 30%), "
            f"got {row['risk_weight']}"
        )

    def test_b31_mdb_rated_cqs2_rwa(self, p1_184_b31_results: dict[str, dict]) -> None:
        """
        B3.1: RWA for rated non-named MDB = EAD × 30% = 300,000.

        Arrange: L_MDB_RATED, EAD=1,000,000 GBP, RW=30%.
        Act:     full Basel 3.1 SA pipeline.
        Assert:  rwa_final == 300,000 ± £0.50.
        """
        # Arrange
        row = p1_184_b31_results[_LOAN_RATED]

        # Assert
        assert row["rwa_final"] == pytest.approx(_B31_RWA_RATED, abs=_RWA_TOL), (
            f"P1.184 B3.1 L_MDB_RATED: expected rwa_final={_B31_RWA_RATED:,.0f}, "
            f"got {row['rwa_final']:,.2f}"
        )

    # ------------------------------------------------------------------
    # L_MDB_UNRATED_SOV1 — unrated, Table 2B flat 50% (sov CQS ignored)
    # ------------------------------------------------------------------

    def test_b31_mdb_unrated_sov1_risk_weight(self, p1_184_b31_results: dict[str, dict]) -> None:
        """
        B3.1: unrated non-named MDB with sovereign CQS 1 → Table 2B unrated = 50%.

        Under B3.1, sovereign CQS does NOT modify the MDB unrated path —
        Table 2B has a single flat row for all unrated non-named MDBs.

        Arrange: L_MDB_UNRATED_SOV1, no institution_cqs, sovereign_cqs=1.
        Act:     full Basel 3.1 SA pipeline.
        Assert:  risk_weight == 0.50.
        """
        # Arrange
        row = p1_184_b31_results[_LOAN_UNRATED_SOV1]

        # Assert
        assert row["risk_weight"] == pytest.approx(_B31_RW_UNRATED_SOV1, abs=_RW_TOL), (
            f"P1.184 B3.1 L_MDB_UNRATED_SOV1: expected risk_weight={_B31_RW_UNRATED_SOV1} "
            f"(Table 2B unrated = 50%, sovereign_cqs not used for B3.1 MDB), "
            f"got {row['risk_weight']}"
        )

    def test_b31_mdb_unrated_sov1_rwa(self, p1_184_b31_results: dict[str, dict]) -> None:
        """
        B3.1: RWA for unrated non-named MDB (sov CQS 1) = EAD × 50% = 500,000.

        Arrange: L_MDB_UNRATED_SOV1, EAD=1,000,000 GBP, RW=50%.
        Act:     full Basel 3.1 SA pipeline.
        Assert:  rwa_final == 500,000 ± £0.50.
        """
        # Arrange
        row = p1_184_b31_results[_LOAN_UNRATED_SOV1]

        # Assert
        assert row["rwa_final"] == pytest.approx(_B31_RWA_UNRATED_SOV1, abs=_RWA_TOL), (
            f"P1.184 B3.1 L_MDB_UNRATED_SOV1: expected rwa_final={_B31_RWA_UNRATED_SOV1:,.0f}, "
            f"got {row['rwa_final']:,.2f}"
        )

    # ------------------------------------------------------------------
    # L_MDB_UNRATED_NOSOV — unrated, Table 2B flat 50%
    # ------------------------------------------------------------------

    def test_b31_mdb_unrated_nosov_risk_weight(self, p1_184_b31_results: dict[str, dict]) -> None:
        """
        B3.1: unrated non-named MDB with no sovereign CQS → Table 2B unrated = 50%.

        Arrange: L_MDB_UNRATED_NOSOV, no institution_cqs, no sovereign_cqs.
        Act:     full Basel 3.1 SA pipeline.
        Assert:  risk_weight == 0.50.
        """
        # Arrange
        row = p1_184_b31_results[_LOAN_UNRATED_NOSOV]

        # Assert
        assert row["risk_weight"] == pytest.approx(_B31_RW_UNRATED_NOSOV, abs=_RW_TOL), (
            f"P1.184 B3.1 L_MDB_UNRATED_NOSOV: expected risk_weight={_B31_RW_UNRATED_NOSOV} "
            f"(Table 2B unrated = 50%), got {row['risk_weight']}"
        )

    def test_b31_mdb_unrated_nosov_rwa(self, p1_184_b31_results: dict[str, dict]) -> None:
        """
        B3.1: RWA for unrated non-named MDB (no sov) = EAD × 50% = 395,000.

        FX: 1,000,000 USD × 0.79 = 790,000 GBP × 50% = 395,000.

        Arrange: L_MDB_UNRATED_NOSOV, EAD=790,000 GBP, RW=50%.
        Act:     full Basel 3.1 SA pipeline.
        Assert:  rwa_final == 395,000 ± £0.50.
        """
        # Arrange
        row = p1_184_b31_results[_LOAN_UNRATED_NOSOV]

        # Assert
        assert row["rwa_final"] == pytest.approx(_B31_RWA_UNRATED_NOSOV, abs=_RWA_TOL), (
            f"P1.184 B3.1 L_MDB_UNRATED_NOSOV: expected rwa_final={_B31_RWA_UNRATED_NOSOV:,.0f} "
            f"(EAD 790,000 × 50%), got {row['rwa_final']:,.2f}"
        )

    # ------------------------------------------------------------------
    # L_MDB_NAMED — named MDB, Basel 3.1
    # ------------------------------------------------------------------

    def test_b31_named_mdb_zero_risk_weight(self, p1_184_b31_results: dict[str, dict]) -> None:
        """
        B3.1: named MDB → 0% unconditional (same as CRR).

        Arrange: L_MDB_NAMED, entity_type=mdb_named, EAD=1,000,000 GBP.
        Act:     full Basel 3.1 SA pipeline.
        Assert:  risk_weight == 0.00 and rwa_final == 0.
        """
        # Arrange
        row = p1_184_b31_results[_LOAN_NAMED]

        # Assert
        assert row["risk_weight"] == pytest.approx(_B31_RW_NAMED, abs=_RW_TOL), (
            f"P1.184 B3.1 L_MDB_NAMED: expected risk_weight=0.00, got {row['risk_weight']}"
        )
        assert row["rwa_final"] == pytest.approx(_B31_RWA_NAMED, abs=_RWA_TOL), (
            f"P1.184 B3.1 L_MDB_NAMED: expected rwa_final=0, got {row['rwa_final']}"
        )
