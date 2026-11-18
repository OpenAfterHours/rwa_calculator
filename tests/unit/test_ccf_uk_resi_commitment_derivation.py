"""RE-14: a UK residential mortgage commitment takes Table A1 Row 4(b) 50% without a manual flag.

PRA PS1/26 Art. 111(1) Table A1 (Basel 3.1), verbatim:

    Row 4 (50%): "The following commitments: (a) note issuance facilities and
    revolving underwriting facilities; and (b) UK residential mortgage commitments
    that are not subject to a conversion factor of 10% or 100%."
    Row 5 (40%): "Any other commitment that is not subject to a conversion factor
    of 10%, 50% or 100%."

Before the fix the Row 4(b) override fired only when the preparer set
``is_uk_residential_mortgage_commitment`` (schema default False, never derived and
absent from the input-schema docs), so the undrawn limb of an ordinary UK mortgage
facility took Row 5's 40%: limit 300,000, drawn 200,000 -> CCF 0.40, EAD 40,000 where
Row 4(b) gives 0.50 / 50,000.

The flag is now tri-state. Explicit True / False is honoured; a null flag is derived
under Basel 3.1 for a row that is evidently a UK residential mortgage commitment:

- a commitment (``is_obs_commitment``), not an issued item;
- a retail mortgage (``exposure_class == retail_mortgage``) actually secured on
  residential property (an allocated ``residential_collateral_value > 0`` or the
  linked property's ``property_type == "residential"``) — commercial-only property
  security does not qualify;
- UK: the data model carries no property location (P1.337), so "UK" is evidenced by
  a GB obligor AND a GBP denomination. A row failing either test keeps Row 5 (the
  pre-fix number) — the derivation never moves a row it cannot show is UK; a firm
  with a UK mortgage to a non-GB obligor sets the flag explicitly, and one with a
  GB obligor's non-UK property sets it False.

The Row 4(b) carve-out ("not subject to a conversion factor of 10% or 100%") is
unchanged: a Row 7 UCC (10%) or a Row 1/2 (100%) row is left alone. CRR has no
Table A1 and is untouched.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.ccf import CCFCalculator

_B31 = CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))
_CRR = CalculationConfig.crr(reporting_date=date(2026, 6, 30))
_UNDRAWN = 100_000.0


def _undrawn_mortgage(**overrides: object) -> pl.LazyFrame:
    row: dict[str, object] = {
        "exposure_reference": "F1_UNDRAWN",
        "drawn_amount": 0.0,
        "nominal_amount": _UNDRAWN,
        "risk_type": None,
        "approach": "standardised",
        "is_obs_commitment": True,
        "is_uk_residential_mortgage_commitment": None,
        "exposure_class": "retail_mortgage",
        "residential_collateral_value": 200_000.0,
        "property_type": None,
        "cp_country_code": "GB",
        "currency": "GBP",
    }
    row.update(overrides)
    return pl.DataFrame(
        [row],
        schema_overrides={
            "risk_type": pl.Utf8,
            "is_uk_residential_mortgage_commitment": pl.Boolean,
            "is_obs_commitment": pl.Boolean,
            "cp_country_code": pl.Utf8,
            "currency": pl.Utf8,
            "exposure_class": pl.Utf8,
            "residential_collateral_value": pl.Float64,
            "property_type": pl.Utf8,
        },
    ).lazy()


def _ccf_ead(frame: pl.LazyFrame, config: CalculationConfig) -> tuple[float, float]:
    out = CCFCalculator().apply_ccf(frame, config).collect()
    return out["ccf"][0], out["ead_from_ccf"][0]


def test_b31_unflagged_uk_mortgage_commitment_takes_row_4b() -> None:
    """The defect: 0.40 / 40,000 before the fix; Row 4(b) gives 0.50 / 50,000."""
    # Arrange
    frame = _undrawn_mortgage()

    # Act
    ccf, ead = _ccf_ead(frame, _B31)

    # Assert
    assert ccf == pytest.approx(0.50)
    assert ead == pytest.approx(50_000.0)


@pytest.mark.parametrize("approach", ["foundation_irb", "advanced_irb"])
def test_b31_irb_rows_take_row_4b_too(approach: str) -> None:
    """Art. 166C(1) / 166D(1)(b): the IRB carriers read the SA Table A1 factor."""
    # Arrange
    frame = _undrawn_mortgage(approach=approach)

    # Act / Assert
    assert _ccf_ead(frame, _B31)[0] == pytest.approx(0.50)


def test_b31_undrawn_row_evidenced_by_the_linked_property_type() -> None:
    """Facility collateral is allocated to DRAWN amounts: the undrawn row's allocated
    residential value is 0, so the linked property's type must also evidence it."""
    # Arrange — the pipeline shape of a mortgage facility's undrawn limb
    frame = _undrawn_mortgage(residential_collateral_value=0.0, property_type="residential")

    # Act / Assert
    assert _ccf_ead(frame, _B31)[0] == pytest.approx(0.50)


