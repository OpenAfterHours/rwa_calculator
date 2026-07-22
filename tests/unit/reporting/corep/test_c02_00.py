"""COREP C 02.00 / OF 02.00 own-funds roll-up tests.

Split from tests/unit/test_corep.py (Phase 7 Sn) — bodies verbatim.
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.contracts.bundles import OutputFloorSummary
from rwa_calc.reporting.corep.generator import COREPTemplateBundle
from rwa_calc.reporting.corep.templates import (
    B31_C02_00_COLUMN_REFS,
    B31_C02_00_COLUMNS,
    B31_C02_00_ROW_SECTIONS,
    C02_00_SA_CLASS_MAP,
    CRR_C02_00_COLUMN_REFS,
    CRR_C02_00_COLUMNS,
    CRR_C02_00_ROW_SECTIONS,
    get_c02_00_columns,
    get_c02_00_row_sections,
)
from tests.fixtures.recon_ledger import LedgerShimCorepGenerator
from tests.unit.reporting.corep._builders import (
    _sa_results_with_currency_mismatch,
)


def _c02_sa_results() -> pl.LazyFrame:
    """SA-only results for C 02.00 testing."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["S1", "S2", "S3", "S4"],
            "approach_applied": ["standardised"] * 4,
            "exposure_class": ["corporate", "institution", "retail", "central_government"],
            "ead_final": [1000.0, 500.0, 300.0, 200.0],
            "risk_weight": [1.0, 0.2, 0.75, 0.0],
            "rwa_final": [1000.0, 100.0, 225.0, 0.0],
        }
    )


def _c02_mixed_results() -> pl.LazyFrame:
    """Mixed SA + IRB results for C 02.00 testing."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["S1", "S2", "I1", "I2", "SL1"],
            "approach_applied": [
                "standardised",
                "standardised",
                "foundation_irb",
                "advanced_irb",
                "slotting",
            ],
            "exposure_class": [
                "corporate",
                "institution",
                "corporate",
                "retail_mortgage",
                "specialised_lending",
            ],
            "ead_final": [1000.0, 500.0, 2000.0, 800.0, 600.0],
            "risk_weight": [1.0, 0.2, 0.5, 0.3, 0.7],
            "rwa_final": [1000.0, 100.0, 1000.0, 240.0, 420.0],
        }
    )


def _c02_b31_results_with_floor() -> pl.LazyFrame:
    """Basel 3.1 results with output floor columns."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["S1", "I1", "I2", "SL1"],
            "approach_applied": [
                "standardised",
                "foundation_irb",
                "advanced_irb",
                "slotting",
            ],
            "exposure_class": [
                "corporate",
                "corporate",
                "retail_mortgage",
                "specialised_lending",
            ],
            "ead_final": [1000.0, 2000.0, 800.0, 600.0],
            "risk_weight": [1.0, 0.5, 0.3, 0.7],
            "rwa_final": [1000.0, 1000.0, 240.0, 420.0],
            "rwa_pre_floor": [1000.0, 1000.0, 240.0, 420.0],
            "sa_rwa": [1000.0, 1500.0, 400.0, 500.0],
            "sl_type": [None, None, None, "project_finance"],
        }
    )


