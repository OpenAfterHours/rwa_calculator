"""Unit tests for the declarative Pillar 3 CR9/CR9.1/CR10 templates (Phase 7 S8).

Tests cover:
    - CR9: IRB PD back-testing — leaf-class taxonomy routing, sparse PD-band
      rows, the c-h point-in-time proxy columns and their carrier ladders,
      String label cells, Excel export
    - The recorded F3 close-out: CR9 sheets key the OBLIGOR basis
      (``reporting_class_origin`` x ``reporting_approach_origin``) — the
      instructions bar substitution effects, so a guaranteed exposure's legs
      never move sheets
    - CR10: slotting subtemplates — supervisory-category rows, the fixed
      Art. 153(5) risk-weight column, the B31 HVCRE split

Why: CR9 is the mandatory PD back-testing disclosure whose sheets must track
the obligor's Art. 147 assignment; CR10 is the slotting disclosure keyed on
supervisory categories.
"""

from __future__ import annotations

import math
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.reporting.pillar3.generator import (
    Pillar3Generator,
    Pillar3TemplateBundle,
)
from rwa_calc.reporting.pillar3.templates import (
    CR6_PD_RANGES,
    CR9_1_COLUMNS,
    CR9_AIRB_CLASSES,
    CR9_APPROACH_DISPLAY,
    CR9_COLUMN_REFS,
    CR9_COLUMNS,
    CR9_FIRB_CLASSES,
    CRR_CR10_COLUMNS,
)
from tests.fixtures.recon_ledger import LedgerShimPillar3Generator

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_slotting_data(**overrides: object) -> pl.LazyFrame:
    """Create minimal slotting pipeline data for testing."""
    defaults: dict[str, object] = {
        "exposure_reference": ["SL1", "SL2", "SL3"],
        "approach_applied": ["slotting", "slotting", "slotting"],
        "exposure_class": ["specialised_lending", "specialised_lending", "specialised_lending"],
        "sl_type": ["project_finance", "project_finance", "ipre"],
        "slotting_category": ["strong", "good", "satisfactory"],
        "ead_final": [1000.0, 800.0, 600.0],
        "rwa_final": [700.0, 720.0, 690.0],
        "expected_loss": [5.0, 8.0, 12.0],
        "drawn_amount": [900.0, 700.0, 500.0],
        "nominal_amount": [150.0, 120.0, 120.0],
        "undrawn_amount": [100.0, 100.0, 100.0],
        "interest": [0.0, 0.0, 0.0],
        "exposure_type": ["loan", "loan", "loan"],
    }
    defaults.update(overrides)
    return pl.LazyFrame(defaults)


def _make_equity_data(**overrides: object) -> pl.LazyFrame:
    """Create equity legs for CR10.5 tests — one per Art. 155(2) simple-RW band.

    ``equity_method`` is the calculator's method discriminator (``irb_simple``
    = Art. 155(2), ``sa`` = Art. 133, ``pd_lgd`` = Art. 155(3)); only
    ``irb_simple`` legs are disclosed in CR10.5. ``risk_weight`` becomes
    ``reporting_rw`` via the ledger shim, which is what places a leg in its band
    row (190/290/370%). ``exposure_type`` is left unset so ``reporting_on_balance_sheet``
    resolves null exactly like a production equity holding.
    """
    defaults: dict[str, object] = {
        "exposure_reference": ["EQ_DIV", "EQ_XT", "EQ_OTHER"],
        "approach_applied": ["equity", "equity", "equity"],
        "equity_method": ["irb_simple", "irb_simple", "irb_simple"],
        "exposure_class": ["equity", "equity", "equity"],
        "equity_type": ["private_equity_diversified", "exchange_traded", "other"],
        "ead_final": [1000.0, 2000.0, 3000.0],
        "risk_weight": [1.90, 2.90, 3.70],
        "rwa_final": [1900.0, 5800.0, 11100.0],
        "expected_loss": [8.0, 16.0, 72.0],
    }
    defaults.update(overrides)
    return pl.LazyFrame(defaults)


def _slotting_plus_equity(equity_method: str) -> pl.LazyFrame:
    """One slotting book plus three equity legs tagged ``equity_method``.

    Slotting keeps CR10 emitting even when the equity population is excluded, so
    the force-emitted CR10.5 sheet is present (and empty) rather than the whole
    CR10 dict collapsing to ``{}``.
    """
    slot = _make_slotting_data().collect()
    equity = _make_equity_data(equity_method=[equity_method] * 3).collect()
    return pl.concat([slot, equity], how="diagonal_relaxed").lazy()


@pytest.fixture
def generator() -> Pillar3Generator:
    return LedgerShimPillar3Generator()


# ---------------------------------------------------------------------------
# CR10 — slotting subtemplates
# ---------------------------------------------------------------------------


