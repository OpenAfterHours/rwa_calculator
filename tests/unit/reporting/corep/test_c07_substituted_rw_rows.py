"""
C 07.00 / OF 07.00: the risk-weight row of a substituted covered part, per basis.

Pipeline position:
    hand-built sealed-exit frame -> LedgerShimCorepGenerator -> c07_00[sheet]

The rule (PS1/26 Annex II, ps1-26-annex-ii-reporting-instructions.pdf; the C 07.00
text it repeats is the same):

- p.94, rows 0140-0280: "Institutions shall report the information on the
  allocation of risk weights within the respective exposure class".
- p.84, cols 0090 / 0100: "Outflows shall correspond to the covered part of the
  Original Exposure pre-conversion factors that is deducted from the obligor's
  exposure class and subsequently assigned to the protection provider's exposure
  class. That amount shall be considered as an inflow into the protection provider's
  exposure class." ... "Inflows and outflows within the same exposure classes shall
  also be reported."
- p.81, col 0010: the original exposure is reported "without taking into account
  ... the effect of credit risk mitigation techniques".

So cols 0010-0150 of a covered part sit at the OBLIGOR's own risk weight on the
obligor's sheet, and cols 0160-0235 and the col 0100 inflow at the PROVIDER's weight
on the provider's sheet. A same-class substitution therefore puts one leg on ONE
sheet in TWO rows. The cases below pin that, the gate it reads
(``is_guarantee_beneficial``, null-safe, with the obligor's ``pre_crm_risk_weight``
recorded), and how it composes with the other three things that choose a C 07.00
risk-weight row: the Article 133 weight of transitional equity, the two parts of a
loan-split real-estate exposure and the memorandum rows 0300 / 0320.

References:
- src/rwa_calc/reporting/corep/c07_rw_bands.py; kernel/bases.py; kernel/rw_parts.py
- PS1/26 Annex II OF 07.00 cols 0010, 0090-0100 and rows 0140-0280, 0300 / 0320
- EBA Q&A 2014_1636 (C 07.00 col 010 at the obligor class's own weight)
"""

from __future__ import annotations

from typing import Any

import polars as pl
import pytest

from rwa_calc.reporting.corep.templates import (
    C07_00_SA_SHEET_MAP,
    C07_00_TOTAL_SHEET_KEY,
    get_sa_risk_weight_bands,
    get_sa_row_sections,
)
from tests.fixtures.recon_ledger import LedgerShimCorepGenerator

CRR = "CRR"
B31 = "BASEL_3_1"
FRAMEWORKS = (CRR, B31)

CORPORATE = C07_00_SA_SHEET_MAP["corporate"]
INSTITUTION = C07_00_SA_SHEET_MAP["institution"]
IN_DEFAULT = C07_00_SA_SHEET_MAP["defaulted"]
REAL_ESTATE = C07_00_SA_SHEET_MAP["residential_mortgage"]

#: The risk-weight block is the third row section; each of its rows is named by its band.
_RW_SECTION = 2

#: A 1,000 corporate loan, 400 of it covered: the covered and the remaining leg.
_COVERED = 400.0
_REMAINING = 600.0
_OWN_RW = 1.0
_PROVIDER_RW = 0.2


def _band_ref(framework: str, weight: float) -> str:
    """The row a weight is reported in, read off the template's band list (LESSONS B3)."""
    labels = [
        label
        for rung, label in get_sa_risk_weight_bands(framework)
        if round(rung, 4) == round(weight, 4)
    ]
    assert len(labels) == 1, f"{framework}: {weight} is on no published rung"
    refs = [
        row.ref for row in get_sa_row_sections(framework)[_RW_SECTION].rows if row.name == labels[0]
    ]
    assert len(refs) == 1, f"{framework}: band {labels[0]!r} names rows {refs}"
    return refs[0]


