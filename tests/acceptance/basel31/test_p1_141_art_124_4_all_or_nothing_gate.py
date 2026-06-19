"""
P1.141 — Basel 3.1 Art. 124(4) all-or-nothing qualifying gate for mixed RE.

Pipeline position:
    Loader → HierarchyResolver → Classifier → CRMProcessor
        → RealEstateSplitter → SACalculator → Aggregator

Scenario design:
    Art. 124(4) makes Art. 124J (Other RE) the default for mixed-use RE exposures.
    The preferential Art. 124F–124I tables apply ONLY if BOTH the residential
    component AND the commercial component separately qualify under Art. 124A(1).
    If either component fails, BOTH drop to Art. 124J — the "all-or-nothing" gate.

    This scenario has one mixed-use exposure (LN-P1141, EAD=2,000,000):
        COL-P1141-R: residential, MV=1,500,000, is_qualifying_re=True
        COL-P1141-C: commercial,  MV=1,000,000, is_qualifying_re=False  ← gate trigger

    The commercial component's is_qualifying_re=False triggers the gate.
    Post-fix: BOTH components route through Art. 124J (Other RE), NOT Art. 124F/124H.

    EAD allocation (pro-rata by collateral value, Art. 124(4) split still applies):
        RESI_share = 1,500,000 / 2,500,000 = 0.60  → EAD_RESI = 1,200,000
        CRE_share  = 1,000,000 / 2,500,000 = 0.40  → EAD_CRE  =   800,000

    Art. 124J risk weights (unrated corporate, cp_rw=1.00):
        RESI component (non-income-dependent): RW = cp_rw = 1.00
        CRE  component (non-income-dependent): RW = max(0.60, cp_rw) = 1.00

    RWA:
        RWA_RESI  = 1,200,000 × 1.00 = 1,200,000
        RWA_CRE   =   800,000 × 1.00 =   800,000
        RWA_total =                     2,000,000

Pre-fix (current) behaviour WITHOUT the gate:
    Each component routes through Art. 124F/124H independently of is_qualifying_re.
    The residential component receives the preferential Art. 124F 20% band:
        cap = 0.55 × 1,500,000 = 825,000  → 825,000@20% + 375,000@100%
        Pre-fix RWA_RESI ≈ 540,000 (NOT 1,200,000)
    CRE component: max(60%, 100%) = 100% → 800,000@100% = 800,000
    Pre-fix RWA_total ≈ 1,340,000 (NOT 2,000,000)

Load-bearing assertions (FAIL pre-fix):
    1. parent total RWA  == 2,000,000  (pre-fix ≈ 1,340,000)
    2. secured_rre RW    == 1.00       (pre-fix ≈ 0.20 from Art. 124F band)

Regulatory references:
    - PRA PS1/26 Art. 124(4): all-or-nothing Art. 124J fallback (ps126app1.pdf p.51)
    - PRA PS1/26 Art. 124A(1): six-criterion qualifying gate (p.51)
    - PRA PS1/26 Art. 124J: Other RE risk weight (p.57-58)
    - PRA PS1/26 Art. 124F: RRE preferential 20%/75% LTV-split (p.55)
    - data/tables/b31_risk_weights.py: B31_OTHER_RE_CRE_FLOOR_RW=0.60,
      B31_CORPORATE_RISK_WEIGHTS[None]=1.00
    - tests/fixtures/p1_141/p1_141.py: fixture constants and builder functions.
    - IMPLEMENTATION_PLAN.md: P1.141 entry.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.p1_141.p1_141 import (
    COUNTERPARTY_REF,
    EAD_CRE,
    EAD_RESI,
    EXPECTED_EAD_RESIDUAL,
    EXPECTED_EAD_TOTAL,
    EXPECTED_RW_CRE,
    EXPECTED_RW_RESI,
    EXPECTED_RWA_CRE,
    EXPECTED_RWA_RESI,
    EXPECTED_RWA_TOTAL,
    REPORTING_DATE,
)
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_141"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_bundle() -> RawDataBundle:
    """
    Construct a RawDataBundle from P1.141 parquets.

    One mixed-use exposure: LN-P1141, EAD=2,000,000, counterparty CP-P1141.
    Two collateral rows: COL-P1141-R (residential, is_qualifying_re=True) and
    COL-P1141-C (commercial, is_qualifying_re=False).

    The load-bearing test column is is_qualifying_re on the collateral frame.
    The engine (post-fix) must propagate per-component qualifying status into
    the classifier/splitter to enforce the Art. 124(4) all-or-nothing gate.

    NOTE: the P1.141 parquet was generated without collateral_type="real_estate".
    The hierarchy resolver (_resolve_property_collateral_values) filters on
    collateral_type == "real_estate" to find RE collateral. We inject this
    field here at the test bundle level — this is NOT a fixture edit; it is
    a test-layer augmentation required to route through the RE split path so
    the actual Art. 124(4) gate assertion can be exercised.
    Without this, the engine sees zero residential/commercial collateral value
    and routes the exposure as an unsplit corporate row (RWA=2,000,000 at 100%),
    producing a coincidental match on the post-fix expected RWA but via the
    wrong code path, which would make the discriminating RW assertions vacuous.
    The fixture-builder should regenerate the parquet with collateral_type set.
    """
    collateral_raw = pl.scan_parquet(_FIXTURES_DIR / "collateral.parquet")
    # Inject collateral_type="real_estate" to ensure the hierarchy resolver
    # picks up the RE collateral values (residential_collateral_value / property_collateral_value).
    collateral = collateral_raw.with_columns(
        pl.lit("real_estate").alias("collateral_type"),
    )
    return make_raw_bundle(
        facilities=pl.scan_parquet(_FIXTURES_DIR / "facility.parquet"),
        loans=pl.scan_parquet(_FIXTURES_DIR / "loan.parquet"),
        counterparties=pl.scan_parquet(_FIXTURES_DIR / "counterparty.parquet"),
        facility_mappings=pl.scan_parquet(_FIXTURES_DIR / "facility_mapping.parquet"),
        lending_mappings=pl.scan_parquet(_FIXTURES_DIR / "lending_mapping.parquet"),
        collateral=collateral,
        org_mappings=pl.scan_parquet(_FIXTURES_DIR / "org_mapping.parquet"),
    )


def _b31_config() -> CalculationConfig:
    """Basel 3.1 SA-only config with reporting_date=2027-01-02 (post-go-live)."""
    return CalculationConfig.basel_3_1(
        reporting_date=REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )


# ---------------------------------------------------------------------------
# Module-scoped SA results fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def p1_141_sa_results() -> pl.DataFrame:
    """
    Run P1.141 fixtures through the Basel 3.1 SA pipeline and return SA results.

    Arrange: Mixed-use RE exposure (LN-P1141, EAD=2,000,000) with one qualifying
             residential collateral (is_qualifying_re=True) and one non-qualifying
             commercial collateral (is_qualifying_re=False). Unrated corporate
             counterparty (CP-P1141). B31 SA-only config, 2027-01-02.
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


