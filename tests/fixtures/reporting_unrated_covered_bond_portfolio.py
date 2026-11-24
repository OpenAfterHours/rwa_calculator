"""
Unrated covered bonds — the Art. 129(5) derivation through the full pipeline and OF 07.00.

Pipeline position:
    build_reporting_unrated_covered_bond_bundle() -> RawDataBundle
        -> PipelineOrchestrator (PermissionMode.STANDARDISED, either regime)
        -> AggregatedResultBundle -> COREPGenerator (C 07.00 / OF 07.00 covered-bond
           sheet z0013 and the Total sheet z0001)

Why this portfolio exists. Art. 129(5) weights a covered bond that has no ECAI
assessment of its own "on the basis of the risk weight assigned to senior
unsecured exposures to the institution which issues them". The rule is the
same article in both regimes, but PS1/26 widens its correspondence table from
four limbs to seven:

    PS1/26 Art. 129(5) (ps126app1.pdf pp.61-62), quoted verbatim:
        "(a) if the exposures to the institution are assigned a risk weight of
        20%, the eligible covered bonds shall be assigned a risk weight of 10%;
        (aa) [...] 30% [...] 15%; (ab) [...] 40% [...] 20%; (b) [...] 50% [...]
        25%; (ba) [...] 75% [...] 35%; (c) [...] 100% [...] 50%; or (d) [...]
        150% [...] 100%."
    UK CRR Art. 129(5): "(a) [...] 20 % [...] 10 %; (b) [...] 50 % [...] 20 %;
        (c) [...] 100 % [...] 50 %; (d) [...] 150 % [...] 100 %."

There is no "Art. 129A" — PS1/26 amends Art. 129 in place.

What this book adds to the registered estate. It is not the first registered
book with an unrated covered bond: ``rw-ladder`` (P5.50) holds two, whose issuers
carry an ECAI step (``institution_cqs`` 2 and 3), so OF 07.00 rows 0171 (15%) and
0181 (25%) already carry figures there, on the covered-bond sheet z0013 and the
Total sheet, and the Bank's rules over them (``boe_b0493`` / ``boe_b0494`` on
z0013, ``boe_b1018`` / ``boe_b1019`` on the Total sheet) already reach a verdict
on a real figure. Measured over ``RUNS`` when this book was registered, what it
adds that no other registered run reaches is:

- the SCRA arm of the Basel 3.1 derivation through the classifier. No other
  registered book has a covered bond whose counterparty carries ``scra_grade``,
  so this is the only run in which ``engine/classify/attributes.py``'s
  ``scra_grade -> cp_scra_grade`` lift feeds Art. 129(5); the unit tests of the
  arm (``tests/unit/test_covered_bonds.py``) write ``cp_scra_grade`` straight
  into the SA frame;
- the precedence legs (issuer ECAI step before SCRA grade; the bond's own
  rating before its issuer) and the issuer-unknown default (Grade C);
- covered-bond-sheet (z0013) rungs no other run populates: Basel 3.1 rows 0190
  (35%, limb (ba)), 0200 (50%) and 0230 (100%), and CRR rows 0200 (50%) and
  0230 (100%) — elsewhere the sheet carries only 0170 / 0180 (``sa-classes``)
  and 0171 / 0181 (``rw-ladder``; 0180 under CRR);
- a second route into row 0171: the SCRA A_ENHANCED leg beside the issuer CQS 2
  leg (the two-leg pattern below).

It moves no rule out of the register's vacuous section and no rule into or out
of either regime's covered set: every rule written over these rows is already
non-vacuous through another run.

## The legs

Every covered-bond counterparty is ``entity_type="covered_bond"`` with no rating
row, so ``cqs`` is null and Art. 129(5) applies; the ISSUER's standing is carried
on the counterparty in the two columns the classifier lifts: ``institution_cqs``
(the issuer's own ECAI step, Art. 120 Table 3) and ``scra_grade`` (an unrated
issuer's SCRA grade, PS1/26 Art. 121 Table 5 and paragraph 5).

    ref                  | issuer basis          | B31 issuer | B31 CB | B31 row | CRR CB | CRR row
    ---------------------|-----------------------|------------|--------|---------|--------|--------
    UCB-LN-SCRA-AE       | SCRA A_ENHANCED       |  30%       |  15%   | 0171    |  50%   | 0200
    UCB-LN-SCRA-A        | SCRA A                |  40%       |  20%   | 0180    |  50%   | 0200
    UCB-LN-SCRA-B        | SCRA B                |  75%       |  35%   | 0190    |  50%   | 0200
    UCB-LN-SCRA-C        | SCRA C                | 150%       | 100%   | 0230    |  50%   | 0200
    UCB-LN-ISSUER-NONE   | nothing known         | (Grade C)  | 100%   | 0230    |  50%   | 0200
    UCB-LN-ECAI-2        | issuer CQS 2          |  30%       |  15%   | 0171    |  20%   | 0180
    UCB-LN-ECAI-3        | issuer CQS 3          |  50%       |  25%   | 0181    |  20%   | 0180
    UCB-LN-ECAI-4        | issuer CQS 4          | 100%       |  50%   | 0200    |  50%   | 0200
    UCB-LN-ECAI-6        | issuer CQS 6          | 150%       | 100%   | 0230    | 100%   | 0230
    UCB-LN-ECAI-OVER-SCRA| issuer CQS 1 + SCRA C |  20%       |  10%   | 0170    |  10%   | 0170
    UCB-LN-OWN-RATING    | own CQS 1, issuer CQS6| Table 7    |  10%   | 0170    |  10%   | 0170
    UCB-LN-INST-ANCHOR   | institution, SCRA A_E |  30% (own) |   -    | 0182    | 100%   | 0230

Three of the legs exist for precedence, not for a weight:

- ``UCB-LN-ECAI-OVER-SCRA`` carries BOTH an issuer ECAI step and the worst SCRA
  grade. The SCRA grades are for "institutions for which a credit assessment by
  a nominated ECAI is not available" (PS1/26 Art. 121(1)), so the ECAI step
  governs: 10%, not the 100% Grade C would give.
- ``UCB-LN-OWN-RATING`` is RATED itself (CQS 1) while its issuer is CQS 6.
  Art. 129(5) applies only where "a credit assessment by a nominated ECAI is not
  available" for the bond, so Table 7 governs: 10%, not the 100% the issuer
  would give.
- ``UCB-LN-INST-ANCHOR`` is a senior unsecured loan to an INSTITUTION with the
  same issuer attributes as ``UCB-LN-SCRA-AE`` — the "senior unsecured exposure
  to the institution" Art. 129(5) names. Its weight is the engine's own issuer
  weight, so the covered bond's weight can be checked as the Art. 129(5) image
  of it rather than only against a hand table. On OF 07.00 it also lights row
  0182 (30%) on the institution and Total sheets, so "row 0182 is empty on the
  covered-bond sheet" (``boe_b0450``) is a statement about scope, not about a
  return in which no 30% figure exists anywhere.

The two-leg pattern (``.claude/LESSONS.md`` B5): row 0171 holds a leg reaching
15% through SCRA (``UCB-LN-SCRA-AE``) beside one reaching it through the issuer
ECAI step (``UCB-LN-ECAI-2``), so a defect in either lift MOVES one leg out of
the row and leaves the other, and "the row was zeroed" is distinguishable from
"one leg moved".

## The CRR arm, and what it deliberately does NOT carry

Under CRR the SCRA grade is not an input — Art. 121(1) weights an unrated
institution by its home sovereign's credit quality step, and Art. 121(2) gives
100% to "unrated institutions incorporated in countries where the central
government is unrated". No leg here carries
``sovereign_cqs``, so every unrated-issuer leg takes the 100% issuer weight and
limb (c), 50% — and the CRR institution anchor takes the same 100%, which keeps
the CRR covered-bond weights consistent with the engine's own issuer weight.
A leg that carried ``sovereign_cqs`` would expose a separate CRR question (the
covered-bond arm never reads the sovereign-derived issuer weight; P5.12 audit,
``crr_position``) that this portfolio is not built to answer.

## What it is NOT

- Not an IRB book: no model permission is supplied and the registered runs use
  ``PermissionMode.STANDARDISED``. Covered bonds held under an IRB permission are
  the subject of open item P1.322, and a book that routed them would pin that
  item's current behaviour.
- Not a CCF / CRM book: every leg is a drawn, unsecured, unguaranteed GBP loan,
  so every C 07.00 cell reduces to EAD x RW.

References:
- UK CRR Art. 129(4)-(5), Art. 120 Table 3, Art. 121(1)-(2)
- PRA PS1/26 Art. 129(4)-(5), Art. 120 Table 3, Art. 121 Table 5 and para. 5
- PRA PS1/26 Annex II, OF 07.00 rows 0170-0230 (p.95); para. 70 (covered-bond class)
"""

