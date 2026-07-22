"""Unit tests for the declarative Pillar 3 CR4/CR5 templates (Phase 7 S8).

Tests cover:
    - CR4: SA exposure and CRM effects — structure, totals, density, null rows
    - CR5: SA risk weight allocation — band buckets, total, unrated fallback
    - CR5 currency-mismatch bucketing (P1.94g: pre-multiplier RW bands)
    - The recorded F3 class-basis decision: CR4 columns a/b key on the obligor
      applied class (``reporting_class_origin``, COREP C 07.00 col 0010 basis);
      CR4 columns c/d/e/f and all CR5 rows key on the post-substitution class
      (``reporting_class``, C 07.00 col 0200 basis, EBA Q&A 2018_4093)

Why: CR4/CR5 are mandatory public disclosures whose class rows must reflect
the applied Art. 112 assignment (defaulted exposures in the "Exposures in
default" row) and Art. 235 substitution (the covered leg in the protection
provider's row post-CRM).
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.reporting.pillar3.generator import Pillar3Generator
from rwa_calc.reporting.pillar3.templates import (
    B31_CR4_ROWS,
    CRR_CR4_COLUMNS,
    CRR_CR4_ROWS,
)
from tests.fixtures.recon_ledger import LedgerShimPillar3Generator

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sa_data(**overrides: object) -> pl.LazyFrame:
    """Create minimal SA pipeline data for testing."""
    defaults: dict[str, object] = {
        "exposure_reference": ["SA1", "SA2", "SA3"],
        "approach_applied": ["standardised", "standardised", "standardised"],
        "exposure_class": ["corporate", "retail_mortgage", "defaulted"],
        "ead_final": [1000.0, 2000.0, 500.0],
        "rwa_final": [1000.0, 700.0, 750.0],
        "risk_weight": [1.0, 0.35, 1.5],
        "drawn_amount": [800.0, 1800.0, 400.0],
        "interest": [50.0, 100.0, 30.0],
        "nominal_amount": [200.0, 300.0, 100.0],
        "undrawn_amount": [150.0, 200.0, 70.0],
        "exposure_type": ["loan", "loan", "loan"],
    }
    defaults.update(overrides)
    return pl.LazyFrame(defaults)


def _make_sa_data_with_mismatch(**overrides: object) -> pl.LazyFrame:
    """Extend _make_sa_data with the two currency-mismatch columns.

    Adds a fourth row (retail_other, EAD=100_000) that has:
        risk_weight                     = 1.125  (post-1.5x-multiplier)
        risk_weight_pre_currency_mismatch = 0.75  (pre-multiplier base RW)
        currency_mismatch_multiplier_applied = True

    CR5 must bucket the mismatch row on the pre-multiplier weight → the 75%
    band (ref "p"), never the Other/Deducted residual (ref "ac").
    """
    base: dict[str, object] = {
        "exposure_reference": ["SA1", "SA2", "SA3", "SA4_MISMATCH"],
        "approach_applied": [
            "standardised",
            "standardised",
            "standardised",
            "standardised",
        ],
        "exposure_class": ["corporate", "retail_mortgage", "defaulted", "retail_other"],
        "ead_final": [1000.0, 2000.0, 500.0, 100_000.0],
        "rwa_final": [1000.0, 700.0, 750.0, 112_500.0],
        "risk_weight": [1.0, 0.35, 1.5, 1.125],
        "risk_weight_pre_currency_mismatch": [1.0, 0.35, 1.5, 0.75],
        "currency_mismatch_multiplier_applied": [False, False, False, True],
        "drawn_amount": [800.0, 1800.0, 400.0, 100_000.0],
        "interest": [50.0, 100.0, 30.0, 0.0],
        "nominal_amount": [200.0, 300.0, 100.0, 0.0],
        "undrawn_amount": [150.0, 200.0, 70.0, 0.0],
        "exposure_type": ["loan", "loan", "loan", "loan"],
    }
    base.update(overrides)
    return pl.LazyFrame(base)


def _make_sa_data_with_ratings() -> pl.LazyFrame:
    """SA legs carrying an own external CQS (``external_cqs``) on some rows.

    R17: CR5 "of which: unrated" (col q / ae) is the exposure value with NO
    nominated-ECAI assessment available, keyed on ``external_cqs`` (null =
    unrated). Mixes rated and unrated legs within one class row, and includes a
    rated retail leg (a class whose flat RW ignores the rating) to pin the
    documented reading: unrated is an ECAI-availability fact, not a
    rating-is-used fact — the rated retail leg counts as RATED.

        C_RATED     corporate     CQS 3  ead 1000  -> rated
        C_UNRATED   corporate     null   ead  400  -> unrated
        INST_RATED  institution   CQS 2  ead 2000  -> rated
        RETAIL_RATED retail_other CQS 4  ead  300  -> rated (rating ignored by 75% RW)
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["C_RATED", "C_UNRATED", "INST_RATED", "RETAIL_RATED"],
            "approach_applied": ["standardised"] * 4,
            "exposure_class": ["corporate", "corporate", "institution", "retail_other"],
            "external_cqs": pl.Series([3, None, 2, 4], dtype=pl.Int8),
            "ead_final": [1000.0, 400.0, 2000.0, 300.0],
            "rwa_final": [1000.0, 400.0, 1000.0, 225.0],
            "risk_weight": [1.0, 1.0, 0.5, 0.75],
            "drawn_amount": [1000.0, 400.0, 2000.0, 300.0],
            "interest": [0.0, 0.0, 0.0, 0.0],
            "nominal_amount": [0.0, 0.0, 0.0, 0.0],
            "undrawn_amount": [0.0, 0.0, 0.0, 0.0],
            "exposure_type": ["loan", "loan", "loan", "loan"],
        }
    )


