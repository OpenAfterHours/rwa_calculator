"""TR-02: the Art. 166A(5) purchased-receivables CCF is an IRB rule, and it is final.

PRA PS1/26 Art. 166A(5), second subparagraph (Credit Risk: Internal Ratings Based
Approach (CRR) Part, Basel 3.1), verbatim:

    "An institution shall, for undrawn purchase commitments for revolving purchased
    receivables, calculate the exposure value using a conversion factor of 40%,
    except where such commitments meet the criteria set out in point 7 of Column A
    of Table A1 of paragraph 1 of Credit Risk Standardised Approach (CRR) Part
    Article 111, in which case the conversion factor shall be 10%."

Art. 166A(1) makes 166A the general provision for every IRB route ("in accordance
with Article 166C where it is using the Foundation IRB Approach or the Slotting
Approach, and in accordance with Article 166D where it is using the Advanced IRB
Approach"), so the factor binds F-IRB, slotting and A-IRB alike, and "shall ...
40%" leaves no own-estimate limb.

The Standardised Approach has no such rule. Its only source is Art. 111 Table A1,
where Row 2(a) gives 100% to "transactions with recourse (including factoring and
invoice discount facilities)" and Row 5 gives 40% to "any other commitment that is
not subject to a conversion factor of 10%, 50% or 100%". Before the fix the engine
wrote the 40% onto the SA carrier too, so an SA factoring line booked FRC (100%)
took 40%, and an A-IRB row used the overridden 40% to open the own-estimate limb.

Rescoped by the verifier: a flagged SA row with a BLANK risk_type is 40% with or
without the flag (Row 5 residual for a commitment), so it is left as it is - not
every revolving purchase commitment is a transaction "with recourse".

CRR is untouched: CRR Art. 166(8)(c) gives a revolving purchased-receivables UCC 0%
through the LR bucket, and the flag remains a no-op.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.ccf import CCFCalculator
from rwa_calc.rulebook.resolve import resolve

_B31 = CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))
_CRR = CalculationConfig.crr(reporting_date=date(2026, 6, 30))
_NOMINAL = 1_000_000.0


def _row(
    *,
    approach: str,
    risk_type: str | None,
    flagged: bool = True,
    is_revolving: bool = True,
    ccf_modelled: float | None = None,
) -> pl.LazyFrame:
    return pl.DataFrame(
        {
            "exposure_reference": ["PR1"],
            "drawn_amount": [0.0],
            "nominal_amount": [_NOMINAL],
            "risk_type": [risk_type],
            "approach": [approach],
            "ccf_modelled": [ccf_modelled],
            "is_revolving": [is_revolving],
            "is_obs_commitment": [True],
            "is_purchased_receivable_commitment": [flagged],
        },
        schema_overrides={"risk_type": pl.Utf8, "ccf_modelled": pl.Float64},
    ).lazy()


def _ccf(frame: pl.LazyFrame, config: CalculationConfig) -> float:
    return CCFCalculator().apply_ccf(frame, config).collect()["ccf"][0]


@pytest.mark.parametrize(
    ("risk_type", "expected"),
    [
        pytest.param("FRC", 1.00, id="FRC-row-2a-factoring-with-recourse"),
        pytest.param("FR", 1.00, id="FR-row-1"),
        pytest.param("MR", 0.50, id="MR-row-4"),
        pytest.param("OC", 0.40, id="OC-row-5"),
        pytest.param("LR", 0.10, id="LR-row-7"),
        pytest.param(None, 0.40, id="blank-commitment-row-5-residual"),
    ],
)
def test_b31_sa_row_keeps_its_table_a1_bucket(risk_type: str | None, expected: float) -> None:
    """SA rows ignore the IRB-only flag; before the fix FRC/FR/MR all became 0.40."""
    # Arrange
    frame = _row(approach="standardised", risk_type=risk_type)

    # Act / Assert
    assert _ccf(frame, _B31) == pytest.approx(expected)


@pytest.mark.parametrize("approach", ["foundation_irb", "slotting"])
@pytest.mark.parametrize(
    ("risk_type", "expected"),
    [("FRC", 0.40), ("MR", 0.40), ("OC", 0.40), ("LR", 0.10)],
)
def test_b31_irb_row_takes_the_166a5_factor(approach: str, risk_type: str, expected: float) -> None:
    """F-IRB and slotting: 40%, or 10% for a Row 7 UCC commitment."""
    # Arrange
    frame = _row(approach=approach, risk_type=risk_type)

    # Act / Assert
    assert _ccf(frame, _B31) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("risk_type", "modelled", "expected"),
    [
        pytest.param("FRC", 0.25, 0.40, id="FRC-own-estimate-below"),
        pytest.param("OC", 0.25, 0.40, id="OC-own-estimate-below"),
        pytest.param("OC", 0.60, 0.40, id="OC-own-estimate-above"),
        pytest.param("LR", None, 0.10, id="LR-no-estimate"),
    ],
)
def test_b31_airb_row_takes_the_166a5_factor_not_an_own_estimate(
    risk_type: str, modelled: float | None, expected: float
) -> None:
    """A-IRB: 'shall ... 40%' - the own-estimate limb is closed (before: 0.25)."""
    # Arrange
    frame = _row(approach="advanced_irb", risk_type=risk_type, ccf_modelled=modelled)

    # Act / Assert
    assert _ccf(frame, _B31) == pytest.approx(expected)


def test_b31_unflagged_airb_revolving_commitment_keeps_its_own_estimate() -> None:
    """Control: without the flag the ordinary Art. 166D(1)(a) limb is unchanged."""
    # Arrange
    frame = _row(approach="advanced_irb", risk_type="OC", flagged=False, ccf_modelled=0.25)

    # Act / Assert — max(0.25, 0.5 x 0.40) = 0.25
    assert _ccf(frame, _B31) == pytest.approx(0.25)


def test_b31_non_revolving_flagged_firb_row_is_not_overridden() -> None:
    """166A(5) names REVOLVING purchased receivables; FRC stays 100% otherwise."""
    # Arrange
    frame = _row(approach="foundation_irb", risk_type="FRC", is_revolving=False)

    # Act / Assert
    assert _ccf(frame, _B31) == pytest.approx(1.00)


@pytest.mark.parametrize(
    ("approach", "risk_type", "expected"),
    [
        pytest.param("standardised", "FRC", 1.00, id="SA-FRC-annex-I-1e"),
        pytest.param("foundation_irb", "LR", 0.00, id="FIRB-LR-166-8-c"),
        pytest.param("foundation_irb", "OC", 0.75, id="FIRB-OC-166-8-d"),
    ],
)
def test_crr_flag_is_a_no_op(approach: str, risk_type: str, expected: float) -> None:
    """CRR has no fixed purchased-receivables factor; the flag changes nothing."""
    # Arrange
    frame = _row(approach=approach, risk_type=risk_type)

    # Act / Assert
    assert _ccf(frame, _CRR) == pytest.approx(expected)


def test_the_166a5_values_and_gate_are_cited_pack_entries() -> None:
    """The IRB factor is its own cited value, not a reuse of the Table A1 Row 5 rate."""
    # Arrange
    b31 = resolve("b31", date(2027, 1, 1))
    crr = resolve("crr", date(2026, 1, 1))

    # Act / Assert
    assert b31.feature("irb_purchased_receivable_commitment_ccf_applies") is True
    assert crr.feature("irb_purchased_receivable_commitment_ccf_applies") is False
    assert float(b31.scalar("irb_purchased_receivable_commitment_ccf")) == pytest.approx(0.40)
    assert float(b31.scalar("irb_purchased_receivable_commitment_ucc_ccf")) == pytest.approx(0.10)
    citation = b31.scalar_param("irb_purchased_receivable_commitment_ccf").citation
    assert (citation.framework, citation.article) == ("PS1/26", "166A")