class TestCR10Generation:
    """Tests for CR10 — Slotting Approach Exposures."""

    def test_cr10_generates_per_sl_type(self, generator: Pillar3Generator):
        data = _make_slotting_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert len(bundle.cr10) > 0
        assert "project_finance" in bundle.cr10

    def test_cr10_rows_per_subtemplate(self, generator: Pillar3Generator):
        data = _make_slotting_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        for sl_type, df in bundle.cr10.items():
            if sl_type == "equity":
                assert df.height == 4  # 3 Art. 155(2) simple-RW bands + total
            else:
                assert df.height == 6  # 5 slotting categories + total

    def test_cr10_risk_weight_populated(self, generator: Pillar3Generator):
        data = _make_slotting_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        pf = bundle.cr10["project_finance"]
        strong = pf.filter(pl.col("row_ref") == "1")
        assert strong["c"][0] == pytest.approx(70.0)  # 0.70 * 100

    def test_cr10_total_ead(self, generator: Pillar3Generator):
        data = _make_slotting_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        pf = bundle.cr10["project_finance"]
        total = pf.filter(pl.col("row_ref") == "6")
        assert total["d"][0] > 0

    def test_cr10_b31_separates_hvcre(self, generator: Pillar3Generator):
        """B31 should separate HVCRE from IPRE."""
        data = _make_slotting_data(sl_type=["project_finance", "project_finance", "hvcre"])
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        if "hvcre" in bundle.cr10:
            hvcre = bundle.cr10["hvcre"]
            strong = hvcre.filter(pl.col("row_ref") == "1")
            # HVCRE Strong = 95%
            assert strong["c"][0] == pytest.approx(95.0)

    def test_cr10_columns_match(self, generator: Pillar3Generator):
        data = _make_slotting_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        expected = {"row_ref", "row_name"} | {c.ref for c in CRR_CR10_COLUMNS}
        for df in bundle.cr10.values():
            assert set(df.columns) == expected


class TestCR105Equity:
    """CR10.5 — CRR equity under the Art. 155(2) IRB simple risk-weight approach.

    The finding this covers (R6): equity legs seal as
    ``reporting_approach_origin == "equity"`` while the generator filtered CR10
    to ``slotting``, so the equity RWEA was never disclosed. The fix populates
    CR10.5 from the simple-RW equity legs (``equity_method == "irb_simple"``).
    """

    def test_bands_populate_by_applied_risk_weight(self, generator: Pillar3Generator):
        """Each simple-RW equity leg lands in the band row matching its RW."""
        bundle = generator.generate_from_lazyframe(_make_equity_data(), framework="CRR")
        equity = bundle.cr10["equity"]
        # 190% band -> row 1 (EAD 1000, RWA 1900); 290% -> row 2; 370% -> row 3.
        assert equity.filter(pl.col("row_ref") == "1")["d"][0] == pytest.approx(1000.0)
        assert equity.filter(pl.col("row_ref") == "1")["e"][0] == pytest.approx(1900.0)
        assert equity.filter(pl.col("row_ref") == "2")["e"][0] == pytest.approx(5800.0)
        assert equity.filter(pl.col("row_ref") == "3")["e"][0] == pytest.approx(11100.0)

    def test_total_row_sums_all_bands(self, generator: Pillar3Generator):
        bundle = generator.generate_from_lazyframe(_make_equity_data(), framework="CRR")
        total = bundle.cr10["equity"].filter(pl.col("row_ref") == "4")
        assert total["d"][0] == pytest.approx(6000.0)  # 1000 + 2000 + 3000
        assert total["e"][0] == pytest.approx(18800.0)  # 1900 + 5800 + 11100
        assert total["f"][0] == pytest.approx(96.0)  # 8 + 16 + 72

    def test_on_balance_sheet_mirrors_exposure_value(self, generator: Pillar3Generator):
        """Equity is an on-BS asset with no off-BS split: col a == col d, col b null."""
        bundle = generator.generate_from_lazyframe(_make_equity_data(), framework="CRR")
        total = bundle.cr10["equity"].filter(pl.col("row_ref") == "4")
        assert total["a"][0] == pytest.approx(6000.0)
        assert total["d"][0] == pytest.approx(6000.0)
        assert total["b"][0] is None

    def test_fixed_risk_weight_column(self, generator: Pillar3Generator):
        """Col c carries the fixed 190/290/370% display RWs; the Total is null."""
        bundle = generator.generate_from_lazyframe(_make_equity_data(), framework="CRR")
        equity = bundle.cr10["equity"]
        assert equity.filter(pl.col("row_ref") == "1")["c"][0] == pytest.approx(190.0)
        assert equity.filter(pl.col("row_ref") == "2")["c"][0] == pytest.approx(290.0)
        assert equity.filter(pl.col("row_ref") == "3")["c"][0] == pytest.approx(370.0)
        assert equity.filter(pl.col("row_ref") == "4")["c"][0] is None

    def test_sa_equity_excluded(self, generator: Pillar3Generator):
        """Art. 133 SA equity (equity_method='sa') is NOT disclosed in CR10.5."""
        bundle = generator.generate_from_lazyframe(_slotting_plus_equity("sa"), framework="CRR")
        equity = bundle.cr10["equity"]
        total = equity.filter(pl.col("row_ref") == "4")
        assert total["d"][0] is None
        assert total["e"][0] is None

    def test_pd_lgd_equity_excluded(self, generator: Pillar3Generator):
        """Art. 155(3) PD/LGD equity (equity_method='pd_lgd') is excluded from CR10.5."""
        bundle = generator.generate_from_lazyframe(_slotting_plus_equity("pd_lgd"), framework="CRR")
        total = bundle.cr10["equity"].filter(pl.col("row_ref") == "4")
        assert total["e"][0] is None

    def test_force_emitted_empty_keeps_fixed_rw_column(self, generator: Pillar3Generator):
        """An excluded population still force-emits CR10.5 with its fixed RW column."""
        bundle = generator.generate_from_lazyframe(_slotting_plus_equity("sa"), framework="CRR")
        equity = bundle.cr10["equity"]
        assert equity.height == 4
        assert equity.filter(pl.col("row_ref") == "2")["c"][0] == pytest.approx(290.0)

    def test_slotting_subtemplates_unaffected(self, generator: Pillar3Generator):
        """Mixing equity in does not move the slotting book off CR10.1-4."""
        bundle = generator.generate_from_lazyframe(
            _slotting_plus_equity("irb_simple"), framework="CRR"
        )
        pf = bundle.cr10["project_finance"]
        assert pf.height == 6  # slotting keeps its 5 categories + total
        assert pf.filter(pl.col("row_ref") == "1")["d"][0] == pytest.approx(1000.0)

    def test_absent_under_basel_3_1(self, generator: Pillar3Generator):
        """Basel 3.1 has no equity CR10 subtemplate (Art. 147A removes IRB equity)."""
        bundle = generator.generate_from_lazyframe(_make_equity_data(), framework="BASEL_3_1")
        assert "equity" not in bundle.cr10