def _make_defaulted_reclass_data() -> pl.LazyFrame:
    """One SA exposure whose raw class is corporate but whose APPLIED Art. 112
    class is defaulted (Art. 112(1)(j)/127 assessment rank beats corporates) —
    the F1/F3 mover shape the golden portfolio's RP-LN-DEFAULT exercises."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["DEF1"],
            "approach_applied": ["standardised"],
            "exposure_class": ["corporate"],
            "exposure_class_applied": ["defaulted"],
            "exposure_class_post_crm": ["defaulted"],
            "ead_final": [1000.0],
            "rwa_final": [1500.0],
            "risk_weight": [1.5],
            "drawn_amount": [1000.0],
            "interest": [0.0],
            "nominal_amount": [0.0],
            "undrawn_amount": [0.0],
            "exposure_type": ["loan"],
        }
    )


def _make_substituted_data() -> pl.LazyFrame:
    """Two physical legs of one guaranteed corporate exposure (Art. 235):
    the guaranteed leg's post-CRM class is the sovereign guarantor's; the
    retained leg keeps the obligor class. Origin class is uniform corporate."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["G1__G_SOV", "G1__REM"],
            "approach_applied": ["standardised", "standardised"],
            "exposure_class": ["corporate", "corporate"],
            "exposure_class_applied": ["corporate", "corporate"],
            "exposure_class_post_crm": ["central_govt_central_bank", "corporate"],
            "ead_final": [600.0, 400.0],
            "rwa_final": [0.0, 400.0],
            "risk_weight": [0.0, 1.0],
            "drawn_amount": [600.0, 400.0],
            "interest": [0.0, 0.0],
            "nominal_amount": [0.0, 0.0],
            "undrawn_amount": [0.0, 0.0],
            "exposure_type": ["loan", "loan"],
        }
    )