from __future__ import annotations

from datetime import date

import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import COUNTERPARTY_SCHEMA, LOAN_SCHEMA, RATINGS_SCHEMA
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Scenario constants — the single source of truth for test assertions.
# ---------------------------------------------------------------------------

#: Unrated covered bonds whose issuer is itself unrated: the SCRA limbs.
LN_SCRA_A_ENHANCED: str = "UCB-LN-SCRA-AE"
LN_SCRA_A: str = "UCB-LN-SCRA-A"
LN_SCRA_B: str = "UCB-LN-SCRA-B"
LN_SCRA_C: str = "UCB-LN-SCRA-C"
#: Unrated covered bond whose issuer carries neither an ECAI step nor a grade.
LN_ISSUER_NONE: str = "UCB-LN-ISSUER-NONE"
#: Unrated covered bonds whose issuer is rated by an ECAI: the Table 3 limbs.
LN_ECAI_2: str = "UCB-LN-ECAI-2"
LN_ECAI_3: str = "UCB-LN-ECAI-3"
LN_ECAI_4: str = "UCB-LN-ECAI-4"
LN_ECAI_6: str = "UCB-LN-ECAI-6"
#: Precedence: issuer ECAI step 1 beside the worst SCRA grade.
LN_ECAI_OVER_SCRA: str = "UCB-LN-ECAI-OVER-SCRA"
#: Precedence: the covered bond's OWN rating (CQS 1) beside an issuer at CQS 6.
LN_OWN_RATING: str = "UCB-LN-OWN-RATING"
#: The senior unsecured exposure to an institution with ``LN_SCRA_A_ENHANCED``'s
#: issuer attributes.
LN_INSTITUTION_ANCHOR: str = "UCB-LN-INST-ANCHOR"

