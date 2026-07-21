"""COREP C 08.01 / OF 08.01 generation tests.

Split from tests/unit/test_corep.py (Phase 7 Sn) — bodies verbatim.
"""

from __future__ import annotations

import polars as pl
import pytest

from tests.fixtures.recon_ledger import LedgerShimCorepGenerator
from tests.unit.reporting.corep._builders import (
    _combined_results,
    _get_total_row,
    _irb_results,
    _irb_results_with_phase2_cols,
)


def _irb_results_with_output_floor() -> pl.LazyFrame:
    """IRB results with output floor columns for Phase 2D testing."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["IRB_CORP_1", "IRB_CORP_2", "IRB_INST_1"],
            "approach_applied": [
                "foundation_irb",
                "foundation_irb",
                "foundation_irb",
            ],
            "exposure_class": ["corporate", "corporate", "institution"],
            "drawn_amount": [5000.0, 3000.0, 2000.0],
            "undrawn_amount": [1000.0, 0.0, 0.0],
            "ead_final": [5500.0, 3000.0, 2000.0],
            "rwa_final": [3850.0, 1800.0, 600.0],
            "risk_weight": [0.70, 0.60, 0.30],
            "pd_floored": [0.005, 0.01, 0.002],
            "lgd_floored": [0.45, 0.45, 0.45],
            "irb_maturity_m": [2.5, 3.0, 1.5],
            "expected_loss": [12.375, 13.5, 1.8],
            "irb_capital_k": [0.056, 0.048, 0.024],
            "provision_held": [15.0, 10.0, 3.0],
            "scra_provision_amount": [10.0, 5.0, 2.0],
            "gcra_provision_amount": [5.0, 5.0, 1.0],
            "counterparty_reference": ["CP_X", "CP_Y", "CP_W"],
            "sa_rwa": [5500.0, 3000.0, 400.0],
        }
    )


def _irb_results_with_pma() -> pl.LazyFrame:
    """IRB results with post-model adjustment columns for C 08.01 testing.

    Why: Basel 3.1 requires reporting of IRB RWEA waterfall including
    pre-adjustment RWEA, general PMAs, mortgage RW floor, and unrecognised
    exposure adjustments. This fixture simulates pipeline output after the
    IRB calculator has applied post-model adjustments.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["IRB_CORP_1", "IRB_CORP_2", "IRB_MTG_1"],
            "approach_applied": ["foundation_irb", "foundation_irb", "advanced_irb"],
            "exposure_class": ["corporate", "corporate", "retail_mortgage"],
            "drawn_amount": [5000.0, 3000.0, 4000.0],
            "undrawn_amount": [1000.0, 0.0, 0.0],
            "ead_final": [5500.0, 3000.0, 4000.0],
            "rwa_final": [4050.0, 1920.0, 1400.0],
            "risk_weight": [0.70, 0.60, 0.30],
            "pd_floored": [0.005, 0.01, 0.003],
            "lgd_floored": [0.45, 0.45, 0.15],
            "irb_maturity_m": [2.5, 3.0, 20.0],
            "expected_loss": [12.375, 13.5, 1.8],
            "irb_capital_k": [0.056, 0.048, 0.024],
            "scra_provision_amount": [10.0, 5.0, 1.0],
            "gcra_provision_amount": [5.0, 5.0, 1.5],
            "counterparty_reference": ["CP_X", "CP_Y", "CP_V"],
            # Post-model adjustment columns (from IRB calculator)
            "rwa_pre_adjustments": [3850.0, 1800.0, 1200.0],
            "post_model_adjustment_rwa": [192.5, 90.0, 60.0],
            "mortgage_rw_floor_adjustment": [0.0, 0.0, 100.0],
            "unrecognised_exposure_adjustment": [7.7, 30.0, 40.0],
            # EL adjustments
            "el_pre_adjustment": [12.375, 13.5, 1.8],
            "post_model_adjustment_el": [0.62, 0.675, 0.09],
            "el_after_adjustment": [12.995, 14.175, 1.89],
        }
    )


