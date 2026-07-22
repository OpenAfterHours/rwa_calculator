"""COREP C 09.02 / OF 09.02 geographical-breakdown (IRB) tests.

Split from tests/unit/test_corep.py (Phase 7 Sn) — bodies verbatim.
"""

from __future__ import annotations

import polars as pl
import pytest

from tests.fixtures.recon_ledger import LedgerShimCorepGenerator


def _irb_geo_results() -> pl.LazyFrame:
    """Synthetic IRB results with country codes for C 09.02 testing."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["E1", "E2", "E3", "E4", "E5"],
            "approach_applied": [
                "foundation_irb",
                "foundation_irb",
                "advanced_irb",
                "advanced_irb",
                "foundation_irb",
            ],
            "exposure_class": [
                "corporate",
                "corporate",
                "retail_mortgage",
                "retail_qrre",
                "institution",
            ],
            "ead_final": [1000.0, 500.0, 2000.0, 800.0, 1500.0],
            "ead_gross": [1200.0, 600.0, 2200.0, 900.0, 1700.0],
            "rwa_final": [700.0, 350.0, 600.0, 200.0, 300.0],
            "cp_country_code": ["GB", "US", "GB", "GB", "US"],
            "default_status": [False, False, False, False, False],
            "pd_floored": [0.01, 0.02, 0.005, 0.03, 0.008],
            "lgd_post_crm": [0.45, 0.45, 0.20, 0.75, 0.45],
            "expected_loss": [4.5, 4.5, 2.0, 18.0, 5.4],
        }
    )


class TestC0902TemplateDefinitions:
    """Test C 09.02 / OF 09.02 template structure definitions."""

    def test_crr_columns_count(self) -> None:
        from rwa_calc.reporting.corep.templates import CRR_C09_02_COLUMNS

        assert len(CRR_C09_02_COLUMNS) == 17

    def test_b31_columns_count(self) -> None:
        from rwa_calc.reporting.corep.templates import B31_C09_02_COLUMNS

        assert len(B31_C09_02_COLUMNS) == 15

    def test_crr_column_refs(self) -> None:
        from rwa_calc.reporting.corep.templates import C09_02_COLUMN_REFS

        assert C09_02_COLUMN_REFS == [
            "0010",
            "0030",
            "0040",
            "0050",
            "0055",
            "0060",
            "0070",
            "0080",
            "0090",
            "0100",
            "0105",
            "0110",
            "0120",
            "0121",
            "0122",
            "0125",
            "0130",
        ]

    def test_b31_column_refs(self) -> None:
        from rwa_calc.reporting.corep.templates import B31_C09_02_COLUMN_REFS

        assert B31_C09_02_COLUMN_REFS == [
            "0010",
            "0030",
            "0040",
            "0050",
            "0055",
            "0060",
            "0070",
            "0080",
            "0090",
            "0100",
            "0105",
            "0107",
            "0120",
            "0125",
            "0130",
        ]

    def test_b31_adds_col_0107(self) -> None:
        from rwa_calc.reporting.corep.templates import B31_C09_02_COLUMN_REFS

        assert "0107" in B31_C09_02_COLUMN_REFS

    def test_b31_removes_supporting_factor_columns(self) -> None:
        from rwa_calc.reporting.corep.templates import B31_C09_02_COLUMN_REFS

        assert "0110" not in B31_C09_02_COLUMN_REFS
        assert "0121" not in B31_C09_02_COLUMN_REFS
        assert "0122" not in B31_C09_02_COLUMN_REFS

    def test_crr_rows_count(self) -> None:
        from rwa_calc.reporting.corep.templates import CRR_C09_02_ROWS

        assert len(CRR_C09_02_ROWS) == 16

    def test_b31_rows_count(self) -> None:
        from rwa_calc.reporting.corep.templates import B31_C09_02_ROWS

        assert len(B31_C09_02_ROWS) == 19

    def test_crr_has_equity_row(self) -> None:
        from rwa_calc.reporting.corep.templates import CRR_C09_02_ROWS

        refs = [r.ref for r in CRR_C09_02_ROWS]
        assert "0140" in refs

    def test_b31_removes_equity_row(self) -> None:
        from rwa_calc.reporting.corep.templates import B31_C09_02_ROWS

        refs = [r.ref for r in B31_C09_02_ROWS]
        assert "0140" not in refs

    def test_b31_adds_corporate_sub_rows(self) -> None:
        from rwa_calc.reporting.corep.templates import B31_C09_02_ROWS

        refs = [r.ref for r in B31_C09_02_ROWS]
        assert "0048" in refs  # FSE/large corporates
        assert "0049" in refs  # purchased receivables
        assert "0055" in refs  # non-SME

    def test_b31_restructures_retail_re(self) -> None:
        from rwa_calc.reporting.corep.templates import B31_C09_02_ROWS

        refs = [r.ref for r in B31_C09_02_ROWS]
        assert "0071" in refs  # resi RE SME
        assert "0072" in refs  # resi RE non-SME
        assert "0073" in refs  # commercial RE SME
        assert "0074" in refs  # commercial RE non-SME

    def test_crr_selector(self) -> None:
        from rwa_calc.reporting.corep.templates import CRR_C09_02_COLUMNS, get_c09_02_columns

        assert get_c09_02_columns("CRR") is CRR_C09_02_COLUMNS

    def test_b31_selector(self) -> None:
        from rwa_calc.reporting.corep.templates import B31_C09_02_COLUMNS, get_c09_02_columns

        assert get_c09_02_columns("BASEL_3_1") is B31_C09_02_COLUMNS

    def test_total_row_is_last(self) -> None:
        from rwa_calc.reporting.corep.templates import CRR_C09_02_ROWS

        assert CRR_C09_02_ROWS[-1].ref == "0150"

    def test_irb_class_map(self) -> None:
        from rwa_calc.reporting.corep.templates import C09_02_IRB_CLASS_MAP

        assert C09_02_IRB_CLASS_MAP["corporate"] == "corporate"
        assert C09_02_IRB_CLASS_MAP["retail_mortgage"] == "retail"
        assert C09_02_IRB_CLASS_MAP["institution"] == "institution"


class TestC0902Generation:
    """Test C 09.02 / OF 09.02 generation from pipeline data."""

    def test_generates_per_country_dict(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_geo_results(), framework="CRR")
        assert isinstance(bundle.c09_02, dict)
        assert "TOTAL" in bundle.c09_02

    def test_generates_gb_and_us_countries(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_geo_results(), framework="CRR")
        assert "GB" in bundle.c09_02
        assert "US" in bundle.c09_02

    def test_dataframe_has_correct_column_count_crr(self) -> None:
        """17 data columns + row_ref + row_name = 19."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_geo_results(), framework="CRR")
        total = bundle.c09_02["TOTAL"]
        assert len(total.columns) == 19  # 17 data + 2 meta

    def test_dataframe_has_correct_column_count_b31(self) -> None:
        """15 data columns + row_ref + row_name = 17."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_geo_results(), framework="BASEL_3_1")
        total = bundle.c09_02["TOTAL"]
        assert len(total.columns) == 17  # 15 data + 2 meta

    def test_sa_only_returns_empty(self) -> None:
        data = pl.LazyFrame(
            {
                "exposure_reference": ["E1"],
                "approach_applied": ["standardised"],
                "exposure_class": ["corporate"],
                "ead_final": [1000.0],
                "rwa_final": [500.0],
                "cp_country_code": ["GB"],
            }
        )
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(data, framework="CRR")
        assert bundle.c09_02 == {}

    def test_missing_country_code_returns_empty(self) -> None:
        data = pl.LazyFrame(
            {
                "exposure_reference": ["E1"],
                "approach_applied": ["foundation_irb"],
                "exposure_class": ["corporate"],
                "ead_final": [1000.0],
                "rwa_final": [500.0],
                "pd_floored": [0.01],
            }
        )
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(data, framework="CRR")
        assert bundle.c09_02 == {}


class TestC0902ColumnValues:
    """Test C 09.02 column value computation."""

    def test_col_0010_original_exposure(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_geo_results(), framework="CRR")
        total = bundle.c09_02["TOTAL"]
        total_row = total.filter(pl.col("row_ref") == "0150")
        # ead_gross sum: 1200 + 600 + 2200 + 900 + 1700 = 6600
        assert total_row["0010"][0] == pytest.approx(6600.0)

    def test_col_0105_exposure_value(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_geo_results(), framework="CRR")
        total = bundle.c09_02["TOTAL"]
        total_row = total.filter(pl.col("row_ref") == "0150")
        # ead_final sum: 1000 + 500 + 2000 + 800 + 1500 = 5800
        assert total_row["0105"][0] == pytest.approx(5800.0)

    def test_col_0125_rwea(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_geo_results(), framework="CRR")
        total = bundle.c09_02["TOTAL"]
        total_row = total.filter(pl.col("row_ref") == "0150")
        # rwa_final sum: 700 + 350 + 600 + 200 + 300 = 2150
        assert total_row["0125"][0] == pytest.approx(2150.0)

    def test_col_0080_ewa_pd(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_geo_results(), framework="CRR")
        total = bundle.c09_02["TOTAL"]
        total_row = total.filter(pl.col("row_ref") == "0150")
        # EAD-weighted PD: (0.01*1000 + 0.02*500 + 0.005*2000 + 0.03*800 + 0.008*1500) / 5800
        # = (10 + 10 + 10 + 24 + 12) / 5800 = 66 / 5800 ≈ 0.011379
        assert total_row["0080"][0] == pytest.approx(66.0 / 5800.0, rel=1e-3)

    def test_col_0090_ewa_lgd(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_geo_results(), framework="CRR")
        total = bundle.c09_02["TOTAL"]
        total_row = total.filter(pl.col("row_ref") == "0150")
        # EAD-weighted LGD: (0.45*1000 + 0.45*500 + 0.20*2000 + 0.75*800 + 0.45*1500) / 5800
        # = (450 + 225 + 400 + 600 + 675) / 5800 = 2350 / 5800 ≈ 0.40517
        assert total_row["0090"][0] == pytest.approx(2350.0 / 5800.0, rel=1e-3)

    def test_col_0130_expected_loss(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_geo_results(), framework="CRR")
        total = bundle.c09_02["TOTAL"]
        total_row = total.filter(pl.col("row_ref") == "0150")
        # EL sum: 4.5 + 4.5 + 2.0 + 18.0 + 5.4 = 34.4
        assert total_row["0130"][0] == pytest.approx(34.4)

    def test_corporate_row_values(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_geo_results(), framework="CRR")
        total = bundle.c09_02["TOTAL"]
        corp_row = total.filter(pl.col("row_ref") == "0030")
        # Corporate EAD: 1000 + 500 = 1500
        assert corp_row["0105"][0] == pytest.approx(1500.0)

    def test_institution_row_values(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_geo_results(), framework="CRR")
        total = bundle.c09_02["TOTAL"]
        inst_row = total.filter(pl.col("row_ref") == "0020")
        # Institution EAD: 1500
        assert inst_row["0105"][0] == pytest.approx(1500.0)


class TestC0902B31Features:
    """Test Basel 3.1 specific features of OF 09.02."""

    def test_no_supporting_factor_columns(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_geo_results(), framework="BASEL_3_1")
        total = bundle.c09_02["TOTAL"]
        assert "0110" not in total.columns
        assert "0121" not in total.columns
        assert "0122" not in total.columns

    def test_has_col_0107_defaulted_ev(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_geo_results(), framework="BASEL_3_1")
        total = bundle.c09_02["TOTAL"]
        assert "0107" in total.columns

    def test_no_equity_row(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_geo_results(), framework="BASEL_3_1")
        total = bundle.c09_02["TOTAL"]
        refs = total["row_ref"].to_list()
        assert "0140" not in refs


class TestC0902EdgeCases:
    """Test C 09.02 edge cases."""

    def test_total_equals_sum_of_countries(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_geo_results(), framework="CRR")
        total_rwa = bundle.c09_02["TOTAL"].filter(pl.col("row_ref") == "0150")["0125"][0]
        gb_rwa = bundle.c09_02["GB"].filter(pl.col("row_ref") == "0150")["0125"][0]
        us_rwa = bundle.c09_02["US"].filter(pl.col("row_ref") == "0150")["0125"][0]
        assert total_rwa == pytest.approx(gb_rwa + us_rwa)

    def test_single_country_total_matches(self) -> None:
        data = pl.LazyFrame(
            {
                "exposure_reference": ["E1"],
                "approach_applied": ["foundation_irb"],
                "exposure_class": ["corporate"],
                "ead_final": [1000.0],
                "ead_gross": [1200.0],
                "rwa_final": [500.0],
                "cp_country_code": ["GB"],
                "pd_floored": [0.01],
                "lgd_post_crm": [0.45],
            }
        )
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(data, framework="CRR")
        total_rwa = bundle.c09_02["TOTAL"].filter(pl.col("row_ref") == "0150")["0125"][0]
        gb_rwa = bundle.c09_02["GB"].filter(pl.col("row_ref") == "0150")["0125"][0]
        assert total_rwa == pytest.approx(gb_rwa)

    def test_null_country_in_total_but_not_per_country(self) -> None:
        data = pl.LazyFrame(
            {
                "exposure_reference": ["E1", "E2"],
                "approach_applied": ["foundation_irb", "foundation_irb"],
                "exposure_class": ["corporate", "corporate"],
                "ead_final": [1000.0, 500.0],
                "rwa_final": [500.0, 250.0],
                "cp_country_code": ["GB", None],
                "pd_floored": [0.01, 0.02],
            }
        )
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(data, framework="CRR")
        assert "TOTAL" in bundle.c09_02
        assert "GB" in bundle.c09_02
        total_ead = bundle.c09_02["TOTAL"].filter(pl.col("row_ref") == "0150")["0105"][0]
        # Total includes both (1000 + 500 = 1500)
        assert total_ead == pytest.approx(1500.0)

    def test_slotting_included_in_corporate(self) -> None:
        """Slotting exposures classified under corporate in geographical breakdown."""
        data = pl.LazyFrame(
            {
                "exposure_reference": ["E1", "E2"],
                "approach_applied": ["slotting", "foundation_irb"],
                "exposure_class": ["specialised_lending", "corporate"],
                "ead_final": [1000.0, 500.0],
                "rwa_final": [700.0, 250.0],
                "cp_country_code": ["GB", "GB"],
                "pd_floored": [0.005, 0.01],
            }
        )
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(data, framework="CRR")
        total = bundle.c09_02["TOTAL"]
        corp_row = total.filter(pl.col("row_ref") == "0030")
        # SL maps to corporate: 1000 + 500 = 1500
        assert corp_row["0105"][0] == pytest.approx(1500.0)

    def test_zero_ead_exposure(self) -> None:
        data = pl.LazyFrame(
            {
                "exposure_reference": ["E1"],
                "approach_applied": ["foundation_irb"],
                "exposure_class": ["corporate"],
                "ead_final": [0.0],
                "ead_gross": [0.0],
                "rwa_final": [0.0],
                "cp_country_code": ["GB"],
                "pd_floored": [0.01],
            }
        )
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(data, framework="CRR")
        total = bundle.c09_02["TOTAL"]
        total_row = total.filter(pl.col("row_ref") == "0150")
        assert total_row["0105"][0] == pytest.approx(0.0)


def _irb_sf_results() -> pl.LazyFrame:
    """IRB book with one SME-supporting-factor exposure + a plain corporate.

    The SME leg carries a distinct ``rwa_pre_factor`` (pre-Art. 501 RWA) and a
    lower ``rwa_final`` (post-factor); the corporate leg has no supporting factor
    so its pre == post. Row 0030 fans the corporate family in; row 0050 is the
    "of which: SME" split (== the corporate_sme leg only).
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["SME1", "CORP1"],
            "approach_applied": ["foundation_irb", "foundation_irb"],
            "exposure_class": ["corporate_sme", "corporate"],
            "ead_final": [1000.0, 2000.0],
            "ead_gross": [1000.0, 2000.0],
            "rwa_final": [380950.0, 2000000.0],
            "rwa_pre_factor": [500000.0, 2000000.0],
            "is_sme": [True, False],
            "is_infrastructure": [False, False],
            "supporting_factor_applied": [True, False],
            "cp_country_code": ["GB", "GB"],
            "default_status": [False, False],
            "pd_floored": [0.01, 0.02],
            "lgd_post_crm": [0.45, 0.45],
        }
    )