def _c02_b31_floor_binding() -> pl.LazyFrame:
    """Basel 3.1 results where floor is binding (total RWA > pre-floor)."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["I1", "I2"],
            "approach_applied": ["foundation_irb", "advanced_irb"],
            "exposure_class": ["corporate", "retail_mortgage"],
            "ead_final": [2000.0, 800.0],
            "risk_weight": [0.15, 0.1],
            "rwa_final": [600.0, 280.0],  # Post-floor (higher)
            "rwa_pre_floor": [300.0, 80.0],  # Pre-floor (lower)
            "sa_rwa": [1500.0, 400.0],
        }
    )


def _irb_results_with_sme_fse() -> pl.LazyFrame:
    """IRB results with is_sme and cp_apply_fi_scalar for OF 02.00 sub-row tests.

    Contains F-IRB and A-IRB exposures with SME and FSE flags to test
    the per-sub-class breakdown (rows 0295-0297, 0355-0356, 0382-0385,
    0400/0410).
    """
    return pl.LazyFrame(
        {
            "exposure_reference": [
                "FIRB_CORP_FSE_1",
                "FIRB_CORP_SME_1",
                "FIRB_CORP_OTHER_1",
                "AIRB_CORP_SME_1",
                "AIRB_CORP_OTHER_1",
                "AIRB_MORT_RES_SME_1",
                "AIRB_MORT_RES_1",
                "AIRB_MORT_COM_SME_1",
                "AIRB_MORT_COM_1",
                "AIRB_QRRE_1",
                "AIRB_OTHER_SME_1",
                "AIRB_OTHER_1",
            ],
            "approach_applied": [
                "foundation_irb",
                "foundation_irb",
                "foundation_irb",
                "advanced_irb",
                "advanced_irb",
                "advanced_irb",
                "advanced_irb",
                "advanced_irb",
                "advanced_irb",
                "advanced_irb",
                "advanced_irb",
                "advanced_irb",
            ],
            "exposure_class": [
                "corporate",
                "corporate",
                "corporate",
                "corporate",
                "corporate",
                "retail_mortgage",
                "retail_mortgage",
                "retail_mortgage",
                "retail_mortgage",
                "retail_qrre",
                "retail_other",
                "retail_other",
            ],
            "ead_final": [
                1000.0,
                500.0,
                2000.0,
                800.0,
                1200.0,
                400.0,
                600.0,
                300.0,
                700.0,
                900.0,
                350.0,
                450.0,
            ],
            "rwa_final": [
                800.0,
                300.0,
                1600.0,
                640.0,
                960.0,
                120.0,
                180.0,
                150.0,
                350.0,
                540.0,
                280.0,
                360.0,
            ],
            "is_sme": [
                False,
                True,
                False,
                True,
                False,
                True,
                False,
                True,
                False,
                False,
                True,
                False,
            ],
            "cp_apply_fi_scalar": [
                True,
                False,
                False,
                False,
                False,
                False,
                False,
                False,
                False,
                False,
                False,
                False,
            ],
            "property_type": [
                None,
                None,
                None,
                None,
                None,
                "residential",
                "residential",
                "commercial",
                "commercial",
                None,
                None,
                None,
            ],
            "sa_rwa": [
                700.0,
                350.0,
                1400.0,
                560.0,
                840.0,
                100.0,
                150.0,
                120.0,
                280.0,
                450.0,
                245.0,
                315.0,
            ],
            "rwa_pre_floor": [
                800.0,
                300.0,
                1600.0,
                640.0,
                960.0,
                120.0,
                180.0,
                150.0,
                350.0,
                540.0,
                280.0,
                360.0,
            ],
            "counterparty_reference": [
                "CP1",
                "CP2",
                "CP3",
                "CP4",
                "CP5",
                "CP6",
                "CP7",
                "CP8",
                "CP9",
                "CP10",
                "CP11",
                "CP12",
            ],
        }
    )


class TestC0200CurrencyMismatchMemoRow:
    """P1.94g DELIV2: OF 02.00 memo row 0500 for retail/RE currency mismatch RWEA.

    Why: Basel 3.1 requires a memo row in OF 02.00 (Own Funds Requirements)
    reporting the total RWEA for retail and RE exposures subject to the 1.5×
    Art. 123B currency mismatch multiplier. Row 0500 is B31-only, memo-only
    (col 0010 populated; cols 0020/0030 None).

    Expected values from _sa_results_with_currency_mismatch():
        SA_RET_1:  currency_mismatch_multiplier_applied=True,  rwa_final=112.5
        SA_RET_2:  currency_mismatch_multiplier_applied=False, rwa_final=150.0
        SA_MORT_1: currency_mismatch_multiplier_applied=True,  rwa_final=375.0
        SA_CORP_1: currency_mismatch_multiplier_applied=False, rwa_final=3000.0

    Memo row 0500 = sum rwa_final where mismatch=True = 112.5 + 375.0 = 487.5

    Total (row 0010) = sum all rwa_final = 112.5 + 150.0 + 375.0 + 3000.0 = 3637.5
    The memo row must NOT change the total.

    Pre-fix failure: row_ref "0500" does not exist in OF 02.00 → empty filter
    → IndexError or assertion on length.
    """

    def test_p1_94g_of_0200_row_0500_exists_b31(self) -> None:
        """Row 0500 must appear in B31 OF 02.00.

        Arrange: SA results with mismatch flag and risk_weight_pre_currency_mismatch.
        Act:     COREPGenerator.generate_from_lazyframe(..., framework='BASEL_3_1').
        Assert:  bundle.c_02_00 filtered to row_ref=='0500' has exactly 1 row.

        Pre-fix failure: row 0500 not defined in B31_C02_00_ROW_SECTIONS → 0 rows.
        """
        # Arrange
        gen = LedgerShimCorepGenerator()

        # Act
        bundle = gen.generate_from_lazyframe(
            _sa_results_with_currency_mismatch(), framework="BASEL_3_1"
        )
        assert bundle.c_02_00 is not None

        # Assert
        row = bundle.c_02_00.filter(pl.col("row_ref") == "0500")
        assert len(row) == 1, (
            f"Expected OF 02.00 row 0500 to exist in B31 framework, "
            f"but got {len(row)} rows. Row 0500 is not yet defined in "
            f"B31_C02_00_ROW_SECTIONS (engine-implementer must add it)."
        )

    def test_p1_94g_of_0200_row_0500_rwea_col_0010(self) -> None:
        """Row 0500 col 0010 equals total RWEA of mismatch exposures (112.5 + 375.0 = 487.5).

        Arrange/Act: as above.
        Assert: row_0500["0010"] == pytest.approx(487.5).

        Pre-fix failure: row does not exist (IndexError or empty frame).
        """
        # Arrange
        gen = LedgerShimCorepGenerator()

        # Act
        bundle = gen.generate_from_lazyframe(
            _sa_results_with_currency_mismatch(), framework="BASEL_3_1"
        )
        assert bundle.c_02_00 is not None

        row = bundle.c_02_00.filter(pl.col("row_ref") == "0500")
        assert len(row) == 1, "Row 0500 absent — generator has not been updated yet"

        # SA_RET_1 (rwa=112.5, mismatch=True) + SA_MORT_1 (rwa=375.0, mismatch=True)
        expected_memo_rwa = 112.5 + 375.0  # = 487.5
        assert row["0010"][0] == pytest.approx(expected_memo_rwa), (
            f"OF 02.00 row 0500 col 0010 should be {expected_memo_rwa} "
            f"(sum rwa_final where currency_mismatch_multiplier_applied), "
            f"got {row['0010'][0]}."
        )

    def test_p1_94g_of_0200_row_0500_cols_0020_0030_none(self) -> None:
        """Row 0500 is memo-only: cols 0020 and 0030 must be None (B31-only SA memo).

        Arrange/Act: as above.
        Assert: row_0500["0020"] is None and row_0500["0030"] is None.

        Pre-fix failure: row does not exist.
        """
        # Arrange
        gen = LedgerShimCorepGenerator()

        # Act
        bundle = gen.generate_from_lazyframe(
            _sa_results_with_currency_mismatch(), framework="BASEL_3_1"
        )
        assert bundle.c_02_00 is not None

        row = bundle.c_02_00.filter(pl.col("row_ref") == "0500")
        assert len(row) == 1, "Row 0500 absent — generator has not been updated yet"

        # Memo-only: SA-equivalent (0020) and floor-adjusted (0030) must both be None
        assert row["0020"][0] is None, (
            f"OF 02.00 row 0500 col 0020 should be None (memo-only), got {row['0020'][0]}"
        )
        assert row["0030"][0] is None, (
            f"OF 02.00 row 0500 col 0030 should be None (memo-only), got {row['0030'][0]}"
        )

    def test_p1_94g_of_0200_total_row_unchanged_by_memo(self) -> None:
        """Adding row 0500 must NOT change the TREA total (row 0010).

        The memo row is purely informational — it must not inflate total RWEA.
        Total = 112.5 + 150.0 + 375.0 + 3000.0 = 3637.5.

        Arrange/Act: as above.
        Assert: row_0010["0010"] == pytest.approx(3637.5).

        Pre-fix: the total row already works; this confirms memo-row addition
        is non-destructive. This assertion passes pre-fix ONLY IF the total
        already computes correctly — include it to guard against regressions.
        """
        # Arrange
        gen = LedgerShimCorepGenerator()

        # Act
        bundle = gen.generate_from_lazyframe(
            _sa_results_with_currency_mismatch(), framework="BASEL_3_1"
        )
        assert bundle.c_02_00 is not None

        total_row = bundle.c_02_00.filter(pl.col("row_ref") == "0010")
        assert len(total_row) == 1

        # TREA = sum of all rwa_final (SA_RET_1 + SA_RET_2 + SA_MORT_1 + SA_CORP_1)
        expected_total = 112.5 + 150.0 + 375.0 + 3000.0  # = 3637.5
        assert total_row["0010"][0] == pytest.approx(expected_total), (
            f"OF 02.00 total TREA (row 0010) should be {expected_total}, "
            f"got {total_row['0010'][0]}. "
            f"The memo row 0500 must not be included in the total."
        )

    def test_p1_94g_of_0200_row_0500_absent_under_crr(self) -> None:
        """Row 0500 is B31-only — must not appear under CRR framework.

        Arrange/Act: same fixture, framework='CRR'.
        Assert: c_02_00 filtered to row_ref=='0500' has 0 rows.

        Pre-fix: this assertion already passes (row doesn't exist at all);
        it ensures row 0500 is not accidentally added to CRR too.
        """
        # Arrange
        gen = LedgerShimCorepGenerator()

        # Act
        bundle = gen.generate_from_lazyframe(_sa_results_with_currency_mismatch(), framework="CRR")
        assert bundle.c_02_00 is not None

        row = bundle.c_02_00.filter(pl.col("row_ref") == "0500")
        assert len(row) == 0, (
            f"OF 02.00 row 0500 must not appear under CRR (B31-only), but got {len(row)} rows."
        )


class TestC0200TemplateDefinitions:
    """Template structure definitions for C 02.00 / OF 02.00."""

    def test_crr_column_count(self) -> None:
        """CRR C 02.00 has 1 column."""
        assert len(CRR_C02_00_COLUMNS) == 1

    def test_b31_column_count(self) -> None:
        """Basel 3.1 OF 02.00 has 3 columns."""
        assert len(B31_C02_00_COLUMNS) == 3

    def test_crr_column_refs(self) -> None:
        """CRR column ref is 0010."""
        assert CRR_C02_00_COLUMN_REFS == ["0010"]

    def test_b31_column_refs(self) -> None:
        """Basel 3.1 column refs are 0010, 0020, 0030."""
        assert B31_C02_00_COLUMN_REFS == ["0010", "0020", "0030"]

    def test_crr_section_count(self) -> None:
        """CRR has 3 sections."""
        assert len(CRR_C02_00_ROW_SECTIONS) == 3

    def test_b31_section_count(self) -> None:
        """Basel 3.1 has 7 sections (SA, F-IRB, A-IRB, slotting, other, plus Memorandum Items added in P1.94g for the Art. 123B currency-mismatch RWEA memo row 0500)."""
        assert len(B31_C02_00_ROW_SECTIONS) == 7

    def test_crr_total_row_exists(self) -> None:
        """CRR has a TOTAL RISK EXPOSURE AMOUNT row."""
        all_rows = [r for s in CRR_C02_00_ROW_SECTIONS for r in s.rows]
        refs = [r.ref for r in all_rows]
        assert "0010" in refs

    def test_b31_floor_indicator_rows(self) -> None:
        """Basel 3.1 has output floor indicator rows 0034, 0035, 0036."""
        all_rows = [r for s in B31_C02_00_ROW_SECTIONS for r in s.rows]
        refs = [r.ref for r in all_rows]
        assert "0034" in refs
        assert "0035" in refs
        assert "0036" in refs

    def test_b31_slotting_rows(self) -> None:
        """Basel 3.1 has per-SL-type slotting rows 0412-0416."""
        all_rows = [r for s in B31_C02_00_ROW_SECTIONS for r in s.rows]
        refs = [r.ref for r in all_rows]
        for ref in ["0411", "0412", "0413", "0414", "0415", "0416"]:
            assert ref in refs, f"Missing slotting row {ref}"

    def test_b31_firb_breakdown_rows(self) -> None:
        """Basel 3.1 has F-IRB sub-class rows 0271, 0290, 0295-0297."""
        all_rows = [r for s in B31_C02_00_ROW_SECTIONS for r in s.rows]
        refs = [r.ref for r in all_rows]
        for ref in ["0271", "0290", "0295", "0296", "0297"]:
            assert ref in refs, f"Missing F-IRB row {ref}"

    def test_b31_airb_retail_rows(self) -> None:
        """Basel 3.1 has A-IRB retail sub-rows 0382-0385."""
        all_rows = [r for s in B31_C02_00_ROW_SECTIONS for r in s.rows]
        refs = [r.ref for r in all_rows]
        for ref in ["0382", "0383", "0384", "0385"]:
            assert ref in refs, f"Missing A-IRB retail row {ref}"

    def test_sa_class_map_covers_major_classes(self) -> None:
        """SA class map has entries for major exposure classes."""
        for cls in ["corporate", "institution", "retail", "central_government", "equity"]:
            assert cls in C02_00_SA_CLASS_MAP, f"Missing SA class mapping for {cls}"

    def test_get_columns_selector(self) -> None:
        """get_c02_00_columns returns framework-appropriate columns."""
        assert get_c02_00_columns("CRR") == CRR_C02_00_COLUMNS
        assert get_c02_00_columns("BASEL_3_1") == B31_C02_00_COLUMNS

    def test_get_row_sections_selector(self) -> None:
        """get_c02_00_row_sections returns framework-appropriate rows."""
        assert get_c02_00_row_sections("CRR") == CRR_C02_00_ROW_SECTIONS
        assert get_c02_00_row_sections("BASEL_3_1") == B31_C02_00_ROW_SECTIONS

    def test_b31_sa_specialised_lending_row(self) -> None:
        """Basel 3.1 has SA specialised lending row 0131."""
        all_rows = [r for s in B31_C02_00_ROW_SECTIONS for r in s.rows]
        refs = [r.ref for r in all_rows]
        assert "0131" in refs


class TestC0200Generation:
    """C 02.00 / OF 02.00 generation from pipeline results."""

    def test_generated_under_crr(self) -> None:
        """C 02.00 is generated under CRR."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_c02_sa_results(), framework="CRR")
        assert bundle.c_02_00 is not None

    def test_generated_under_b31(self) -> None:
        """OF 02.00 is generated under Basel 3.1."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_c02_sa_results(), framework="BASEL_3_1")
        assert bundle.c_02_00 is not None

    def test_is_dataframe(self) -> None:
        """Result is a polars DataFrame."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_c02_sa_results(), framework="CRR")
        assert isinstance(bundle.c_02_00, pl.DataFrame)

    def test_crr_has_one_data_column(self) -> None:
        """CRR C 02.00 has row_ref, row_name, and 1 data column (0010)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_c02_sa_results(), framework="CRR")
        df = bundle.c_02_00
        assert df is not None
        assert "row_ref" in df.columns
        assert "row_name" in df.columns
        assert "0010" in df.columns
        # Only 1 data column + 2 metadata columns
        assert len(df.columns) == 3

    def test_b31_has_three_data_columns(self) -> None:
        """Basel 3.1 OF 02.00 has row_ref, row_name, and 3 data columns."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_c02_sa_results(), framework="BASEL_3_1")
        df = bundle.c_02_00
        assert df is not None
        assert "0010" in df.columns
        assert "0020" in df.columns
        assert "0030" in df.columns
        assert len(df.columns) == 5

    def test_missing_rwa_column_returns_none(self) -> None:
        """Returns None when RWA column is missing."""
        gen = LedgerShimCorepGenerator()
        results = pl.LazyFrame({"exposure_reference": ["E1"], "ead_final": [1000.0]})
        bundle = gen.generate_from_lazyframe(results, framework="CRR")
        assert bundle.c_02_00 is None

    def test_error_logged_when_skipped(self) -> None:
        """Error logged when C 02.00 is skipped."""
        gen = LedgerShimCorepGenerator()
        results = pl.LazyFrame({"exposure_reference": ["E1"]})
        bundle = gen.generate_from_lazyframe(results, framework="CRR")
        assert any("C 02.00 skipped" in e for e in bundle.errors)

    def test_bundle_field_none_by_default(self) -> None:
        """c_02_00 field defaults to None."""
        bundle = COREPTemplateBundle(c07_00={}, c08_01={}, c08_02={})
        assert bundle.c_02_00 is None


class TestC0200TotalRow:
    """TOTAL RISK EXPOSURE AMOUNT row (0010) tests."""

    def test_sa_only_total(self) -> None:
        """Total RWEA = sum of all SA RWA."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_c02_sa_results(), framework="CRR")
        df = bundle.c_02_00
        assert df is not None
        row = df.filter(pl.col("row_ref") == "0010")
        # S1=1000, S2=100, S3=225, S4=0 → 1325
        assert row["0010"][0] == pytest.approx(1325.0)

    def test_mixed_total(self) -> None:
        """Total RWEA = SA + IRB + slotting."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_c02_mixed_results(), framework="CRR")
        df = bundle.c_02_00
        assert df is not None
        row = df.filter(pl.col("row_ref") == "0010")
        # S1=1000, S2=100, I1=1000, I2=240, SL1=420 → 2760
        assert row["0010"][0] == pytest.approx(2760.0)

    def test_own_funds_requirement(self) -> None:
        """Own funds requirement (row 0040) = 8% × TREA."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_c02_sa_results(), framework="CRR")
        df = bundle.c_02_00
        assert df is not None
        trea = df.filter(pl.col("row_ref") == "0010")["0010"][0]
        own_funds = df.filter(pl.col("row_ref") == "0040")["0010"][0]
        assert own_funds == pytest.approx(trea * 0.08)

    def test_b31_total_row_three_columns(self) -> None:
        """B31 total row has all 3 columns populated."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_c02_b31_results_with_floor(), framework="BASEL_3_1")
        df = bundle.c_02_00
        assert df is not None
        row = df.filter(pl.col("row_ref") == "0010")
        assert row["0010"][0] is not None
        assert row["0020"][0] is not None
        assert row["0030"][0] is not None

    def test_b31_total_rwa_matches(self) -> None:
        """B31 col 0010 total = sum of all rwa_final."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_c02_b31_results_with_floor(), framework="BASEL_3_1")
        df = bundle.c_02_00
        assert df is not None
        row = df.filter(pl.col("row_ref") == "0010")
        # S1=1000, I1=1000, I2=240, SL1=420 → 2660
        assert row["0010"][0] == pytest.approx(2660.0)


class TestC0200SABreakdown:
    """SA exposure class breakdown rows."""

    def test_sa_total(self) -> None:
        """SA total (row 0060) = sum of SA approach RWA."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_c02_sa_results(), framework="CRR")
        df = bundle.c_02_00
        assert df is not None
        row = df.filter(pl.col("row_ref") == "0060")
        # All SA: 1000+100+225+0 = 1325
        assert row["0010"][0] == pytest.approx(1325.0)

    def test_sa_corporate_row(self) -> None:
        """Corporate RWA in SA class row 0130."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_c02_sa_results(), framework="CRR")
        df = bundle.c_02_00
        assert df is not None
        row = df.filter(pl.col("row_ref") == "0130")
        assert row["0010"][0] == pytest.approx(1000.0)

    def test_sa_institution_row(self) -> None:
        """Institution RWA in SA class row 0120."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_c02_sa_results(), framework="CRR")
        df = bundle.c_02_00
        assert df is not None
        row = df.filter(pl.col("row_ref") == "0120")
        assert row["0010"][0] == pytest.approx(100.0)

    def test_sa_retail_row(self) -> None:
        """Retail RWA in SA class row 0140."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_c02_sa_results(), framework="CRR")
        df = bundle.c_02_00
        assert df is not None
        row = df.filter(pl.col("row_ref") == "0140")
        assert row["0010"][0] == pytest.approx(225.0)

    def test_sa_sovereign_row(self) -> None:
        """Sovereign RWA in SA class row 0070."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_c02_sa_results(), framework="CRR")
        df = bundle.c_02_00
        assert df is not None
        row = df.filter(pl.col("row_ref") == "0070")
        assert row["0010"][0] == pytest.approx(0.0)

    def test_mixed_sa_only_in_sa_rows(self) -> None:
        """With mixed data, only SA approach goes to SA rows."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_c02_mixed_results(), framework="CRR")
        df = bundle.c_02_00
        assert df is not None
        sa_total = df.filter(pl.col("row_ref") == "0060")
        # SA exposures only: S1=1000, S2=100 → 1100
        assert sa_total["0010"][0] == pytest.approx(1100.0)


class TestC0200IRBBreakdown:
    """IRB approach breakdown rows."""

    def test_irb_total(self) -> None:
        """IRB total (row 0220) = F-IRB + A-IRB + slotting."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_c02_mixed_results(), framework="CRR")
        df = bundle.c_02_00
        assert df is not None
        row = df.filter(pl.col("row_ref") == "0220")
        # I1=1000 (FIRB) + I2=240 (AIRB) + SL1=420 (slotting) = 1660
        assert row["0010"][0] == pytest.approx(1660.0)

    def test_firb_total(self) -> None:
        """F-IRB total (row 0240) = F-IRB RWA."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_c02_mixed_results(), framework="CRR")
        df = bundle.c_02_00
        assert df is not None
        row = df.filter(pl.col("row_ref") == "0240")
        assert row["0010"][0] == pytest.approx(1000.0)

    def test_airb_total(self) -> None:
        """A-IRB total (row 0300) = A-IRB RWA."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_c02_mixed_results(), framework="CRR")
        df = bundle.c_02_00
        assert df is not None
        row = df.filter(pl.col("row_ref") == "0300")
        assert row["0010"][0] == pytest.approx(240.0)

    def test_airb_retail_mortgage(self) -> None:
        """A-IRB retail mortgage RWA in row 0380."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_c02_mixed_results(), framework="CRR")
        df = bundle.c_02_00
        assert df is not None
        row = df.filter(pl.col("row_ref") == "0380")
        assert row["0010"][0] == pytest.approx(240.0)

    def test_slotting_total(self) -> None:
        """Slotting total in CRR row 0410."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_c02_mixed_results(), framework="CRR")
        df = bundle.c_02_00
        assert df is not None
        row = df.filter(pl.col("row_ref") == "0410")
        assert row["0010"][0] == pytest.approx(420.0)

    def test_b31_slotting_by_type(self) -> None:
        """Basel 3.1 breaks slotting into per-SL-type rows."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_c02_b31_results_with_floor(), framework="BASEL_3_1")
        df = bundle.c_02_00
        assert df is not None
        # SL1 is project_finance → row 0412
        sl_total = df.filter(pl.col("row_ref") == "0411")
        pf_row = df.filter(pl.col("row_ref") == "0412")
        assert sl_total["0010"][0] == pytest.approx(420.0)
        assert pf_row["0010"][0] == pytest.approx(420.0)

    def test_credit_risk_equals_total(self) -> None:
        """Credit risk row (0050) = total (0010) since only CR in scope."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_c02_mixed_results(), framework="CRR")
        df = bundle.c_02_00
        assert df is not None
        total = df.filter(pl.col("row_ref") == "0010")["0010"][0]
        cr = df.filter(pl.col("row_ref") == "0050")["0010"][0]
        assert cr == pytest.approx(total)

    def test_sa_plus_irb_equals_credit_risk(self) -> None:
        """SA total + IRB total = credit risk total."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_c02_mixed_results(), framework="CRR")
        df = bundle.c_02_00
        assert df is not None
        cr = df.filter(pl.col("row_ref") == "0050")["0010"][0]
        sa = df.filter(pl.col("row_ref") == "0060")["0010"][0]
        irb = df.filter(pl.col("row_ref") == "0220")["0010"][0]
        assert sa + irb == pytest.approx(cr)


class TestC0200B31Features:
    """Basel 3.1 specific features: 3 columns, floor rows, sub-breakdowns."""

    def test_sa_equivalent_column(self) -> None:
        """Col 0020 (SA-equivalent) is populated from sa_rwa."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_c02_b31_results_with_floor(), framework="BASEL_3_1")
        df = bundle.c_02_00
        assert df is not None
        row = df.filter(pl.col("row_ref") == "0010")
        # sa_rwa: 1000+1500+400+500 = 3400
        assert row["0020"][0] == pytest.approx(3400.0)

    def test_floor_indicator_row(self) -> None:
        """Row 0034 indicates whether floor is activated."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_c02_b31_results_with_floor(), framework="BASEL_3_1")
        df = bundle.c_02_00
        assert df is not None
        row = df.filter(pl.col("row_ref") == "0034")
        assert len(row) == 1
        # Floor not binding in this dataset (rwa_final == rwa_pre_floor)
        assert row["0010"][0] == pytest.approx(0.0)

    def test_floor_binding_indicator(self) -> None:
        """Row 0034 = 1 when floor is binding."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_c02_b31_floor_binding(), framework="BASEL_3_1")
        df = bundle.c_02_00
        assert df is not None
        row = df.filter(pl.col("row_ref") == "0034")
        assert row["0010"][0] == pytest.approx(1.0)

    def test_b31_firb_institution_row(self) -> None:
        """B31 has F-IRB institution detail row 0271."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_c02_b31_results_with_floor(), framework="BASEL_3_1")
        df = bundle.c_02_00
        assert df is not None
        row = df.filter(pl.col("row_ref") == "0271")
        assert len(row) == 1  # Row exists

    def test_b31_sa_specialised_lending_row(self) -> None:
        """B31 SA SL sub-row 0131 populated when SL under SA."""
        gen = LedgerShimCorepGenerator()
        # SL under SA → goes to corporate row 0130 and SL sub-row 0131
        results = pl.LazyFrame(
            {
                "exposure_reference": ["SL1"],
                "approach_applied": ["standardised"],
                "exposure_class": ["specialised_lending"],
                "ead_final": [500.0],
                "risk_weight": [1.0],
                "rwa_final": [500.0],
            }
        )
        bundle = gen.generate_from_lazyframe(results, framework="BASEL_3_1")
        df = bundle.c_02_00
        assert df is not None
        row = df.filter(pl.col("row_ref") == "0131")
        assert row["0010"][0] == pytest.approx(500.0)


class TestC0200NullRows:
    """Non-credit-risk rows should be null (out of scope)."""

    @pytest.mark.parametrize(
        "row_ref,row_name",
        [
            ("0430", "Settlement risk"),
            ("0440", "Securitisation positions in non-trading book"),
            ("0460", "Position, foreign exchange and commodities risk"),
            ("0590", "Credit valuation adjustment (CVA)"),
            ("0640", "Operational risk"),
            ("0680", "Additional risk exposure: fixed overheads"),
        ],
    )
    def test_out_of_scope_row_is_null(self, row_ref: str, row_name: str) -> None:
        """Non-credit-risk rows have null values."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_c02_sa_results(), framework="CRR")
        df = bundle.c_02_00
        assert df is not None
        row = df.filter(pl.col("row_ref") == row_ref)
        assert len(row) == 1
        assert row["row_name"][0] == row_name
        assert row["0010"][0] is None


class TestC0200EdgeCases:
    """Edge cases for C 02.00 generation."""

    def test_empty_results(self) -> None:
        """Empty results produce zero totals."""
        gen = LedgerShimCorepGenerator()
        results = pl.LazyFrame(
            schema={
                "exposure_reference": pl.String,
                "approach_applied": pl.String,
                "exposure_class": pl.String,
                "ead_final": pl.Float64,
                "rwa_final": pl.Float64,
            }
        )
        bundle = gen.generate_from_lazyframe(results, framework="CRR")
        df = bundle.c_02_00
        assert df is not None
        total = df.filter(pl.col("row_ref") == "0010")
        assert total["0010"][0] == pytest.approx(0.0)

    def test_data_columns_are_float64(self) -> None:
        """Data columns are Float64."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_c02_sa_results(), framework="CRR")
        df = bundle.c_02_00
        assert df is not None
        assert df["0010"].dtype == pl.Float64

    def test_row_ref_is_string(self) -> None:
        """Row ref column is String."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_c02_sa_results(), framework="CRR")
        df = bundle.c_02_00
        assert df is not None
        assert df["row_ref"].dtype == pl.String

    def test_row_order_preserved(self) -> None:
        """Rows appear in the order defined by row sections."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_c02_sa_results(), framework="CRR")
        df = bundle.c_02_00
        assert df is not None
        refs = df["row_ref"].to_list()
        expected = [r.ref for s in CRR_C02_00_ROW_SECTIONS for r in s.rows]
        assert refs == expected

    def test_b31_row_order_preserved(self) -> None:
        """Basel 3.1 rows appear in the order defined by row sections."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_c02_b31_results_with_floor(), framework="BASEL_3_1")
        df = bundle.c_02_00
        assert df is not None
        refs = df["row_ref"].to_list()
        expected = [r.ref for s in B31_C02_00_ROW_SECTIONS for r in s.rows]
        assert refs == expected

    def test_null_rwa_treated_as_zero(self) -> None:
        """Null RWA values treated as zero in aggregation."""
        gen = LedgerShimCorepGenerator()
        results = pl.LazyFrame(
            {
                "exposure_reference": ["E1", "E2"],
                "approach_applied": ["standardised", "standardised"],
                "exposure_class": ["corporate", "corporate"],
                "ead_final": [1000.0, 500.0],
                "rwa_final": [1000.0, None],
            }
        )
        bundle = gen.generate_from_lazyframe(results, framework="CRR")
        df = bundle.c_02_00
        assert df is not None
        total = df.filter(pl.col("row_ref") == "0010")
        assert total["0010"][0] == pytest.approx(1000.0)


class TestOF0200IRBSubRowSplits:
    """Tests for OF 02.00 IRB sub-row population using is_sme and cp_apply_fi_scalar.

    Why: The master capital template (OF 02.00) must report F-IRB and A-IRB
    RWEA with proper sub-class breakdown: financial/large corporates vs SME vs
    other general corporates (rows 0295-0297, 0355-0356), and retail RE by
    property type and SME status (rows 0382-0385, 0400/0410). Previously these
    rows showed placeholder zeros.
    """

    def test_firb_fse_row_0295(self) -> None:
        """Row 0295: F-IRB financial/large corporates."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_sme_fse(), framework="BASEL_3_1")
        assert bundle.c_02_00 is not None
        row = bundle.c_02_00.filter(pl.col("row_ref") == "0295")
        assert len(row) == 1
        # FIRB_CORP_FSE_1: rwa = 800
        assert row["0010"][0] == pytest.approx(800.0)

    def test_firb_sme_row_0296(self) -> None:
        """Row 0296: F-IRB other general corporates SME."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_sme_fse(), framework="BASEL_3_1")
        assert bundle.c_02_00 is not None
        row = bundle.c_02_00.filter(pl.col("row_ref") == "0296")
        assert len(row) == 1
        # FIRB_CORP_SME_1: rwa = 300
        assert row["0010"][0] == pytest.approx(300.0)

    def test_firb_nonsme_row_0297(self) -> None:
        """Row 0297: F-IRB other general corporates non-SME."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_sme_fse(), framework="BASEL_3_1")
        assert bundle.c_02_00 is not None
        row = bundle.c_02_00.filter(pl.col("row_ref") == "0297")
        assert len(row) == 1
        # FIRB_CORP_OTHER_1: rwa = 1600
        assert row["0010"][0] == pytest.approx(1600.0)

    def test_firb_corp_sub_rows_sum_to_total(self) -> None:
        """Rows 0295+0296+0297 should sum to total F-IRB corporates (row 0260)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_sme_fse(), framework="BASEL_3_1")
        assert bundle.c_02_00 is not None
        df = bundle.c_02_00
        r0260 = float(df.filter(pl.col("row_ref") == "0260")["0010"][0])
        r0290 = float(df.filter(pl.col("row_ref") == "0290")["0010"][0])
        r0295 = float(df.filter(pl.col("row_ref") == "0295")["0010"][0])
        r0296 = float(df.filter(pl.col("row_ref") == "0296")["0010"][0])
        r0297 = float(df.filter(pl.col("row_ref") == "0297")["0010"][0])
        # 0260 = SL (0290) + FSE (0295) + SME (0296) + non-SME (0297)
        assert r0260 == pytest.approx(r0290 + r0295 + r0296 + r0297)

    def test_airb_sme_row_0355(self) -> None:
        """Row 0355: A-IRB other general corporates SME."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_sme_fse(), framework="BASEL_3_1")
        assert bundle.c_02_00 is not None
        row = bundle.c_02_00.filter(pl.col("row_ref") == "0355")
        assert len(row) == 1
        # AIRB_CORP_SME_1: rwa = 640
        assert row["0010"][0] == pytest.approx(640.0)

    def test_airb_nonsme_row_0356(self) -> None:
        """Row 0356: A-IRB other general corporates non-SME (incl. FSE)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_sme_fse(), framework="BASEL_3_1")
        assert bundle.c_02_00 is not None
        row = bundle.c_02_00.filter(pl.col("row_ref") == "0356")
        assert len(row) == 1
        # AIRB_CORP_OTHER_1: rwa = 960
        assert row["0010"][0] == pytest.approx(960.0)

    def test_airb_resi_sme_row_0382(self) -> None:
        """Row 0382: A-IRB retail residential RE SME."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_sme_fse(), framework="BASEL_3_1")
        assert bundle.c_02_00 is not None
        row = bundle.c_02_00.filter(pl.col("row_ref") == "0382")
        assert len(row) == 1
        # AIRB_MORT_RES_SME_1: rwa = 120
        assert row["0010"][0] == pytest.approx(120.0)

    def test_airb_resi_nonsme_row_0383(self) -> None:
        """Row 0383: A-IRB retail residential RE non-SME."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_sme_fse(), framework="BASEL_3_1")
        assert bundle.c_02_00 is not None
        row = bundle.c_02_00.filter(pl.col("row_ref") == "0383")
        assert len(row) == 1
        # AIRB_MORT_RES_1: rwa = 180
        assert row["0010"][0] == pytest.approx(180.0)

    def test_airb_comm_sme_row_0384(self) -> None:
        """Row 0384: A-IRB retail commercial RE SME."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_sme_fse(), framework="BASEL_3_1")
        assert bundle.c_02_00 is not None
        row = bundle.c_02_00.filter(pl.col("row_ref") == "0384")
        assert len(row) == 1
        # AIRB_MORT_COM_SME_1: rwa = 150
        assert row["0010"][0] == pytest.approx(150.0)

    def test_airb_comm_nonsme_row_0385(self) -> None:
        """Row 0385: A-IRB retail commercial RE non-SME."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_sme_fse(), framework="BASEL_3_1")
        assert bundle.c_02_00 is not None
        row = bundle.c_02_00.filter(pl.col("row_ref") == "0385")
        assert len(row) == 1
        # AIRB_MORT_COM_1: rwa = 350
        assert row["0010"][0] == pytest.approx(350.0)

    def test_airb_retail_re_sub_rows_sum_to_total(self) -> None:
        """Rows 0382+0383+0384+0385 sum to total A-IRB retail RE (row 0380)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_sme_fse(), framework="BASEL_3_1")
        assert bundle.c_02_00 is not None
        df = bundle.c_02_00
        r0380 = float(df.filter(pl.col("row_ref") == "0380")["0010"][0])
        r0382 = float(df.filter(pl.col("row_ref") == "0382")["0010"][0])
        r0383 = float(df.filter(pl.col("row_ref") == "0383")["0010"][0])
        r0384 = float(df.filter(pl.col("row_ref") == "0384")["0010"][0])
        r0385 = float(df.filter(pl.col("row_ref") == "0385")["0010"][0])
        assert r0380 == pytest.approx(r0382 + r0383 + r0384 + r0385)

    def test_airb_other_sme_row_0400(self) -> None:
        """Row 0400: A-IRB retail other SME."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_sme_fse(), framework="BASEL_3_1")
        assert bundle.c_02_00 is not None
        row = bundle.c_02_00.filter(pl.col("row_ref") == "0400")
        assert len(row) == 1
        # AIRB_OTHER_SME_1: rwa = 280
        assert row["0010"][0] == pytest.approx(280.0)

    def test_airb_other_nonsme_row_0410(self) -> None:
        """Row 0410: A-IRB retail other non-SME."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_sme_fse(), framework="BASEL_3_1")
        assert bundle.c_02_00 is not None
        row = bundle.c_02_00.filter(pl.col("row_ref") == "0410")
        assert len(row) == 1
        # AIRB_OTHER_1: rwa = 360
        assert row["0010"][0] == pytest.approx(360.0)

    def test_no_sub_rows_in_crr(self) -> None:
        """CRR does not have sub-rows 0295-0297, 0355-0356, 0382-0385."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_sme_fse(), framework="CRR")
        assert bundle.c_02_00 is not None
        df = bundle.c_02_00
        b31_only_rows = ["0295", "0296", "0297", "0355", "0356", "0382", "0383", "0384", "0385"]
        for ref in b31_only_rows:
            assert len(df.filter(pl.col("row_ref") == ref)) == 0

    def test_fallback_without_sme_flag(self) -> None:
        """Without is_sme column, non-FSE corporate RWA goes to non-SME row."""
        data = _irb_results_with_sme_fse().drop("is_sme")
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(data, framework="BASEL_3_1")
        assert bundle.c_02_00 is not None
        df = bundle.c_02_00
        # FSE exposure (800) still goes to 0295; rest (300+1600=1900) to 0297
        r0295 = float(df.filter(pl.col("row_ref") == "0295")["0010"][0])
        assert r0295 == pytest.approx(800.0)
        r0297 = float(df.filter(pl.col("row_ref") == "0297")["0010"][0])
        assert r0297 == pytest.approx(1900.0)
        r0296 = float(df.filter(pl.col("row_ref") == "0296")["0010"][0])
        assert r0296 == pytest.approx(0.0)