def _make_mixed_bs_ccr_data() -> pl.LazyFrame:
    """One corporate loan (on-BS), one corporate facility_undrawn commitment
    (off-BS — sealed ``reporting_on_balance_sheet`` null), and one institution
    SA-CCR derivative netting set (counterparty credit risk).

    Reproduces the ``ccr_crr`` golden bug the R3 fix closes at unit grain: the
    institution row disclosed the derivative RWEA (col e) while its on/off-BS
    columns (a-d) were empty, and the facility_undrawn commitment was absent
    from the off-BS columns but present in the RWEA — neither row reconciled
    ``c + d`` to ``e``. All three legs carry ``standardised`` origin so the
    exclusion cannot lean on the Basel 3.1 ``standardised_ccr`` relabel.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["LN1", "FU1", "NS1"],
            "approach_applied": ["standardised", "standardised", "standardised"],
            "exposure_class": ["corporate", "corporate", "institution"],
            "exposure_type": ["loan", "facility_undrawn", "ccr_netting_set"],
            "risk_type": [None, None, "CCR_DERIVATIVE"],
            "ead_final": [1000.0, 500.0, 2000.0],
            "rwa_final": [1000.0, 500.0, 2500.0],
            "risk_weight": [1.0, 1.0, 1.25],
            "drawn_amount": [900.0, 0.0, 2000.0],
            "interest": [100.0, 0.0, 0.0],
            "nominal_amount": [0.0, 500.0, 0.0],
            "undrawn_amount": [0.0, 500.0, 0.0],
        }
    )


@pytest.fixture
def generator() -> Pillar3Generator:
    return LedgerShimPillar3Generator()


# ---------------------------------------------------------------------------
# CR4 — SA exposure and CRM effects
# ---------------------------------------------------------------------------


class TestCR4Generation:
    """Tests for CR4 — SA Exposure and CRM Effects."""

    def test_cr4_generated_crr(self, generator: Pillar3Generator):
        data = _make_sa_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert bundle.cr4 is not None
        assert bundle.cr4.height == len(CRR_CR4_ROWS)

    def test_cr4_generated_b31(self, generator: Pillar3Generator):
        data = _make_sa_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        assert bundle.cr4 is not None
        assert bundle.cr4.height == len(B31_CR4_ROWS)

    def test_cr4_total_row_rwea(self, generator: Pillar3Generator):
        data = _make_sa_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert bundle.cr4 is not None
        total = bundle.cr4.filter(pl.col("row_ref") == "17")
        assert total["e"][0] == pytest.approx(2450.0)  # 1000 + 700 + 750

    def test_cr4_corporate_row_populated(self, generator: Pillar3Generator):
        data = _make_sa_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert bundle.cr4 is not None
        corp = bundle.cr4.filter(pl.col("row_ref") == "7")
        assert corp["e"][0] == pytest.approx(1000.0)

    def test_cr4_rwea_density_calculated(self, generator: Pillar3Generator):
        data = _make_sa_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert bundle.cr4 is not None
        total = bundle.cr4.filter(pl.col("row_ref") == "17")
        f_val = total["f"][0]
        assert f_val is not None
        assert f_val > 0

    def test_cr4_empty_rows_are_null(self, generator: Pillar3Generator):
        """Rows for classes not in pipeline should be null."""
        data = _make_sa_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert bundle.cr4 is not None
        # Row 11 (high risk) has no pipeline data
        hr = bundle.cr4.filter(pl.col("row_ref") == "11")
        assert hr["e"][0] is None

    def test_cr4_columns_match_template(self, generator: Pillar3Generator):
        data = _make_sa_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert bundle.cr4 is not None
        expected_cols = {"row_ref", "row_name"} | {c.ref for c in CRR_CR4_COLUMNS}
        assert set(bundle.cr4.columns) == expected_cols


class TestCR4ClassBasisRetarget:
    """The recorded F3 decision: CR4 rows key on the sealed ledger classes,
    not the classifier's raw ``exposure_class``."""

    def test_defaulted_exposure_reports_in_default_row(self, generator: Pillar3Generator):
        """A defaulted corporate belongs in row 10 "Exposures in default"
        (COREP Annex II ¶62 assessment rank 4), not row 7 Corporates."""
        bundle = generator.generate_from_lazyframe(_make_defaulted_reclass_data(), framework="CRR")
        assert bundle.cr4 is not None
        default_row = bundle.cr4.filter(pl.col("row_ref") == "10")
        corp_row = bundle.cr4.filter(pl.col("row_ref") == "7")
        assert default_row["a"][0] == pytest.approx(1000.0)
        assert default_row["c"][0] == pytest.approx(1000.0)
        assert default_row["e"][0] == pytest.approx(1500.0)
        assert corp_row["e"][0] == pytest.approx(0.0)

    def test_pre_crm_columns_key_on_obligor_class(self, generator: Pillar3Generator):
        """Columns a/b stay in the obligor's class row for both legs of a
        substituted exposure (C 07.00 col 0010 basis: pre-substitution)."""
        bundle = generator.generate_from_lazyframe(_make_substituted_data(), framework="CRR")
        assert bundle.cr4 is not None
        corp_row = bundle.cr4.filter(pl.col("row_ref") == "7")
        sov_row = bundle.cr4.filter(pl.col("row_ref") == "1")
        assert corp_row["a"][0] == pytest.approx(1000.0)  # both legs' gross
        assert sov_row["a"][0] == pytest.approx(0.0)  # no sovereign origination

    def test_post_crm_columns_key_on_protection_provider_class(self, generator: Pillar3Generator):
        """Columns c/e move the covered leg into the guarantor's row
        (C 07.00 col 0200 inflow basis; EBA Q&A 2018_4093)."""
        bundle = generator.generate_from_lazyframe(_make_substituted_data(), framework="CRR")
        assert bundle.cr4 is not None
        corp_row = bundle.cr4.filter(pl.col("row_ref") == "7")
        sov_row = bundle.cr4.filter(pl.col("row_ref") == "1")
        assert sov_row["c"][0] == pytest.approx(600.0)  # inflow: covered leg
        assert corp_row["c"][0] == pytest.approx(400.0)  # retained leg only
        assert sov_row["e"][0] == pytest.approx(0.0)
        assert corp_row["e"][0] == pytest.approx(400.0)

    def test_total_row_counts_each_leg_once(self, generator: Pillar3Generator):
        bundle = generator.generate_from_lazyframe(_make_substituted_data(), framework="CRR")
        assert bundle.cr4 is not None
        total = bundle.cr4.filter(pl.col("row_ref") == "17")
        assert total["a"][0] == pytest.approx(1000.0)
        assert total["c"][0] == pytest.approx(1000.0)
        assert total["e"][0] == pytest.approx(400.0)


