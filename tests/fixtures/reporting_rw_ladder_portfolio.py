"""
SA risk-weight ladder — one leg per C 07.00 / OF 07.00 rung no other registered run reaches.

Pipeline position:
    build_reporting_rw_ladder_bundle() -> RawDataBundle
        -> PipelineOrchestrator (PermissionMode.STANDARDISED, ``rw_ladder_config``)
        -> AggregatedResultBundle -> COREPGenerator (C 07.00 / OF 07.00 rows 0140-0280)

Why this portfolio exists
-------------------------
C 07.00 / OF 07.00 rows 0140-0280 break each exposure-class sheet down by the
risk weight, and the published rules write one identity per row: RWEA (col
0220) equals exposure value (col 0200) times the weight the row's label names.
The Bank publishes that identity twice: as an equality (``boe_b0475``-
``boe_b0507``, ``boe_b0771``) on the class sheets and as ``>=``
(``boe_b1007``-``boe_b1032``) on the Total, retail and real-estate sheets. The
EBA's CRR set is ``v0316_m``-``v0328_m``, ``v4751_m`` and ``v4752_m``. A row
that carries no figure satisfies its identity at ``0 = 0``, so the rule is
VACUOUS: it holds and checks nothing (``.claude/LESSONS.md`` B5). Before this
portfolio, every registered run left these Basel 3.1 rungs dark: 15%, 25%, 40%,
45%, 65%, 80%, 105%, 130% and 135%. Under CRR it left 250% and 1250% dark. No
amount of depth on the other portfolios could reach them: they belong to class
weights none of those portfolios uses.

The legs. Every leg is one drawn, unhedged, unsplit exposure whose applied
weight IS the rung, so its row carries ``c0220 = c0200 x w`` exactly:

    leg                  | basis (PS1/26; CRR)                         | z    | CRR        | Basel 3.1
    ---------------------|---------------------------------------------|------|------------|----------
    RWL-LN-INST-SCRA-A   | Art. 121 SCRA grade A; 121(2) no sovereign  | 0007 |  100% 0230 |  40% 0191
    RWL-LN-COVBOND-15    | Art. 129(5)(aa) issuer 30%; (b) issuer 50%  | 0013 |   20% 0180 |  15% 0171
    RWL-LN-COVBOND-25    | Art. 129(5)(b) issuer 50%; (b) issuer 50%   | 0013 |   20% 0180 |  25% 0181
    RWL-LN-CORP-IG       | Art. 122(6)(a) investment grade; 122(1)     | 0008 |  100% 0230 |  65% 0202
    RWL-LN-CORP-NIG      | Art. 122(6)(b) not investment grade; 122(1) | 0008 |  100% 0230 | 135% 0234
    RWL-LN-PF-HQ         | Art. 122B(4) high-quality operational PF    | 0008 |  100% 0230 |  80% 0221
    RWL-LN-PF-PRE        | Art. 122B(2)(c) pre-operational PF          | 0008 |  100% 0230 | 130% 0233
    RWL-LN-RETAIL-QRRE   | Art. 123(3)(a) QRRE transactor; Art. 123    | 0009 |   75% 0220 |  45% 0192
    RWL-LN-RE-40         | Art. 124G Table 6B 60% < LTV <= 70%; 125    | 0010 |   35% 0190 |  40% 0191
    RWL-LN-RE-105        | Art. 124G Table 6B LTV > 100%; 125 blend    | 0010 |  (P2.87)   | 105% 0231
    RWL-EQ-SIGNIFICANT   | Art. 133(6)(c); Art. 48(4) / 133(2)         | 0016 |  250% 0250 | 250% 0250
    RWL-EQ-CIU-FALLBACK  | Art. 132(2) CIU fallback, both              | 0015 | 1250% 0270 | 1250% 0270

The two project-finance legs also give OF 07.00 row 0023 ("of which: ...
Project finance exposures", Annex II p.89) and its phase rows a figure, so
``boe_b0958`` and the OF 09.01 tie-outs ``boe_b0975``-``boe_b0977`` stop
holding at ``0 = 0``.

Both regimes run the same book. Every sheet that gains a Basel 3.1 rung also
carries a CRR figure, so a defect that dropped one regime's legs shows up as a
changed cell, not as a dark sheet.

Basel 3.1 lights the two corporate rungs only under the Art. 122(6) election, so
the portfolio has its own config: ``rw_ladder_config`` sets
``use_investment_grade_assessment``. Registered against the gate's plain
``_sa_config``, the two corporates would take the Art. 122(5) flat 100% and the
65% / 135% rows would go dark again. That is the third form of LESSONS B5:
registered, wrong config, dead cell.

``RWL-LN-RE-105`` under CRR is a row PAST the Art. 125 80% clamp, and that is
deliberate. CRR blends its two parts into one weight: 35% up to 80% of the
property value and 75% above it, about 45.9% in all. That weight lands in row
0280 of the real-estate sheet. Plan item P2.87 owns that placement, so this
portfolio does not assert it. P2.87 also asks for exactly this row: "No
registered CRR row is past 80%, so register one first". ``RWL-LN-RE-40`` is the
row short of the clamp beside it (LESSONS B5, fourth form).

What is deliberately NOT here, and why each rung stays dark
-----------------------------------------------------------
- 70% (row 0210, Art. 232(3)(c) life insurance; ``boe_b0488`` / ``boe_b1012`` /
  ``v0323_m``). A corporate loan fully covered by life insurance from a
  100%-weighted insurer lands on row 0210 in both regimes, as Annex II requires.
  It also reports the covered part as an outflow (col 0090) with NO matching
  inflow (col 0100), so col 0150 falls short of col 0200 by the covered part.
  PS1/26 Annex II p.84 makes the covered part "an inflow into the exposure class
  relating to the undertaking providing the life insurance". When the leg was
  tried here, it broke ERROR ``v0308_m`` (CRR) and ``boe_b0471`` (Basel 3.1)
  and WARNING ``v8726_m``, ``v0313_m``, ``boe_b0556`` and ``boe_b0721``. No
  registered run breaks any of those today. It is the root cause plan item
  P1.347 records for the Art. 222 Simple Method: the covered part is not split
  onto its own leg in the protection provider's class. Banking two
  submission-rejecting breaks is a posture decision of its own, the same call
  that keeps P1.347's ``fcsm`` portfolio out of ``RUNS``. The leg joins this
  book once the inflow is reported.
- 110% (row 0232, Art. 124I(2)). The Bank's ``boe_b0445`` forbids row 0232 on
  the real-estate sheet, which publisher issue PI-05 contests.
- Currency-mismatch (Art. 123B) and junior-charge (Arts. 124G(2) / 124I(3))
  legs. Annex II pp.94-95 report them on the weight before the multiplier.
  Until P2.86 lands, the engine bands them on the multiplied weight instead.
  That is also why every retail and real-estate obligor here states
  ``borrower_income_currency`` "GBP": no Art. 123B(3) fallback can then
  multiply a leg off its rung.
- 4% (row 0160, Art. 305(3) client clearing). A CCR trade exposure, so it
  belongs to the ``ccr`` portfolio's axis, not to a class weight.
- CRR 370% (row 0260, Art. 471). The pack has no SA class-weight path to it.
- The class-sheet twins of rungs the Bank forbids on every class sheet except
  0015 (CIU) and 0017 (other): ``boe_b0497`` 45%, ``boe_b0498`` 60%,
  ``boe_b0502`` 105% and ``boe_b0503`` 110%. The forbidding rules are the
  applicable-weights rules ``boe_b0430``-``boe_b0450``. A mandate-based CIU at
  each weight would bind them, but it would test only the banding, not a class
  weight (LESSONS C4), so it is left out.

References:
- PS1/26 Art. 121, 122(6), 122B(2)(c)/(4), 123(3), 124G Table 6B, 129(5),
  132(2), 133(6)(c), 232(3)(c); PS1/26 Annex II OF 07.00 rows 0140-0280 (pp.94-96)
- CRR Art. 48(4), 121(2), 122(1), 125, 129(5), 132(2), 133(2); CRR Annex II
  C 07.00 rows 0140-0280
- BoE v4.1.1 rules boe_b0475-b0507 / b0771 (equality), boe_b1007-b1032 (>=),
  boe_b0430-b0450 (applicable weights); EBA v0316_m-v0328_m, v4751_m, v4752_m
"""

