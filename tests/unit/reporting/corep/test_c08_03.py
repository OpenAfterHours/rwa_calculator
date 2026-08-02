"""COREP C 08.03 / OF 08.03 generation tests.

Split from tests/unit/test_corep.py (Phase 7 Sn) — bodies verbatim.
"""

from __future__ import annotations

import itertools
import math

import polars as pl
import pytest

from rwa_calc.reporting.corep.generator import COREPTemplateBundle
from tests.fixtures.recon_ledger import LedgerShimCorepGenerator


def _irb_pd_range_results() -> pl.LazyFrame:
    """Synthetic IRB results spanning multiple PD ranges for C 08.03 testing.

    Covers 5 exposures across 5 leaf PD ranges (CRR allocation, on pd_floored):
    - PD 0.002 (0.20%) → "0.15 to <0.25"  (row 0040)
    - PD 0.005 (0.50%) → "0.50 to <0.75"  (row 0060)
    - PD 0.01  (1.00%) → "0.75 to <1.75"  (row 0080, under parent 0070)
    - PD 0.03  (3.00%) → "2.5 to <5"      (row 0110, under parent 0100)
    - PD 1.0   (100%)  → "100 (Default)"  (row 0170)

    Two of the five sit under a parent band, so the sheet emits 7 rows: five
    leaves plus parents 0070 and 0100.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["E1", "E2", "E3", "E4", "E5"],
            "approach_applied": [
                "foundation_irb",
                "foundation_irb",
                "advanced_irb",
                "foundation_irb",
                "foundation_irb",
            ],
            "exposure_class": [
                "corporate",
                "corporate",
                "corporate",
                "corporate",
                "corporate",
            ],
            "drawn_amount": [5000.0, 3000.0, 2000.0, 1000.0, 500.0],
            "undrawn_amount": [1000.0, 0.0, 500.0, 0.0, 0.0],
            "nominal_amount": [1000.0, 0.0, 500.0, 0.0, 0.0],
            "ead_final": [5500.0, 3000.0, 2200.0, 1000.0, 500.0],
            "rwa_final": [2750.0, 1800.0, 1540.0, 750.0, 0.0],
            "risk_weight": [0.50, 0.60, 0.70, 0.75, 0.0],
            "pd_floored": [0.002, 0.005, 0.01, 0.03, 1.0],
            "pd": [0.001, 0.004, 0.01, 0.03, 1.0],
            "lgd_floored": [0.45, 0.45, 0.35, 0.40, 0.45],
            "irb_maturity_m": [2.5, 3.0, 2.0, 4.0, 1.0],
            "expected_loss": [4.95, 6.75, 7.7, 12.0, 225.0],
            "provision_held": [5.0, 8.0, 6.0, 15.0, 200.0],
            "scra_provision_amount": [3.0, 4.0, 3.0, 8.0, 100.0],
            "gcra_provision_amount": [2.0, 4.0, 3.0, 7.0, 100.0],
            "counterparty_reference": ["CP_A", "CP_B", "CP_C", "CP_D", "CP_E"],
            "ccf": [0.5, 0.0, 0.4, 0.0, 0.0],
        }
    )


def _irb_multi_class_pd_range() -> pl.LazyFrame:
    """IRB results with multiple exposure classes for per-class C 08.03 testing."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["E1", "E2", "E3", "E4"],
            "approach_applied": [
                "foundation_irb",
                "foundation_irb",
                "advanced_irb",
                "foundation_irb",
            ],
            "exposure_class": [
                "corporate",
                "corporate",
                "institution",
                "retail_mortgage",
            ],
            "drawn_amount": [5000.0, 3000.0, 2000.0, 4000.0],
            "nominal_amount": [1000.0, 0.0, 0.0, 0.0],
            "ead_final": [5500.0, 3000.0, 2000.0, 4000.0],
            "rwa_final": [2750.0, 1800.0, 600.0, 1200.0],
            "pd_floored": [0.005, 0.01, 0.002, 0.003],
            "lgd_floored": [0.45, 0.45, 0.45, 0.15],
            "irb_maturity_m": [2.5, 3.0, 1.5, 20.0],
            "expected_loss": [12.375, 13.5, 1.8, 1.8],
            "provision_held": [15.0, 10.0, 3.0, 2.5],
            "counterparty_reference": ["CP_A", "CP_B", "CP_C", "CP_D"],
        }
    )


