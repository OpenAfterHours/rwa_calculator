"""
Phase O1 (b) -- Standardised Approach oracles under PRA PS1/26 (Basel 3.1).

Every risk weight below was read out of `docs/assets/ps126app1.pdf` (PRA2026/1,
effective 1 January 2027) and is cited to the article and table it came from.
Nothing here reads the engine.

Where PS1/26 renumbers relative to CRR the article carries a
``[Note: This rule corresponds to Article NNN of CRR ...]`` line; the citations
below quote the PS1/26 number, which is the operative one from 2027.

References:
- Art. 114  central governments and central banks (Table 1)
- Art. 115  regional governments and local authorities (Tables 1A, 1B)
- Art. 116  public sector entities (Tables 2, 2A)
- Art. 117  multilateral development banks (Table 2B)
- Art. 118  international organisations
- Art. 120  rated institutions (Tables 3, 4)
- Art. 121  unrated institutions -- SCRA grades (Tables 5, 5A)
- Art. 122  corporates (Table 6)
- Art. 122B specialised lending
- Art. 123  retail
- Art. 124F-124L  real estate
- Art. 127  exposures in default
- Art. 128  exposures associated with particularly high risk
- Art. 129  eligible covered bonds (Table 7)
- Art. 133  subordinated debt, equity and other own funds instruments
- Art. 134  other items
"""

from __future__ import annotations

from typing import Any

from .formulas import blend_two_bands
from .record import oracle

FRAMEWORK = "BASEL_3_1"
PHASE = "O1"

M = 1_000_000.0

_FOREIGN = {"country_code": "US", "currency": "USD"}
_LONG_DATED = {"residual_maturity_years": 5.0, "original_maturity_years": 5.0}

# Art. 116(1)/(2) are written for UK public sector entities; Art. 116(3A) extends
# them to third-country PSEs only through Art. 116(5) of CRR, which needs a
# Treasury equivalence determination. A UK PSE tests Tables 2 / 2A directly.
_UK = {"country_code": "GB", "currency": "GBP", "local_currency": "GBP"}


def _sa(
    oracle_id: str,
    exposure_class: str,
    regulation: str,
    risk_weight: float,
    inputs: dict[str, Any],
    *,
    ead: float = M,
    rwa: float | None = None,
    intermediate: dict[str, Any] | None = None,
    unasserted: tuple[str, ...] = (),
) -> dict[str, Any]:
    return oracle(
        oracle_id=oracle_id,
        phase=PHASE,
        framework=FRAMEWORK,
        approach="SA",
        exposure_class=exposure_class,
        regulation=regulation,
        ead=ead,
        risk_weight=risk_weight,
        inputs={"exposure_class": exposure_class, **inputs},
        intermediate=intermediate,
        rwa=rwa,
        unasserted=unasserted,
    )


# -----------------------------------------------------------------------------
# Sovereign, RGLA, PSE, MDB, international organisations
# -----------------------------------------------------------------------------
# Art. 114(2)  Table 1  (sovereign, rated):        0 / 20 / 50 / 100 / 100 / 150
# Art. 114(4)  UK central government in sterling:  0
# Art. 115(1)(a)(i) Table 1A (RGLA, unrated, on the central government's CQS):
#                                                 20 / 50 / 100 / 100 / 100 / 150
# Art. 115(1)(b) Table 1B (RGLA, rated):          20 / 50 / 50 / 100 / 100 / 150
# Art. 115(5)  UK RGLA in sterling:                20
# Art. 116(1)  Table 2  (PSE, unrated):           20 / 50 / 100 / 100 / 100 / 150
# Art. 116(2)  Table 2A (PSE, rated):             20 / 50 / 50 / 100 / 100 / 150
# Art. 117(1)(a) Table 2B (MDB, rated):           20 / 30 / 50 / 100 / 100 / 150
# Art. 117(1)(b) MDB, unrated:                     50
# Art. 117(2)  named MDBs:                          0
# Art. 118(1)  named international organisations:   0
SOVEREIGN_TABLE_1 = {1: 0.00, 2: 0.20, 3: 0.50, 4: 1.00, 5: 1.00, 6: 1.50}
RGLA_TABLE_1A = {1: 0.20, 2: 0.50, 3: 1.00, 4: 1.00, 5: 1.00, 6: 1.50}
RGLA_TABLE_1B = {1: 0.20, 2: 0.50, 3: 0.50, 4: 1.00, 5: 1.00, 6: 1.50}
PSE_TABLE_2 = {1: 0.20, 2: 0.50, 3: 1.00, 4: 1.00, 5: 1.00, 6: 1.50}
PSE_TABLE_2A = {1: 0.20, 2: 0.50, 3: 0.50, 4: 1.00, 5: 1.00, 6: 1.50}
MDB_TABLE_2B = {1: 0.20, 2: 0.30, 3: 0.50, 4: 1.00, 5: 1.00, 6: 1.50}
MDB_UNRATED_RW = 0.50