#: Each leg's issuer attributes, as the counterparty carries them.
_ISSUER_ATTRIBUTES: dict[str, dict[str, object]] = {
    LN_SCRA_A_ENHANCED: {"scra_grade": "A_ENHANCED"},
    LN_SCRA_A: {"scra_grade": "A"},
    LN_SCRA_B: {"scra_grade": "B"},
    LN_SCRA_C: {"scra_grade": "C"},
    LN_ISSUER_NONE: {},
    LN_ECAI_2: {"institution_cqs": 2},
    LN_ECAI_3: {"institution_cqs": 3},
    LN_ECAI_4: {"institution_cqs": 4},
    LN_ECAI_6: {"institution_cqs": 6},
    LN_ECAI_OVER_SCRA: {"institution_cqs": 1, "scra_grade": "C"},
    LN_OWN_RATING: {"institution_cqs": 6},
    LN_INSTITUTION_ANCHOR: {"scra_grade": "A_ENHANCED"},
}

#: The one covered bond that carries its own ECAI assessment (Art. 129(4) Table 7).
OWN_RATING_CQS: int = 1

#: Drawn amounts in GBP, EAD = drawn. Distinct per leg, and chosen so that every
#: OF 07.00 row total and every ``drawn x rw`` differs from every other, so a leg
#: on the wrong row is identifiable from one cell without a reverse lookup.
DRAWN: dict[str, float] = {
    LN_SCRA_A_ENHANCED: 1_200_000.0,
    LN_SCRA_A: 2_400_000.0,
    LN_SCRA_B: 3_600_000.0,
    LN_SCRA_C: 4_800_000.0,
    LN_ISSUER_NONE: 5_200_000.0,
    LN_ECAI_2: 6_000_000.0,
    LN_ECAI_3: 7_000_000.0,
    LN_ECAI_4: 8_000_000.0,
    LN_ECAI_6: 1_100_000.0,
    LN_ECAI_OVER_SCRA: 1_500_000.0,
    LN_OWN_RATING: 2_500_000.0,
    LN_INSTITUTION_ANCHOR: 3_300_000.0,
}

#: Every covered-bond leg (everything but the institution anchor).
COVERED_BOND_REFERENCES: tuple[str, ...] = tuple(
    reference for reference in DRAWN if reference != LN_INSTITUTION_ANCHOR
)

#: The applied risk weight each leg must resolve to: (CRR, Basel 3.1). Hand values
#: from the rule text (module docstring), never read back from the rulepack.
EXPECTED_RW: dict[str, tuple[float, float]] = {
    # SCRA limbs: CRR has no SCRA, so an unrated issuer with no sovereign_cqs takes
    # Art. 121(2) 100% -> limb (c) 50%. PS1/26 Table 5 / para. 5 -> 129(5).
    LN_SCRA_A_ENHANCED: (0.50, 0.15),  # B31 30% -> (aa)
    LN_SCRA_A: (0.50, 0.20),  # B31 40% -> (ab)
    LN_SCRA_B: (0.50, 0.35),  # B31 75% -> (ba)
    LN_SCRA_C: (0.50, 1.00),  # B31 150% -> (d)
    LN_ISSUER_NONE: (0.50, 1.00),  # B31: no grade -> the Grade C weight -> (d)
    # Issuer ECAI limbs, Art. 120 Table 3: CRR 20/50/50/100/100/150, B31 20/30/50/100/100/150.
    LN_ECAI_2: (0.20, 0.15),  # CRR 50% -> (b) 20%; B31 30% -> (aa) 15%
    LN_ECAI_3: (0.20, 0.25),  # CRR 50% -> (b) 20%; B31 50% -> (b) 25%
    LN_ECAI_4: (0.50, 0.50),  # 100% -> (c)
    LN_ECAI_6: (1.00, 1.00),  # 150% -> (d)
    # Precedence legs.
    LN_ECAI_OVER_SCRA: (0.10, 0.10),  # issuer CQS 1, 20% -> (a); the grade is not read
    LN_OWN_RATING: (0.10, 0.10),  # Art. 129(4) Table 7 CQS 1; the issuer is not read
    # The issuer anchor: CRR Art. 121(2) 100%; PS1/26 Art. 121(5) 30%.
    LN_INSTITUTION_ANCHOR: (1.00, 0.30),
}

