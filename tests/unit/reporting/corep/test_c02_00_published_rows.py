"""C 02.00 / OF 02.00: every figure in its PUBLISHED row and column.

Why this file exists: the template reported real numbers under row codes the
published templates give to something else. The codes asserted here are read
from the publishers, not from the generator:

- Basel 3.1 — the Bank of England PRA001 taxonomy (table ``OF02.00.01.01``) and
  PS1/26 Annex II §1.3. ``tests/contracts/test_of02_published_cells.py`` holds
  the layout to the taxonomy; this file holds WHICH LEGS land in each row.
- CRR — the EBA validation rules for C 02.00, read from the packaged extract
  and evaluated as written (``v0204_m`` and its siblings state the template's
  structure), and the row labels of the PRA's own "C 02.00 - OWN FUNDS
  REQUIREMENTS (CA2)" sheet in the PS1/26 Annex I OF 02.00 workbook.

Every expected amount is a sum over named legs of ``_c02_frames`` — never over
the generator's own grouping.

References:
- PRA PS1/26 Annex II §1.3 (OF 02.00); Art. 92(2A) (the output floor)
- Regulation (EU) 2021/451 Annex I/II (C 02.00); EBA validation rules v3.0
"""

from __future__ import annotations

import datetime as dt
import logging
import re

import polars as pl
import pytest

from rwa_calc.contracts.bundles import OutputFloorSummary
from rwa_calc.contracts.config import OutputFloorConfig
from rwa_calc.domain.enums import InstitutionType, ReportingBasis
from rwa_calc.reporting.filing.canonical import FILING_MODULE, build_canonical_return
from rwa_filer.model import ReturnHeader
from rwa_filer.rules.catalogue import FRAMEWORK_CRR, load_rules
from rwa_filer.taxonomy.pack import resolve_pack
from rwa_filer.validate.structure import check_structure
from tests.fixtures.recon_ledger import LedgerShimCorepGenerator
from tests.unit.reporting.corep._c02_frames import (
    AIRB_LEGS,
    COMMON_LEGS,
    CRR_ONLY_LEGS,
    FIRB_LEGS,
    FLOOR_MULTIPLIER,
    MODELLED_LEGS,
    SA_LEGS,
    SLOTTING_LEGS,
    Leg,
    b31_frame,
    crr_frame,
    own,
    standardised,
)

CRR = "CRR"
B31 = "BASEL_3_1"
REFERENCE_DATE = dt.date(2027, 3, 31)
#: A checksum-valid LEI. Nothing here depends on who is reporting.
ENTITY_IDENTIFIER = "5493001KJTIIGC8Y1R12"
OF_ADJ = -125.0

#: The EBA rules that state the structure of C 02.00, each ``{lhs} = sum``.
CRR_STRUCTURE_RULES = ("v0204_m", "v0205_m", "v0207_m", "v0210_m", "v0211_m")

_CELL = re.compile(r"\{r(\d{4}), c(\d{4})\}")


def _summary(of_adj: float = OF_ADJ, floor_pct: float = FLOOR_MULTIPLIER) -> OutputFloorSummary:
    return OutputFloorSummary(
        u_trea=0.0,
        s_trea=0.0,
        floor_pct=floor_pct,
        floor_threshold=0.0,
        shortfall=0.0,
        portfolio_floor_binding=False,
        floored_modelled_rwa=0.0,
        of_adj=of_adj,
    )


def _generate(
    frame: pl.LazyFrame,
    framework: str,
    *,
    summary: OutputFloorSummary | None = None,
    config: OutputFloorConfig | None = None,
) -> pl.DataFrame:
    bundle = LedgerShimCorepGenerator().generate_from_lazyframe(
        frame, framework=framework, output_floor_summary=summary, output_floor_config=config
    )
    assert bundle.c_02_00 is not None
    return bundle.c_02_00


def _cell(frame: pl.DataFrame, row: str, column: str = "0010") -> float | None:
    matched = frame.filter(pl.col("row_ref") == row)
    assert matched.height == 1, f"row {row} is not in the template"
    return matched[column][0]


def _label(frame: pl.DataFrame, row: str) -> str:
    return frame.filter(pl.col("row_ref") == row)["row_name"][0]


