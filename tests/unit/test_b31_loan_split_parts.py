"""
Unit tests: the Basel 3.1 SA dispatcher records the two parts of a loan-split weight.

PS1/26 Art. 124F(1) (residential) and Art. 124H(1) (commercial, natural person or
SME), ps126app1.pdf p.55-56: "(a) the part of the exposure up to 55% of the value
of the property shall be assigned a risk weight of 20%" (60% commercial) "and (b)
the risk weight of the counterparty shall be applied to the residual part of the
exposure, if any, in accordance with Article 124L". The engine prices such a row
with ONE exposure-weighted weight; OF 07.00 needs the two parts (PS1/26 Annex II
p.94: such exposures "shall be reported in two parts, against the risk weight
applied to the portion up to 55% of the value of the property, and against the
portion above 55% of the value of the property (if applicable)").

So ``apply_risk_weights`` writes three carriers, non-null ONLY where the row's
weight IS that two-part weight:

- ``sa_loan_split_secured_share`` — the share of the exposure up to the cap
- ``sa_loan_split_secured_rw`` — Art. 124F(1)(a) / 124H(1)(a)
- ``sa_loan_split_residual_rw`` — the Art. 124L counterparty weight

Every leg that takes another branch (ADC, Art. 124J non-qualifying, income-
producing, Art. 124H(3) other counterparty, a loan short of the cap, an earlier
dispatcher branch such as subordinated debt, or a non-real-estate row whose weight
happens to equal a blend) carries nulls. The risk weight itself must not move on
any row. A later step that re-weights a carrying row (Art. 127) leaves the
carriers stale, and the OF 07.00 reader keeps that row whole.

References:
- PS1/26 Art. 124F, 124H, 124J, 124K, 124L (ps126app1.pdf pp.55-58)
- PS1/26 Annex II OF 07.00 rows 0140-0280 (p.94)
"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.sa.risk_weights import apply_risk_weights
from rwa_calc.reporting.kernel.rw_parts import split_risk_weight_parts

_SHARE = "sa_loan_split_secured_share"
_SECURED_RW = "sa_loan_split_secured_rw"
_RESIDUAL_RW = "sa_loan_split_residual_rw"
_CARRIERS = (_SHARE, _SECURED_RW, _RESIDUAL_RW)

#: A natural-person residential mortgage, the baseline every case varies.
_BASE: dict[str, Any] = {
    "ead_final": 400_000.0,
    "exposure_class": "retail_mortgage",
    "cqs": None,
    "ltv": 0.60,
    "prior_charge_ltv": 0.0,
    "property_type": "residential",
    "cp_is_natural_person": True,
    "is_sme": False,
    "qualifies_as_retail": True,
    "has_income_cover": False,
    "is_adc": False,
    "is_qualifying_re": True,
    "cp_entity_type": "individual",
}

#: (reference, overrides, expected risk weight, expected carriers or None).
#: Weights are hand calculations from the article text, not engine read-backs.
_CASES: list[tuple[str, dict[str, Any], float, tuple[float, float, float] | None]] = [
    # Art. 124F(1): 0.55 / 0.60 at 20%, the rest at Art. 124L(1)(a) 75%.
    ("RRE-60", {}, 0.20 * 0.55 / 0.60 + 0.75 * 0.05 / 0.60, (0.55 / 0.60, 0.20, 0.75)),
    # Short of the cap: the whole loan is the 20% part; nothing to split.
    ("RRE-50", {"ltv": 0.50}, 0.20, None),
    # Art. 124F(2)(a): a prior charge of 10% of value lowers the cap to 45%.
    ("RRE-JUNIOR", {"prior_charge_ltv": 0.10}, 0.20 * 0.75 + 0.75 * 0.25, (0.75, 0.20, 0.75)),
    # Art. 124H(1): SME commercial, 0.55 / 0.80 at 60%, the rest at Art. 124L(1)(c) 85%.
    (
        "CRE-SME",
        {
            "exposure_class": "commercial_mortgage",
            "property_type": "commercial",
            "ltv": 0.80,
            "cp_is_natural_person": False,
            "is_sme": True,
            "qualifies_as_retail": False,
            "cp_entity_type": "corporate",
        },
        0.60 * 0.6875 + 0.85 * 0.3125,
        (0.6875, 0.60, 0.85),
    ),
]

#: Rows whose weight is NOT a two-part weight: carriers must be null.
_NOT_TWO_PART: list[tuple[str, dict[str, Any]]] = [
    # Art. 124H(3): a non-SME corporate is weighted max(60%, min(cp, 124I)), whole.
    (
        "CRE-CORP",
        {
            "exposure_class": "commercial_mortgage",
            "property_type": "commercial",
            "ltv": 0.80,
            "cp_is_natural_person": False,
            "is_sme": False,
            "qualifies_as_retail": False,
            "cp_entity_type": "corporate",
        },
    ),
    # Art. 124G: materially dependent residential, Table 6B, whole.
    ("RRE-INCOME", {"has_income_cover": True}),
    # Art. 124K: ADC, whole.
    ("ADC", {"is_adc": True}),
    # Art. 124J: fails Art. 124A, whole.
    ("NON-QUALIFYING", {"is_qualifying_re": False}),
    # Art. 112 Table A2 priority 3 ahead of real estate: subordinated debt to an SME,
    # secured on commercial property, takes the Art. 133 150% flat. The route's own
    # predicates DO reach the Art. 124H(1) split here (SME, commercial, 0 < share < 1);
    # only the ``risk_weight == blend`` gate sees that an earlier branch priced it.
    (
        "CRE-SUB-DEBT",
        {
            "exposure_class": "corporate",
            "property_type": "commercial",
            "ltv": 0.80,
            "cp_is_natural_person": False,
            "is_sme": True,
            "qualifies_as_retail": False,
            "cp_entity_type": "corporate",
            "seniority": "subordinated",
        },
    ),
    # Measured false positives of an equality-only detector: 20% non-real-estate rows.
    (
        "COVERED-BOND-20",
        {
            "exposure_class": "covered_bond",
            "cqs": 2,
            "ltv": None,
            "property_type": None,
            "cp_is_natural_person": False,
            "qualifies_as_retail": False,
            "cp_entity_type": "institution",
        },
    ),
    (
        "MDB-20",
        {
            "exposure_class": "mdb",
            "cqs": 1,
            "ltv": None,
            "property_type": None,
            "cp_is_natural_person": False,
            "qualifies_as_retail": False,
            "cp_entity_type": "mdb",
        },
    ),
]


def _frame(rows: list[tuple[str, dict[str, Any]]]) -> pl.LazyFrame:
    records = [{"exposure_reference": ref, **_BASE, **overrides} for ref, overrides in rows]
    return pl.DataFrame(
        records,
        schema_overrides={"cqs": pl.Int8, "ltv": pl.Float64, "property_type": pl.String},
    ).lazy()


def _weigh(config: CalculationConfig) -> pl.DataFrame:
    rows = [(ref, overrides) for ref, overrides, _rw, _parts in _CASES] + _NOT_TWO_PART
    return apply_risk_weights(_frame(rows), config).collect()


@pytest.fixture(scope="module")
def b31_weighted() -> pl.DataFrame:
    return _weigh(CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30)))


def _row(frame: pl.DataFrame, reference: str) -> dict[str, Any]:
    matched = frame.filter(pl.col("exposure_reference") == reference)
    assert matched.height == 1, reference
    return matched.row(0, named=True)


@pytest.mark.parametrize(("reference", "overrides", "weight", "parts"), _CASES)
def test_the_risk_weight_is_the_articles_weight(
    b31_weighted: pl.DataFrame,
    reference: str,
    overrides: dict[str, Any],
    weight: float,
    parts: tuple[float, float, float] | None,
) -> None:
    """The carrier is a record of the weight, never a change to it."""
    assert _row(b31_weighted, reference)["risk_weight"] == pytest.approx(weight, abs=1e-12)


@pytest.mark.parametrize(
    ("reference", "overrides", "weight", "parts"),
    [case for case in _CASES if case[3] is not None],
)
def test_a_two_part_weight_records_its_parts(
    b31_weighted: pl.DataFrame,
    reference: str,
    overrides: dict[str, Any],
    weight: float,
    parts: tuple[float, float, float],
) -> None:
    row = _row(b31_weighted, reference)
    share, secured_rw, residual_rw = parts

    assert row[_SHARE] == pytest.approx(share, abs=1e-12)
    assert row[_SECURED_RW] == pytest.approx(secured_rw, abs=1e-12)
    assert row[_RESIDUAL_RW] == pytest.approx(residual_rw, abs=1e-12)
    # The parts reproduce the weight exactly: what reporting splits foots to the RWEA.
    blend = row[_SECURED_RW] * row[_SHARE] + row[_RESIDUAL_RW] * (1.0 - row[_SHARE])
    assert blend == row["risk_weight"]


@pytest.mark.parametrize("reference", ["RRE-50", *(ref for ref, _ in _NOT_TWO_PART)])
def test_a_weight_that_is_not_two_part_records_nothing(
    b31_weighted: pl.DataFrame, reference: str
) -> None:
    row = _row(b31_weighted, reference)

    assert [row[column] for column in _CARRIERS] == [None, None, None]


def test_the_controls_take_other_weights_than_a_two_part_one(b31_weighted: pl.DataFrame) -> None:
    """Adequacy (LESSONS C11): each null case reaches a branch of its own.

    The two 20% non-real-estate rows are the shape an equality-only detector
    tagged (their weight equals a blend at the default 100% LTV); the class
    predicates are what keep them out, so they must really be 20%.
    """
    assert _row(b31_weighted, "COVERED-BOND-20")["risk_weight"] == pytest.approx(0.20)
    assert _row(b31_weighted, "MDB-20")["risk_weight"] == pytest.approx(0.20)
    # Priced by the earlier sub-debt branch, not the Art. 124H(1) blend it would also reach.
    assert _row(b31_weighted, "CRE-SUB-DEBT")["risk_weight"] == pytest.approx(1.50)
    two_part = _row(b31_weighted, "RRE-60")["risk_weight"]
    for reference in ("CRE-CORP", "RRE-INCOME", "ADC", "NON-QUALIFYING"):
        assert _row(b31_weighted, reference)["risk_weight"] != pytest.approx(two_part), reference


def test_a_defaulted_mortgage_is_reported_whole_at_its_article_127_weight() -> None:
    """Art. 127 re-weights the row AFTER the dispatcher recorded its two parts.

    PS1/26 Art. 127(3): a defaulted residential exposure not materially dependent on
    the property's cash flows takes 100% on the whole exposure. The carriers the
    dispatcher wrote no longer describe that weight, so the OF 07.00 reader must keep
    the row whole: splitting it would report a 100% loan as 20% / 75% parts.
    """
    defaulted = _frame([("RRE-60-DEFAULTED", {"is_defaulted": True})])
    config = CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))

    weighted = apply_risk_weights(defaulted, config).collect()
    reported = split_risk_weight_parts(
        weighted, exposure_cols=("ead_final",), rwea_cols=("rwa_final",)
    )

    assert weighted["risk_weight"].to_list() == [pytest.approx(1.0)]
    assert reported.to_dicts() == weighted.to_dicts()


def test_crr_writes_no_carrier() -> None:
    """CRR Art. 125 / 126 are not PS1/26 loan splitting; the dispatcher never records one."""
    weighted = _weigh(CalculationConfig.crr(reporting_date=date(2026, 6, 30)))

    assert not set(_CARRIERS) & set(weighted.columns)