def _irb_results_with_double_default() -> pl.LazyFrame:
    """IRB results with double default tracking columns for C 08.01 col 0220.

    Why: CRR Art. 153(3) requires reporting of unfunded credit protection
    subject to double default treatment. Col 0220 shows the guaranteed amount
    where the DD formula was used instead of standard substitution.

    Two corporate exposures:
    - IRB_DD_1: DD-eligible (guaranteed by institution, A-IRB, has DD protection)
    - IRB_DD_2: Not DD-eligible (no guarantee)
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["IRB_DD_1", "IRB_DD_2"],
            "approach_applied": ["advanced_irb", "advanced_irb"],
            "exposure_class": ["corporate", "corporate"],
            "drawn_amount": [5000.0, 3000.0],
            "undrawn_amount": [1000.0, 0.0],
            "ead_final": [5500.0, 3000.0],
            "rwa_final": [2750.0, 1800.0],
            "risk_weight": [0.50, 0.60],
            "pd_floored": [0.02, 0.01],
            "lgd_floored": [0.45, 0.45],
            "irb_maturity_m": [2.5, 3.0],
            "expected_loss": [49.5, 13.5],
            "irb_capital_k": [0.04, 0.048],
            "provision_held": [50.0, 10.0],
            "el_shortfall": [0.0, 3.5],
            "el_excess": [0.5, 0.0],
            "scra_provision_amount": [10.0, 5.0],
            "gcra_provision_amount": [5.0, 5.0],
            "counterparty_reference": ["CP_DD1", "CP_DD2"],
            # Double default tracking columns
            "is_double_default_eligible": [True, False],
            "double_default_unfunded_protection": [3000.0, 0.0],
            "irb_lgd_double_default": [0.45, None],
            "guaranteed_portion": [3000.0, 0.0],
            "unguaranteed_portion": [2500.0, 3000.0],
        }
    )


def _irb_results_with_slotting() -> pl.LazyFrame:
    """Synthetic IRB results with both PD/LGD model and slotting approaches.

    Corporate class: 2 F-IRB + 1 slotting = 3 rows
    - F-IRB corp: EAD 5500 + 3000 = 8500, RWA 3850 + 1800 = 5650
    - Slotting corp: EAD 2000, RWA 1600

    Institution class: 1 F-IRB row
    - F-IRB inst: EAD 2000, RWA 600

    Specialised lending class: 1 slotting row
    - Slotting SL: EAD 4000, RWA 2800
    """
    return pl.LazyFrame(
        {
            "exposure_reference": [
                "IRB_CORP_1",
                "IRB_CORP_2",
                "IRB_CORP_SLOT",
                "IRB_INST_1",
                "IRB_SL_1",
            ],
            "approach_applied": [
                "foundation_irb",
                "foundation_irb",
                "slotting",
                "foundation_irb",
                "slotting",
            ],
            "exposure_class": [
                "corporate",
                "corporate",
                "corporate",
                "institution",
                "specialised_lending",
            ],
            "drawn_amount": [5000.0, 3000.0, 2000.0, 2000.0, 4000.0],
            "undrawn_amount": [1000.0, 0.0, 0.0, 0.0, 0.0],
            "ead_final": [5500.0, 3000.0, 2000.0, 2000.0, 4000.0],
            "rwa_final": [3850.0, 1800.0, 1600.0, 600.0, 2800.0],
            "risk_weight": [0.70, 0.60, 0.80, 0.30, 0.70],
            "pd_floored": [0.005, 0.01, None, 0.002, None],
            "lgd_floored": [0.45, 0.45, None, 0.45, None],
            "irb_maturity_m": [2.5, 3.0, None, 1.5, None],
            "expected_loss": [12.375, 13.5, 0.0, 1.8, 0.0],
            "irb_capital_k": [0.056, 0.048, None, 0.024, None],
            "provision_held": [15.0, 10.0, 5.0, 3.0, 8.0],
            "el_shortfall": [0.0, 3.5, 0.0, 0.0, 0.0],
            "el_excess": [2.625, 0.0, 0.0, 1.2, 0.0],
            "scra_provision_amount": [10.0, 5.0, 3.0, 2.0, 5.0],
            "gcra_provision_amount": [5.0, 5.0, 2.0, 1.0, 3.0],
            "counterparty_reference": ["CP_X", "CP_Y", "CP_Z", "CP_W", "CP_V"],
        }
    )


def _irb_results_b31_unrated_corporates() -> pl.LazyFrame:
    """Synthetic B31 IRB results for testing unrated corporates (rows 0190/0200).

    Corporate class: 4 rows — 2 rated (sa_cqs present), 2 unrated (sa_cqs null)
    Of the 2 unrated: 1 investment grade, 1 non-investment grade
    """
    return pl.LazyFrame(
        {
            "exposure_reference": [
                "IRB_CORP_RATED_1",
                "IRB_CORP_RATED_2",
                "IRB_CORP_UNRATED_IG",
                "IRB_CORP_UNRATED_NIG",
            ],
            "approach_applied": [
                "foundation_irb",
                "foundation_irb",
                "foundation_irb",
                "foundation_irb",
            ],
            "exposure_class": [
                "corporate",
                "corporate",
                "corporate",
                "corporate",
            ],
            "drawn_amount": [5000.0, 3000.0, 2000.0, 1000.0],
            "undrawn_amount": [0.0, 0.0, 0.0, 0.0],
            "ead_final": [5000.0, 3000.0, 2000.0, 1000.0],
            "rwa_final": [3500.0, 2100.0, 1000.0, 800.0],
            "risk_weight": [0.70, 0.70, 0.50, 0.80],
            "pd_floored": [0.005, 0.01, 0.003, 0.02],
            "lgd_floored": [0.45, 0.45, 0.45, 0.45],
            "irb_maturity_m": [2.5, 2.5, 2.5, 2.5],
            "expected_loss": [11.25, 13.5, 2.7, 9.0],
            "irb_capital_k": [0.056, 0.056, 0.04, 0.064],
            "provision_held": [15.0, 10.0, 5.0, 8.0],
            "el_shortfall": [0.0, 0.0, 0.0, 0.0],
            "el_excess": [3.75, 0.0, 2.3, 0.0],
            "scra_provision_amount": [10.0, 5.0, 3.0, 4.0],
            "gcra_provision_amount": [5.0, 5.0, 2.0, 4.0],
            "counterparty_reference": ["CP_A", "CP_B", "CP_C", "CP_D"],
            "sa_cqs": [2, 3, None, None],
            "cp_is_investment_grade": [None, None, True, False],
        }
    )


def _get_section3_row(df: pl.DataFrame, row_ref: str) -> pl.DataFrame:
    """Get a Section 3 row by row_ref from a per-class DataFrame."""
    return df.filter(pl.col("row_ref") == row_ref)


class TestC0801:
    """Tests for C 08.01 IRB totals template generation."""

    def test_c0801_produces_per_class_output(self) -> None:
        """C 08.01 produces a dict keyed by IRB exposure class."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        assert isinstance(bundle.c08_01, dict)
        assert "corporate" in bundle.c08_01
        assert "corporate_sme" in bundle.c08_01
        assert "institution" in bundle.c08_01
        assert "retail_mortgage" in bundle.c08_01

    def test_c0801_each_class_has_row_sections(self) -> None:
        """Each per-class DataFrame has rows from all 3 IRB sections."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        corp = bundle.c08_01["corporate"]
        row_refs = corp["row_ref"].to_list()

        # Section 1: Total
        assert "0010" in row_refs
        # Section 2: Exposure types
        assert "0020" in row_refs  # On-BS
        # Section 3: Calculation approaches
        assert "0070" in row_refs  # Grades/pools

    def test_c0801_uses_4_digit_column_refs(self) -> None:
        """DataFrame uses 4-digit COREP column refs."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        corp = bundle.c08_01["corporate"]
        cols = set(corp.columns)

        assert "0010" in cols  # PD
        assert "0020" in cols  # Original exposure
        assert "0110" in cols  # Exposure value (EAD)
        assert "0230" in cols  # LGD
        assert "0250" in cols  # Maturity (days)
        assert "0260" in cols  # RWEA

    def test_c0801_total_ead(self) -> None:
        """Total EAD (col 0110) sums correctly."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        corp = _get_total_row(bundle.c08_01["corporate"])
        # Corp EAD: 5500 + 3000 = 8500
        assert corp["0110"][0] == pytest.approx(8500.0)

    def test_c0801_total_rwea(self) -> None:
        """Total RWEA (col 0260) sums correctly."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        corp = _get_total_row(bundle.c08_01["corporate"])
        # Corp RWA: 3850 + 1800 = 5650
        assert corp["0260"][0] == pytest.approx(5650.0)

    def test_c0801_weighted_average_pd(self) -> None:
        """Exposure-weighted average PD (col 0010) is correct."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        corp = _get_total_row(bundle.c08_01["corporate"])
        # PD: (0.005*5500 + 0.01*3000) / 8500 = 57.5 / 8500
        expected_pd = (0.005 * 5500 + 0.01 * 3000) / (5500 + 3000)
        assert corp["0010"][0] == pytest.approx(expected_pd, rel=1e-6)

    def test_c0801_weighted_average_lgd(self) -> None:
        """Exposure-weighted average LGD (col 0230) is correct."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        corp = _get_total_row(bundle.c08_01["corporate"])
        # Both corporates have LGD=0.45, so weighted average = 0.45
        assert corp["0230"][0] == pytest.approx(0.45)

    def test_c0801_maturity_in_days(self) -> None:
        """Maturity (col 0250) is in DAYS, not years.

        Why: COREP col 0250 requires maturity in days. The pipeline
        stores irb_maturity_m in years. The generator must multiply by 365.
        """
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        corp = _get_total_row(bundle.c08_01["corporate"])
        # Weighted maturity in years: (2.5*5500 + 3.0*3000) / 8500 = 2.6765
        # In days: 2.6765 * 365 = 976.9
        expected_m_years = (2.5 * 5500 + 3.0 * 3000) / (5500 + 3000)
        expected_m_days = expected_m_years * 365.0
        assert corp["0250"][0] == pytest.approx(expected_m_days, rel=1e-4)

    def test_c0801_expected_loss(self) -> None:
        """Expected loss (col 0280) sums correctly."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        corp = _get_total_row(bundle.c08_01["corporate"])
        # EL: 12.375 + 13.5 = 25.875
        assert corp["0280"][0] == pytest.approx(25.875)

    def test_c0801_provisions(self) -> None:
        """Provisions (col 0290) sums correctly — emitted negative per Annex II §1.3."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        corp = _get_total_row(bundle.c08_01["corporate"])
        # Provisions: (10+5) + (5+5) = 25; stored as negative deduction
        assert corp["0290"][0] == pytest.approx(-25.0)

    def test_c0801_obligor_count(self) -> None:
        """Obligor count (col 0300) uses distinct counterparty refs."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        corp = _get_total_row(bundle.c08_01["corporate"])
        # 2 distinct counterparties: CP_X, CP_Y
        assert corp["0300"][0] == pytest.approx(2.0)

    def test_c0801_no_sa_in_irb_output(self) -> None:
        """C 08.01 dict must not include SA-only exposure classes."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_combined_results())

        # central_govt_central_bank is SA-only in test data
        assert "central_govt_central_bank" not in bundle.c08_01

    def test_c0801_empty_results(self) -> None:
        """C 08.01 handles empty results gracefully."""
        gen = LedgerShimCorepGenerator()
        empty = pl.LazyFrame(
            schema={
                "approach_applied": pl.String,
                "exposure_class": pl.String,
                "ead_final": pl.Float64,
                "rwa_final": pl.Float64,
            }
        )
        bundle = gen.generate_from_lazyframe(empty)
        assert bundle.c08_01 == {}


