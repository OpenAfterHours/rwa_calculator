"""
P5.12: Art. 129(5) unrated covered bonds through the full pipeline, CRR and Basel 3.1.

Pipeline position:
    build_reporting_unrated_covered_bond_bundle() -> Loader seal -> HierarchyResolver
        -> Classifier (lifts ``institution_cqs`` / ``scra_grade`` to ``cp_*``)
        -> SACalculator -> OutputAggregator

Key responsibilities:
- Prove every unrated covered bond takes the Art. 129(5) image of its issuer's
  senior unsecured weight, in each regime's own correspondence table — four
  limbs under CRR, seven under PS1/26 — with RWA = EAD x RW.
- Prove the precedence the article implies: the issuer's ECAI step before its
  SCRA grade, and the covered bond's own ECAI assessment (Art. 129(4) Table 7)
  before either.
- Prove the covered bond's weight is the image of the weight the engine itself
  assigns a senior unsecured exposure to an institution with the same
  attributes, so the derivation and the institution path cannot drift apart.

Why the full pipeline and not ``calculate_single_sa_exposure``: the unit tests
of this derivation (``tests/unit/test_covered_bonds.py``) write ``cp_scra_grade``
and ``cp_institution_cqs`` straight into the SA frame, so the classifier lift
that produces those columns from the counterparty's ``scra_grade`` /
``institution_cqs`` is not on their path. Here it is: replacing either lift with
a typed null moves the SCRA or the ECAI legs off their weights (measured).

Regulatory basis (quoted from the PDFs; the values below are hand values from
these texts, never read back from the rulepack):

    PS1/26 Art. 129(5) (ps126app1.pdf pp.61-62): "Eligible covered bonds for
    which a credit assessment by a nominated ECAI is not available shall be
    assigned a risk weight on the basis of the risk weight assigned to senior
    unsecured exposures to the institution which issues them. [...] (a) [...]
    20% [...] 10%; (aa) [...] 30% [...] 15%; (ab) [...] 40% [...] 20%; (b)
    [...] 50% [...] 25%; (ba) [...] 75% [...] 35%; (c) [...] 100% [...] 50%;
    or (d) [...] 150% [...] 100%."
    UK CRR Art. 129(5): the same sentence with limbs (a) 20 -> 10, (b) 50 -> 20,
    (c) 100 -> 50 and (d) 150 -> 100 only.
    Issuer weights: Art. 120 Table 3 (CRR CQS 1-6 -> 20/50/50/100/100/150;
    PS1/26 -> 20/30/50/100/100/150); PS1/26 Art. 121(2) Table 5 (Grade A 40%,
    B 75%, C 150%) and Art. 121(5) (Grade A, CET1 >= 14%, leverage >= 5% ->
    30%); CRR Art. 121(2) (unrated institution, unrated sovereign -> 100%).

References:
- UK CRR Art. 120, 121(1)-(2), 129(4)-(5)
- PRA PS1/26 Art. 120 Table 3, 121(1)-(2)/(5), 129(4)-(5)
- tests/fixtures/reporting_unrated_covered_bond_portfolio.py (the leg table)
- tests/acceptance/reporting/test_of07_unrated_covered_bond_rows.py (OF 07.00)
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.reporting_unrated_covered_bond_portfolio import (
    COVERED_BOND_REFERENCES,
    DRAWN,
    EXPECTED_RW,
    LN_ECAI_OVER_SCRA,
    LN_INSTITUTION_ANCHOR,
    LN_OWN_RATING,
    LN_SCRA_A_ENHANCED,
    OWN_RATING_CQS,
    build_reporting_unrated_covered_bond_bundle,
)

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

#: The regimes, each with the index of its weight in ``EXPECTED_RW`` / ``EXPECTED_ROW``.
_FRAMEWORKS: tuple[str, ...] = ("CRR", "BASEL_3_1")
_INDEX: dict[str, int] = {"CRR": 0, "BASEL_3_1": 1}

#: Art. 129(5) as each regime words it: issuer senior unsecured weight -> covered bond
#: weight. CRR (a)-(d); PS1/26 adds (aa), (ab), (ba) and moves (b) from 20% to 25%.
_ART_129_5: dict[str, dict[float, float]] = {
    "CRR": {0.20: 0.10, 0.50: 0.20, 1.00: 0.50, 1.50: 1.00},
    "BASEL_3_1": {
        0.20: 0.10,
        0.30: 0.15,
        0.40: 0.20,
        0.50: 0.25,
        0.75: 0.35,
        1.00: 0.50,
        1.50: 1.00,
    },
}


@lru_cache(maxsize=2)
def _results(framework: str) -> pl.DataFrame:
    """The book through ``PipelineOrchestrator`` under one regime, SA permission only."""
    if framework == "CRR":
        config = CalculationConfig.crr(
            reporting_date=date(2025, 12, 31), permission_mode=PermissionMode.STANDARDISED
        )
    else:
        config = CalculationConfig.basel_3_1(
            reporting_date=date(2027, 6, 1), permission_mode=PermissionMode.STANDARDISED
        )
    result = PipelineOrchestrator().run_with_data(
        build_reporting_unrated_covered_bond_bundle(), config
    )
    return result.results.collect()


def _leg(framework: str, reference: str) -> dict:
    """The single result row of one leg (no leg is split: no CRM, no RE)."""
    rows = _results(framework).filter(pl.col("exposure_reference") == reference)
    assert rows.height == 1, f"{framework}: expected one row for {reference}, got {rows.height}"
    return rows.row(0, named=True)


# ---------------------------------------------------------------------------
# Adequacy (LESSONS C11): the book is what the weight tests assume it is
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("framework", _FRAMEWORKS)
def test_every_leg_is_a_standardised_covered_bond_and_only_one_carries_its_own_rating(
    framework: str,
) -> None:
    """Without ``cqs`` null on every leg but one, Art. 129(5) is not what is being tested."""
    # Arrange / Act
    legs = {reference: _leg(framework, reference) for reference in COVERED_BOND_REFERENCES}

    # Assert
    for reference, leg in legs.items():
        assert leg["exposure_class"] == "covered_bond", reference
        assert leg["approach_applied"] == "standardised", reference
        expected_cqs = OWN_RATING_CQS if reference == LN_OWN_RATING else None
        assert leg["cqs"] == expected_cqs, f"{reference}: cqs {leg['cqs']}"
    assert _leg(framework, LN_INSTITUTION_ANCHOR)["exposure_class"] == "institution"


# ---------------------------------------------------------------------------
# The weights
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("reference", COVERED_BOND_REFERENCES)
@pytest.mark.parametrize("framework", _FRAMEWORKS)
def test_an_unrated_covered_bond_takes_the_art_129_5_image_of_its_issuers_weight(
    framework: str, reference: str
) -> None:
    """Absolute hand values per leg and regime; see the fixture's leg table."""
    # Arrange
    expected_rw = EXPECTED_RW[reference][_INDEX[framework]]

    # Act
    leg = _leg(framework, reference)

    # Assert
    assert leg["ead_final"] == pytest.approx(DRAWN[reference])
    assert leg["risk_weight"] == pytest.approx(expected_rw)
    assert leg["rwa_final"] == pytest.approx(DRAWN[reference] * expected_rw)


