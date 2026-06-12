"""
P2.44 — SA-SL inferred-rating disapplication (Art. 139(2B)).

Pipeline position:
    Loader → HierarchyResolver → Classifier → CRMProcessor → SACalculator → Aggregator

Scenario design:
    An object_finance SA specialised-lending exposure has a single external rating
    that is inferred (rating_is_inferred=True, rating_is_issue_specific=False).

    Art. 139(2B) of PRA PS1/26 disapplies the Art. 139(2)/(2A) inferred-rating
    fallbacks for exposures routed under Art. 122B(1) (SA specialised-lending
    sub-classes). Because the only available rating is inferred, the engine MUST
    treat the exposure as unrated and apply the Art. 122B(2)(a) object-finance
    100% risk weight.

    Current (pre-fix) engine behaviour:
        The inferred CQS=3 is honoured (rating_is_inferred is not yet read from
        the ratings parquet — RATINGS_SCHEMA does not yet include the column).
        The SA namespace SL override at sa/namespace.py:1249-1258 only fires when
        cqs is null or <= 0; CQS=3 causes the rated-corporate path to apply →
        risk_weight = 0.75 (Art. 122(2) Table 6, CQS-3 corporate B31).

    Post-fix expected behaviour:
        Engine reads rating_is_inferred=True from the ratings parquet, suppresses
        the inferred rating under Art. 139(2B) for the Art. 122B(1) SL path, and
        treats the exposure as unrated → risk_weight = 1.00 (Art. 122B(2)(a)).

    Failure mode (current):
        assert risk_weight == 1.00
        AssertionError: risk_weight is 0.75 (CQS-3 corporate 75% used instead of
        Art. 122B(2)(a) unrated object-finance 100%)

Expected outputs (post-fix):
    risk_weight         = 1.00  (100%, Art. 122B(2)(a) unrated object-finance)
    ead_final           = 1,000,000 GBP
    rwa_final           = 1,000,000 GBP
    exposure_class_sa   = "corporate"  (SA sub-type for SL)
    sl_type             = "object_finance"

Anti-assertion (current engine yields this, post-fix MUST NOT):
    risk_weight != 0.75  (CQS-3 corporate Basel 3.1 = 75%)
    rwa_final   != 750,000

Regulatory references:
    - PRA PS1/26 Art. 122B(1): SA routing for specialised-lending sub-classes
    - PRA PS1/26 Art. 122B(2)(a): unrated object-finance risk weight = 100%
    - PRA PS1/26 Art. 139(2B): disapplies inferred-rating fallbacks for
      the Art. 122B(1) SA-SL routing path
    - PRA PS1/26 Art. 139(2)/(2A): inferred-rating fallbacks (disapplied here)
    - data/tables/b31_risk_weights.py: B31_SA_SL_RISK_WEIGHTS["object_finance"] = 1.00

Code references:
    - tests/fixtures/p2_44/p2_44.py: fixture constants and parquet generators
    - src/rwa_calc/data/schemas.py: RATINGS_SCHEMA (needs rating_is_inferred column)
    - src/rwa_calc/engine/sa/namespace.py:1249-1258: SL unrated override
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import cast

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.p2_44.p2_44 import (
    ANTI_EXPECTED_RISK_WEIGHT,
    EXPECTED_EAD,
    EXPECTED_EXPOSURE_CLASS_SA,
    EXPECTED_RISK_WEIGHT,
    EXPECTED_RWA,
    EXPECTED_SL_TYPE,
    EXPOSURE_REF,
)
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Fixture directory
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p2_44"

# ---------------------------------------------------------------------------
# Pipeline helpers
# ---------------------------------------------------------------------------


def _build_p2_44_bundle() -> RawDataBundle:
    """
    Load P2.44 parquet fixtures and assemble a RawDataBundle.

    Provides:
        - One SL object-finance counterparty (CP_P244, specialised_lending, GB)
        - Specialised-lending metadata (sl_type=object_finance, is_hvcre=False)
        - One on-balance loan (EXP_P244, GBP 1,000,000, senior, provisions=0)
        - One external rating (RT_P244, CQS=3, rating_is_inferred=True,
          rating_is_issue_specific=False)

    The rating parquet includes two extra Boolean columns not yet in RATINGS_SCHEMA:
        rating_is_issue_specific=False
        rating_is_inferred=True

    The engine-implementer wave must add these columns to RATINGS_SCHEMA and
    update the SA SL namespace to suppress the inferred rating under Art. 139(2B).
    """
    facility_mappings = pl.LazyFrame(
        schema={
            "parent_facility_reference": pl.String,
            "child_reference": pl.String,
            "child_type": pl.String,
        }
    )
    lending_mappings = pl.LazyFrame(
        schema={
            "parent_counterparty_reference": pl.String,
            "child_counterparty_reference": pl.String,
        }
    )

    return make_raw_bundle(
        facilities=pl.scan_parquet(_FIXTURES_DIR / "facility.parquet"),
        loans=pl.scan_parquet(_FIXTURES_DIR / "loan.parquet"),
        counterparties=pl.scan_parquet(_FIXTURES_DIR / "counterparty.parquet"),
        ratings=pl.scan_parquet(_FIXTURES_DIR / "rating.parquet"),
        specialised_lending=pl.scan_parquet(_FIXTURES_DIR / "sl_metadata.parquet"),
        facility_mappings=facility_mappings,
        lending_mappings=lending_mappings,
    )


def _b31_sa_config() -> CalculationConfig:
    """
    Basel 3.1 SA-only config.

    Reporting date 2027-06-30 — post Basel 3.1 effective date (1 Jan 2027).
    PermissionMode.STANDARDISED forces the SA path; no IRB routing.
    """
    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 30),
        permission_mode=PermissionMode.STANDARDISED,
    )


# ---------------------------------------------------------------------------
# Module-scoped SA results fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def p2_44_sa_results() -> pl.DataFrame:
    """
    Run P2.44 fixtures through the Basel 3.1 SA pipeline and return SA results.

    Arrange: CP_P244 (specialised_lending, GB) with sl_type=object_finance,
             EXP_P244 (GBP 1,000,000, senior), rating RT_P244 (CQS=3,
             rating_is_inferred=True, rating_is_issue_specific=False).
             Basel 3.1 SA-only config, 2027-06-30.
    Act:     PipelineOrchestrator().run_with_data(bundle, config).sa_results.
    Return:  Collected SA results DataFrame for all assertions.
    """
    bundle = _build_p2_44_bundle()
    config = _b31_sa_config()
    results = PipelineOrchestrator().run_with_data(bundle, config)
    assert results.sa_results is not None, (
        "SA results should not be None — check PermissionMode.STANDARDISED config "
        "and that the SL specialised-lending counterparty routes to SA."
    )
    return cast(pl.DataFrame, results.sa_results.collect())


def _get_exposure_row(df: pl.DataFrame) -> dict:
    """Return the single SA result row for EXP_P244."""
    rows = df.filter(pl.col("exposure_reference") == EXPOSURE_REF).to_dicts()
    assert len(rows) == 1, (
        f"Expected exactly 1 SA result row for {EXPOSURE_REF!r}, got {len(rows)}. "
        f"Available refs: {df['exposure_reference'].to_list()!r}"
    )
    return rows[0]


# ---------------------------------------------------------------------------
# P2.44 acceptance test class
# ---------------------------------------------------------------------------


class TestP244SASLInferredRatingDisapplied:
    """
    P2.44: Art. 139(2B) suppresses inferred ratings for SA-SL Art. 122B(1) path.

    When the only available external rating is inferred (rating_is_inferred=True,
    rating_is_issue_specific=False), Art. 139(2B) disapplies the Art. 139(2)/(2A)
    inferred-rating fallbacks for SA specialised-lending exposures.  The exposure
    must be treated as unrated → Art. 122B(2)(a) object-finance 100% risk weight.

    Pre-fix failure mode: rating_is_inferred not read from ratings parquet (column
    not yet in RATINGS_SCHEMA); inferred CQS=3 is honoured → SA uses the rated
    corporate Art. 122(2) Table 6 path → risk_weight=0.75, rwa_final=750,000.
    Post-fix: risk_weight=1.00, rwa_final=1,000,000.
    """

    # -------------------------------------------------------------------------
    # DISCRIMINATING ASSERTION — FAILS pre-fix
    # -------------------------------------------------------------------------

    def test_p2_44_inferred_rating_suppressed_risk_weight_is_100_pct(
        self, p2_44_sa_results: pl.DataFrame
    ) -> None:
        """
        P2.44 DISCRIMINATING: SA-SL object-finance with inferred-only rating →
        risk_weight = 1.00 (Art. 122B(2)(a) unrated object-finance).

        Art. 139(2B) disapplies the inferred-rating fallback for Art. 122B(1) SA-SL.
        Only rating is inferred (rating_is_inferred=True) → exposure treated as
        unrated → Art. 122B(2)(a) applies → risk_weight = 100%.

        Pre-fix (current): risk_weight = 0.75 (CQS-3 corporate B31 Art. 122(2)
        Table 6 used because inferred-rating suppression is not implemented).

        Arrange: Basel 3.1 SA-only config, CP_P244 (specialised_lending,
                 object_finance), EXP_P244 (GBP 1,000,000), RT_P244 (CQS=3,
                 rating_is_inferred=True).
        Act:     SA pipeline produces risk_weight for EXP_P244.
        Assert:  risk_weight == 1.00.
        """
        # Arrange
        row = _get_exposure_row(p2_44_sa_results)

        # Act: risk_weight is read directly from the SA results row

        # Assert — FAILS pre-fix (engine returns 0.75 from CQS-3 rated-corporate path)
        assert row["risk_weight"] == pytest.approx(EXPECTED_RISK_WEIGHT, abs=1e-6), (
            f"P2.44: SA-SL object-finance with inferred-only rating should have "
            f"risk_weight = {EXPECTED_RISK_WEIGHT:.2f} "
            f"(Art. 122B(2)(a) unrated object-finance, Art. 139(2B) disapplication). "
            f"Got risk_weight = {row['risk_weight']:.4f}. "
            f"Pre-fix: rating_is_inferred not read from parquet → inferred CQS=3 "
            f"honoured → rated-corporate Art. 122(2) Table 6 path fires → 0.75. "
            f"Fix required: add rating_is_inferred to RATINGS_SCHEMA and suppress "
            f"inferred rating in SA SL namespace for Art. 122B(1) exposures."
        )

    def test_p2_44_inferred_rating_suppressed_rwa_is_1m(
        self, p2_44_sa_results: pl.DataFrame
    ) -> None:
        """
        P2.44 DISCRIMINATING: RWA = EAD × RW = 1,000,000 × 1.00 = 1,000,000.

        Arrange: EAD = GBP 1,000,000, risk_weight = 1.00 (post-fix Art. 122B(2)(a)).
        Act:     SA pipeline produces rwa_final for EXP_P244.
        Assert:  rwa_final == 1,000,000.

        Pre-fix: rwa_final = 750,000 (0.75 × 1,000,000 from rated-corporate path).
        """
        # Arrange
        row = _get_exposure_row(p2_44_sa_results)

        # Assert — FAILS pre-fix (engine returns 750,000)
        assert row["rwa_final"] == pytest.approx(EXPECTED_RWA, abs=1e-3), (
            f"P2.44: rwa_final should be {EXPECTED_RWA:,.0f} "
            f"(EAD {EXPECTED_EAD:,.0f} × risk_weight {EXPECTED_RISK_WEIGHT:.2f}, "
            f"Art. 122B(2)(a) unrated object-finance). "
            f"Got rwa_final = {row['rwa_final']:,.0f}. "
            f"Pre-fix: rwa_final = 750,000 (CQS-3 corporate 75% applied instead)."
        )

    # -------------------------------------------------------------------------
    # EAD integrity assertion
    # -------------------------------------------------------------------------

    def test_p2_44_ead_is_1m(self, p2_44_sa_results: pl.DataFrame) -> None:
        """
        P2.44: EAD = 1,000,000 (fully drawn on-balance loan, no CCF).

        This assertion MUST PASS both pre-fix and post-fix — EAD is not affected
        by the inferred-rating disapplication.

        Arrange: EXP_P244, drawn_amount=1,000,000, interest=0, CCF=1.0 (on-BS).
        Act:     ead_final from SA results row.
        Assert:  ead_final ≈ 1,000,000 (abs=1e-3).
        """
        # Arrange
        row = _get_exposure_row(p2_44_sa_results)

        # Assert
        assert row["ead_final"] == pytest.approx(EXPECTED_EAD, abs=1e-3), (
            f"P2.44: ead_final should be {EXPECTED_EAD:,.0f} "
            f"(fully drawn, no CCF). Got {row['ead_final']:,.0f}."
        )

    # -------------------------------------------------------------------------
    # Structural / exposure-class assertions
    # -------------------------------------------------------------------------

    def test_p2_44_exposure_class_sa_is_corporate(self, p2_44_sa_results: pl.DataFrame) -> None:
        """
        P2.44: exposure_class_sa = "corporate" (SA sub-type for SL under Art. 122B(1)).

        Art. 122B(1): specialised-lending sub-classes (including object_finance)
        are treated as corporate exposures under the SA. The exposure_class_sa must
        be "corporate" both pre-fix and post-fix.

        Arrange: CP_P244 (entity_type=specialised_lending), sl_type=object_finance.
        Act:     exposure_class_sa from SA results row.
        Assert:  exposure_class_sa == "corporate".
        """
        # Arrange
        row = _get_exposure_row(p2_44_sa_results)

        # Assert — exposure_class_sa is stored lowercase in the engine
        # ("corporate"), while fixture constant is "CORPORATE" (display form).
        # Compare case-insensitively so the test is robust to case normalisation.
        assert row["exposure_class_sa"].lower() == EXPECTED_EXPOSURE_CLASS_SA.lower(), (
            f"P2.44: exposure_class_sa should be {EXPECTED_EXPOSURE_CLASS_SA.lower()!r} "
            f"(SA sub-type for SL Art. 122B(1)). Got {row['exposure_class_sa']!r}."
        )

    def test_p2_44_sl_type_is_object_finance(self, p2_44_sa_results: pl.DataFrame) -> None:
        """
        P2.44: sl_type = "object_finance" (load-bearing for Art. 122B(2)(a) 100% RW).

        The sl_type column must carry through to the SA results so the SL override
        can apply the correct unrated risk weight. Both pre-fix and post-fix.

        Arrange: sl_metadata CP_P244 row with sl_type="object_finance".
        Act:     sl_type from SA results row.
        Assert:  sl_type == "object_finance".
        """
        # Arrange
        row = _get_exposure_row(p2_44_sa_results)

        # Assert
        assert row["sl_type"] == EXPECTED_SL_TYPE, (
            f"P2.44: sl_type should be {EXPECTED_SL_TYPE!r} "
            f"(required for Art. 122B(2)(a) unrated object-finance path). "
            f"Got {row['sl_type']!r}."
        )

    # -------------------------------------------------------------------------
    # ANTI-ASSERTION — the CQS-3 rated-corporate path MUST NOT fire
    # -------------------------------------------------------------------------

    def test_p2_44_risk_weight_is_not_crr_cqs3_corporate_75_pct(
        self, p2_44_sa_results: pl.DataFrame
    ) -> None:
        """
        P2.44 ANTI-ASSERTION: risk_weight != 0.75 (CQS-3 corporate Basel 3.1).

        0.75 is the Art. 122(2) Table 6 risk weight for CQS-3 rated corporates
        under Basel 3.1. This path MUST NOT fire when the rating is inferred and
        Art. 139(2B) disapplication applies.

        If risk_weight == 0.75 the engine is incorrectly honouring the inferred
        CQS=3 for the SA specialised-lending path. This is the pre-fix value.

        Arrange: EXP_P244, rating RT_P244 (CQS=3, rating_is_inferred=True).
        Act:     risk_weight from SA results row.
        Assert:  risk_weight != 0.75.
        """
        # Arrange
        row = _get_exposure_row(p2_44_sa_results)

        # Assert — structural guard: must not use rated-corporate 75% path
        assert row["risk_weight"] != pytest.approx(ANTI_EXPECTED_RISK_WEIGHT, abs=1e-4), (
            f"P2.44 ANTI-ASSERTION: risk_weight must NOT be {ANTI_EXPECTED_RISK_WEIGHT:.2f} "
            f"(Art. 122(2) Table 6 CQS-3 corporate Basel 3.1 = 75%). "
            f"Got {row['risk_weight']:.4f}. "
            f"This confirms the engine is honouring the inferred CQS=3 rating — "
            f"Art. 139(2B) disapplication has not been implemented."
        )

    def test_p2_44_rwa_is_not_750k(self, p2_44_sa_results: pl.DataFrame) -> None:
        """
        P2.44 ANTI-ASSERTION: rwa_final != 750,000 (EAD × 0.75 rated-corporate path).

        750,000 = 1,000,000 × 0.75 — the pre-fix value produced by the inferred
        CQS=3 rating being incorrectly applied through Art. 122(2) Table 6.
        Post-fix: rwa_final = 1,000,000 (Art. 122B(2)(a) unrated object-finance).

        Arrange: EXP_P244, EAD=1,000,000, risk_weight=0.75 (pre-fix wrong path).
        Act:     rwa_final from SA results row.
        Assert:  rwa_final != 750,000.
        """
        # Arrange
        row = _get_exposure_row(p2_44_sa_results)

        # Assert — rwa anti-assertion mirrors risk_weight anti-assertion
        _anti_rwa = ANTI_EXPECTED_RISK_WEIGHT * EXPECTED_EAD  # 750_000.0
        assert row["rwa_final"] != pytest.approx(_anti_rwa, abs=1e-3), (
            f"P2.44 ANTI-ASSERTION: rwa_final must NOT be {_anti_rwa:,.0f} "
            f"(EAD={EXPECTED_EAD:,.0f} × 0.75 rated-corporate path). "
            f"Got rwa_final = {row['rwa_final']:,.0f}. "
            f"Pre-fix value: 750,000. Post-fix must be 1,000,000."
        )