class TestC0803TemplateDefinitions:
    """Tests for C 08.03 / OF 08.03 template structure definitions."""

    def test_crr_c0803_has_11_columns(self) -> None:
        """CRR C 08.03 has exactly 11 columns."""
        from rwa_calc.reporting.corep.templates import CRR_C08_03_COLUMNS

        assert len(CRR_C08_03_COLUMNS) == 11

    def test_b31_c0803_has_11_columns(self) -> None:
        """Basel 3.1 OF 08.03 has exactly 11 columns."""
        from rwa_calc.reporting.corep.templates import B31_C08_03_COLUMNS

        assert len(B31_C08_03_COLUMNS) == 11

    def test_crr_row_axis_matches_published_template(self) -> None:
        """CRR C 08.03 reproduces the published PD scale row-for-row.

        Source: Regulation (EU) 2021/451 Annex I, template C 08.03 (sheet 8.3 of
        the onshored COREP own-funds workbook in docs/assets).
        """
        from rwa_calc.reporting.corep.templates import get_c08_03_pd_ranges

        assert [(ref, label) for _lo, _hi, ref, label in get_c08_03_pd_ranges("CRR")] == [
            ("0010", "0.00 to <0.15"),
            ("0020", "0.00 to <0.10"),
            ("0030", "0.10 to <0.15"),
            ("0040", "0.15 to <0.25"),
            ("0050", "0.25 to <0.50"),
            ("0060", "0.50 to <0.75"),
            ("0070", "0.75 to <2.5"),
            ("0080", "0.75 to <1.75"),
            ("0090", "1.75 to <2.5"),
            ("0100", "2.5 to <10"),
            ("0110", "2.5 to <5"),
            ("0120", "5 to <10"),
            ("0130", "10 to <100"),
            ("0140", "10 to <20"),
            ("0150", "20 to <30"),
            ("0160", "30 to <100"),
            ("0170", "100 (Default)"),
        ]

    def test_b31_row_axis_splits_the_first_sub_band_at_five_basis_points(self) -> None:
        """OF 08.03 replaces CRR row 0020 with rows 0015/0025, giving 18 rows.

        Source: PRA PS1/26 Annex I, template OF 08.03.
        """
        from rwa_calc.reporting.corep.templates import get_c08_03_pd_ranges

        b31 = get_c08_03_pd_ranges("BASEL_3_1")
        assert [(ref, label) for _lo, _hi, ref, label in b31[:4]] == [
            ("0010", "0.00 to <0.15"),
            ("0015", "0.00 to <0.05"),
            ("0025", "0.05 to <0.10"),
            ("0030", "0.10 to <0.15"),
        ]
        # Everything from 0.15% up is identical to CRR.
        assert b31[4:] == get_c08_03_pd_ranges("CRR")[3:]

    @pytest.mark.parametrize("framework", ["CRR", "BASEL_3_1"])
    def test_parent_rows_span_exactly_their_children(self, framework: str) -> None:
        """Each parent row's band is the union of the sub-band rows below it.

        This is the structure the published validation rules assert — EBA
        v09753-v09756 / BoE boe_b0767-boe_b0770, e.g. {r0070} = {r0080}+{r0090}
        — and it is what a flat, non-overlapping scale can never satisfy.
        """
        from rwa_calc.reporting.corep.templates import (
            C08_03_PD_PARENT_REFS,
            get_c08_03_pd_ranges,
        )

        ranges = get_c08_03_pd_ranges(framework)
        parent_idx = [i for i, band in enumerate(ranges) if band[2] in C08_03_PD_PARENT_REFS]
        assert len(parent_idx) == 4

        for i in parent_idx:
            lower, upper, ref, _label = ranges[i]
            children = list(itertools.takewhile(lambda b, hi=upper: b[0] < hi, ranges[i + 1 :]))
            assert len(children) >= 2, f"row {ref} has no sub-breakdown"
            assert children[0][0] == pytest.approx(lower), f"row {ref} children start late"
            assert children[-1][1] == pytest.approx(upper), f"row {ref} children end early"
            for first, second in itertools.pairwise(children):
                assert first[1] == pytest.approx(second[0]), f"row {ref} children have a gap"

    @pytest.mark.parametrize("framework", ["CRR", "BASEL_3_1"])
    def test_leaf_rows_partition_the_pd_spectrum(self, framework: str) -> None:
        """Stripping the parents leaves a clean tiling of [0, inf), so every
        exposure lands in exactly one row and is counted exactly once."""
        from rwa_calc.reporting.corep.templates import (
            C08_03_PD_PARENT_REFS,
            get_c08_03_pd_ranges,
        )

        leaves = [b for b in get_c08_03_pd_ranges(framework) if b[2] not in C08_03_PD_PARENT_REFS]
        assert leaves[0][0] == pytest.approx(0.0, abs=1e-10)
        assert math.isinf(leaves[-1][1])
        for first, second in itertools.pairwise(leaves):
            assert first[1] == pytest.approx(second[0])

    def test_column_refs_list_matches_columns(self) -> None:
        """C08_03_COLUMN_REFS is derived from CRR_C08_03_COLUMNS refs."""
        from rwa_calc.reporting.corep.templates import C08_03_COLUMN_REFS, CRR_C08_03_COLUMNS

        assert [c.ref for c in CRR_C08_03_COLUMNS] == C08_03_COLUMN_REFS

    def test_get_c08_03_columns_crr(self) -> None:
        """get_c08_03_columns returns CRR columns for 'CRR' framework."""
        from rwa_calc.reporting.corep.templates import CRR_C08_03_COLUMNS, get_c08_03_columns

        assert get_c08_03_columns("CRR") is CRR_C08_03_COLUMNS

    def test_get_c08_03_columns_b31(self) -> None:
        """get_c08_03_columns returns B31 columns for 'BASEL_3_1' framework."""
        from rwa_calc.reporting.corep.templates import B31_C08_03_COLUMNS, get_c08_03_columns

        assert get_c08_03_columns("BASEL_3_1") is B31_C08_03_COLUMNS

    def test_b31_pd_column_name_includes_post_floor(self) -> None:
        """Basel 3.1 OF 08.03 col 0050 name specifies 'post input floor'."""
        from rwa_calc.reporting.corep.templates import B31_C08_03_COLUMNS

        pd_col = next(c for c in B31_C08_03_COLUMNS if c.ref == "0050")
        assert "post input floor" in pd_col.name.lower()


