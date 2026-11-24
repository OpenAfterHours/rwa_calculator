"""OF 07.00 rows 0330-0360 and OF 09.01 rows 0090-0094: each leg in the Art. 124 limb
the SA dispatcher's real-estate route places it in, and in no other.

Basel 3.1 only. PS1/26 makes regulatory real estate, other real estate and ADC three
mutually exclusive limbs of one class: Art. 124(1)-(3) give each its own risk weights,
Art. 124A(1) makes a regulatory exposure one that "is not an ADC exposure" and whose
property is valued "in accordance with Article 124D" (point (d)), and the Glossary
defines an other real estate exposure as "a real estate exposure that is not a
regulatory real estate exposure or an ADC exposure". PS1/26 Annex II
(``ps1-26-annex-ii-reporting-instructions.pdf`` PAGE_INDEX 89-91 and 139) reports
them on these rows:

- OF 07.00 0330-0344: the regulatory limb (Art. 124F / 124G / 124H / 124I);
  0350-0354: the other limb (Art. 124J(1) / (2) / (3)); 0360: ADC (Art. 124K).
- OF 09.01 0090 is the "Sum of rows 0091 to 0094", each of which has the "Same
  definition as for row 0330 / 0340 / 0350 / 0360 of OF CR SA template".

Each extra leg below reaches a defect on its own (``.claude/LESSONS.md`` C7), every
one a shape the input flags alone used to misplace:

- an attested non-qualifying leg: in a regulatory row AND 0350;
- an ADC leg on commercial property: in 0340 AND 0360, with ``is_qualifying_re`` True
  (what the pipeline gives it) and unset, so the qualification term alone cannot pass;
- an ADC leg that also meets an Art. 124J predicate: attested non-qualifying (in
  0340, 0350 AND 0360), or on a property with no value (in 0340 AND 0360). ADC must
  win over the other limb as well as the regulatory one. Tested other-first, both
  land in 0350 alone, and every partition and twin identity below still holds, so
  only the per-row test sees it;
- a property with no value (``property_type`` set, no LTV): weighted under Art. 124J
  (Art. 124A(1)(d) fails) but reported in 0330;
- a mortgage carrying its own LTV and no ``property_type``: weighted under Art. 124F
  but reported in no limb row of either template;
- the same with an attested non-qualification: in OF 09.01 row 0093 but in no
  OF 07.00 limb row, so the two templates disagreed.

CRR has no rows 0330-0360 and no OF 09.01 rows 0091-0094
(``test_c07_real_estate_rows.py::test_re_rows_absent_crr``).

References:
- PRA PS1/26 Art. 124, 124A, 124J; Glossary "other real estate exposure"
- PRA PS1/26 Annex II OF 07.00 rows 0330-0360; OF 09.01 rows 0090-0094
"""

from __future__ import annotations

from typing import Any

import polars as pl
import pytest

from rwa_calc.reporting.corep.generator import COREPTemplateBundle
from tests.fixtures.recon_ledger import LedgerShimCorepGenerator

#: The two legs every case keeps: one regulatory residential leg whose
#: qualification and ADC flags are UNSET (both read null-safe, so it stays
#: regulatory) and one attested regulatory commercial leg. Both valued.
_BASE_LEGS: tuple[dict[str, Any], ...] = (
    {"ref": "RES_Q", "cls": "residential_mortgage", "ptype": "residential", "ltv": 0.5,
     "amount": 100.0, "qualifying": None, "adc": None, "md": False},
    {"ref": "COMM_Q", "cls": "commercial_mortgage", "ptype": "commercial", "ltv": 0.5,
     "amount": 400.0, "qualifying": True, "adc": False, "md": False},
)  # fmt: skip
_BASE_ROWS: dict[str, float] = {"0330": 100.0, "0331": 100.0, "0340": 400.0}

#: The OF 07.00 real-estate rows each case asserts in full (an unlisted one is 0.0).
_ROWS: tuple[str, ...] = (
    "0330", "0331", "0332", "0340", "0350", "0351", "0352", "0353", "0354", "0360",
)  # fmt: skip