def sovereign_like() -> list[dict[str, Any]]:
    return [
        _sa(
            "ORC-040",
            "central_govt_central_bank",
            "PS1/26 Art. 114(2) Table 1: CQS 2 sovereign (foreign ccy) -> 20% RW",
            SOVEREIGN_TABLE_1[2],
            {"cqs": 2, "entity_type": "sovereign", **_FOREIGN},
        ),
        _sa(
            "ORC-041",
            "central_govt_central_bank",
            "PS1/26 Art. 114(4): UK central government, denominated and funded in "
            "sterling -> 0% RW",
            0.00,
            {
                "cqs": 3,
                "entity_type": "sovereign",
                "country_code": "GB",
                "currency": "GBP",
                "local_currency": "GBP",
            },
        ),
        _sa(
            "ORC-042",
            "rgla",
            "PS1/26 Art. 115(1)(a)(i) Table 1A: unrated RGLA, central government CQS 2 -> 50% RW",
            RGLA_TABLE_1A[2],
            {"cqs": None, "entity_type": "rgla_institution", "sovereign_cqs": 2, **_FOREIGN},
        ),
        _sa(
            "ORC-043",
            "rgla",
            "PS1/26 Art. 115(1)(b) Table 1B: rated RGLA CQS 3 -> 50% RW",
            RGLA_TABLE_1B[3],
            {"cqs": 3, "entity_type": "rgla_institution", **_FOREIGN},
        ),
        _sa(
            "ORC-044",
            "rgla",
            "PS1/26 Art. 115(5): UK regional government, sterling -> 20% RW",
            0.20,
            {
                "cqs": None,
                "entity_type": "rgla_institution",
                "country_code": "GB",
                "currency": "GBP",
                "local_currency": "GBP",
            },
        ),
        _sa(
            "ORC-045",
            "pse",
            "PS1/26 Art. 116(1) Table 2: unrated PSE, central government CQS 1 -> 20% RW",
            PSE_TABLE_2[1],
            {"cqs": None, "entity_type": "pse_sovereign", "sovereign_cqs": 1, **_UK},
        ),
        _sa(
            "ORC-046",
            "pse",
            "PS1/26 Art. 116(2) Table 2A: rated PSE CQS 3 -> 50% RW",
            PSE_TABLE_2A[3],
            {"cqs": 3, "entity_type": "pse_sovereign", **_UK},
        ),
        _sa(
            "ORC-047",
            "mdb",
            "PS1/26 Art. 117(1)(a) Table 2B: rated MDB CQS 2 -> 30% RW "
            "(CRR assigned 50% via the institution ladder)",
            MDB_TABLE_2B[2],
            {"cqs": 2, "entity_type": "mdb", **_FOREIGN},
        ),
        _sa(
            "ORC-048",
            "mdb",
            "PS1/26 Art. 117(1)(b): MDB with no ECAI assessment -> 50% RW",
            MDB_UNRATED_RW,
            {"cqs": None, "entity_type": "mdb", **_FOREIGN},
        ),
        _sa(
            "ORC-049",
            "international_organisation",
            "PS1/26 Art. 118(1): named international organisation -> 0% RW",
            0.00,
            {"cqs": None, "entity_type": "international_org", **_FOREIGN},
        ),
    ]