class TestC0803Generation:
    """Tests for C 08.03 DataFrame generation from IRB pipeline results."""

    def test_c0803_produces_per_class_output(self) -> None:
        """C 08.03 produces a dict keyed by exposure class."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results())
        assert isinstance(bundle.c08_03, dict)
        assert "corporate" in bundle.c08_03

    def test_c0803_multiple_classes(self) -> None:
        """C 08.03 produces separate DataFrames for each IRB exposure class."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_multi_class_pd_range())
        assert "corporate" in bundle.c08_03
        assert "institution" in bundle.c08_03
        assert "retail_mortgage" in bundle.c08_03

    def test_c0803_has_11_columns_plus_row_metadata(self) -> None:
        """Each C 08.03 DataFrame has 11 data columns + 2 metadata (row_ref, row_name)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results())
        corp = bundle.c08_03["corporate"]
        # 11 data columns + row_ref + row_name = 13
        assert len(corp.columns) == 13

    def test_c0803_empty_for_sa_only(self) -> None:
        """C 08.03 is empty when only SA exposures exist."""
        gen = LedgerShimCorepGenerator()
        results = pl.LazyFrame(
            {
                "exposure_reference": ["E1"],
                "approach_applied": ["standardised"],
                "exposure_class": ["corporate"],
                "ead_final": [1000.0],
                "rwa_final": [500.0],
            }
        )
        bundle = gen.generate_from_lazyframe(results)
        assert bundle.c08_03 == {}

    def test_c0803_excludes_slotting(self) -> None:
        """C 08.03 excludes slotting exposures — only F-IRB/A-IRB."""
        gen = LedgerShimCorepGenerator()
        results = pl.LazyFrame(
            {
                "exposure_reference": ["E1", "E2"],
                "approach_applied": ["foundation_irb", "slotting"],
                "exposure_class": ["corporate", "specialised_lending"],
                "ead_final": [5000.0, 3000.0],
                "rwa_final": [2500.0, 2100.0],
                "pd_floored": [0.005, 0.0],
                "lgd_floored": [0.45, 0.0],
                "counterparty_reference": ["CP_A", "CP_B"],
            }
        )
        bundle = gen.generate_from_lazyframe(results)
        # Only corporate should appear (slotting excluded)
        assert "corporate" in bundle.c08_03
        assert "specialised_lending" not in bundle.c08_03


class TestC0803PDRangeAssignment:
    """Tests for correct PD range bucket assignment in C 08.03."""

    def test_pd_002_lands_in_015_025_bucket(self) -> None:
        """PD 0.002 (0.20%) falls in the '0.15 to <0.25' band (row 0040)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results())
        corp = bundle.c08_03["corporate"]
        row = corp.filter(pl.col("row_ref") == "0040")
        assert len(row) == 1
        assert row["row_name"][0] == "0.15 to <0.25"

    def test_pd_005_lands_in_050_075_bucket(self) -> None:
        """PD 0.005 (0.50%) falls in the '0.50 to <0.75' band (row 0060)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results())
        corp = bundle.c08_03["corporate"]
        row = corp.filter(pl.col("row_ref") == "0060")
        assert len(row) == 1
        assert row["row_name"][0] == "0.50 to <0.75"

    def test_pd_001_lands_in_075_175_bucket_under_its_parent(self) -> None:
        """PD 0.01 (1.00%) falls in the '0.75 to <1.75' leaf (row 0080), and
        its parent '0.75 to <2.5' (row 0070) is emitted alongside it."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results())
        corp = bundle.c08_03["corporate"]
        leaf = corp.filter(pl.col("row_ref") == "0080")
        assert len(leaf) == 1
        assert leaf["row_name"][0] == "0.75 to <1.75"
        parent = corp.filter(pl.col("row_ref") == "0070")
        assert len(parent) == 1
        assert parent["row_name"][0] == "0.75 to <2.5"

    def test_pd_003_lands_in_250_500_bucket(self) -> None:
        """PD 0.03 (3.00%) falls in the '2.5 to <5' band (row 0110)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results())
        corp = bundle.c08_03["corporate"]
        row = corp.filter(pl.col("row_ref") == "0110")
        assert len(row) == 1

    def test_pd_100_lands_in_default_bucket(self) -> None:
        """PD 1.0 (100%) falls in the '100 (Default)' band (row 0170)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results())
        corp = bundle.c08_03["corporate"]
        row = corp.filter(pl.col("row_ref") == "0170")
        assert len(row) == 1
        assert row["row_name"][0] == "100 (Default)"

    def test_empty_buckets_omitted(self) -> None:
        """PD range buckets with no exposures are not included in output."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results())
        corp = bundle.c08_03["corporate"]
        # 5 populated leaves (PDs 0.002, 0.005, 0.01, 0.03, 1.0) + the 2 parent
        # bands enclosing them (0070 over 0080, 0100 over 0110).
        assert len(corp) == 7
        assert corp["row_ref"].to_list() == ["0040", "0060", "0070", "0080", "0100", "0110", "0170"]

    def test_parent_row_never_emits_without_its_children(self) -> None:
        """A parent band is only reported when at least one of its sub-bands
        is populated, so a parent row can never appear alone."""
        from rwa_calc.reporting.corep.templates import C08_03_PD_PARENT_REFS

        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results())
        refs = set(bundle.c08_03["corporate"]["row_ref"].to_list())
        assert refs & C08_03_PD_PARENT_REFS == {"0070", "0100"}


class TestC0803ColumnValues:
    """Tests for C 08.03 column value computation."""

    def test_ead_in_050_075_bucket(self) -> None:
        """Col 0040 (EAD) in 0.50-0.75% bucket equals the single exposure's EAD."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results())
        corp = bundle.c08_03["corporate"]
        row = corp.filter(pl.col("row_ref") == "0060")
        # E2: PD=0.005, EAD=3000
        assert row["0040"][0] == pytest.approx(3000.0, rel=1e-4)

    def test_rwea_in_050_075_bucket(self) -> None:
        """Col 0090 (RWEA) in 0.50-0.75% bucket equals the single exposure's RWA."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results())
        corp = bundle.c08_03["corporate"]
        row = corp.filter(pl.col("row_ref") == "0060")
        # E2: RWA=1800
        assert row["0090"][0] == pytest.approx(1800.0, rel=1e-4)

    def test_avg_pd_single_exposure(self) -> None:
        """Col 0050 (avg PD) for a single-exposure bucket equals that exposure's PD."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results())
        corp = bundle.c08_03["corporate"]
        row = corp.filter(pl.col("row_ref") == "0060")
        # E2: PD=0.005
        assert row["0050"][0] == pytest.approx(0.005, rel=1e-6)

    def test_avg_lgd_single_exposure(self) -> None:
        """Col 0070 (avg LGD) for a single-exposure bucket equals that exposure's LGD."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results())
        corp = bundle.c08_03["corporate"]
        row = corp.filter(pl.col("row_ref") == "0060")
        # E2: LGD=0.45
        assert row["0070"][0] == pytest.approx(0.45, rel=1e-6)

    def test_avg_maturity_in_years(self) -> None:
        """Col 0080 (avg maturity) is reported in years (not days like C 08.01)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results())
        corp = bundle.c08_03["corporate"]
        row = corp.filter(pl.col("row_ref") == "0060")
        # E2: maturity=3.0 years
        assert row["0080"][0] == pytest.approx(3.0, rel=1e-4)

    def test_expected_loss(self) -> None:
        """Col 0100 (EL) sums expected loss for the bucket."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results())
        corp = bundle.c08_03["corporate"]
        row = corp.filter(pl.col("row_ref") == "0060")
        # E2: EL=6.75
        assert row["0100"][0] == pytest.approx(6.75, rel=1e-4)

    def test_provisions(self) -> None:
        """Col 0110 (provisions) sums scra + gcra provisions for the bucket."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results())
        corp = bundle.c08_03["corporate"]
        row = corp.filter(pl.col("row_ref") == "0060")
        # E2: scra=4.0 + gcra=4.0 = 8.0
        assert row["0110"][0] == pytest.approx(8.0, rel=1e-4)

    def test_obligor_count(self) -> None:
        """Col 0060 (obligors) counts unique counterparty references."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results())
        corp = bundle.c08_03["corporate"]
        row = corp.filter(pl.col("row_ref") == "0060")
        # E2: 1 counterparty (CP_B)
        assert row["0060"][0] == pytest.approx(1.0)

    def test_on_bs_exposure(self) -> None:
        """Col 0010 (on-BS) sums drawn_amount + interest for the bucket."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results())
        corp = bundle.c08_03["corporate"]
        row = corp.filter(pl.col("row_ref") == "0060")
        # E2: drawn=3000, no interest column so drawn only
        assert row["0010"][0] == pytest.approx(3000.0, rel=1e-4)

    def test_off_bs_exposure(self) -> None:
        """Col 0020 (off-BS) sums nominal_amount for the bucket."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results())
        corp = bundle.c08_03["corporate"]
        row = corp.filter(pl.col("row_ref") == "0040")
        # E1: nominal=1000
        assert row["0020"][0] == pytest.approx(1000.0, rel=1e-4)

    def test_default_bucket_has_zero_rwa(self) -> None:
        """Default bucket (PD=100%) has RWEA=0 (K=0 for defaulted exposures)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results())
        corp = bundle.c08_03["corporate"]
        row = corp.filter(pl.col("row_ref") == "0170")
        assert row["0090"][0] == pytest.approx(0.0, abs=1e-4)


