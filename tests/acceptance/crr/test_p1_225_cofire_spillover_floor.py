"""
P1.225 co-fire: Art. 140(2)(b) 100% floor must bind through the Art. 120(3)(c)
short-term obligor spillover (CRR).

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> SACalculator -> Aggregator

Regression scenario (verified defect in the just-landed P1.225, commit 4055b3a0):
    The Art. 140(2)(b) obligor floor is silently defeated when the pre-existing
    P1.223 Art. 120(3)(c) short-term spillover co-fires on the SAME obligor.

    The spillover (``_apply_obligor_short_term_spillover``) overwrites a spilled
    leg's ``cqs`` (null -> the assessment cqs) and ``has_short_term_ecai``
    (False -> True). The pre-fix SA floor predicate
    ``cqs.is_null() & ~has_short_term_ecai`` then reads both conditions as
    False and skips the leg, so Art. 140(2)(b)'s 100% floor never reaches it —
    a 50pp anti-conservative understatement (0.50 instead of >=1.00).

Fixture (reuses the P1.223 builders with the issue-specific short-term ECAI
assessment flipped CQS 3 -> 2, so it now maps to the 50% Table 7 band):

    INST-001 (institution): counterparty-wide long-term ECAI rating CQS 2,
    PLUS an issue-specific short-term assessment CQS 2 scoped to FAC-A.

    | ref  | facility | maturity   | rating                | role                          |
    |------|----------|------------|-----------------------|-------------------------------|
    | LN-A | FAC-A    | short (ST) | ST-CQS2 (50%, Tbl 7)  | trigger — carries own ST rtg  |
    | LN-B | FAC-B    | short (ST) | unrated               | TARGET — spilled AND floored  |
    | LN-C | FAC-C    | LONG (5y)  | unrated (LT inherited)| control — long-term, no floor |

Hand-calculation (CRR, ``CalculationConfig.crr()``, Art. 131 Table 7 CQS->RW):

    Step 1 — LN-A directly matches the FAC-A-scoped ST assessment: cqs 2,
             has_short_term_ecai=True, has_own_short_term_ecai=True.
    Step 2 — Art. 120(3)(c) spillover: obligor general cqs = 2 (Table 4 20%),
             worst obligor ST-assessment cqs = 2 (Table 7 50%). 50% > 20% ->
             less favourable -> fires. LN-B (unrated ST claim) is spilled:
             cqs null -> 2, has_short_term_ecai False -> True. LN-C (long-term)
             is outside the ST window -> unaffected.
    Step 3 — Base SA risk weights:
             LN-A: Table 7 CQS 2                       -> 0.50
             LN-B: spilled -> Table 7 CQS 2            -> 0.50 (pre-floor)
             LN-C: long-term ECRA Table 3 CQS 2 (CRR)  -> 0.50
    Step 4 — Art. 140(2)(b) obligor floor: INST-001 carries a 50%-attracting ST
             assessment (LN-A) -> floor its UNRATED short-term unsecured claims
             at 100%. LN-A is rated (own assessment) -> not floored. LN-B is
             unrated (spilled, no own assessment) -> floored: max(0.50, 1.00)
             = 1.00. LN-C is long-term -> outside the (b) floor scope.
    Step 5 — RWA = EAD (drawn) x RW:
             LN-A: 1,000,000 x 0.50 =   500,000
             LN-B: 2,000,000 x 1.00 = 2,000,000  (pre-fix bug: x 0.50 = 1,000,000)
             LN-C: 4,000,000 x 0.50 = 2,000,000

Headline discriminating assertion: LN-B.risk_weight == 1.00 (pre-fix engine
returns 0.50). LN-A (0.50) and LN-C (0.50 CRR) are regression guards proving
the floor is scoped to the unrated spilled leg only.

References:
    - CRR Art. 140(2)(b) (CRE21.17-21.18): 100% floor on an obligor's unrated
      short-term claims when a 50%-attracting short-term assessment exists.
    - CRR Art. 120(3)(c): obligor-level short-term spillover (P1.223).
    - CRR Art. 131 Table 7: short-term credit assessment risk weights.
    - tests/fixtures/p1_223/p1_223.py: the reused fixture builders.
    - tests/acceptance/crr/test_p1_225_art_140_2_obligor_st_contamination.py:
      the sibling P1.225 acceptance suite (no counterparty-level rating, so
      the spillover never co-fires there).
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from tests.fixtures.p1_223.p1_223 import (
    DRAWN_A,
    DRAWN_B,
    DRAWN_C,
    EXPECTED_RISK_WEIGHT_LN_C_CRR,
    LOAN_REF_A,
    LOAN_REF_B,
    LOAN_REF_C,
    create_p1223_counterparty,
    create_p1223_facilities,
    create_p1223_facility_mappings,
    create_p1223_loans,
    create_p1223_ratings,
)
from tests.fixtures.raw_bundle import make_raw_bundle

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator

# Reporting date strictly before the ST maturity (2027-03-15), mirroring the
# P1.223 REPORTING_DATE_GUIDANCE.
_REPORTING_DATE = date(2027, 2, 1)

# Expected co-fire risk weights / RWAs (CRR).
_EXPECTED_RW_LN_A = 0.50  # own ST-CQS2 assessment, Table 7 — not floored
_EXPECTED_RW_LN_B_POST_FIX = 1.00  # Art. 140(2)(b) floor over the spilled 0.50
_ILLUSTRATIVE_RW_LN_B_PRE_FIX = 0.50  # bug: floor defeated by the spillover
_EXPECTED_RWA_LN_A = DRAWN_A * _EXPECTED_RW_LN_A  # 500,000
_EXPECTED_RWA_LN_B_POST_FIX = DRAWN_B * _EXPECTED_RW_LN_B_POST_FIX  # 2,000,000
_EXPECTED_RWA_LN_C_CRR = DRAWN_C * EXPECTED_RISK_WEIGHT_LN_C_CRR  # 2,000,000


def _cofire_ratings() -> pl.DataFrame:
    """P1.223 ratings with the issue-specific ST assessment flipped CQS 3 -> 2.

    Flipping the short-term row to CQS 2 (the 50% Table 7 band) turns the
    P1.223 spillover fixture into the P1.225 co-fire: the obligor now carries a
    50%-attracting short-term assessment, so Art. 140(2)(b)'s 100% floor must
    bind on the spilled unrated leg. The long-term counterparty rating stays
    CQS 2.
    """
    ratings = create_p1223_ratings()
    cqs_dtype = ratings.schema["cqs"]
    return ratings.with_columns(
        pl.when(pl.col("is_short_term"))
        .then(pl.lit(2, dtype=cqs_dtype))
        .otherwise(pl.col("cqs"))
        .alias("cqs")
    )


def _build_bundle() -> RawDataBundle:
    """Reuse the P1.223 obligor/facility/loan shape with the co-fire ratings."""
    return make_raw_bundle(
        facilities=create_p1223_facilities(),
        loans=create_p1223_loans(),
        counterparties=create_p1223_counterparty(),
        facility_mappings=create_p1223_facility_mappings(),
        lending_mappings=pl.LazyFrame(
            schema={
                "parent_counterparty_reference": pl.String,
                "child_counterparty_reference": pl.String,
            }
        ),
        ratings=_cofire_ratings(),
    )


def _crr_config() -> CalculationConfig:
    """CRR SA-only config, reporting date before the ST maturity."""
    return CalculationConfig.crr(
        reporting_date=_REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )


def _row(df: pl.DataFrame, exposure_reference: str) -> dict:
    """Return the single SA result row for a loan exposure_reference."""
    rows = df.filter(pl.col("exposure_reference") == exposure_reference).to_dicts()
    assert len(rows) == 1, (
        f"P1.225 co-fire: expected exactly 1 row for {exposure_reference!r}, got {len(rows)}. "
        f"All exposure_references: {df['exposure_reference'].to_list()}"
    )
    return rows[0]


@pytest.fixture(scope="module")
def sa_results() -> pl.DataFrame:
    """CRR SA pipeline results over the co-fire fixture (one run)."""
    bundle = _build_bundle()
    results = PipelineOrchestrator().run_with_data(bundle, _crr_config())
    assert results.sa_results is not None, (
        "SA results should not be None — check PermissionMode.STANDARDISED config"
    )
    return results.sa_results.collect()


class TestP1225CofireSpilloverFloorCRR:
    """Art. 140(2)(b) floor binds even when the Art. 120(3)(c) spillover co-fires (CRR)."""

    # -------------------------------------------------------------------------
    # Item 1 — LN-B floor. DISCRIMINATING: FAILS today.
    # -------------------------------------------------------------------------

    def test_cofire_ln_b_floored_at_100_pct(self, sa_results: pl.DataFrame) -> None:
        """
        P1.225 co-fire DISCRIMINATING: LN-B (unrated short-term unsecured, same
        obligor as the 50% ST trigger) must be floored at 100% even though the
        Art. 120(3)(c) spillover first moved it to 50%.

        FAILS today: the spillover overwrites LN-B's cqs (null -> 2) and
        has_short_term_ecai (False -> True), so the pre-fix floor predicate
        (cqs.is_null() & ~has_short_term_ecai) drops it and LN-B keeps the
        spilled 50% (rwa_final 1,000,000).
        """
        row = _row(sa_results, LOAN_REF_B)

        assert row["risk_weight"] >= 1.00, (
            f"P1.225 co-fire: LN-B risk_weight must be floored >= 1.00 "
            f"(Art. 140(2)(b)); pre-fix bug returns {_ILLUSTRATIVE_RW_LN_B_PRE_FIX:.2f} "
            f"because the Art. 120(3)(c) spillover defeats the floor predicate. "
            f"Got {row['risk_weight']:.4f}"
        )
        assert row["risk_weight"] == pytest.approx(_EXPECTED_RW_LN_B_POST_FIX, abs=1e-4), (
            f"P1.225 co-fire: expected LN-B risk_weight={_EXPECTED_RW_LN_B_POST_FIX:.2f} "
            f"(max(spilled 0.50, 100% floor)), got {row['risk_weight']:.4f}"
        )
        assert row["rwa_final"] == pytest.approx(_EXPECTED_RWA_LN_B_POST_FIX, rel=1e-4), (
            f"P1.225 co-fire: expected LN-B rwa_final={_EXPECTED_RWA_LN_B_POST_FIX:,.0f} "
            f"(EAD 2,000,000 x 100% floor), got {row['rwa_final']:,.2f}"
        )

    # -------------------------------------------------------------------------
    # Item 2 — the co-fire condition itself. Proves this is the spillover path.
    # -------------------------------------------------------------------------

    def test_cofire_ln_b_carries_spilled_short_term_flag(self, sa_results: pl.DataFrame) -> None:
        """
        P1.225 co-fire: LN-B carries has_short_term_ecai=True from the
        Art. 120(3)(c) spillover, yet is still floored — this is the exact
        condition that defeated the pre-fix floor. Distinguishes this scenario
        from P1.225 E4 (has_short_term_ecai=False, no counterparty rating, so no
        spillover fires there).

        The flag is True both pre- and post-fix (the spillover is unchanged);
        the fix is that the floor now binds despite it.
        """
        row = _row(sa_results, LOAN_REF_B)

        assert row["has_short_term_ecai"] is True, (
            f"P1.225 co-fire: LN-B should carry the spilled has_short_term_ecai flag "
            f"(Art. 120(3)(c) co-fire), got {row['has_short_term_ecai']!r}"
        )

    # -------------------------------------------------------------------------
    # Item 3 — trigger unchanged. PASS today, must stay green.
    # -------------------------------------------------------------------------

    def test_cofire_ln_a_trigger_unchanged(self, sa_results: pl.DataFrame) -> None:
        """
        P1.225 co-fire: LN-A (the directly-rated 50% ST trigger) keeps its own
        Table 7 CQS 2 risk weight — a rated leg is the contamination SOURCE,
        never a floor target.
        """
        row = _row(sa_results, LOAN_REF_A)

        assert row["risk_weight"] == pytest.approx(_EXPECTED_RW_LN_A, abs=1e-4), (
            f"P1.225 co-fire: expected LN-A risk_weight={_EXPECTED_RW_LN_A:.2f} "
            f"(Table 7 CQS 2, own assessment — not floored), got {row['risk_weight']:.4f}"
        )
        assert row["rwa_final"] == pytest.approx(_EXPECTED_RWA_LN_A, rel=1e-4), (
            f"P1.225 co-fire: expected LN-A rwa_final={_EXPECTED_RWA_LN_A:,.0f}, "
            f"got {row['rwa_final']:,.2f}"
        )

    # -------------------------------------------------------------------------
    # Item 4 — long-term control. PASS today, must stay green.
    # -------------------------------------------------------------------------

    def test_cofire_ln_c_long_term_control_unchanged(self, sa_results: pl.DataFrame) -> None:
        """
        P1.225 co-fire: LN-C (long-term unrated sibling of the same obligor) is
        NOT floored — Art. 140(2)(b) reaches only short-term claims, and LN-C is
        outside the ST window (5-year maturity). Keeps the CRR long-term ECRA
        Table 3 CQS 2 weight (50%). Proves the floor is scoped to short-term.
        """
        row = _row(sa_results, LOAN_REF_C)

        assert row["risk_weight"] == pytest.approx(EXPECTED_RISK_WEIGHT_LN_C_CRR, abs=1e-4), (
            f"P1.225 co-fire: expected LN-C risk_weight={EXPECTED_RISK_WEIGHT_LN_C_CRR:.2f} "
            f"(CRR long-term ECRA CQS 2, unaffected by the short-term floor), "
            f"got {row['risk_weight']:.4f}"
        )
        assert row["rwa_final"] == pytest.approx(_EXPECTED_RWA_LN_C_CRR, rel=1e-4), (
            f"P1.225 co-fire: expected LN-C rwa_final={_EXPECTED_RWA_LN_C_CRR:,.0f}, "
            f"got {row['rwa_final']:,.2f}"
        )
