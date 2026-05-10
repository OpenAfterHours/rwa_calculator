"""
P1.154-B31 — Basel 3.1 Art. 118 IO discriminator vs Art. 117(1)(a) Table 2B MDB.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> SACalculator -> Aggregator

Key assertions:
- CP_IO_IMF_B31 (entity_type="international_org") must be classified as
  "international_organisation" and receive 0% unconditional RW (Art. 118).
- CP_MDB_NN_B31 (entity_type="mdb", CQS 2) must be classified as "mdb" and
  receive 30% RW from B31 Art. 117(1)(a) Table 2B — not the 50% that CRR
  Art. 117(1) institution ECRA CQS 2 (>3m) would give.

Hand-calculations (Basel 3.1, CalculationConfig.basel_3_1(),
                  reporting_date=2027-06-30, PermissionMode.STANDARDISED):

  FAC_IO_IMF_B31_001_UNDRAWN (CP_IO_IMF_B31, entity_type="international_org"):
    Exposure class: INTERNATIONAL_ORGANISATION (Art. 112(1)(e), Art. 118)
    Risk weight (Art. 118): 0% unconditional — no CQS lookup, no rating needed
    EAD: USD 100,000,000 (face value, no FX conversion without fx_rates table)
    RWA: 100,000,000 × 0.00 = 0

  FAC_MDB_NN_B31_001_UNDRAWN (CP_MDB_NN_B31, entity_type="mdb", CQS 2):
    Exposure class: MDB (Art. 117)
    CQS: 2 (from RATING_MDB_NN_B31_CQS2, Moody's Aa3)
    Risk weight (Art. 117(1)(a) Table 2B, CQS 2): 30%
    EAD: EUR 50,000,000 (face value, no FX conversion without fx_rates table)
    RWA: 50,000,000 × 0.30 = 15,000,000

Discriminator vs CRR:
    Under CRR Art. 117(1), non-named MBDs are treated as institutions, so
    CQS 2 > 3m maturity → ECRA Table 3 → 50%.  Under B31 Art. 117(1)(a),
    a dedicated Table 2B applies directly to MDB CQS → CQS 2 = 30%.
    The 30% vs 50% gap is the load-bearing B31 discriminator for P1.154-B31.

Pre-fix failure mode (engine-implementer gap):
    The B31 override chain in engine/sa/namespace.py handles:
      - International Organisation → 0% (line ~1094)
      - Named MDB → 0% (line ~1097)
      - Unrated non-named MDB → 50% (line ~1100)
    But there is NO branch for a RATED non-named MDB using Table 2B.
    CP_MDB_NN_B31 with CQS 2 therefore falls through without a B31-specific
    override, and the risk_weight returned will NOT be 0.30.

References:
    - PRA PS1/26 Art. 118: named international organisations → 0% SA RW
    - PRA PS1/26 Art. 117(1)(a) Table 2B: B31 MDB RW by own CQS (CQS 2 = 30%)
    - src/rwa_calc/data/tables/crr_risk_weights.py: MDB_RISK_WEIGHTS_TABLE_2B
    - src/rwa_calc/engine/sa/namespace.py: _apply_b31_risk_weight_overrides
    - tests/fixtures/p1_154_b31/p1_154_b31.py: scenario constants
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest
from tests.fixtures.p1_154_b31.p1_154_b31 import (
    EXPECTED_RW_INTERNATIONAL_ORG,
    EXPECTED_RW_MDB_CQS2_B31,
    FAC_IO_IMF_B31_001,
    FAC_MDB_NN_B31_001,
    IMF_LIMIT,
    MDB_LIMIT,
)

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import LOAN_SCHEMA
from rwa_calc.engine.pipeline import PipelineOrchestrator

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_154_b31" / "data"

# ---------------------------------------------------------------------------
# Scenario constants (mirrored from p1_154_b31.py)
# ---------------------------------------------------------------------------

# The engine generates an _UNDRAWN suffix for undrawn facility exposures.
_IMF_EXPOSURE_REF = f"{FAC_IO_IMF_B31_001}_UNDRAWN"
_MDB_EXPOSURE_REF = f"{FAC_MDB_NN_B31_001}_UNDRAWN"

# Post-fix expected exposure classes
_EXPECTED_CLASS_IMF = "international_organisation"
_EXPECTED_CLASS_MDB = "mdb"

# Post-fix expected risk weights (from p1_154_b31.py exports)
_EXPECTED_RW_IMF = EXPECTED_RW_INTERNATIONAL_ORG  # 0.00 — Art. 118 unconditional
_EXPECTED_RW_MDB = EXPECTED_RW_MDB_CQS2_B31  # 0.30 — Table 2B CQS 2

# Post-fix expected RWA (face-value EAD, no FX — no fx_rates table in bundle)
_EXPECTED_RWA_IMF = 0.0  # 100m × 0.00 = 0
_EXPECTED_RWA_MDB = 15_000_000.0  # 50m × 0.30 = 15m

# Post-fix expected EAD (face-value, no FX conversion without fx_rates table)
_EXPECTED_EAD_IMF = IMF_LIMIT  # USD 100,000,000 (no conversion)
_EXPECTED_EAD_MDB = MDB_LIMIT  # EUR 50,000,000 (no conversion)

# Tolerances
_RW_TOL = 1e-6  # absolute on risk_weight
_AMT_TOL = 0.50  # £0.50 absolute on rwa_final / ead_final


# ---------------------------------------------------------------------------
# Bundle builder
# ---------------------------------------------------------------------------


def _build_bundle() -> RawDataBundle:
    """
    Load P1.154-B31 scenario parquets and assemble a RawDataBundle.

    No fx_rates table: all EAD amounts remain in original currency (face value).
    No loans — both exposures are facility-only (committed, full_risk). The
    pipeline treats these as off-balance-sheet commitments and generates
    *_UNDRAWN rows.

    Ratings include CQS 2 for the MDB counterparty only. IMF has no rating
    row — Art. 118 assigns 0% unconditionally, bypassing CQS lookup.
    """
    counterparties = pl.scan_parquet(_FIXTURES_DIR / "counterparties.parquet")
    facilities = pl.scan_parquet(_FIXTURES_DIR / "facilities.parquet")
    ratings = pl.scan_parquet(_FIXTURES_DIR / "ratings.parquet")

    return RawDataBundle(
        facilities=facilities,
        loans=pl.LazyFrame(schema=dtypes_of(LOAN_SCHEMA)),
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
        ratings=ratings,
    )


def _extract_row(sa_results: pl.LazyFrame, exposure_ref: str) -> dict:
    """
    Filter SA results to a single row for exposure_ref and return as a dict.

    Asserts exactly one row is found — the pipeline must not drop or duplicate
    the exposure.
    """
    df = sa_results.filter(pl.col("exposure_reference") == exposure_ref).collect()
    assert len(df) == 1, (
        f"P1.154-B31: expected exactly 1 SA row for {exposure_ref}, got {len(df)}. "
        f"Pipeline may have dropped or duplicated the exposure."
    )
    return df.to_dicts()[0]


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def p1_154_b31_results() -> dict[str, dict]:
    """
    Run the P1.154-B31 fixtures through the Basel 3.1 SA pipeline once.

    Returns a mapping of exposure_reference -> result row dict for both
    exposures. Module-scoped to avoid repeated pipeline runs.

    Pre-fix: CP_MDB_NN_B31 (rated non-named MDB, CQS 2) falls through the
    B31 override chain without a Table 2B lookup, returning a risk weight
    != 0.30.

    Post-fix: The B31 override chain must include a rated non-named MDB
    branch that looks up Table 2B for CQS -> RW (CQS 2 = 30%).

    CP_IO_IMF_B31 should already pass (IO -> 0% is implemented), but the
    test verifies both exposures for completeness.
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
        "P1.154-B31: SA results should not be None for SA-only standardised config"
    )

    sa_lf = results.sa_results
    return {
        exposure_ref: _extract_row(sa_lf, exposure_ref)
        for exposure_ref in (_IMF_EXPOSURE_REF, _MDB_EXPOSURE_REF)
    }


