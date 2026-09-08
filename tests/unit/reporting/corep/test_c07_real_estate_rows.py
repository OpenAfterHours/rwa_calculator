"""OF 07.00 real-estate detail rows 0330-0360 (Basel 3.1).

Split out of ``test_c07.py``: the sheet axis is the Art. 112(1) class list, so
every mortgage-secured ``ExposureClass`` member reports on ONE ``real_estate``
sheet and the residential / commercial / ADC detail lives entirely on the ROW
axis. That makes this block the row-axis counterpart of the class merge, and it
is large enough that keeping it here also holds ``test_c07.py`` under the
``max_reporting_test_file_loc`` ratchet.

Why the rows matter: PS1/26 requires granular reporting of RE exposures by
property type, cash-flow dependency and SME status, which is what lets a
supervisor see concentration risk in property-secured lending.

References:
- PRA PS1/26 Annex II, OF 07.00 rows 0330-0360
"""

from __future__ import annotations

import polars as pl
import pytest

from tests.fixtures.recon_ledger import LedgerShimCorepGenerator


def _sa_results_with_re() -> pl.LazyFrame:
    """SA results spanning the residential / commercial / ADC row axis."""
    return pl.LazyFrame(
        {
            "exposure_reference": [
                "SA_RE_RES_1",
                "SA_RE_RES_2",
                "SA_RE_COMM_1",
                "SA_RE_COMM_2",
                "SA_RE_COMM_3",
                "SA_RE_ADC_1",
                "SA_CORP_1",
            ],
            "approach_applied": ["standardised"] * 7,
            # ``ExposureClass`` members, not descriptive strings: the sealed
            # class carrier only ever holds enum values, and all three RE members
            # key the single Art. 112(1)(i) ``real_estate`` sheet. The
            # residential / commercial distinction these rows exercise is a ROW
            # breakdown on that sheet (0330-0360, driven by ``property_type``).
            "exposure_class": [
                "residential_mortgage",
                "residential_mortgage",
                "commercial_mortgage",
                "commercial_mortgage",
                "commercial_mortgage",
                "commercial_mortgage",
                "corporate",
            ],
            "drawn_amount": [200.0, 300.0, 500.0, 400.0, 150.0, 100.0, 1000.0],
            "undrawn_amount": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "ead_final": [200.0, 300.0, 500.0, 400.0, 150.0, 100.0, 1000.0],
            "rwa_final": [40.0, 105.0, 300.0, 240.0, 112.5, 150.0, 1000.0],
            "risk_weight": [0.20, 0.35, 0.60, 0.60, 0.75, 1.50, 1.00],
            "scra_provision_amount": [0.0] * 7,
            "gcra_provision_amount": [0.0] * 7,
            "collateral_adjusted_value": [0.0] * 7,
            "guaranteed_portion": [0.0] * 7,
            "sa_cqs": [None] * 7,
            "counterparty_reference": [
                "CP_R1",
                "CP_R2",
                "CP_C1",
                "CP_C2",
                "CP_C3",
                "CP_ADC",
                "CP_CORP",
            ],
            "property_type": [
                "residential",
                "residential",
                "commercial",
                "commercial",
                "commercial",
                "commercial",
                None,
            ],
            "materially_dependent_on_property": [
                False,
                True,
                False,
                True,
                False,
                None,
                None,
            ],
            "is_adc": [False, False, False, False, False, True, False],
            # SME flag for commercial sub-split
            "sme_supporting_factor_eligible": [
                False,
                False,
                False,
                False,
                True,
                False,
                False,
            ],
        }
    )


