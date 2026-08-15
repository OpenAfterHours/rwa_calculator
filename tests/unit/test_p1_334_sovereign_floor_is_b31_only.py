"""P1.334 — the Art. 121(6) sovereign floor is a Basel 3.1 provision only.

`apply_risk_weights` called `apply_sovereign_floor_for_institutions`
unconditionally, so a CRR run applied PS1/26 Art. 121(6). **UK CRR Art. 121 has
four paragraphs**, verified verbatim against `docs/assets/crr.pdf`
(PAGE_INDEX 119):

    1. Table 5, keyed on the credit quality step of the central government of
       the jurisdiction in which the institution is incorporated
    2. unrated central government -> 100%
    3. original effective maturity of three months or less -> 20%
    4. trade finance under Art. 162(3) -> 50% (20% at <= 3 months residual)

then Article 122. There is no (5) and no (6).

PS1/26 Art. 121(6) opens *"Notwithstanding paragraphs 2 to 5"* — it modifies the
SCRA Grade A/B/C ladder that CRR does not have. CRR reaches the same supervisory
concern structurally rather than by a floor: Art. 121(1) already **derives** the
unrated institution's weight from its sovereign's CQS, so there is nothing for a
sovereign floor to bite on.

Direction: conservative (RWA-increasing), so removing it REDUCES RWA on the
affected population — which is why the discriminating case below is pinned
rather than left to a coincidence of table values.

References:
- UK CRR Art. 121(1)-(4) (crr.pdf PAGE_INDEX 119)
- PRA PS1/26 Art. 121(6) (ps126app1.pdf PAGE_INDEX 42)
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.branch_reasons import SA_RISK_WEIGHT_BRANCH_REASON, SovereignFloorReason
from rwa_calc.engine.sa import SACalculator
from rwa_calc.rulebook.resolve import resolve
from tests.fixtures.single_exposure import calculate_single_sa_exposure

FEATURE = "sa_unrated_institution_sovereign_floor_applies"


@pytest.fixture
def sa_calculator() -> SACalculator:
    return SACalculator()


@pytest.fixture
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2026, 6, 30))


@pytest.fixture
def b31_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


# ---------------------------------------------------------------------------
# The pack Feature — the regime decision, per arch_check check 17
# ---------------------------------------------------------------------------


def test_feature_is_off_under_crr_and_on_under_b31() -> None:
    """The regime decision lives in a cited pack Feature, not in engine code."""
    # Arrange / Act
    crr = resolve("crr", date(2026, 1, 1))
    b31 = resolve("b31", date(2027, 1, 1))

    # Assert
    assert crr.feature(FEATURE) is False
    assert b31.feature(FEATURE) is True


def test_the_feature_cites_the_right_article_on_each_side() -> None:
    """CRR cites Art. 121 (the four-paragraph article); B31 cites PS1/26 121."""
    # Arrange / Act
    crr_citation = str(resolve("crr", date(2026, 1, 1)).entry(FEATURE).citation)
    b31_citation = str(resolve("b31", date(2027, 1, 1)).entry(FEATURE).citation)

    # Assert
    assert "121" in crr_citation
    assert "PS1/26" in b31_citation


# ---------------------------------------------------------------------------
# The discriminating case — Art. 121(3) 20% vs a CQS-6 sovereign at 150%
# ---------------------------------------------------------------------------


def _short_dated_unrated_institution_in_fx(
    calculator: SACalculator, config: CalculationConfig
) -> dict:
    """<=3-month exposure to an unrated TR institution, booked in USD.

    Deliberately the widest gap available: CRR Art. 121(3) assigns 20%, while a
    CQS-6 sovereign floor would assign 150%. Any test where the two coincide
    proves nothing about whether the floor ran.
    """
    return calculate_single_sa_exposure(
        calculator,
        ead=Decimal("1000000"),
        exposure_class="INSTITUTION",
        cqs=None,
        residual_maturity_years=0.25,
        original_maturity_years=0.25,
        currency="USD",
        country_code="TR",
        local_currency="TRY",
        sovereign_cqs=6,
        config=config,
    )


def test_crr_short_dated_unrated_institution_keeps_art_121_3_20pct(
    sa_calculator: SACalculator, crr_config: CalculationConfig
) -> None:
    """CRR: 20% stands. Was 150% — the floor applied where no floor exists."""
    # Arrange / Act
    result = _short_dated_unrated_institution_in_fx(sa_calculator, crr_config)

    # Assert
    assert result["risk_weight"] == pytest.approx(0.20)


def test_b31_short_dated_unrated_institution_is_still_floored(
    sa_calculator: SACalculator, b31_config: CalculationConfig
) -> None:
    """B31 must NOT move — the load-bearing survivor.

    Without this, gating the floor off for BOTH regimes would satisfy the CRR
    assertion above while deleting a live Basel 3.1 rule.
    """
    # Arrange / Act
    result = _short_dated_unrated_institution_in_fx(sa_calculator, b31_config)

    # Assert — Table 5A Grade C is 150% and the CQS-6 floor is 150%; either way
    # the B31 leg stays high, and it must not fall to the CRR value.
    assert result["risk_weight"] > 0.20


def test_the_two_regimes_disagree_on_the_discriminating_row(
    sa_calculator: SACalculator, crr_config: CalculationConfig, b31_config: CalculationConfig
) -> None:
    """An identity, so the gate cannot silently collapse back to regime-invariant."""
    # Arrange / Act
    crr = _short_dated_unrated_institution_in_fx(sa_calculator, crr_config)
    b31 = _short_dated_unrated_institution_in_fx(sa_calculator, b31_config)

    # Assert
    assert crr["risk_weight"] != b31["risk_weight"]


# ---------------------------------------------------------------------------
# The branch reason — abstention must be visible, not silent
# ---------------------------------------------------------------------------


def test_crr_rows_are_named_regime_not_applicable(
    sa_calculator: SACalculator, crr_config: CalculationConfig
) -> None:
    """A gated-off rule still names itself, so the census can see it abstain.

    Skipping the call outright would drop the column and make "the rule did not
    apply" indistinguishable from "the rule never ran" — the exact conflation
    Phase 3's branch reasons exist to end.
    """
    # Arrange / Act
    result = _short_dated_unrated_institution_in_fx(sa_calculator, crr_config)

    # Assert
    assert result[SA_RISK_WEIGHT_BRANCH_REASON] == SovereignFloorReason.REGIME_NOT_APPLICABLE.value


def test_b31_rows_are_never_named_regime_not_applicable(
    sa_calculator: SACalculator, b31_config: CalculationConfig
) -> None:
    """The abstention limb must not leak into the regime that has the rule."""
    # Arrange / Act
    result = _short_dated_unrated_institution_in_fx(sa_calculator, b31_config)

    # Assert
    assert result[SA_RISK_WEIGHT_BRANCH_REASON] != SovereignFloorReason.REGIME_NOT_APPLICABLE.value


def test_the_reason_column_keeps_its_enum_dtype_when_gated_off(
    sa_calculator: SACalculator, crr_config: CalculationConfig
) -> None:
    """The abstention path must emit the Enum, not a String.

    The ``sa_branch`` edge contract requires the declared Enum dtype, and a
    plain ``pl.lit`` string passes every value assertion while failing the
    edge — caught here rather than as an opaque stage error.
    """
    # Arrange
    exposures = pl.LazyFrame(
        {
            "exposure_reference": ["E1"],
            "risk_weight": [0.20],
            "_upper_class": ["INSTITUTION"],
        }
    )
    from rwa_calc.engine.sa.sovereign_floor import apply_sovereign_floor_for_institutions

    # Act
    out = apply_sovereign_floor_for_institutions(
        exposures, pl.lit(value=True), applies=False
    ).collect()

    # Assert
    assert out.schema[SA_RISK_WEIGHT_BRANCH_REASON] == pl.Enum(
        [member.value for member in SovereignFloorReason]
    )
    assert out["risk_weight"][0] == pytest.approx(0.20)