def test_b31_explicit_false_is_honoured() -> None:
    """A preparer can opt a row out (e.g. a GB obligor's non-UK property)."""
    # Arrange
    frame = _undrawn_mortgage(is_uk_residential_mortgage_commitment=False)

    # Act / Assert — Row 5 40%
    assert _ccf_ead(frame, _B31)[0] == pytest.approx(0.40)


def test_b31_explicit_true_is_honoured_without_evidence() -> None:
    """A preparer can opt a row in that the proxy cannot see (non-GB obligor)."""
    # Arrange
    frame = _undrawn_mortgage(is_uk_residential_mortgage_commitment=True, cp_country_code="US")

    # Act / Assert
    assert _ccf_ead(frame, _B31)[0] == pytest.approx(0.50)


@pytest.mark.parametrize(
    ("overrides", "why"),
    [
        ({"cp_country_code": "US"}, "non-GB obligor: UK not evidenced"),
        ({"cp_country_code": None}, "unknown obligor country: UK not evidenced"),
        ({"currency": "EUR"}, "non-GBP denomination: UK not evidenced"),
        ({"residential_collateral_value": 0.0}, "no residential security (CRE only)"),
        ({"residential_collateral_value": None}, "no residential security recorded"),
        (
            {"residential_collateral_value": 0.0, "property_type": "commercial"},
            "secured on commercial property only",
        ),
        ({"exposure_class": "corporate"}, "not a retail mortgage"),
        ({"is_obs_commitment": False, "risk_type": "MLR"}, "an issued item, not a commitment"),
    ],
)
def test_b31_row_without_evidence_keeps_its_bucket(overrides: dict[str, object], why: str) -> None:
    """The derivation never moves a row it cannot show is a UK resi commitment."""
    # Arrange
    frame = _undrawn_mortgage(**overrides)
    expected = 0.20 if overrides.get("risk_type") == "MLR" else 0.40

    # Act / Assert
    assert _ccf_ead(frame, _B31)[0] == pytest.approx(expected), why


def test_b31_original_currency_is_the_denomination_tested() -> None:
    """After FX, ``currency`` is the reporting currency; the original one decides."""
    # Arrange — a EUR mortgage converted to GBP for reporting
    frame = _undrawn_mortgage().with_columns(pl.lit("EUR").alias("original_currency"))

    # Act / Assert — not evidenced as UK: Row 5
    assert _ccf_ead(frame, _B31)[0] == pytest.approx(0.40)


@pytest.mark.parametrize(
    ("risk_type", "expected"),
    [("LR", 0.10), ("FRC", 1.00)],
)
def test_b31_row_4b_carve_out_is_respected(risk_type: str, expected: float) -> None:
    """'not subject to a conversion factor of 10% or 100%' — Row 7 / Row 2 stay."""
    # Arrange
    frame = _undrawn_mortgage(risk_type=risk_type)

    # Act / Assert
    assert _ccf_ead(frame, _B31)[0] == pytest.approx(expected)


def test_crr_is_untouched() -> None:
    """CRR has no Table A1 Row 4(b): an OC commitment stays at Annex I 50%."""
    # Arrange
    frame = _undrawn_mortgage(risk_type="OC")

    # Act / Assert — no original-maturity source, so the conservative 2(b)(ii) 50%
    assert _ccf_ead(frame, _CRR)[0] == pytest.approx(0.50)