# ---------------------------------------------------------------------------
# P1.154-B31: IMF (named international organisation, Art. 118) — should pass
# ---------------------------------------------------------------------------


class TestIMFInternationalOrganisationB31:
    """
    P1.154-B31 — B31 Art. 118: IMF (entity_type='international_org') must be
    classified as 'international_organisation' and receive 0% unconditional RW.

    This class is the control group — ExposureClass.INTERNATIONAL_ORGANISATION
    and IO_ZERO_RW are already implemented, so these assertions should pass
    even before the engine-implementer fix for P1.154-B31. They are included
    to confirm the Art. 118 path is intact under Basel 3.1 config.
    """

    def test_p1_154_b31_international_organisation_zero_rw_vs_mdb_table_2b(
        self, p1_154_b31_results: dict[str, dict]
    ) -> None:
        """
        Full scenario assertion: IO at 0%, MDB at 30% (Table 2B CQS 2).

        This is the single test function named per the scenario spec. It
        asserts both rows together to confirm the B31 discriminator holds:
        IO (Art. 118) = 0% unconditional, non-named MDB (Art. 117(1)(a)
        Table 2B, CQS 2) = 30%.

        Arrange: two-counterparty bundle with B31 config (2027-06-30, SA).
        Act:     full Basel 3.1 SA pipeline.
        Assert:
          IMF  — exposure_class="international_organisation", RW=0.00, RWA=0
          MDB  — exposure_class="mdb", CQS=2, RW=0.30, RWA=15,000,000
        """
        # Arrange
        imf_row = p1_154_b31_results[_IMF_EXPOSURE_REF]
        mdb_row = p1_154_b31_results[_MDB_EXPOSURE_REF]

        # Assert — IMF (Art. 118, unconditional 0%)
        assert imf_row["exposure_class"] == _EXPECTED_CLASS_IMF, (
            f"P1.154-B31 Art. 118: expected exposure_class='international_organisation', "
            f"got '{imf_row['exposure_class']}'"
        )
        assert imf_row["approach_applied"] == "standardised", (
            f"P1.154-B31: expected approach_applied='standardised', "
            f"got '{imf_row['approach_applied']}'"
        )
        assert imf_row["risk_weight"] == pytest.approx(_EXPECTED_RW_IMF, abs=_RW_TOL), (
            f"P1.154-B31 Art. 118: expected risk_weight=0.00, got {imf_row['risk_weight']}"
        )
        assert imf_row["ead_final"] == pytest.approx(_EXPECTED_EAD_IMF, abs=_AMT_TOL), (
            f"P1.154-B31 Art. 118: expected ead_final={_EXPECTED_EAD_IMF:,.0f}, "
            f"got {imf_row['ead_final']:,.2f}"
        )
        assert imf_row["rwa_final"] == pytest.approx(_EXPECTED_RWA_IMF, abs=_AMT_TOL), (
            f"P1.154-B31 Art. 118: expected rwa_final=0.00, got {imf_row['rwa_final']}"
        )

        # Assert — non-named MDB (Art. 117(1)(a) Table 2B, CQS 2 = 30%)
        assert mdb_row["exposure_class"] == _EXPECTED_CLASS_MDB, (
            f"P1.154-B31 Art. 117(1)(a): expected exposure_class='mdb', "
            f"got '{mdb_row['exposure_class']}'"
        )
        assert mdb_row["approach_applied"] == "standardised", (
            f"P1.154-B31: expected approach_applied='standardised', "
            f"got '{mdb_row['approach_applied']}'"
        )
        assert mdb_row["risk_weight"] == pytest.approx(_EXPECTED_RW_MDB, abs=_RW_TOL), (
            f"P1.154-B31 Art. 117(1)(a) Table 2B: expected risk_weight=0.30 "
            f"(CQS 2 → 30% under B31 Table 2B; CRR institution ECRA CQS 2 >3m = 50%). "
            f"got {mdb_row['risk_weight']}. "
            f"Fix: add rated non-named MDB branch to _apply_b31_risk_weight_overrides "
            f"in engine/sa/namespace.py using MDB_RISK_WEIGHTS_TABLE_2B."
        )
        assert mdb_row["ead_final"] == pytest.approx(_EXPECTED_EAD_MDB, abs=_AMT_TOL), (
            f"P1.154-B31 Art. 117(1)(a): expected ead_final={_EXPECTED_EAD_MDB:,.0f}, "
            f"got {mdb_row['ead_final']:,.2f}"
        )
        assert mdb_row["rwa_final"] == pytest.approx(_EXPECTED_RWA_MDB, abs=_AMT_TOL), (
            f"P1.154-B31 Art. 117(1)(a) Table 2B: expected rwa_final={_EXPECTED_RWA_MDB:,.0f} "
            f"(EAD 50,000,000 × 30%), got {mdb_row['rwa_final']:,.2f}"
        )