#: case id -> (the extra leg, the rows it adds to ``_BASE_ROWS``).
_CASES: dict[str, tuple[dict[str, Any], dict[str, float]]] = {
    "non_qualifying_residential": (
        {"ref": "RES_NQ", "cls": "residential_mortgage", "ptype": "residential", "ltv": 0.5,
         "amount": 200.0, "qualifying": False, "adc": False, "md": False},
        {"0350": 200.0, "0351": 200.0},
    ),
    "non_qualifying_commercial": (
        {"ref": "COMM_NQ", "cls": "commercial_mortgage", "ptype": "commercial", "ltv": 0.5,
         "amount": 300.0, "qualifying": False, "adc": False, "md": True},
        {"0350": 300.0, "0354": 300.0},
    ),
    "adc_attested_qualifying": (
        {"ref": "ADC_Q", "cls": "commercial_mortgage", "ptype": "commercial", "ltv": 0.5,
         "amount": 800.0, "qualifying": True, "adc": True, "md": False},
        {"0360": 800.0},
    ),
    "adc_unset_qualifying": (
        {"ref": "ADC_U", "cls": "commercial_mortgage", "ptype": "commercial", "ltv": 0.5,
         "amount": 800.0, "qualifying": None, "adc": True, "md": False},
        {"0360": 800.0},
    ),
    # ADC takes precedence over the other limb too: an ADC leg that ALSO meets an
    # Art. 124J predicate (attested non-qualifying, or a property with no value) is
    # still Art. 124K and never 0350 (Glossary: other real estate is "not ... an ADC
    # exposure"). Once P1.292 reads an unset flag as non-qualifying, every ADC leg
    # without one takes the first of these shapes.
    "adc_non_qualifying": (
        {"ref": "ADC_NQ", "cls": "commercial_mortgage", "ptype": "commercial", "ltv": 0.5,
         "amount": 800.0, "qualifying": False, "adc": True, "md": False},
        {"0360": 800.0},
    ),
    "adc_unvalued": (
        {"ref": "ADC_UNVALUED", "cls": "commercial_mortgage", "ptype": "commercial",
         "ltv": None, "amount": 800.0, "qualifying": True, "adc": True, "md": False},
        {"0360": 800.0},
    ),
    # Art. 124A(1)(d): a property with no value is other real estate (Art. 124J(2)).
    "unvalued_property": (
        {"ref": "UNVALUED", "cls": "retail_mortgage", "ptype": "residential", "ltv": None,
         "amount": 250.0, "qualifying": True, "adc": False, "md": False},
        {"0350": 250.0, "0351": 250.0},
    ),
    # Its own LTV and no property_type: the class decides the side (Art. 124F).
    "loan_level_ltv": (
        {"ref": "LOAN_LTV", "cls": "retail_mortgage", "ptype": None, "ltv": 0.71,
         "amount": 250.0, "qualifying": None, "adc": False, "md": False},
        {"0330": 250.0, "0331": 250.0},
    ),
    # Non-qualifying with no property_type: other, on the side the Art. 124J weight
    # reads it (``is_residential_property``: null is commercial, Art. 124J(3)).
    "non_qualifying_no_property_type": (
        {"ref": "NQ_NO_TYPE", "cls": "retail_mortgage", "ptype": None, "ltv": 0.71,
         "amount": 250.0, "qualifying": False, "adc": False, "md": False},
        {"0350": 250.0, "0353": 250.0},
    ),
}  # fmt: skip

#: OF 07.00 limb row -> its OF 09.01 twin ("Same definition as for row ...").
_C09_TWIN: dict[str, str] = {"0330": "0091", "0340": "0092", "0350": "0093", "0360": "0094"}

#: (OF 09.01 column, OF 07.00 column) pairs the Bank ties (boe_b0978-b0989).
_TIED_COLUMNS: tuple[tuple[str, str], ...] = (("0010", "0010"), ("0075", "0200"), ("0090", "0220"))