# ---------------------------------------------------------------------------


def _make_cr9_irb_data(**overrides: object) -> pl.LazyFrame:
    """Create IRB data with multiple obligors for CR9 back-testing tests.

    Includes 6 exposures across F-IRB (corporate, institution) and A-IRB
    (retail_mortgage, retail_other) with varied PDs, default status, and
    counterparty references for obligor counting.

    Discriminator columns for P2.49 taxonomy routing:
    - ``is_sme``: retail SME/non-SME split
    - ``property_type``: "residential"/"commercial" for retail_mortgage sub-classes
    - ``cp_is_financial_sector_entity``: True routes F-IRB corporate to
      "corporate_financial_large"; False routes to "corporate_other_non_sme"

    After P2.49:
    - CP1 (F-IRB corporate, cp_is_financial_sector_entity=False) →
      ``foundation_irb - corporate_other_non_sme``
    - CP2 (F-IRB institution) → ``foundation_irb - institution``
    - CP3/CP4 (A-IRB retail_mortgage, property_type=residential, is_sme=False) →
      ``advanced_irb - retail_rre_non_sme``
    - CP5/CP6 (A-IRB retail_other, is_sme=False) →
      ``advanced_irb - retail_other_non_sme``
    """
    defaults: dict[str, object] = {
        "exposure_reference": ["CR9_1", "CR9_2", "CR9_3", "CR9_4", "CR9_5", "CR9_6"],
        "approach_applied": [
            "foundation_irb",
            "foundation_irb",
            "advanced_irb",
            "advanced_irb",
            "advanced_irb",
            "advanced_irb",
        ],
        "exposure_class": [
            "corporate",
            "institution",
            "retail_mortgage",
            "retail_mortgage",
            "retail_other",
            "retail_other",
        ],
        # P2.49 discriminator columns — required for new taxonomy routing
        "is_sme": [False, False, False, False, False, False],
        "property_type": [None, None, "residential", "residential", None, None],
        "cp_is_financial_sector_entity": [False, False, False, False, False, False],
        "ead_final": [5000.0, 3000.0, 2000.0, 1500.0, 1000.0, 800.0],
        "rwa_final": [4000.0, 1800.0, 1200.0, 900.0, 600.0, 480.0],
        "pd_floored": [0.02, 0.005, 0.01, 0.008, 0.03, 1.0],
        "pd": [0.018, 0.004, 0.009, 0.007, 0.025, 1.0],
        "lgd_floored": [0.45, 0.45, 0.10, 0.10, 0.30, 0.45],
        "irb_maturity_m": [2.5, 2.5, 1.0, 1.0, 1.0, 1.0],
        "expected_loss": [45.0, 6.75, 2.0, 1.2, 9.0, 360.0],
        "counterparty_reference": ["CP1", "CP2", "CP3", "CP4", "CP5", "CP6"],
        "is_defaulted": [False, False, False, False, False, True],
        "drawn_amount": [4500.0, 2700.0, 1800.0, 1350.0, 900.0, 720.0],
        "nominal_amount": [600.0, 400.0, 300.0, 200.0, 150.0, 100.0],
        "undrawn_amount": [500.0, 300.0, 200.0, 150.0, 100.0, 80.0],
        "interest": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        "exposure_type": ["loan", "loan", "loan", "loan", "loan", "loan"],
        "ccf_applied": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
    }
    defaults.update(overrides)
    return pl.LazyFrame(defaults)