# ---------------------------------------------------------------------------
# Granular MDB Table 2B tests — one assertion per concept
# ---------------------------------------------------------------------------


class TestMDBTable2BB31:
    """
    P1.154-B31 — B31 Art. 117(1)(a) Table 2B: non-named MDB CQS 2 → 30%.

    The load-bearing failure before the engine fix: the B31 override chain
    in namespace.py handles unrated MDB (50%) but has no branch for a rated
    MDB — the Table 2B lookup (CQS 2 = 30%) is missing.

    Pre-fix: risk_weight for the rated MDB will not be 0.30. The exact
    fallback value depends on the chain ordering, but it will not be the
    correct B31 value.
    """

    def test_p1_154_b31_mdb_exposure_class_is_mdb(
        self, p1_154_b31_results: dict[str, dict]
    ) -> None:
        """
        Non-named MDB (entity_type='mdb') must be classified as 'mdb'.

        Arrange: FAC_MDB_NN_B31_001_UNDRAWN, entity_type='mdb'.
        Act:     full Basel 3.1 SA pipeline.
        Assert:  exposure_class == "mdb".
        """
        # Arrange
        row = p1_154_b31_results[_MDB_EXPOSURE_REF]

        # Assert
        assert row["exposure_class"] == _EXPECTED_CLASS_MDB, (
            f"P1.154-B31: expected exposure_class='mdb', got '{row['exposure_class']}'"
        )

    def test_p1_154_b31_mdb_risk_weight_table_2b_cqs2(
        self, p1_154_b31_results: dict[str, dict]
    ) -> None:
        """
        Non-named MDB with CQS 2 must receive 30% RW (B31 Art. 117(1)(a) Table 2B).

        The B31 discriminator vs CRR: CRR Art. 117(1) routes non-named MDBs
        through institution ECRA tables → CQS 2 >3m = 50%.  B31 Art. 117(1)(a)
        uses a dedicated Table 2B → CQS 2 = 30%.

        Pre-fix failure: the B31 override chain has no rated non-named MDB branch,
        so the engine returns a risk_weight != 0.30.

        Arrange: FAC_MDB_NN_B31_001_UNDRAWN, CQS=2, entity_type='mdb' (non-named).
        Act:     full Basel 3.1 SA pipeline.
        Assert:  risk_weight == 0.30 ± 1e-6.
        """
        # Arrange
        row = p1_154_b31_results[_MDB_EXPOSURE_REF]

        # Assert
        assert row["risk_weight"] == pytest.approx(_EXPECTED_RW_MDB, abs=_RW_TOL), (
            f"P1.154-B31 Art. 117(1)(a) Table 2B: expected risk_weight=0.30 "
            f"(CQS 2 → 30% under B31 Table 2B; CRR institution ECRA CQS 2 >3m = 50%). "
            f"got {row['risk_weight']}. "
            f"Fix: add rated non-named MDB branch to _apply_b31_risk_weight_overrides "
            f"in engine/sa/namespace.py using MDB_RISK_WEIGHTS_TABLE_2B CQS lookup."
        )

    def test_p1_154_b31_mdb_ead_equals_facility_limit(
        self, p1_154_b31_results: dict[str, dict]
    ) -> None:
        """
        Non-named MDB EAD must equal the full facility limit (EUR 50,000,000).

        No FX rates table in the bundle — EAD is face value in original currency.

        Arrange: FAC_MDB_NN_B31_001_UNDRAWN, limit=50,000,000 EUR, no FX.
        Act:     full Basel 3.1 SA pipeline.
        Assert:  ead_final == 50,000,000 ± £0.50.
        """
        # Arrange
        row = p1_154_b31_results[_MDB_EXPOSURE_REF]

        # Assert
        assert row["ead_final"] == pytest.approx(_EXPECTED_EAD_MDB, abs=_AMT_TOL), (
            f"P1.154-B31: expected ead_final={_EXPECTED_EAD_MDB:,.0f} "
            f"(EUR 50m face value, no FX), got {row['ead_final']:,.2f}"
        )

    def test_p1_154_b31_mdb_rwa_table_2b_cqs2(self, p1_154_b31_results: dict[str, dict]) -> None:
        """
        Non-named MDB RWA = EAD × 30% = 15,000,000 (B31 Art. 117(1)(a) Table 2B).

        Pre-fix: since risk_weight is not 0.30, rwa_final will not be 15,000,000.

        Arrange: FAC_MDB_NN_B31_001_UNDRAWN, EAD=50,000,000, RW=30% (B31 Table 2B).
        Act:     full Basel 3.1 SA pipeline.
        Assert:  rwa_final == 15,000,000 ± £0.50.
        """
        # Arrange
        row = p1_154_b31_results[_MDB_EXPOSURE_REF]

        # Assert
        assert row["rwa_final"] == pytest.approx(_EXPECTED_RWA_MDB, abs=_AMT_TOL), (
            f"P1.154-B31 Art. 117(1)(a) Table 2B: expected rwa_final={_EXPECTED_RWA_MDB:,.0f} "
            f"(EAD 50,000,000 × 30%), got {row['rwa_final']:,.2f}"
        )