# -----------------------------------------------------------------------------
# Institutions -- Art. 120 (ECRA) and Art. 121 (SCRA)
# -----------------------------------------------------------------------------
# Art. 120(1) Table 3  (rated, original maturity > 3 months):
#   CQS  1     2     3     4     5     6
#   RW  20%   30%   50%  100%  100%  150%
#   The CQS-2 weight is 30% here and 50% under CRR Art. 120 Table 3 -- this is
#   one of the two places a wrong constant would be invisible to every
#   conservation / monotonicity property.
# Art. 120(2) Table 4  (rated, original maturity <= 3 months):
#   20% / 20% / 20% / 50% / 50% / 150%
# Art. 121(2) Table 5  (unrated, SCRA):  Grade A 40%, Grade B 75%, Grade C 150%
# Art. 121(3) Table 5A (unrated, <= 3 months): Grade A 20%, B 50%, C 150%
# Art. 121(5) Grade A with CET1 >= 14% and leverage ratio >= 5%: 30%
INSTITUTION_TABLE_3 = {1: 0.20, 2: 0.30, 3: 0.50, 4: 1.00, 5: 1.00, 6: 1.50}
INSTITUTION_TABLE_4 = {1: 0.20, 2: 0.20, 3: 0.20, 4: 0.50, 5: 0.50, 6: 1.50}
INSTITUTION_TABLE_5 = {"A": 0.40, "B": 0.75, "C": 1.50}
INSTITUTION_GRADE_A_ENHANCED_RW = 0.30


def institutions() -> list[dict[str, Any]]:
    return [
        _sa(
            "ORC-050",
            "institution",
            "PS1/26 Art. 120(1) Table 3: rated institution CQS 2, original "
            "maturity > 3 months -> 30% RW",
            INSTITUTION_TABLE_3[2],
            {"cqs": 2, "entity_type": "institution", **_LONG_DATED, **_FOREIGN},
        ),
        _sa(
            "ORC-051",
            "institution",
            "PS1/26 Art. 120(1) Table 3: rated institution CQS 3 -> 50% RW",
            INSTITUTION_TABLE_3[3],
            {"cqs": 3, "entity_type": "institution", **_LONG_DATED, **_FOREIGN},
        ),
        _sa(
            "ORC-052",
            "institution",
            "PS1/26 Art. 121(2) Table 5: unrated institution, SCRA Grade A -> 40% RW",
            INSTITUTION_TABLE_5["A"],
            {
                "cqs": None,
                "entity_type": "institution",
                "scra_grade": "A",
                **_LONG_DATED,
                **_FOREIGN,
            },
        ),
        _sa(
            "ORC-053",
            "institution",
            "PS1/26 Art. 121(2) Table 5: unrated institution, SCRA Grade B -> 75% RW",
            INSTITUTION_TABLE_5["B"],
            {
                "cqs": None,
                "entity_type": "institution",
                "scra_grade": "B",
                **_LONG_DATED,
                **_FOREIGN,
            },
        ),
        _sa(
            "ORC-054",
            "institution",
            "PS1/26 Art. 121(2) Table 5: unrated institution, SCRA Grade C -> 150% RW",
            INSTITUTION_TABLE_5["C"],
            {
                "cqs": None,
                "entity_type": "institution",
                "scra_grade": "C",
                **_LONG_DATED,
                **_FOREIGN,
            },
        ),
        _sa(
            "ORC-055",
            "institution",
            "PS1/26 Art. 121(5): unrated Grade A institution with CET1 >= 14% and "
            "leverage ratio >= 5% -> 30% RW",
            INSTITUTION_GRADE_A_ENHANCED_RW,
            {
                "cqs": None,
                "entity_type": "institution",
                "scra_grade": "A_ENHANCED",
                **_LONG_DATED,
                **_FOREIGN,
            },
        ),
    ]


# -----------------------------------------------------------------------------
# Corporates -- Art. 122
# -----------------------------------------------------------------------------
# Art. 122(2) Table 6:
#   CQS  1     2     3     4     5     6
#   RW  20%   50%   75%  100%  150%  150%
#   The CQS-3 weight is 75% here and 100% under CRR Art. 122 Table 6.
# Art. 122(5)  unrated, no Art. 122(6) permission:  100%
# Art. 122(6)(a) unrated, assessed investment grade: 65%
# Art. 122(6)(b) unrated, assessed not investment grade: 135%
# Art. 122(11) unrated SME that is not a retail exposure: 85%
CORPORATE_TABLE_6 = {1: 0.20, 2: 0.50, 3: 0.75, 4: 1.00, 5: 1.50, 6: 1.50}
CORPORATE_UNRATED_RW = 1.00
CORPORATE_INVESTMENT_GRADE_RW = 0.65
CORPORATE_SME_UNRATED_RW = 0.85