from __future__ import annotations

from datetime import date
from typing import NamedTuple

import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COLLATERAL_SCHEMA,
    COUNTERPARTY_SCHEMA,
    EQUITY_EXPOSURE_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    FACILITY_SCHEMA,
    LOAN_SCHEMA,
    SPECIALISED_LENDING_SCHEMA,
)
from rwa_calc.domain.enums import PermissionMode
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Constants — the single source of truth for the test assertions
# ---------------------------------------------------------------------------

#: Each regime's reporting date: the gate's STANDARDISED dates.
REPORTING_DATE: dict[str, date] = {"CRR": date(2025, 12, 31), "BASEL_3_1": date(2027, 6, 1)}

_VALUE_DATE = date(2024, 12, 31)
_MATURITY = date(2031, 12, 31)  # beyond both reporting dates

#: Above the GBP 44m SME ceiling, so no supporting factor and no Art. 122(11) 85%.
_LARGE_REVENUE = 400_000_000.0

CP_INST_SCRA_A = "RWL-CP-INST-SCRA-A"
CP_COVBOND_15 = "RWL-CP-COVBOND-15"
CP_COVBOND_25 = "RWL-CP-COVBOND-25"
CP_CORP_IG = "RWL-CP-CORP-IG"
CP_CORP_NIG = "RWL-CP-CORP-NIG"
CP_PF_HQ = "RWL-CP-PF-HQ"
CP_PF_PRE = "RWL-CP-PF-PRE"
CP_RETAIL_QRRE = "RWL-CP-RETAIL-QRRE"
CP_RE_40 = "RWL-CP-RE-40"
CP_RE_105 = "RWL-CP-RE-105"
CP_EQUITY = "RWL-CP-EQUITY"