class TestOutputFloor:
    """Tests for Basel 3.1 output floor columns 0275/0276."""

    def test_b31_output_floor_columns_present(self) -> None:
        """Cols 0275/0276 present in Basel 3.1 C 08.01 output."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_results_with_output_floor(), framework="BASEL_3_1"
        )

        corp = _get_total_row(bundle.c08_01["corporate"])
        assert "0275" in corp.columns
        assert "0276" in corp.columns

    def test_b31_output_floor_exposure_value(self) -> None:
        """Col 0275 (SA-equiv exposure) = sum of EAD for the class."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_results_with_output_floor(), framework="BASEL_3_1"
        )

        corp = _get_total_row(bundle.c08_01["corporate"])
        # Corporate: EAD 5500+3000=8500
        assert corp["0275"][0] == pytest.approx(8500.0)

    def test_b31_output_floor_sa_rwa(self) -> None:
        """Col 0276 (SA-equiv RWEA) = sum of sa_equivalent_rwa."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_results_with_output_floor(), framework="BASEL_3_1"
        )

        corp = _get_total_row(bundle.c08_01["corporate"])
        # Corporate: sa_equivalent_rwa 5500+3000=8500
        assert corp["0276"][0] == pytest.approx(8500.0)

    def test_crr_output_floor_columns_absent(self) -> None:
        """Cols 0275/0276 are not in CRR C 08.01 output."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_output_floor(), framework="CRR")

        corp = _get_total_row(bundle.c08_01["corporate"])
        assert "0275" not in corp.columns
        assert "0276" not in corp.columns

    def test_b31_output_floor_null_without_sa_rwa(self) -> None:
        """Col 0276 is null when sa_equivalent_rwa not in data."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results(), framework="BASEL_3_1")

        corp = _get_total_row(bundle.c08_01["corporate"])
        assert corp["0276"][0] is None


class TestLFSESubColumns:
    """Tests for C 08.01 large financial sector entity sub-columns."""

    def test_c0801_lfse_original_exposure(self) -> None:
        """Col 0030 (LFSE original exposure) populated from cp_apply_fi_scalar."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_phase2_cols())

        # Institution has cp_apply_fi_scalar=True: drawn=2000, undrawn=0
        inst = _get_total_row(bundle.c08_01["institution"])
        assert inst["0030"][0] == pytest.approx(2000.0)

    def test_c0801_lfse_ead(self) -> None:
        """Col 0140 (LFSE EAD) populated from cp_apply_fi_scalar."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_phase2_cols())

        inst = _get_total_row(bundle.c08_01["institution"])
        # Institution: ead_final=2000, cp_apply_fi_scalar=True
        assert inst["0140"][0] == pytest.approx(2000.0)

    def test_c0801_lfse_lgd(self) -> None:
        """Col 0240 (LFSE LGD) = EAD-weighted avg LGD for LFSE exposures."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_phase2_cols())

        inst = _get_total_row(bundle.c08_01["institution"])
        # Institution LFSE: single exposure with LGD=0.45
        assert inst["0240"][0] == pytest.approx(0.45)

    def test_c0801_lfse_rwea(self) -> None:
        """Col 0270 (LFSE RWEA) populated from cp_apply_fi_scalar."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_phase2_cols())

        inst = _get_total_row(bundle.c08_01["institution"])
        # Institution: rwa_final=600, cp_apply_fi_scalar=True
        assert inst["0270"][0] == pytest.approx(600.0)

    def test_c0801_lfse_zero_when_no_lfse_in_class(self) -> None:
        """LFSE cols are 0.0 when no exposures have cp_apply_fi_scalar=True."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_phase2_cols())

        # Corporate has no LFSE exposures (all cp_apply_fi_scalar=False)
        corp = _get_total_row(bundle.c08_01["corporate"])
        assert corp["0030"][0] == pytest.approx(0.0)
        assert corp["0140"][0] == pytest.approx(0.0)
        assert corp["0270"][0] == pytest.approx(0.0)

    def test_c0801_lfse_null_without_column(self) -> None:
        """LFSE cols are null when cp_apply_fi_scalar not in data."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())  # no cp_apply_fi_scalar

        corp = _get_total_row(bundle.c08_01["corporate"])
        assert corp["0030"][0] is None
        assert corp["0140"][0] is None
        assert corp["0270"][0] is None


class TestPostModelAdjustments:
    """Task 3F: Post-model adjustments (Basel 3.1 OF 08.01 cols 0251-0254, 0280-0282).

    Why: PRA PS9/24 Art. 153(5A), 154(4A), 158(6A) require firms to report
    the RWEA waterfall showing the impact of post-model adjustments on IRB
    results. These columns enable supervisors to assess whether PMAs are
    adequate and whether modelled risk weights adequately capture risk.
    """

    def test_b31_col_0251_rwa_pre_adjustments(self) -> None:
        """Col 0251: RWEA pre adjustments equals sum of rwa_pre_adjustments."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_pma(), framework="BASEL_3_1")
        corp = bundle.c08_01["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        assert total["0251"][0] == pytest.approx(3850.0 + 1800.0)

    def test_b31_col_0252_general_pma(self) -> None:
        """Col 0252: General PMA equals sum of post_model_adjustment_rwa."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_pma(), framework="BASEL_3_1")
        corp = bundle.c08_01["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        assert total["0252"][0] == pytest.approx(192.5 + 90.0)

    def test_b31_col_0253_mortgage_floor(self) -> None:
        """Col 0253: Mortgage RW floor adjustment for mortgage class."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_pma(), framework="BASEL_3_1")
        mtg = bundle.c08_01.get("retail_mortgage")
        if mtg is not None:
            total = mtg.filter(pl.col("row_ref") == "0010")
            assert total["0253"][0] == pytest.approx(100.0)

    def test_b31_col_0254_unrecognised(self) -> None:
        """Col 0254: Unrecognised exposure adjustment."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_pma(), framework="BASEL_3_1")
        corp = bundle.c08_01["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        assert total["0254"][0] == pytest.approx(7.7 + 30.0)

    def test_b31_col_0280_el_pre_adjustment(self) -> None:
        """Col 0280: EL pre-adjustment equals sum of el_pre_adjustment."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_pma(), framework="BASEL_3_1")
        corp = bundle.c08_01["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        assert total["0280"][0] == pytest.approx(12.375 + 13.5)

    def test_b31_col_0281_el_pma(self) -> None:
        """Col 0281: EL PMA equals sum of post_model_adjustment_el."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_pma(), framework="BASEL_3_1")
        corp = bundle.c08_01["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        assert total["0281"][0] == pytest.approx(0.62 + 0.675)

    def test_b31_col_0282_el_after_adjustment(self) -> None:
        """Col 0282: EL after adjustment equals sum of el_after_adjustment."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_pma(), framework="BASEL_3_1")
        corp = bundle.c08_01["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        assert total["0282"][0] == pytest.approx(12.995 + 14.175)

    def test_crr_no_pma_columns(self) -> None:
        """CRR framework does not have PMA columns 0251-0254."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_pma(), framework="CRR")
        corp = bundle.c08_01["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        assert "0251" not in total.columns
        assert "0252" not in total.columns
        assert "0253" not in total.columns
        assert "0254" not in total.columns

    def test_without_pma_columns_returns_none(self) -> None:
        """Without PMA columns in pipeline data, COREP cols are None."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results(), framework="BASEL_3_1")
        corp = bundle.c08_01.get("corporate")
        if corp is not None:
            total = corp.filter(pl.col("row_ref") == "0010")
            if "0251" in total.columns:
                assert total["0251"][0] is None

    def test_corporate_zero_mortgage_floor(self) -> None:
        """Corporate class should have zero mortgage floor adjustment."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_pma(), framework="BASEL_3_1")
        corp = bundle.c08_01["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        assert total["0253"][0] == pytest.approx(0.0)


class TestDoubleDefaultCOREP:
    """Task 3E: Double default treatment in COREP C 08.01 col 0220.

    Why: CRR Art. 153(3) allows firms with A-IRB permission to recognise
    double default effects, reducing capital for guaranteed corporate exposures
    where the joint default probability is low. Col 0220 reports the unfunded
    protection amount subject to this treatment, enabling supervisory review
    of DD usage and risk concentration.
    """

    def test_crr_col_0220_populated(self) -> None:
        """CRR C 08.01 col 0220 reports DD unfunded protection amount."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_double_default(), framework="CRR")
        corp = bundle.c08_01["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        # IRB_DD_1 has 3000 DD unfunded protection, IRB_DD_2 has 0
        assert total["0220"][0] == pytest.approx(3000.0)

    def test_crr_col_0220_zero_when_no_dd(self) -> None:
        """CRR C 08.01 col 0220 is zero when no DD exposures."""
        gen = LedgerShimCorepGenerator()
        # Use plain IRB results (no DD columns)
        bundle = gen.generate_from_lazyframe(_irb_results(), framework="CRR")
        corp = bundle.c08_01["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        # Without DD column, should be None
        assert total["0220"][0] is None

    def test_b31_no_col_0220(self) -> None:
        """Basel 3.1 OF 08.01 does not have col 0220 (DD removed)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_results_with_double_default(), framework="BASEL_3_1"
        )
        corp = bundle.c08_01["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        assert "0220" not in total.columns

    def test_crr_col_0220_institution_class(self) -> None:
        """Col 0220 for institution class with no DD → None."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_double_default(), framework="CRR")
        inst = bundle.c08_01.get("institution")
        # No institution exposures in fixture → class absent or empty
        if inst is not None:
            total = inst.filter(pl.col("row_ref") == "0010")
            if len(total) > 0:
                # Institution exposures can't have DD (not corporate)
                assert total["0220"][0] is None or total["0220"][0] == pytest.approx(0.0)

    def test_dd_unfunded_included_in_total_guarantees(self) -> None:
        """DD unfunded is a subset of total unfunded protection."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_double_default(), framework="CRR")
        corp = bundle.c08_01["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        dd_amount = total["0220"][0]
        guar_amount = total["0150"][0] if "0150" in total.columns else None
        # DD unfunded should be <= total guarantees (DD is a subset of guarantee treatments)
        if dd_amount is not None and guar_amount is not None:
            assert dd_amount <= guar_amount + 0.01


class TestSection3CalculationApproaches:
    """Tests for C 08.01 Section 3 — Calculation Approaches.

    Section 3 splits the total IRB exposure by calculation method:
    row 0070 (PD/LGD model) vs row 0080 (slotting), with additional
    sub-portfolio rows for free deliveries, purchased receivables,
    unrated corporates, and investment grade corporates.

    Why: Regulators use Section 3 to verify that exposures are correctly
    allocated between calculation approaches (Art. 142-191). An entirely
    null Section 3 masks whether the institution correctly segregates
    model-based and slotting exposures.
    """

    # --- Row 0070: Obligor grades/pools (F-IRB + A-IRB) ---

    def test_row_0070_populated_for_firb_airb(self) -> None:
        """Row 0070 is populated with F-IRB/A-IRB exposures."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_slotting())
        corp = bundle.c08_01["corporate"]
        row = _get_section3_row(corp, "0070")
        assert len(row) == 1
        # F-IRB corporate EAD: 5500 + 3000 = 8500 (excludes slotting 2000)
        assert row["0110"][0] == pytest.approx(8500.0)

    def test_row_0070_ead_excludes_slotting(self) -> None:
        """Row 0070 EAD excludes slotting rows (those go to row 0080)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_slotting())
        corp = bundle.c08_01["corporate"]
        total_ead = _get_total_row(corp)["0110"][0]
        row_0070_ead = _get_section3_row(corp, "0070")["0110"][0]
        row_0080_ead = _get_section3_row(corp, "0080")["0110"][0]
        # 0070 + 0080 should equal total
        assert row_0070_ead + (row_0080_ead or 0.0) == pytest.approx(total_ead)

    def test_row_0070_rwea_correct(self) -> None:
        """Row 0070 RWEA sums F-IRB/A-IRB rows only."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_slotting())
        corp = bundle.c08_01["corporate"]
        row = _get_section3_row(corp, "0070")
        # F-IRB corporate RWA: 3850 + 1800 = 5650 (excludes slotting 1600)
        assert row["0260"][0] == pytest.approx(5650.0)

    def test_row_0070_weighted_average_pd(self) -> None:
        """Row 0070 PD is EAD-weighted average of F-IRB/A-IRB exposures."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_slotting())
        corp = bundle.c08_01["corporate"]
        row = _get_section3_row(corp, "0070")
        # PD: (0.005*5500 + 0.01*3000) / (5500+3000) = 57.5/8500
        expected_pd = (0.005 * 5500 + 0.01 * 3000) / 8500
        assert row["0010"][0] == pytest.approx(expected_pd, rel=1e-6)

    def test_row_0070_obligor_count(self) -> None:
        """Row 0070 obligor count covers F-IRB/A-IRB counterparties only."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_slotting())
        corp = bundle.c08_01["corporate"]
        row = _get_section3_row(corp, "0070")
        # F-IRB corporates have 2 unique counterparties: CP_X, CP_Y
        assert row["0300"][0] == pytest.approx(2.0)

    def test_row_0070_institution_class(self) -> None:
        """Row 0070 works for institution class (all F-IRB, no slotting)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_slotting())
        inst = bundle.c08_01["institution"]
        row = _get_section3_row(inst, "0070")
        assert row["0110"][0] == pytest.approx(2000.0)

    # --- Row 0080: Slotting approach ---

    def test_row_0080_populated_for_slotting(self) -> None:
        """Row 0080 is populated with slotting exposures."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_slotting())
        corp = bundle.c08_01["corporate"]
        row = _get_section3_row(corp, "0080")
        assert len(row) == 1
        # Slotting corporate EAD: 2000
        assert row["0110"][0] == pytest.approx(2000.0)

    def test_row_0080_rwea_correct(self) -> None:
        """Row 0080 RWEA sums slotting rows only."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_slotting())
        corp = bundle.c08_01["corporate"]
        row = _get_section3_row(corp, "0080")
        # Slotting corporate RWA: 1600
        assert row["0260"][0] == pytest.approx(1600.0)

    def test_row_0080_sl_class_all_slotting(self) -> None:
        """Specialised lending class has all EAD in row 0080 (slotting)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_slotting())
        sl = bundle.c08_01["specialised_lending"]
        row_0080 = _get_section3_row(sl, "0080")
        assert row_0080["0110"][0] == pytest.approx(4000.0)
        assert row_0080["0260"][0] == pytest.approx(2800.0)

    def test_row_0080_null_when_no_slotting_in_class(self) -> None:
        """Row 0080 is null when the class has no slotting exposures."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_slotting())
        inst = bundle.c08_01["institution"]
        row = _get_section3_row(inst, "0080")
        assert row["0110"][0] is None

    def test_row_0070_null_when_no_model_based_in_class(self) -> None:
        """Row 0070 is null when the class has only slotting exposures."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_slotting())
        sl = bundle.c08_01["specialised_lending"]
        row_0070 = _get_section3_row(sl, "0070")
        assert row_0070["0110"][0] is None

    # --- Rows 0070 + 0080 additive integrity ---

    def test_section3_ead_adds_to_total(self) -> None:
        """Row 0070 EAD + row 0080 EAD = total row 0010 EAD (within class)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_slotting())
        corp = bundle.c08_01["corporate"]
        total = _get_total_row(corp)["0110"][0]
        r70 = _get_section3_row(corp, "0070")["0110"][0] or 0.0
        r80 = _get_section3_row(corp, "0080")["0110"][0] or 0.0
        assert r70 + r80 == pytest.approx(total)

    def test_section3_rwea_adds_to_total(self) -> None:
        """Row 0070 RWEA + row 0080 RWEA = total row 0010 RWEA (within class)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_slotting())
        corp = bundle.c08_01["corporate"]
        total = _get_total_row(corp)["0260"][0]
        r70 = _get_section3_row(corp, "0070")["0260"][0] or 0.0
        r80 = _get_section3_row(corp, "0080")["0260"][0] or 0.0
        assert r70 + r80 == pytest.approx(total)

    # --- Row 0160: Alternative RE treatment (CRR only) ---

    def test_row_0160_null_no_pipeline_flag(self) -> None:
        """Row 0160 is null — requires pipeline flag not yet available."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_slotting(), framework="CRR")
        corp = bundle.c08_01["corporate"]
        row = _get_section3_row(corp, "0160")
        assert row["0110"][0] is None

    # --- Row 0170: Free deliveries ---

    def test_row_0170_null_no_pipeline_data(self) -> None:
        """Row 0170 is null — free delivery tracking not yet in pipeline."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_slotting(), framework="CRR")
        corp = bundle.c08_01["corporate"]
        row = _get_section3_row(corp, "0170")
        assert row["0110"][0] is None

    # --- Row 0180: Dilution risk ---

    def test_row_0180_null_no_dilution_data(self) -> None:
        """Row 0180 is null — dilution risk tracking not yet in pipeline."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_slotting(), framework="CRR")
        corp = bundle.c08_01["corporate"]
        row = _get_section3_row(corp, "0180")
        assert row["0110"][0] is None

    # --- B31 Row 0190: Corporates without ECAI ---

    def test_row_0190_b31_unrated_corporates(self) -> None:
        """Row 0190 is populated for unrated corporates under Basel 3.1."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_results_b31_unrated_corporates(), framework="BASEL_3_1"
        )
        corp = bundle.c08_01["corporate"]
        row = _get_section3_row(corp, "0190")
        # Unrated corporates: EAD 2000 + 1000 = 3000
        assert row["0110"][0] == pytest.approx(3000.0)

    def test_row_0190_excludes_rated(self) -> None:
        """Row 0190 excludes corporates that have an ECAI rating."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_results_b31_unrated_corporates(), framework="BASEL_3_1"
        )
        corp = bundle.c08_01["corporate"]
        total_ead = _get_total_row(corp)["0110"][0]
        row_0190_ead = _get_section3_row(corp, "0190")["0110"][0]
        # Total 11000, rated 8000, unrated 3000
        assert row_0190_ead < total_ead
        assert row_0190_ead == pytest.approx(3000.0)

    def test_row_0190_not_present_in_crr(self) -> None:
        """Row 0190 does not exist in CRR template (B31 only)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_b31_unrated_corporates(), framework="CRR")
        corp = bundle.c08_01["corporate"]
        row_refs = corp["row_ref"].to_list()
        assert "0190" not in row_refs

    # --- B31 Row 0200: Investment grade ---

    def test_row_0200_b31_investment_grade(self) -> None:
        """Row 0200 is populated for investment grade unrated corporates."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_results_b31_unrated_corporates(), framework="BASEL_3_1"
        )
        corp = bundle.c08_01["corporate"]
        row = _get_section3_row(corp, "0200")
        # Investment grade unrated: EAD 2000 only (the IG flagged one)
        assert row["0110"][0] == pytest.approx(2000.0)

    def test_row_0200_subset_of_0190(self) -> None:
        """Row 0200 EAD is <= row 0190 EAD (investment grade is a subset)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_results_b31_unrated_corporates(), framework="BASEL_3_1"
        )
        corp = bundle.c08_01["corporate"]
        ead_0190 = _get_section3_row(corp, "0190")["0110"][0] or 0.0
        ead_0200 = _get_section3_row(corp, "0200")["0110"][0] or 0.0
        assert ead_0200 <= ead_0190 + 0.01

    def test_row_0200_not_present_in_crr(self) -> None:
        """Row 0200 does not exist in CRR template (B31 only)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_b31_unrated_corporates(), framework="CRR")
        corp = bundle.c08_01["corporate"]
        row_refs = corp["row_ref"].to_list()
        assert "0200" not in row_refs

    # --- Edge cases ---

    def test_section3_with_basic_irb_data(self) -> None:
        """Section 3 works with basic IRB data (no slotting column ambiguity)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())
        corp = bundle.c08_01["corporate"]
        row_0070 = _get_section3_row(corp, "0070")
        # All basic IRB data is F-IRB or A-IRB, so 0070 should match total
        total = _get_total_row(corp)["0110"][0]
        assert row_0070["0110"][0] == pytest.approx(total)

    def test_section3_row_0080_null_when_no_slotting(self) -> None:
        """Row 0080 is null when input has no slotting approach."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())
        corp = bundle.c08_01["corporate"]
        row_0080 = _get_section3_row(corp, "0080")
        assert row_0080["0110"][0] is None

    def test_section3_provisions_column(self) -> None:
        """Row 0070 provisions (col 0290) sums correctly — emitted negative per Annex II §1.3."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_slotting())
        corp = bundle.c08_01["corporate"]
        row = _get_section3_row(corp, "0070")
        # F-IRB provisions: (10+5) + (5+5) = 25; stored as negative deduction
        assert row["0290"][0] == pytest.approx(-25.0)

    def test_b31_section3_has_0175_row(self) -> None:
        """B31 template includes row 0175 (Purchased receivables)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_slotting(), framework="BASEL_3_1")
        corp = bundle.c08_01["corporate"]
        row_refs = corp["row_ref"].to_list()
        assert "0175" in row_refs

    def test_crr_section3_has_0160_row(self) -> None:
        """CRR template includes row 0160 (Alternative RE treatment)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_slotting(), framework="CRR")
        corp = bundle.c08_01["corporate"]
        row_refs = corp["row_ref"].to_list()
        assert "0160" in row_refs


