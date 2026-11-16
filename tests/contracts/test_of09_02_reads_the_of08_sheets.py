"""
OF 09.02's class rows against the OF 08.01 sheets the Bank's rules tie them to.

Why this file exists: OF 09.02 split its Basel 3.1 rows on carriers of its own —
the correlation-multiplier input ``cp_apply_fi_scalar`` for "financial corporates
and large corporates" (row 0048), and an SME test that read the class NAME (rows
0050, 0071-0074, 0120) — while OF 02.00 and OF 08 split the same legs on
``corep/irb_sheets.py``. Annex II addresses row 0048 to Art. 147(4C) and the OF 08
sheet 0022 to Art. 147(2)(c)(ii), the same population, and the Bank ties the two
templates row by row with ERROR rules, so a leg classified differently is one
population reported as two (plan P2.67).

The source of truth (LESSONS B3) is the Bank's own rule book: every enforced rule
of the form "OF 09.02 row R, all countries, = (or <=) OF 08.01 row 0010 on sheets
Z" is read from it, and the identity is asserted on a book with a leg on every
published sheet. Nothing here is taken from ``c09.py`` or ``irb_sheets.py`` except
the published-code -> sheet-key map, which ``test_of08_published_sheets.py`` holds
to the taxonomy.

The identity is asserted on the CELLS, not on the engine's verdict: the book's
amounts are in the hundreds and a monetary fact is filed to the nearest thousand,
so every rule of the family passes on it whatever the cells say.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, NamedTuple

import polars as pl
import pytest
from tests.fixtures.recon_ledger import LedgerShimCorepGenerator
from tests.unit.reporting.corep._c02_frames import MODELLED_LEGS, b31_frame

from rwa_calc.reporting.corep import irb_sheets
from rwa_filer.boe.catalogue import load_rulebook

if TYPE_CHECKING:
    from rwa_calc.reporting.corep.generator import COREPTemplateBundle

FRAMEWORK = "BASEL_3_1"
MODULE = "PRA001"
RULE_BOOK = "banking_reporting-4.1.1.json"
#: The leg flagged with the correlation-multiplier input. It is an OTHER general
#: corporate by sub-class, so it must NOT follow the flag into row 0048; F_FSE,
#: financial / large by sub-class, carries no flag and must still be there.
MULTIPLIER_FLAGGED = ("F_OTH",)

_TIE = re.compile(
    r"^\{t: OF09\.02\.01\.01, r: (?P<row>\d{4}), c: (?P<column>\d{4}),.*?\} (?P<op>i=|i<=) "
    r"(?:isum\()?\{t: OF08\.01\.01\.01, r: 0010, c: (?P<column_08>\d{4}), z: (?P<z>[0-9; ]+),"
)


class Tie(NamedTuple):
    """One published tie: an OF 09.02 cell against OF 08.01 sheet totals."""

    rule_id: str
    row: str
    column: str
    operator: str
    column_08: str
    sheet_codes: tuple[str, ...]


def _published_ties() -> list[Tie]:
    ties = []
    for rule in load_rulebook(RULE_BOOK).rules:
        match = _TIE.match(rule.expression) if rule.is_enforced(MODULE) else None
        if match:
            codes = tuple(code.strip() for code in match["z"].split(";"))
            ties.append(
                Tie(
                    rule.rule_id,
                    match["row"],
                    match["column"],
                    match["op"],
                    match["column_08"],
                    codes,
                )
            )
    return ties


TIES = _published_ties()


@pytest.fixture(scope="module")
def frame() -> pl.LazyFrame:
    return b31_frame(MODELLED_LEGS).with_columns(
        pl.lit("GB").alias("cp_country_code"),
        pl.col("exposure_reference").is_in(list(MULTIPLIER_FLAGGED)).alias("cp_apply_fi_scalar"),
        pl.lit(0.01).alias("pd_floored"),
        pl.lit(0.45).alias("lgd_post_crm"),
        pl.col("ead_final").alias("drawn_amount"),
    )


@pytest.fixture(scope="module")
def generated(frame: pl.LazyFrame) -> COREPTemplateBundle:
    return LedgerShimCorepGenerator().generate_from_lazyframe(frame, framework=FRAMEWORK)


def _cell(sheet: pl.DataFrame, row: str, column: str) -> float:
    value = sheet.filter(pl.col("row_ref") == row)[column][0]
    return 0.0 if value is None else float(value)


def test_the_rule_book_ties_the_sub_class_rows_to_sheets() -> None:
    """Adequacy: the family was read, and it names the rows this file is about."""
    by_cell = {(tie.row, tie.column): tie.sheet_codes for tie in TIES}
    assert len(TIES) >= 40, f"only {len(TIES)} ties parsed: the rule text changed shape"
    assert by_cell[("0048", "0010")] == ("0022",)
    assert by_cell[("0050", "0010")] == ("0023", "0024")
    assert by_cell[("0055", "0010")] == ("0011", "0012")
    assert by_cell[("0120", "0010")] == ("0016",)
    assert by_cell[("0130", "0010")] == ("0017",)


def test_the_book_can_tell_the_carriers_apart(frame: pl.LazyFrame) -> None:
    """Adequacy (LESSONS C11). One leg is financial / large with NO multiplier flag,
    one carries the flag WITHOUT being financial / large, and one retail leg is an
    SME whose class name does not say so — or the carriers agree and this file
    proves nothing."""
    legs = frame.select(
        "exposure_reference", "exposure_class", "exposure_subclass", "is_sme", "cp_apply_fi_scalar"
    ).collect()
    fin_large = legs.filter(pl.col("exposure_subclass") == "corporate_financial_large")
    flagged = legs.filter(pl.col("cp_apply_fi_scalar"))
    retail_sme = legs.filter(
        pl.col("is_sme").fill_null(value=False) & pl.col("exposure_class").str.starts_with("retail")
    )
    assert fin_large.height >= 1, "no financial / large leg: row 0048 has nothing to carry"
    assert not fin_large["cp_apply_fi_scalar"].any(), "every financial / large leg is flagged"
    assert flagged.height >= 1, "no leg carries the multiplier flag"
    assert (flagged["exposure_subclass"] != "corporate_financial_large").all(), (
        "every flagged leg is financial / large: the two carriers agree"
    )
    assert retail_sme.height >= 1, "no SME in a retail class: the retail SME rows are 0 = 0"


@pytest.mark.parametrize("tie", TIES, ids=[f"{t.rule_id}-r{t.row}-c{t.column}" for t in TIES])
def test_each_class_row_is_the_total_of_the_sheets_the_bank_ties_it_to(
    generated: COREPTemplateBundle, tie: Tie
) -> None:
    # Arrange
    total = generated.c09_02["TOTAL"]
    sheets = [generated.c08_01[irb_sheets.B31_SHEET_KEYS[code]] for code in tie.sheet_codes]

    # Act
    reported = _cell(total, tie.row, tie.column)
    on_the_sheets = sum(_cell(sheet, "0010", tie.column_08) for sheet in sheets)

    # Assert
    assert on_the_sheets > 0.0, f"sheets {tie.sheet_codes} carry nothing: the tie is 0 = 0"
    message = (
        f"{tie.rule_id}: OF 09.02 r{tie.row} c{tie.column} = {reported}, OF 08.01 sheets "
        f"{tie.sheet_codes} r0010 c{tie.column_08} = {on_the_sheets}"
    )
    if tie.operator == "i=":
        assert reported == pytest.approx(on_the_sheets), message
    else:
        assert reported <= on_the_sheets + 1e-9, message