LN_INST_SCRA_A = "RWL-LN-INST-SCRA-A"
LN_COVBOND_15 = "RWL-LN-COVBOND-15"
LN_COVBOND_25 = "RWL-LN-COVBOND-25"
LN_CORP_IG = "RWL-LN-CORP-IG"
LN_CORP_NIG = "RWL-LN-CORP-NIG"
LN_PF_HQ = "RWL-LN-PF-HQ"
LN_PF_PRE = "RWL-LN-PF-PRE"
LN_RETAIL_QRRE = "RWL-LN-RETAIL-QRRE"
LN_RE_40 = "RWL-LN-RE-40"
LN_RE_105 = "RWL-LN-RE-105"
EQ_SIGNIFICANT = "RWL-EQ-SIGNIFICANT"
EQ_CIU_FALLBACK = "RWL-EQ-CIU-FALLBACK"

FAC_RETAIL_QRRE = "RWL-FAC-RETAIL-QRRE"

#: Exposure values in GBP. Distinct per leg, and distinct once multiplied by each
#: weight the leg takes, so no cell of one leg can be mistaken for another's.
EXPOSURE: dict[str, float] = {
    LN_INST_SCRA_A: 2_000_000.0,
    LN_COVBOND_15: 4_000_000.0,
    LN_COVBOND_25: 3_000_000.0,
    LN_CORP_IG: 5_000_000.0,
    LN_CORP_NIG: 1_500_000.0,
    LN_PF_HQ: 2_500_000.0,
    LN_PF_PRE: 1_200_000.0,
    LN_RETAIL_QRRE: 6_000.0,
    LN_RE_40: 260_000.0,
    LN_RE_105: 330_000.0,
    EQ_SIGNIFICANT: 300_000.0,
    EQ_CIU_FALLBACK: 40_000.0,
}

#: The property behind each real-estate leg: LTV 65% and 110%.
_PROPERTY_VALUE: dict[str, float] = {LN_RE_40: 400_000.0, LN_RE_105: 300_000.0}

#: CRR Art. 125 on ``RWL-LN-RE-105``: 35% on the part up to 80% of the property
#: value, the retail 75% on the remainder, blended over the exposure.
_CRR_RE_105_BLEND = (
    0.35 * 0.80 * _PROPERTY_VALUE[LN_RE_105]
    + 0.75 * (EXPOSURE[LN_RE_105] - 0.80 * _PROPERTY_VALUE[LN_RE_105])
) / EXPOSURE[LN_RE_105]