class TestRealEstateRows:
    """Task 3H: Real estate detail rows (B3.1 OF 07.00 rows 0330-0360).

    Why: Basel 3.1 requires granular reporting of RE exposures by property
    type, cash-flow dependency, and SME status. This enables supervisors to
    assess concentration risk in property-secured lending.
    """

    def test_the_fixture_spans_more_than_one_engine_re_class(self) -> None:
        """Adequacy (``.claude/LESSONS.md`` C11). Every row assertion below is
        stated on ONE merged sheet, so it is only a test of the row axis if the
        sheet is fed by more than one engine class."""
        classes = set(_sa_results_with_re().collect()["exposure_class"].to_list())

        assert {"residential_mortgage", "commercial_mortgage"} <= classes

    def test_residential_re_total(self) -> None:
        """Row 0330 shows total regulatory residential RE."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_re(), framework="BASEL_3_1")
        # Every RE class shares the Art. 112(1)(i) "real_estate" sheet
        re_res = bundle.c07_00.get("real_estate")
        assert re_res is not None
        row = re_res.filter(pl.col("row_ref") == "0330")
        assert len(row) == 1
        # SA_RE_RES_1 + SA_RE_RES_2: 200 + 300 = 500
        assert row["0200"][0] == pytest.approx(500.0)

    def test_residential_not_dependent(self) -> None:
        """Row 0331: residential, not materially dependent."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_re(), framework="BASEL_3_1")
        re_res = bundle.c07_00["real_estate"]
        row = re_res.filter(pl.col("row_ref") == "0331")
        assert len(row) == 1
        # SA_RE_RES_1: 200 (not dependent)
        assert row["0200"][0] == pytest.approx(200.0)

    def test_residential_dependent(self) -> None:
        """Row 0332: residential, materially dependent."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_re(), framework="BASEL_3_1")
        re_res = bundle.c07_00["real_estate"]
        row = re_res.filter(pl.col("row_ref") == "0332")
        assert len(row) == 1
        # SA_RE_RES_2: 300 (dependent)
        assert row["0200"][0] == pytest.approx(300.0)

    def test_commercial_re_total(self) -> None:
        """Row 0340 shows total regulatory commercial RE."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_re(), framework="BASEL_3_1")
        re_comm = bundle.c07_00.get("real_estate")
        assert re_comm is not None
        row = re_comm.filter(pl.col("row_ref") == "0340")
        assert len(row) == 1
        # All commercial (excl ADC): 500 + 400 + 150 + 100 = 1150
        # But property_type = commercial for all, including ADC
        assert row["0200"][0] == pytest.approx(1150.0)

    def test_commercial_not_dependent_non_sme(self) -> None:
        """Row 0341: commercial, not dependent, non-SME."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_re(), framework="BASEL_3_1")
        re_comm = bundle.c07_00["real_estate"]
        row = re_comm.filter(pl.col("row_ref") == "0341")
        assert len(row) == 1
        # SA_RE_COMM_1: 500 (not dependent, not SME)
        assert row["0200"][0] == pytest.approx(500.0)

    def test_commercial_sme_not_dependent(self) -> None:
        """Row 0343: commercial, not dependent, SME."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_re(), framework="BASEL_3_1")
        re_comm = bundle.c07_00["real_estate"]
        row = re_comm.filter(pl.col("row_ref") == "0343")
        assert len(row) == 1
        # SA_RE_COMM_3: 150 (not dependent, SME)
        assert row["0200"][0] == pytest.approx(150.0)

    def test_adc_row(self) -> None:
        """Row 0360 shows ADC exposures."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_re(), framework="BASEL_3_1")
        re_comm = bundle.c07_00["real_estate"]
        row = re_comm.filter(pl.col("row_ref") == "0360")
        assert len(row) == 1
        # SA_RE_ADC_1: 100
        assert row["0200"][0] == pytest.approx(100.0)

    def test_re_rows_absent_crr(self) -> None:
        """RE detail rows don't exist under CRR."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_re(), framework="CRR")
        re_res = bundle.c07_00.get("real_estate")
        if re_res is not None:
            re_rows = re_res.filter(
                pl.col("row_ref").is_in(["0330", "0331", "0332", "0340", "0341", "0342", "0360"])
            )
            assert len(re_rows) == 0

    def test_dependent_splits_sum_to_total(self) -> None:
        """Rows 0331 + 0332 = 0330 for residential RE."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_re(), framework="BASEL_3_1")
        re_res = bundle.c07_00["real_estate"]
        total = re_res.filter(pl.col("row_ref") == "0330")["0200"][0]
        not_dep = re_res.filter(pl.col("row_ref") == "0331")["0200"][0]
        dep = re_res.filter(pl.col("row_ref") == "0332")["0200"][0]
        assert total == pytest.approx(not_dep + dep)

    def test_the_property_type_rows_foot_to_the_merged_sheet_total(self) -> None:
        """0330 + 0340 + 0360 = the sheet's own total row.

        The merge put four engine rows on one sheet; this is the assertion that
        none of them was dropped on the way onto the row axis (``LESSONS`` E2 —
        a breakdown that silently sheds rows still looks plausible read row by
        row). ``SA_CORP_1`` is on the corporate sheet, so the RE sheet totals
        only the six mortgage rows.
        """
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_re(), framework="BASEL_3_1")
        sheet = bundle.c07_00["real_estate"]

        def value(row_ref: str) -> float:
            return float(sheet.filter(pl.col("row_ref") == row_ref)["0200"][0] or 0.0)

        # Row 0340 already counts the ADC leg (its property_type is commercial),
        # so 0360 is an of-which of 0340 rather than a sibling of it.
        assert value("0010") == pytest.approx(value("0330") + value("0340"))
        assert value("0010") == pytest.approx(1650.0)