class TestCR9TemplateDefinitions:
    """Tests for CR9 template constant definitions."""

    def test_cr9_has_8_columns(self):
        assert len(CR9_COLUMNS) == 8

    def test_cr9_column_refs(self):
        assert CR9_COLUMN_REFS == ["a", "b", "c", "d", "e", "f", "g", "h"]

    def test_cr9_col_a_is_exposure_class(self):
        assert CR9_COLUMNS[0].name == "Exposure class"

    def test_cr9_col_b_is_pd_range(self):
        assert CR9_COLUMNS[1].name == "PD range"

    def test_cr9_col_f_mentions_post_input_floor(self):
        col_f = next(c for c in CR9_COLUMNS if c.ref == "f")
        assert "post input floor" in col_f.name.lower()

    def test_cr9_col_h_is_historical_rate(self):
        col_h = next(c for c in CR9_COLUMNS if c.ref == "h")
        assert "historical" in col_h.name.lower()

    def test_cr9_airb_classes_count(self):
        assert len(CR9_AIRB_CLASSES) == 10

    def test_cr9_firb_classes_count(self):
        assert len(CR9_FIRB_CLASSES) == 5

    def test_cr9_approach_display_has_both(self):
        assert "foundation_irb" in CR9_APPROACH_DISPLAY
        assert "advanced_irb" in CR9_APPROACH_DISPLAY

    def test_cr9_firb_includes_institution(self):
        keys = [k for k, *_ in CR9_FIRB_CLASSES]
        assert "institution" in keys

    def test_cr9_airb_includes_retail(self):
        # P2.49: collapsed parent keys "retail_mortgage" and "retail_other"
        # are replaced by SME/non-SME and property-type sub-class leaves.
        # Only the scalar class "retail_qrre" is unchanged.
        keys = [k for k, *_ in CR9_AIRB_CLASSES]
        assert "retail_qrre" in keys
        assert "retail_rre_sme" in keys
        assert "retail_rre_non_sme" in keys
        assert "retail_cre_sme" in keys
        assert "retail_cre_non_sme" in keys
        assert "retail_other_sme" in keys
        assert "retail_other_non_sme" in keys
        # Collapsed parents must not survive
        assert "retail_mortgage" not in keys
        assert "retail_other" not in keys

    def test_cr9_1_has_base_columns(self):
        """CR9.1 has at least the 8 base columns (ECAI columns added dynamically)."""
        assert len(CR9_1_COLUMNS) == 8

    def test_cr9_1_col_b_is_firm_defined(self):
        col_b = next(c for c in CR9_1_COLUMNS if c.ref == "b")
        assert "firm-defined" in col_b.name.lower()

    def test_cr9_uses_same_pd_ranges_as_cr6(self):
        """CR9 uses the same 17 fixed PD range buckets as CR6."""
        assert len(CR6_PD_RANGES) == 17
        assert CR6_PD_RANGES[0][0] == pytest.approx(0.0, abs=1e-10)
        assert math.isinf(CR6_PD_RANGES[-1][1])


