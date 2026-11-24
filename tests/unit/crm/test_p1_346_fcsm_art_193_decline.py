"""P1.346 — Simple-Method collateral may not raise an exposure's risk weight.

``engine/sa/rw_adjustments.py::apply_fcsm_rw_substitution`` blends the
collateral's Art. 222(3) weight into the secured portion of an SA exposure.
Art. 222(3) floors that weight at 20% and sets no ceiling, so wherever the
collateral weighs MORE than the obligor (cross-currency cash against a 0%
sovereign, a 100% corporate bond against a 20% institution, Basel 3.1 250%
equity against a 100% corporate) the blend used to RAISE the exposure's RWEA.

The rule that settles it is Art. 193, not Art. 222(3):

- CRR Art. 193(1) (legislation.gov.uk, current text): "No exposure in respect of
  which an institution obtains credit risk mitigation shall produce a higher
  risk-weighted exposure amount or expected loss amount than an otherwise
  identical exposure in respect of which an institution has no credit risk
  mitigation." Mandatory and per exposure.
- PS1/26 Art. 193(1) is "[Note: Provision left blank]" and Art. 193(2A) says "an
  institution may choose to disregard any item of credit protection" for the
  methods in paragraph A1, which names the Financial Collateral Simple Method.
  Under Basel 3.1 the decline is a firm ELECTION (owner sign-off on P1.346:
  elected, for the whole Simple-Method leg, per exposure).

The engine therefore DECLINES the whole Simple-Method leg of an exposure whose
collateral weight is above its own (mirroring the guarantee decline in
``apply_guarantee_substitution``), records that in ``fcsm_substitution_applied``
and keeps the substitution where the two weights are EQUAL (Art. 193(1) is
silent at equality: equal is not "higher"; the brief prescribes a decline only
where the blend "exceeds" the unsecured weight).

Every test is parametrised over both regimes and each regime fails on its own
before the fix (LESSONS C7).

References:
- CRR Art. 193(1), Art. 222(3)/(6)
- PRA PS1/26 Art. 193(A1), (1), (2A); Art. 222(3)
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import CRMCollateralMethod
from rwa_calc.engine.sa.rw_adjustments import apply_fcsm_rw_substitution
from rwa_calc.rulebook.model import Feature
from rwa_calc.rulebook.resolve import resolve

_REGIMES: tuple[str, ...] = ("crr", "b31")
_REPORTING_DATE: dict[str, date] = {"crr": date(2026, 6, 30), "b31": date(2027, 6, 30)}
_FEATURE = "fcsm_decline_non_beneficial"

_EAD = 1_000_000.0

#: (reference, obligor RW, FCSM collateral value, FCSM collateral RW,
#:  expected RW, expected ``fcsm_substitution_applied``)
_LEGS: tuple[tuple[str, float, float, float, float, bool], ...] = (
    # (a) the bullet's case: EUR cash on a GBP loan to a 0% domestic sovereign.
    #     Art. 222(3) floors the cash at 20%; the old blend took the loan 0% -> 20%.
    ("A_ZERO_RW_SOVEREIGN_EUR_CASH", 0.0, 1_000_000.0, 0.20, 0.0, False),
    # (b) a 100% corporate bond covering half of a 20% exposure: 20% -> 60%.
    ("B_LOW_RW_OBLIGOR_CORPORATE_BOND", 0.20, 500_000.0, 1.00, 0.20, False),
    # (c) Basel 3.1 250% equity covering 40% of a 100% corporate: 100% -> 160%.
    ("C_EQUITY_ABOVE_OBLIGOR", 1.00, 400_000.0, 2.50, 1.00, False),
    # (d) non-binding control: the collateral weighs less, the blend stands.
    ("D_CONTROL_BENEFICIAL", 1.00, 1_000_000.0, 0.20, 0.20, True),
    # (e) equality: Art. 193(1) is silent ("higher"), the substitution stands.
    ("E_EQUAL_WEIGHTS", 1.00, 1_000_000.0, 1.00, 1.00, True),
    # (f) no Simple-Method collateral at all.
    ("F_NO_COLLATERAL", 0.50, 0.0, 0.0, 0.50, False),
)
#: The legs that carry Simple-Method collateral and must be declined.
_DECLINED = {leg[0] for leg in _LEGS if leg[2] > 0 and not leg[5]}


def _config(regime: str) -> CalculationConfig:
    factory = CalculationConfig.crr if regime == "crr" else CalculationConfig.basel_3_1
    return factory(
        reporting_date=_REPORTING_DATE[regime],
        crm_collateral_method=CRMCollateralMethod.SIMPLE,
    )


def _frame() -> pl.LazyFrame:
    return pl.LazyFrame(
        {
            "exposure_reference": [leg[0] for leg in _LEGS],
            "ead_final": [_EAD] * len(_LEGS),
            "risk_weight": [leg[1] for leg in _LEGS],
            "fcsm_collateral_value": [leg[2] for leg in _LEGS],
            "fcsm_collateral_rw": [leg[3] for leg in _LEGS],
            "approach": ["standardised"] * len(_LEGS),
            "exposure_class": ["corporate"] * len(_LEGS),
        }
    )


def _uncapped_blend(obligor_rw: float, value: float, collateral_rw: float) -> float:
    secured = min(value / _EAD, 1.0)
    return secured * collateral_rw + (1.0 - secured) * obligor_rw


def _by_ref(result: pl.DataFrame) -> dict[str, dict[str, object]]:
    return {row["exposure_reference"]: row for row in result.iter_rows(named=True)}


# =============================================================================
# The decline itself
# =============================================================================


@pytest.mark.parametrize("regime", _REGIMES)
@pytest.mark.parametrize(
    ("reference", "obligor_rw", "value", "collateral_rw", "expected_rw", "_applied"),
    _LEGS,
    ids=[leg[0] for leg in _LEGS],
)
def test_simple_method_collateral_never_raises_the_risk_weight(
    regime: str,
    reference: str,
    obligor_rw: float,
    value: float,
    collateral_rw: float,
    expected_rw: float,
    _applied: bool,
) -> None:
    """The post-FCSM weight is the blend where it helps, the obligor's where it would hurt.

    Arrange: one SA row per leg, Simple Method elected.
    Act:     apply_fcsm_rw_substitution.
    Assert:  absolute risk weight and RWEA per leg; for every declined leg the
             uncapped Art. 222(3) blend really is above the obligor's weight, so
             the leg cannot pass vacuously (LESSONS C11).
    """
    # Arrange
    if reference in _DECLINED:
        assert _uncapped_blend(obligor_rw, value, collateral_rw) > obligor_rw, (
            f"{reference}: the uncapped blend does not exceed the obligor's weight - "
            "this leg could not show the defect"
        )

    # Act
    result = _by_ref(apply_fcsm_rw_substitution(_frame(), _config(regime)).collect())[reference]

    # Assert
    assert result["risk_weight"] == pytest.approx(expected_rw, abs=1e-12)
    assert result["ead_final"] * result["risk_weight"] == pytest.approx(
        _EAD * expected_rw, abs=1e-6
    )
    assert result["pre_fcsm_risk_weight"] == pytest.approx(obligor_rw, abs=1e-12)


@pytest.mark.parametrize("regime", _REGIMES)
def test_a_declined_leg_is_recorded_as_not_applied(regime: str) -> None:
    """``fcsm_substitution_applied`` is True only where the blend was applied.

    It is the one carrier reporting reads to keep C 07.00 / OF 07.00 col 0070 on
    the same decision as the RWEA.

    Arrange: the six legs.
    Act:     apply_fcsm_rw_substitution.
    Assert:  the flag per leg, exactly.
    """
    # Arrange
    frame = _frame()

    # Act
    result = _by_ref(apply_fcsm_rw_substitution(frame, _config(regime)).collect())

    # Assert
    assert {ref: row["fcsm_substitution_applied"] for ref, row in result.items()} == {
        leg[0]: leg[5] for leg in _LEGS
    }


@pytest.mark.parametrize("regime", _REGIMES)
def test_equal_weights_keep_the_simple_method_substitution(regime: str) -> None:
    """At equality the substitution is APPLIED, not declined (the deposit sibling's choice).

    The guarantee path declines at equality (strict ``<``); the Simple Method
    does not. Capital is identical either way — what this pins is the audit and
    reporting trail: the row stays a Simple-Method row and its collateral stays
    in col 0070.

    Arrange: collateral and obligor both at 100%, full cover.
    Act:     apply_fcsm_rw_substitution.
    Assert:  risk weight 1.00, applied, ``ead_calculation_method`` "simple".
    """
    # Arrange
    frame = _frame()

    # Act
    row = _by_ref(apply_fcsm_rw_substitution(frame, _config(regime)).collect())["E_EQUAL_WEIGHTS"]

    # Assert
    assert row["risk_weight"] == pytest.approx(1.0, abs=1e-12)
    assert row["fcsm_substitution_applied"] is True
    assert row["ead_calculation_method"] == "simple"


# =============================================================================
# The regime basis: a mandatory cap under CRR, an election under Basel 3.1
# =============================================================================


@pytest.mark.parametrize(
    ("regime", "framework", "article", "note_prefix"),
    [("crr", "CRR", "193(1)", ""), ("b31", "PS1/26", "193", "(2A)")],
)
def test_each_regime_declines_on_its_own_basis(
    regime: str, framework: str, article: str, note_prefix: str
) -> None:
    """CRR declines under the mandatory Art. 193(1); Basel 3.1 under the 193(2A) election.

    PS1/26 Art. 193(1) is "[Note: Provision left blank]" — a Basel 3.1 decline
    citing it would cite a deleted provision. Watchfire's PS1/26 grammar takes
    "paragraph N" only, so the Basel 3.1 citation is article "193" with a note
    that opens "(2A)".

    Arrange: resolve the regime's pack.
    Act:     read the Feature entry.
    Assert:  enabled, cited to the regime's own paragraph.
    """
    # Arrange
    pack = resolve(regime, _REPORTING_DATE[regime])

    # Act
    entry = pack.entry(_FEATURE)

    # Assert
    assert isinstance(entry, Feature)
    assert entry.enabled is True
    assert (entry.citation.framework, entry.citation.article) == (framework, article)
    assert entry.citation.note.startswith(note_prefix)


def test_the_basel_3_1_election_is_reversible_from_the_pack() -> None:
    """Switching the Basel 3.1 election off restores the uncapped Art. 222(3) blend.

    Arrange: the Basel 3.1 pack with the Feature overridden to False.
    Act:     apply_fcsm_rw_substitution on leg (c).
    Assert:  1.60 — 0.4 x 250% + 0.6 x 100% — and the leg is applied.
    """
    # Arrange
    pack = resolve("b31", _REPORTING_DATE["b31"])
    entry = pack.entry(_FEATURE)
    assert isinstance(entry, Feature)
    off = pack.with_overrides(
        **{_FEATURE: Feature(name=_FEATURE, enabled=False, citation=entry.citation)}
    )

    # Act
    result = apply_fcsm_rw_substitution(_frame(), _config("b31"), pack=off).collect()

    # Assert
    row = _by_ref(result)["C_EQUITY_ABOVE_OBLIGOR"]
    assert row["risk_weight"] == pytest.approx(1.60, abs=1e-12)
    assert row["fcsm_substitution_applied"] is True