@pytest.mark.parametrize("framework", _FRAMEWORKS)
def test_the_issuers_ecai_step_comes_before_its_scra_grade(framework: str) -> None:
    """Issuer CQS 1 (20% -> 10%) beside Grade C: the grade must not be read.

    PS1/26 Art. 121(1) grades only institutions "for which a credit assessment by
    a nominated ECAI is not available"; Grade C would give 150% -> 100%.
    """
    leg = _leg(framework, LN_ECAI_OVER_SCRA)

    assert leg["risk_weight"] == pytest.approx(0.10)


@pytest.mark.parametrize("framework", _FRAMEWORKS)
def test_a_covered_bonds_own_rating_comes_before_its_issuers_weight(framework: str) -> None:
    """Own CQS 1 (Table 7: 10%) beside an issuer at CQS 6 (150% -> 100%).

    Art. 129(5) applies only where "a credit assessment by a nominated ECAI is
    not available" for the bond itself; otherwise Art. 129(4) Table 7 governs.
    """
    leg = _leg(framework, LN_OWN_RATING)

    assert leg["cqs"] == OWN_RATING_CQS
    assert leg["risk_weight"] == pytest.approx(0.10)


@pytest.mark.parametrize("framework", _FRAMEWORKS)
def test_the_covered_bond_weight_is_the_image_of_the_engines_own_issuer_weight(
    framework: str,
) -> None:
    """Art. 129(5) works "on the basis of the risk weight assigned to senior
    unsecured exposures to the institution which issues them".

    The anchor is a senior unsecured loan to an institution with exactly the
    issuer attributes of ``LN_SCRA_A_ENHANCED`` (SCRA A_ENHANCED, GB, no ECAI step,
    no ``sovereign_cqs``). Whatever weight the engine gives it, the covered bond's
    must be that weight's image under the regime's own correspondence table:
    CRR 100% -> (c) 50%; PS1/26 30% -> (aa) 15%.
    """
    # Arrange
    anchor_rw = _leg(framework, LN_INSTITUTION_ANCHOR)["risk_weight"]

    # Act
    covered_bond_rw = _leg(framework, LN_SCRA_A_ENHANCED)["risk_weight"]

    # Assert
    assert anchor_rw == pytest.approx(EXPECTED_RW[LN_INSTITUTION_ANCHOR][_INDEX[framework]])
    image = {round(k, 4): v for k, v in _ART_129_5[framework].items()}
    assert round(anchor_rw, 4) in image, (
        f"{framework}: issuer weight {anchor_rw} is no limb of Art. 129(5)"
    )
    assert covered_bond_rw == pytest.approx(image[round(anchor_rw, 4)])