class LadderLeg(NamedTuple):
    """Where one leg must land: its sheet's z-code and, per regime, (weight, row).

    A CRR ``row`` of ``None`` means the CRR placement is not this portfolio's to
    assert: ``RWL-LN-RE-105``'s Art. 125 blend, which plan item P2.87 owns.
    """

    z_code: str
    crr: tuple[float, str | None]
    b31: tuple[float, str]


#: Every leg, its sheet and its rung in each regime. The z-code is the
#: publisher's. The tests resolve it to a bundle key through
#: ``filing/sheet_maps.py``, so the class-to-sheet mapping is not restated
#: here (LESSONS B3).
LADDER: dict[str, LadderLeg] = {
    LN_INST_SCRA_A: LadderLeg("0007", (1.00, "0230"), (0.40, "0191")),
    LN_COVBOND_15: LadderLeg("0013", (0.20, "0180"), (0.15, "0171")),
    LN_COVBOND_25: LadderLeg("0013", (0.20, "0180"), (0.25, "0181")),
    LN_CORP_IG: LadderLeg("0008", (1.00, "0230"), (0.65, "0202")),
    LN_CORP_NIG: LadderLeg("0008", (1.00, "0230"), (1.35, "0234")),
    LN_PF_HQ: LadderLeg("0008", (1.00, "0230"), (0.80, "0221")),
    LN_PF_PRE: LadderLeg("0008", (1.00, "0230"), (1.30, "0233")),
    LN_RETAIL_QRRE: LadderLeg("0009", (0.75, "0220"), (0.45, "0192")),
    LN_RE_40: LadderLeg("0010", (0.35, "0190"), (0.40, "0191")),
    LN_RE_105: LadderLeg("0010", (_CRR_RE_105_BLEND, None), (1.05, "0231")),
    EQ_SIGNIFICANT: LadderLeg("0016", (2.50, "0250"), (2.50, "0250")),
    EQ_CIU_FALLBACK: LadderLeg("0015", (12.50, "0270"), (12.50, "0270")),
}


# ---------------------------------------------------------------------------
# Main public entry points
# ---------------------------------------------------------------------------


def build_reporting_rw_ladder_bundle() -> RawDataBundle:
    """Assemble the risk-weight ladder as a sealed ``RawDataBundle``.

    Run it under ``rw_ladder_config(framework)``. No model permission is
    supplied, so every leg is standardised and C 07.00 / OF 07.00 carries all of
    them.
    """
    return make_raw_bundle(
        counterparties=_counterparties(),
        loans=_loans(),
        facilities=_facilities(),
        facility_mappings=_facility_mappings(),
        collateral=_collateral(),
        specialised_lending=_specialised_lending(),
        equity_exposures=_equity_exposures(),
    )


def rw_ladder_config(framework: str) -> CalculationConfig:
    """The ladder's run config: STANDARDISED, plus the Art. 122(6) election under Basel 3.1.

    PS1/26 Art. 122(6) gives 65% to an unrated corporate the firm assesses as
    investment grade and 135% to one it does not, if the firm "has obtained the
    prior permission from the PRA". Without the election Art. 122(5) gives both
    100%, and the two corporate legs light no new row. The ``crr`` factory takes
    no such keyword: the election does not exist under CRR, and the dataclass
    default (False) is the only reading.

    Args:
        framework: ``"CRR"`` or ``"BASEL_3_1"``.

    Returns:
        The config the portfolio is registered with in the supervisory gate.
    """
    if framework == "CRR":
        return CalculationConfig.crr(
            reporting_date=REPORTING_DATE[framework],
            permission_mode=PermissionMode.STANDARDISED,
        )
    return CalculationConfig.basel_3_1(
        reporting_date=REPORTING_DATE[framework],
        permission_mode=PermissionMode.STANDARDISED,
        use_investment_grade_assessment=True,
    )


# ---------------------------------------------------------------------------
# Table builders (private)
# ---------------------------------------------------------------------------