# ---------------------------------------------------------------------------
# CR5 — SA risk weight allocation
# ---------------------------------------------------------------------------


class TestCR5Generation:
    """Tests for CR5 — SA Risk Weight Allocation."""

    def test_cr5_generated_crr(self, generator: Pillar3Generator):
        data = _make_sa_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert bundle.cr5 is not None

    def test_cr5_total_matches_ead(self, generator: Pillar3Generator):
        data = _make_sa_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert bundle.cr5 is not None
        total = bundle.cr5.filter(pl.col("row_ref") == "17")
        # Total column (p for CRR) should equal total EAD
        assert total["p"][0] == pytest.approx(3500.0)  # 1000 + 2000 + 500

    def test_cr5_100pct_bucket_has_corporate(self, generator: Pillar3Generator):
        data = _make_sa_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert bundle.cr5 is not None
        corp = bundle.cr5.filter(pl.col("row_ref") == "7")
        # Corporate has RW 1.0 (100%), column j
        assert corp["j"][0] == pytest.approx(1000.0)

    def test_cr5_35pct_bucket_has_mortgage(self, generator: Pillar3Generator):
        data = _make_sa_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert bundle.cr5 is not None
        mortgage = bundle.cr5.filter(pl.col("row_ref") == "9")
        # Mortgage RW 0.35 (35%), column f
        assert mortgage["f"][0] == pytest.approx(2000.0)

    def test_cr5_b31_has_extra_columns(self, generator: Pillar3Generator):
        data = _make_sa_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        assert bundle.cr5 is not None
        assert "ba" in bundle.cr5.columns
        assert "bd" in bundle.cr5.columns

    def test_cr5_unrated_column_all_unrated_fallback(self, generator: Pillar3Generator):
        """A frame carrying no ``external_cqs`` carrier falls back to all-unrated,
        so column q equals the Total — the pre-R17 behaviour preserved on frames
        that supply no rating info (mirrors the C 08 discriminator's fallback)."""
        data = _make_sa_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert bundle.cr5 is not None
        total = bundle.cr5.filter(pl.col("row_ref") == "17")
        assert total["q"][0] == pytest.approx(3500.0)


class TestCR5ClassBasisRetarget:
    """The recorded F3 decision for CR5: every figure is post-CF/post-CRM, so
    rows key uniformly on the post-substitution ``reporting_class``."""

    def test_defaulted_exposure_bands_in_default_row(self, generator: Pillar3Generator):
        bundle = generator.generate_from_lazyframe(_make_defaulted_reclass_data(), framework="CRR")
        assert bundle.cr5 is not None
        default_row = bundle.cr5.filter(pl.col("row_ref") == "10")
        corp_row = bundle.cr5.filter(pl.col("row_ref") == "7")
        assert default_row["k"][0] == pytest.approx(1000.0)  # 150% band
        assert default_row["p"][0] == pytest.approx(1000.0)  # Total
        assert corp_row["p"][0] == pytest.approx(0.0)

    def test_substituted_leg_bands_in_guarantor_row(self, generator: Pillar3Generator):
        """The covered leg's EAD sits in the guarantor's class row at the
        guarantor's risk weight (0% sovereign band a)."""
        bundle = generator.generate_from_lazyframe(_make_substituted_data(), framework="CRR")
        assert bundle.cr5 is not None
        sov_row = bundle.cr5.filter(pl.col("row_ref") == "1")
        corp_row = bundle.cr5.filter(pl.col("row_ref") == "7")
        assert sov_row["a"][0] == pytest.approx(600.0)  # 0% band
        assert sov_row["p"][0] == pytest.approx(600.0)
        assert corp_row["j"][0] == pytest.approx(400.0)  # 100% band
        assert corp_row["p"][0] == pytest.approx(400.0)