def _c02_crr_equity_irb_results() -> pl.LazyFrame:
    """CRR results with an Art. 155(2) IRB-simple equity leg.

    One SA corporate, one F-IRB corporate, and one equity leg tagged
    ``irb_simple`` (1,000 EAD x 290% = 2,900 RWA). The equity leg must report
    at row 0420 and the IRB total (0220), never the SA rows (0060/0210).
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["S1", "I1", "EQ1"],
            "approach_applied": ["standardised", "foundation_irb", "equity"],
            "exposure_class": ["corporate", "corporate", "equity"],
            "equity_method": [None, None, "irb_simple"],
            "ead_final": [1000.0, 2000.0, 1000.0],
            "risk_weight": [1.0, 0.5, 2.9],
            "rwa_final": [1000.0, 1000.0, 2900.0],
        }
    )


def _c02_crr_equity_sa_results() -> pl.LazyFrame:
    """CRR results with an Art. 133 SA-method equity leg (SA-only firm).

    Same shape as the IRB-simple fixture but the equity leg is tagged ``sa`` —
    it must report in the SA breakdown (0060/0210), and row 0420 empties.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["S1", "I1", "EQ1"],
            "approach_applied": ["standardised", "foundation_irb", "equity"],
            "exposure_class": ["corporate", "corporate", "equity"],
            "equity_method": [None, None, "sa"],
            "ead_final": [1000.0, 2000.0, 1000.0],
            "risk_weight": [1.0, 0.5, 2.5],
            "rwa_final": [1000.0, 1000.0, 2500.0],
        }
    )