def _leg(  # noqa: PLR0913 - one sealed ledger row, every field named
    reference: str,
    amount: float,
    risk_weight: float,
    *,
    obligor_class: str = "corporate",
    post_class: str | None = None,
    pre_crm_risk_weight: float | None = None,
    beneficial: bool | None = False,
    covered: bool = False,
    **extra: Any,
) -> dict[str, Any]:
    """One drawn standardised leg as the aggregator seals it after the guarantee split."""
    post = post_class if post_class is not None else obligor_class
    return {
        "exposure_reference": reference,
        "counterparty_reference": f"CP_{reference}",
        "approach_applied": "standardised",
        "approach_post_crm": "standardised",
        "exposure_type": "loan",
        "exposure_class": obligor_class,
        "exposure_class_post_crm": post,
        "drawn_amount": amount,
        "undrawn_amount": 0.0,
        "ead_final": amount,
        "rwa_final": amount * risk_weight,
        "risk_weight": risk_weight,
        "pre_crm_risk_weight": pre_crm_risk_weight,
        "is_guarantee_beneficial": beneficial,
        "guaranteed_portion": amount if covered else 0.0,
        "protection_type": "guarantee" if covered else None,
        "post_crm_exposure_class_guaranteed": post,
        **extra,
    }


def _covered_loan(provider_class: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """The covered leg (beneficially substituted) and the remaining leg of one loan."""
    return (
        _leg(
            "LOAN__G_PROVIDER",
            _COVERED,
            _PROVIDER_RW,
            post_class=provider_class,
            pre_crm_risk_weight=_OWN_RW,
            beneficial=True,
            covered=True,
        ),
        _leg("LOAN__REM", _REMAINING, _OWN_RW, pre_crm_risk_weight=_OWN_RW),
    )


def _frame(*legs: dict[str, Any]) -> pl.LazyFrame:
    return pl.LazyFrame(
        list(legs),
        schema_overrides={
            "pre_crm_risk_weight": pl.Float64,
            "is_guarantee_beneficial": pl.Boolean,
            "protection_type": pl.String,
        },
    )


def _sheets(results: pl.LazyFrame, framework: str) -> dict[str, pl.DataFrame]:
    return LedgerShimCorepGenerator().generate_from_lazyframe(results, framework=framework).c07_00


def _row(sheets: dict[str, pl.DataFrame], sheet: str, row_ref: str) -> dict[str, Any]:
    assert sheet in sheets, f"sheet {sheet!r} not emitted; got {sorted(sheets)}"
    matched = sheets[sheet].filter(pl.col("row_ref") == row_ref)
    assert matched.height == 1, f"{sheet}: expected one row {row_ref}, got {matched.height}"
    return matched.row(0, named=True)


def _non_null(row: dict[str, Any]) -> dict[str, Any]:
    return {
        ref: value
        for ref, value in row.items()
        if ref not in ("row_ref", "row_name") and value is not None
    }


# ---------------------------------------------------------------------------
# The two bases, one row each
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_cross_class_covered_part_is_original_exposure_at_the_obligors_own_weight(
    framework: str,
) -> None:
    """Cols 0010 / 0040: the WHOLE loan in the obligor's 100% row of the corporate sheet."""
    own, provider = _band_ref(framework, _OWN_RW), _band_ref(framework, _PROVIDER_RW)
    assert own != provider  # adequacy: two weights on two rows

    sheets = _sheets(_frame(*_covered_loan("institution")), framework)

    own_row = _row(sheets, CORPORATE, own)
    assert own_row["0010"] == pytest.approx(_COVERED + _REMAINING)
    assert own_row["0040"] == pytest.approx(_COVERED + _REMAINING)
    assert _non_null(_row(sheets, CORPORATE, provider)) == {}


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_cross_class_covered_part_is_exposure_value_at_the_providers_weight(
    framework: str,
) -> None:
    """CONTROL, green before and after: cols 0150-0220 stay with the provider.

    Its mutation is banding the post-basis cells on the obligor's weight as well.
    """
    sheets = _sheets(_frame(*_covered_loan("institution")), framework)

    arrived = _row(sheets, INSTITUTION, _band_ref(framework, _PROVIDER_RW))
    stayed = _row(sheets, CORPORATE, _band_ref(framework, _OWN_RW))
    assert arrived["0150"] == pytest.approx(_COVERED)
    assert arrived["0200"] == pytest.approx(_COVERED)
    assert arrived["0220"] == pytest.approx(_COVERED * _PROVIDER_RW)
    assert stayed["0150"] == pytest.approx(_REMAINING)
    assert stayed["0200"] == pytest.approx(_REMAINING)
    assert stayed["0220"] == pytest.approx(_REMAINING * _OWN_RW)


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_same_class_substitution_reports_two_rows_on_one_sheet(framework: str) -> None:
    """A corporate cover for a corporate loan: one sheet, the leg in two rows.

    The 100% row holds the whole original exposure and the part that stayed; the 20%
    row holds the covered part's exposure value, reached through the col 0100 inflow.
    """
    own, provider = _band_ref(framework, _OWN_RW), _band_ref(framework, _PROVIDER_RW)

    sheets = _sheets(_frame(*_covered_loan("corporate")), framework)

    own_row = _row(sheets, CORPORATE, own)
    provider_row = _row(sheets, CORPORATE, provider)
    assert own_row["0010"] == pytest.approx(_COVERED + _REMAINING)
    assert own_row["0150"] == pytest.approx(_REMAINING)
    assert own_row["0200"] == pytest.approx(_REMAINING)
    assert provider_row["0010"] == pytest.approx(0.0)
    assert provider_row["0150"] == pytest.approx(_COVERED)
    assert provider_row["0200"] == pytest.approx(_COVERED)
    if framework == CRR:  # OF 07.00 greys col 0100 on the risk-weight rows
        assert provider_row["0100"] == pytest.approx(_COVERED)


# ---------------------------------------------------------------------------
# The gate: only an APPLIED substitution with a recorded own weight moves the row
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_a_leg_with_no_substitution_bands_both_bases_on_its_applied_weight(
    framework: str,
) -> None:
    """``pre_crm_risk_weight`` is taken before the Art. 123B multiplier: read ungated it
    would put a multiplied leg's original exposure in its un-multiplied row.

    CONTROL, green before and after. Its mutation is reading the own weight without
    the ``is_guarantee_beneficial`` gate (observed red).
    """
    leg = _leg("FX", 1_000.0, 1.5, pre_crm_risk_weight=1.0, beneficial=False)

    sheets = _sheets(_frame(leg), framework)

    assert _row(sheets, CORPORATE, _band_ref(framework, 1.5))["0010"] == pytest.approx(1_000.0)
    assert _non_null(_row(sheets, CORPORATE, _band_ref(framework, 1.0))) == {}


@pytest.mark.parametrize("framework", FRAMEWORKS)
@pytest.mark.parametrize(
    ("beneficial", "pre_crm_risk_weight"),
    [(None, _OWN_RW), (True, None)],
    ids=["unknown-benefit", "no-recorded-own-weight"],
)
def test_an_unknown_benefit_or_own_weight_keeps_the_applied_band(
    framework: str, beneficial: bool | None, pre_crm_risk_weight: float | None
) -> None:
    """Null-safe both ways: an unknown benefit is not a substitution, and a missing own
    weight is never banded (it would fall to "Other risk weights").

    CONTROL, green before and after. Its mutations are filling a null benefit True and
    dropping the ``pre_crm_risk_weight`` null guard (each observed red on its own case).
    """
    leg = _leg(
        "COVERED",
        _COVERED,
        _PROVIDER_RW,
        pre_crm_risk_weight=pre_crm_risk_weight,
        beneficial=beneficial,
        covered=True,
    )

    sheets = _sheets(_frame(leg), framework)

    assert _row(sheets, CORPORATE, _band_ref(framework, _PROVIDER_RW))["0010"] == pytest.approx(
        _COVERED
    )


# ---------------------------------------------------------------------------
# Composition with the other three things that choose a risk-weight row
# ---------------------------------------------------------------------------


def test_transitional_equity_keeps_its_article_133_row_on_both_bases() -> None:
    """The Art. 133 weight (``risk_weight_pre_equity_transitional``) still bands an equity
    leg when the frame carries the substitution columns: no equity leg is substituted,
    so its flag is null and both bases read the Art. 133 weight (row 0250, 250%).

    CONTROL, green before and after. Its mutation is taking the origin band off the
    bare ``risk_weight`` (observed red: the 1,000 falls to "Other risk weights").
    """
    equity = _leg(
        "EQ",
        1_000.0,
        1.6,
        obligor_class="equity",
        risk_weight_pre_equity_transitional=2.5,
        equity_transitional_approach="sa_transitional",
        beneficial=None,
    )
    frame = _frame(equity, *_covered_loan("institution"))

    sheets = _sheets(frame, B31)

    article_133 = _row(sheets, "equity", _band_ref(B31, 2.5))
    assert article_133["0010"] == pytest.approx(1_000.0)
    assert article_133["0200"] == pytest.approx(1_000.0)
    assert article_133["0220"] == pytest.approx(1_600.0)


def test_memorandum_rows_report_a_covered_default_at_the_obligors_own_weight() -> None:
    """Rows 0300 / 0320 are the "in default" class's 100% / 150% rows split by the class
    before default (``c07_sheet_scope``), so they band per basis like the rows they repeat:
    the covered part's original exposure at the Art. 127 150%, its exposure value gone to
    the provider. The Total's row 0320 is then the in-default sheet's 150% row."""
    defaulted = {
        "exposure_class_applied": "defaulted",
        "reporting_class_pre_default": "corporate",
        "is_defaulted": True,
    }
    covered = _leg(
        "D__G_INST",
        _COVERED,
        _PROVIDER_RW,
        post_class="institution",
        pre_crm_risk_weight=1.5,
        beneficial=True,
        covered=True,
        **defaulted,
    )
    remaining = _leg(
        "D__REM", _REMAINING, 1.5, post_class="defaulted", pre_crm_risk_weight=1.5, **defaulted
    )

    sheets = _sheets(_frame(covered, remaining), B31)

    memo = _row(sheets, CORPORATE, "0320")
    assert memo["0010"] == pytest.approx(_COVERED + _REMAINING)
    assert memo["0200"] == pytest.approx(_REMAINING)
    in_default = _row(sheets, IN_DEFAULT, _band_ref(B31, 1.5))
    total = _row(sheets, C07_00_TOTAL_SHEET_KEY, "0320")
    assert total["0010"] == pytest.approx(in_default["0010"])
    assert total["0200"] == pytest.approx(in_default["0200"])


#: A 400,000 natural-person mortgage at 60% LTV: 55/60 of it at 20%, the rest at 75%.
_SHARE = 0.55 / 0.60
_BLEND = 0.20 * _SHARE + 0.75 * (1.0 - _SHARE)
_LOAN_SPLIT = {
    "sa_loan_split_secured_share": _SHARE,
    "sa_loan_split_secured_rw": 0.20,
    "sa_loan_split_residual_rw": 0.75,
}


def test_a_covered_loan_split_leg_is_reported_in_its_two_parts_on_the_origin_basis() -> None:
    """Annex II p.94: a loan-split exposure "shall be reported in two parts". The covered
    leg's own weight is the blend, so its original exposure goes to the 20% and 75% rows
    of the real-estate sheet, never to "Other risk weights" (``boe_b0445``), and its
    exposure value stays whole at the provider's 0% on the sovereign sheet."""
    covered = _leg(
        "RRE__G_CGCB",
        100_000.0,
        0.0,
        obligor_class="residential_mortgage",
        post_class="central_govt_central_bank",
        pre_crm_risk_weight=_BLEND,
        beneficial=True,
        covered=True,
        **_LOAN_SPLIT,
    )

    sheets = _sheets(_frame(covered), B31)

    secured = _row(sheets, REAL_ESTATE, _band_ref(B31, 0.20))
    residual = _row(sheets, REAL_ESTATE, _band_ref(B31, 0.75))
    assert secured["0010"] == pytest.approx(100_000.0 * _SHARE)
    assert residual["0010"] == pytest.approx(100_000.0 * (1.0 - _SHARE))
    assert _non_null(_row(sheets, REAL_ESTATE, "0280")) == {}
    sovereign = _row(sheets, C07_00_SA_SHEET_MAP["central_govt_central_bank"], _band_ref(B31, 0.0))
    assert sovereign["0200"] == pytest.approx(100_000.0)