def corporates() -> list[dict[str, Any]]:
    return [
        _sa(
            "ORC-056",
            "corporate",
            "PS1/26 Art. 122(2) Table 6: rated corporate CQS 3 -> 75% RW "
            "(CRR Table 6 assigns 100%)",
            CORPORATE_TABLE_6[3],
            {"cqs": 3, "entity_type": "corporate", **_FOREIGN},
        ),
        _sa(
            "ORC-057",
            "corporate",
            "PS1/26 Art. 122(2) Table 6: rated corporate CQS 5 -> 150% RW",
            CORPORATE_TABLE_6[5],
            {"cqs": 5, "entity_type": "corporate", **_FOREIGN},
        ),
        _sa(
            "ORC-058",
            "corporate",
            "PS1/26 Art. 122(5): unrated corporate without the Art. 122(6) permission -> 100% RW",
            CORPORATE_UNRATED_RW,
            {"cqs": None, "entity_type": "corporate"},
        ),
        _sa(
            "ORC-059",
            "corporate",
            "PS1/26 Art. 122(6)(a): unrated corporate assessed as investment grade -> 65% RW",
            CORPORATE_INVESTMENT_GRADE_RW,
            {
                "cqs": None,
                "entity_type": "corporate",
                "is_investment_grade": True,
                "use_investment_grade_assessment": True,
            },
        ),
        _sa(
            "ORC-060",
            "corporate_sme",
            "PS1/26 Art. 122(11): unrated SME that is not a retail exposure -> 85% RW",
            CORPORATE_SME_UNRATED_RW,
            {
                "cqs": None,
                "entity_type": "corporate",
                "is_sme": True,
                "qualifies_as_retail": False,
            },
            # The RWEA would also depend on whether the CRR Art. 501 SME
            # supporting factor survives Basel 3.1. Art. 501 sits in Part Ten,
            # which is in neither ps126app1.pdf nor the comparison document, so
            # that could not be sourced here: the risk weight is asserted, the
            # RWEA is published but not compared.
            unasserted=("rwa",),
        ),
    ]


# -----------------------------------------------------------------------------
# Retail -- Art. 123
# -----------------------------------------------------------------------------
# Art. 123(3)(a) regulatory retail, transactor:        45%
# Art. 123(3)(b) regulatory retail, non-transactor:    75%
# Art. 123(3)(c) retail that is not regulatory retail: 100%
# Art. 123(4)    pension / salary assignment loans:     35%
RETAIL_TRANSACTOR_RW = 0.45
RETAIL_REGULATORY_RW = 0.75
RETAIL_OTHER_RW = 1.00
RETAIL_PAYROLL_RW = 0.35

_NATURAL_PERSON = {
    "cqs": None,
    "entity_type": "individual",
    "cp_is_natural_person": True,
}


