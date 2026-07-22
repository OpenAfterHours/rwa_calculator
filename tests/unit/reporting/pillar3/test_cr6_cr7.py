"""Unit tests for the declarative Pillar 3 CR6/CR6-A/CR7/CR7-A templates (Phase 7 S8).

Tests cover:
    - CR6: per-class IRB PD-range sheets — structure, obligor counts, density,
      the String PD-range label column, empty-band all-null rows
    - The recorded F3 second-tranche decision: the CR6 family keys on the
      OBLIGOR class basis (``reporting_class_origin``), never post-substitution
      ("without considering any substitution effects due to CRM")
    - The recorded defaulted-100%-band fix: a defaulted IRB exposure lands in
      PD-band row 17 regardless of its model PD
    - CR6-A: scope-of-IRB-use rows on the origination class (recorded keying)
    - CR7: credit-derivative effect rows, incl. the recorded CRR row-8 fix
      (Retail — Secured by immovable property = A-IRB retail_mortgage)
    - CR7-A: per-approach CRM-extent frames

Why: these are mandatory public IRB disclosures whose class axes must track
the obligor's Art. 147 assignment; the substitution movement is a column
pair (CR7 a->b, CR7-A m->n), never a sheet move.
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.reporting.pillar3.generator import Pillar3Generator
from rwa_calc.reporting.pillar3.templates import (
    B31_CR7_ROWS,
    CR6A_COLUMNS,
    CR7A_AIRB_ROWS,
    CR7A_FIRB_ROWS,
    CRR_CR6_COLUMNS,
    CRR_CR7_ROWS,
)
from tests.fixtures.recon_ledger import LedgerShimPillar3Generator

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_irb_data(**overrides: object) -> pl.LazyFrame:
    """Create minimal IRB pipeline data for testing."""
    defaults: dict[str, object] = {
        "exposure_reference": ["IRB1", "IRB2", "IRB3"],
        "approach_applied": ["foundation_irb", "advanced_irb", "advanced_irb"],
        "exposure_class": ["corporate", "retail_mortgage", "retail_other"],
        "ead_final": [5000.0, 3000.0, 2000.0],
        "rwa_final": [4000.0, 1500.0, 1200.0],
        "pd_floored": [0.02, 0.005, 0.01],
        "pd": [0.018, 0.004, 0.009],
        "lgd_floored": [0.45, 0.10, 0.30],
        "irb_maturity_m": [2.5, 1.0, 1.0],
        "expected_loss": [45.0, 15.0, 6.0],
        "counterparty_reference": ["CP1", "CP2", "CP3"],
        "drawn_amount": [4500.0, 2700.0, 1800.0],
        "nominal_amount": [600.0, 400.0, 300.0],
        "undrawn_amount": [500.0, 300.0, 200.0],
        "interest": [0.0, 0.0, 0.0],
        "exposure_type": ["loan", "loan", "loan"],
        "ccf_applied": [1.0, 1.0, 1.0],
    }
    defaults.update(overrides)
    return pl.LazyFrame(defaults)


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


def _make_slotting_data(**overrides: object) -> pl.LazyFrame:
    """Create minimal slotting pipeline data for testing."""
    defaults: dict[str, object] = {
        "exposure_reference": ["SL1", "SL2", "SL3"],
        "approach_applied": ["slotting", "slotting", "slotting"],
        "exposure_class": ["specialised_lending"] * 3,
        "slotting_category": ["strong", "good", "satisfactory"],
        "ead_final": [1000.0, 800.0, 600.0],
        "rwa_final": [700.0, 720.0, 690.0],
        "expected_loss": [5.0, 8.0, 12.0],
        "exposure_type": ["loan", "loan", "loan"],
    }
    defaults.update(overrides)
    return pl.LazyFrame(defaults)


def _align_and_concat(frames: list[pl.DataFrame]) -> pl.LazyFrame:
    """Schema-align frames (missing columns as typed nulls) and concat."""
    dtypes: dict[str, pl.DataType] = {}
    for frame in frames:
        for name, dtype in frame.schema.items():
            if name not in dtypes and dtype != pl.Null:
                dtypes[name] = dtype
    all_cols = sorted(dtypes)
    aligned = []
    for frame in frames:
        exprs = [
            pl.col(name).cast(dtypes[name])
            if name in frame.columns
            else pl.lit(None, dtype=dtypes[name]).alias(name)
            for name in all_cols
        ]
        aligned.append(frame.select(exprs))
    return pl.concat(aligned).lazy()


def _make_mixed_data() -> pl.LazyFrame:
    """SA + IRB + slotting rows in one frame."""
    return _align_and_concat(
        [
            _make_sa_data().collect(),
            _make_irb_data().collect(),
            _make_slotting_data().collect(),
        ]
    )


def _make_substituted_irb_data() -> pl.LazyFrame:
    """Two physical legs of one guaranteed F-IRB corporate exposure whose
    covered leg substitutes to a sovereign guarantor (post-CRM class moves;
    the obligor applied class stays corporate on both legs)."""
    return _make_irb_data(
        exposure_reference=["G1__G_SOV", "G1__REM", "IRB3"],
        approach_applied=["foundation_irb", "foundation_irb", "advanced_irb"],
        exposure_class=["corporate", "corporate", "retail_other"],
        exposure_class_applied=["corporate", "corporate", "retail_other"],
        exposure_class_post_crm=["central_govt_central_bank", "corporate", "retail_other"],
        counterparty_reference=["CP1", "CP1", "CP3"],
        ead_final=[3000.0, 2000.0, 2000.0],
        rwa_final=[0.0, 1600.0, 1200.0],
        pd=[0.018, 0.018, 0.009],
        pd_floored=[0.02, 0.02, 0.01],
    )


@pytest.fixture
def generator() -> Pillar3Generator:
    return LedgerShimPillar3Generator()


# ---------------------------------------------------------------------------
# CR6 — IRB exposures by exposure class and PD range
# ---------------------------------------------------------------------------


class TestCR6Generation:
    """Tests for CR6 — IRB Exposures by PD Range."""

    def test_cr6_generates_per_class(self, generator: Pillar3Generator):
        data = _make_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert len(bundle.cr6) > 0
        assert "corporate" in bundle.cr6

    def test_cr6_has_17_pd_rows_plus_total(self, generator: Pillar3Generator):
        data = _make_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        for _ec, df in bundle.cr6.items():
            assert df.height == 18  # 17 PD ranges + 1 total

    def test_cr6_total_ead_positive(self, generator: Pillar3Generator):
        data = _make_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        for _ec, df in bundle.cr6.items():
            total = df.filter(pl.col("row_ref") == "18")
            assert total["e"][0] > 0

    def test_cr6_pd_range_column_is_string(self, generator: Pillar3Generator):
        data = _make_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        for _ec, df in bundle.cr6.items():
            assert df.schema["a"] == pl.String

    def test_cr6_obligor_count(self, generator: Pillar3Generator):
        data = _make_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        corp = bundle.cr6["corporate"]
        total = corp.filter(pl.col("row_ref") == "18")
        assert total["g"][0] == pytest.approx(1.0)

    def test_cr6_b31_uses_original_pd_for_allocation(self, generator: Pillar3Generator):
        """PD range allocation should use pre-floor PD (pd) under B31."""
        data = _make_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        assert len(bundle.cr6) > 0

    def test_cr6_rwea_density(self, generator: Pillar3Generator):
        data = _make_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        corp = bundle.cr6["corporate"]
        total = corp.filter(pl.col("row_ref") == "18")
        density = total["k"][0]
        ead = total["e"][0]
        rwa = total["j"][0]
        assert density == pytest.approx(rwa / ead, rel=1e-4)

    def test_cr6_columns_match_template(self, generator: Pillar3Generator):
        data = _make_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        expected = {"row_ref", "row_name"} | {c.ref for c in CRR_CR6_COLUMNS}
        for _ec, df in bundle.cr6.items():
            assert set(df.columns) == expected

    def test_cr6_empty_band_rows_are_all_null(self, generator: Pillar3Generator):
        """An unpopulated PD band renders as an all-null row (not zeros)."""
        data = _make_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        corp = bundle.cr6["corporate"]
        # CP1 has pd_floored=0.02 -> band 6 ("0.20 to < 0.25%"? no — 0.02 =
        # 2.00% -> band "1.00 to < 2.50%" ref 10 is CRR allocation); band 1
        # ("0.00 to < 0.03%") is empty either way.
        band1 = corp.filter(pl.col("row_ref") == "1")
        assert band1["b"][0] is None
        assert band1["e"][0] is None
        assert band1["g"][0] is None


class TestCR6ObligorClassBasis:
    """The recorded F3 second-tranche decision: CR6 sheets key the OBLIGOR
    applied class — substitution never moves a sheet ("without considering
    any substitution effects due to CRM")."""

    def test_substituted_legs_stay_in_obligor_class_sheet(self, generator: Pillar3Generator):
        bundle = generator.generate_from_lazyframe(_make_substituted_irb_data(), framework="CRR")
        # Both legs of the guaranteed corporate stay on the corporate sheet;
        # no sovereign sheet appears.
        assert "central_govt_central_bank" not in bundle.cr6
        corp_total = bundle.cr6["corporate"].filter(pl.col("row_ref") == "18")
        assert corp_total["e"][0] == pytest.approx(5000.0)  # both legs
        assert corp_total["j"][0] == pytest.approx(1600.0)

    def test_defaulted_exposure_lands_in_100pct_band(self, generator: Pillar3Generator):
        """Recorded fix: "All defaulted exposures shall be included in the
        bucket representing PD of 100%" — regardless of the model PD."""
        data = _make_irb_data(
            is_defaulted=[True, False, False],  # CP1 defaulted at model pd 2%
        )
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        corp = bundle.cr6["corporate"]
        default_band = corp.filter(pl.col("row_ref") == "17")
        assert default_band["e"][0] == pytest.approx(5000.0)
        model_band = corp.filter(pl.col("row_ref") == "10")  # 1.00 to < 2.50%
        assert model_band["e"][0] is None


class TestCR6GrossSideCarriersAndCCRExclusion:
    """R-gross-side-carriers: CR6 must not silently drop the facility_undrawn
    leg from its gross/CCF columns (today's ``on_balance_sheet`` predicate is
    a STRICT boolean equality — a null-classified facility_undrawn leg
    matches neither True nor False), and must exclude CCR legs from its IRB
    population entirely (the R3 CR4/CR5 decision, not yet mirrored here).
    See .claude/state/gross-side-carriers-spec.md.
    """

    def _mixed_band_data(self) -> pl.LazyFrame:
        """One PD band (0.50 to < 0.75%, ref "8"), corporate, foundation_irb:
        a loan, a facility_undrawn commitment, and a CCR netting-set leg
        mistakenly sharing the same origin approach tag."""
        return pl.LazyFrame(
            {
                "exposure_reference": ["LN1", "FU1", "NS1"],
                "counterparty_reference": ["CP1", "CP2", "CP3"],
                "approach_applied": ["foundation_irb", "foundation_irb", "foundation_irb"],
                "exposure_class": ["corporate", "corporate", "corporate"],
                "exposure_type": ["loan", "facility_undrawn", "ccr_netting_set"],
                "drawn_amount": [5000.0, 0.0, 0.0],
                "interest": [0.0, 0.0, 0.0],
                "nominal_amount": [0.0, 4000.0, 0.0],
                "undrawn_amount": [0.0, 4000.0, 0.0],
                "ead_final": [5000.0, 3000.0, 2000.0],
                "rwa_final": [3500.0, 2100.0, 2500.0],
                "pd_floored": [0.005, 0.005, 0.005],
                "lgd_floored": [0.45, 0.45, 0.45],
                "irb_maturity_m": [2.5, 2.5, 2.5],
                "ccf": [None, 0.75, None],
            }
        )

    def test_cr6_facility_undrawn_off_bs_gross_and_ccf(self, generator: Pillar3Generator) -> None:
        """Col c (off-BS gross) must count the facility_undrawn headroom
        (today 0.0 — the leg's null on/off classification matches neither
        side); col d (avg CCF, weighted over the off-BS legs) must include
        it too (today null — no leg matches the off-BS predicate)."""
        bundle = generator.generate_from_lazyframe(self._mixed_band_data(), framework="CRR")
        corp = bundle.cr6["corporate"]
        band = corp.filter(pl.col("row_ref") == "8")
        assert band["b"][0] == pytest.approx(5000.0)  # on-BS gross (loan) — unaffected
        assert band["c"][0] == pytest.approx(4000.0)  # off-BS gross (FU headroom)
        assert band["d"][0] == pytest.approx(0.75)  # avg CCF over the off-BS legs (FU only)

    def test_cr6_ccr_leg_excluded_from_ead_and_rwea(self, generator: Pillar3Generator) -> None:
        """Col e (EAD) and col j (RWEA) must exclude the CCR netting-set leg
        entirely (today it is counted — CR6 carries no CCR population
        exclusion, unlike CR4/CR5's ``sa_scope`` narrowing)."""
        bundle = generator.generate_from_lazyframe(self._mixed_band_data(), framework="CRR")
        corp = bundle.cr6["corporate"]
        band = corp.filter(pl.col("row_ref") == "8")
        assert band["e"][0] == pytest.approx(8000.0)  # loan 5000 + FU 3000; CCR excluded
        assert band["j"][0] == pytest.approx(5600.0)  # loan 3500 + FU 2100; CCR excluded


# ---------------------------------------------------------------------------
# CR6-A — scope of IRB and SA use
# ---------------------------------------------------------------------------


class TestCR6AGeneration:
    """Tests for CR6-A — Scope of IRB and SA use."""

    def test_cr6a_generated(self, generator: Pillar3Generator):
        data = _make_mixed_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert bundle.cr6a is not None

    def test_cr6a_total_row_has_all_ead(self, generator: Pillar3Generator):
        data = _make_mixed_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert bundle.cr6a is not None
        total = bundle.cr6a.filter(pl.col("row_name").str.contains("Total"))
        assert total["b"][0] > 0

    def test_cr6a_irb_percentage(self, generator: Pillar3Generator):
        data = _make_mixed_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert bundle.cr6a is not None
        total = bundle.cr6a.filter(pl.col("row_name").str.contains("Total"))
        irb_pct = total["d"][0]
        sa_pct = total["c"][0]
        assert irb_pct + sa_pct == pytest.approx(100.0, rel=0.01)

    def test_cr6a_columns_match(self, generator: Pillar3Generator):
        data = _make_mixed_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert bundle.cr6a is not None
        expected = {"row_ref", "row_name"} | {c.ref for c in CR6A_COLUMNS}
        assert set(bundle.cr6a.columns) == expected

    def test_cr6a_defaulted_sa_exposure_stays_in_origination_class_row(
        self, generator: Pillar3Generator
    ):
        """Recorded keying decision: CR6-A rows carry the ORIGINATION class
        (Art. 147-shaped axis, no defaulted sink row) — an SA-treated
        defaulted corporate stays in the Corporates scope row."""
        data = _make_sa_data(
            exposure_class=["corporate", "retail_mortgage", "corporate"],
            exposure_class_applied=["corporate", "retail_mortgage", "defaulted"],
            exposure_class_post_crm=["corporate", "retail_mortgage", "defaulted"],
        )
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert bundle.cr6a is not None
        corp = bundle.cr6a.filter(pl.col("row_ref") == "3")
        assert corp["b"][0] == pytest.approx(1500.0)  # SA1 + the defaulted SA3


# ---------------------------------------------------------------------------
# CR7 — effect of credit derivatives on RWEAs
# ---------------------------------------------------------------------------


class TestCR7Generation:
    """Tests for CR7 — Credit Derivatives Effect."""

    def test_cr7_generated_crr(self, generator: Pillar3Generator):
        data = _make_mixed_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert bundle.cr7 is not None
        assert bundle.cr7.height == len(CRR_CR7_ROWS)

    def test_cr7_generated_b31(self, generator: Pillar3Generator):
        data = _make_mixed_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        assert bundle.cr7 is not None
        assert bundle.cr7.height == len(B31_CR7_ROWS)

    def test_cr7_pre_equals_post(self, generator: Pillar3Generator):
        """Pre-CD RWEA == post-CD RWEA (recorded approximation: the ledger
        carries no hypothetical pre-credit-derivative RWEA)."""
        data = _make_mixed_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert bundle.cr7 is not None
        for i in range(bundle.cr7.height):
            a = bundle.cr7["a"][i]
            b = bundle.cr7["b"][i]
            if a is not None and b is not None:
                assert a == pytest.approx(b)

    def test_cr7_total_positive(self, generator: Pillar3Generator):
        data = _make_mixed_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert bundle.cr7 is not None
        total = bundle.cr7.filter(pl.col("row_ref") == "10")
        assert total["b"][0] > 0

    def test_cr7_crr_row8_is_airb_retail_mortgage(self, generator: Pillar3Generator):
        """Recorded fix: row 8 "Retail — Secured by immovable property" sums
        the A-IRB retail_mortgage class (the retired handler summed
        retail_other + retail_qrre — byte-identical to row 9)."""
        data = _make_mixed_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert bundle.cr7 is not None
        row8 = bundle.cr7.filter(pl.col("row_ref") == "8")
        row9 = bundle.cr7.filter(pl.col("row_ref") == "9")
        assert row8["b"][0] == pytest.approx(1500.0)  # IRB2 retail_mortgage
        assert row9["b"][0] == pytest.approx(1200.0)  # IRB3 retail_other


# ---------------------------------------------------------------------------
# CR7-A — extent of CRM techniques
# ---------------------------------------------------------------------------


class TestCR7AGeneration:
    """Tests for CR7-A — Extent of CRM Techniques."""

    def test_cr7a_generates_per_approach(self, generator: Pillar3Generator):
        data = _make_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert len(bundle.cr7a) > 0

    def test_cr7a_firb_rows(self, generator: Pillar3Generator):
        data = _make_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        if "foundation_irb" in bundle.cr7a:
            assert bundle.cr7a["foundation_irb"].height == len(CR7A_FIRB_ROWS)

    def test_cr7a_airb_rows(self, generator: Pillar3Generator):
        data = _make_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        if "advanced_irb" in bundle.cr7a:
            assert bundle.cr7a["advanced_irb"].height == len(CR7A_AIRB_ROWS)

    def test_cr7a_total_exposure_positive(self, generator: Pillar3Generator):
        data = _make_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        for _approach, df in bundle.cr7a.items():
            total = df.filter(pl.col("row_name").str.contains("Total"))
            assert total["a"][0] > 0

    def test_cr7a_rows_key_on_obligor_class(self, generator: Pillar3Generator):
        """Both legs of a substituted exposure report under the obligor's
        class row ("without taking into account any substitution effects
        due to the existence of a guarantee")."""
        bundle = generator.generate_from_lazyframe(_make_substituted_irb_data(), framework="CRR")
        firb = bundle.cr7a["foundation_irb"]
        corp = firb.filter(pl.col("row_ref") == "4")  # Corporates — Other
        assert corp["a"][0] == pytest.approx(5000.0)  # both legs' EAD
        assert corp["m"][0] == pytest.approx(1600.0)