def _get_child_rows(df: pl.DataFrame) -> pl.DataFrame:
    """
    Return all rows derived from LN-P1141 (the RE-split children).

    Discovers children at runtime by filtering on counterparty reference and
    split_parent_id, WITHOUT hard-coding the parent exposure_reference.
    The fixture's beneficiary_reference is LOAN_REF (='LN-P1141') and the
    RE splitter sets split_parent_id = parent exposure_reference which is
    derived from LOAN_REF.

    Includes both the original row (if any) and all split sub-rows.
    """
    # Filter by counterparty reference to avoid hard-coding exposure_reference
    return df.filter(pl.col("counterparty_reference") == COUNTERPARTY_REF)


def _get_rre_child(df: pl.DataFrame) -> dict | None:
    """Return the secured_rre child row for the mixed RE split, or None."""
    rows = _get_child_rows(df).filter(pl.col("re_split_role") == "secured_rre").to_dicts()
    return rows[0] if rows else None


def _get_cre_child(df: pl.DataFrame) -> dict | None:
    """Return the secured_cre child row for the mixed RE split, or None."""
    rows = _get_child_rows(df).filter(pl.col("re_split_role") == "secured_cre").to_dicts()
    return rows[0] if rows else None


def _get_residual_child(df: pl.DataFrame) -> dict | None:
    """Return the residual child row for the mixed RE split, or None."""
    rows = _get_child_rows(df).filter(pl.col("re_split_role") == "residual").to_dicts()
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# P1.141 acceptance test class
# ---------------------------------------------------------------------------