class TestCR9Generation:
    """Tests for CR9 template generation logic."""

    def test_cr9_returns_empty_under_crr(self, generator: Pillar3Generator):
        """CR9 is Basel 3.1 only — CRR returns empty dict."""
        data = _make_cr9_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert bundle.cr9 == {}

    def test_cr9_returns_dict_under_b31(self, generator: Pillar3Generator):
        data = _make_cr9_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        assert isinstance(bundle.cr9, dict)
        assert len(bundle.cr9) > 0

    def test_cr9_keys_include_approach_and_class(self, generator: Pillar3Generator):
        data = _make_cr9_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        # P2.49: collapsed parent keys are replaced by leaf sub-class keys.
        # CP1 (F-IRB corporate, cp_is_financial_sector_entity=False) →
        #   foundation_irb - corporate_other_non_sme
        # CP2 (F-IRB institution) → foundation_irb - institution (unchanged)
        # CP3/CP4 (A-IRB retail_mortgage, residential, is_sme=False) →
        #   advanced_irb - retail_rre_non_sme
        # CP5/CP6 (A-IRB retail_other, is_sme=False) →
        #   advanced_irb - retail_other_non_sme
        keys = set(bundle.cr9.keys())
        assert "foundation_irb - corporate_other_non_sme" in keys
        assert "foundation_irb - institution" in keys
        assert "advanced_irb - retail_rre_non_sme" in keys
        assert "advanced_irb - retail_other_non_sme" in keys
        # Old collapsed parents must be absent
        assert "foundation_irb - corporate" not in keys
        assert "advanced_irb - retail_mortgage" not in keys
        assert "advanced_irb - retail_other" not in keys

    def test_cr9_has_correct_column_count(self, generator: Pillar3Generator):
        data = _make_cr9_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        for key, df in bundle.cr9.items():
            # row_ref + row_name + 8 template columns = 10
            assert len(df.columns) == 10, f"Wrong column count for {key}: {df.columns}"

    def test_cr9_total_row_present(self, generator: Pillar3Generator):
        data = _make_cr9_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        for key, df in bundle.cr9.items():
            total_rows = df.filter(pl.col("row_ref") == "18")
            assert total_rows.height == 1, f"Missing total row for {key}"

    def test_cr9_no_empty_buckets_emitted(self, generator: Pillar3Generator):
        """Empty PD buckets should not produce rows (unlike CR6 which emits all 17)."""
        data = _make_cr9_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        for key, df in bundle.cr9.items():
            # Should have fewer than 18 rows (17 PD ranges + 1 total)
            # since not all PD ranges have data
            assert df.height < 18, f"Too many rows for {key}: {df.height}"


class TestCR9ColumnValues:
    """Tests for CR9 column value computation."""

    def test_col_c_obligor_count(self, generator: Pillar3Generator):
        """Col c counts unique counterparty references."""
        data = _make_cr9_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        # P2.49: CP1 (F-IRB corporate, cp_is_financial_sector_entity=False) →
        # foundation_irb - corporate_other_non_sme
        corp = bundle.cr9["foundation_irb - corporate_other_non_sme"]
        total = corp.filter(pl.col("row_ref") == "18")
        # 1 corporate F-IRB counterparty (CP1)
        assert total["c"][0] == pytest.approx(1.0)

    def test_col_d_default_count(self, generator: Pillar3Generator):
        """Col d counts defaulted obligors."""
        data = _make_cr9_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        # P2.49: retail_other (is_sme=False) → advanced_irb - retail_other_non_sme
        # CP6 is defaulted; CP5 is not → total d=1
        ro = bundle.cr9["advanced_irb - retail_other_non_sme"]
        total = ro.filter(pl.col("row_ref") == "18")
        assert total["d"][0] == pytest.approx(1.0)

    def test_col_d_non_defaulted_class_zero(self, generator: Pillar3Generator):
        """Classes with no defaults should have d=0."""
        data = _make_cr9_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        # P2.49: CP1 (F-IRB corporate, cp_is_financial_sector_entity=False) →
        # foundation_irb - corporate_other_non_sme
        corp = bundle.cr9["foundation_irb - corporate_other_non_sme"]
        total = corp.filter(pl.col("row_ref") == "18")
        assert total["d"][0] == pytest.approx(0.0)

    def test_col_e_observed_default_rate(self, generator: Pillar3Generator):
        """Col e = d/c * 100 (observed default rate as percentage)."""
        data = _make_cr9_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        # P2.49: retail_other (is_sme=False) → advanced_irb - retail_other_non_sme
        # 2 obligors (CP5, CP6), 1 defaulted → 50%
        ro = bundle.cr9["advanced_irb - retail_other_non_sme"]
        total = ro.filter(pl.col("row_ref") == "18")
        assert total["e"][0] == pytest.approx(50.0)

    def test_col_f_ewa_pd_percentage(self, generator: Pillar3Generator):
        """Col f = EAD-weighted average PD * 100 (post input floor)."""
        data = _make_cr9_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        # P2.49: CP1 (F-IRB corporate, cp_is_financial_sector_entity=False) →
        # foundation_irb - corporate_other_non_sme
        corp = bundle.cr9["foundation_irb - corporate_other_non_sme"]
        total = corp.filter(pl.col("row_ref") == "18")
        # F-IRB corporate: PD=0.02, EAD=5000 → EWA PD = 0.02 * 100 = 2.0%
        assert total["f"][0] == pytest.approx(2.0)

    def test_col_g_arithmetic_avg_pd(self, generator: Pillar3Generator):
        """Col g = arithmetic average PD * 100 (obligor-weighted)."""
        data = _make_cr9_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        # P2.49: retail_mortgage (property_type=residential, is_sme=False) →
        # advanced_irb - retail_rre_non_sme
        # CP3/CP4: PDs=[0.01, 0.008] → avg 0.009 * 100 = 0.9%
        rm = bundle.cr9["advanced_irb - retail_rre_non_sme"]
        total = rm.filter(pl.col("row_ref") == "18")
        assert total["g"][0] == pytest.approx(0.9)

    def test_col_h_falls_back_to_observed_rate(self, generator: Pillar3Generator):
        """Col h falls back to col e when historical_annual_default_rate is absent."""
        data = _make_cr9_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        # P2.49: retail_other (is_sme=False) → advanced_irb - retail_other_non_sme
        ro = bundle.cr9["advanced_irb - retail_other_non_sme"]
        total = ro.filter(pl.col("row_ref") == "18")
        # Should equal observed rate (50%) as fallback
        assert total["h"][0] == pytest.approx(total["e"][0])

    def test_col_h_uses_historical_data_when_present(self, generator: Pillar3Generator):
        """Col h uses historical_annual_default_rate when column is present."""
        data = _make_cr9_irb_data(
            historical_annual_default_rate=[0.01, 0.02, 0.015, 0.015, 0.025, 0.05],
        )
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        # P2.49: CP1 (F-IRB corporate, cp_is_financial_sector_entity=False) →
        # foundation_irb - corporate_other_non_sme
        corp = bundle.cr9["foundation_irb - corporate_other_non_sme"]
        total = corp.filter(pl.col("row_ref") == "18")
        # Corporate: historical_annual_default_rate=0.01 → 1.0%
        assert total["h"][0] == pytest.approx(1.0)

    def test_col_a_shows_class_display_name(self, generator: Pillar3Generator):
        data = _make_cr9_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        # P2.49: CP1 (F-IRB corporate, cp_is_financial_sector_entity=False) →
        # foundation_irb - corporate_other_non_sme, display label is
        # "Corporates — Other general corporates (non-SME)"
        corp = bundle.cr9["foundation_irb - corporate_other_non_sme"]
        expected_label = "Corporates — Other general corporates (non-SME)"
        assert all(v == expected_label for v in corp["a"].to_list())

    def test_col_b_shows_pd_range_label(self, generator: Pillar3Generator):
        data = _make_cr9_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        # P2.49: CP1 (F-IRB corporate, cp_is_financial_sector_entity=False) →
        # foundation_irb - corporate_other_non_sme
        corp = bundle.cr9["foundation_irb - corporate_other_non_sme"]
        # Total row col b should be "Total"
        total = corp.filter(pl.col("row_ref") == "18")
        assert total["b"][0] == "Total"