def _frame(legs: tuple[dict[str, Any], ...], *, sealed: bool = True) -> pl.LazyFrame:
    """A B31 SA real-estate book in the sealed shape (``LESSONS`` C11(c)).

    ``sealed=False`` drops ``is_qualifying_re``, ``is_adc`` and ``ltv``, the shape no
    pipeline run produces (all three are sealed on the aggregator exit).
    """
    n = len(legs)
    amounts = [leg["amount"] for leg in legs]
    data: dict[str, list[Any]] = {
        "exposure_reference": [leg["ref"] for leg in legs],
        "counterparty_reference": [f"CP_{leg['ref']}" for leg in legs],
        "approach_applied": ["standardised"] * n,
        "exposure_class": [leg["cls"] for leg in legs],
        "exposure_type": ["loan"] * n,
        "drawn_amount": amounts,
        "undrawn_amount": [0.0] * n,
        "ead_gross": amounts,
        "ead_final": amounts,
        "risk_weight": [1.0] * n,
        "rwa_final": amounts,
        "scra_provision_amount": [0.0] * n,
        "gcra_provision_amount": [0.0] * n,
        "collateral_adjusted_value": [0.0] * n,
        "guaranteed_portion": [0.0] * n,
        "sa_cqs": [None] * n,
        "cp_country_code": ["GB"] * n,
        "default_status": [False] * n,
        "property_type": [leg["ptype"] for leg in legs],
        "materially_dependent_on_property": [leg["md"] for leg in legs],
        "is_sme": [False] * n,
        "sme_supporting_factor_eligible": [False] * n,
    }
    schema: dict[str, Any] = {"sa_cqs": pl.Int8, "property_type": pl.String}
    if sealed:
        data["is_qualifying_re"] = [leg["qualifying"] for leg in legs]
        data["is_adc"] = [leg["adc"] for leg in legs]
        data["ltv"] = [leg["ltv"] for leg in legs]
        schema |= {"is_qualifying_re": pl.Boolean, "is_adc": pl.Boolean, "ltv": pl.Float64}
    return pl.LazyFrame(data, schema_overrides=schema)


def _bundle(case: str) -> COREPTemplateBundle:
    extra, _added = _CASES[case]
    frame = _frame((*_BASE_LEGS, extra))
    return LedgerShimCorepGenerator().generate_from_lazyframe(frame, framework="BASEL_3_1")


def _cell(sheet: pl.DataFrame, row_ref: str, col: str) -> float:
    """A cell's figure, an empty cell read as 0.0 for the partition sums."""
    row = sheet.filter(pl.col("row_ref") == row_ref)
    assert row.height == 1, f"row {row_ref} is not emitted"
    value = row[col][0]
    return 0.0 if value is None else float(value)


@pytest.mark.parametrize("case", sorted(_CASES))
def test_the_case_holds_a_leg_the_input_flags_alone_misplace(case: str) -> None:
    """Adequacy (``LESSONS`` C11): each extra leg is a shape a reading of
    ``property_type`` and ``is_qualifying_re`` alone put in the wrong row or in
    none. Without that the cases below prove nothing."""
    extra, _added = _CASES[case]

    attested_out = extra["qualifying"] is False or extra["adc"] is True
    unvalued = extra["ptype"] is not None and extra["ltv"] is None
    untyped = extra["ptype"] is None and extra["ltv"] is not None

    assert attested_out or unvalued or untyped


@pytest.mark.parametrize("case", sorted(_CASES))
def test_of_07_00_reports_each_leg_in_its_limb_and_side(case: str) -> None:
    """Rows 0330-0360 hold exactly their own limb and property side (col 0200)."""
    _extra, added = _CASES[case]
    expected = {ref: _BASE_ROWS.get(ref, 0.0) + added.get(ref, 0.0) for ref in _ROWS}
    sheet = _bundle(case).c07_00["real_estate"]

    reported = {ref: _cell(sheet, ref, "0200") for ref in _ROWS}

    assert reported == pytest.approx(expected)