@pytest.fixture(scope="module")
def crr() -> pl.DataFrame:
    return _generate(crr_frame(), CRR)


@pytest.fixture(scope="module")
def b31() -> pl.DataFrame:
    return _generate(b31_frame(), B31, summary=_summary())


# =============================================================================
# CRR — C 02.00
# =============================================================================


class TestCrrStructure:
    """The structure the EBA's own rules state, evaluated as written."""

    @pytest.mark.parametrize("rule_id", CRR_STRUCTURE_RULES)
    def test_the_published_identity_holds(self, crr: pl.DataFrame, rule_id: str) -> None:
        # Arrange
        rule = next(r for r in load_rules(FRAMEWORK_CRR).rules if r.rule_id == rule_id)
        assert rule.expression is not None
        (lhs_row, lhs_column), *terms = _CELL.findall(rule.expression)
        reported = dict(zip(crr["row_ref"].to_list(), crr["0010"].to_list(), strict=True))

        # Act — a cell the return does not carry counts as zero, as the rule says.
        lhs = reported.get(lhs_row) or 0.0
        rhs = sum(reported.get(row) or 0.0 for row, _ in terms)

        # Assert
        assert lhs_column == "0010"
        assert lhs > 0.0, f"{rule_id} is vacuous on this frame: row {lhs_row} carries nothing"
        assert lhs == pytest.approx(rhs), f"{rule_id}: {rule.expression}"

    @pytest.mark.parametrize(
        ("row", "label"),
        [
            # PS1/26 Annex I OF 02.00 workbook, sheet "C 02.00 - OWN FUNDS REQUIREMENTS (CA2)",
            # whitespace normalised (the sheet prints "(OpR )" and a double space in 0150).
            (
                "0040",
                "RISK WEIGHTED EXPOSURE AMOUNTS FOR CREDIT, COUNTERPARTY CREDIT AND DILUTION "
                "RISKS AND FREE DELIVERIES",
            ),
            ("0050", "Standardised approach (SA)"),
            ("0060", "SA exposure classes excluding securitisation positions"),
            ("0240", "Internal ratings based Approach (IRB)"),
            (
                "0250",
                "IRB approaches when neither own estimates of LGD nor Conversion Factors are used",
            ),
            ("0260", "Central governments and central banks"),
            ("0270", "Institutions"),
            ("0280", "Corporates - SME"),
            ("0290", "Corporates - Specialised Lending"),
            ("0300", "Corporates - Other"),
            ("0310", "IRB approaches when own estimates of LGD and/or Conversion Factors are used"),
            ("0320", "Central governments and central banks"),
            ("0330", "Institutions"),
            ("0340", "Corporates - SME"),
            ("0350", "Corporates - Specialised Lending"),
            ("0360", "Corporates - Other"),
            ("0370", "Retail - Secured by real estate SME"),
            ("0380", "Retail - Secured by real estate non-SME"),
            ("0390", "Retail - Qualifying revolving"),
            ("0400", "Retail - Other SME"),
            ("0410", "Retail - Other non-SME"),
            ("0420", "Equity IRB"),
            ("0470", "Securitisation positions"),
            ("0490", "TOTAL RISK EXPOSURE AMOUNT FOR SETTLEMENT/DELIVERY"),
            (
                "0520",
                "TOTAL RISK EXPOSURE AMOUNT FOR POSITION, FOREIGN EXCHANGE AND COMMODITIES RISKS",
            ),
            ("0590", "TOTAL RISK EXPOSURE AMOUNT FOR OPERATIONAL RISK (OpR)"),
            ("0630", "ADDITIONAL RISK EXPOSURE AMOUNT DUE TO FIXED OVERHEADS"),
            ("0640", "TOTAL RISK EXPOSURE AMOUNT FOR CREDIT VALUATION ADJUSTMENT"),
        ],
    )
    def test_the_row_carries_its_published_label(
        self, crr: pl.DataFrame, row: str, label: str
    ) -> None:
        assert _label(crr, row) == label

    @pytest.mark.parametrize("row", ["0220", "0430", "0440"])
    def test_a_code_the_template_does_not_have_is_not_a_row(
        self, crr: pl.DataFrame, row: str
    ) -> None:
        """0220 / 0430 / 0440 were our IRB total, settlement and securitisation
        rows; C 02.00 has no such codes (v0205_m: 0040 = 0050 + 0240 + 0460 + 0470)."""
        assert crr.filter(pl.col("row_ref") == row).height == 0


