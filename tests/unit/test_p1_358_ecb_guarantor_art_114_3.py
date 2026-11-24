"""
Unit pins — P1.358: an ECB guarantor takes the Art. 114(3) 0%, not the CGCB Table 1 ladder.

Pipeline position:
    engine/sa/guarantor_rw.py::build_guarantor_rw_expr — the one guarantor
    risk-weight chain, compiled by the SA substitution path
    (engine/sa/rw_adjustments.py::apply_guarantee_substitution, which slotting
    delegates to and which the Basel 3.1 output floor's SA-equivalent runs for
    every row) and by the IRB risk-weight substitution fallback
    (engine/irb/guarantee.py::_compute_guarantor_rw_sa).

The rule, read verbatim
-----------------------
PS1/26 Art. 114(3) (ps126app1.pdf p.36): "Exposures to the European Central Bank
shall be assigned a 0% risk weight." UK CRR Art. 114(3) (legislation.gov.uk,
revised text, article/114/data.xml): "Exposures to the ECB shall be assigned a
0 % risk weight." No currency limb, no rating limb, in either regime.

Art. 235(1) prices the covered part at the risk weight of a (comparable) direct
exposure to the protection provider — CRR: "g the risk weight of exposures to
the protection provider as specified under Chapter 2"; PS1/26 235(1)(a): "rg =
the risk weight of a comparable direct exposure to the protection provider".
Art. 235(3) restricts only the 114(4) / 114(7) domestic-currency treatments
("Institutions may extend the treatment set out in Article 114(4) and (7) ..."
in CRR; "paragraph 4 of ... Article 114 and Article 114(7) of CRR" in PS1/26),
so it never reaches 114(3). Art. 201(1)(a) makes central banks eligible
providers in both regimes.

The defect
----------
``build_guarantor_rw_expr`` had no ECB branch. ``central_bank_ecb`` maps to the
``central_govt_central_bank`` class, so an ECB guarantor fell onto the Art. 114(2)
Table 1 CQS ladder: 100% unrated, 20% / 50% / 150% at CQS 2 / 3 / 6. It reached 0%
only by accident — at CQS 1, or through the 114(7) EU-domestic branch when tagged
with a euro-area country AND guaranteed and funded in EUR. Under the strict ``<``
Art. 193(1) benefit test an unrated ECB guarantee on a 100%-weighted borrower was
therefore DECLINED outright.

What each test proves
---------------------
- The builder pins are run with no domestic expression, so country and currency
  cannot reach them; they prove the CQS-independence of the 0%.
- The Art. 235(3) independence needs the domestic predicate bound, so it runs
  through the SA ``apply_guarantee_substitution``: a DE-tagged ECB guarantee in
  EUR on a USD-FUNDED exposure fails the 235(3) funding limb (shown by a generic
  ``central_bank`` control on the same row, which stays on Table 1) and must
  still be 0%.
- Two negative guards stop the branch widening: a generic ``central_bank`` keeps
  Table 1, and a loan TO the ECB keeps its guarantor's own weight (a corporate,
  and a generic central bank in the ECB's own class) — the obligor-keyed
  ``is_ecb_expr()`` reads ``cp_entity_type``, and reusing it unchanged here would
  zero the wrong side of the guarantee.
- A declined guarantor (class cleared by the Art. 201 gate) still prices nothing.

Every parametrised test carries a ``crr`` and a ``b31`` id; run each id on its
own to see that each regime fails separately (LESSONS C7). Expected values are
hand-pinned from the rule text and anchored to the rulepack by
``test_p1_358_scenario_scalars_match_the_rulepack``, never read from the engine.

References:
- CRR Art. 114(1)-(3), 201(1)(a), 235(1), 235(3)
- PS1/26 Art. 114(1)-(3), 201(1)(a), 235(1)(a), 235(3)
- CRR Art. 122 Table 5 / PS1/26 Art. 122(2) Table 6 (corporate CQS 3: 100% / 75%)
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import CQS, ExposureClass
from rwa_calc.engine.irb.guarantee import (
    apply_guarantee_substitution as apply_irb_guarantee_substitution,
)
from rwa_calc.engine.sa.guarantor_rw import build_guarantor_rw_expr
from rwa_calc.engine.sa.rw_adjustments import (
    apply_guarantee_substitution as apply_sa_guarantee_substitution,
)
from rwa_calc.rulebook.resolve import resolve

# ---------------------------------------------------------------------------
# Hand-pinned expectations (from the rule text; anchored to the pack below)
# ---------------------------------------------------------------------------

REGIMES: tuple[str, ...] = ("crr", "b31")

ECB_ENTITY_TYPE = "central_bank_ecb"
CENTRAL_BANK_ENTITY_TYPE = "central_bank"
CGCB_CLASS = "central_govt_central_bank"

#: Art. 114(3), both regimes.
ECB_ZERO_RW: float = 0.0
#: Art. 114(1) unrated central government / central bank.
CGCB_UNRATED_RW: float = 1.00
#: Art. 114(2) Table 1, both regimes.
CGCB_TABLE_1: dict[int, float] = {1: 0.0, 2: 0.20, 3: 0.50, 6: 1.50}
#: CRR Art. 122 Table 5 / PS1/26 Art. 122(2) Table 6 at CQS 3.
CORPORATE_CQS3_RW: dict[str, float] = {"crr": 1.00, "b31": 0.75}

EAD: float = 1_000_000.0
COVERED: float = 500_000.0
#: An unrated corporate borrower: CRR Art. 122(2) / PS1/26 Art. 122(2), 100%.
BORROWER_RW: float = 1.00
#: Above the ECB's 0% and below its old 100% unrated weight, so the IRB leg is
#: beneficial after the fix and declined before it.
IRB_BORROWER_RW: float = 0.80

_REPORTING_DATE: dict[str, date] = {"crr": date(2026, 6, 30), "b31": date(2027, 6, 30)}


def _config(regime: str) -> CalculationConfig:
    if regime == "crr":
        return CalculationConfig.crr(reporting_date=_REPORTING_DATE["crr"])
    return CalculationConfig.basel_3_1(reporting_date=_REPORTING_DATE["b31"])


# ---------------------------------------------------------------------------
# Pack anchor
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("regime", REGIMES)
def test_p1_358_scenario_scalars_match_the_rulepack(regime: str) -> None:
    """Every hand-pinned weight in this module is the resolved pack's value.

    Arrange: the run pack for the regime, and the CRR pack that carries the
             Art. 114(2) Table 1 ``cgcb_risk_weights`` the guarantor chain reads
             for both regimes (PS1/26 Table 1 is identical).
    Act:     read ``ecb_zero_rw`` and the Table 1 entries.
    Assert:  they equal this module's constants, so a pack change fails here
             first rather than silently moving the expectations below.
    """
    # Arrange
    pack = resolve(regime, _REPORTING_DATE[regime])
    crr_pack = resolve("crr", _REPORTING_DATE["crr"])

    # Act
    ecb = pack.scalar_param("ecb_zero_rw").value
    table_1 = dict(crr_pack.lookup("cgcb_risk_weights").entries)

    # Assert
    assert ecb == Decimal(str(ECB_ZERO_RW))
    assert float(table_1[CQS.UNRATED]) == CGCB_UNRATED_RW
    for cqs, rw in CGCB_TABLE_1.items():
        assert float(table_1[CQS(cqs)]) == rw, f"Table 1 CQS {cqs}"


# ---------------------------------------------------------------------------
# Builder — the shared chain, evaluated on one guarantor row
# ---------------------------------------------------------------------------


def _evaluate_guarantor_rw(
    *,
    regime: str,
    entity_type: str,
    cqs: int | None,
    exposure_class: str | None = CGCB_CLASS,
) -> float | None:
    """Evaluate ``build_guarantor_rw_expr`` for one guarantor row, no domestic test."""
    frame = pl.LazyFrame(
        {
            "guarantor_exposure_class": [exposure_class],
            "guarantor_entity_type": [entity_type],
            "guarantor_cqs": [cqs],
            "guarantor_country_code": [None],
            "guarantor_is_equivalent_jurisdiction": [None],
            "guarantor_scra_grade": [None],
        },
        schema_overrides={
            "guarantor_exposure_class": pl.String,
            "guarantor_cqs": pl.Int8,
            "guarantor_country_code": pl.String,
            "guarantor_is_equivalent_jurisdiction": pl.Boolean,
            "guarantor_scra_grade": pl.String,
        },
    )
    expr = build_guarantor_rw_expr(
        exposure_class_col="guarantor_exposure_class",
        entity_type_col="guarantor_entity_type",
        cqs_col="guarantor_cqs",
        country_code_col="guarantor_country_code",
        equivalence_col="guarantor_is_equivalent_jurisdiction",
        scra_grade_col="guarantor_scra_grade",
        is_basel_3_1=regime == "b31",
    )
    return frame.select(expr.alias("guarantor_rw")).collect()["guarantor_rw"][0]


class TestBuilderPricesTheEcbAtArt1143:
    """The chain gives an ECB guarantor 0% whatever its credit quality step."""

    @pytest.mark.parametrize("regime", REGIMES)
    @pytest.mark.parametrize("cqs", [None, 2, 3, 6], ids=["unrated", "cqs2", "cqs3", "cqs6"])
    def test_ecb_guarantor_is_zero_weighted_at_every_cqs(
        self, regime: str, cqs: int | None
    ) -> None:
        """Art. 114(3) carries no rating limb, so no CQS moves the ECB off 0%.

        Arrange: an ECB guarantor row in the CGCB class with the given CQS.
        Act:     build_guarantor_rw_expr.
        Assert:  0.0.

        Pre-fix: the Art. 114(2) Table 1 weight — 1.00 unrated, 0.20 / 0.50 /
        1.50 at CQS 2 / 3 / 6. CQS 1 is left out: Table 1 gives it 0% too, so it
        cannot tell the branch from the ladder.
        """
        # Arrange / Act
        rw = _evaluate_guarantor_rw(regime=regime, entity_type=ECB_ENTITY_TYPE, cqs=cqs)

        # Assert
        assert rw is not None, f"{regime}: an ECB guarantor priced no risk weight at all"
        assert rw == pytest.approx(ECB_ZERO_RW, abs=1e-12), (
            f"{regime}: Art. 114(3) gives the ECB 0% unconditionally; got {rw:.4f}, "
            "which is the Art. 114(2) Table 1 / Art. 114(1) unrated CGCB weight."
        )

    @pytest.mark.parametrize("regime", REGIMES)
    @pytest.mark.parametrize(
        ("cqs", "expected"),
        [(None, CGCB_UNRATED_RW), (3, CGCB_TABLE_1[3])],
        ids=["unrated", "cqs3"],
    )
    def test_a_generic_central_bank_stays_on_table_1(
        self, regime: str, cqs: int | None, expected: float
    ) -> None:
        """Control: the branch is the ECB's alone, not every central bank's.

        Arrange: a ``central_bank`` guarantor (not the ECB), same class.
        Act:     build_guarantor_rw_expr.
        Assert:  the Table 1 / unrated weight, unchanged by the fix.
        """
        # Arrange / Act
        rw = _evaluate_guarantor_rw(regime=regime, entity_type=CENTRAL_BANK_ENTITY_TYPE, cqs=cqs)

        # Assert
        assert rw == pytest.approx(expected, abs=1e-12), (
            f"{regime}: a non-ECB central bank must keep Art. 114(1)/(2); got {rw!r}"
        )

    @pytest.mark.parametrize("regime", REGIMES)
    @pytest.mark.parametrize("exposure_class", ["", None], ids=["cleared", "null"])
    def test_a_declined_ecb_guarantor_prices_nothing(
        self, regime: str, exposure_class: str | None
    ) -> None:
        """Control: the Art. 201 gate declines by clearing the class; that still wins.

        Arrange: an ECB entity type whose guarantor class is cleared or null.
        Act:     build_guarantor_rw_expr.
        Assert:  null — no substitution (P1.395: an entity-type branch must also
                 require a class).
        """
        # Arrange / Act
        rw = _evaluate_guarantor_rw(
            regime=regime, entity_type=ECB_ENTITY_TYPE, cqs=None, exposure_class=exposure_class
        )

        # Assert
        assert rw is None, f"{regime}: a declined ECB guarantor must price no RW, got {rw!r}"


# ---------------------------------------------------------------------------
# SA path — apply_guarantee_substitution binds the domestic test
# ---------------------------------------------------------------------------


def _sa_guaranteed_row(
    *,
    regime: str,
    guarantor_entity_type: str,
    guarantor_cqs: int | None = None,
    guarantor_country_code: str | None = None,
    guarantee_currency: str = "GBP",
    currency: str = "GBP",
    funding_currency: str | None = None,
    borrower_entity_type: str = "corporate",
    borrower_rw: float = BORROWER_RW,
) -> dict[str, Any]:
    """Run the SA substitution on a 1m exposure, 500k covered by one guarantor."""
    frame = pl.LazyFrame(
        {
            "exposure_reference": ["P1358-EXP"],
            "exposure_class": ["corporate"],
            "cp_entity_type": [borrower_entity_type],
            "ead_final": [EAD],
            "risk_weight": [borrower_rw],
            "guaranteed_portion": [COVERED],
            "unguaranteed_portion": [EAD - COVERED],
            "guarantor_entity_type": [guarantor_entity_type],
            "guarantor_cqs": [guarantor_cqs],
            "guarantor_country_code": [guarantor_country_code],
            "guarantee_currency": [guarantee_currency],
            "currency": [currency],
            "funding_currency": [funding_currency],
        },
        schema_overrides={
            "guarantor_cqs": pl.Int8,
            "guarantor_country_code": pl.String,
            "funding_currency": pl.String,
        },
    )
    return apply_sa_guarantee_substitution(frame, _config(regime)).collect().to_dicts()[0]


class TestSaSubstitutionAppliesTheEcbZero:
    """Through the SA path the ECB 0% makes the guarantee beneficial and applies it."""

    @pytest.mark.parametrize("regime", REGIMES)
    def test_unrated_ecb_guarantee_substitutes_at_zero(self, regime: str) -> None:
        """An unrated ECB guarantee on a 100% borrower: covered half at 0%.

        Arrange: unrated corporate borrower at 100%, EAD 1,000,000, 500,000
                 guaranteed by an unrated ECB (no country), GBP throughout.
        Act:     SA apply_guarantee_substitution.
        Assert:  guarantor RW 0.0, substituted, blended RW 0.50, RWA 500,000.

        Pre-fix: guarantor RW 1.00 (Table 1 unrated) — not below the borrower's
        1.00, so the strict Art. 193(1) test DECLINES the guarantee:
        GUARANTEE_NOT_APPLIED_NON_BENEFICIAL, RW 1.00, RWA 1,000,000.
        """
        # Arrange / Act
        row = _sa_guaranteed_row(regime=regime, guarantor_entity_type=ECB_ENTITY_TYPE)

        # Assert
        assert row["ead_final"] == pytest.approx(EAD), "a zero EAD makes every RWA claim vacuous"
        assert row["guarantor_rw"] == pytest.approx(ECB_ZERO_RW, abs=1e-12), (
            f"{regime}: ECB guarantor RW should be 0% (Art. 114(3) via Art. 235(1)); "
            f"got {row['guarantor_rw']!r}"
        )
        assert row["is_guarantee_beneficial"] is True
        assert row["guarantee_status"] == "SA_RW_SUBSTITUTION"
        assert row["risk_weight"] == pytest.approx(0.50, abs=1e-12)
        assert row["risk_weight"] * row["ead_final"] == pytest.approx(500_000.0, abs=1e-6), (
            "expected RWA 500,000 = 500,000 x 100% uncovered + 500,000 x 0% covered"
        )

    @pytest.mark.parametrize("regime", REGIMES)
    def test_ecb_zero_does_not_need_the_art_235_3_domestic_limbs(self, regime: str) -> None:
        """DE-tagged ECB, EUR guarantee, USD-funded exposure: still 0%.

        Art. 235(3) restricts only the 114(4)/(7) domestic-currency treatments;
        this row FAILS its funding limb, so any 0% it gets must come from 114(3).

        Arrange: unrated ECB guarantor tagged DE, guarantee and exposure in EUR,
                 exposure funded in USD.
        Act:     SA apply_guarantee_substitution.
        Assert:  guarantor RW 0.0, substituted.

        Pre-fix: the 114(7) EU-domestic branch is refused (USD funding), so the
        row falls to Table 1 unrated — 1.00 — and the guarantee is declined.
        """
        # Arrange / Act
        row = _sa_guaranteed_row(
            regime=regime,
            guarantor_entity_type=ECB_ENTITY_TYPE,
            guarantor_country_code="DE",
            guarantee_currency="EUR",
            currency="EUR",
            funding_currency="USD",
        )

        # Assert
        assert row["guarantor_rw"] == pytest.approx(ECB_ZERO_RW, abs=1e-12), (
            f"{regime}: the ECB's 0% is Art. 114(3), which Art. 235(3) does not "
            f"condition on currency or funding; got {row['guarantor_rw']!r}"
        )
        assert row["guarantee_status"] == "SA_RW_SUBSTITUTION"

    @pytest.mark.parametrize("regime", REGIMES)
    @pytest.mark.parametrize(
        ("funding_currency", "expected"),
        [("USD", CGCB_UNRATED_RW), ("EUR", 0.0)],
        ids=["usd_funded_fails_235_3", "eur_funded_is_domestic"],
    )
    def test_the_same_row_for_a_generic_central_bank_obeys_art_235_3(
        self, regime: str, funding_currency: str, expected: float
    ) -> None:
        """Adequacy control for the test above: the funding limb really bites.

        Arrange: the same DE / EUR row with a generic ``central_bank`` guarantor.
        Act:     SA apply_guarantee_substitution.
        Assert:  USD-funded -> Table 1 unrated 100%; EUR-funded -> the 114(7)
                 EU-domestic 0%. Green before and after the fix — it proves the
                 ECB row above is not reaching 0% through 114(7).
        """
        # Arrange / Act
        row = _sa_guaranteed_row(
            regime=regime,
            guarantor_entity_type=CENTRAL_BANK_ENTITY_TYPE,
            guarantor_country_code="DE",
            guarantee_currency="EUR",
            currency="EUR",
            funding_currency=funding_currency,
        )

        # Assert
        assert row["guarantor_rw"] == pytest.approx(expected, abs=1e-12)

    @pytest.mark.parametrize("regime", REGIMES)
    @pytest.mark.parametrize(
        ("guarantor_entity_type", "expected"),
        [("corporate", CORPORATE_CQS3_RW), (CENTRAL_BANK_ENTITY_TYPE, None)],
        ids=["corporate_cqs3", "central_bank_cqs3"],
    )
    def test_a_loan_to_the_ecb_keeps_its_guarantors_own_weight(
        self, regime: str, guarantor_entity_type: str, expected: dict[str, float] | None
    ) -> None:
        """Negative guard: the branch keys on the GUARANTOR, never the obligor.

        ``is_ecb_expr()`` reads ``cp_entity_type`` — the obligor. Reused unchanged
        in the guarantor chain it would zero a guarantee ON a loan to the ECB
        rather than one BY the ECB. The central-bank case is the sharper guard:
        its class is the ECB's class, so only the entity-type column separates
        the two.

        Arrange: obligor ``central_bank_ecb`` (0% direct), guarantor a CQS 3
                 corporate or a CQS 3 generic central bank.
        Act:     SA apply_guarantee_substitution.
        Assert:  the guarantor's own CQS 3 weight — corporate CRR Table 5 100% /
                 PS1/26 Table 6 75%; central bank Table 1 50% — never 0%.
        """
        # Arrange
        want = expected[regime] if expected is not None else CGCB_TABLE_1[3]

        # Act
        row = _sa_guaranteed_row(
            regime=regime,
            guarantor_entity_type=guarantor_entity_type,
            guarantor_cqs=3,
            borrower_entity_type=ECB_ENTITY_TYPE,
            borrower_rw=ECB_ZERO_RW,
        )

        # Assert
        assert row["guarantor_rw"] == pytest.approx(want, abs=1e-12), (
            f"{regime}: a {guarantor_entity_type} guarantor of a loan TO the ECB must "
            f"keep its own weight {want}; got {row['guarantor_rw']!r}"
        )


# ---------------------------------------------------------------------------
# IRB path — the risk-weight substitution fallback compiles the same chain
# ---------------------------------------------------------------------------


def _irb_guaranteed_row(*, regime: str, guarantor_entity_type: str) -> dict[str, Any]:
    """Run the IRB substitution on a fully covered F-IRB row with an SA guarantor."""
    frame = pl.LazyFrame(
        {
            "exposure_reference": ["P1358-IRB"],
            "pd": [0.05],
            "lgd": [0.45],
            "ead_final": [EAD],
            "maturity": [2.5],
            "exposure_class": [ExposureClass.CORPORATE.value],
            "rwa": [IRB_BORROWER_RW * EAD],
            "risk_weight": [IRB_BORROWER_RW],
            "guaranteed_portion": [EAD],
            "unguaranteed_portion": [0.0],
            "guarantor_entity_type": [guarantor_entity_type],
            "guarantor_cqs": [None],
            "guarantor_approach": ["sa"],
            "guarantor_pd": [None],
        },
        schema_overrides={"guarantor_cqs": pl.Int8, "guarantor_pd": pl.Float64},
    )
    return apply_irb_guarantee_substitution(frame, _config(regime)).collect().to_dicts()[0]


class TestIrbRiskWeightSubstitutionAppliesTheEcbZero:
    """``_compute_guarantor_rw_sa`` compiles the shared chain, so it gains the branch."""

    @pytest.mark.parametrize("regime", REGIMES)
    def test_unrated_ecb_guarantor_substitutes_at_zero_on_an_irb_row(self, regime: str) -> None:
        """An F-IRB row at 80% fully covered by an unrated ECB: RWA 0.

        Arrange: F-IRB corporate row, IRB RW 0.80, EAD 1,000,000 fully covered
                 by an unrated ECB guarantor routed to the SA (``guarantor_approach``
                 "sa").
        Act:     IRB apply_guarantee_substitution.
        Assert:  ``guarantor_rw`` (``guarantor_rw_sa`` on an SA-approach
                 guarantor; the scratch column itself is dropped) 0.0, RWA 0.

        Pre-fix: guarantor RW 1.00 >= 0.80, so the guarantee is declined and the
        row keeps its 800,000 IRB RWA.
        """
        # Arrange / Act
        row = _irb_guaranteed_row(regime=regime, guarantor_entity_type=ECB_ENTITY_TYPE)

        # Assert
        assert row["guarantor_rw"] == pytest.approx(ECB_ZERO_RW, abs=1e-12), (
            f"{regime}: IRB RWSM fallback should price the ECB at 0%; got {row['guarantor_rw']!r}"
        )
        assert row["guarantee_status"] == "SA_RW_SUBSTITUTION"
        assert row["rwa"] == pytest.approx(0.0, abs=1e-6), (
            f"{regime}: a fully ECB-covered row carries no RWA; got {row['rwa']!r}"
        )

    @pytest.mark.parametrize("regime", REGIMES)
    def test_a_generic_central_bank_guarantor_is_still_declined(self, regime: str) -> None:
        """Control: an unrated generic central bank stays at 100% and is declined.

        Arrange: the same row with a ``central_bank`` guarantor.
        Act:     IRB apply_guarantee_substitution.
        Assert:  guarantor RW 1.00, RWA stays 800,000.
        """
        # Arrange / Act
        row = _irb_guaranteed_row(regime=regime, guarantor_entity_type=CENTRAL_BANK_ENTITY_TYPE)

        # Assert
        assert row["guarantor_rw"] == pytest.approx(CGCB_UNRATED_RW, abs=1e-12)
        assert row["rwa"] == pytest.approx(IRB_BORROWER_RW * EAD, abs=1e-6)