class TestCR5CurrencyMismatchBucketing:
    """P1.94g DELIV1: CR5 must bucket mismatch rows on pre-mismatch risk weight.

    Why: A retail_other row with currency mismatch has risk_weight=1.125 (after
    the 1.5× Art. 123B multiplier) but its pre-multiplier weight is 0.75.  The
    CR5 disclosure table must show EAD in the 75% bucket (column "p" in B31) to
    reflect the underlying credit risk weight, not the FX-adjusted weight.
    """

    def test_p1_94g_cr5_b31_mismatch_ead_in_75pct_bucket(self, generator: Pillar3Generator) -> None:
        """Mismatch row (RW=1.125, pre-mismatch=0.75) must land in the 75% B31 bucket.

        Arrange: retail_other row with currency_mismatch_multiplier_applied=True,
                 risk_weight=1.125, risk_weight_pre_currency_mismatch=0.75,
                 ead_final=100_000.
        Act:     generate CR5 for BASEL_3_1.
        Assert:  Retail row (row_ref "8") has column "p" (75% band) == 100_000.
        """
        # Arrange
        data = _make_sa_data_with_mismatch()

        # Act
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        assert bundle.cr5 is not None

        # Retail row — SA_DISCLOSURE_CLASSES maps ("retail_other",) → row_ref "8"
        retail_row = bundle.cr5.filter(pl.col("row_ref") == "8")
        assert len(retail_row) == 1, "Expected one retail row in CR5"

        # Assert: EAD must land in the 75% bucket (column ref "p", index 15 in B31)
        ead_in_75pct = retail_row["p"][0]
        assert ead_in_75pct == pytest.approx(100_000.0), (
            f"Mismatch row EAD (100_000) should be in the 75% bucket (ref 'p'), "
            f"but got {ead_in_75pct}. "
            f"Bucketing on the post-multiplier risk_weight=1.125 matches no B31 "
            f"band and falls to Other/Deducted ('ac')."
        )

    def test_p1_94g_cr5_b31_mismatch_ead_not_in_other_deducted(
        self, generator: Pillar3Generator
    ) -> None:
        """Anti-confound: mismatch EAD must NOT land in Other/Deducted.

        The 1.125 RW row would fall into Other/Deducted (ref 'ac') if bucketed
        on the post-multiplier weight, because no 112.5% band exists in B31.

        Arrange/Act: same as above.
        Assert:  Retail row has column 'ac' (Other/Deducted) != 100_000.
        """
        # Arrange
        data = _make_sa_data_with_mismatch()

        # Act
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        assert bundle.cr5 is not None

        retail_row = bundle.cr5.filter(pl.col("row_ref") == "8")
        assert len(retail_row) == 1

        # "ac" is Other/Deducted in B31 (n=28 bands → index 28 → chr('a'+28-26)='ac')
        ead_in_other = retail_row["ac"][0]
        assert ead_in_other != pytest.approx(100_000.0), (
            f"Mismatch row EAD (100_000) must NOT be in Other/Deducted ('ac'), "
            f"but got {ead_in_other}."
        )


