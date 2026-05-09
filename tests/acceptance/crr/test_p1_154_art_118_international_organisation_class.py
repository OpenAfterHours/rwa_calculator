"""
P1.154: CRR Art. 118 — named international organisations must receive a
dedicated exposure class and 0% unconditional risk weight.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> SACalculator -> Aggregator

Key responsibilities:
- Validate CRR Art. 118: named international organisations (IMF, BIS, ECB, EU, IBRD, IFC,
  IADB, ADB, AfDB, CEB, NIB, CDB, EBRD, EFSI, ESM, EFSF) must be classified as
  ExposureClass.INTERNATIONAL_ORGANISATION — not collapsed into the MDB class.
- Validate Art. 118 unconditional 0% risk weight: the 0% must flow from the
  INTERNATIONAL_ORGANISATION exposure class, not from any coincidental MDB check.
- Validate the MDB control row (non-named MDB CQS 3) is unaffected by the new
  routing: exposure_class remains "mdb".

Bug (pre-fix):
    The engine's entity_type → SA exposure class mapping routes
    entity_type="international_org" to the MDB branch (Art. 117), assigning
    exposure_class="mdb". The new ExposureClass.INTERNATIONAL_ORGANISATION enum value
    must be added and the mapping updated to fix the classification.

    CRR Art. 112(1)(e) lists international organisations as a distinct exposure class.
    CRR Art. 118 assigns 0% SA risk weight unconditionally.

Hand-calculations (CRR, CalculationConfig.crr(), reporting_date = 2026-06-30):
    No FX rates table — all EADs are in original currency (face value).

  FAC_IO_IMF_001_UNDRAWN (CP_IO_IMF, entity_type="international_org"):
    Exposure class (post-fix): INTERNATIONAL_ORGANISATION (Art. 112(1)(e))
    Risk weight (Art. 118): 0% unconditional (no CQS lookup, no rating needed)
    EAD: USD 100,000,000 (face value, no FX conversion without fx_rates table)
    RWA: 100,000,000 × 0.00 = 0

  FAC_MDB_NN_001_UNDRAWN (CP_MDB_NONNAMED, entity_type="mdb"):
    Exposure class: mdb (unchanged — control row)
    CQS: 3 (from rating row RATING_MDB_NN_CQS3 — rating_type="external_cqs")
    Risk weight (Art. 117(1) Table 2B, CQS 3): 50%
    EAD: EUR 50,000,000 (face value, no FX conversion without fx_rates table)
    RWA: 50,000,000 × 0.50 = 25,000,000

Pre-fix failure mode:
    FAC_IO_IMF_001_UNDRAWN: exposure_class="mdb" (wrong) instead of
    "international_organisation" (expected). This is the load-bearing assertion
    that drives the P1.154 engine fix.

References:
    - CRR Art. 112(1)(e): exposure class for international organisations
    - CRR Art. 118: named international organisations → 0% SA risk weight
    - CRR Art. 117(1): non-named MDB treated as institution → Table 2B CQS lookup
    - src/rwa_calc/domain/enums.py: ExposureClass (new INTERNATIONAL_ORGANISATION member)
    - src/rwa_calc/engine/classifier.py: ENTITY_TYPE_TO_SA_CLASS mapping
    - tests/fixtures/p1_154/p1_154.py: scenario constants and parquet builders
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import LOAN_SCHEMA
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.p1_154.p1_154 import (
    EXPECTED_RW_INTERNATIONAL_ORG,
    EXPECTED_RW_MDB_CQS3,
    FAC_IO_IMF_001,
    FAC_MDB_NN_001,
    IMF_LIMIT,
    MDB_LIMIT,
)

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_154"

# ---------------------------------------------------------------------------
# Scenario constants (mirrored from p1_154.py)
# ---------------------------------------------------------------------------

# The engine generates an _UNDRAWN suffix for undrawn facility exposures.
_IMF_EXPOSURE_REF = f"{FAC_IO_IMF_001}_UNDRAWN"
_MDB_EXPOSURE_REF = f"{FAC_MDB_NN_001}_UNDRAWN"

# Post-fix expected exposure classes (Art. 112(1)(e) and Art. 117 respectively)
_EXPECTED_CLASS_IMF = "international_organisation"
_EXPECTED_CLASS_MDB = "mdb"

# Post-fix expected risk weights (from p1_154.py exports)
_EXPECTED_RW_IMF = EXPECTED_RW_INTERNATIONAL_ORG   # 0.00 — Art. 118 unconditional
_EXPECTED_RW_MDB = EXPECTED_RW_MDB_CQS3            # 0.50 — Table 2B CQS 3

# Post-fix expected RWA (face-value EAD, no FX — no fx_rates table in bundle)
_EXPECTED_RWA_IMF = 0.0                             # 100m × 0.00 = 0
_EXPECTED_RWA_MDB = 25_000_000.0                   # 50m × 0.50 = 25m

# Post-fix expected EAD (face-value, no FX conversion without fx_rates table)
_EXPECTED_EAD_IMF = IMF_LIMIT                       # USD 100,000,000 (no conversion)
_EXPECTED_EAD_MDB = MDB_LIMIT                       # EUR 50,000,000 (no conversion)

# Tolerances
_RW_TOL = 1e-6    # absolute on risk_weight
_AMT_TOL = 0.50   # £0.50 absolute on rwa_final / ead_final

# ---------------------------------------------------------------------------
# Bundle builder
# ---------------------------------------------------------------------------


def _build_bundle() -> RawDataBundle:
    """
    Load P1.154 scenario parquets and assemble a RawDataBundle.

    No fx_rates table: all EAD amounts remain in original currency (face value).
    This is deliberate — the fixture docstring states FX-irrelevant classification
    tests should use raw limit values. Omitting fx_rates ensures EAD numerics match
    the raw limits in IMF_LIMIT and MDB_LIMIT.

    No loans — both exposures are facility-only (committed, full_risk). The
    pipeline treats these as off-balance-sheet commitments and generates
    *_UNDRAWN rows.

    Ratings are included so the MDB counterparty resolves to CQS 3. Note that
    the rating_type="external_cqs" in the fixture; the engine filters on
    rating_type="external". The MDB CQS resolution may therefore fall back to
    unrated in the current build — this is a pre-existing data issue independent
    of P1.154. The load-bearing P1.154 assertion is the IMF exposure_class.
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
        f"P1.154: expected exactly 1 SA row for {exposure_ref}, got {len(df)}. "
        f"Pipeline may have dropped or duplicated the exposure."
    )
    return df.to_dicts()[0]


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def p1_154_crr_results() -> dict[str, dict]:
    """
    Run the P1.154 fixtures through the CRR SA pipeline once.

    Returns a mapping of exposure_reference -> result row dict for both
    exposures. Module-scoped to avoid repeated pipeline runs.

    Pre-fix: CP_IO_IMF (IMF, international_org) is misclassified as "mdb".
    Post-fix: CP_IO_IMF must be classified as "international_organisation"
    (Art. 112(1)(e)) with 0% unconditional RW (Art. 118).

    The MDB control (CP_MDB_NONNAMED) remains on the "mdb" branch throughout.
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
        "P1.154 CRR: SA results should not be None for SA-only standardised config"
    )

    sa_lf = results.sa_results
    return {
        exposure_ref: _extract_row(sa_lf, exposure_ref)
        for exposure_ref in (_IMF_EXPOSURE_REF, _MDB_EXPOSURE_REF)
    }


# ---------------------------------------------------------------------------
# P1.154 Discriminator tests — IMF (named international organisation)
# ---------------------------------------------------------------------------


class TestIMFInternationalOrganisationClass:
    """
    P1.154 — CRR Art. 112(1)(e) / Art. 118: IMF (entity_type='international_org')
    must be classified as 'international_organisation', not 'mdb'.

    Pre-fix failures (engine routes international_org → mdb):
      exposure_class = "mdb" (wrong), should be "international_organisation"

    The 0% risk weight, 0 RWA, and standardised approach are correct regardless
    of the classification bug, but only the post-fix exposure_class assignment
    makes them legally correct under CRR Art. 118.
    """

    def test_p1_154_art_118_imf_exposure_class_is_international_organisation(
        self, p1_154_crr_results: dict[str, dict]
    ) -> None:
        """
        IMF (entity_type='international_org') must be classified as
        'international_organisation' under CRR Art. 112(1)(e).

        Pre-fix: the engine maps international_org → mdb, so exposure_class = "mdb".
        Post-fix: a new ExposureClass.INTERNATIONAL_ORGANISATION enum value is added
        and the ENTITY_TYPE_TO_SA_CLASS mapping is updated.

        Arrange: FAC_IO_IMF_001_UNDRAWN, counterparty entity_type='international_org'.
        Act:     full CRR SA pipeline with PermissionMode.STANDARDISED.
        Assert:  exposure_class == "international_organisation".
        """
        # Arrange
        row = p1_154_crr_results[_IMF_EXPOSURE_REF]

        # Assert
        assert row["exposure_class"] == _EXPECTED_CLASS_IMF, (
            f"P1.154 Art. 118: expected exposure_class='international_organisation' "
            f"(CRR Art. 112(1)(e) — IMF is a named international organisation), "
            f"got '{row['exposure_class']}'. "
            f"Pre-fix bug: entity_type='international_org' is collapsed into 'mdb'. "
            f"Fix: add ExposureClass.INTERNATIONAL_ORGANISATION and update "
            f"ENTITY_TYPE_TO_SA_CLASS in classifier.py / entity_class_mapping.py."
        )

    def test_p1_154_art_118_imf_risk_weight_is_zero(
        self, p1_154_crr_results: dict[str, dict]
    ) -> None:
        """
        IMF exposure must receive 0% risk weight under CRR Art. 118.

        Art. 118: named international organisations → 0% unconditional.
        The 0% must flow from the INTERNATIONAL_ORGANISATION class, not from
        any coincidental named-MDB check.

        Arrange: FAC_IO_IMF_001_UNDRAWN, exposure_class='international_organisation'.
        Act:     full CRR SA pipeline.
        Assert:  risk_weight == 0.00.
        """
        # Arrange
        row = p1_154_crr_results[_IMF_EXPOSURE_REF]

        # Assert
        assert row["risk_weight"] == pytest.approx(_EXPECTED_RW_IMF, abs=_RW_TOL), (
            f"P1.154 Art. 118: expected risk_weight=0.00 "
            f"(CRR Art. 118 named international organisation → 0% unconditional), "
            f"got {row['risk_weight']}"
        )

    def test_p1_154_art_118_imf_rwa_is_zero(
        self, p1_154_crr_results: dict[str, dict]
    ) -> None:
        """
        IMF RWA must be zero: EAD × 0% = 0.

        Arrange: FAC_IO_IMF_001_UNDRAWN, EAD=100,000,000 (face value, no FX), RW=0%.
        Act:     full CRR SA pipeline.
        Assert:  rwa_final == 0.00 ± £0.50.
        """
        # Arrange
        row = p1_154_crr_results[_IMF_EXPOSURE_REF]

        # Assert
        assert row["rwa_final"] == pytest.approx(_EXPECTED_RWA_IMF, abs=_AMT_TOL), (
            f"P1.154 Art. 118: expected rwa_final=0.00 "
            f"(EAD × 0% = 0), got {row['rwa_final']}"
        )

    def test_p1_154_art_118_imf_ead_equals_facility_limit(
        self, p1_154_crr_results: dict[str, dict]
    ) -> None:
        """
        IMF EAD must equal the full facility limit (USD 100,000,000).

        No FX rates table in the bundle — EAD is stored in original currency
        face value. The 5-year committed, full_risk facility with 100% CCF
        means EAD = limit.

        Arrange: FAC_IO_IMF_001_UNDRAWN, limit=100,000,000 USD, CCF=100%, no FX.
        Act:     full CRR SA pipeline.
        Assert:  ead_final == 100,000,000 ± £0.50.
        """
        # Arrange
        row = p1_154_crr_results[_IMF_EXPOSURE_REF]

        # Assert
        assert row["ead_final"] == pytest.approx(_EXPECTED_EAD_IMF, abs=_AMT_TOL), (
            f"P1.154 Art. 118: expected ead_final={_EXPECTED_EAD_IMF:,.0f} "
            f"(USD 100m face value, no FX conversion), "
            f"got {row['ead_final']:,.2f}"
        )

    def test_p1_154_art_118_imf_approach_is_standardised(
        self, p1_154_crr_results: dict[str, dict]
    ) -> None:
        """
        IMF exposure must use the standardised approach.

        The pipeline config uses PermissionMode.STANDARDISED — all exposures
        must be routed through SA.

        Arrange: FAC_IO_IMF_001_UNDRAWN, config.permission_mode=STANDARDISED.
        Act:     full CRR SA pipeline.
        Assert:  approach_applied == "standardised".
        """
        # Arrange
        row = p1_154_crr_results[_IMF_EXPOSURE_REF]

        # Assert
        assert row["approach_applied"] == "standardised", (
            f"P1.154 Art. 118: expected approach_applied='standardised', "
            f"got '{row['approach_applied']}'"
        )


# ---------------------------------------------------------------------------
# P1.154 Control tests — non-named MDB (Art. 117, CQS 3)
# ---------------------------------------------------------------------------


class TestMDBControlRowUnchanged:
    """
    P1.154 control group — CRR Art. 117(1): non-named MDB (entity_type='mdb')
    must remain classified as 'mdb' after the international_organisation fix.

    This ensures the P1.154 engine change does not inadvertently break the
    MDB classification path.

    The 50% risk weight and 25,000,000 RWA depend on CQS 3 being resolved
    from the rating row (RATING_MDB_NN_CQS3). Note: the fixture uses
    rating_type='external_cqs'; the engine resolves only rating_type='external'.
    If CQS resolution is broken independently of P1.154, these assertions
    will fail — but the load-bearing P1.154 assertion is the IMF exposure_class.
    """

    def test_p1_154_mdb_control_exposure_class_unchanged(
        self, p1_154_crr_results: dict[str, dict]
    ) -> None:
        """
        Non-named MDB (entity_type='mdb') must remain classified as 'mdb'.

        The P1.154 fix must not alter the MDB classification path.

        Arrange: FAC_MDB_NN_001_UNDRAWN, counterparty entity_type='mdb'.
        Act:     full CRR SA pipeline.
        Assert:  exposure_class == "mdb".
        """
        # Arrange
        row = p1_154_crr_results[_MDB_EXPOSURE_REF]

        # Assert
        assert row["exposure_class"] == _EXPECTED_CLASS_MDB, (
            f"P1.154 control: expected exposure_class='mdb' "
            f"(non-named MDB entity_type='mdb' → Art. 117 → MDB class), "
            f"got '{row['exposure_class']}'"
        )

    def test_p1_154_mdb_control_risk_weight_cqs3(
        self, p1_154_crr_results: dict[str, dict]
    ) -> None:
        """
        Non-named MDB with CQS 3 must receive 50% RW via Art. 117(1) Table 2B.

        CRR Art. 117(1): non-named MDB → institution treatment → Table 2B lookup.
        Table 2B CQS 3 → 50%.

        Arrange: FAC_MDB_NN_001_UNDRAWN, CQS=3, EAD=50,000,000.
        Act:     full CRR SA pipeline.
        Assert:  risk_weight == 0.50.
        """
        # Arrange
        row = p1_154_crr_results[_MDB_EXPOSURE_REF]

        # Assert
        assert row["risk_weight"] == pytest.approx(_EXPECTED_RW_MDB, abs=_RW_TOL), (
            f"P1.154 control: expected risk_weight=0.50 "
            f"(CRR Art. 117(1) Table 2B, CQS 3 = 50%), "
            f"got {row['risk_weight']}"
        )

    def test_p1_154_mdb_control_rwa(
        self, p1_154_crr_results: dict[str, dict]
    ) -> None:
        """
        Non-named MDB RWA = EAD × 50% = 25,000,000.

        Arrange: FAC_MDB_NN_001_UNDRAWN, EAD=50,000,000 (face value, no FX), RW=50%.
        Act:     full CRR SA pipeline.
        Assert:  rwa_final == 25,000,000 ± £0.50.
        """
        # Arrange
        row = p1_154_crr_results[_MDB_EXPOSURE_REF]

        # Assert
        assert row["rwa_final"] == pytest.approx(_EXPECTED_RWA_MDB, abs=_AMT_TOL), (
            f"P1.154 control: expected rwa_final={_EXPECTED_RWA_MDB:,.0f} "
            f"(EAD 50,000,000 × 50%), got {row['rwa_final']:,.2f}"
        )

    def test_p1_154_mdb_control_ead(
        self, p1_154_crr_results: dict[str, dict]
    ) -> None:
        """
        Non-named MDB EAD must equal the full facility limit (EUR 50,000,000).

        No FX rates table in the bundle — EAD is stored in original currency
        face value.

        Arrange: FAC_MDB_NN_001_UNDRAWN, limit=50,000,000 EUR, CCF=100%, no FX.
        Act:     full CRR SA pipeline.
        Assert:  ead_final == 50,000,000 ± £0.50.
        """
        # Arrange
        row = p1_154_crr_results[_MDB_EXPOSURE_REF]

        # Assert
        assert row["ead_final"] == pytest.approx(_EXPECTED_EAD_MDB, abs=_AMT_TOL), (
            f"P1.154 control: expected ead_final={_EXPECTED_EAD_MDB:,.0f} "
            f"(EUR 50m face value, no FX conversion), "
            f"got {row['ead_final']:,.2f}"
        )