class TestC0803B31Features:
    """Tests for Basel 3.1-specific C 08.03 / OF 08.03 features."""

    def test_b31_row_allocation_uses_pre_floor_pd(self) -> None:
        """Basel 3.1 OF 08.03 allocates rows using pre-input-floor PD.

        E1 has pd=0.001 (0.10%), which falls in "0.10 to <0.15" (row 0030),
        even though pd_floored=0.002 (0.20%) would fall in "0.15 to <0.25"
        (row 0040). Asserting 0040 is ABSENT is what pins the basis.
        """
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results(), framework="BASEL_3_1")
        corp = bundle.c08_03["corporate"]
        refs = corp["row_ref"].to_list()
        assert "0030" in refs  # pre-input-floor band
        assert "0040" not in refs  # the post-floor band, not used for allocation

    def test_b31_pd_value_reports_post_floor(self) -> None:
        """Basel 3.1 OF 08.03 col 0050 reports post-input-floor PD.

        E1 is in the "0.10 to <0.15" band (by original PD 0.001) but
        col 0050 should report floored PD 0.002.
        """
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results(), framework="BASEL_3_1")
        corp = bundle.c08_03["corporate"]
        row = corp.filter(pl.col("row_ref") == "0030")
        # E1: post-floor PD=0.002
        assert row["0050"][0] == pytest.approx(0.002, rel=1e-6)

    def test_crr_uses_floored_pd_for_allocation(self) -> None:
        """CRR C 08.03 uses floored PD for both allocation and reporting.

        E1 has pd_floored=0.002 (0.20%) → "0.15 to <0.25" (row 0040), while
        its pre-floor pd=0.001 would have landed in row 0030.
        """
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results(), framework="CRR")
        corp = bundle.c08_03["corporate"]
        refs = corp["row_ref"].to_list()
        assert "0040" in refs  # the floored band
        assert "0030" not in refs  # the pre-floor band, not used under CRR

    def test_b31_has_11_columns(self) -> None:
        """Basel 3.1 C 08.03 still produces 11 data columns + 2 metadata."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results(), framework="BASEL_3_1")
        corp = bundle.c08_03["corporate"]
        assert len(corp.columns) == 13


class TestC0803EdgeCases:
    """Edge case tests for C 08.03 generation."""

    def test_no_pd_column_returns_empty(self) -> None:
        """C 08.03 returns empty dict when no PD column is available."""
        gen = LedgerShimCorepGenerator()
        results = pl.LazyFrame(
            {
                "exposure_reference": ["E1"],
                "approach_applied": ["foundation_irb"],
                "exposure_class": ["corporate"],
                "ead_final": [1000.0],
                "rwa_final": [500.0],
            }
        )
        bundle = gen.generate_from_lazyframe(results)
        assert bundle.c08_03 == {}

    def test_no_irb_data_returns_empty(self) -> None:
        """C 08.03 returns empty dict when no IRB exposures exist."""
        gen = LedgerShimCorepGenerator()
        results = pl.LazyFrame(
            {
                "exposure_reference": ["E1"],
                "approach_applied": ["standardised"],
                "exposure_class": ["corporate"],
                "ead_final": [1000.0],
                "rwa_final": [500.0],
                "pd_floored": [0.01],
            }
        )
        bundle = gen.generate_from_lazyframe(results)
        assert bundle.c08_03 == {}

    def test_c0803_bundle_default_is_empty_dict(self) -> None:
        """COREPTemplateBundle.c08_03 defaults to empty dict."""
        bundle = COREPTemplateBundle(c07_00={}, c08_01={}, c08_02={})
        assert bundle.c08_03 == {}

    def test_null_pd_goes_to_unassigned(self) -> None:
        """Exposures with null PD go to 'Unassigned' row."""
        gen = LedgerShimCorepGenerator()
        results = pl.LazyFrame(
            {
                "exposure_reference": ["E1", "E2"],
                "approach_applied": ["foundation_irb", "foundation_irb"],
                "exposure_class": ["corporate", "corporate"],
                "ead_final": [1000.0, 2000.0],
                "rwa_final": [500.0, 1000.0],
                "pd_floored": [0.005, None],
                "counterparty_reference": ["CP_A", "CP_B"],
            }
        )
        bundle = gen.generate_from_lazyframe(results)
        corp = bundle.c08_03["corporate"]
        unassigned = corp.filter(pl.col("row_name") == "Unassigned")
        assert len(unassigned) == 1
        assert unassigned["0040"][0] == pytest.approx(2000.0)

    def test_total_ead_across_leaf_buckets(self) -> None:
        """EAD summed over the LEAF bands equals total input EAD.

        Parent bands must be excluded: they repeat their children's span, so
        summing every emitted row would double-count.
        """
        from rwa_calc.reporting.corep.templates import C08_03_PD_PARENT_REFS

        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results())
        corp = bundle.c08_03["corporate"]
        leaves = corp.filter(~pl.col("row_ref").is_in(list(C08_03_PD_PARENT_REFS)))
        # Sum of all input EADs: 5500 + 3000 + 2200 + 1000 + 500 = 12200
        assert leaves["0040"].sum() == pytest.approx(12200.0, rel=1e-4)

    def test_total_rwea_across_leaf_buckets(self) -> None:
        """RWEA summed over the LEAF bands equals total input RWEA."""
        from rwa_calc.reporting.corep.templates import C08_03_PD_PARENT_REFS

        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results())
        corp = bundle.c08_03["corporate"]
        leaves = corp.filter(~pl.col("row_ref").is_in(list(C08_03_PD_PARENT_REFS)))
        # Sum: 2750 + 1800 + 1540 + 750 + 0 = 6840
        assert leaves["0090"].sum() == pytest.approx(6840.0, rel=1e-4)

    def test_parent_band_equals_sum_of_its_children(self) -> None:
        """Row 0070 = row 0080 + row 0090 on every additive column — the
        invariant EBA v09754 / BoE boe_b0768 assert. Only 0080 is populated
        here, so the parent must equal it exactly.
        """
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results())
        corp = bundle.c08_03["corporate"]
        parent = corp.filter(pl.col("row_ref") == "0070")
        child = corp.filter(pl.col("row_ref") == "0080")
        for col in ("0010", "0020", "0040", "0060", "0090", "0100", "0110"):
            assert parent[col][0] == pytest.approx(child[col][0]), col

    def test_ccf_average_weighted_by_nominal(self) -> None:
        """Col 0030 (avg CCF) is weighted by nominal amount, not EAD."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results())
        corp = bundle.c08_03["corporate"]
        # E1 (PD=0.002, row 0040): nominal=1000, ccf=0.5 → avg=0.5
        row = corp.filter(pl.col("row_ref") == "0040")
        assert row["0030"][0] == pytest.approx(0.5, rel=1e-4)

    def test_zero_nominal_bucket_has_null_ccf(self) -> None:
        """Bucket with zero nominal amount has null average CCF."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results())
        corp = bundle.c08_03["corporate"]
        # E2 (PD=0.005, row 0060): nominal=0, ccf=0 → null
        row = corp.filter(pl.col("row_ref") == "0060")
        assert row["0030"][0] is None


class TestC0803SealedGrossSideCarriers:
    """Sealed-shape (``exposure_type``-bearing) frames exercising the
    gross-side-carrier fix.

    Root cause: the legacy on/off-BS ladder classifies ``exposure_type``
    "loan" -> on, "facility"/"contingent" -> off, anything else -> null — but
    the unified pipeline never emits "facility" (a dead value), only
    "facility_undrawn". So every facility_undrawn leg (undrawn commitment
    headroom) is dropped from BOTH gross columns (0010/0020) while its EAD
    stays in 0040 — the user-reported symptom (EAD >> gross with no
    inflows). See .claude/state/gross-side-carriers-spec.md.
    """

    def _mixed_gross_side_carrier_results(self) -> pl.LazyFrame:
        """Three PD bands, corporate, foundation_irb:

        - band 0060 (pd 0.005): loan + contingent + facility_undrawn — the
          reported bug in miniature.
        - band 0110 (pd 0.03): loan + facility_undrawn only, no contingent —
          pins that deleting the retired whole-bucket fallback does not
          regress this simpler case (today's fallback rescues col 0020 to
          the right number by accident; the sealed carrier must reproduce
          the SAME value).
        - band 0080 (pd 0.01): the same trio as 0060 plus a CCR netting-set
          leg — pins the recorded scope decision that COREP C 08.x keeps CCR
          in the EAD population (0040) while its null side-carriers keep it
          OUT of the on/off-BS split (0010/0020).
        """
        return pl.LazyFrame(
            {
                "exposure_reference": [
                    "LN_A",
                    "CO_A",
                    "FU_A",
                    "LN_B",
                    "FU_B",
                    "LN_C",
                    "CO_C",
                    "FU_C",
                    "NS_C",
                ],
                "counterparty_reference": [
                    "CPA1",
                    "CPA2",
                    "CPA3",
                    "CPB1",
                    "CPB2",
                    "CPC1",
                    "CPC2",
                    "CPC3",
                    "CPC4",
                ],
                "approach_applied": ["foundation_irb"] * 9,
                "exposure_class": ["corporate"] * 9,
                "exposure_type": [
                    "loan",
                    "contingent",
                    "facility_undrawn",
                    "loan",
                    "facility_undrawn",
                    "loan",
                    "contingent",
                    "facility_undrawn",
                    "ccr_netting_set",
                ],
                "drawn_amount": [5000.0, 0.0, 0.0, 5000.0, 0.0, 5000.0, 0.0, 0.0, 0.0],
                "interest": [0.0] * 9,
                "nominal_amount": [0.0, 2000.0, 4000.0, 0.0, 4000.0, 0.0, 2000.0, 4000.0, 0.0],
                "undrawn_amount": [0.0, 0.0, 4000.0, 0.0, 4000.0, 0.0, 0.0, 4000.0, 0.0],
                "ead_final": [
                    5000.0,
                    1000.0,
                    3000.0,
                    5000.0,
                    3000.0,
                    5000.0,
                    1000.0,
                    3000.0,
                    2000.0,
                ],
                "rwa_final": [2500.0, 500.0, 1500.0, 2500.0, 1500.0, 2500.0, 500.0, 1500.0, 2500.0],
                "pd_floored": [0.005, 0.005, 0.005, 0.03, 0.03, 0.01, 0.01, 0.01, 0.01],
                "lgd_floored": [0.45] * 9,
                "irb_maturity_m": [2.5] * 9,
                "ccf": [None, 0.5, 0.75, None, 0.75, None, 0.5, 0.75, None],
            }
        )

    def test_c0803_mixed_band_gross_split_and_ead(self) -> None:
        """Band 0060 (loan+contingent+facility_undrawn): col 0020 must count
        the facility_undrawn headroom once (today it is dropped entirely),
        and the gross total (0010+0020) must exceed the EAD (0040) by exactly
        the off-BS CCF haircut — never fall short of it, as the reported bug
        did.
        """
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(self._mixed_gross_side_carrier_results())
        corp = bundle.c08_03["corporate"]
        band = corp.filter(pl.col("row_ref") == "0060")

        assert band["0010"][0] == pytest.approx(5000.0)  # on-BS: loan drawn+interest
        assert band["0020"][0] == pytest.approx(6000.0)  # off-BS: contingent 2000 + FU 4000
        assert band["0040"][0] == pytest.approx(9000.0)  # EAD unaffected by the bs-split bug

        gross_total = band["0010"][0] + band["0020"][0]
        ead_total = band["0040"][0]
        # 2000 nominal * (1 - 0.5 ccf) + 4000 nominal * (1 - 0.75 ccf) = 2000;
        # gross must EXCEED ead by exactly the CCF haircut, never fall short
        # of it (falling short — with no inflow to explain it — was the bug).
        assert gross_total - ead_total == pytest.approx(2000.0)

        # Band 0110 (loan + facility_undrawn, no contingent): the retired
        # whole-bucket fallback already rescues col 0020 to the right number
        # by accident today — the sealed carrier must reproduce the SAME
        # value once the fallback is deleted, not regress it.
        band_no_contingent = corp.filter(pl.col("row_ref") == "0110")
        assert band_no_contingent["0010"][0] == pytest.approx(5000.0)
        assert band_no_contingent["0020"][0] == pytest.approx(4000.0)
        assert band_no_contingent["0040"][0] == pytest.approx(8000.0)

        # Band 0080 (the mixed trio + a CCR netting-set leg): CCR stays IN
        # the EAD population (0040 gains its 2000) but its null side-carriers
        # keep it OUT of the on/off-BS split — 0010/0020 match band 0060.
        band_with_ccr = corp.filter(pl.col("row_ref") == "0080")
        assert band_with_ccr["0010"][0] == pytest.approx(5000.0)
        assert band_with_ccr["0020"][0] == pytest.approx(6000.0)
        assert band_with_ccr["0040"][0] == pytest.approx(11000.0)  # 9000 + 2000 CCR