def retail() -> list[dict[str, Any]]:
    return [
        _sa(
            "ORC-061",
            "retail_other",
            "PS1/26 Art. 123(3)(b): regulatory retail, not a transactor -> 75% RW",
            RETAIL_REGULATORY_RW,
            {**_NATURAL_PERSON, "qualifies_as_retail": True, "is_qrre_transactor": False},
        ),
        _sa(
            "ORC-062",
            "retail_qrre",
            "PS1/26 Art. 123(3)(a): regulatory retail transactor exposure -> 45% RW",
            RETAIL_TRANSACTOR_RW,
            {**_NATURAL_PERSON, "qualifies_as_retail": True, "is_qrre_transactor": True},
        ),
        _sa(
            "ORC-063",
            "retail_other",
            "PS1/26 Art. 123(3)(c): retail exposure that does not qualify as a "
            "regulatory retail exposure -> 100% RW",
            RETAIL_OTHER_RW,
            {**_NATURAL_PERSON, "qualifies_as_retail": False, "is_qrre_transactor": False},
        ),
        _sa(
            "ORC-283",
            "retail_qrre",
            "PS1/26 Art. 123(3)(c): a TRANSACTOR that does not qualify as a "
            "regulatory retail exposure -> 100% RW. Art. 123(3)(a) reserves the "
            "45% for 'regulatory retail exposures that ARE transactor exposures', "
            "so the transactor property alone does not earn it; (c) sweeps up "
            "'all other retail exposures that do not qualify'. This is the fourth "
            "corner of the (qualifies x transactor) square and was the only one "
            "the estate did not carry -- the engine returned 45% here until "
            "P1.293, a 55pp understatement",
            RETAIL_OTHER_RW,
            {**_NATURAL_PERSON, "qualifies_as_retail": False, "is_qrre_transactor": True},
        ),
        _sa(
            "ORC-064",
            "retail_other",
            "PS1/26 Art. 123(4): pension / salary assignment loan meeting points (a)-(d) -> 35% RW",
            RETAIL_PAYROLL_RW,
            {
                **_NATURAL_PERSON,
                "qualifies_as_retail": True,
                "is_payroll_loan": True,
                "original_maturity_years": 8.0,
                "residual_maturity_years": 8.0,
            },
        ),
    ]


# -----------------------------------------------------------------------------
# Real estate -- Art. 124F to 124L
# -----------------------------------------------------------------------------
# Art. 124F(1): regulatory residential real estate NOT materially dependent on
#   the property's cash-flows -- 20% on the part of the exposure up to 55% of
#   the value of the property, counterparty risk weight (Art. 124L) above.
# Art. 124G(1) Table 6B: regulatory residential real estate that IS materially
#   dependent -- whole-exposure risk weight by LTV band:
#     <=50%  50-60%  60-70%  70-80%  80-90%  90-100%  >100%
#      30%     35%     40%     50%     60%     75%     105%
# Art. 124H(1): regulatory commercial real estate to a natural person or SME
#   NOT materially dependent -- 60% up to 55% of value, counterparty RW above.
# Art. 124I(1)/(2): regulatory commercial real estate that IS materially
#   dependent -- 100% where LTV <= 80%, 110% where LTV > 80%.
# Art. 124K(1)/(2): ADC exposures -- 150%, or 100% for qualifying residential
#   ADC with substantial pre-sales or borrower equity.
# Art. 124L(1)(a): counterparty risk weight for a natural person -- 75%.
RRE_PREFERENTIAL_RW = 0.20
CRE_PREFERENTIAL_RW = 0.60
RE_VALUE_SHARE = 0.55
COUNTERPARTY_RW_NATURAL_PERSON = 0.75

RRE_IPRE_TABLE_6B = [
    (0.50, 0.30),
    (0.60, 0.35),
    (0.70, 0.40),
    (0.80, 0.50),
    (0.90, 0.60),
    (1.00, 0.75),
]
RRE_IPRE_ABOVE_100_RW = 1.05
CRE_IPRE_LOW_LTV_RW = 1.00
CRE_IPRE_HIGH_LTV_RW = 1.10
ADC_RW = 1.50
ADC_RESIDENTIAL_PRESOLD_RW = 1.00


def ipre_residential_rw(ltv: float) -> float:
    """Table 6B lookup: the band is inclusive at its upper bound."""
    for upper, rw in RRE_IPRE_TABLE_6B:
        if ltv <= upper:
            return rw
    return RRE_IPRE_ABOVE_100_RW


def _split_rw(ltv: float, preferential_rw: float, counterparty_rw: float) -> float:
    """20% / 60% on the slice up to 55% of value, counterparty RW above it."""
    exposure = 1.0
    value = exposure / ltv
    return blend_two_bands(
        exposure=exposure,
        secured_amount=RE_VALUE_SHARE * value,
        secured_rw=preferential_rw,
        residual_rw=counterparty_rw,
    )