class TestCR5UnratedDiscriminator:
    """R17: CR5 "of which: unrated" reports only legs WITHOUT an own ECAI
    assessment (``external_cqs`` null), not 100% of every class row.

    The reading (CRR Art. 444(e) col q / PS1/26 Annex XX col ae; EBA Annex XX
    instructions): "unrated" = exposure value for which no nominated-ECAI
    credit assessment is available — an INPUT availability fact applied to
    EVERY class row, independent of whether the class RW uses the rating.
    """

    def test_rated_leg_excluded_from_unrated_column_crr(self, generator: Pillar3Generator):
        """Corporate row: Total counts both legs, unrated counts only the
        null-``external_cqs`` leg (the CQS-3 leg is rated → excluded)."""
        bundle = generator.generate_from_lazyframe(_make_sa_data_with_ratings(), framework="CRR")
        assert bundle.cr5 is not None
        corp = bundle.cr5.filter(pl.col("row_ref") == "7")
        assert corp["p"][0] == pytest.approx(1400.0)  # Total = 1000 rated + 400 unrated
        assert corp["q"][0] == pytest.approx(400.0)  # unrated = the null-CQS leg only

    def test_fully_rated_row_reports_zero_unrated_crr(self, generator: Pillar3Generator):
        """Institution row is entirely rated (CQS 2): unrated (q) drops to 0."""
        bundle = generator.generate_from_lazyframe(_make_sa_data_with_ratings(), framework="CRR")
        assert bundle.cr5 is not None
        inst = bundle.cr5.filter(pl.col("row_ref") == "6")
        assert inst["p"][0] == pytest.approx(2000.0)
        assert inst["q"][0] == pytest.approx(0.0)

    def test_rated_but_rating_ignored_class_counts_as_rated_crr(self, generator: Pillar3Generator):
        """A retail leg carrying an ECAI assessment counts as RATED even though
        the 75% retail RW ignores the rating — the documented availability
        reading, not a rating-is-used reading."""
        bundle = generator.generate_from_lazyframe(_make_sa_data_with_ratings(), framework="CRR")
        assert bundle.cr5 is not None
        retail = bundle.cr5.filter(pl.col("row_ref") == "8")
        assert retail["p"][0] == pytest.approx(300.0)
        assert retail["q"][0] == pytest.approx(0.0)  # rated → excluded from unrated

    def test_total_row_unrated_sums_only_unrated_legs_crr(self, generator: Pillar3Generator):
        """Grand-total row: unrated (q) = 400 (the single null-CQS leg), not the
        3700 Total — the R17 bug reported 100% of exposure as unrated."""
        bundle = generator.generate_from_lazyframe(_make_sa_data_with_ratings(), framework="CRR")
        assert bundle.cr5 is not None
        total = bundle.cr5.filter(pl.col("row_ref") == "17")
        assert total["p"][0] == pytest.approx(3700.0)
        assert total["q"][0] == pytest.approx(400.0)

    def test_unrated_never_exceeds_total_every_row_crr(self, generator: Pillar3Generator):
        """Invariant: unrated (q) ≤ Total (p) for every bound CR5 row."""
        bundle = generator.generate_from_lazyframe(_make_sa_data_with_ratings(), framework="CRR")
        assert bundle.cr5 is not None
        for row in bundle.cr5.iter_rows(named=True):
            total, unrated = row["p"], row["q"]
            if total is not None and unrated is not None:
                assert unrated <= total + 1e-9, (
                    f"row {row['row_ref']}: unrated {unrated} > total {total}"
                )

    def test_unrated_discriminator_b31_column_ae(self, generator: Pillar3Generator):
        """Basel 3.1: the discriminator binds the B31 "of which: unrated" column
        ``ae`` (Total is ``ad``) — corporate row excludes the rated leg."""
        bundle = generator.generate_from_lazyframe(
            _make_sa_data_with_ratings(), framework="BASEL_3_1"
        )
        assert bundle.cr5 is not None
        corp = bundle.cr5.filter(pl.col("row_ref") == "7")
        assert corp["ad"][0] == pytest.approx(1400.0)  # Total
        assert corp["ae"][0] == pytest.approx(400.0)  # of which unrated
        total = bundle.cr5.filter(pl.col("row_ref") == "17")
        assert total["ae"][0] == pytest.approx(400.0)


# ---------------------------------------------------------------------------
# R3 — CR4/CR5 population symmetry (SA credit risk excl. CCR/settlement)
# ---------------------------------------------------------------------------


