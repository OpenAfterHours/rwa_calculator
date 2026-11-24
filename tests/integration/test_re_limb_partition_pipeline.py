"""
Integration: through ``PipelineOrchestrator``, OF 07.00 rows 0330-0360 and OF 09.01
rows 0091-0094 report each real-estate leg in the Art. 124 limb the SA dispatcher's
real-estate route places it in, and in no other.

The unit tests (``tests/unit/reporting/corep/test_re_limb_partition.py``) build the
sealed frame by hand. This runs the shapes that reach the defect through the real
pipeline (``.claude/LESSONS.md`` C11(c)), each from the ``p1_140`` portfolio with its
input changed in memory:

- ``adc_and_non_qualifying``:
  - ``LN_ADC_SPV_001`` is a corporate SPV development loan secured on COMMERCIAL
    property. The engine derives ``is_adc`` True and the aggregator lifts it onto
    the real-estate class (``commercial_mortgage``). It keeps the collateral's
    ``is_qualifying_re`` True. It was reported in 0340 AND 0360.
  - ``LN_ADC_NP_001`` is a natural person's residential mortgage whose property is
    attested NOT to meet Art. 124A (``is_qualifying_re`` False). It was reported in
    0330 AND 0350.
- ``loan_level_ltv``: ``LN_ADC_NP_001`` with no property collateral and its own
  LTV, so ``property_type`` is null. The engine weights it under the Art. 124F loan
  split. It was reported in no limb row of either template.
- ``unvalued_property``: ``LN_ADC_NP_001``'s property with no market value and no
  LTV. Art. 124A(1)(d) ("the value of the property is determined in accordance
  with Article 124D") fails, so the engine weights it under Art. 124J. It was
  reported in 0330 (Art. 124F).
- ``adc_non_qualifying`` and ``adc_unvalued``: ``LN_ADC_SPV_001`` on commercial
  property as above, but ALSO meeting an Art. 124J predicate: its property attested
  non-qualifying (``is_qualifying_re`` False), or with no market value and no LTV.
  The engine weights it under Art. 124K (150%) all the same, since its ADC branch
  comes first. It was reported in 0340, 0360 and (non-qualifying) 0350. These pin
  that ADC takes precedence over the other limb, not just the regulatory one:
  checked other-first, the leg lands in 0350 alone and every partition and twin
  identity still holds. Once P1.292 reads an unset qualifying flag as False, every
  ADC leg without one has the first shape.

PS1/26 Art. 124A(1): a regulatory real estate exposure "is not an ADC exposure".
Glossary: an other real estate exposure is "not a regulatory real estate exposure or
an ADC exposure". Annex II OF 09.01 row 0090 is the "Sum of rows 0091 to 0094",
each with the "Same definition as" OF 07.00 0330 / 0340 / 0350 / 0360.

References:
- PRA PS1/26 Art. 124, 124A(1), 124F, 124J, 124K; Glossary
- PRA PS1/26 Annex II OF 07.00 rows 0330-0360; OF 09.01 rows 0090-0094
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from functools import cache
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.schemas import FACILITY_SCHEMA, LOAN_SCHEMA
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.loader import ensure_columns
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator, COREPTemplateBundle
from tests.fixtures.raw_bundle import make_raw_bundle

_FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "p1_140"

#: The two legs and the collateral each is secured by.
_ADC_LOAN, _ADC_COLLATERAL, _ADC_EAD = "LN_ADC_SPV_001", "COL_ADC_SPV_001", 10_000_000.0
_NP_LOAN, _NP_COLLATERAL, _NP_EAD = "LN_ADC_NP_001", "COL_ADC_NP_001", 250_000.0

#: OF 07.00 limb row -> its OF 09.01 twin ("Same definition as for row ...").
_C09_TWIN: dict[str, str] = {"0330": "0091", "0340": "0092", "0350": "0093", "0360": "0094"}

#: The OF 07.00 real-estate rows each shape asserts in full (an unlisted one is 0.0).
_ROWS: tuple[str, ...] = (
    "0330", "0331", "0332", "0340", "0341", "0342", "0350", "0351", "0352", "0353",
    "0354", "0360",
)  # fmt: skip


def _on(reference: str, value: object, column: str, dtype: pl.DataType) -> pl.Expr:
    """``column`` set to ``value`` on collateral ``reference`` alone."""
    return (
        pl.when(pl.col("collateral_reference") == reference)
        .then(pl.lit(value, dtype=dtype))
        .otherwise(pl.col(column))
        .alias(column)
    )


def _adc_and_non_qualifying(collateral: pl.LazyFrame) -> pl.LazyFrame:
    return collateral.with_columns(
        _on(_ADC_COLLATERAL, "commercial", "property_type", pl.String()),
        _on(_NP_COLLATERAL, False, "is_qualifying_re", pl.Boolean()),
    )


def _without_np_property(collateral: pl.LazyFrame) -> pl.LazyFrame:
    return collateral.filter(pl.col("collateral_reference") != _NP_COLLATERAL)


def _unvalued_np_property(collateral: pl.LazyFrame) -> pl.LazyFrame:
    return collateral.with_columns(
        _on(_NP_COLLATERAL, None, "market_value", pl.Float64()),
        _on(_NP_COLLATERAL, None, "property_ltv", pl.Float64()),
    )


def _adc_non_qualifying(collateral: pl.LazyFrame) -> pl.LazyFrame:
    return collateral.with_columns(
        _on(_ADC_COLLATERAL, "commercial", "property_type", pl.String()),
        _on(_ADC_COLLATERAL, False, "is_qualifying_re", pl.Boolean()),
    )


def _adc_unvalued(collateral: pl.LazyFrame) -> pl.LazyFrame:
    return collateral.with_columns(
        _on(_ADC_COLLATERAL, "commercial", "property_type", pl.String()),
        _on(_ADC_COLLATERAL, None, "market_value", pl.Float64()),
        _on(_ADC_COLLATERAL, None, "property_ltv", pl.Float64()),
    )


#: The ADC shapes whose leg also meets an Art. 124J predicate.
_ADC_AND_OTHER_SHAPES: tuple[str, ...] = ("adc_non_qualifying", "adc_unvalued")


#: shape -> (the collateral change, the loan-level LTV given LN_ADC_NP_001, the
#: OF 07.00 rows the real-estate sheet must carry).
_SHAPES: dict[
    str, tuple[Callable[[pl.LazyFrame], pl.LazyFrame], float | None, dict[str, float]]
] = {
    "adc_and_non_qualifying": (
        _adc_and_non_qualifying,
        None,
        {"0350": _NP_EAD, "0351": _NP_EAD, "0360": _ADC_EAD},
    ),
    "loan_level_ltv": (_without_np_property, 0.71, {"0330": _NP_EAD, "0331": _NP_EAD}),
    "unvalued_property": (_unvalued_np_property, None, {"0350": _NP_EAD, "0351": _NP_EAD}),
    "adc_non_qualifying": (
        _adc_non_qualifying,
        None,
        {"0330": _NP_EAD, "0331": _NP_EAD, "0360": _ADC_EAD},
    ),
    "adc_unvalued": (_adc_unvalued, None, {"0330": _NP_EAD, "0331": _NP_EAD, "0360": _ADC_EAD}),
}


@cache
def _run(shape: str) -> tuple[pl.DataFrame, COREPTemplateBundle]:
    """The p1_140 portfolio, Basel 3.1 SA, with ``shape``'s change applied."""
    change, loan_ltv, _rows = _SHAPES[shape]
    loans = ensure_columns(pl.scan_parquet(_FIXTURES_DIR / "loan.parquet"), LOAN_SCHEMA)
    if loan_ltv is not None:
        loans = loans.with_columns(
            pl.when(pl.col("loan_reference") == _NP_LOAN)
            .then(pl.lit(loan_ltv))
            .otherwise(pl.col("ltv"))
            .alias("ltv")
        )
    bundle = make_raw_bundle(
        facilities=ensure_columns(
            pl.scan_parquet(_FIXTURES_DIR / "facility.parquet"), FACILITY_SCHEMA
        ),
        loans=loans,
        counterparties=pl.scan_parquet(_FIXTURES_DIR / "counterparty.parquet"),
        facility_mappings=pl.scan_parquet(_FIXTURES_DIR / "facility_mapping.parquet"),
        lending_mappings=pl.scan_parquet(_FIXTURES_DIR / "lending_mapping.parquet"),
        collateral=change(pl.scan_parquet(_FIXTURES_DIR / "collateral.parquet")),
    )
    config = CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 30), permission_mode=PermissionMode.STANDARDISED
    )
    result = PipelineOrchestrator().run_with_data(bundle, config)
    corep = COREPGenerator().generate_from_lazyframe(result.results, framework="BASEL_3_1")
    return result.results.collect(), corep