# ---------------------------------------------------------------------------
# Control: IMF granular assertions
# ---------------------------------------------------------------------------


class TestIMFB31:
    """
    P1.154-B31 control group — Art. 118: IMF (international_org) → 0% unconditional.

    These are expected to pass before the engine-implementer fix because
    ExposureClass.INTERNATIONAL_ORGANISATION and IO_ZERO_RW are already
    implemented. They confirm the Art. 118 path is not broken by the MDB fix.
    """

    def test_p1_154_b31_imf_exposure_class_is_international_organisation(
        self, p1_154_b31_results: dict[str, dict]
    ) -> None:
        """
        IMF (entity_type='international_org') must be classified as
        'international_organisation' under Art. 112(1)(e).

        Arrange: FAC_IO_IMF_B31_001_UNDRAWN, entity_type='international_org'.
        Act:     full Basel 3.1 SA pipeline.
        Assert:  exposure_class == "international_organisation".
        """
        # Arrange
        row = p1_154_b31_results[_IMF_EXPOSURE_REF]

        # Assert
        assert row["exposure_class"] == _EXPECTED_CLASS_IMF, (
            f"P1.154-B31 Art. 118: expected exposure_class='international_organisation', "
            f"got '{row['exposure_class']}'"
        )

    def test_p1_154_b31_imf_risk_weight_is_zero(self, p1_154_b31_results: dict[str, dict]) -> None:
        """
        IMF must receive 0% RW (Art. 118 unconditional).

        Arrange: FAC_IO_IMF_B31_001_UNDRAWN, no CQS.
        Act:     full Basel 3.1 SA pipeline.
        Assert:  risk_weight == 0.00 ± 1e-6.
        """
        # Arrange
        row = p1_154_b31_results[_IMF_EXPOSURE_REF]

        # Assert
        assert row["risk_weight"] == pytest.approx(_EXPECTED_RW_IMF, abs=_RW_TOL), (
            f"P1.154-B31 Art. 118: expected risk_weight=0.00, got {row['risk_weight']}"
        )

    def test_p1_154_b31_imf_ead_equals_facility_limit(
        self, p1_154_b31_results: dict[str, dict]
    ) -> None:
        """
        IMF EAD must equal the full facility limit (USD 100,000,000).

        No FX rates table in the bundle — EAD is face value in original currency.

        Arrange: FAC_IO_IMF_B31_001_UNDRAWN, limit=100,000,000 USD, no FX.
        Act:     full Basel 3.1 SA pipeline.
        Assert:  ead_final == 100,000,000 ± £0.50.
        """
        # Arrange
        row = p1_154_b31_results[_IMF_EXPOSURE_REF]

        # Assert
        assert row["ead_final"] == pytest.approx(_EXPECTED_EAD_IMF, abs=_AMT_TOL), (
            f"P1.154-B31 Art. 118: expected ead_final={_EXPECTED_EAD_IMF:,.0f} "
            f"(USD 100m face value, no FX), got {row['ead_final']:,.2f}"
        )

    def test_p1_154_b31_imf_rwa_is_zero(self, p1_154_b31_results: dict[str, dict]) -> None:
        """
        IMF RWA must be zero: EAD × 0% = 0.

        Arrange: FAC_IO_IMF_B31_001_UNDRAWN, EAD=100,000,000, RW=0%.
        Act:     full Basel 3.1 SA pipeline.
        Assert:  rwa_final == 0.00 ± £0.50.
        """
        # Arrange
        row = p1_154_b31_results[_IMF_EXPOSURE_REF]

        # Assert
        assert row["rwa_final"] == pytest.approx(_EXPECTED_RWA_IMF, abs=_AMT_TOL), (
            f"P1.154-B31 Art. 118: expected rwa_final=0.00, got {row['rwa_final']}"
        )