class TestCR4CR5PopulationSymmetry:
    """CR4 and CR5 compute every column over the SAME population.

    CR4/CR5 disclose SA CREDIT risk excluding counterparty credit risk and
    settlement risk (CRR Art. 444(e); CCR disclosed in CCR1-CCR8). The
    ``sa_scope`` narrowing drops the non-credit-risk synthetic legs entirely
    and reclassifies the facility_undrawn commitment to off-balance-sheet, so
    a row's RWEA (CR4 col e) never covers exposure its on/off-BS columns omit.
    """

    def test_cr4_ccr_leg_excluded_from_every_column(self, generator: Pillar3Generator):
        """The institution row held ONLY the SA-CCR derivative: excluding it
        zeroes the whole row (was e=2500 with a/b/c/d=0 — the un-reconciled
        bug where RWEA was disclosed with no on/off-BS split)."""
        bundle = generator.generate_from_lazyframe(_make_mixed_bs_ccr_data(), framework="CRR")
        assert bundle.cr4 is not None
        inst = bundle.cr4.filter(pl.col("row_ref") == "6")
        for col in ("a", "b", "c", "d", "e"):
            assert inst[col][0] == pytest.approx(0.0), col

    def test_cr4_facility_undrawn_classified_off_balance_sheet(self, generator: Pillar3Generator):
        """The undrawn commitment lands off-BS: its gross feeds col b and its
        post-CCF EAD feeds col d (both were 0 before the fix), so the corporate
        row reconciles c+d to the RWEA population."""
        bundle = generator.generate_from_lazyframe(_make_mixed_bs_ccr_data(), framework="CRR")
        assert bundle.cr4 is not None
        corp = bundle.cr4.filter(pl.col("row_ref") == "7")
        assert corp["a"][0] == pytest.approx(1000.0)  # on-BS gross drawn+interest (loan)
        assert corp["b"][0] == pytest.approx(1000.0)  # off-BS gross nominal+undrawn (commitment)
        assert corp["c"][0] == pytest.approx(1000.0)  # on-BS post-CRM EAD (loan)
        assert corp["d"][0] == pytest.approx(500.0)  # off-BS post-CRM EAD (commitment)
        assert corp["e"][0] == pytest.approx(1500.0)  # RWEA = loan + commitment; CCR excluded

    def test_cr4_every_row_rwea_reconciles_to_on_off_bs_population(
        self, generator: Pillar3Generator
    ):
        """No CR4 row discloses RWEA (col e) without a reconciling on/off-BS
        EAD (c+d): the population of col e is exactly the union of the on- and
        off-balance-sheet split columns."""
        bundle = generator.generate_from_lazyframe(_make_mixed_bs_ccr_data(), framework="CRR")
        assert bundle.cr4 is not None
        for row in bundle.cr4.filter(pl.col("e").is_not_null()).iter_rows(named=True):
            c, d, e = row["c"] or 0.0, row["d"] or 0.0, row["e"] or 0.0
            if e > 0.0:
                assert (c + d) > 0.0, f"row {row['row_ref']}: RWEA {e} with no on/off-BS EAD"
        total = bundle.cr4.filter(pl.col("row_ref") == "17")
        # Total post-CRM EAD = loan 1000 + commitment 500; the CCR leg (2000) is excluded.
        assert (total["c"][0] + total["d"][0]) == pytest.approx(1500.0)

    def test_cr5_ccr_excluded_and_facility_undrawn_off_bs(self, generator: Pillar3Generator):
        """CR5 uses the same population: the CCR institution row zeroes out and
        the facility_undrawn commitment reports on the off-BS side (col bb)."""
        crr = generator.generate_from_lazyframe(_make_mixed_bs_ccr_data(), framework="CRR")
        assert crr.cr5 is not None
        # CRR Total col p: institution row is CCR-only -> 0; corporate row keeps
        # the loan + undrawn commitment EAD (CCR excluded from the population).
        assert crr.cr5.filter(pl.col("row_ref") == "6")["p"][0] == pytest.approx(0.0)
        assert crr.cr5.filter(pl.col("row_ref") == "7")["p"][0] == pytest.approx(1500.0)

        b31 = generator.generate_from_lazyframe(_make_mixed_bs_ccr_data(), framework="BASEL_3_1")
        assert b31.cr5 is not None
        corp = b31.cr5.filter(pl.col("row_ref") == "7")
        assert corp["ba"][0] == pytest.approx(1000.0)  # on-BS gross (loan)
        assert corp["bb"][0] == pytest.approx(1000.0)  # off-BS gross (undrawn commitment)
        inst = b31.cr5.filter(pl.col("row_ref") == "6")
        assert inst["ba"][0] == pytest.approx(0.0)  # CCR derivative excluded
        assert inst["bb"][0] == pytest.approx(0.0)
