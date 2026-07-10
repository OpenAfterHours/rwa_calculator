"""
P1.219 — Guarantee maturity-mismatch `t` must use residual protection maturity,
not the seasoned `original_maturity_years` term.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> SACalculator -> Aggregator

Key assertion:
    CRR Art. 239(3) GA = G* x (t-0.25)/(T-0.25); Art. 238(1) defines `t` as the
    years *remaining* to protection maturity (the residual, derived from
    ``maturity_date``) -- not the original seasoned term
    (``original_maturity_years``). ``engine/crm/guarantees.py``
    (``_apply_maturity_mismatch_to_guarantees``) currently prefers
    ``original_maturity_years`` over the residual whenever both are present:

        t_raw = when(original_maturity_years.is_not_null())
                .then(original_maturity_years)
                .otherwise(t_from_date)

    With a seasoned 5-year guarantee whose *residual* maturity has run down to
    1.0y, the bug uses t=5.0 (>= T=4.0y, "no mismatch") instead of the correct
    t=1.0 (< T=4.0y, Art. 239(3) scaling applies), understating RWA by ~76%.
    Art. 237(2)(a)'s separate >=1y *original*-maturity eligibility gate is
    unaffected and stays on ``original_maturity_years`` (5.0 >= 1.0 -> eligible).

Scenario (EXP-219):
    - CP-OBLIGOR-219:   corporate, GB, unrated -> 100% SA risk weight (Art. 122)
    - CP-GUARANTOR-219: institution, GB, CQS 1 -> 20% SA risk weight (Art. 120)
    - EXP-219: GBP 1,000,000 drawn, maturity_date 2030-06-01 -> T = 4.0y from 2026-06-01
    - G-219: maturity_date 2027-06-01 (residual t = 1.0y, correct post-fix),
      original_maturity_years = 5.0y (seasoned; passes Art. 237(2)(a) gate; the
      WRONG t the pre-fix bug prefers), protection_type=guarantee (not
      credit_derivative -> H_restructuring = 0)
      -> H_fx = 0 (GBP = GBP); G* = 1,000,000
      -> POST-FIX: t_eff = max(1.0, 0.25) = 1.0 < T_eff = 4.0 -> mismatch
         m = (1.0-0.25)/(4.0-0.25) = 0.75/3.75 = 0.2
         GA = 1,000,000 x 0.2 = 200,000.0
         RWA = 200,000.0 x 0.20 + 800,000.0 x 1.00 = 840,000.0
      -> PRE-FIX (bug): t_eff = max(5.0, 0.25) = 5.0 >= T_eff = 4.0 -> no mismatch
         GA = 1,000,000.0 (full face)
         RWA = 1,000,000.0 x 0.20 = 200,000.0 (understated by 640,000, ~76%)

Defect under test (pre-fix):
    ``crm/guarantees.py`` prefers ``original_maturity_years`` (5.0) over the
    residual derived from ``maturity_date`` (1.0) when both are present, so the
    engine treats this seasoned-but-short-residual guarantee as having "no
    mismatch" and applies GA at full face value.

    The primary discriminating assertion (total RWA == 840,000.0) FAILS pre-fix
    because the engine returns 200,000.0.

References:
    - CRR Art. 239(3): GA = G* x (t-0.25)/(T-0.25) maturity mismatch adjustment
    - CRR Art. 238(1): definition of protection maturity t (years remaining)
    - CRR Art. 237(2)(a): minimum original maturity >= 1y eligibility filter
      (unaffected by this fix -- stays on original_maturity_years)
    - CRR Art. 122: unrated corporate 100% SA risk weight
    - CRR Art. 120 Table 3: institution CQS 1 -> 20% SA risk weight
    - PS1/26 mirrors of the above (mismatch scaling is framework-invariant, the
      is_crr guard having already been removed by P1.200)
    - src/rwa_calc/engine/crm/guarantees.py: _apply_maturity_mismatch_to_guarantees
    - tests/fixtures/p1_219/p1_219.py: fixture builder and scenario constants
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
from tests.acceptance.conftest import get_guaranteed_row, get_total_rwa
from tests.fixtures.p1_219.p1_219 import (
    BUGGED_TOTAL_RWA,
    EXPECTED_GUARANTEED_PORTION,
    EXPECTED_GUARANTOR_RW,
    EXPECTED_TOTAL_RWA,
    EXPECTED_UNGUARANTEED_PORTION,
    LOAN_REF,
    REPORTING_DATE,
)
from tests.fixtures.raw_bundle import make_raw_bundle

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import FACILITY_MAPPING_SCHEMA, FACILITY_SCHEMA, LENDING_MAPPING_SCHEMA
from rwa_calc.engine.pipeline import PipelineOrchestrator

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_219" / "data"

_BORROWER_RW = 1.00  # unrated corporate, Art. 122 -- remainder sub-row risk weight

# ---------------------------------------------------------------------------
# Config factories
# ---------------------------------------------------------------------------


def _crr_config() -> CalculationConfig:
    """CRR SA-only config with reporting_date matching the scenario (2026-06-01)."""
    return CalculationConfig.crr(
        reporting_date=REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )


def _b31_config() -> CalculationConfig:
    """Basel 3.1 SA-only config with same reporting_date (framework-invariance pin)."""
    return CalculationConfig.basel_3_1(
        reporting_date=REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )


# ---------------------------------------------------------------------------
# Bundle builder
# ---------------------------------------------------------------------------


def _build_bundle() -> RawDataBundle:
    """
    Construct a RawDataBundle from P1.219 parquets.

    Loads counterparties, loans, ratings, and guarantees from the
    scenario-local parquets in tests/fixtures/p1_219/data/.

    Facilities, facility_mappings, and lending_mappings are empty frames
    with the correct schemas -- the P1.219 scenario has a single drawn
    loan with no facility hierarchy rows required.
    """
    return make_raw_bundle(
        facilities=pl.LazyFrame(schema=dtypes_of(FACILITY_SCHEMA)),
        loans=pl.scan_parquet(_FIXTURES_DIR / "loan.parquet"),
        counterparties=pl.scan_parquet(_FIXTURES_DIR / "counterparty.parquet"),
        facility_mappings=pl.LazyFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA)),
        lending_mappings=pl.LazyFrame(schema=dtypes_of(LENDING_MAPPING_SCHEMA)),
        guarantees=pl.scan_parquet(_FIXTURES_DIR / "guarantee.parquet"),
        ratings=pl.scan_parquet(_FIXTURES_DIR / "rating.parquet"),
    )


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------


def _run_pipeline(config: CalculationConfig) -> pl.DataFrame:
    """
    Run the P1.219 bundle through the credit risk pipeline and return SA results.

    The CRM processor splits the guaranteed loan into two sub-rows:
      - ``EXP-219__G_CP-GUARANTOR-219``: guaranteed portion
        (ead_final = 200,000.0 post-fix; 1,000,000.0 pre-fix)
      - ``EXP-219__REM``: unguaranteed remainder
        (ead_final = 800,000.0 post-fix; 0.0 pre-fix)

    Returns the collected SA results DataFrame.
    """
    bundle = _build_bundle()
    results = PipelineOrchestrator().run_with_data(bundle, config)
    assert results.sa_results is not None, (
        "SA results must not be None — check PermissionMode.STANDARDISED config"
    )
    return results.sa_results.collect()


# ---------------------------------------------------------------------------
# Acceptance tests — P1.219 residual-vs-original maturity mismatch `t` defect
#
# Result-row readers (get_total_rwa / get_guaranteed_row) are imported from
# tests.acceptance.conftest — both take the parent loan reference (LOAN_REF).
# The scenario is framework-invariant (Art. 239(3) mirrored identically by
# PS1/26; the is_crr guard was already removed by P1.200), so both CRR and
# Basel 3.1 configs are exercised and must produce identical numbers.
# ---------------------------------------------------------------------------


class TestP1219GuaranteeMaturityMismatchResidual:
    """
    P1.219: CRR/PS1/26 Art. 239(3) `t` must be the residual protection maturity
    (Art. 238(1)) derived from ``maturity_date``, not the seasoned
    ``original_maturity_years`` term.

    The defect: ``crm/guarantees.py`` prefers ``original_maturity_years`` over
    the residual whenever both are present. With a seasoned 5-year guarantee
    whose residual has run down to 1.0y, the bug treats t=5.0 (>= T=4.0y) as
    "no mismatch" and applies GA at full face value (1,000,000), giving
    RWA = 200,000 instead of the correct 840,000 (~76% understatement).

    Fixture: EXP-219 (corporate, unrated, GBP 1M, T=4.0y from 2026-06-01)
             G-219 (maturity_date=2027-06-01 -> residual t=1.0y;
                    original_maturity_years=5.0 -> seasoned, WRONG pre-fix t)
             CP-GUARANTOR-219 (institution GB, CQS 1 -> 20% RW)

    Hand-calc (Art. 239(3), residual wins post-fix):
        m = (1.0-0.25)/(4.0-0.25) = 0.75/3.75 = 0.2
        GA = 1,000,000 x 0.2 = 200,000.0
        unguaranteed = 1,000,000 - 200,000 = 800,000.0
        RWA = 200,000.0 x 0.20 + 800,000.0 x 1.00 = 840,000.0
    """

    @pytest.fixture(scope="class")
    def crr_sa_results(self) -> pl.DataFrame:
        """
        CRR SA pipeline results for P1.219.

        Arrange: P1.219 parquets — corporate borrower (unrated) with a seasoned
                 guarantee (5.0y original, 1.0y residual) from a CQS-1
                 institution, reporting_date=2026-06-01 (T arithmetic).
        Act:     PipelineOrchestrator with CalculationConfig.crr().
        Return:  Collected SA results DataFrame.
        """
        return _run_pipeline(_crr_config())

    @pytest.fixture(scope="class")
    def b31_sa_results(self) -> pl.DataFrame:
        """
        Basel 3.1 SA pipeline results for P1.219 (framework-invariance pin).

        Arrange: Same P1.219 parquets, reporting_date=2026-06-01, B31 config.
        Act:     PipelineOrchestrator with CalculationConfig.basel_3_1().
        Return:  Collected SA results DataFrame.
        """
        return _run_pipeline(_b31_config())

    # -------------------------------------------------------------------------
    # CRR DISCRIMINATING ASSERTION — FAILS pre-fix
    # -------------------------------------------------------------------------

    def test_p1_219_crr_total_rwa_uses_residual_maturity_for_mismatch_scaling(
        self, crr_sa_results: pl.DataFrame
    ) -> None:
        """
        P1.219 DISCRIMINATING: CRR total RWA == 840,000.0 (residual t wins).

        CRR Art. 238(1): t is the years *remaining* to protection maturity —
        the residual derived from ``maturity_date`` (1.0y here), not the
        seasoned ``original_maturity_years`` (5.0y). With t=1.0y < T=4.0y,
        Art. 239(3) scaling applies:
            GA = 1,000,000 x (1.0-0.25)/(4.0-0.25) = 200,000.0
            unguaranteed = 800,000.0
            RWA = 200,000.0 x 0.20 + 800,000.0 x 1.00 = 840,000.0

        Pre-fix (current): guarantees.py prefers original_maturity_years (5.0)
        over the residual, so t_eff=5.0 >= T_eff=4.0 -> no mismatch ->
        GA = 1,000,000.0 -> RWA = 200,000.0 — this test FAILS.

        Arrange: CRR config (reporting_date=2026-06-01), EXP-219 with G-219
                 (residual t=1.0y, original 5.0y, T=4.0y).
        Act:     Sum rwa_final across all EXP-219 sub-rows.
        Assert:  total rwa_final == 840,000.0 (abs=0.01).
        """
        # Arrange
        total_rwa = get_total_rwa(crr_sa_results, LOAN_REF)

        # Assert — FAILS pre-fix (engine returns 200,000.0)
        assert total_rwa == pytest.approx(EXPECTED_TOTAL_RWA, abs=0.01), (
            f"P1.219 CRR: total RWA should be {EXPECTED_TOTAL_RWA:,.10f} "
            f"(Art. 239(3) with residual t=1.0y: GA = 1,000,000 x "
            f"(1.0-0.25)/(4.0-0.25) = 200,000.0; "
            f"RWA = 200,000.0x0.20 + 800,000.0x1.00). "
            f"Got {total_rwa:,.4f}. "
            f"Pre-fix value {BUGGED_TOTAL_RWA:,.0f} means guarantees.py used the "
            f"seasoned original_maturity_years (5.0) instead of the residual (1.0), "
            f"treating t=5.0 >= T=4.0 as 'no mismatch'."
        )

    def test_p1_219_crr_guaranteed_and_unguaranteed_portions_use_residual_scaling(
        self, crr_sa_results: pl.DataFrame
    ) -> None:
        """
        P1.219 DISCRIMINATING: CRR guaranteed_portion == 200,000.0,
        unguaranteed_portion == 800,000.0.

        Art. 239(3) with residual t=1.0y: GA = 1,000,000 x 0.2 = 200,000.0.
        Pre-fix: guaranteed_portion = 1,000,000.0 (bug uses t=5.0 -> no scaling),
        unguaranteed_portion = 0.0.

        Arrange: CRR config, EXP-219 fully guaranteed by G-219
                 (residual t=1.0y < T=4.0y).
        Act:     Sum guaranteed_portion / unguaranteed_portion across EXP-219 sub-rows.
        Assert:  guaranteed_portion == 200,000.0; unguaranteed_portion == 800,000.0
                 (abs=0.01).
        """
        # Arrange
        sub_rows = crr_sa_results.filter(pl.col("parent_exposure_reference") == LOAN_REF)
        assert sub_rows.height > 0, f"No SA sub-rows for parent_exposure_reference='{LOAN_REF}'"
        guaranteed_portion = sub_rows["guaranteed_portion"].sum()
        unguaranteed_portion = sub_rows["unguaranteed_portion"].sum()

        # Assert — FAILS pre-fix (engine returns 1,000,000.0 / 0.0)
        assert guaranteed_portion == pytest.approx(EXPECTED_GUARANTEED_PORTION, abs=0.01), (
            f"P1.219 CRR: guaranteed_portion should be {EXPECTED_GUARANTEED_PORTION:,.10f} "
            f"(Art. 239(3): G* x (t-0.25)/(T-0.25) with residual t=1.0y). "
            f"Got {guaranteed_portion:,.4f}. "
            f"Pre-fix: guaranteed_portion = 1,000,000.0 (original_maturity_years "
            f"wins -> t=5.0 -> no scaling)."
        )
        assert unguaranteed_portion == pytest.approx(EXPECTED_UNGUARANTEED_PORTION, abs=0.01), (
            f"P1.219 CRR: unguaranteed_portion should be {EXPECTED_UNGUARANTEED_PORTION:,.10f} "
            f"(= EAD - scaled GA). "
            f"Got {unguaranteed_portion:,.4f}. "
            f"Pre-fix: unguaranteed_portion = 0.0 (bug treats guarantee as fully covering)."
        )

    def test_p1_219_crr_guaranteed_portion_risk_weight_is_20pct(
        self, crr_sa_results: pl.DataFrame
    ) -> None:
        """
        P1.219: CRR guaranteed-portion risk_weight == 0.20 (institution CQS 1, Art. 120).

        The substituted RW on the guaranteed sub-row must reflect the guarantor
        (CP-GUARANTOR-219, institution CQS 1 -> 20%) regardless of the
        maturity-mismatch fix (the RW lookup itself is unaffected by the `t`
        preference bug); it confirms the substitution routing is correct both
        before and after the fix.

        Arrange: CRR config, guaranteed-portion sub-row for EXP-219.
        Act:     risk_weight field on the __G_ sub-row.
        Assert:  risk_weight == 0.20 (abs=1e-6).
        """
        # Arrange
        row = get_guaranteed_row(crr_sa_results, LOAN_REF)

        # Assert
        actual_rw = row["risk_weight"]
        assert actual_rw == pytest.approx(EXPECTED_GUARANTOR_RW, abs=1e-6), (
            f"P1.219 CRR: guaranteed-portion risk_weight should be {EXPECTED_GUARANTOR_RW:.2f} "
            f"(institution CQS 1, Art. 120 Table 3). "
            f"Got {actual_rw:.4f}."
        )

    def test_p1_219_crr_remainder_sub_row_risk_weight_is_100pct(
        self, crr_sa_results: pl.DataFrame
    ) -> None:
        """
        P1.219: CRR remainder (``__REM``) sub-row risk_weight == 1.00 (unrated
        corporate borrower, Art. 122).

        Pre-fix, the guarantee is treated as fully covering EXP-219, so no
        ``__REM`` sub-row with non-zero EAD exists — this assertion only holds
        once the residual-t fix produces a genuine unguaranteed remainder.

        Arrange: CRR config, remainder sub-row for EXP-219.
        Act:     risk_weight field on the __REM sub-row.
        Assert:  risk_weight == 1.00 (abs=1e-6).
        """
        # Arrange
        rem_rows = crr_sa_results.filter(
            (pl.col("parent_exposure_reference") == LOAN_REF)
            & pl.col("exposure_reference").str.contains("__REM")
        ).to_dicts()
        assert len(rem_rows) == 1, (
            f"Expected exactly 1 remainder row for {LOAN_REF!r}, got {len(rem_rows)}. "
            f"All rows: "
            f"{crr_sa_results.select(['exposure_reference', 'parent_exposure_reference']).to_dicts()}"
        )
        actual_rw = rem_rows[0]["risk_weight"]

        # Assert — FAILS pre-fix (remainder EAD is 0, or the __REM row is degenerate)
        assert actual_rw == pytest.approx(_BORROWER_RW, abs=1e-6), (
            f"P1.219 CRR: remainder sub-row risk_weight should be {_BORROWER_RW:.2f} "
            f"(unrated corporate, Art. 122). "
            f"Got {actual_rw:.4f}."
        )

    # -------------------------------------------------------------------------
    # B31 FRAMEWORK-INVARIANCE PIN — must match CRR post-fix
    # -------------------------------------------------------------------------

    def test_p1_219_b31_total_rwa_equals_crr_value(self, b31_sa_results: pl.DataFrame) -> None:
        """
        P1.219 B31 framework-invariance: total RWA == 840,000.0 (same as CRR).

        Art. 239(3) is identical under PS1/26 (the ``is_crr`` guard on the
        scaling call was already removed by P1.200); the residual-vs-original
        `t` preference bug is framework-agnostic, so both CRR and Basel 3.1
        must yield the same RWA for the same fixture, both pre-fix (200,000.0)
        and post-fix (840,000.0).

        Arrange: B31 config, same EXP-219 + G-219 fixture.
        Act:     Sum rwa_final across all EXP-219 sub-rows.
        Assert:  total rwa_final == 840,000.0 (abs=0.01).
        """
        # Arrange
        total_rwa = get_total_rwa(b31_sa_results, LOAN_REF)

        # Assert — FAILS pre-fix (engine returns 200,000.0)
        assert total_rwa == pytest.approx(EXPECTED_TOTAL_RWA, abs=0.01), (
            f"P1.219 B31: total RWA should be {EXPECTED_TOTAL_RWA:,.10f} "
            f"(PS1/26 Art. 239(3) with residual t=1.0y, framework-invariant). "
            f"Got {total_rwa:,.4f}. "
            f"If this differs from the CRR value, the fix has introduced a "
            f"framework-conditional branch instead of a uniform residual-t fix."
        )

    # -------------------------------------------------------------------------
    # EAD INTEGRITY — structural regression guard (CRR)
    # -------------------------------------------------------------------------

    def test_p1_219_crr_total_ead_is_unchanged(self, crr_sa_results: pl.DataFrame) -> None:
        """
        P1.219: Art. 239(3) scales GA (covered amount), not EAD — total EAD = 1,000,000.

        Arrange: CRR config, EXP-219 drawn_amount = 1,000,000.
        Act:     Sum ead_final across all EXP-219 sub-rows.
        Assert:  total ead_final == 1,000,000 (abs=1.0).
        """
        # Arrange
        sub_rows = crr_sa_results.filter(pl.col("parent_exposure_reference") == LOAN_REF)
        total_ead = sub_rows["ead_final"].sum()

        # Assert
        assert total_ead == pytest.approx(1_000_000.0, abs=1.0), (
            f"P1.219 CRR: total ead_final across sub-rows should be 1,000,000 "
            f"(Art. 239(3) does not change EAD). "
            f"Got {total_ead:,.2f}"
        )
