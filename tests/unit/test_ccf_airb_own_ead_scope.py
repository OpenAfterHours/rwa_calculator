"""Basel 3.1 A-IRB single own estimate of EAD is confined to revolving loan facilities.

PRA PS1/26 Art. 166D(3) (IRB Part, Basel 3.1), verbatim:

    "An institution may, in respect of,
    (a) fully undrawn revolving loan facilities (i.e. where a revolving loan
        commitment arises from a facility for which no on-balance sheet item is
        related), and
    (b) partially drawn revolving loan facilities (i.e. where a revolving loan
        commitment and an on-balance sheet item relate to the same facility),
    assign a single exposure value to each such facility instead of the exposure
    values that would otherwise be assigned to the revolving loan commitment in
    accordance with paragraph 1 and, where appliable, any related on-balance sheet
    item in accordance with Article 166A(2)."

Paragraph 1 gives the exposure value "(b) for all other off-balance sheet items: the
conversion factor that would be applicable to the off-balance sheet item under the
Standardised Approach". The PS1/26 glossary: a commitment "is not itself an issued
off-balance sheet item"; a "revolving loan commitment" arises "from a revolving loan
facility ... that lets a borrower obtain a loan". And Art. 166A(5): "An institution
shall, for undrawn purchase commitments for revolving purchased receivables,
calculate the exposure value using a conversion factor of 40%".

So the ``ead_modelled`` route is the sibling of the Art. 166D(1)(a) own conversion
factor (CM-03) and reaches the same population: a revolving loan COMMITMENT. Before
this fix ``engine/ccf.py::_compute_ead`` used ``ead_modelled`` on ANY A-IRB row, so
an issued letter of credit, a non-revolving commitment or a flagged revolving
purchased-receivables commitment carrying one took max(ead_modelled, on-BS + 50% x
SA off-BS) - at worst half its Table A1 exposure value.

CRR is untouched: the Art. 166D(5) EAD route is gated on the Basel 3.1
``airb_ead_floor_applies`` Feature and CRR ignores ``ead_modelled``.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.ccf import CCFCalculator

_B31 = CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))
_CRR = CalculationConfig.crr(reporting_date=date(2026, 6, 30))
_NOMINAL = 1_000_000.0
_LOW_OWN_EAD = 50_000.0


def _airb_row(
    *,
    risk_type: str,
    is_obs_commitment: bool,
    is_revolving: bool,
    ead_modelled: float,
    is_purchased_receivable_commitment: bool = False,
) -> pl.LazyFrame:
    return pl.DataFrame(
        {
            "exposure_reference": ["X1"],
            "drawn_amount": [0.0],
            "nominal_amount": [_NOMINAL],
            "risk_type": [risk_type],
            "approach": ["advanced_irb"],
            "ccf_modelled": [None],
            "ead_modelled": [ead_modelled],
            "is_revolving": [is_revolving],
            "is_obs_commitment": [is_obs_commitment],
            "is_purchased_receivable_commitment": [is_purchased_receivable_commitment],
        },
        schema_overrides={"ccf_modelled": pl.Float64},
    ).lazy()


def _ead(frame: pl.LazyFrame, config: CalculationConfig) -> float:
    return CCFCalculator().apply_ccf(frame, config).collect()["ead_pre_crm"][0]


def test_b31_issued_item_under_revolving_facility_ignores_its_own_ead() -> None:
    """An issued MLR letter of credit takes Table A1 Row 6 20%: 200,000.

    Before the fix: max(50,000, 0 + 0.5 x 1,000,000 x 0.20, 0) = 100,000.
    """
    # Arrange
    frame = _airb_row(
        risk_type="MLR", is_obs_commitment=False, is_revolving=True, ead_modelled=_LOW_OWN_EAD
    )

    # Act / Assert
    assert _ead(frame, _B31) == pytest.approx(200_000.0)


def test_b31_non_revolving_commitment_ignores_its_own_ead() -> None:
    """A non-revolving OC commitment takes Table A1 Row 5 40%: 400,000.

    Before the fix: max(50,000, 0.5 x 1,000,000 x 0.40, 0) = 200,000.
    """
    # Arrange
    frame = _airb_row(
        risk_type="OC", is_obs_commitment=True, is_revolving=False, ead_modelled=_LOW_OWN_EAD
    )

    # Act / Assert
    assert _ead(frame, _B31) == pytest.approx(400_000.0)


def test_b31_purchased_receivable_commitment_ignores_its_own_ead() -> None:
    """A flagged revolving purchase commitment takes the Art. 166A(5) 40%: 400,000.

    Before the fix: max(50,000, 0.5 x 1,000,000 x 0.40, 0) = 200,000.
    """
    # Arrange
    frame = _airb_row(
        risk_type="OC",
        is_obs_commitment=True,
        is_revolving=True,
        ead_modelled=_LOW_OWN_EAD,
        is_purchased_receivable_commitment=True,
    )

    # Act / Assert
    assert _ead(frame, _B31) == pytest.approx(400_000.0)


@pytest.mark.parametrize(
    ("ead_modelled", "expected"),
    [
        pytest.param(250_000.0, 250_000.0, id="own-estimate-above-floor"),
        pytest.param(_LOW_OWN_EAD, 200_000.0, id="floor-b-binds"),
    ],
)
def test_b31_revolving_loan_commitment_keeps_its_own_ead(
    ead_modelled: float, expected: float
) -> None:
    """Control: Art. 166D(3) applies, floored by (5)(b) at 0.5 x 1,000,000 x 0.40."""
    # Arrange
    frame = _airb_row(
        risk_type="OC", is_obs_commitment=True, is_revolving=True, ead_modelled=ead_modelled
    )

    # Act / Assert
    assert _ead(frame, _B31) == pytest.approx(expected)


def test_crr_ignores_an_issued_items_own_ead() -> None:
    """CRR control: no Art. 166D under CRR — Art. 166(10)(c) 20% for an issued MLR item."""
    # Arrange
    frame = _airb_row(
        risk_type="MLR", is_obs_commitment=False, is_revolving=True, ead_modelled=_LOW_OWN_EAD
    )

    # Act / Assert
    assert _ead(frame, _CRR) == pytest.approx(200_000.0)