def _irb_results_sme_factor() -> pl.LazyFrame:
    """CRR IRB corporate_sme exposures with the SME supporting factor applied,
    so col 0256 (the "(-)" SME supporting-factor adjustment) fires non-zero.

    Every row on the corporate_sme sheet is SME-applied, so the total-row
    footing 0255 + 0256 == 0260 holds exactly (no unadjusted residual):
        0255 = Σ rwa_pre_factor        = 10000 + 6000 = 16000
        delta = Σ (rwa_pre_factor - rwa_final) = 1500 + 900 = 2400
        0256 = -delta                  = -2400  (Annex II §1.3 "(-)")
        0260 = Σ rwa_final             = 8500 + 5100 = 13600
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["IRB_SME_1", "IRB_SME_2"],
            "approach_applied": ["foundation_irb", "foundation_irb"],
            "exposure_class": ["corporate_sme", "corporate_sme"],
            "drawn_amount": [10000.0, 6000.0],
            "undrawn_amount": [0.0, 0.0],
            "ead_final": [10000.0, 6000.0],
            "rwa_final": [8500.0, 5100.0],
            "rwa_pre_factor": [10000.0, 6000.0],
            "risk_weight": [0.85, 0.85],
            "pd_floored": [0.02, 0.02],
            "lgd_floored": [0.45, 0.45],
            "irb_maturity_m": [2.5, 2.5],
            "expected_loss": [90.0, 54.0],
            "scra_provision_amount": [0.0, 0.0],
            "gcra_provision_amount": [0.0, 0.0],
            "counterparty_reference": ["CP_S1", "CP_S2"],
            "sme_supporting_factor_applied": [True, True],
            "is_sme": [True, True],
        }
    )


def _irb_results_b31_netting() -> pl.LazyFrame:
    """B31 IRB exposures carrying an on-balance-sheet netting amount, so col
    0035 (the "(-)" on-BS netting adjustment, B31-only) fires non-zero."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["IRB_CORP_1", "IRB_CORP_2"],
            "approach_applied": ["foundation_irb", "foundation_irb"],
            "exposure_class": ["corporate", "corporate"],
            "drawn_amount": [5000.0, 3000.0],
            "undrawn_amount": [0.0, 0.0],
            "ead_final": [5000.0, 3000.0],
            "rwa_final": [3500.0, 1800.0],
            "risk_weight": [0.70, 0.60],
            "pd_floored": [0.005, 0.01],
            "lgd_floored": [0.45, 0.45],
            "irb_maturity_m": [2.5, 3.0],
            "expected_loss": [11.25, 13.5],
            "scra_provision_amount": [0.0, 0.0],
            "gcra_provision_amount": [0.0, 0.0],
            "counterparty_reference": ["CP_X", "CP_Y"],
            "on_bs_netting_amount": [500.0, 300.0],
        }
    )


