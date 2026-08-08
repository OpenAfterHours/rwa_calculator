"""
Phase O4 -- slotting and IRB equity oracles.

Slotting and IRB equity are pure table lookups, which is exactly the defect
class the property suite cannot see: a wrong constant in one of these tables
leaves every conservation, bound and monotonicity property intact.

References:
- CRR Art. 153(5) Table 1: specialised lending slotting risk weights, split on
  whether the remaining maturity is below 2.5 years.
- PS1/26 Art. 153(5)(c)/(d) Table A: the same, re-cut into seven columns and
  extended with a separate HVCRE row.
- CRR Art. 155(2): equity simple risk-weight approach (190 / 290 / 370).
- PS1/26 Art. 155: every paragraph is "[Note: Provision left blank]" -- the IRB
  equity treatments are withdrawn and equity is risk-weighted under Art. 133.
"""

from __future__ import annotations

from typing import Any

from .record import oracle

PHASE = "O4"
M = 1_000_000.0

# -----------------------------------------------------------------------------
# CRR Art. 153(5) Table 1
# -----------------------------------------------------------------------------
#   Remaining maturity   Cat 1   Cat 2   Cat 3   Cat 4   Cat 5
#   < 2.5 years           50%     70%    115%    250%      0%
#   >= 2.5 years          70%     90%    115%    250%      0%
#
# Categories 1-5 are the "strong / good / satisfactory / weak / default" rating
# grades of the slotting criteria.
CRR_SLOTTING_SHORT = {
    "strong": 0.50,
    "good": 0.70,
    "satisfactory": 1.15,
    "weak": 2.50,
    "default": 0.00,
}
CRR_SLOTTING_LONG = {
    "strong": 0.70,
    "good": 0.90,
    "satisfactory": 1.15,
    "weak": 2.50,
    "default": 0.00,
}

# -----------------------------------------------------------------------------
# PS1/26 Art. 153(5) Table A
# -----------------------------------------------------------------------------
#                       Strong        Good       Satisfactory  Weak  Default
#                        A     B      C     D
#   Object / project /
#   commodities / IPRE   50%   70%    70%   90%      115%      250%    0%
#   HVCRE                70%   95%    95%  120%      140%      250%    0%
#
# Art. 153(5)(c): assign column B to Strong and column D to Good.
# Art. 153(5)(d): where less than 2.5 years remain, an institution may assign
#   column A to Strong and column C to Good instead.
B31_SLOTTING_LONG = {
    "strong": 0.70,
    "good": 0.90,
    "satisfactory": 1.15,
    "weak": 2.50,
    "default": 0.00,
}
B31_SLOTTING_SHORT = {
    "strong": 0.50,
    "good": 0.70,
    "satisfactory": 1.15,
    "weak": 2.50,
    "default": 0.00,
}
B31_SLOTTING_HVCRE_LONG = {
    "strong": 0.95,
    "good": 1.20,
    "satisfactory": 1.40,
    "weak": 2.50,
    "default": 0.00,
}
B31_SLOTTING_HVCRE_SHORT = {
    "strong": 0.70,
    "good": 0.95,
    "satisfactory": 1.40,
    "weak": 2.50,
    "default": 0.00,
}


def _slotting(
    oracle_id: str,
    framework: str,
    regulation: str,
    category: str,
    risk_weight: float,
    inputs: dict[str, Any],
) -> dict[str, Any]:
    return oracle(
        oracle_id=oracle_id,
        phase=PHASE,
        framework=framework,
        approach="SLOTTING",
        exposure_class="specialised_lending",
        regulation=regulation,
        ead=M,
        risk_weight=risk_weight,
        inputs={"slotting_category": category, **inputs},
    )