class TestCR9PDAllocation:
    """Tests for PD range bucket assignment in CR9."""

    def test_pd_allocation_uses_original_pd(self, generator: Pillar3Generator):
        """B31 allocates by pd (pre-input-floor), not pd_floored."""
        data = _make_cr9_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        # P2.49: CP1 (F-IRB corporate, cp_is_financial_sector_entity=False) →
        # foundation_irb - corporate_other_non_sme
        corp = bundle.cr9["foundation_irb - corporate_other_non_sme"]
        # Corporate: pd=0.018 → bucket "10" (1.00-2.50%)
        non_total = corp.filter(pl.col("row_ref") != "18")
        refs = non_total["row_ref"].to_list()
        assert "10" in refs  # 1.00 to < 2.50%

    def test_defaulted_in_100_percent_bucket(self, generator: Pillar3Generator):
        """Defaulted exposures (PD=1.0) should be in the 100% (Default) bucket."""
        data = _make_cr9_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        # P2.49: retail_other (is_sme=False) → advanced_irb - retail_other_non_sme
        ro = bundle.cr9["advanced_irb - retail_other_non_sme"]
        bucket_17 = ro.filter(pl.col("row_ref") == "17")
        assert bucket_17.height == 1
        assert bucket_17["d"][0] == pytest.approx(1.0)  # 1 defaulted

    def test_pd_range_labels_are_readable(self, generator: Pillar3Generator):
        data = _make_cr9_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        for _key, df in bundle.cr9.items():
            labels = df["b"].to_list()
            assert "Total" in labels
            for label in labels:
                assert isinstance(label, str)
                assert len(label) > 0