class TestC0801SignConvention:
    """Annex II §1.3 "(-)" sign convention on the C 08.01 surface (item R2)."""

    def test_crr_0256_sme_adjustment_is_negative(self) -> None:
        """CRR col 0256 (SME supporting-factor adjustment) is reported negative."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_sme_factor(), framework="CRR")
        total = _get_total_row(bundle.c08_01["corporate_sme"])
        assert total["0256"][0] == pytest.approx(-2400.0)
        assert total["0256"][0] <= 0.0

    def test_crr_0255_plus_0256_foots_to_0260(self) -> None:
        """0255 + 0256 == 0260 under the "(-)" display convention (0256 signed)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_sme_factor(), framework="CRR")
        total = _get_total_row(bundle.c08_01["corporate_sme"])
        pre = total["0255"][0]
        sme_adj = total["0256"][0]
        post = total["0260"][0]
        assert pre == pytest.approx(16000.0)
        assert post == pytest.approx(13600.0)
        assert pre + sme_adj == pytest.approx(post)

    def test_crr_waterfall_uses_positive_magnitudes(self) -> None:
        """The CRM waterfall (0090) is computed BEFORE the display negation, so a
        substitution outflow does not double-count once its column is flipped.

        SME rows here carry no CRM outflow, so 0090 == 0020 (gross) — the point
        is only that the sign pass runs after the formula, leaving 0090 positive.
        """
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_sme_factor(), framework="CRR")
        total = _get_total_row(bundle.c08_01["corporate_sme"])
        assert total["0090"][0] == pytest.approx(16000.0)

    def test_b31_has_no_supporting_factor_columns(self) -> None:
        """B31 dropped supporting factors, so 0256/0257 are absent (nothing to negate)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_sme_factor(), framework="BASEL_3_1")
        corp_sme = bundle.c08_01["corporate_sme"]
        assert "0256" not in corp_sme.columns
        assert "0257" not in corp_sme.columns

    def test_b31_0035_on_bs_netting_is_negated(self) -> None:
        """B31 col 0035 (on-BS netting adjustment) is reported negative when present."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_b31_netting(), framework="BASEL_3_1")
        total = _get_total_row(bundle.c08_01["corporate"])
        # Σ on_bs_netting_amount = 500 + 300 = 800; emitted as a negative deduction.
        assert total["0035"][0] == pytest.approx(-800.0)
        assert total["0035"][0] <= 0.0