#: The OF 07.00 / C 07.00 "Breakdown by risk weights" row each leg must land on:
#: (CRR row, Basel 3.1 row). Rows 0171 / 0181 / 0190 are the PS1/26-only rungs.
EXPECTED_ROW: dict[str, tuple[str, str]] = {
    LN_SCRA_A_ENHANCED: ("0200", "0171"),
    LN_SCRA_A: ("0200", "0180"),
    LN_SCRA_B: ("0200", "0190"),
    LN_SCRA_C: ("0200", "0230"),
    LN_ISSUER_NONE: ("0200", "0230"),
    LN_ECAI_2: ("0180", "0171"),
    LN_ECAI_3: ("0180", "0181"),
    LN_ECAI_4: ("0200", "0200"),
    LN_ECAI_6: ("0230", "0230"),
    LN_ECAI_OVER_SCRA: ("0170", "0170"),
    LN_OWN_RATING: ("0170", "0170"),
    LN_INSTITUTION_ANCHOR: ("0230", "0182"),
}

_VALUE_DATE: date = date(2020, 1, 1)
_MATURITY: date = date(2031, 12, 31)  # > both reporting dates; not short-term (Art. 121(4))


# ---------------------------------------------------------------------------
# Main public entry point
# ---------------------------------------------------------------------------


def build_reporting_unrated_covered_bond_bundle() -> RawDataBundle:
    """Assemble the unrated covered-bond book as a sealed ``RawDataBundle``.

    Run it through ``PipelineOrchestrator().run_with_data`` under either regime
    with ``PermissionMode.STANDARDISED``: no model permission is supplied, and
    every leg is SA (see "What it is NOT" in the module docstring).
    """
    return make_raw_bundle(
        counterparties=_counterparties(),
        loans=_loans(),
        ratings=_ratings(),
    )


# ---------------------------------------------------------------------------
# Table builders (private)
# ---------------------------------------------------------------------------


def _counterparties() -> pl.DataFrame:
    """One obligor per leg, carrying its issuer's standing; GB, so no FX floor applies."""
    rows: list[dict] = [
        {
            "counterparty_reference": _counterparty(reference),
            "entity_type": "institution" if reference == LN_INSTITUTION_ANCHOR else "covered_bond",
            "country_code": "GB",
            **attributes,
        }
        for reference, attributes in _ISSUER_ATTRIBUTES.items()
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(COUNTERPARTY_SCHEMA))


def _ratings() -> pl.DataFrame:
    """The single ECAI assessment in the book: ``LN_OWN_RATING``'s own, CQS 1.

    Every other covered bond is unrated on purpose — that is what puts it on
    Art. 129(5). An issuer's ECAI step is NOT a rating row of the covered bond: it
    is the counterparty's ``institution_cqs``.
    """
    rows: list[dict] = [
        {
            "rating_reference": f"UCB-RTG-{LN_OWN_RATING}",
            "counterparty_reference": _counterparty(LN_OWN_RATING),
            "rating_type": "external",
            "rating_agency": "TEST_AGENCY",
            "cqs": OWN_RATING_CQS,
            "rating_date": _VALUE_DATE,
        }
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(RATINGS_SCHEMA))


def _loans() -> pl.DataFrame:
    """One fully drawn senior GBP term loan per leg; EAD = drawn."""
    rows: list[dict] = [
        {
            "loan_reference": reference,
            "counterparty_reference": _counterparty(reference),
            "product_type": "term_loan",
            "drawn_amount": drawn,
            "currency": "GBP",
            "value_date": _VALUE_DATE,
            "maturity_date": _MATURITY,
            "seniority": "senior",
        }
        for reference, drawn in DRAWN.items()
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(LOAN_SCHEMA))


def _counterparty(loan_reference: str) -> str:
    """The obligor of one leg: ``UCB-LN-X`` is lent to ``UCB-CP-X``."""
    return loan_reference.replace("-LN-", "-CP-", 1)
