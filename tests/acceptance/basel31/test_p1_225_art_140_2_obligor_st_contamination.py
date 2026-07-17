"""
P1.225: PS1/26 Art. 140(2) obligor-level short-term rating contamination
(Basel 3.1 twin).

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> SACalculator -> Aggregator

Key responsibilities:
- Same scenario as the CRR sibling
  (tests/acceptance/crr/test_p1_225_art_140_2_obligor_st_contamination.py)
  under ``CalculationConfig.basel_3_1()`` — the Art. 140(2) text is
  identical in both regimes (CRE21.17-21.18) and the short-term Table 7
  (CRR, landed P1.216) / Table 4A-6A (B31) risk weights this fixture's
  triggers exercise are numerically identical at CQS 2 (50%) and CQS 4
  (150%), so every expected value in this file is identical to the CRR
  sibling.

Hand-calculation (Basel 3.1, CalculationConfig.basel_3_1(), Table 4A-6A
CQS-to-RW — see tests/fixtures/p1_225/p1_225.py for the full derivation):

    E1 (CP-X, ST-CQS4 trigger):        RW = 1.50 (Table 4A-6A)     -> RWA = 1,500,000
    E2 (CP-X, unrated, long-term):     pre-fix RW = 1.00 (class default)
                                        post-fix RW = 1.50 (Art. 140(2)(a) 150% broadcast)
    E3 (CP-Y, ST-CQS2 trigger):        RW = 0.50 (Table 4A-6A)     -> RWA =   500,000
    E4 (CP-Y, unrated, short-term):    pre-fix RW = 0.20 (SCRA grade A preferential band,
                                        pipeline-confirmed identical under CRR/B31)
                                        post-fix RW = max(0.20, 1.00) = 1.00 (Art. 140(2)(b) floor)
    E5 (CP-X, 100% guaranteed by CP-GOV, sovereign CQS 1): guaranteed leg RW = 0.00,
        BOTH pre- and post-fix (unsecured exclusion — Art. 140(2)(a) never reaches
        a guaranteed leg regardless of CP-X's contamination state)
    E6 (CP-Z, isolated control, no ST-rated facility on this obligor): RW = 1.00,
        BOTH pre- and post-fix (no contamination trigger exists for this obligor)

    Portfolio total rwa_final (pipeline-observed baseline, both regimes):
        1,500,000 (E1) + 1,000,000 (E2) + 500,000 (E3) + 200,000 (E4)
        + 0 (E5 guaranteed leg) + 0 (E5 remainder, ead_final=0) + 1,000,000 (E6)
        = 4,200,000
    Post-fix expected total: 4,200,000 + 500,000 (E2 delta) + 800,000 (E4 delta)
        = 5,500,000

References:
    - PRA PS1/26 Art. 140(2) (CRE21.17-21.18): obligor-level short-term-
      assessment contamination — 150% broadcast (a) / 100% floor (b).
    - PRA PS1/26 Art. 120(2B) Table 4A / Art. 122(3) Table 6A: short-term
      credit assessment risk weights.
    - tests/fixtures/p1_225/p1_225.py: fixture builder, scenario constants,
      and the full hand-calculation this file's expected values are drawn
      from.
    - docs/plans/compliance-audit-crr-111-241-rectification.md:119-123
      (P1.225 finding).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.p1_225.p1_225 import (
    EXPECTED_RW_E1,
    EXPECTED_RW_E2_POST_FIX,
    EXPECTED_RW_E3,
    EXPECTED_RW_E4_POST_FIX_FLOOR,
    EXPECTED_RW_E5_GUARANTOR,
    EXPECTED_RW_E6_CONTROL,
    EXPECTED_RWA_E1,
    EXPECTED_RWA_E2_POST_FIX,
    EXPECTED_RWA_E3,
    EXPECTED_RWA_E6,
    LOAN_E1_REF,
    LOAN_E2_REF,
    LOAN_E3_REF,
    LOAN_E4_REF,
    LOAN_E5_REF,
    LOAN_E6_REF,
)
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_225"

# Same reporting date as the CRR sibling — the fixture's flag semantics
# don't depend on regime-effective-date arithmetic here.
_REPORTING_DATE = date(2027, 1, 31)

# Post-fix expected portfolio total: pipeline-observed baseline (4,200,000,
# see module docstring) + E2 delta (+500,000) + E4 delta (+800,000).
_EXPECTED_TOTAL_RWA_POST_FIX = 5_500_000.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_bundle() -> RawDataBundle:
    """Same P1.225 bundle as the CRR sibling — counterparty/loan/rating/guarantee."""
    return make_raw_bundle(
        facilities=pl.LazyFrame(
            schema={"facility_reference": pl.String, "counterparty_reference": pl.String}
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
        guarantees=pl.scan_parquet(_FIXTURES_DIR / "guarantee.parquet"),
    )


def _basel_31_config() -> CalculationConfig:
    """Basel 3.1 SA-only config, same reporting_date as the CRR sibling."""
    return CalculationConfig.basel_3_1(
        reporting_date=_REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )


def _row(df: pl.DataFrame, exposure_reference: str) -> dict:
    """Return the single SA result row for a non-split exposure_reference."""
    rows = df.filter(pl.col("exposure_reference") == exposure_reference).to_dicts()
    assert len(rows) == 1, (
        f"P1.225: expected exactly 1 row for {exposure_reference!r}, got {len(rows)}. "
        f"All exposure_references: {df['exposure_reference'].to_list()}"
    )
    return rows[0]


def _e5_guaranteed_leg(df: pl.DataFrame) -> dict:
    """The guarantor-substituted leg of E5 (is_guaranteed=True, guarantor CQS 1)."""
    rows = df.filter(
        (pl.col("parent_exposure_reference") == LOAN_E5_REF) & (pl.col("is_guaranteed") == True)  # noqa: E712
    ).to_dicts()
    assert len(rows) == 1, (
        f"P1.225: expected exactly 1 guaranteed-leg row for {LOAN_E5_REF!r}, got {len(rows)}."
    )
    return rows[0]


def _e5_remainder_leg(df: pl.DataFrame) -> dict:
    """The borrower-retained remainder leg of E5 (is_guaranteed=False, ead_final=0)."""
    rows = df.filter(
        (pl.col("parent_exposure_reference") == LOAN_E5_REF) & (pl.col("is_guaranteed") == False)  # noqa: E712
    ).to_dicts()
    assert len(rows) == 1, (
        f"P1.225: expected exactly 1 remainder-leg row for {LOAN_E5_REF!r}, got {len(rows)}."
    )
    return rows[0]


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def sa_results() -> pl.DataFrame:
    """B31 SA pipeline results over the full P1.225 fixture set (one run)."""
    bundle = _build_bundle()
    results = PipelineOrchestrator().run_with_data(bundle, _basel_31_config())
    assert results.sa_results is not None, (
        "SA results should not be None — check PermissionMode.STANDARDISED config"
    )
    return results.sa_results.collect()


# ---------------------------------------------------------------------------
# P1.225 acceptance tests — Basel 3.1
# ---------------------------------------------------------------------------


class TestP1225Art1402ObligorSTContaminationB31:
    """P1.225: B31 Art. 140(2) obligor-level ST contamination — 150% broadcast / 100% floor."""

    # -------------------------------------------------------------------------
    # Item 1 — E2 contamination (Art. 140(2)(a)). DISCRIMINATING: FAILS today.
    # -------------------------------------------------------------------------

    def test_p1_225_e2_contaminated_to_150_pct(self, sa_results: pl.DataFrame) -> None:
        """
        P1.225 DISCRIMINATING: E2 (CP-X, unrated long-term unsecured) must
        be contaminated to 150% by CP-X's ST-CQS4 trigger (E1).

        Arrange: LN_P225_E2 (unrated, long-term, unsecured, same obligor as
                 E1's ST-CQS4 150% trigger).
        Act:     full B31 SA pipeline.
        Assert:  risk_weight == 1.50, rwa_final == 1,500,000.

        FAILS today: the engine applies the per-exposure-only override, so
        E2 keeps its class-default 100% (risk_weight=1.00,
        rwa_final=1,000,000) — Art. 140(2)(a)'s "short- OR long-term"
        broadcast never reaches it.
        """
        row = _row(sa_results, LOAN_E2_REF)

        assert row["risk_weight"] == pytest.approx(EXPECTED_RW_E2_POST_FIX, abs=1e-4), (
            f"P1.225 (B31): expected E2 risk_weight={EXPECTED_RW_E2_POST_FIX:.2f} "
            f"(Art. 140(2)(a) 150% contamination from CP-X's ST-CQS4 trigger), "
            f"got {row['risk_weight']:.4f}"
        )
        assert row["rwa_final"] == pytest.approx(EXPECTED_RWA_E2_POST_FIX, rel=1e-4), (
            f"P1.225 (B31): expected E2 rwa_final={EXPECTED_RWA_E2_POST_FIX:,.0f} "
            f"(EAD 1,000,000 x 150%), got {row['rwa_final']:,.2f}"
        )

    # -------------------------------------------------------------------------
    # Item 2 — E4 floor (Art. 140(2)(b)). DISCRIMINATING: FAILS today.
    # -------------------------------------------------------------------------

    def test_p1_225_e4_floored_at_100_pct(self, sa_results: pl.DataFrame) -> None:
        """
        P1.225 DISCRIMINATING: E4 (CP-Y, unrated short-term unsecured) must
        be floored at 100% by CP-Y's ST-CQS2 trigger (E3).

        Arrange: LN_P225_E4 (unrated, short-term, unsecured, SCRA grade A
                 preferential band 20%, same obligor as E3's ST-CQS2 50%
                 trigger).
        Act:     full B31 SA pipeline.
        Assert:  risk_weight == 1.00 (max(20%, 100%)), rwa_final == 1,000,000.

        FAILS today: the engine keeps E4 on the SCRA grade A preferential
        20% band (risk_weight=0.20, rwa_final=200,000) — Art. 140(2)(b)'s
        100% floor never reaches it.
        """
        row = _row(sa_results, LOAN_E4_REF)

        assert row["risk_weight"] == pytest.approx(EXPECTED_RW_E4_POST_FIX_FLOOR, abs=1e-4), (
            f"P1.225 (B31): expected E4 risk_weight={EXPECTED_RW_E4_POST_FIX_FLOOR:.2f} "
            f"(Art. 140(2)(b) 100% floor, max(20%, 100%)), got {row['risk_weight']:.4f}"
        )
        assert row["rwa_final"] == pytest.approx(1_000_000.0, rel=1e-4), (
            f"P1.225 (B31): expected E4 rwa_final=1,000,000 (EAD 1,000,000 x 100% floor), "
            f"got {row['rwa_final']:,.2f}"
        )

    # -------------------------------------------------------------------------
    # Item 3 — triggers unchanged. PASS today, must stay green.
    # -------------------------------------------------------------------------

    def test_p1_225_e1_trigger_unchanged(self, sa_results: pl.DataFrame) -> None:
        """
        P1.225: E1 (the ST-CQS4 150% trigger itself) is unaffected by the
        contamination fix — it already carries its own issue-specific
        short-term risk weight directly.

        Arrange: LN_P225_E1, loan-scoped ST-CQS4 rating.
        Act:     full B31 SA pipeline.
        Assert:  risk_weight == 1.50, rwa_final == 1,500,000.

        Should PASS today and MUST still pass after — this is a regression
        pin, not a discriminating test.
        """
        row = _row(sa_results, LOAN_E1_REF)

        assert row["risk_weight"] == pytest.approx(EXPECTED_RW_E1, abs=1e-4), (
            f"P1.225 (B31): expected E1 risk_weight={EXPECTED_RW_E1:.2f} (CQS 4), "
            f"got {row['risk_weight']:.4f}"
        )
        assert row["rwa_final"] == pytest.approx(EXPECTED_RWA_E1, rel=1e-4), (
            f"P1.225 (B31): expected E1 rwa_final={EXPECTED_RWA_E1:,.0f}, "
            f"got {row['rwa_final']:,.2f}"
        )

    def test_p1_225_e3_trigger_unchanged(self, sa_results: pl.DataFrame) -> None:
        """
        P1.225: E3 (the ST-CQS2 50% trigger itself) is unaffected by the
        contamination fix — its own rating already carries the short-term
        risk weight, and CP-Y has no 150%-attracting facility so only the
        (b) floor arm is ever active on this obligor.

        Arrange: LN_P225_E3, loan-scoped ST-CQS2 rating.
        Act:     full B31 SA pipeline.
        Assert:  risk_weight == 0.50, rwa_final == 500,000.

        Should PASS today and MUST still pass after.
        """
        row = _row(sa_results, LOAN_E3_REF)

        assert row["risk_weight"] == pytest.approx(EXPECTED_RW_E3, abs=1e-4), (
            f"P1.225 (B31): expected E3 risk_weight={EXPECTED_RW_E3:.2f} (CQS 2), "
            f"got {row['risk_weight']:.4f}"
        )
        assert row["rwa_final"] == pytest.approx(EXPECTED_RWA_E3, rel=1e-4), (
            f"P1.225 (B31): expected E3 rwa_final={EXPECTED_RWA_E3:,.0f}, "
            f"got {row['rwa_final']:,.2f}"
        )

    # -------------------------------------------------------------------------
    # Item 4 — control obligor. PASS today, must stay green.
    # -------------------------------------------------------------------------

    def test_p1_225_e6_isolated_control_unchanged(self, sa_results: pl.DataFrame) -> None:
        """
        P1.225: E6 (CP-Z, isolated obligor with no ST-rated facility
        anywhere) never moves — no contamination trigger exists for CP-Z.

        Arrange: LN_P225_E6, unrated long-term corporate, isolated obligor.
        Act:     full B31 SA pipeline.
        Assert:  risk_weight == 1.00, rwa_final == 1,000,000.

        Should PASS today and MUST still pass after — proves the fix is
        scoped per-obligor, not portfolio-wide.
        """
        row = _row(sa_results, LOAN_E6_REF)

        assert row["risk_weight"] == pytest.approx(EXPECTED_RW_E6_CONTROL, abs=1e-4), (
            f"P1.225 (B31): expected E6 risk_weight={EXPECTED_RW_E6_CONTROL:.2f} "
            f"(unrated corporate class default, no ST trigger on CP-Z), "
            f"got {row['risk_weight']:.4f}"
        )
        assert row["rwa_final"] == pytest.approx(EXPECTED_RWA_E6, rel=1e-4), (
            f"P1.225 (B31): expected E6 rwa_final={EXPECTED_RWA_E6:,.0f}, "
            f"got {row['rwa_final']:,.2f}"
        )

    # -------------------------------------------------------------------------
    # Item 5 — unsecured exclusion. PASS today, must stay green.
    # -------------------------------------------------------------------------

    def test_p1_225_e5_guaranteed_leg_excluded_from_contamination(
        self, sa_results: pl.DataFrame
    ) -> None:
        """
        P1.225: E5's GUARANTEED leg keeps its guarantor-substituted risk
        weight (0.00, sovereign CQS 1) regardless of CP-X's contamination
        state — a guaranteed exposure is not "unsecured", so Art. 140(2)(a)
        never reaches it.

        Arrange: LN_P225_E5, 100% guaranteed by CP_P225_GOV (sovereign CQS 1).
        Act:     full B31 SA pipeline.
        Assert:  guaranteed-leg risk_weight == 0.00.

        Should PASS today and MUST still pass after — proves the
        "unsecured" exclusion holds even though E5 shares CP-X (the
        150%-contaminated obligor) with E1/E2.

        NOTE: the REMAINDER leg's risk_weight is deliberately NOT pinned —
        it has ead_final=0 and, being an unrated unsecured leg of a
        contaminated obligor, may legitimately flip 1.00 -> 1.50 post-fix
        with zero RWA effect. Its rwa_final==0 invariant is pinned instead
        (see test_p1_225_e5_remainder_leg_ead_and_rwa_are_zero).
        """
        row = _e5_guaranteed_leg(sa_results)

        assert row["risk_weight"] == pytest.approx(EXPECTED_RW_E5_GUARANTOR, abs=1e-6), (
            f"P1.225 (B31): expected E5 guaranteed-leg risk_weight="
            f"{EXPECTED_RW_E5_GUARANTOR:.2f} (sovereign CQS 1, unaffected by CP-X's "
            f"contamination — a guaranteed leg is not unsecured), "
            f"got {row['risk_weight']:.4f}"
        )

    def test_p1_225_e5_remainder_leg_ead_and_rwa_are_zero(self, sa_results: pl.DataFrame) -> None:
        """
        P1.225: E5's REMAINDER leg (fully guaranteed, 0% retained) carries
        zero EAD and zero RWA, both pre- and post-fix — its risk_weight is
        deliberately not pinned (see the guaranteed-leg test docstring).

        Arrange: LN_P225_E5, 100% guaranteed — the remainder leg is the
                 borrower-retained 0% tranche.
        Act:     full B31 SA pipeline.
        Assert:  ead_final == 0, rwa_final == 0.
        """
        row = _e5_remainder_leg(sa_results)

        assert row["ead_final"] == pytest.approx(0.0, abs=1.0), (
            f"P1.225 (B31): expected E5 remainder-leg ead_final=0, got {row['ead_final']:,.2f}"
        )
        assert row["rwa_final"] == pytest.approx(0.0, abs=1.0), (
            f"P1.225 (B31): expected E5 remainder-leg rwa_final=0 (ead_final=0 "
            f"regardless of risk_weight), got {row['rwa_final']:,.2f}"
        )

    # -------------------------------------------------------------------------
    # Item 6 — cross-check totals. DISCRIMINATING: FAILS today.
    # -------------------------------------------------------------------------

    def test_p1_225_portfolio_total_rwa_reflects_full_contamination(
        self, sa_results: pl.DataFrame
    ) -> None:
        """
        P1.225 DISCRIMINATING: portfolio total rwa_final reflects BOTH the
        E2 broadcast and E4 floor deltas simultaneously.

        Derivation: pipeline-observed pre-fix baseline (both regimes)
            1,500,000 (E1) + 1,000,000 (E2) + 500,000 (E3) + 200,000 (E4)
            + 0 (E5 guaranteed leg) + 0 (E5 remainder, ead_final=0)
            + 1,000,000 (E6) = 4,200,000
        Post-fix: 4,200,000 + 500,000 (E2: 1,000,000 -> 1,500,000)
                            + 800,000 (E4: 200,000 -> 1,000,000)
                = 5,500,000

        Arrange: all six P1.225 loans in one pipeline run.
        Act:     full B31 SA pipeline; sum rwa_final across all rows.
        Assert:  total rwa_final == 5,500,000.

        FAILS today: total is 4,200,000 (E2/E4 uncontaminated). This is a
        redundant cross-check against test_p1_225_e2_contaminated_to_150_pct
        / test_p1_225_e4_floored_at_100_pct — it also catches a fix that
        gets E2/E4 individually right but accidentally perturbs E1/E3/E5/E6.
        """
        total_rwa = sa_results["rwa_final"].sum()

        assert total_rwa == pytest.approx(_EXPECTED_TOTAL_RWA_POST_FIX, rel=1e-4), (
            f"P1.225 (B31): expected portfolio total rwa_final="
            f"{_EXPECTED_TOTAL_RWA_POST_FIX:,.0f} (pre-fix baseline 4,200,000 "
            f"+ E2 delta 500,000 + E4 delta 800,000), got {total_rwa:,.2f}"
        )

    # -------------------------------------------------------------------------
    # Probe: has_short_term_ecai must NOT be the contamination mechanism.
    # -------------------------------------------------------------------------

    def test_p1_225_e2_e4_do_not_carry_own_short_term_ecai_flag(
        self, sa_results: pl.DataFrame
    ) -> None:
        """
        P1.225 probe (per team-lead request): confirm E2/E4 do not carry
        the P1.223 ``has_short_term_ecai`` spillover flag — Art. 140(2)
        obligor contamination is a DISTINCT mechanism from Art. 120(3)(c)'s
        short-term-only spillover (P1.223), and E2/E4 are contaminated via
        Art. 140(2), never via their own issue-specific ST rating.

        Confirmed unambiguous via a live pipeline run: ``has_short_term_ecai``
        is False on both E2 and E4 under B31 today. Should PASS today and
        after the fix — the two mechanisms must remain independent.
        """
        e2 = _row(sa_results, LOAN_E2_REF)
        e4 = _row(sa_results, LOAN_E4_REF)

        assert e2["has_short_term_ecai"] is False, (
            f"P1.225 (B31): E2 has_short_term_ecai should be False (E2 has no "
            f"issue-specific ST rating of its own — it is contaminated via "
            f"Art. 140(2), not Art. 120(3)(c)), got {e2['has_short_term_ecai']!r}"
        )
        assert e4["has_short_term_ecai"] is False, (
            f"P1.225 (B31): E4 has_short_term_ecai should be False (E4 has no "
            f"issue-specific ST rating of its own — it is floored via Art. 140(2)(b), "
            f"not Art. 120(3)(c)), got {e4['has_short_term_ecai']!r}"
        )