class TestCrrPlacement:
    """Which legs each published row counts."""

    def test_the_totals(self, crr: pl.DataFrame) -> None:
        everything = own(COMMON_LEGS + CRR_ONLY_LEGS)
        assert _cell(crr, "0010") == pytest.approx(everything)
        assert _cell(crr, "0040") == pytest.approx(everything)

    def test_the_standardised_approach_is_one_figure_in_two_rows(self, crr: pl.DataFrame) -> None:
        """0050 "SA" has one component, 0060 "SA classes excluding securitisation"."""
        assert _cell(crr, "0050") == pytest.approx(own(SA_LEGS))
        assert _cell(crr, "0060") == pytest.approx(own(SA_LEGS))

    def test_the_irb_total_counts_both_approaches_slotting_and_irb_equity(
        self, crr: pl.DataFrame
    ) -> None:
        expected = own(MODELLED_LEGS) + own(CRR_ONLY_LEGS)
        assert _cell(crr, "0240") == pytest.approx(expected)
        assert _cell(crr, "0240") == pytest.approx(
            _cell(crr, "0250") + _cell(crr, "0310") + _cell(crr, "0420")  # type: ignore[operator]
        )

    @pytest.mark.parametrize(
        ("row", "references"),
        [
            ("0260", ("F_CG",)),
            ("0270", ("F_INST",)),
            ("0280", ("F_SME",)),
            # CRR Art. 147(2)(c) has no "financial and large" corporate sub-class.
            ("0300", ("F_FSE", "F_OTH")),
            ("0320", ("A_CG",)),
            ("0330", ("A_INST",)),
            ("0340", ("A_SME",)),
            ("0350", ("A_SL",)),
            ("0360", ("A_OTH",)),
            ("0370", ("A_RES_SME", "A_COM_SME")),
            ("0380", ("A_RES", "A_COM")),
            ("0390", ("A_QRRE",)),
            ("0400", ("A_OSME",)),
            ("0410", ("A_ONON",)),
            ("0420", ("EQ_IRB",)),
        ],
    )
    def test_the_class_row_counts_its_legs(
        self, crr: pl.DataFrame, row: str, references: tuple[str, ...]
    ) -> None:
        assert _cell(crr, row) == pytest.approx(own(COMMON_LEGS + CRR_ONLY_LEGS, *references))

    def test_slotting_is_specialised_lending_without_own_estimates(self, crr: pl.DataFrame) -> None:
        """C 02.00 has no slotting row. v10673_m lets the C 08.01 slotting row carry
        a figure on the specialised-lending sheets only, v0338_m puts it in that
        sheet's total, and v4248_i ties the total to row 0290 — whose parent 0250
        is "neither own estimates of LGD nor Conversion Factors", which is what
        Art. 153(5) slotting is."""
        assert _cell(crr, "0290") == pytest.approx(own(FIRB_LEGS, "F_SL") + own(SLOTTING_LEGS))
        assert _cell(crr, "0250") == pytest.approx(
            own(FIRB_LEGS) + own(SLOTTING_LEGS) + own(CRR_ONLY_LEGS, "F_CG")
        )

    def test_slotting_is_not_reported_as_retail(self) -> None:
        """Row 0410 was "Supervisory slotting"; it is "Retail - Other non-SME"."""
        frame = _generate(crr_frame(SLOTTING_LEGS), CRR)
        assert _cell(frame, "0410") == pytest.approx(0.0)
        assert _cell(frame, "0310") == pytest.approx(0.0)

    @pytest.mark.parametrize(
        "row", ["0450", "0460", "0470", "0490", "0520", "0590", "0630", "0640", "0680", "0690"]
    )
    def test_a_row_this_calculator_does_not_compute_is_empty(
        self, crr: pl.DataFrame, row: str
    ) -> None:
        assert _cell(crr, row) is None


# =============================================================================
# Basel 3.1 — OF 02.00
# =============================================================================