def _leg(shape: str, reference: str) -> dict[str, object]:
    legs = _run(shape)[0].filter(pl.col("exposure_reference") == reference)
    assert legs.height == 1, f"expected one {reference} leg, got {legs.height}"
    return legs.row(0, named=True)


def _cell(sheet: pl.DataFrame, row_ref: str, col: str) -> float:
    row = sheet.filter(pl.col("row_ref") == row_ref)
    assert row.height == 1, f"row {row_ref} is not emitted"
    value = row[col][0]
    return 0.0 if value is None else float(value)


def test_adc_and_non_qualifying_reaches_both_limbs_of_the_defect() -> None:
    """Adequacy (``LESSONS`` C11): an ADC leg on the real-estate class with a
    commercial property AND a True qualifying flag, and an attested
    non-qualifying residential leg. Without both the tests below prove nothing."""
    adc = _leg("adc_and_non_qualifying", _ADC_LOAN)
    other = _leg("adc_and_non_qualifying", _NP_LOAN)

    assert (adc["is_adc"], adc["property_type"], adc["is_qualifying_re"]) == (
        True,
        "commercial",
        True,
    )
    assert adc["reporting_class_origin"] == "commercial_mortgage"
    assert (other["is_adc"], other["property_type"], other["is_qualifying_re"]) == (
        False,
        "residential",
        False,
    )