def _irb_sme_infra_results() -> pl.LazyFrame:
    """IRB corporate book carrying BOTH an SME-supported and an
    infrastructure-supported leg on the same sheet (+ a plain corporate control).

    All three key the corporate row 0030, so the SME (0121) and infrastructure
    (0122) reliefs land on one sheet and the pre/adj/post block must still foot.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["SME1", "INFRA1", "CORP1"],
            "approach_applied": ["foundation_irb", "foundation_irb", "foundation_irb"],
            "exposure_class": ["corporate_sme", "corporate", "corporate"],
            "ead_final": [1000.0, 1500.0, 2000.0],
            "ead_gross": [1000.0, 1500.0, 2000.0],
            "rwa_final": [380950.0, 750000.0, 2000000.0],
            "rwa_pre_factor": [500000.0, 1000000.0, 2000000.0],
            "is_sme": [True, False, False],
            "is_infrastructure": [False, True, False],
            "supporting_factor_applied": [True, True, False],
            "cp_country_code": ["GB", "GB", "GB"],
            "default_status": [False, False, False],
            "pd_floored": [0.01, 0.015, 0.02],
            "lgd_post_crm": [0.45, 0.45, 0.45],
        }
    )


class TestC0902SupportingFactorColumns:
    """C 09.02 CRR supporting-factor columns (rectification R15).

    Before R15 the pre-SF RWEA (col 0110) was bound to the post-SF carrier, so
    0110 == 0125 and the (-) adjustment cols 0121/0122 were structurally null.
    The pre-SF col now keys ``rwa_pre_factor`` and the adjustment cols carry
    Σ(pre − post) over each factor's applied subset, negated.
    """

    @staticmethod
    def _row(ref: str) -> dict[str, float]:
        # Rows 0030/0050 are populated, so all four RWEA cells are non-null floats.
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_sf_results(), framework="CRR")
        row = bundle.c09_02["TOTAL"].filter(pl.col("row_ref") == ref)
        return {c: float(row[c][0]) for c in ("0110", "0121", "0122", "0125")}

    def test_corporate_parent_pre_sf(self) -> None:
        # Row 0030 = Σ rwa_pre_factor over {corporate, corporate_sme}.
        assert self._row("0030")["0110"] == pytest.approx(2500000.0)

    def test_corporate_parent_sme_adjustment(self) -> None:
        assert self._row("0030")["0121"] == pytest.approx(-119050.0)

    def test_sme_row_pre_sf(self) -> None:
        # Row 0050 "of which: SME" == the corporate_sme leg only.
        assert self._row("0050")["0110"] == pytest.approx(500000.0)

    def test_sme_row_post_sf_unchanged(self) -> None:
        assert self._row("0050")["0125"] == pytest.approx(380950.0)

    def test_sme_row_adjustment_negated(self) -> None:
        assert self._row("0050")["0121"] == pytest.approx(-119050.0)

    def test_infrastructure_adjustment_zero(self) -> None:
        assert self._row("0030")["0122"] == pytest.approx(0.0)

    def test_sf_columns_foot(self) -> None:
        row = self._row("0050")
        assert row["0110"] + row["0121"] + row["0122"] == pytest.approx(row["0125"])

    def test_delta_equals_supporting_factor_benefit(self) -> None:
        row = self._row("0030")
        assert row["0110"] - row["0125"] == pytest.approx(119050.0)

    def test_b31_has_no_supporting_factor_columns(self) -> None:
        gen = LedgerShimCorepGenerator()
        total = gen.generate_from_lazyframe(_irb_sf_results(), framework="BASEL_3_1").c09_02[
            "TOTAL"
        ]
        for ref in ("0110", "0121", "0122"):
            assert ref not in total.columns

    def test_consistency_with_c08_01_supporting_factor_pair(self) -> None:
        """Template-to-template: C 09.02 row 0050 (SME) pre/adj/post equals
        C 08.01's corporate_sme 0255/0256/0260 over the same population."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_sf_results(), framework="CRR")
        sme = bundle.c09_02["TOTAL"].filter(pl.col("row_ref") == "0050")
        c08 = bundle.c08_01["corporate_sme"].filter(pl.col("row_ref") == "0010")
        assert sme["0110"][0] == pytest.approx(c08["0255"][0])
        assert sme["0121"][0] == pytest.approx(c08["0256"][0])
        assert sme["0125"][0] == pytest.approx(c08["0260"][0])

    def test_infrastructure_and_sme_relief_on_one_sheet(self) -> None:
        """Both the SME (0121) and infrastructure (0122) adjustments populate on
        the corporate parent row 0030, each on its own factor's applied subset,
        and the pre/adj/post block foots. Pins the ``is_infrastructure`` fallback
        name, which the reference portfolio cannot exercise."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_sme_infra_results(), framework="CRR")
        row = bundle.c09_02["TOTAL"].filter(pl.col("row_ref") == "0030")
        pre, sme, infra, post = (float(row[c][0]) for c in ("0110", "0121", "0122", "0125"))
        assert sme == pytest.approx(-119050.0)  # -(500000 - 380950)
        assert infra == pytest.approx(-250000.0)  # -(1000000 - 750000)
        assert pre == pytest.approx(3500000.0)  # 500000 + 1000000 + 2000000
        assert post == pytest.approx(3130950.0)  # 380950 + 750000 + 2000000
        assert pre + sme + infra == pytest.approx(post)