def real_estate() -> list[dict[str, Any]]:
    rre_low = _split_rw(0.50, RRE_PREFERENTIAL_RW, COUNTERPARTY_RW_NATURAL_PERSON)
    rre_high = _split_rw(1.00, RRE_PREFERENTIAL_RW, COUNTERPARTY_RW_NATURAL_PERSON)
    cre_low = _split_rw(0.50, CRE_PREFERENTIAL_RW, COUNTERPARTY_RW_NATURAL_PERSON)
    return [
        _sa(
            "ORC-065",
            "retail_mortgage",
            "PS1/26 Art. 124F(1): regulatory RRE not materially dependent on the "
            "property's cash-flows, LTV 50% -- the whole exposure sits inside "
            "55% of the property value -> 20% RW",
            rre_low,
            {
                **_NATURAL_PERSON,
                "ltv": 0.50,
                "property_type": "residential",
                "has_income_cover": False,
                "is_qualifying_re": True,
            },
        ),
        _sa(
            "ORC-066",
            "retail_mortgage",
            "PS1/26 Art. 124F(1) with Art. 124L(1)(a): regulatory RRE not "
            "materially dependent, LTV 100% -- 20% on 55% of value, 75% natural-"
            "person counterparty RW on the remaining 45% -> 44.75% blended RW",
            rre_high,
            {
                **_NATURAL_PERSON,
                "ltv": 1.00,
                "property_type": "residential",
                "has_income_cover": False,
                "is_qualifying_re": True,
            },
            intermediate={
                "preferential_rw": RRE_PREFERENTIAL_RW,
                "value_share": RE_VALUE_SHARE,
                "counterparty_rw": COUNTERPARTY_RW_NATURAL_PERSON,
            },
        ),
        _sa(
            "ORC-067",
            "retail_mortgage",
            "PS1/26 Art. 124G(1) Table 6B: regulatory RRE materially dependent on "
            "the property's cash-flows, LTV 65% (60% < LTV <= 70%) -> 40% RW",
            ipre_residential_rw(0.65),
            {
                **_NATURAL_PERSON,
                "ltv": 0.65,
                "property_type": "residential",
                "has_income_cover": True,
                "is_qualifying_re": True,
            },
        ),
        _sa(
            "ORC-068",
            "retail_mortgage",
            "PS1/26 Art. 124G(1) Table 6B: regulatory RRE materially dependent, "
            "LTV 105% (> 100%) -> 105% RW",
            ipre_residential_rw(1.05),
            {
                **_NATURAL_PERSON,
                "ltv": 1.05,
                "property_type": "residential",
                "has_income_cover": True,
                "is_qualifying_re": True,
            },
        ),
        _sa(
            "ORC-069",
            "commercial_mortgage",
            "PS1/26 Art. 124H(1): regulatory CRE to a natural person, not "
            "materially dependent, LTV 50% -- the whole exposure sits inside 55% "
            "of the property value -> 60% RW",
            cre_low,
            {
                **_NATURAL_PERSON,
                "ltv": 0.50,
                "property_type": "commercial",
                "has_income_cover": False,
                "is_qualifying_re": True,
            },
        ),
        _sa(
            "ORC-070",
            "commercial_mortgage",
            "PS1/26 Art. 124I(1): regulatory CRE materially dependent on the "
            "property's cash-flows, LTV 70% (<= 80%) -> 100% RW",
            CRE_IPRE_LOW_LTV_RW,
            {
                "cqs": None,
                "entity_type": "corporate",
                "ltv": 0.70,
                "property_type": "commercial",
                "has_income_cover": True,
                "is_qualifying_re": True,
            },
        ),
        _sa(
            "ORC-071",
            "commercial_mortgage",
            "PS1/26 Art. 124I(2): regulatory CRE materially dependent, LTV 90% (> 80%) -> 110% RW",
            CRE_IPRE_HIGH_LTV_RW,
            {
                "cqs": None,
                "entity_type": "corporate",
                "ltv": 0.90,
                "property_type": "commercial",
                "has_income_cover": True,
                "is_qualifying_re": True,
            },
        ),
        _sa(
            "ORC-072",
            "commercial_mortgage",
            "PS1/26 Art. 124K(1): acquisition, development and construction exposure -> 150% RW",
            ADC_RW,
            {
                "cqs": None,
                "entity_type": "corporate",
                "ltv": 0.60,
                "property_type": "commercial",
                "is_adc": True,
                "is_presold": False,
            },
        ),
        _sa(
            "ORC-073",
            "residential_mortgage",
            "PS1/26 Art. 124K(2): residential ADC exposure with substantial "
            "pre-sale contracts -> 100% RW",
            ADC_RESIDENTIAL_PRESOLD_RW,
            {
                "cqs": None,
                "entity_type": "corporate",
                "ltv": 0.60,
                "property_type": "residential",
                "is_adc": True,
                "is_presold": True,
            },
        ),
    ]