def _counterparties() -> pl.DataFrame:
    """One obligor per leg; the two equity legs share one issuer.

    Every obligor is unrated. A rating would put its leg on an ECAI ladder, and
    these legs exist for the unrated limbs. The covered-bond issuers carry
    ``institution_cqs`` because Art. 129(5) derives an unrated covered bond's
    weight from its issuer's: CQS 2 -> 30% -> 15%, and CQS 3 -> 50% -> 25%. The
    retail and real-estate obligors are natural persons managed as retail, and
    each states that it earns in the loan's currency.
    """
    natural_person: dict[str, object] = {
        "entity_type": "individual",
        "country_code": "GB",
        "is_natural_person": True,
        "is_managed_as_retail": True,
        "borrower_income_currency": "GBP",
    }
    large_corporate: dict[str, object] = {
        "entity_type": "corporate",
        "country_code": "GB",
        "annual_revenue": _LARGE_REVENUE,
    }
    project_finance = {**large_corporate, "entity_type": "specialised_lending"}
    rows: list[dict[str, object]] = [
        {
            "counterparty_reference": CP_INST_SCRA_A,
            "entity_type": "institution",
            "country_code": "GB",
            "scra_grade": "A",
        },
        {
            "counterparty_reference": CP_COVBOND_15,
            "entity_type": "covered_bond",
            "country_code": "GB",
            "institution_cqs": 2,
        },
        {
            "counterparty_reference": CP_COVBOND_25,
            "entity_type": "covered_bond",
            "country_code": "GB",
            "institution_cqs": 3,
        },
        {**large_corporate, "counterparty_reference": CP_CORP_IG, "is_investment_grade": True},
        {**large_corporate, "counterparty_reference": CP_CORP_NIG, "is_investment_grade": False},
        {**project_finance, "counterparty_reference": CP_PF_HQ},
        {**project_finance, "counterparty_reference": CP_PF_PRE},
        {**natural_person, "counterparty_reference": CP_RETAIL_QRRE},
        {**natural_person, "counterparty_reference": CP_RE_40},
        {**natural_person, "counterparty_reference": CP_RE_105},
        {**large_corporate, "counterparty_reference": CP_EQUITY},
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(COUNTERPARTY_SCHEMA))


def _loans() -> pl.DataFrame:
    """One drawn senior GBP loan per lending leg.

    The real-estate legs state the property on the loan row, as the rich
    portfolio does. ``has_income_cover`` makes them materially dependent on the
    property's cash flows, which takes them to the Art. 124G whole-loan bands
    rather than the Art. 124F split.
    """
    rows: list[dict[str, object]] = [
        _loan(LN_INST_SCRA_A, CP_INST_SCRA_A),
        _loan(LN_COVBOND_15, CP_COVBOND_15),
        _loan(LN_COVBOND_25, CP_COVBOND_25),
        _loan(LN_CORP_IG, CP_CORP_IG),
        _loan(LN_CORP_NIG, CP_CORP_NIG),
        _loan(LN_PF_HQ, CP_PF_HQ),
        _loan(LN_PF_PRE, CP_PF_PRE),
        {**_loan(LN_RETAIL_QRRE, CP_RETAIL_QRRE), "product_type": "credit_card"},
        {**_loan(LN_RE_40, CP_RE_40), **_property_terms(LN_RE_40)},
        {**_loan(LN_RE_105, CP_RE_105), **_property_terms(LN_RE_105)},
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(LOAN_SCHEMA))


def _facilities() -> pl.DataFrame:
    """The credit-card facility behind the QRRE leg, fully drawn.

    The transactor flag is a facility attribute: ``hierarchy/enrich.py`` carries
    it onto the loan. The limit equals the drawn balance, so the facility has no
    undrawn leg and the cell has no conversion factor in it.
    """
    rows: list[dict[str, object]] = [
        {
            "facility_reference": FAC_RETAIL_QRRE,
            "product_type": "credit_card",
            "counterparty_reference": CP_RETAIL_QRRE,
            "value_date": _VALUE_DATE,
            "maturity_date": _MATURITY,
            "currency": "GBP",
            "limit": EXPOSURE[LN_RETAIL_QRRE],
            "committed": True,
            "is_revolving": True,
            "is_qrre_transactor": True,
            "seniority": "senior",
            "risk_type": "LR",
        }
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(FACILITY_SCHEMA))