@pytest.mark.parametrize("case", sorted(_CASES))
def test_of_07_00_limb_rows_foot_to_the_real_estate_sheet_total(case: str) -> None:
    """0330 + 0340 + 0350 + 0360 = row 0010, in cols 0010 and 0200."""
    sheet = _bundle(case).c07_00["real_estate"]

    for col in ("0010", "0200"):
        limbs = sum(_cell(sheet, ref, col) for ref in _C09_TWIN)
        assert limbs == pytest.approx(_cell(sheet, "0010", col)), col


@pytest.mark.parametrize("case", sorted(_CASES))
def test_of_07_00_regulatory_and_other_rows_foot_to_their_published_children(case: str) -> None:
    """Annex II: 0330 = 0331 + 0332 and 0350 = 0351 + 0352 + 0353 + 0354.

    (0340 = 0341 + 0342 is not asserted here: no leg is an SME, and 0341's SME
    exclusion is P1.378.)
    """
    sheet = _bundle(case).c07_00["real_estate"]

    def total(*refs: str) -> float:
        return sum(_cell(sheet, ref, "0200") for ref in refs)

    assert total("0330") == pytest.approx(total("0331", "0332"))
    assert total("0350") == pytest.approx(total("0351", "0352", "0353", "0354"))


@pytest.mark.parametrize("case", sorted(_CASES))
def test_of_09_01_sub_rows_equal_their_of_07_00_twins(case: str) -> None:
    """OF 09.01 0091-0094 have the "Same definition as" OF 07.00 0330-0360."""
    bundle = _bundle(case)
    c07 = bundle.c07_00["real_estate"]
    c09 = bundle.c09_01["TOTAL"]

    for c07_ref, c09_ref in _C09_TWIN.items():
        for c09_col, c07_col in _TIED_COLUMNS:
            assert _cell(c09, c09_ref, c09_col) == pytest.approx(_cell(c07, c07_ref, c07_col)), (
                f"OF 09.01 r{c09_ref} c{c09_col} vs OF 07.00 r{c07_ref} c{c07_col}"
            )


@pytest.mark.parametrize("case", sorted(_CASES))
def test_of_09_01_row_0090_is_the_sum_of_rows_0091_to_0094(case: str) -> None:
    """Annex II OF 09.01 row 0090: "Sum of rows 0091 to 0094"."""
    c09 = _bundle(case).c09_01["TOTAL"]

    for col in ("0010", "0075"):
        parts = sum(_cell(c09, ref, col) for ref in ("0091", "0092", "0093", "0094"))
        assert parts == pytest.approx(_cell(c09, "0090", col)), col


def test_a_frame_sealing_no_route_inputs_reports_no_limb_row() -> None:
    """The ABSENT path (``LESSONS`` B1), distinct from the null one above.

    A frame with no ``is_qualifying_re`` / ``is_adc`` / ``ltv`` cannot evaluate the
    dispatcher's real-estate route, so every limb row renders empty rather than
    guessing; the class totals still carry the book. Production never takes this
    path: all three are sealed on the aggregator exit.
    """
    extra, _added = _CASES["non_qualifying_residential"]
    frame = _frame((*_BASE_LEGS, extra), sealed=False)
    bundle = LedgerShimCorepGenerator().generate_from_lazyframe(frame, framework="BASEL_3_1")
    c07 = bundle.c07_00["real_estate"]
    c09 = bundle.c09_01["TOTAL"]

    assert _cell(c07, "0010", "0200") == pytest.approx(700.0)
    assert _cell(c09, "0090", "0075") == pytest.approx(700.0)
    assert [_cell(c07, ref, "0200") for ref in _C09_TWIN] == [0.0] * 4
    assert [_cell(c09, ref, "0075") for ref in _C09_TWIN.values()] == [0.0] * 4
