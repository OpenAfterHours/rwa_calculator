"""OF 07.00 reports a figure only where the published template has a cell.

The generator computes every cell of a row — a later cell is often a formula
over an earlier one — and until 2026-11-13 it reported them all. Three families
of figure landed where PS1/26 Annex I greys the template out:

- the CRM substitution block (cols 0050-0140) on the risk-weight rows, most
  visibly the col 0100 inflow and col 0110 net exposure;
- the pre-conversion columns on the counterparty-credit-risk rows 0090-0130,
  which report an exposure value and an RWEA and nothing before them;
- col 0211 on rows that are neither a netting-set row nor a risk-weight row.

And one column the template does not have at all: 0020.

What must NOT change is the arithmetic that runs through those cells. Col 0150
on a risk-weight row is reached through the col 0100 inflow, and the Bank's rule
``boe_b0719`` decomposes the Total row's col 0150 over the risk-weight rows — so
the block is still computed there, and only its cells are left out.

Which cells are grey is held to the Bank's taxonomy by
``tests/contracts/test_of07_published_cells.py``; this file holds that the
generator honours the declaration.

References:
- PRA PS1/26 Annex I (OF 07.00 template), Annex II §3.2.5
- Bank of England Banking Taxonomy v4.1.1, tables OF07.00.01.01 / .02
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.reporting.corep.of07_published_cells import get_c07_unreported_cells
from tests.fixtures.recon_ledger import LedgerShimCorepGenerator
from tests.unit.reporting.corep.test_c07_ccr import _ccr_derivative_results
from tests.unit.reporting.corep.test_c07_crm_substitution import _sa_results_with_substitution

_CRM_BLOCK = ("0050", "0060", "0070", "0080", "0090", "0100", "0110", "0120", "0130", "0140")
_RW_20_ROW = "0180"  # the institution sheet's own exposure
_RW_100_ROW = "0230"  # where the substituted leg is reported in this frame
_DERIVATIVE_ROW = "0110"


def _sheets(results: pl.LazyFrame, framework: str = "BASEL_3_1") -> dict[str, pl.DataFrame]:
    return LedgerShimCorepGenerator().generate_from_lazyframe(results, framework=framework).c07_00


def _row(sheet: pl.DataFrame, ref: str) -> dict[str, float | None]:
    return sheet.filter(pl.col("row_ref") == ref).row(0, named=True)


class TestRiskWeightRows:
    def test_a_risk_weight_row_reports_no_crm_substitution_block(self) -> None:
        # Arrange
        sheets = _sheets(_sa_results_with_substitution())

        # Act
        band = _row(sheets["institution"], _RW_20_ROW)

        # Assert
        assert [band[ref] for ref in _CRM_BLOCK] == [None] * len(_CRM_BLOCK)

    def test_the_inflow_still_reaches_the_fully_adjusted_exposure_on_its_band(self) -> None:
        """500 of a corporate exposure is guaranteed by an institution and arrives
        on the institution sheet. The frame seals no guarantor weight, so the
        leg is reported at the 100% band — a row with no exposure of its own,
        whose col 0150 exists ONLY because the blanked col 0100 was computed."""
        # Arrange
        sheets = _sheets(_sa_results_with_substitution())

        # Act
        band = _row(sheets["institution"], _RW_100_ROW)

        # Assert
        assert band["0010"] == pytest.approx(0.0)
        assert band["0100"] is None
        assert band["0150"] == pytest.approx(500.0)

    def test_the_total_row_keeps_its_crm_substitution_block(self) -> None:
        # Arrange
        sheets = _sheets(_sa_results_with_substitution())

        # Act
        total = _row(sheets["institution"], "0010")

        # Assert
        assert total["0100"] == pytest.approx(500.0)
        assert total["0110"] == pytest.approx(3_000.0 - 15.0 + 500.0)

    def test_the_risk_weight_rows_still_decompose_the_total_row(self) -> None:
        """boe_b0719: row 0010 col 0150 = the sum of the risk-weight rows."""
        # Arrange
        sheet = _sheets(_sa_results_with_substitution())["institution"]
        band_refs = [
            ref for ref, cols in get_c07_unreported_cells("BASEL_3_1").items() if "0100" in cols
        ]

        # Act
        bands = sheet.filter(pl.col("row_ref").is_in(band_refs))["0150"].sum()

        # Assert
        assert bands == pytest.approx(_row(sheet, "0010")["0150"])


class TestCounterpartyCreditRiskRows:
    def test_a_netting_set_row_reports_only_exposure_value_and_rwea(self) -> None:
        # Arrange
        sheets = _sheets(_ccr_derivative_results())
        reported = {"0200", "0210", "0211", "0220"}

        # Act
        row = _row(sheets["institution"], _DERIVATIVE_ROW)
        carried = {ref for ref, value in row.items() if ref.isdigit() and value is not None}

        # Assert
        assert carried <= reported
        assert row["0200"] is not None
        assert row["0220"] is not None

    def test_the_total_row_still_counts_the_netting_sets_in_its_original_exposure(self) -> None:
        """The CCR rows do not report col 0010, but the Total row's col 0010
        includes their exposure value (Annex II col 0010, CCR qualification)."""
        # Arrange
        sheets = _sheets(_ccr_derivative_results())

        # Act
        total = _row(sheets["institution"], "0010")

        # Assert
        assert total["0010"] == pytest.approx(total["0200"])
        assert total["0010"] > 0.0


class TestColumnsTheTemplateDoesNotHave:
    def test_there_is_no_column_0020_under_basel_31(self) -> None:
        # Arrange / Act
        sheet = _sheets(_sa_results_with_substitution())["corporate"]

        # Assert
        assert "0020" not in sheet.columns

    def test_col_0211_is_blank_on_the_total_row(self) -> None:
        # Arrange
        sheets = _sheets(_ccr_derivative_results())

        # Act
        total = _row(sheets["institution"], "0010")

        # Assert
        assert total["0211"] is None
        assert total["0210"] is not None


class TestEveryDeclaredBlankCell:
    @pytest.mark.parametrize(
        "results",
        [_sa_results_with_substitution, _ccr_derivative_results],
        ids=["substitution", "derivatives"],
    )
    def test_no_sheet_carries_a_figure_in_a_cell_the_template_lacks(self, results) -> None:
        # Arrange
        declared = get_c07_unreported_cells("BASEL_3_1")

        # Act
        carried = [
            (key, ref, column)
            for key, sheet in _sheets(results()).items()
            for row in sheet.iter_rows(named=True)
            for ref in [row["row_ref"]]
            for column in declared.get(ref, ())
            if row.get(column) is not None
        ]

        # Assert
        assert carried == []


class TestCrrIsUnchanged:
    def test_a_crr_risk_weight_row_still_reports_its_net_exposure(self) -> None:
        """Nothing is blanked under CRR: no EBA template is held to read its grey
        cells from, so the CRR layout is left exactly as it was."""
        # Arrange
        sheets = _sheets(_sa_results_with_substitution(), framework="CRR")

        # Act
        band = _row(sheets["institution"], "0180")

        # Assert
        assert band["0110"] is not None
        assert "0020" in sheets["institution"].columns