class TestCR9EdgeCases:
    """Tests for CR9 edge cases and error handling."""

    def test_no_irb_data_returns_empty(self, generator: Pillar3Generator):
        """No IRB exposures → empty CR9 dict."""
        sa_only = pl.LazyFrame(
            {
                "exposure_reference": ["SA1"],
                "approach_applied": ["standardised"],
                "exposure_class": ["corporate"],
                "ead_final": [1000.0],
                "rwa_final": [800.0],
                "pd_floored": [0.01],
            }
        )
        bundle = generator.generate_from_lazyframe(sa_only, framework="BASEL_3_1")
        assert bundle.cr9 == {}

    def test_missing_pd_column_returns_empty_with_error(
        self,
        generator: Pillar3Generator,
    ):
        """Missing PD columns → empty dict and error message."""
        data = pl.LazyFrame(
            {
                "exposure_reference": ["X"],
                "approach_applied": ["foundation_irb"],
                "exposure_class": ["corporate"],
                "ead_final": [1000.0],
                "rwa_final": [800.0],
            }
        )
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        assert bundle.cr9 == {}
        assert any("CR9" in e for e in bundle.errors)

    def test_slotting_exposures_excluded(self, generator: Pillar3Generator):
        """Slotting exposures should not appear in CR9 (they use CR10)."""
        data = pl.LazyFrame(
            {
                "exposure_reference": ["SL1"],
                "approach_applied": ["slotting"],
                "exposure_class": ["specialised_lending"],
                "ead_final": [1000.0],
                "rwa_final": [700.0],
                "pd_floored": [0.02],
                "pd": [0.018],
            }
        )
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        # Slotting is filtered out by _filter_irb_non_slotting before CR9 runs
        assert bundle.cr9 == {}

    def test_default_detection_falls_back_to_pd(self, generator: Pillar3Generator):
        """Without is_defaulted column, PD >= 1.0 is used as default proxy."""
        data = _make_cr9_irb_data()
        # Remove is_defaulted column
        collected = data.collect().drop("is_defaulted")
        no_default_col = collected.lazy()
        bundle = generator.generate_from_lazyframe(no_default_col, framework="BASEL_3_1")
        ro = bundle.cr9.get("advanced_irb - retail_other_non_sme")
        assert ro is not None
        total = ro.filter(pl.col("row_ref") == "18")
        # CP6 has PD=1.0, should be detected as defaulted
        assert total["d"][0] == pytest.approx(1.0)

    def test_single_exposure_class(self, generator: Pillar3Generator):
        """Single exposure class produces a single CR9 template."""
        data = pl.LazyFrame(
            {
                "exposure_reference": ["X1", "X2"],
                "approach_applied": ["foundation_irb", "foundation_irb"],
                "exposure_class": ["corporate", "corporate"],
                "ead_final": [1000.0, 2000.0],
                "rwa_final": [800.0, 1600.0],
                "pd_floored": [0.01, 0.02],
                "pd": [0.009, 0.018],
                "counterparty_reference": ["A", "B"],
            }
        )
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        assert len(bundle.cr9) == 1
        assert "foundation_irb - corporate_other_non_sme" in bundle.cr9

    def test_prior_year_obligor_count_used_when_present(
        self,
        generator: Pillar3Generator,
    ):
        """Col c uses prior_year_obligor_count when available."""
        data = _make_cr9_irb_data(
            prior_year_obligor_count=[1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
        )
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        corp = bundle.cr9["foundation_irb - corporate_other_non_sme"]
        total = corp.filter(pl.col("row_ref") == "18")
        # prior_year_obligor_count for corporate is 1.0 (one row)
        assert total["c"][0] == pytest.approx(1.0)

    def test_multiple_obligors_same_class(self, generator: Pillar3Generator):
        """Multiple obligors in same class are counted correctly."""
        data = pl.LazyFrame(
            {
                "exposure_reference": ["X1", "X2", "X3"],
                "approach_applied": ["advanced_irb", "advanced_irb", "advanced_irb"],
                "exposure_class": ["corporate", "corporate", "corporate"],
                "ead_final": [1000.0, 2000.0, 3000.0],
                "rwa_final": [800.0, 1600.0, 2400.0],
                "pd_floored": [0.01, 0.01, 0.02],
                "pd": [0.009, 0.009, 0.018],
                "counterparty_reference": ["A", "A", "B"],  # 2 unique CPs
                "is_defaulted": [False, False, False],
            }
        )
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        corp = bundle.cr9["advanced_irb - corporate_other_non_sme"]
        total = corp.filter(pl.col("row_ref") == "18")
        assert total["c"][0] == pytest.approx(2.0)  # 2 unique counterparties


class TestCR9BundleIntegration:
    """Tests for CR9 integration with Pillar3TemplateBundle."""

    def test_bundle_cr9_field_default_empty(self):
        bundle = Pillar3TemplateBundle()
        assert bundle.cr9 == {}

    def test_bundle_cr9_alongside_other_templates(self, generator: Pillar3Generator):
        """CR9 coexists with other templates in the same bundle."""
        data = _make_cr9_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        assert isinstance(bundle.cr9, dict)
        assert bundle.cr6 is not None or isinstance(bundle.cr6, dict)
        assert bundle.framework == "BASEL_3_1"

    def test_end_to_end_with_mixed_data(self, generator: Pillar3Generator):
        """CR9 generated alongside all other templates from mixed data."""
        sa = pl.DataFrame(
            {
                "exposure_reference": ["SA1", "SA2"],
                "approach_applied": ["standardised", "standardised"],
                "exposure_class": ["corporate", "retail_other"],
                "ead_final": [1000.0, 500.0],
                "rwa_final": [1000.0, 375.0],
                "risk_weight": [1.0, 0.75],
                "drawn_amount": [900.0, 450.0],
                "nominal_amount": [150.0, 75.0],
                "undrawn_amount": [100.0, 50.0],
                "interest": [0.0, 0.0],
                "exposure_type": ["loan", "loan"],
                "sa_rwa": [1000.0, 375.0],
            }
        )
        irb = _make_cr9_irb_data().collect()
        irb = irb.with_columns(pl.lit(None).alias("risk_weight").cast(pl.Float64))
        irb = irb.with_columns(pl.col("rwa_final").alias("sa_rwa"))
        # Align schemas
        all_cols = set(sa.columns) | set(irb.columns)
        for col in all_cols:
            if col not in sa.columns:
                dtype = irb.schema.get(col, pl.Float64)
                sa = sa.with_columns(pl.lit(None).cast(dtype).alias(col))
            if col not in irb.columns:
                dtype = sa.schema.get(col, pl.Float64)
                irb = irb.with_columns(pl.lit(None).cast(dtype).alias(col))
        combined = pl.concat([sa.select(sorted(all_cols)), irb.select(sorted(all_cols))])
        bundle = generator.generate_from_lazyframe(
            combined.lazy(),
            framework="BASEL_3_1",
        )
        assert len(bundle.cr9) > 0
        assert bundle.ov1 is not None
        assert bundle.cr4 is not None


class TestCR9ExcelExport:
    """Tests for CR9 Excel export."""

    def test_export_includes_cr9_sheets(
        self,
        generator: Pillar3Generator,
        tmp_path: Path,
    ):
        """CR9 templates should be written to Excel sheets."""
        data = _make_cr9_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        output = tmp_path / "pillar3_cr9.xlsx"
        result = generator.export_to_excel(bundle, output)
        assert output.exists()
        # CR9 rows should be included in total row count
        cr9_rows = sum(df.height for df in bundle.cr9.values())
        assert result.row_count >= cr9_rows


# =============================================================================
# P1.94g — DELIV1: CR5 buckets mismatch rows on pre-mismatch risk weight
# =============================================================================


class TestCR9ObligorClassBasis:
    """The recorded F3 close-out: CR9 sheets key the OBLIGOR applied class —
    substitution never moves a back-testing sheet ("without considering any
    substitution effects due to CRM")."""

    def _make_substituted_cr9_data(self) -> pl.LazyFrame:
        """Two physical legs of one guaranteed F-IRB corporate whose covered
        leg substitutes to a sovereign guarantor post-CRM."""
        return _make_cr9_irb_data(
            exposure_reference=["G1__G_SOV", "G1__REM", "CR9_3", "CR9_4", "CR9_5", "CR9_6"],
            approach_applied=[
                "foundation_irb",
                "foundation_irb",
                "advanced_irb",
                "advanced_irb",
                "advanced_irb",
                "advanced_irb",
            ],
            exposure_class=[
                "corporate",
                "corporate",
                "retail_mortgage",
                "retail_mortgage",
                "retail_other",
                "retail_other",
            ],
            exposure_class_applied=[
                "corporate",
                "corporate",
                "retail_mortgage",
                "retail_mortgage",
                "retail_other",
                "retail_other",
            ],
            exposure_class_post_crm=[
                "central_govt_central_bank",
                "corporate",
                "retail_mortgage",
                "retail_mortgage",
                "retail_other",
                "retail_other",
            ],
            counterparty_reference=["CP1", "CP1", "CP3", "CP4", "CP5", "CP6"],
        )

    def test_substituted_legs_stay_in_obligor_class_sheet(self, generator: Pillar3Generator):
        bundle = generator.generate_from_lazyframe(
            self._make_substituted_cr9_data(), framework="BASEL_3_1"
        )
        assert "foundation_irb - central_govt_central_bank" not in bundle.cr9
        corp = bundle.cr9["foundation_irb - corporate_other_non_sme"]
        total = corp.filter(pl.col("row_ref") == "18")
        assert total["c"][0] == pytest.approx(1.0)  # one obligor, both legs

    def test_defaulted_low_model_pd_forced_to_100pct_band(self, generator: Pillar3Generator):
        """Recorded fix (mirrors CR6): a defaulted obligor at a model PD
        below 100% still lands in the 100% band row."""
        data = _make_cr9_irb_data(
            is_defaulted=[True, False, False, False, False, True],
            pd=[0.018, 0.004, 0.009, 0.007, 0.025, 1.0],
        )
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        corp = bundle.cr9["foundation_irb - corporate_other_non_sme"]
        refs = corp["row_ref"].to_list()
        assert "17" in refs  # CP1 forced to the 100% band despite pd=0.018
        band_10 = corp.filter(pl.col("row_ref") == "10")
        assert band_10.height == 0  # not left in the model-PD band