class TestB31Placement:
    """Which legs each published row counts, in column 0010."""

    def test_the_totals(self, b31: pl.DataFrame) -> None:
        assert _cell(b31, "0010") == pytest.approx(own(COMMON_LEGS))
        assert _cell(b31, "0040") == pytest.approx(own(COMMON_LEGS))

    def test_the_standardised_approach_is_one_figure_in_two_rows(self, b31: pl.DataFrame) -> None:
        """Rows 0050 and 0060 are ONE data point in the taxonomy."""
        assert _cell(b31, "0050") == pytest.approx(own(SA_LEGS))
        assert _cell(b31, "0060") == pytest.approx(own(SA_LEGS))

    @pytest.mark.parametrize(
        ("row", "references"),
        [
            ("0131", ("SA_SL",)),
            ("0240", tuple(leg.reference for leg in MODELLED_LEGS)),
            ("0250", tuple(leg.reference for leg in FIRB_LEGS)),
            ("0271", ("F_INST",)),
            ("0290", ("F_SL",)),
            ("0295", ("F_FSE",)),
            ("0296", ("F_SME",)),
            ("0297", ("F_OTH",)),
            ("0310", tuple(leg.reference for leg in AIRB_LEGS)),
            ("0350", ("A_SL",)),
            ("0355", ("A_SME",)),
            ("0356", ("A_OTH",)),
            ("0382", ("A_RES_SME",)),
            ("0383", ("A_RES",)),
            ("0384", ("A_COM_SME",)),
            ("0385", ("A_COM",)),
            ("0390", ("A_QRRE",)),
            ("0400", ("A_OSME",)),
            ("0410", ("A_ONON",)),
            ("0411", tuple(leg.reference for leg in SLOTTING_LEGS)),
            ("0412", ("SL_PF",)),
            ("0413", ("SL_OF",)),
            ("0414", ("SL_CF",)),
            ("0415", ("SL_IPRE",)),
            ("0416", ("SL_HVCRE",)),
        ],
    )
    def test_the_row_counts_its_legs_in_both_columns(
        self, b31: pl.DataFrame, row: str, references: tuple[str, ...]
    ) -> None:
        """Column 0020 is the standardised-approach RWEA of the SAME legs (PS1/26
        Annex II §1.3: "risk exposure amounts calculated under standardised
        approaches per exposure class"); the taxonomy has it on the modelled
        rows only, so the one SA row here (0131) carries column 0010 alone."""
        assert _cell(b31, row) == pytest.approx(own(COMMON_LEGS, *references))
        expected_sa = None if row == "0131" else standardised(COMMON_LEGS, *references)
        assert _cell(b31, row, "0020") == (
            None if expected_sa is None else pytest.approx(expected_sa)
        )

    @pytest.mark.parametrize(
        "row",
        [
            "0190",  # no Art. 112(1)(n) class under PS1/26
            "0220",  # was our IRB total; the IRB total is 0240
            "0260",  # was "F-IRB corporates"; 0250 has no corporate subtotal
            "0300",  # was our A-IRB total; the A-IRB total is 0310
            "0330",  # A-IRB institutions: withdrawn by Art. 147A
            "0340",  # was "A-IRB corporates"; 0310 has no corporate subtotal
            "0370",  # was "A-IRB retail"; 0310 has no retail subtotal
            "0380",  # was "A-IRB retail secured by property"; split into 0382-0385
            "0420",  # Equity IRB: withdrawn by Art. 147A
            "0430",  # was settlement risk; that is 0490
            "0440",  # was securitisation; that is 0470
            "0500",  # was a currency-mismatch memo; 0500 is non-trading-book settlement
        ],
    )
    def test_a_code_the_template_does_not_have_is_not_a_row(
        self, b31: pl.DataFrame, row: str
    ) -> None:
        assert b31.filter(pl.col("row_ref") == row).height == 0

    def test_the_published_credit_risk_sum_holds(self, b31: pl.DataFrame) -> None:
        """boe_b1093: r0040 = r0050 + r0240 + r0460 + r0470, column 0010."""
        assert _cell(b31, "0040") == pytest.approx(
            _cell(b31, "0050") + _cell(b31, "0240")  # type: ignore[operator]
        )
        assert _cell(b31, "0460") is None
        assert _cell(b31, "0470") is None

    def test_an_exposure_the_template_has_no_row_for_stays_in_its_approach_total(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """PS1/26 Art. 147A withdraws A-IRB for institutions, so OF 02.00 has no
        such row. The RWEA is neither dropped nor put in a neighbouring row: it
        stays in the A-IRB and IRB totals and the shortfall is logged."""
        # Arrange
        stray = Leg("A_INST", "advanced_irb", "institution", 620.0, 700.0)
        legs = (*AIRB_LEGS, stray)

        # Act
        with caplog.at_level(logging.WARNING, logger="rwa_calc.reporting.corep.c02"):
            frame = _generate(b31_frame(legs), B31)

        # Assert
        assert _cell(frame, "0310") == pytest.approx(own(legs))
        assert _cell(frame, "0240") == pytest.approx(own(legs))
        details = ("0350", "0355", "0356", "0382", "0383", "0384", "0385", "0390", "0400", "0410")
        assert sum(_cell(frame, row) or 0.0 for row in details) == pytest.approx(own(AIRB_LEGS))
        assert any("620.00" in record.getMessage() for record in caplog.records)


class TestB31Columns:
    """Where columns 0020 and 0030 exist, and what they hold."""

    def test_a_standardised_row_reports_column_0010_only(self, b31: pl.DataFrame) -> None:
        for row in ("0050", "0060", "0070", "0120", "0130", "0150", "0210", "0211"):
            assert _cell(b31, row) is not None
            assert _cell(b31, row, "0020") is None, f"row {row} has no column 0020"
            assert _cell(b31, row, "0030") is None, f"row {row} has no column 0030"

    def test_a_modelled_row_reports_no_column_0030(self, b31: pl.DataFrame) -> None:
        for row in ("0040", "0240", "0250", "0271", "0310", "0390", "0411", "0412"):
            assert _cell(b31, row, "0020") is not None
            assert _cell(b31, row, "0030") is None, f"row {row} has no column 0030"

    def test_the_total_row_reports_no_column_0020(self, b31: pl.DataFrame) -> None:
        assert _cell(b31, "0010", "0020") is None

    def test_the_floor_rows_report_column_0030_only(self, b31: pl.DataFrame) -> None:
        for row in ("0034", "0035", "0036"):
            assert _cell(b31, row, "0010") is None
            assert _cell(b31, row, "0020") is None
            assert _cell(b31, row, "0030") is not None

    def test_standardised_credit_risk_is_sa_plus_the_modelled_book_on_sa(
        self, b31: pl.DataFrame
    ) -> None:
        """boe_b0716: r0040 c0020 = r0050 c0010 + r0240 c0020 (+ r0460 + r0470)."""
        expected = own(SA_LEGS) + standardised(MODELLED_LEGS)
        assert _cell(b31, "0040", "0020") == pytest.approx(expected)
        assert _cell(b31, "0040", "0020") == pytest.approx(
            _cell(b31, "0050") + _cell(b31, "0240", "0020")  # type: ignore[operator]
        )


class TestB31OutputFloor:
    """Rows 0010 (column 0030), 0034, 0035 and 0036."""

    def test_the_multiplier_is_a_rate_not_a_percentage(self, b31: pl.DataFrame) -> None:
        """boe_b0359 admits 0.55, 0.60, 0.65, 0.70 and 0.725 — not 55 or 72.5."""
        assert _cell(b31, "0035", "0030") == pytest.approx(FLOOR_MULTIPLIER)

    def test_the_multiplier_is_the_summarys_when_one_is_supplied(self) -> None:
        frame = _generate(b31_frame(), B31, summary=_summary(floor_pct=0.725))
        assert _cell(frame, "0035", "0030") == pytest.approx(0.725)

    def test_the_multiplier_is_read_off_the_ledger_without_a_summary(self) -> None:
        frame = _generate(b31_frame(), B31)
        assert _cell(frame, "0035", "0030") == pytest.approx(FLOOR_MULTIPLIER)

    def test_no_multiplier_is_invented_when_the_floor_never_ran(self) -> None:
        """An unknown multiplier is empty, never 0.0 — which boe_b0359 rejects."""
        frame = _generate(b31_frame(carry_multiplier=False), B31)
        assert _cell(frame, "0035", "0030") is None

    def test_the_adjustment_is_the_summarys(self, b31: pl.DataFrame) -> None:
        assert _cell(b31, "0036", "0030") == pytest.approx(OF_ADJ)

    def test_the_floor_is_x_times_s_trea_plus_of_adj(self, b31: pl.DataFrame) -> None:
        """PS1/26 Annex II §1.3, row 0010: "x * S-TREA + OF-ADJ", with S-TREA "the
        total of all SA exposures provided in columns 0010 and 0020"."""
        s_trea = own(SA_LEGS) + standardised(MODELLED_LEGS)
        assert _cell(b31, "0010", "0030") == pytest.approx(FLOOR_MULTIPLIER * s_trea + OF_ADJ)

    def test_the_floor_is_not_stated_without_the_adjustment(self) -> None:
        """OF-ADJ is a portfolio figure the ledger does not carry: with no summary
        the floor is unknown, and an unknown floor is empty rather than wrong.
        boe_b0957 then asks for none of rows 0034-0036."""
        frame = _generate(b31_frame(), B31)
        assert _cell(frame, "0010", "0030") is None
        assert _cell(frame, "0034", "0030") is None
        assert _cell(frame, "0036", "0030") is None

    def test_the_floor_is_not_activated_below_the_unfloored_total(self, b31: pl.DataFrame) -> None:
        floor = _cell(b31, "0010", "0030")
        assert floor is not None
        assert floor < own(COMMON_LEGS)
        assert _cell(b31, "0034", "0030") == pytest.approx(0.0)

    def test_the_floor_is_activated_at_or_above_the_unfloored_total(self) -> None:
        """Annex II row 0034: "when, in row 0010, the value in column 0030 is equal
        to or greater than the value in column 0010"."""
        # Arrange — an adjustment large enough to lift the floor over U-TREA.
        s_trea = own(SA_LEGS) + standardised(MODELLED_LEGS)
        of_adj = own(COMMON_LEGS) - FLOOR_MULTIPLIER * s_trea

        # Act
        frame = _generate(b31_frame(), B31, summary=_summary(of_adj=of_adj))

        # Assert
        assert _cell(frame, "0010", "0030") == pytest.approx(own(COMMON_LEGS))
        assert _cell(frame, "0034", "0030") == pytest.approx(1.0)

    def test_column_0010_is_the_unfloored_amount_when_the_floor_binds(self) -> None:
        """Row 0010 column 0010 is ONE data point with OF 02.01's U-TREA total, and
        boe_b1092 sums it from the rows beneath it — so a binding floor's add-on
        (in ``rwa_final``) belongs in none of them."""
        # Arrange
        frame = _generate(b31_frame(floor_add_on=1_000.0), B31, summary=_summary())

        # Act / Assert
        assert _cell(frame, "0010") == pytest.approx(own(COMMON_LEGS))
        assert _cell(frame, "0240") == pytest.approx(own(MODELLED_LEGS))
        assert _cell(frame, "0271") == pytest.approx(own(FIRB_LEGS, "F_INST"))

    def test_an_exempt_entity_reports_no_output_floor(self) -> None:
        """An entity outside Art. 92(2A) has no floor: column 0030 is empty. Column
        0020 is not the floor and stays — boe_b0716 is an Error rule with no
        precondition, and the class cells are OF 08.01 col 0276's data points."""
        # Arrange
        exempt = OutputFloorConfig.basel_3_1(
            institution_type=InstitutionType.INTERNATIONAL_SUBSIDIARY,
            reporting_basis=ReportingBasis.INDIVIDUAL,
        )

        # Act
        frame = _generate(b31_frame(), B31, summary=_summary(), config=exempt)

        # Assert
        assert frame["0030"].null_count() == frame.height
        assert _cell(frame, "0240", "0020") == pytest.approx(standardised(MODELLED_LEGS))
        assert _cell(frame, "0040", "0020") == pytest.approx(
            own(SA_LEGS) + standardised(MODELLED_LEGS)
        )


class TestB31StandardisedColumnWithoutTheCarrier:
    """Column 0020 on a ledger that seals no ``sa_rwa`` — the floor never ran."""

    def test_a_standardised_only_book_still_states_its_s_trea(self) -> None:
        """boe_b0716 has no precondition: row 0040 column 0020 must equal row 0050
        column 0010 on a book with nothing modelled. Nothing is needed from
        ``sa_rwa`` to know it — S-TREA of an SA book is its own RWEA."""
        # Arrange
        frame = _generate(b31_frame(SA_LEGS).drop("sa_rwa", "rwa_pre_floor"), B31)

        # Act / Assert
        assert _cell(frame, "0040", "0020") == pytest.approx(own(SA_LEGS))
        assert _cell(frame, "0040", "0020") == pytest.approx(_cell(frame, "0050"))
        assert _cell(frame, "0240", "0020") == pytest.approx(0.0)

    def test_a_modelled_book_without_the_carrier_is_left_empty_and_says_so(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The standardised RWEA of a modelled leg cannot be derived here. Empty,
        with a warning — never the leg's own RWEA and never zero."""
        # Arrange
        ledger = b31_frame().drop("sa_rwa")

        # Act
        with caplog.at_level(logging.WARNING, logger="rwa_calc.reporting.corep.c02"):
            frame = _generate(ledger, B31, summary=_summary())

        # Assert
        assert frame["0020"].null_count() == frame.height
        assert _cell(frame, "0010", "0030") is None
        assert _cell(frame, "0240") == pytest.approx(own(MODELLED_LEGS))
        assert any("no sa_rwa" in record.getMessage() for record in caplog.records)


class TestB31OneFactWithOf0201:
    """Row 0010 column 0010 and OF 02.01 row 0080 column 0030 are ONE data point
    in the PRA001 taxonomy: a return holds one number for the two cells."""

    def test_the_return_holds_one_unfloored_total_for_the_two_templates(self) -> None:
        """OF 02.01 reaches U-TREA as "modelled + standardised" (Annex II column
        0030); OF 02.00 sums the same legs flat, and the two can differ in the
        last binary place. Each template keeps the sum of its own legs; the
        filing adapter gives the shared data point one value, so the structure
        check — which compares the cells EXACTLY — has nothing to refuse."""
        # Arrange — thirds: flat 1850.0 against 1850.0000000000002 partitioned.
        legs = tuple(leg._replace(own=leg.own / 3.0) for leg in COMMON_LEGS)
        bundle = LedgerShimCorepGenerator().generate_from_lazyframe(b31_frame(legs), framework=B31)
        assert bundle.c_02_00 is not None
        assert bundle.of_02_01 is not None
        u_trea = bundle.of_02_01.filter(pl.col("row_ref") == "0080")["0030"][0]
        assert _cell(bundle.c_02_00, "0010") != u_trea, "the two sums no longer differ"
        assert _cell(bundle.c_02_00, "0010") == pytest.approx(u_trea)
        pack = resolve_pack(FILING_MODULE, REFERENCE_DATE)
        header = ReturnHeader(ENTITY_IDENTIFIER, REFERENCE_DATE, FILING_MODULE)

        # Act
        canonical = build_canonical_return(bundle, header, pack=pack).canonical
        filed = canonical.facts.filter(
            ((pl.col("table") == "OF02.00.01.01") & (pl.col("row") == "0010"))
            | ((pl.col("table") == "OF02.01.01.03") & (pl.col("row") == "0080"))
        ).filter(pl.col("column").is_in(["0010", "0030"]))
        shared = filed.filter(
            ((pl.col("table") == "OF02.00.01.01") & (pl.col("column") == "0010"))
            | ((pl.col("table") == "OF02.01.01.03") & (pl.col("column") == "0030"))
        )

        # Assert — on the U-TREA data point alone: this synthetic frame gives its
        # SA-CCR leg none of the columns OF 07.00 admits a derivative on, so the SA
        # rows disagree with OF 07.00 here for a reason that is the frame's.
        assert shared.height == 2
        assert shared["value"].n_unique() == 1
        assert "OF02.01.01.03" not in [
            finding.subject
            for finding in check_structure(canonical, pack)
            if finding.code == "STR007"
        ]