def _c02_b31_equity_results() -> pl.LazyFrame:
    """Basel 3.1 results with an equity leg — always SA-method (Art. 147A).

    Under B31 the equity calculator stamps ``sa`` for every leg (IRB equity is
    removed), so row 0420 must empty and the book stays in the SA rows.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["S1", "I1", "EQ1"],
            "approach_applied": ["standardised", "foundation_irb", "equity"],
            "exposure_class": ["corporate", "corporate", "equity"],
            "equity_method": [None, None, "sa"],
            "ead_final": [1000.0, 2000.0, 1000.0],
            "risk_weight": [1.0, 0.5, 2.5],
            "rwa_final": [1000.0, 1000.0, 2500.0],
            "rwa_pre_floor": [1000.0, 1000.0, 2500.0],
            "sa_rwa": [1000.0, 1500.0, 2500.0],
        }
    )


class TestC0200EquityMethodRouting:
    """R8: C 02.00 row 0420 "Equity IRB" holds only Art. 155 IRB-method equity.

    Why: Under Basel 3.1 (PS1/26 Art. 147A) IRB equity is removed — every equity
    leg is SA, so row 0420 must be empty and the book stays in the SA breakdown.
    Under CRR, only equity actually treated under Art. 155 (irb_simple/pd_lgd)
    belongs in 0420; SA-treated equity belongs in the SA rows. The fix routes by
    the sealed ``equity_method`` discriminator and must never change the totals
    (rows 0010/0040/0050) — it moves RWA between breakdown rows only.
    """

    def _row(self, df: pl.DataFrame, ref: str) -> float:
        return float(df.filter(pl.col("row_ref") == ref)["0010"][0])

    def test_b31_equity_irb_row_empty(self) -> None:
        """B31: row 0420 "Equity IRB" is zero (Art. 147A — no IRB equity)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_c02_b31_equity_results(), framework="BASEL_3_1")
        assert bundle.c_02_00 is not None
        assert self._row(bundle.c_02_00, "0420") == pytest.approx(0.0)

    def test_b31_equity_stays_in_sa_rows(self) -> None:
        """B31: the equity book (2,500) reports in SA total (0060) and class (0210)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_c02_b31_equity_results(), framework="BASEL_3_1")
        assert bundle.c_02_00 is not None
        df = bundle.c_02_00
        # SA total = corporate SA (1000) + equity SA (2500) = 3500
        assert self._row(df, "0060") == pytest.approx(3500.0)
        # SA equity class row keeps the book
        assert self._row(df, "0210") == pytest.approx(2500.0)

    def test_b31_totals_unchanged_and_footing_holds(self) -> None:
        """B31: totals count equity once and 0060 + 0220 == 0050."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_c02_b31_equity_results(), framework="BASEL_3_1")
        assert bundle.c_02_00 is not None
        df = bundle.c_02_00
        # Total = 1000 + 1000 + 2500 = 4500 (equity once)
        assert self._row(df, "0010") == pytest.approx(4500.0)
        assert self._row(df, "0050") == pytest.approx(4500.0)
        assert self._row(df, "0040") == pytest.approx(4500.0 * 0.08)
        # Footing: SA total + IRB total = credit risk total
        assert self._row(df, "0060") + self._row(df, "0220") == pytest.approx(self._row(df, "0050"))

    def test_crr_irb_equity_in_row_0420(self) -> None:
        """CRR irb_simple: row 0420 holds the equity book (2,900)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_c02_crr_equity_irb_results(), framework="CRR")
        assert bundle.c_02_00 is not None
        assert self._row(bundle.c_02_00, "0420") == pytest.approx(2900.0)

    def test_crr_irb_equity_not_in_sa_rows(self) -> None:
        """CRR irb_simple: SA total (0060) and class row (0210) exclude the equity."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_c02_crr_equity_irb_results(), framework="CRR")
        assert bundle.c_02_00 is not None
        df = bundle.c_02_00
        # SA total = corporate SA only (1000); equity is IRB, not SA
        assert self._row(df, "0060") == pytest.approx(1000.0)
        # SA equity class row empties (equity is IRB)
        assert self._row(df, "0210") == pytest.approx(0.0)

    def test_crr_irb_equity_folds_into_irb_total(self) -> None:
        """CRR irb_simple: IRB total (0220) includes the equity, footing holds."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_c02_crr_equity_irb_results(), framework="CRR")
        assert bundle.c_02_00 is not None
        df = bundle.c_02_00
        # IRB total = F-IRB (1000) + IRB equity (2900) = 3900
        assert self._row(df, "0220") == pytest.approx(3900.0)
        # Totals unchanged; footing holds
        assert self._row(df, "0010") == pytest.approx(4900.0)
        assert self._row(df, "0060") + self._row(df, "0220") == pytest.approx(self._row(df, "0050"))

    def test_crr_sa_equity_in_sa_rows_only(self) -> None:
        """CRR sa-method equity: reports in SA rows only, row 0420 empties."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_c02_crr_equity_sa_results(), framework="CRR")
        assert bundle.c_02_00 is not None
        df = bundle.c_02_00
        # SA total = corporate SA (1000) + equity SA (2500) = 3500
        assert self._row(df, "0060") == pytest.approx(3500.0)
        assert self._row(df, "0210") == pytest.approx(2500.0)
        # IRB total = F-IRB only (1000); row 0420 empty
        assert self._row(df, "0220") == pytest.approx(1000.0)
        assert self._row(df, "0420") == pytest.approx(0.0)
        # Footing holds
        assert self._row(df, "0060") + self._row(df, "0220") == pytest.approx(self._row(df, "0050"))

    def test_equity_free_run_row_0420_empty(self) -> None:
        """Equity-free run (no equity_method column): 0420 zero-fills, no crash."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_c02_mixed_results(), framework="CRR")
        assert bundle.c_02_00 is not None
        assert self._row(bundle.c_02_00, "0420") == pytest.approx(0.0)


class TestOF0200FloorIndicatorRows:
    """Tests for OF 02.00 output floor indicator rows 0034-0036.

    Why: These rows tell regulators whether the output floor is active
    (row 0034), what multiplier % applies (row 0035), and the OF-ADJ
    monetary value (row 0036). Previously rows 0035/0036 were always zero.
    """

    def test_floor_multiplier_from_summary(self) -> None:
        """Row 0035 shows floor_pct * 100 from OutputFloorSummary."""
        summary = OutputFloorSummary(
            u_trea=1000.0,
            s_trea=800.0,
            floor_pct=0.725,
            floor_threshold=580.0,
            shortfall=0.0,
            portfolio_floor_binding=False,
            # P2.20: modelled-only post-floor scope (IRB-only summary fixture).
            floored_modelled_rwa=1000.0,
            of_adj=50.0,
        )
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_results_with_sme_fse(),
            framework="BASEL_3_1",
            output_floor_summary=summary,
        )
        assert bundle.c_02_00 is not None
        row = bundle.c_02_00.filter(pl.col("row_ref") == "0035")
        assert len(row) == 1
        # 72.5% → 72.5
        assert row["0010"][0] == pytest.approx(72.5)

    def test_of_adj_from_summary(self) -> None:
        """Row 0036 shows of_adj monetary value from OutputFloorSummary."""
        summary = OutputFloorSummary(
            u_trea=1000.0,
            s_trea=800.0,
            floor_pct=0.725,
            floor_threshold=580.0,
            shortfall=0.0,
            portfolio_floor_binding=False,
            # P2.20: modelled-only post-floor scope (IRB-only summary fixture).
            floored_modelled_rwa=1000.0,
            of_adj=123.45,
        )
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_results_with_sme_fse(),
            framework="BASEL_3_1",
            output_floor_summary=summary,
        )
        assert bundle.c_02_00 is not None
        row = bundle.c_02_00.filter(pl.col("row_ref") == "0036")
        assert len(row) == 1
        assert row["0010"][0] == pytest.approx(123.45)

    def test_floor_rows_zero_without_summary(self) -> None:
        """Rows 0035/0036 are zero when no OutputFloorSummary is provided."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_sme_fse(), framework="BASEL_3_1")
        assert bundle.c_02_00 is not None
        r0035 = bundle.c_02_00.filter(pl.col("row_ref") == "0035")
        r0036 = bundle.c_02_00.filter(pl.col("row_ref") == "0036")
        assert r0035["0010"][0] == pytest.approx(0.0)
        assert r0036["0010"][0] == pytest.approx(0.0)

    def test_floor_rows_absent_crr(self) -> None:
        """CRR does not have floor indicator rows 0034-0036."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_sme_fse(), framework="CRR")
        assert bundle.c_02_00 is not None
        df = bundle.c_02_00
        for ref in ("0034", "0035", "0036"):
            assert len(df.filter(pl.col("row_ref") == ref)) == 0