class TestB31P1141Art1244AllOrNothingGate:
    """
    P1.141: Basel 3.1 Art. 124(4) all-or-nothing qualifying gate.

    When a mixed RE exposure has at least ONE non-qualifying component
    (is_qualifying_re=False), Art. 124(4) mandates Art. 124J (Other RE)
    for BOTH components — NOT just the failing component.

    The discriminating fixture: commercial component is_qualifying_re=False
    triggers the gate, withdrawing the Art. 124F 20% residential preferential band.

    Post-fix expected:
        secured_rre row: EAD=1,200,000, RW=1.00 (Art. 124J, cp_rw=1.00)
        secured_cre row: EAD=800,000,   RW=1.00 (Art. 124J, max(0.60,1.00))
        residual row:    EAD=0.0
        parent RWA_total = 2,000,000

    Pre-fix (current): residential receives Art. 124F 20% band ≈ 540,000 RWA,
    CRE 800,000@100% = 800,000 RWA, total ≈ 1,340,000. FAILS assertions below.
    """

    # -------------------------------------------------------------------------
    # DISCRIMINATING ASSERTIONS — FAIL pre-fix
    # -------------------------------------------------------------------------

    def test_p1_141_parent_total_rwa_is_2m(self, p1_141_sa_results: pl.DataFrame) -> None:
        """
        P1.141 DISCRIMINATING: parent total RWA = 2,000,000.

        Art. 124J (PRA PS1/26): both components take the Other RE RW = cp_rw=1.00.
        EAD_total = 2,000,000 → RWA_total = 2,000,000.

        Pre-fix (current): commercial is_qualifying_re gate not enforced →
            residential component gets Art. 124F 20% band → RWA_RESI ≈ 540,000,
            RWA_CRE = 800,000, total ≈ 1,340,000. This test FAILS pre-fix.

        Post-fix: gate enforced → BOTH components at Art. 124J 100% → RWA = 2,000,000.

        Arrange: B31 SA-only config, LN-P1141, EAD=2,000,000, mixed RE collateral
                 with commercial is_qualifying_re=False.
        Act:     Sum rwa_final across all rows for CP-P1141.
        Assert:  total rwa_final == 2,000,000.0 (abs=1.0).
        """
        # Arrange
        child_rows = _get_child_rows(p1_141_sa_results)
        total_rwa = child_rows["rwa_final"].sum()

        # Assert — FAILS pre-fix (engine returns ≈ 1,340,000)
        assert total_rwa == pytest.approx(EXPECTED_RWA_TOTAL, abs=1.0), (
            f"P1.141: parent total rwa_final should be {EXPECTED_RWA_TOTAL:,.0f} "
            f"(EAD 2,000,000 × Art. 124J 100% for BOTH components — gate triggered "
            f"because commercial is_qualifying_re=False per Art. 124(4)). "
            f"Got {total_rwa:,.0f}. "
            f"Pre-fix value ≈ 1,340,000: Art. 124(4) all-or-nothing gate not enforced "
            f"— residential component incorrectly receives Art. 124F 20% band "
            f"(825,000@20%=165,000 + 375,000@100%=375,000 = 540,000) instead of "
            f"Art. 124J 100% (1,200,000). "
            f"Engine-implementer must propagate per-component is_qualifying_re signal "
            f"and route BOTH components to b31_other_re_rw_expr when either fails."
        )

    def test_p1_141_secured_rre_risk_weight_is_100_pct(
        self, p1_141_sa_results: pl.DataFrame
    ) -> None:
        """
        P1.141 DISCRIMINATING: secured_rre child row risk_weight = 1.00 (NOT 0.20).

        Art. 124J (Other RE, non-income-dependent, cp_rw=1.00): RW = cp_rw = 1.00.
        Pre-fix: Art. 124F 20% band applies to the residential component → RW ≈ 0.20
        for the secured portion (825,000@20%). This test FAILS pre-fix.

        Arrange: B31 SA-only config, mixed RE, commercial is_qualifying_re=False.
        Act:     Retrieve secured_rre child row (re_split_role == "secured_rre").
        Assert:  risk_weight == 1.00 (abs=1e-6).
        """
        # Arrange
        rre_row = _get_rre_child(p1_141_sa_results)

        assert rre_row is not None, (
            "P1.141: no secured_rre row found in SA results. "
            "Expected a split row with re_split_role='secured_rre' for the "
            "residential component of the mixed RE exposure LN-P1141. "
            f"Available rows: {_get_child_rows(p1_141_sa_results).select(['exposure_reference', 're_split_role', 'risk_weight']).to_dicts()}"
        )

        # Assert — FAILS pre-fix (Art. 124F gives the secured portion ≈ 0.20)
        assert rre_row["risk_weight"] == pytest.approx(EXPECTED_RW_RESI, abs=1e-6), (
            f"P1.141: secured_rre risk_weight should be {EXPECTED_RW_RESI:.2f} "
            f"(Art. 124J Other RE, non-income-dependent, cp_rw=1.00 → RW=cp_rw=1.00). "
            f"Got {rre_row['risk_weight']:.6f}. "
            f"Pre-fix: Art. 124F 20% band applied to residential component — "
            f"the is_qualifying_re=False on commercial component does not yet "
            f"trigger the Art. 124(4) all-or-nothing gate for the residential row. "
            f"Post-fix: gate enforced → residential rows use Art. 124J → RW=1.00."
        )

    # -------------------------------------------------------------------------
    # STRUCTURAL ASSERTIONS — verify the split shape (post-fix required)
    # -------------------------------------------------------------------------

    def test_p1_141_secured_rre_ead_is_1_2m(self, p1_141_sa_results: pl.DataFrame) -> None:
        """
        P1.141: secured_rre EAD = 1,200,000 (60% of 2,000,000).

        Art. 124(4) pro-rata split: RESI_share = 1,500,000/2,500,000 = 0.60.
        EAD_RESI = 2,000,000 × 0.60 = 1,200,000. EAD allocation is independent
        of the qualifying gate — the split still uses the 0.55×V cap method.

        Arrange: LN-P1141, collateral MV: RESI=1,500,000, CRE=1,000,000.
        Act:     ead_final from the secured_rre child row.
        Assert:  ead_final ≈ 1,200,000 (abs=1.0).
        """
        rre_row = _get_rre_child(p1_141_sa_results)

        assert rre_row is not None, (
            "P1.141: no secured_rre row found — check splitter emits re_split_role."
        )

        assert rre_row["ead_final"] == pytest.approx(EAD_RESI, abs=1.0), (
            f"P1.141: secured_rre ead_final should be {EAD_RESI:,.0f} "
            f"(Art. 124(4) pro-rata: 2,000,000 × 1,500,000/2,500,000). "
            f"Got {rre_row['ead_final']:,.0f}."
        )

    def test_p1_141_secured_rre_rwa_is_1_2m(self, p1_141_sa_results: pl.DataFrame) -> None:
        """
        P1.141: secured_rre RWA = 1,200,000 (EAD × RW = 1,200,000 × 1.00).

        Post-fix: Art. 124J → RW=1.00 → RWA_RESI = 1,200,000.
        Pre-fix: Art. 124F → blended → RWA_RESI ≈ 540,000.

        Arrange: secured_rre child row with EAD=1,200,000, RW=1.00 (post-fix).
        Act:     rwa_final from the secured_rre row.
        Assert:  rwa_final ≈ 1,200,000 (abs=1.0).
        """
        rre_row = _get_rre_child(p1_141_sa_results)

        assert rre_row is not None, "P1.141: no secured_rre row found."

        assert rre_row["rwa_final"] == pytest.approx(EXPECTED_RWA_RESI, abs=1.0), (
            f"P1.141: secured_rre rwa_final should be {EXPECTED_RWA_RESI:,.0f} "
            f"(EAD {EAD_RESI:,.0f} × Art. 124J RW {EXPECTED_RW_RESI:.2f}). "
            f"Got {rre_row['rwa_final']:,.0f}. "
            f"Pre-fix: ≈ 540,000 (Art. 124F 20% band)."
        )

    def test_p1_141_secured_cre_ead_is_800k(self, p1_141_sa_results: pl.DataFrame) -> None:
        """
        P1.141: secured_cre EAD = 800,000 (40% of 2,000,000).

        Art. 124(4) pro-rata split: CRE_share = 1,000,000/2,500,000 = 0.40.
        EAD_CRE = 2,000,000 × 0.40 = 800,000.

        Arrange: LN-P1141, CRE collateral MV=1,000,000.
        Act:     ead_final from the secured_cre child row.
        Assert:  ead_final ≈ 800,000 (abs=1.0).
        """
        cre_row = _get_cre_child(p1_141_sa_results)

        assert cre_row is not None, (
            "P1.141: no secured_cre row found — check splitter emits re_split_role='secured_cre'."
        )

        assert cre_row["ead_final"] == pytest.approx(EAD_CRE, abs=1.0), (
            f"P1.141: secured_cre ead_final should be {EAD_CRE:,.0f} "
            f"(Art. 124(4) pro-rata: 2,000,000 × 1,000,000/2,500,000). "
            f"Got {cre_row['ead_final']:,.0f}."
        )

    def test_p1_141_secured_cre_risk_weight_is_100_pct(
        self, p1_141_sa_results: pl.DataFrame
    ) -> None:
        """
        P1.141: secured_cre risk_weight = 1.00 (Art. 124J, max(0.60, cp_rw=1.00)).

        Art. 124J Other RE (non-income-dependent): RW = max(CRE_floor, cp_rw).
        B31_OTHER_RE_CRE_FLOOR_RW=0.60; cp_rw=1.00 → max(0.60,1.00) = 1.00.
        (Both pre-fix and post-fix: CRE component already routes through Art. 124J
        in the current engine for the non-NP/SME corporate path. This assertion
        validates that the CRE row is still present and correct after the fix.)

        Arrange: secured_cre child row, corporate unrated counterparty.
        Act:     risk_weight from the secured_cre row.
        Assert:  risk_weight == 1.00 (abs=1e-6).
        """
        cre_row = _get_cre_child(p1_141_sa_results)

        assert cre_row is not None, "P1.141: no secured_cre row found."

        assert cre_row["risk_weight"] == pytest.approx(EXPECTED_RW_CRE, abs=1e-6), (
            f"P1.141: secured_cre risk_weight should be {EXPECTED_RW_CRE:.2f} "
            f"(Art. 124J: max(B31_OTHER_RE_CRE_FLOOR_RW=0.60, cp_rw=1.00) = 1.00). "
            f"Got {cre_row['risk_weight']:.6f}."
        )

    def test_p1_141_secured_cre_rwa_is_800k(self, p1_141_sa_results: pl.DataFrame) -> None:
        """
        P1.141: secured_cre RWA = 800,000 (EAD × RW = 800,000 × 1.00).

        Arrange: secured_cre child row with EAD=800,000, RW=1.00.
        Act:     rwa_final from the secured_cre row.
        Assert:  rwa_final ≈ 800,000 (abs=1.0).
        """
        cre_row = _get_cre_child(p1_141_sa_results)

        assert cre_row is not None, "P1.141: no secured_cre row found."

        assert cre_row["rwa_final"] == pytest.approx(EXPECTED_RWA_CRE, abs=1.0), (
            f"P1.141: secured_cre rwa_final should be {EXPECTED_RWA_CRE:,.0f} "
            f"(EAD {EAD_CRE:,.0f} × Art. 124J RW {EXPECTED_RW_CRE:.2f}). "
            f"Got {cre_row['rwa_final']:,.0f}."
        )

    def test_p1_141_residual_ead_is_zero(self, p1_141_sa_results: pl.DataFrame) -> None:
        """
        P1.141 DISCRIMINATING: residual EAD = 0.0.

        Post-fix: the Art. 124(4) Art. 124J path allocates EAD pro-rata across
        the full collateral value (V_RESI + V_CRE = 2,500,000) without a 0.55×V
        cap on the secured portions. The full parent EAD is consumed by the two
        secured components (EAD_RESI=1,200,000 + EAD_CRE=800,000 = 2,000,000),
        leaving residual EAD = 0.

        Pre-fix (current): the splitter applies 0.55×V caps before routing to
        Art. 124J. With caps binding:
          RESI secured = min(1,200,000, 0.55×1,500,000) = min(1,200,000, 825,000) = 825,000
          CRE  secured = min(800,000,   0.55×1,000,000) = min(800,000,   550,000) = 550,000
          residual     = 2,000,000 - 825,000 - 550,000 = 625,000
        Pre-fix residual ≈ 625,000 — this test FAILS pre-fix.

        Post-fix: Art. 124J path uses pro-rata direct allocation (no 0.55×V cap),
        residual = 0. This test discriminates the EAD-allocation half of the fix.

        Arrange: LN-P1141, mixed RE, Art. 124J path (gate triggered).
        Act:     ead_final from the residual child row (re_split_role='residual').
        Assert:  ead_final == 0.0 (abs=1.0).
        """
        residual_row = _get_residual_child(p1_141_sa_results)

        assert residual_row is not None, (
            "P1.141: no residual row found (re_split_role='residual'). "
            "The RE splitter must emit a residual row even when EAD=0 for "
            "per-parent reconciliation."
        )

        # FAILS pre-fix: residual ≈ 625,000; post-fix: 0
        assert residual_row["ead_final"] == pytest.approx(EXPECTED_EAD_RESIDUAL, abs=1.0), (
            f"P1.141: residual ead_final should be {EXPECTED_EAD_RESIDUAL:.1f} "
            f"(Art. 124J path: full EAD pro-rata to secured_rre + secured_cre, "
            f"no 0.55×V cap → residual = 2,000,000 - 1,200,000 - 800,000 = 0). "
            f"Got {residual_row['ead_final']:,.0f}. "
            f"Pre-fix: 0.55×V caps bind → secured_rre=825,000 + secured_cre=550,000 "
            f"= 1,375,000, leaving residual ≈ 625,000. "
            f"Engine-implementer must remove 0.55×V cap on the Art. 124J path."
        )

    def test_p1_141_child_ead_sums_to_parent(self, p1_141_sa_results: pl.DataFrame) -> None:
        """
        P1.141 EAD reconciliation: sum(child EAD) == parent EAD == 2,000,000.

        Art. 124(4): the pro-rata split must allocate exactly the full parent EAD
        across the child rows (secured_rre + secured_cre + residual).
        The Art. 124J routing change does not affect EAD allocation — it only
        changes the risk weight applied to each secured component.

        Arrange: all child rows for CP-P1141 (secured_rre + secured_cre + residual).
        Act:     Sum ead_final across all child rows.
        Assert:  sum(ead_final) ≈ EXPECTED_EAD_TOTAL = 2,000,000 (abs=1.0).
        """
        # Arrange — all rows for this counterparty
        child_rows = _get_child_rows(p1_141_sa_results)
        total_ead = child_rows["ead_final"].sum()

        # Assert
        assert total_ead == pytest.approx(EXPECTED_EAD_TOTAL, abs=1.0), (
            f"P1.141: sum(child ead_final) should equal parent EAD "
            f"{EXPECTED_EAD_TOTAL:,.0f} (Art. 124(4) EAD conservation). "
            f"Got {total_ead:,.0f}. "
            f"Rows: {child_rows.select(['exposure_reference', 're_split_role', 'ead_final']).to_dicts()}"
        )
