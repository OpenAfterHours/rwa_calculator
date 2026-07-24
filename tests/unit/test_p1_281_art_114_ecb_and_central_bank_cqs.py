"""
P1.281 — Art. 114(3) ECB 0% risk weight and PS1/26 Art. 114(2A) central-bank CQS.

Two distinct provisions of the same article, with DIFFERENT regime scope:

**Art. 114(3) — the ECB, regime-INVARIANT.**
    CRR (crr.pdf p.111): "Exposures to the ECB shall be assigned a 0 % risk weight."
    PS1/26 (ps126app1.pdf p.36): "Exposures to the European Central Bank shall be
    assigned a 0% risk weight."
    Unconditional under both regimes — no currency test, no rating test. It must
    therefore NOT be gated on a pack Feature.

**Art. 114(2A) — unrated central banks, PS1/26 ONLY.**
    "Exposures to a central bank for which a credit assessment by a nominated ECAI
    is not available shall be treated in accordance with paragraph 2 if a credit
    assessment by a nominated ECAI is available for the central government of the
    jurisdiction of the central bank. In this case, the central government's credit
    assessment shall be used to determine the risk weight for exposures to the
    central bank."
    CRR Art. 114 has no paragraph 2A (it runs 1, 2, 3, 4, then 5/6 deleted and 7
    third-country equivalence), so this limb is Feature-gated to Basel 3.1.

Do NOT confuse either with **Art. 114(4)**, the only CGCB 0% branch that existed
before this item: "Exposures to the central government of the United Kingdom and
the Bank [of England] denominated and funded in sterling shall be assigned a risk
weight of 0 %." That is a currency-conditional branch keyed on
``is_domestic_currency`` and it does not reach a EUR-denominated ECB exposure —
which is why the ECB rows below deliberately carry no domestic country/currency
pair, so a pre-fix 100% proves the 114(4) route is not what makes them 0%.

Table 1 (identical in both regimes): CQS 1 -> 0%, 2 -> 20%, 3 -> 50%,
4 -> 100%, 5 -> 100%, 6 -> 150%.

References:
- CRR Art. 114(1)/(2)/(3)/(4); PS1/26 Art. 114(1)/(2)/(2A)/(3)/(4)
- data/schemas.py VALID_ENTITY_TYPES: the ``central_bank_ecb`` data convention
  (the ``mdb_named`` precedent — a distinct entity_type value, not a new column)
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.sa import SACalculator
from rwa_calc.engine.sa.central_bank import lift_central_bank_cqs
from rwa_calc.rulebook import RulepackV0
from tests.fixtures.single_exposure import calculate_single_sa_exposure

_EAD = Decimal("1000000")
_CGCB = "CENTRAL_GOVT_CENTRAL_BANK"


@pytest.fixture
def sa_calculator() -> SACalculator:
    return SACalculator()


@pytest.fixture
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2026, 6, 30))


@pytest.fixture
def b31_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


def _rw(
    sa_calculator: SACalculator,
    config: CalculationConfig,
    *,
    entity_type: str,
    cqs: int | None = None,
    sovereign_cqs: int | None = None,
    country_code: str | None = None,
    currency: str = "EUR",
) -> float:
    result = calculate_single_sa_exposure(
        sa_calculator,
        ead=_EAD,
        exposure_class=_CGCB,
        config=config,
        entity_type=entity_type,
        cqs=cqs,
        sovereign_cqs=sovereign_cqs,
        country_code=country_code,
        currency=currency,
    )
    return result["risk_weight"]


# =========================================================================
# Art. 114(3) — ECB 0%, regime-invariant
# =========================================================================


class TestECBZeroRiskWeight:
    """Exposures to the ECB are 0% under BOTH regimes, unconditionally."""

    def test_ecb_is_zero_under_crr(
        self, sa_calculator: SACalculator, crr_config: CalculationConfig
    ) -> None:
        # Arrange / Act — supranational: no country_code, so no Art. 114(4) route
        rw = _rw(sa_calculator, crr_config, entity_type="central_bank_ecb")

        # Assert — CRR Art. 114(3); pre-fix this was the Art. 114(1) unrated 100%
        assert rw == pytest.approx(0.0)

    def test_ecb_is_zero_under_basel_3_1(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        # Arrange / Act
        rw = _rw(sa_calculator, b31_config, entity_type="central_bank_ecb")

        # Assert — PS1/26 Art. 114(3), same words; NOT Feature-gated
        assert rw == pytest.approx(0.0)

    def test_ecb_zero_overrides_a_poor_credit_assessment(
        self, sa_calculator: SACalculator, crr_config: CalculationConfig
    ) -> None:
        """Art. 114(3) is unconditional — it outranks the Table 1 CQS ladder."""
        # Arrange / Act — CQS 6 would otherwise be 150%
        rw = _rw(sa_calculator, crr_config, entity_type="central_bank_ecb", cqs=6)

        # Assert
        assert rw == pytest.approx(0.0)

    def test_ecb_zero_does_not_come_from_the_domestic_currency_branch(
        self, sa_calculator: SACalculator, crr_config: CalculationConfig
    ) -> None:
        """A plain unrated central bank on the same row shape is NOT 0%.

        This is the Art. 114(3)-vs-114(4) anti-confound: identical country
        (none) and currency (EUR), differing only in entity_type. If the 0%
        above came from ``is_domestic_currency`` this row would be 0% too.
        """
        # Arrange / Act
        rw = _rw(sa_calculator, crr_config, entity_type="central_bank")

        # Assert — Art. 114(1) unrated fallback
        assert rw == pytest.approx(1.0)


# =========================================================================
# PS1/26 Art. 114(2A) — unrated central bank takes its government's CQS
# =========================================================================


class TestUnratedCentralBankUsesSovereignCQS:
    """B31 only: an unrated central bank is weighted on its government's CQS."""

    def test_b31_unrated_central_bank_takes_sovereign_cqs_2(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        # Arrange / Act — no own ECAI rating; the US government is CQS 2
        rw = _rw(
            sa_calculator,
            b31_config,
            entity_type="central_bank",
            sovereign_cqs=2,
            country_code="US",
            currency="USD",
        )

        # Assert — Table 1 CQS 2 = 20%; pre-fix this was the unrated 100%
        assert rw == pytest.approx(0.20)

    def test_b31_unrated_central_bank_takes_sovereign_cqs_1(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        # Arrange / Act
        rw = _rw(
            sa_calculator,
            b31_config,
            entity_type="central_bank",
            sovereign_cqs=1,
            country_code="US",
            currency="USD",
        )

        # Assert — Table 1 CQS 1 = 0%
        assert rw == pytest.approx(0.0)

    def test_own_credit_assessment_outranks_the_sovereign_cqs(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Art. 114(2A) applies only where no ECAI assessment IS available."""
        # Arrange / Act — own CQS 3 (50%) alongside a CQS 1 government
        rw = _rw(
            sa_calculator,
            b31_config,
            entity_type="central_bank",
            cqs=3,
            sovereign_cqs=1,
            country_code="US",
            currency="USD",
        )

        # Assert — 50%, not the government's 0%
        assert rw == pytest.approx(0.50)

    def test_no_sovereign_rating_keeps_the_unrated_fallback(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Art. 114(2A)'s condition fails when the government is unrated too."""
        # Arrange / Act — neither rating available; nothing may be fabricated
        rw = _rw(
            sa_calculator,
            b31_config,
            entity_type="central_bank",
            country_code="US",
            currency="USD",
        )

        # Assert — Art. 114(1) 100%
        assert rw == pytest.approx(1.0)

    def test_crr_has_no_paragraph_2a_so_the_lift_must_not_fire(
        self, sa_calculator: SACalculator, crr_config: CalculationConfig
    ) -> None:
        """CRR Art. 114 runs 1, 2, 3, 4, 7 — there is no 2A."""
        # Arrange / Act — same row that gives 20% under B31
        rw = _rw(
            sa_calculator,
            crr_config,
            entity_type="central_bank",
            sovereign_cqs=2,
            country_code="US",
            currency="USD",
        )

        # Assert — the CRR unrated 100% stands
        assert rw == pytest.approx(1.0)

    def test_lift_preserves_the_int8_cqs_dtype(self, b31_config: CalculationConfig) -> None:
        """The lift must not widen ``cqs`` — ``sa_branch`` requires Int8.

        ``cp_sovereign_cqs`` is declared Int32 while ``cqs`` is Int8, so an
        uncast ``when/then/otherwise`` yields Int32 and the sa_branch edge
        contract fails on every Basel 3.1 pipeline run (the unit harness builds
        frames directly and never seals that edge, so only this pin catches it).
        """
        # Arrange
        frame = pl.LazyFrame(
            {
                "cp_entity_type": ["central_bank"],
                "cqs": pl.Series([None], dtype=pl.Int8),
                "cp_sovereign_cqs": pl.Series([2], dtype=pl.Int32),
            }
        )

        # Act
        lifted = lift_central_bank_cqs(frame, RulepackV0.from_config(b31_config).pack).collect()

        # Assert — value substituted AND dtype preserved
        assert lifted["cqs"][0] == 2
        assert lifted.schema["cqs"] == pl.Int8

    def test_sovereign_entity_type_is_out_of_scope(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Art. 114(2A) reads "exposures to a central BANK" — not a government.

        A central government's own assessment IS the one Table 1 uses, so there
        is nothing to substitute; an unrated sovereign stays at 100%.
        """
        # Arrange / Act
        rw = _rw(
            sa_calculator,
            b31_config,
            entity_type="sovereign",
            sovereign_cqs=1,
            country_code="US",
            currency="USD",
        )

        # Assert
        assert rw == pytest.approx(1.0)