def test_loan_level_ltv_is_a_real_estate_leg_with_no_property_type() -> None:
    """Adequacy: no ``property_type``, a real-estate class, and an LTV the engine
    weighted it on. The Art. 124F loan-split carrier is set only where the
    dispatcher's regulatory residential branch priced the leg
    (``with_b31_loan_split_parts``), so it says which limb the weight came from."""
    leg = _leg("loan_level_ltv", _NP_LOAN)

    assert leg["property_type"] is None
    assert leg["reporting_class_origin"] == "retail_mortgage"
    assert leg["ltv"] == pytest.approx(0.71)
    assert leg["sa_loan_split_secured_share"] is not None


def test_unvalued_property_is_weighted_as_other_real_estate() -> None:
    """Adequacy: a residential property attested qualifying, but with no value and
    so no LTV. The engine weights it under Art. 124J(2) at the natural person's
    Art. 124L(a) weight (75%), not under the Art. 124F loan split."""
    leg = _leg("unvalued_property", _NP_LOAN)

    assert (leg["property_type"], leg["is_qualifying_re"], leg["ltv"]) == (
        "residential",
        True,
        None,
    )
    assert leg["reporting_class_origin"] == "retail_mortgage"
    assert leg["sa_loan_split_secured_share"] is None
    assert leg["risk_weight"] == pytest.approx(0.75)


@pytest.mark.parametrize("shape", _ADC_AND_OTHER_SHAPES)
def test_the_adc_leg_also_meets_an_art_124j_predicate_and_is_weighted_as_adc(shape: str) -> None:
    """Adequacy: an ADC leg on the real-estate class with a commercial property that
    the route's other-real-estate predicate ALSO matches (attested non-qualifying,
    or no LTV), weighted at the Art. 124K 150% all the same. Without that the
    precedence test below cannot fail."""
    leg = _leg(shape, _ADC_LOAN)

    assert (leg["is_adc"], leg["property_type"]) == (True, "commercial")
    assert leg["reporting_class_origin"] == "commercial_mortgage"
    assert leg["risk_weight"] == pytest.approx(1.5)
    if shape == "adc_non_qualifying":
        assert leg["is_qualifying_re"] is False
    else:
        assert (leg["is_qualifying_re"], leg["ltv"]) == (True, None)


@pytest.mark.parametrize("shape", _ADC_AND_OTHER_SHAPES)
def test_adc_takes_precedence_over_the_other_real_estate_limb(shape: str) -> None:
    """The ADC leg is in OF 07.00 0360 and OF 09.01 0094 alone: never 0350 / 0093
    (Glossary: other real estate is "not ... an ADC exposure"), and never 0340."""
    corep = _run(shape)[1]
    c07, c09 = corep.c07_00["real_estate"], corep.c09_01["TOTAL"]

    def raw(sheet: pl.DataFrame, row_ref: str, col: str) -> object:
        return sheet.filter(pl.col("row_ref") == row_ref)[col][0]

    for col in ("0010", "0200"):
        assert _cell(c07, "0360", col) == pytest.approx(_ADC_EAD), col
        assert (raw(c07, "0340", col), raw(c07, "0350", col)) == (None, None), col
    assert _cell(c09, "0094", "0010") == pytest.approx(_cell(c07, "0360", "0010"))
    assert (raw(c09, "0092", "0010"), raw(c09, "0093", "0010")) == (None, None)


@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_of_07_00_reports_each_leg_in_its_limb_and_side(shape: str) -> None:
    """0330-0360 on the real-estate sheet (cols 0010 and 0200), and the four limb
    rows sum to row 0010."""
    _change, _ltv, rows = _SHAPES[shape]
    sheet = _run(shape)[1].c07_00["real_estate"]

    for col in ("0010", "0200"):
        reported = {ref: _cell(sheet, ref, col) for ref in _ROWS}
        assert reported == pytest.approx({ref: rows.get(ref, 0.0) for ref in _ROWS}), col
        limbs = sum(reported[ref] for ref in _C09_TWIN)
        assert limbs == pytest.approx(_cell(sheet, "0010", col)), col


@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_of_09_01_sub_rows_equal_their_of_07_00_twins_and_sum_to_row_0090(shape: str) -> None:
    """boe_b0978-b0989 (r0091-r0094 against r0330-r0360) and "Sum of rows 0091 to 0094"."""
    corep = _run(shape)[1]
    c07, c09 = corep.c07_00["real_estate"], corep.c09_01["TOTAL"]

    for c07_ref, c09_ref in _C09_TWIN.items():
        for c09_col, c07_col in (("0010", "0010"), ("0075", "0200"), ("0090", "0220")):
            assert _cell(c09, c09_ref, c09_col) == pytest.approx(_cell(c07, c07_ref, c07_col)), (
                f"OF 09.01 r{c09_ref} c{c09_col} vs OF 07.00 r{c07_ref} c{c07_col}"
            )
    parts = sum(_cell(c09, c09_ref, "0010") for c09_ref in _C09_TWIN.values())
    assert parts == pytest.approx(_cell(c09, "0090", "0010"))