def _facility_mappings() -> pl.DataFrame:
    """Hang the QRRE loan under its facility."""
    rows: list[dict[str, object]] = [
        {
            "parent_facility_reference": FAC_RETAIL_QRRE,
            "child_reference": LN_RETAIL_QRRE,
            "child_type": "loan",
        }
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(FACILITY_MAPPING_SCHEMA))


def _collateral() -> pl.DataFrame:
    """The two residential properties, each pledged directly to its loan.

    ``is_income_producing`` agrees with the loan row's ``has_income_cover``.
    """
    rows = [_property(LN_RE_40), _property(LN_RE_105)]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(COLLATERAL_SCHEMA))


def _specialised_lending() -> pl.DataFrame:
    """The two project-finance obligors and their Art. 122B phases.

    The table requires ``slotting_category``, but only a slotting route reads
    it, and a STANDARDISED run never takes one.
    """
    rows: list[dict[str, object]] = [
        {
            "counterparty_reference": CP_PF_HQ,
            "sl_type": "project_finance",
            "project_phase": "high_quality_operational",
            "slotting_category": "strong",
            "is_hvcre": False,
        },
        {
            "counterparty_reference": CP_PF_PRE,
            "sl_type": "project_finance",
            "project_phase": "pre_operational",
            "slotting_category": "strong",
            "is_hvcre": False,
        },
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(SPECIALISED_LENDING_SCHEMA))


def _equity_exposures() -> pl.DataFrame:
    """The two equity-table legs: an Art. 48(4) holding and a CIU on the fallback.

    The significant investment keeps its 250% under Basel 3.1 too: rules 4.2 and
    4.3 exclude an Art. 133(6) item by name, so the transitional does not move
    it. Carrying value = fair value = exposure value.
    """
    rows: list[dict[str, object]] = [
        {
            **_equity(EQ_SIGNIFICANT),
            "equity_type": "listed",
            "is_exchange_traded": True,
            "is_significant_investment": True,
        },
        {**_equity(EQ_CIU_FALLBACK), "equity_type": "ciu", "ciu_approach": "fallback"},
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(EQUITY_EXPOSURE_SCHEMA))


# ---------------------------------------------------------------------------
# Row helpers (private)
# ---------------------------------------------------------------------------


def _loan(reference: str, counterparty_reference: str) -> dict[str, object]:
    """One fully drawn senior GBP term loan for the leg's exposure value."""
    return {
        "loan_reference": reference,
        "counterparty_reference": counterparty_reference,
        "product_type": "term_loan",
        "drawn_amount": EXPOSURE[reference],
        "currency": "GBP",
        "value_date": _VALUE_DATE,
        "maturity_date": _MATURITY,
        "seniority": "senior",
    }


def _property_terms(reference: str) -> dict[str, object]:
    """The loan-row property columns of a materially dependent residential leg."""
    return {
        "property_type": "residential",
        "ltv": EXPOSURE[reference] / _PROPERTY_VALUE[reference],
        "has_income_cover": True,
    }


def _property(reference: str) -> dict[str, object]:
    """One qualifying residential property pledged to one loan."""
    value = _PROPERTY_VALUE[reference]
    return {
        "collateral_reference": f"{reference}-COL",
        "collateral_type": "real_estate",
        "currency": "GBP",
        "market_value": value,
        "nominal_value": value,
        "beneficiary_type": "loan",
        "beneficiary_reference": reference,
        "residual_maturity_years": 10.0,
        "original_maturity_years": 20.0,
        "is_eligible_financial_collateral": False,
        "is_eligible_irb_collateral": True,
        "valuation_date": _VALUE_DATE,
        "valuation_type": "market",
        "property_type": "residential",
        "property_ltv": EXPOSURE[reference] / value,
        "is_income_producing": True,
        "is_adc": False,
        "is_presold": False,
        "is_qualifying_re": True,
        "prior_charge_ltv": 0.0,
    }


def _equity(reference: str) -> dict[str, object]:
    """The columns every equity-table leg shares."""
    return {
        "exposure_reference": reference,
        "counterparty_reference": CP_EQUITY,
        "currency": "GBP",
        "carrying_value": EXPOSURE[reference],
        "fair_value": EXPOSURE[reference],
    }