def slotting() -> list[dict[str, Any]]:
    long_dated = {"is_short_maturity": False, "sl_type": "project_finance"}
    short_dated = {"is_short_maturity": True, "sl_type": "project_finance"}
    return [
        _slotting(
            "ORC-110",
            "CRR",
            "CRR Art. 153(5) Table 1: category 1 (strong) specialised lending, "
            "remaining maturity >= 2.5 years -> 70% RW",
            "strong",
            CRR_SLOTTING_LONG["strong"],
            long_dated,
        ),
        _slotting(
            "ORC-111",
            "CRR",
            "CRR Art. 153(5) Table 1: category 1 (strong) specialised lending, "
            "remaining maturity < 2.5 years -> 50% RW",
            "strong",
            CRR_SLOTTING_SHORT["strong"],
            short_dated,
        ),
        _slotting(
            "ORC-112",
            "CRR",
            "CRR Art. 153(5) Table 1: category 2 (good), >= 2.5 years -> 90% RW",
            "good",
            CRR_SLOTTING_LONG["good"],
            long_dated,
        ),
        _slotting(
            "ORC-113",
            "CRR",
            "CRR Art. 153(5) Table 1: category 3 (satisfactory) -> 115% RW",
            "satisfactory",
            CRR_SLOTTING_LONG["satisfactory"],
            long_dated,
        ),
        _slotting(
            "ORC-114",
            "CRR",
            "CRR Art. 153(5) Table 1: category 4 (weak) -> 250% RW",
            "weak",
            CRR_SLOTTING_LONG["weak"],
            long_dated,
        ),
        _slotting(
            "ORC-115",
            "CRR",
            "CRR Art. 153(5) Table 1: category 5 (default) -> 0% RW",
            "default",
            CRR_SLOTTING_LONG["default"],
            long_dated,
        ),
        _slotting(
            "ORC-116",
            "BASEL_3_1",
            "PS1/26 Art. 153(5)(c)(i) Table A column B: strong project finance, "
            "remaining maturity >= 2.5 years -> 70% RW",
            "strong",
            B31_SLOTTING_LONG["strong"],
            long_dated,
        ),
        _slotting(
            "ORC-117",
            "BASEL_3_1",
            "PS1/26 Art. 153(5)(d)(i) Table A column A: strong project finance "
            "with less than 2.5 years to maturity -> 50% RW",
            "strong",
            B31_SLOTTING_SHORT["strong"],
            short_dated,
        ),
        _slotting(
            "ORC-118",
            "BASEL_3_1",
            "PS1/26 Art. 153(5)(c)(ii) Table A column D: good project finance, "
            ">= 2.5 years -> 90% RW",
            "good",
            B31_SLOTTING_LONG["good"],
            long_dated,
        ),
        _slotting(
            "ORC-119",
            "BASEL_3_1",
            "PS1/26 Art. 153(5)(c) Table A, HVCRE row column B: strong HVCRE, "
            ">= 2.5 years -> 95% RW",
            "strong",
            B31_SLOTTING_HVCRE_LONG["strong"],
            {"is_short_maturity": False, "sl_type": "hvcre", "is_hvcre": True},
        ),
        _slotting(
            "ORC-120",
            "BASEL_3_1",
            "PS1/26 Art. 153(5)(c) Table A, HVCRE row: satisfactory HVCRE -> 140% RW",
            "satisfactory",
            B31_SLOTTING_HVCRE_LONG["satisfactory"],
            {"is_short_maturity": False, "sl_type": "hvcre", "is_hvcre": True},
        ),
    ]


# -----------------------------------------------------------------------------
# CRR Art. 155(2) -- equity simple risk-weight approach
# -----------------------------------------------------------------------------
CRR_EQUITY_PRIVATE_DIVERSIFIED_RW = 1.90
CRR_EQUITY_EXCHANGE_TRADED_RW = 2.90
CRR_EQUITY_OTHER_RW = 3.70


def equity_irb() -> list[dict[str, Any]]:
    return [
        oracle(
            oracle_id="ORC-121",
            phase=PHASE,
            framework="CRR",
            approach="EQUITY",
            exposure_class="equity",
            regulation="CRR Art. 155(2): simple risk-weight approach -- private "
            "equity in a sufficiently diversified portfolio -> 190% RW",
            ead=M,
            risk_weight=CRR_EQUITY_PRIVATE_DIVERSIFIED_RW,
            inputs={
                "equity_type": "private_equity",
                "is_diversified": True,
                "permission": "IRB",
            },
        ),
        oracle(
            oracle_id="ORC-122",
            phase=PHASE,
            framework="CRR",
            approach="EQUITY",
            exposure_class="equity",
            regulation="CRR Art. 155(2): simple risk-weight approach -- exchange "
            "traded equity -> 290% RW",
            ead=M,
            risk_weight=CRR_EQUITY_EXCHANGE_TRADED_RW,
            inputs={
                "equity_type": "exchange_traded",
                "is_exchange_traded": True,
                "permission": "IRB",
            },
        ),
        oracle(
            oracle_id="ORC-123",
            phase=PHASE,
            framework="CRR",
            approach="EQUITY",
            exposure_class="equity",
            regulation="CRR Art. 155(2): simple risk-weight approach -- all other "
            "equity exposures -> 370% RW",
            ead=M,
            risk_weight=CRR_EQUITY_OTHER_RW,
            inputs={"equity_type": "unlisted", "permission": "IRB"},
        ),
    ]


def all_oracles() -> list[dict[str, Any]]:
    return [*slotting(), *equity_irb()]