# -----------------------------------------------------------------------------
# Default, high risk, covered bonds, equity, other items
# -----------------------------------------------------------------------------
# Art. 127(1)(a)/(b): unsecured part of a defaulted exposure -- 150% where
#   specific credit risk adjustments are below 20% of the outstanding amount,
#   100% at or above 20%.
# Art. 128(1): exposures associated with particularly high risk -> 150%.
#   (CRR Art. 128 was omitted from the UK CRR with effect from 1 Jan 2022;
#   PS1/26 reinstates it.)
# Art. 129(4) Table 7 (eligible covered bonds):
#   CQS  1     2     3     4     5     6
#   RW  10%   20%   20%   50%   50%  100%
# Art. 133(3): equity exposure -> 250%   (CRR Art. 133(2) assigned 100%).
# Art. 134(1): tangible assets and other items -> 100%.
COVERED_BOND_TABLE_7 = {1: 0.10, 2: 0.20, 3: 0.20, 4: 0.50, 5: 0.50, 6: 1.00}
HIGH_RISK_RW = 1.50
EQUITY_RW = 2.50


def defaults_and_others() -> list[dict[str, Any]]:
    return [
        _sa(
            "ORC-074",
            "defaulted",
            "PS1/26 Art. 127(1)(a): defaulted exposure with specific credit risk "
            "adjustments below 20% of the outstanding amount -> 150% RW",
            1.50,
            {
                "cqs": None,
                "entity_type": "corporate",
                "is_defaulted": True,
                "provision_allocated": 100_000.0,
            },
        ),
        _sa(
            "ORC-075",
            "defaulted",
            "PS1/26 Art. 127(1)(b): defaulted exposure with specific credit risk "
            "adjustments at or above 20% of the outstanding amount -> 100% RW",
            1.00,
            {
                "cqs": None,
                "entity_type": "corporate",
                "is_defaulted": True,
                "provision_allocated": 300_000.0,
            },
        ),
        _sa(
            "ORC-076",
            "high_risk",
            "PS1/26 Art. 128(1): exposure associated with particularly high risk -> 150% RW",
            HIGH_RISK_RW,
            {"cqs": None, "entity_type": "high_risk"},
        ),
        _sa(
            "ORC-077",
            "covered_bond",
            "PS1/26 Art. 129(4) Table 7: eligible covered bond CQS 1 -> 10% RW",
            COVERED_BOND_TABLE_7[1],
            {"cqs": 1, "entity_type": "covered_bond", **_FOREIGN},
        ),
        _sa(
            "ORC-078",
            "covered_bond",
            "PS1/26 Art. 129(4) Table 7: eligible covered bond CQS 3 -> 20% RW",
            COVERED_BOND_TABLE_7[3],
            {"cqs": 3, "entity_type": "covered_bond", **_FOREIGN},
        ),
        _sa(
            "ORC-079",
            "other",
            "PS1/26 Art. 134(1): tangible assets / other items -> 100% RW",
            1.00,
            {"cqs": None, "entity_type": "other_tangible"},
        ),
    ]


def equity() -> list[dict[str, Any]]:
    return [
        oracle(
            oracle_id="ORC-080",
            phase=PHASE,
            framework=FRAMEWORK,
            approach="EQUITY",
            exposure_class="equity",
            regulation="PS1/26 Art. 133(3): equity exposure -> 250% RW "
            "(CRR Art. 133(2) assigned 100%)",
            ead=M,
            risk_weight=EQUITY_RW,
            inputs={"equity_type": "listed", "is_exchange_traded": True},
        )
    ]


def all_oracles() -> list[dict[str, Any]]:
    return [
        *sovereign_like(),
        *institutions(),
        *corporates(),
        *retail(),
        *real_estate(),
        *defaults_and_others(),
        *equity(),
    ]
