"""CM-03: Basel 3.1 A-IRB own-estimate CCFs are confined to revolving loan COMMITMENTS.

PRA PS1/26 Art. 166D(1) (IRB Part, Basel 3.1), verbatim:

    "An institution shall ... determine the exposure value for off-balance sheet
    items in respect of which it uses the Advanced IRB Approach ... by multiplying
    the item's nominal value by:
    (a) for revolving loan commitments which would not be subject to a 100%
        conversion factor under Credit Risk: Standardised Approach (CRR) Part
        Article 111: an own estimate of conversion factor ...;
    (b) for all other off-balance sheet items: the conversion factor that would be
        applicable to the off-balance sheet item under the Standardised Approach,
        as set out in Credit Risk: Standardised Approach (CRR) Part Article 111."

PS1/26 glossary, "commitment": "means any off-balance sheet contractual arrangement
that has been offered by the institution and accepted by the obligor, including to
extend credit, purchase assets or issue off-balance sheet items (but which is not
itself an issued off-balance sheet item)". "revolving loan commitment": "means a
commitment arising from a revolving loan facility ...".

So an ISSUED off-balance-sheet item (a letter of credit, a guarantee) is never a
revolving loan commitment, even when it is booked under a revolving facility and
inherits that facility's ``is_revolving`` flag: it takes the SA conversion factor
under limb (b). The engine marks issued items with ``is_obs_commitment = False``.

Before the fix the Basel 3.1 eligibility test read only ``is_revolving`` and the
SA CCF, so an issued medium/low-risk letter of credit (SA 20%) under a revolving
facility with ``ccf_modelled = 0.05`` took max(0.05, 0.5 x 0.20) = 0.10.

CRR is untouched: CRR Art. 166(8) admits own estimates "across different product
types as mentioned in points (a) to (d)" and the engine already confines that to
``is_obs_commitment | is_short_term_trade_lc`` (Art. 166(10) items take the
supervisory factor).
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


def _airb_row(
    *,
    risk_type: str,
    is_obs_commitment: bool | None,
    ccf_modelled: float,
    is_revolving: bool = True,
) -> pl.LazyFrame:
    return pl.DataFrame(
        {
            "exposure_reference": ["X1"],
            "drawn_amount": [0.0],
            "nominal_amount": [_NOMINAL],
            "risk_type": [risk_type],
            "approach": ["advanced_irb"],
            "ccf_modelled": [ccf_modelled],
            "is_revolving": [is_revolving],
            "is_obs_commitment": [is_obs_commitment],
        },
        schema_overrides={"is_obs_commitment": pl.Boolean},
    ).lazy()


def _ccf(frame: pl.LazyFrame, config: CalculationConfig) -> tuple[float, float]:
    out = CCFCalculator().apply_ccf(frame, config).collect()
    return out["ccf"][0], out["ead_from_ccf"][0]


def test_b31_issued_item_under_revolving_facility_takes_the_sa_ccf() -> None:
    """The defect: an issued MLR letter of credit must take SA 20%, not 0.5 x 20%."""
    # Arrange
    frame = _airb_row(risk_type="MLR", is_obs_commitment=False, ccf_modelled=0.05)

    # Act
    ccf, ead = _ccf(frame, _B31)

    # Assert — Art. 166D(1)(b): SA Table A1 Row 6 20%; before the fix 0.10 / 100,000
    assert ccf == pytest.approx(0.20)
    assert ead == pytest.approx(200_000.0)


def test_b31_issued_item_ignores_a_modelled_ccf_above_the_sa_ccf() -> None:
    """Limb (b) is the SA factor itself, in either direction - not a floor."""
    # Arrange
    frame = _airb_row(risk_type="MR_ISSUED", is_obs_commitment=False, ccf_modelled=0.80)

    # Act
    ccf, _ = _ccf(frame, _B31)

    # Assert — Table A1 Row 3 50%
    assert ccf == pytest.approx(0.50)


def test_b31_revolving_loan_commitment_keeps_its_own_estimate() -> None:
    """Control: limb (a) still applies to a revolving commitment (OC, SA 40%)."""
    # Arrange
    frame = _airb_row(risk_type="OC", is_obs_commitment=True, ccf_modelled=0.30)

    # Act
    ccf, ead = _ccf(frame, _B31)

    # Assert — max(0.30, 0.5 x 0.40 = 0.20) = 0.30
    assert ccf == pytest.approx(0.30)
    assert ead == pytest.approx(300_000.0)


def test_b31_unknown_commitment_status_takes_the_sa_ccf() -> None:
    """A null ``is_obs_commitment`` cannot evidence a commitment: SA factor (conservative)."""
    # Arrange
    frame = _airb_row(risk_type="OC", is_obs_commitment=None, ccf_modelled=0.25)

    # Act
    ccf, _ = _ccf(frame, _B31)

    # Assert — the named OC bucket gives SA 40%; the modelled 0.25 is NOT used
    assert ccf == pytest.approx(0.40)


def test_crr_issued_item_is_unchanged() -> None:
    """CRR: Art. 166(10)(c) supervisory 20% for an issued MLR item (pre-existing)."""
    # Arrange
    frame = _airb_row(risk_type="MLR", is_obs_commitment=False, ccf_modelled=0.05)

    # Act
    ccf, ead = _ccf(frame, _CRR)

    # Assert
    assert ccf == pytest.approx(0.20)
    assert ead == pytest.approx(200_000.0)


def test_crr_commitment_keeps_its_own_estimate() -> None:
    """CRR control: an Art. 166(8) commitment keeps its modelled CCF."""
    # Arrange
    frame = _airb_row(risk_type="OC", is_obs_commitment=True, ccf_modelled=0.30)

    # Act
    ccf, _ = _ccf(frame, _CRR)

    # Assert
    assert ccf == pytest.approx(0.30)
