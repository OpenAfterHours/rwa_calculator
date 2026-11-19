"""CM-09: a contingent on a COMMITMENT bucket (MR / OC) but marked issued raises DQ017.

CRR Art. 166(8)(d) (current UK CRR), verbatim: "for other credit lines, note issuance
facilities (NIFs), and revolving underwriting facilities (RUFs), a conversion factor
of 75 % shall apply." Art. 166(10) applies only "for all off-balance sheet items other
than those mentioned in paragraphs 1 to 8" — (b) "50 % if it is a medium-risk item".

``MR`` is the NIF / RUF commitment bucket and ``OC`` the "other commitments" bucket,
but a contingent defaults to ``is_obs_commitment = False`` (an issued item), so a NIF
booked as a contingent without the flag takes the Art. 166(10)(b) 50% under CRR F-IRB
instead of 166(8)(d)'s 75% — silently. The engine honours its documented flag, and the
contradiction cannot be auto-resolved (an issued medium-risk item mis-coded ``MR``
would then be overstated at 75%), so the fix is a warning, not a derivation.
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.contracts.errors import ERROR_ISSUED_ITEM_ON_COMMITMENT_RISK_TYPE
from rwa_calc.contracts.validation import validate_bundle_values
from tests.fixtures.raw_bundle import make_raw_bundle


def _bundle(
    risk_type: str | None, is_obs_commitment: bool | None, nominal: float = 1_000_000.0
) -> object:
    data: dict[str, list[object]] = {
        "contingent_reference": ["C1"],
        "counterparty_reference": ["CP001"],
        "nominal_amount": [nominal],
        "risk_type": [risk_type],
    }
    schema: dict[str, pl.DataType] = {
        "contingent_reference": pl.Utf8(),
        "counterparty_reference": pl.Utf8(),
        "nominal_amount": pl.Float64(),
        "risk_type": pl.Utf8(),
    }
    if is_obs_commitment is not None:
        data["is_obs_commitment"] = [is_obs_commitment]
        schema["is_obs_commitment"] = pl.Boolean()
    return make_raw_bundle(
        contingents=pl.DataFrame(data, schema=schema).lazy(),
        counterparties=pl.LazyFrame({"counterparty_reference": ["CP001"]}),
    )


def _dq017(bundle: object) -> list:
    return [
        e
        for e in validate_bundle_values(bundle)  # type: ignore[arg-type]
        if e.code == ERROR_ISSUED_ITEM_ON_COMMITMENT_RISK_TYPE
    ]


@pytest.mark.parametrize("risk_type", ["MR", "medium_risk", "OC", "other_commit"])
@pytest.mark.parametrize("flag", [False, None], ids=["explicit-false", "absent-default"])
def test_commitment_bucket_on_an_issued_contingent_warns(risk_type: str, flag: bool | None) -> None:
    """The contradiction the item exists to surface: exactly one DQ017."""
    # Act
    found = _dq017(_bundle(risk_type, flag))

    # Assert
    assert len(found) == 1
    assert found[0].field_name == "is_obs_commitment"
    assert "166(8)(d)" in (found[0].regulatory_reference or "")


@pytest.mark.parametrize(
    ("risk_type", "flag", "nominal"),
    [
        pytest.param("MR", True, 1_000_000.0, id="commitment-flagged"),
        pytest.param("MR_ISSUED", False, 1_000_000.0, id="issued-bucket"),
        pytest.param("MLR", False, 1_000_000.0, id="issued-mlr"),
        pytest.param(None, False, 1_000_000.0, id="no-risk-type-dq016-territory"),
        pytest.param("MR", False, 0.0, id="zero-amount"),
    ],
)
def test_no_warning_without_the_contradiction(
    risk_type: str | None, flag: bool, nominal: float
) -> None:
    """Controls: a flagged commitment, an issued bucket, no bucket, no amount."""
    # Act / Assert
    assert _dq017(_bundle(risk_type, flag, nominal)) == []
