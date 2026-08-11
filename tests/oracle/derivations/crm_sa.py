"""
Phase O3 -- credit risk mitigation on the Standardised Approach side.

Every number below was read out of `docs/assets/crr.pdf` (the onshored
Regulation (EU) No 575/2013 as amended for the UK) and is cited to the article,
table and column it came from. Nothing here reads the engine, and nothing here
reads the rulepack -- the rulepack is where the engine keeps its values, so
sourcing an expected value from it would make this module a mirror rather than
an oracle.

Scope covered (the first four items of the O3 roadmap in ``README.md``):

1. Financial Collateral Simple Method -- Art. 222, eligibility Art. 197.
2. Financial Collateral Comprehensive Method -- the Art. 224 supervisory
   volatility adjustments and the Art. 223(2)/(3)/(5) composition
   ``E* = max(0, E(1 + H_E) - C(1 - H_C - H_fx))``.
3. The Art. 233(3) currency-mismatch adjustment to unfunded protection.
4. Guarantees under the Art. 235(1) risk-weight substitution formula, with
   partial cover and the Art. 201(1) eligibility list.

Deliberately NOT covered (O3 roadmap items 5 and 6):

- F-IRB ``LGD*`` (Art. 228(2), 230, 231). Every oracle here is an SA exposure.
- The Art. 237/238 maturity-mismatch adjustment. It is not merely absent, it is
  actively held OFF: the engine takes T = 5 years when the exposure carries no
  maturity (Art. 238(1)), which would put a factor of ``(t - 0.25)/(T - 0.25)``
  on every pledge maturing inside five years. Each collateral oracle therefore
  sets ``exposure_maturity_years`` short enough that ``t >= T`` and the factor is
  exactly 1.0, so what is being measured is the Art. 224 haircut alone. Removing
  that input turns these into maturity-mismatch oracles by accident -- which is
  how the first draft of this module read a 42% understatement that was really
  Art. 238 doing its job.

- ``H_E``, the Art. 223(3) exposure-side volatility adjustment, is zero for
  every oracle here: Art. 223(3) applies it to the exposure itself, which is
  non-zero only where the exposure IS a security (an SFT lending a bond out).
  All of these are cash loans, so ``E_VA = E``.

References:
- Art. 197      eligibility of collateral under all approaches and methods
- Art. 198      additional eligibility under the Comprehensive Method
- Art. 201      eligibility of protection providers under all approaches
- Art. 222      Financial Collateral Simple Method
- Art. 223      Financial Collateral Comprehensive Method
- Art. 224      supervisory volatility adjustments (Tables 1 to 4)
- Art. 226      scaling up for non-daily revaluation
- Art. 228(1)   E* is the SA exposure value
- Art. 233      valuation of unfunded credit protection
- Art. 235      SA risk-weighted exposure amount with unfunded protection
- Art. 114 / 120 / 122 / 134  the risk weights the collateral and the
                              guarantors are weighted at
"""

from __future__ import annotations

import math
from typing import Any

from .record import oracle

FRAMEWORK = "CRR"
PHASE = "O3"

M = 1_000_000.0

#: The obligor every oracle shares: an unsecured corporate rated CQS 5.
#: Art. 122(1) Table 6 puts that at 150%, which is deliberately far from both the
#: Art. 222(3) 20% floor and every collateral / guarantor weight used below, so a
#: blended weight can only come out right for the right reason.
OBLIGOR_CQS = 5
OBLIGOR_RW = 1.50

#: Exposure value E under Art. 111, and the pledged market value C.
E = M
C = 300_000.0

#: Art. 224(2): the liquidation period, in business days, by transaction type.
LIQ_SECURED_LENDING = 20  # Art. 224(2)(a)
LIQ_REPO = 5  # Art. 224(2)(b)
LIQ_CAPITAL_MARKET = 10  # Art. 224(2)(c)

# -----------------------------------------------------------------------------
# Art. 224(1) Table 1 -- debt securities, 10-day liquidation-period column
# -----------------------------------------------------------------------------
# Columns 4-6 of Table 1, i.e. the volatility adjustments for debt securities
# issued by the entities described in Art. 197(1)(b) -- central governments and
# central banks, plus the Art. 197(2) assimilations.
#
#   CQS   <= 1 year    > 1 <= 5 years    > 5 years
#   1       0,5 %          2 %              4 %
#   2-3     1 %            3 %              6 %
#   4      15 %           15 %             15 %
_TABLE_1_SOVEREIGN: dict[int, dict[str, float]] = {
    1: {"0_1y": 0.005, "1_5y": 0.02, "5y_plus": 0.04},
    2: {"0_1y": 0.01, "1_5y": 0.03, "5y_plus": 0.06},
    3: {"0_1y": 0.01, "1_5y": 0.03, "5y_plus": 0.06},
    4: {"0_1y": 0.15, "1_5y": 0.15, "5y_plus": 0.15},
}

# Columns 7-9 of Table 1: debt securities issued by the entities described in
# Art. 197(1)(c) (institutions) and (d) (other entities, i.e. corporates).
#
#   CQS   <= 1 year    > 1 <= 5 years    > 5 years
#   1       1 %            4 %              8 %
#   2-3     2 %            6 %             12 %
#   4       N/A            N/A              N/A
_TABLE_1_OTHER: dict[int, dict[str, float]] = {
    1: {"0_1y": 0.01, "1_5y": 0.04, "5y_plus": 0.08},
    2: {"0_1y": 0.02, "1_5y": 0.06, "5y_plus": 0.12},
    3: {"0_1y": 0.02, "1_5y": 0.06, "5y_plus": 0.12},
}

#: Art. 224(1) Table 3, 10-day column -- "other collateral or exposure types".
#: Main index equities / main index convertible bonds 15%, other equities or
#: convertible bonds listed on a recognised exchange 25%, cash 0%, gold 15%.
_TABLE_3 = {
    "cash": 0.0,
    "gold": 0.15,
    "equity_main_index": 0.15,
    "equity_other_listed": 0.25,
}

#: Art. 224(1) Table 4, 10-day column -- volatility adjustment for currency
#: mismatch. Art. 233(4) fixes the SAME 10-day basis for unfunded protection,
#: which is why the guarantee oracles below use 8% flat whatever the
#: transaction's own liquidation period would be.
_TABLE_4_FX = 0.08

#: Art. 224(1) Tables 1, 3 and 4 as PRINTED for the 20-day and 5-day liquidation
#: periods, in percent, exactly as they appear in the PDF. Used only to check the
#: square-root-of-time relation asserted below -- never to derive an oracle.
_PRINTED_20_DAY = {
    0.005: 0.707,
    0.01: 1.414,
    0.02: 2.828,
    0.03: 4.243,
    0.04: 5.657,
    0.06: 8.485,
    0.08: 11.314,
    0.12: 16.971,
    0.15: 21.213,
    0.25: 35.355,
}
_PRINTED_5_DAY = {
    0.005: 0.354,
    0.01: 0.707,
    0.02: 1.414,
    0.03: 2.121,
    0.04: 2.828,
    0.06: 4.243,
    0.08: 5.657,
    0.12: 8.485,
    0.15: 10.607,
    0.25: 17.678,
}


def _scaled(haircut_10_day: float, liquidation_period_days: int) -> float:
    """The Art. 224(1) volatility adjustment for a liquidation period.

    Art. 224(1) publishes three columns per row -- 20, 10 and 5 business days --
    and Art. 224(2) says which applies to which transaction type. The columns are
    one number scaled by the square root of time, and the printed figures are that
    number rounded to three decimal places of a percent: 2% at 10 days is
    2.828427...% at 20 days, printed "2,828". This returns the UNROUNDED value,
    because the oracle is compared at a relative tolerance of 1e-6 and the printed
    3-dp figure is only good to about 1e-4.

    ``_assert_printed_columns`` below checks this function against every printed
    figure it is used for, so the relation is evidenced rather than assumed.
    """
    return haircut_10_day * math.sqrt(liquidation_period_days / 10.0)


def _assert_printed_columns() -> None:
    """The scaling relation reproduces Art. 224(1)'s own 20-day and 5-day columns.

    Runs at import. If a future reading of the table disagrees with the
    square-root-of-time relation, ``derive.py`` fails here rather than quietly
    publishing a value no column of Table 1 contains.

    Scope note: the SECURITISATION columns of Table 1 are excluded, and are not
    used by any oracle in this module. Three of their printed figures are not the
    3-dp rounding of the relation (CQS 1 <= 1 year reads 2,829 against 2.828, CQS
    2-3 > 5 years reads 33,942 against 33.941, and the 5-day CQS 1 > 5 years
    reads 11,313 against 11.314), so the securitisation family needs its own
    reading before it can be pinned.
    """
    for base, printed in _PRINTED_20_DAY.items():
        derived = round(_scaled(base, 20) * 100.0, 3)
        if derived != printed:
            raise ValueError(
                f"Art. 224(1) 20-day column: {base:.3%} at 10 days scales to "
                f"{derived}%, but the table prints {printed}%"
            )
    for base, printed in _PRINTED_5_DAY.items():
        derived = round(_scaled(base, 5) * 100.0, 3)
        if derived != printed:
            raise ValueError(
                f"Art. 224(1) 5-day column: {base:.3%} at 10 days scales to "
                f"{derived}%, but the table prints {printed}%"
            )


_assert_printed_columns()


# -----------------------------------------------------------------------------
# The risk weights the collateral and the guarantors are weighted at
# -----------------------------------------------------------------------------
# Art. 114(2) Table 1 -- central governments and central banks.
#   CQS  1     2     3     4     5     6
#   RW   0%   20%   50%  100%  100%  150%
# Art. 114(1): 100% where no paragraph 2-7 treatment applies (unrated).
_SOVEREIGN_RW = {1: 0.00, 2: 0.20, 3: 0.50, 4: 1.00, 5: 1.00, 6: 1.50, None: 1.00}

# Art. 120(1) Table 3 -- rated institutions, residual maturity over 3 months.
#   CQS  1     2     3     4     5     6
#   RW  20%   50%   50%  100%  100%  150%
_INSTITUTION_RW = {1: 0.20, 2: 0.50, 3: 0.50, 4: 1.00, 5: 1.00, 6: 1.50, None: 1.00}

# Art. 122(1) Table 6 -- corporates.
#   CQS  1     2     3     4     5     6
#   RW  20%   50%  100%  100%  150%  150%
# Art. 122(2): 100% where the corporate is unrated (the obligor's own weight
# here is the CQS 5 150%, not this).
_CORPORATE_RW = {1: 0.20, 2: 0.50, 3: 1.00, 4: 1.00, 5: 1.50, 6: 1.50, None: 1.00}

#: Art. 222(3): "The risk weight of the collateralised portion shall be at least
#: 20% except as specified in paragraphs 4 to 6."
FCSM_RW_FLOOR = 0.20

#: Art. 222(6)(b): a 0%-RW central-government debt security qualifies for the 0%
#: carve-out only where "its market value has been discounted by 20%".
FCSM_SOVEREIGN_DISCOUNT = 0.20

#: Art. 222(1) / Art. 134: the weight a cash deposit, a cash assimilated
#: instrument or gold would carry as a direct exposure.
CASH_AND_GOLD_RW = 0.00

#: Art. 222(1): equity held as financial collateral is weighted at the weight it
#: would carry as a direct exposure to the instrument -- Art. 133(1) 100% under
#: CRR (there is no Art. 222 carve-out for equity, and no floor issue: 100% is
#: already above the Art. 222(3) 20% floor).
EQUITY_COLLATERAL_RW = 1.00


# -----------------------------------------------------------------------------
# Fact-pattern builders
# -----------------------------------------------------------------------------
#: Art. 238(1) caps the effective maturity of the underlying at five years and
#: the engine assumes that cap when the exposure carries no maturity. A quarter
#: of a year keeps T at the Art. 238 0.25 lower bound, so every pledge below has
#: t >= T and no Art. 237/238 maturity mismatch exists to adjust for.
_SHORT_EXPOSURE_MATURITY_YEARS = 0.25

#: Residual maturities chosen to land one pledge in each Art. 224(1) Table 1
#: maturity band: <= 1 year, > 1 <= 5 years, > 5 years.
_BAND_MATURITY = {"0_1y": 0.5, "1_5y": 3.0, "5y_plus": 7.0}
_BAND_LABEL = {
    "0_1y": "residual maturity <= 1 year",
    "1_5y": "residual maturity > 1 and <= 5 years",
    "5y_plus": "residual maturity > 5 years",
}


def _obligor(**extra: Any) -> dict[str, Any]:
    """The shared obligor inputs."""
    return {"exposure_class": "corporate", "cqs": OBLIGOR_CQS, **extra}


def _bond(
    *,
    issuer: str,
    cqs: int | None,
    band: str,
    market_value: float = C,
    currency: str = "GBP",
    liquidation_period_days: int | None = None,
) -> dict[str, Any]:
    """One pledged debt security.

    ``issuer`` is ``"sovereign"`` for an Art. 197(1)(b) security and
    ``"corporate"`` for an Art. 197(1)(d) one; the engine reads the issuer from
    ``issuer_type`` and the instrument class from ``collateral_type``.
    """
    row: dict[str, Any] = {
        "collateral_type": "government_bond" if issuer == "sovereign" else "corporate_bond",
        "issuer_type": issuer,
        "issuer_cqs": cqs,
        "residual_maturity_years": _BAND_MATURITY[band],
        "market_value": market_value,
        "currency": currency,
    }
    if liquidation_period_days is not None:
        row["liquidation_period_days"] = liquidation_period_days
    return row


def _other_collateral(
    kind: str,
    *,
    market_value: float = C,
    currency: str = "GBP",
    liquidation_period_days: int | None = None,
) -> dict[str, Any]:
    """One pledged Art. 224(1) Table 3 item: cash, gold or equity."""
    row: dict[str, Any] = {"market_value": market_value, "currency": currency}
    if kind == "cash":
        row["collateral_type"] = "cash"
    elif kind == "gold":
        row["collateral_type"] = "gold"
    else:
        row["collateral_type"] = "equity"
        row["is_main_index"] = kind == "equity_main_index"
        row["is_listed"] = kind in ("equity_main_index", "equity_other_listed")
    if liquidation_period_days is not None:
        row["liquidation_period_days"] = liquidation_period_days
    return row


def _comprehensive(
    oracle_id: str,
    regulation: str,
    collateral: list[dict[str, Any]],
    haircuts: list[tuple[float, float]],
    *,
    exposure: float = E,
    is_sft: bool = False,
) -> dict[str, Any]:
    """One Financial Collateral Comprehensive Method oracle.

    ``haircuts`` is one ``(H_C, H_fx)`` pair per pledge, in the same order.
    Art. 223(2) gives ``C_VA = C x (1 - H_C - H_fx)`` per item, Art. 223(3) gives
    ``E_VA = E x (1 + H_E)`` with ``H_E = 0`` for a cash loan, and Art. 223(5)
    composes them as ``E* = max(0, E_VA - C_VAM)``. Art. 228(1) then makes E* the
    SA exposure value, so RWEA = E* x the obligor's own risk weight -- the
    Comprehensive Method never touches the risk weight.
    """
    per_item = [
        max(0.0, item["market_value"] * (1.0 - h_c - h_fx))
        for item, (h_c, h_fx) in zip(collateral, haircuts, strict=True)
    ]
    c_va = sum(per_item)
    e_star = max(0.0, exposure - c_va)
    inputs = _obligor(
        collateral=collateral,
        exposure_maturity_years=_SHORT_EXPOSURE_MATURITY_YEARS,
    )
    if is_sft:
        inputs["is_sft"] = True
    return oracle(
        oracle_id=oracle_id,
        phase=PHASE,
        framework=FRAMEWORK,
        approach="SA",
        exposure_class="corporate",
        regulation=regulation,
        ead=exposure,
        risk_weight=OBLIGOR_RW if e_star > 0 else 0.0,
        inputs=inputs,
        intermediate={
            "collateral_volatility_adjusted_value_CVA": c_va,
            "exposure_volatility_adjusted_value_EVA": exposure,
        },
        rwa=e_star * OBLIGOR_RW,
        extra_expected={"ead": e_star},
    )


def _simple(
    oracle_id: str,
    regulation: str,
    collateral: list[dict[str, Any]],
    recognised: list[tuple[float, float]],
) -> dict[str, Any]:
    """One Financial Collateral Simple Method oracle.

    ``recognised`` is one ``(value, risk_weight)`` pair per pledge: the market
    value Art. 222(2) recognises (after any Art. 222(6)(b) 20% discount, and zero
    for a pledge Art. 197 does not make eligible collateral at all) and the
    weight Art. 222(3)/(6) puts on the portion it collateralises.

    Art. 222 does NOT reduce the exposure value -- it substitutes risk weights --
    so ``expected["ead"]`` stays at E, which is itself an assertion worth making.
    The collateralised proportion is capped at 100% (a pledge cannot secure more
    than the whole exposure), and the remainder keeps the obligor's own weight.
    """
    covered = min(sum(value for value, _ in recognised), E)
    weighted = sum(value * weight for value, weight in recognised)
    secured_rw = (weighted / sum(value for value, _ in recognised)) if covered else 0.0
    secured_share = covered / E
    blended = secured_share * secured_rw + (1.0 - secured_share) * OBLIGOR_RW
    return oracle(
        oracle_id=oracle_id,
        phase=PHASE,
        framework=FRAMEWORK,
        approach="SA",
        exposure_class="corporate",
        regulation=regulation,
        ead=E,
        risk_weight=blended,
        inputs=_obligor(
            crm_method="simple",
            collateral=collateral,
            exposure_maturity_years=_SHORT_EXPOSURE_MATURITY_YEARS,
        ),
        intermediate={
            "collateralised_value": covered,
            "collateralised_portion_risk_weight": secured_rw,
        },
        rwa=E * blended,
        extra_expected={"ead": E},
    )


def _guaranteed(
    oracle_id: str,
    regulation: str,
    *,
    entity_type: str,
    guarantor_cqs: int | None,
    guarantor_rw: float | None,
    amount_covered: float,
    currency: str = "GBP",
) -> dict[str, Any]:
    """One Art. 235(1) risk-weight substitution oracle.

    ``guarantor_rw`` of None means the protection is not recognised -- either the
    provider is outside the Art. 201(1) list, or Art. 193(1) declines a
    substitution that would raise RWEA -- and the whole exposure keeps the
    obligor's weight.

    Art. 233(3) reduces the nominal protection G to
    ``G* = G x (1 - H_fx)`` on a currency mismatch, with H_fx fixed by
    Art. 233(4) on a 10-BUSINESS-DAY basis -- Art. 224(1) Table 4's middle
    column, 8% -- regardless of the transaction's own liquidation period.
    Art. 235(1) then gives
    ``RWEA = max(0, E - G_A) x r + G_A x g``, and Art. 235(2) permits it only
    where the protected and unprotected parts rank equally, which they do here.
    """
    h_fx = 0.0 if currency == "GBP" else _TABLE_4_FX
    g_star = amount_covered * (1.0 - h_fx)
    covered = 0.0 if guarantor_rw is None else min(g_star, E)
    effective_g = OBLIGOR_RW if guarantor_rw is None else guarantor_rw
    rwea = (E - covered) * OBLIGOR_RW + covered * effective_g
    return oracle(
        oracle_id=oracle_id,
        phase=PHASE,
        framework=FRAMEWORK,
        approach="SA",
        exposure_class="corporate",
        regulation=regulation,
        ead=E,
        risk_weight=rwea / E,
        inputs=_obligor(
            guarantees=[{"amount_covered": amount_covered, "currency": currency}],
            guarantors=[{"ref": "GTOR001", "entity_type": entity_type, "cqs": guarantor_cqs}],
        ),
        intermediate={
            "protection_value_after_fx_G_star": g_star,
            "covered_amount_GA": covered,
            "guarantor_risk_weight_g": effective_g,
        },
        rwa=rwea,
        extra_expected={"ead": E},
    )


# -----------------------------------------------------------------------------
# ORC-200 to ORC-220 -- Art. 224(1) Table 1, whole domain, 10-day column
# -----------------------------------------------------------------------------
# Art. 224(2)(c) puts a capital-market-driven transaction on a 10-business-day
# liquidation period, so these read the printed 10-day column with no scaling in
# the way. Every populated cell of the sovereign and non-sovereign halves of
# Table 1 is pinned -- 12 sovereign and 9 other -- including the cells that
# agree today. A defect at two sampled cells of a table is not a characterised
# defect: the Art. 121 Table 5 finding recorded in ``test_oracle.py`` reads as
# purely conservative at the first two steps and anti-conservative at the last.
_SOVEREIGN_BAND_IDS = {
    (1, "0_1y"): "ORC-200",
    (1, "1_5y"): "ORC-201",
    (1, "5y_plus"): "ORC-202",
    (2, "0_1y"): "ORC-203",
    (2, "1_5y"): "ORC-204",
    (2, "5y_plus"): "ORC-205",
    (3, "0_1y"): "ORC-206",
    (3, "1_5y"): "ORC-207",
    (3, "5y_plus"): "ORC-208",
    (4, "0_1y"): "ORC-209",
    (4, "1_5y"): "ORC-210",
    (4, "5y_plus"): "ORC-211",
}
_OTHER_BAND_IDS = {
    (1, "0_1y"): "ORC-212",
    (1, "1_5y"): "ORC-213",
    (1, "5y_plus"): "ORC-214",
    (2, "0_1y"): "ORC-215",
    (2, "1_5y"): "ORC-216",
    (2, "5y_plus"): "ORC-217",
    (3, "0_1y"): "ORC-218",
    (3, "1_5y"): "ORC-219",
    (3, "5y_plus"): "ORC-220",
}


def table_1_haircuts() -> list[dict[str, Any]]:
    """Every populated cell of Art. 224(1) Table 1, 10-day column."""
    out: list[dict[str, Any]] = []
    for (cqs, band), oracle_id in sorted(_SOVEREIGN_BAND_IDS.items(), key=lambda kv: kv[1]):
        haircut = _TABLE_1_SOVEREIGN[cqs][band]
        out.append(
            _comprehensive(
                oracle_id,
                f"CRR Art. 224(1) Table 1 (Art. 197(1)(b) issuer), 10-day column: "
                f"CQS {cqs}, {_BAND_LABEL[band]} -> H_C = {haircut:.3%}; "
                f"Art. 223(2)/(5) and Art. 228(1)",
                [_bond(issuer="sovereign", cqs=cqs, band=band, liquidation_period_days=10)],
                [(haircut, 0.0)],
            )
        )
    for (cqs, band), oracle_id in sorted(_OTHER_BAND_IDS.items(), key=lambda kv: kv[1]):
        haircut = _TABLE_1_OTHER[cqs][band]
        out.append(
            _comprehensive(
                oracle_id,
                f"CRR Art. 224(1) Table 1 (Art. 197(1)(c)/(d) issuer), 10-day column: "
                f"CQS {cqs}, {_BAND_LABEL[band]} -> H_C = {haircut:.3%}; "
                f"Art. 223(2)/(5) and Art. 228(1)",
                [_bond(issuer="corporate", cqs=cqs, band=band, liquidation_period_days=10)],
                [(haircut, 0.0)],
            )
        )
    return out


# -----------------------------------------------------------------------------
# ORC-221 to ORC-224 -- Art. 224(1) Table 3, 10-day column
# -----------------------------------------------------------------------------
_TABLE_3_IDS = {
    "cash": "ORC-221",
    "gold": "ORC-222",
    "equity_main_index": "ORC-223",
    "equity_other_listed": "ORC-224",
}
_TABLE_3_LABEL = {
    "cash": "cash",
    "gold": "gold",
    "equity_main_index": "main index equities / main index convertible bonds",
    "equity_other_listed": "other equities or convertible bonds listed on a recognised exchange",
}


def table_3_haircuts() -> list[dict[str, Any]]:
    """Every row of Art. 224(1) Table 3, 10-day column."""
    return [
        _comprehensive(
            _TABLE_3_IDS[kind],
            f"CRR Art. 224(1) Table 3, 10-day column: {_TABLE_3_LABEL[kind]} -> "
            f"H_C = {_TABLE_3[kind]:.3%}; Art. 223(2)/(5) and Art. 228(1)",
            [_other_collateral(kind, liquidation_period_days=10)],
            [(_TABLE_3[kind], 0.0)],
        )
        for kind in ("cash", "gold", "equity_main_index", "equity_other_listed")
    ]


# -----------------------------------------------------------------------------
# ORC-225 to ORC-232 -- Art. 197 eligibility, Comprehensive Method
# -----------------------------------------------------------------------------
# Art. 197(1)(b) admits a central-government security only where its ECAI
# assessment is associated with "credit quality step 4 or above", and
# Art. 197(1)(c)/(d) an institution's or other entity's only at "credit quality
# step 3 or above". A security outside those steps -- or with no ECAI assessment
# at all, since the limb is conditioned on having one -- is not eligible
# collateral, so it contributes nothing to C_VA and E* stays at E.
#
# Art. 197(1)(f) admits equity only where it is "included in a main index".
# Art. 198(1)(a) extends that to non-main-index equity "traded on a recognised
# exchange" for a firm using the Comprehensive Method, so the pledge that fails
# BOTH tests -- not in a main index and not listed -- is the ineligible one.
_INELIGIBLE_IDS = {
    ("sovereign", 5): "ORC-225",
    ("sovereign", 6): "ORC-226",
    ("sovereign", None): "ORC-227",
    ("corporate", 4): "ORC-228",
    ("corporate", 5): "ORC-229",
    ("corporate", 6): "ORC-230",
    ("corporate", None): "ORC-231",
}
_INELIGIBLE_LIMB = {
    "sovereign": "Art. 197(1)(b) (central government issuer, CQS 4 or above)",
    "corporate": "Art. 197(1)(d) (other-entity issuer, CQS 3 or above)",
}


def eligibility_gate() -> list[dict[str, Any]]:
    """Art. 197 ineligibility recognises no collateral value at all."""
    out: list[dict[str, Any]] = []
    for (issuer, cqs), oracle_id in sorted(_INELIGIBLE_IDS.items(), key=lambda kv: kv[1]):
        described = "unrated" if cqs is None else f"CQS {cqs}"
        out.append(
            _comprehensive(
                oracle_id,
                f"CRR {_INELIGIBLE_LIMB[issuer]}: an {described} debt security is "
                f"NOT eligible collateral, so C_VA = 0 and E* = E",
                [_bond(issuer=issuer, cqs=cqs, band="1_5y", liquidation_period_days=10)],
                [(1.0, 0.0)],
            )
        )
    out.append(
        _comprehensive(
            "ORC-232",
            "CRR Art. 197(1)(f) / Art. 198(1)(a): an equity that is neither in a "
            "main index nor listed on a recognised exchange is NOT eligible "
            "collateral, so C_VA = 0 and E* = E",
            [_other_collateral("equity_unlisted", liquidation_period_days=10)],
            [(1.0, 0.0)],
        )
    )
    # The Comprehensive-Method control for ORC-281. Same pledge, same
    # attestation, same article -- so a pair whose Simple-Method half disagrees
    # and whose Comprehensive half agrees localises the defect to one method
    # rather than to the rule. Without the control, "the Art. 218 gate is
    # missing" cannot be told apart from "the Art. 218 gate does not exist".
    out.append(
        _comprehensive(
            "ORC-282",
            "CRR Art. 218 with Art. 197(1)(d): an unrated third-party credit linked "
            "note is not eligible collateral, so C_VA = 0 and E* = E",
            [
                {
                    "collateral_type": "credit_linked_note",
                    "market_value": C,
                    "currency": "GBP",
                    "is_own_issued_cln": False,
                    "liquidation_period_days": 10,
                }
            ],
            [(1.0, 0.0)],
        )
    )
    return out


# -----------------------------------------------------------------------------
# ORC-233 to ORC-240 -- Art. 223(2) currency mismatch and Art. 224(2) periods
# -----------------------------------------------------------------------------
def fx_and_liquidation_period() -> list[dict[str, Any]]:
    """Art. 224(1) Table 4, and the three Art. 224(2) liquidation periods.

    Art. 223(1) second sub-paragraph requires the currency-volatility adjustment
    to be ADDED to the collateral's own adjustment, and Art. 223(2) subtracts the
    sum: ``C_VA = C x (1 - H_C - H_fx)``. The three liquidation periods are
    pinned on the same pledge so a change to one cannot hide behind another.
    """
    sovereign_1_5y = _TABLE_1_SOVEREIGN[1]["1_5y"]
    return [
        _comprehensive(
            "ORC-233",
            "CRR Art. 224(1) Table 4, 10-day column: EUR cash against a GBP "
            "exposure -> H_fx = 8%, H_C = 0%; Art. 223(1)/(2)",
            [_other_collateral("cash", currency="EUR", liquidation_period_days=10)],
            [(_TABLE_3["cash"], _TABLE_4_FX)],
        ),
        _comprehensive(
            "ORC-234",
            "CRR Art. 223(1)/(2): the Art. 224 Table 4 currency adjustment is "
            "ADDED to the collateral's own -- EUR CQS 1 sovereign security, "
            f"residual maturity 3 years -> H_C = {sovereign_1_5y:.1%} and H_fx = 8%",
            [
                _bond(
                    issuer="sovereign",
                    cqs=1,
                    band="1_5y",
                    currency="EUR",
                    liquidation_period_days=10,
                )
            ],
            [(sovereign_1_5y, _TABLE_4_FX)],
        ),
        _comprehensive(
            "ORC-235",
            "CRR Art. 224(2)(a): a secured lending transaction takes a 20-business-day "
            "liquidation period. Cash is 0% in every column of Table 3, so the "
            "scaling cannot move it -- the case that proves the period change is not "
            "silently rescaling a zero",
            [_other_collateral("cash")],
            [(_TABLE_3["cash"], 0.0)],
        ),
        _comprehensive(
            "ORC-236",
            "CRR Art. 224(1) Table 1, 20-day column (Art. 224(2)(a) secured lending): "
            f"CQS 1 sovereign security, residual maturity 3 years -> H_C = "
            f"{_scaled(sovereign_1_5y, 20):.6%}, printed in the table as 2,828%",
            [_bond(issuer="sovereign", cqs=1, band="1_5y")],
            [(_scaled(sovereign_1_5y, 20), 0.0)],
        ),
        _comprehensive(
            "ORC-237",
            "CRR Art. 224(1) Table 3, 20-day column (Art. 224(2)(a) secured lending): "
            f"gold -> H_C = {_scaled(_TABLE_3['gold'], 20):.6%}, printed as 21,213%",
            [_other_collateral("gold")],
            [(_scaled(_TABLE_3["gold"], 20), 0.0)],
        ),
        _comprehensive(
            "ORC-238",
            "CRR Art. 224(1) Table 4, 20-day column (Art. 224(2)(a) secured lending): "
            f"EUR cash against a GBP exposure -> H_fx = {_scaled(_TABLE_4_FX, 20):.6%}, "
            "printed as 11,314%",
            [_other_collateral("cash", currency="EUR")],
            [(_TABLE_3["cash"], _scaled(_TABLE_4_FX, 20))],
        ),
        _comprehensive(
            "ORC-239",
            "CRR Art. 224(1) Table 1, 5-day column (Art. 224(2)(b) repurchase / "
            "securities lending): CQS 1 sovereign security, residual maturity 3 years "
            f"-> H_C = {_scaled(sovereign_1_5y, 5):.6%}, printed as 1,414%",
            [_bond(issuer="sovereign", cqs=1, band="1_5y")],
            [(_scaled(sovereign_1_5y, 5), 0.0)],
            is_sft=True,
        ),
        _comprehensive(
            "ORC-240",
            "CRR Art. 224(1) Table 4, 5-day column (Art. 224(2)(b) repurchase / "
            f"securities lending): EUR cash -> H_fx = {_scaled(_TABLE_4_FX, 5):.6%}, "
            "printed as 5,657%",
            [_other_collateral("cash", currency="EUR")],
            [(_TABLE_3["cash"], _scaled(_TABLE_4_FX, 5))],
            is_sft=True,
        ),
    ]


# -----------------------------------------------------------------------------
# ORC-241 to ORC-243 -- the Art. 223(5) composition itself
# -----------------------------------------------------------------------------
def composition() -> list[dict[str, Any]]:
    """The ``max(0, ...)`` floor, linearity in E, and Art. 223(7) aggregation."""
    return [
        _comprehensive(
            "ORC-241",
            "CRR Art. 223(5): E* = max(0, E_VA - C_VAM) -- collateral of "
            "1,200,000 against an exposure of 1,000,000 floors E* at zero rather "
            "than producing a negative exposure value",
            [_other_collateral("cash", market_value=1_200_000.0, liquidation_period_days=10)],
            [(_TABLE_3["cash"], 0.0)],
        ),
        _comprehensive(
            "ORC-242",
            "CRR Art. 223(5): the composition is a difference, not a ratio -- the "
            "same 300,000 cash pledge against a 500,000 exposure leaves "
            "E* = 200,000, not 500,000 x (1 - 0.3)",
            [_other_collateral("cash", liquidation_period_days=10)],
            [(_TABLE_3["cash"], 0.0)],
            exposure=500_000.0,
        ),
        _comprehensive(
            "ORC-243",
            "CRR Art. 223(7): where the collateral is a number of eligible items "
            "each takes its own volatility adjustment -- 200,000 cash at 0% plus "
            "200,000 gold at 15% gives C_VA = 370,000",
            [
                _other_collateral("cash", market_value=200_000.0, liquidation_period_days=10),
                _other_collateral("gold", market_value=200_000.0, liquidation_period_days=10),
            ],
            [(_TABLE_3["cash"], 0.0), (_TABLE_3["gold"], 0.0)],
        ),
    ]


# -----------------------------------------------------------------------------
# ORC-244 to ORC-258 -- Art. 222 Financial Collateral Simple Method
# -----------------------------------------------------------------------------
def simple_method() -> list[dict[str, Any]]:
    """Art. 222: substitute the collateral's own weight, do not reduce EAD."""
    discounted = 500_000.0 * (1.0 - FCSM_SOVEREIGN_DISCOUNT)
    return [
        _simple(
            "ORC-244",
            "CRR Art. 222(6)(a): cash on deposit in the same currency as the "
            "exposure takes 0% on the collateralised portion -- the Art. 222(3) "
            "20% floor applies 'except as specified in paragraphs 4 to 6'",
            [_other_collateral("cash")],
            [(C, 0.00)],
        ),
        _simple(
            "ORC-245",
            "CRR Art. 222(3): the same cash pledge denominated in EUR against a "
            "GBP exposure fails the Art. 222(6) same-currency condition, so the "
            "collateralised portion takes max(0%, 20% floor) = 20%",
            [_other_collateral("cash", currency="EUR")],
            [(C, FCSM_RW_FLOOR)],
        ),
        _simple(
            "ORC-246",
            "CRR Art. 222(6)(b): a same-currency central-government security "
            "eligible for 0% under Art. 114 takes 0%, but only on a market value "
            "'discounted by 20%' -- 500,000 pledged is 400,000 recognised",
            [_bond(issuer="sovereign", cqs=1, band="1_5y", market_value=500_000.0)],
            [(discounted, 0.00)],
        ),
        _simple(
            "ORC-247",
            "CRR Art. 222(3)/(6)(b): the same CQS 1 sovereign security in EUR "
            "against a GBP exposure fails the same-currency condition -- no 20% "
            "market-value discount, and the 20% risk-weight floor applies to the "
            "whole 500,000",
            [
                _bond(
                    issuer="sovereign",
                    cqs=1,
                    band="1_5y",
                    market_value=500_000.0,
                    currency="EUR",
                )
            ],
            [(500_000.0, FCSM_RW_FLOOR)],
        ),
        _simple(
            "ORC-248",
            "CRR Art. 222(3) with Art. 114(2) Table 1: a CQS 2 central-government "
            "security would carry 20% as a direct exposure, which is exactly the "
            "Art. 222(3) floor",
            [_bond(issuer="sovereign", cqs=2, band="1_5y")],
            [(C, max(_SOVEREIGN_RW[2], FCSM_RW_FLOOR))],
        ),
        _simple(
            "ORC-249",
            "CRR Art. 222(3) with Art. 114(2) Table 1: a CQS 3 central-government "
            "security carries 50%, above the floor",
            [_bond(issuer="sovereign", cqs=3, band="1_5y")],
            [(C, max(_SOVEREIGN_RW[3], FCSM_RW_FLOOR))],
        ),
        _simple(
            "ORC-250",
            "CRR Art. 222(3) with Art. 114(2) Table 1: a CQS 4 central-government "
            "security carries 100%",
            [_bond(issuer="sovereign", cqs=4, band="1_5y")],
            [(C, max(_SOVEREIGN_RW[4], FCSM_RW_FLOOR))],
        ),
        _simple(
            "ORC-251",
            "CRR Art. 222(3) with Art. 122(1) Table 6: a CQS 1 corporate security carries 20%",
            [_bond(issuer="corporate", cqs=1, band="1_5y")],
            [(C, max(_CORPORATE_RW[1], FCSM_RW_FLOOR))],
        ),
        _simple(
            "ORC-252",
            "CRR Art. 222(3) with Art. 122(1) Table 6: a CQS 2 corporate security carries 50%",
            [_bond(issuer="corporate", cqs=2, band="1_5y")],
            [(C, max(_CORPORATE_RW[2], FCSM_RW_FLOOR))],
        ),
        _simple(
            "ORC-253",
            "CRR Art. 222(3) with Art. 122(1) Table 6: a CQS 3 corporate security carries 100%",
            [_bond(issuer="corporate", cqs=3, band="1_5y")],
            [(C, max(_CORPORATE_RW[3], FCSM_RW_FLOOR))],
        ),
        _simple(
            "ORC-254",
            "CRR Art. 222(1)/(3) with Art. 133(1): main-index equity held as "
            "financial collateral carries the 100% a direct equity exposure would",
            [_other_collateral("equity_main_index")],
            [(C, EQUITY_COLLATERAL_RW)],
        ),
        _simple(
            "ORC-255",
            "CRR Art. 222(3) with Art. 134(4): gold would carry 0% as a direct "
            "exposure, but it is neither cash nor a sovereign security, so no "
            "Art. 222(6) carve-out reaches it and the 20% floor binds",
            [_other_collateral("gold")],
            [(C, max(CASH_AND_GOLD_RW, FCSM_RW_FLOOR))],
        ),
        _simple(
            "ORC-256",
            "CRR Art. 222(3): a 1,200,000 same-currency cash pledge against a "
            "1,000,000 exposure collateralises the whole exposure at 0% -- there "
            "is no 'remainder of the exposure value' left to weight",
            [_other_collateral("cash", market_value=1_200_000.0)],
            [(1_200_000.0, 0.00)],
        ),
        _simple(
            "ORC-257",
            "CRR Art. 197(1)(b) via Art. 222(2): a CQS 5 central-government "
            "security is not eligible collateral, so there is no 'portion of the "
            "exposure value collateralised by the market value of eligible "
            "collateral' and the whole exposure keeps the obligor's 150%",
            [_bond(issuer="sovereign", cqs=5, band="1_5y")],
            [(0.0, 0.00)],
        ),
        _simple(
            "ORC-258",
            "CRR Art. 197(1)(d) via Art. 222(2): a CQS 4 corporate security is not "
            "eligible collateral, so the whole exposure keeps the obligor's 150%",
            [_bond(issuer="corporate", cqs=4, band="1_5y")],
            [(0.0, 0.00)],
        ),
        # ORC-274 to ORC-280 complete the Art. 197 ineligibility family on the
        # Simple Method side. Only the members whose own SA weight is BELOW the
        # obligor's can show the defect at all: a CQS 6 security carries the same
        # 150% the obligor does, so recognising it changes nothing and the oracle
        # agrees for the wrong reason. Those members are pinned precisely because
        # they agree -- a future change to the collateral weight would move them
        # silently otherwise. This is the Art. 121 Table 5 shape recorded in
        # ``test_oracle.py``: sampling the interesting members mis-characterises
        # the family.
        _simple(
            "ORC-274",
            "CRR Art. 197(1)(b) via Art. 222(2): a CQS 6 central-government "
            "security is not eligible collateral. Art. 114(2) Table 1 would weight "
            "it at the same 150% the obligor carries, so this member cannot "
            "distinguish a working eligibility gate from a missing one -- it is "
            "pinned to fix the value, not to catch the defect",
            [_bond(issuer="sovereign", cqs=6, band="1_5y")],
            [(0.0, 0.00)],
        ),
        _simple(
            "ORC-275",
            "CRR Art. 197(1)(b) via Art. 222(2): a central-government security with "
            "no ECAI credit assessment is not eligible collateral -- the limb is "
            "conditioned on having an assessment associated with CQS 4 or above",
            [_bond(issuer="sovereign", cqs=None, band="1_5y")],
            [(0.0, 0.00)],
        ),
        _simple(
            "ORC-276",
            "CRR Art. 197(1)(d) via Art. 222(2): a CQS 5 corporate security is not "
            "eligible collateral (Art. 122(1) Table 6 weights it at 150%, so this "
            "member coincides with the unsecured answer)",
            [_bond(issuer="corporate", cqs=5, band="1_5y")],
            [(0.0, 0.00)],
        ),
        _simple(
            "ORC-277",
            "CRR Art. 197(1)(d) via Art. 222(2): a CQS 6 corporate security is not "
            "eligible collateral (also 150%, also coincident)",
            [_bond(issuer="corporate", cqs=6, band="1_5y")],
            [(0.0, 0.00)],
        ),
        _simple(
            "ORC-278",
            "CRR Art. 197(1)(d) via Art. 222(2): a corporate security with no ECAI "
            "credit assessment is not eligible collateral",
            [_bond(issuer="corporate", cqs=None, band="1_5y")],
            [(0.0, 0.00)],
        ),
        _simple(
            "ORC-279",
            "CRR Art. 197(1)(f) via Art. 222(2): an equity that is in no main index "
            "is not eligible collateral under the Simple Method. Art. 198(1)(a)'s "
            "extension to non-main-index listed equity is expressly confined to a "
            "firm using the Comprehensive Method ('where an institution uses the "
            "Financial Collateral Comprehensive Method set out in Article 223'), so "
            "listing does not rescue it here",
            [_other_collateral("equity_other_listed")],
            [(0.0, 0.00)],
        ),
        _simple(
            "ORC-280",
            "CRR Art. 197(1)(b) via Art. 222(2), at full cover: a 1,000,000 CQS 5 "
            "central-government pledge against a 1,000,000 exposure is still not "
            "eligible collateral. This is the magnitude case -- if the eligibility "
            "gate is missing, the whole exposure moves from the obligor's 150% to "
            "the security's own 100%",
            [_bond(issuer="sovereign", cqs=5, band="1_5y", market_value=E)],
            [(0.0, 0.00)],
        ),
        _simple(
            "ORC-281",
            "CRR Art. 218 with Art. 197(1)(d): only a credit linked note issued by "
            "the LENDING institution may be treated as cash collateral. A "
            "third-party note is an ordinary debt security of another entity, so it "
            "needs an ECAI assessment at CQS 3 or above; unrated, it is not eligible "
            "collateral under either limb",
            [
                {
                    "collateral_type": "credit_linked_note",
                    "market_value": C,
                    "currency": "GBP",
                    "is_own_issued_cln": False,
                }
            ],
            [(0.0, 0.00)],
        ),
    ]


# -----------------------------------------------------------------------------
# ORC-259 to ORC-273 -- Art. 235 substitution and Art. 201 eligibility
# -----------------------------------------------------------------------------
G = 400_000.0


def guarantees() -> list[dict[str, Any]]:
    """Art. 235(1) substitution across the Art. 201(1) eligibility list."""
    return [
        _guaranteed(
            "ORC-259",
            "CRR Art. 235(1) with Art. 201(1)(f) and Art. 120(1) Table 3: a CQS 1 "
            "institution guarantees 400,000 of a 1,000,000 exposure -- "
            "RWEA = 600,000 x 150% + 400,000 x 20%",
            entity_type="institution",
            guarantor_cqs=1,
            guarantor_rw=_INSTITUTION_RW[1],
            amount_covered=G,
        ),
        _guaranteed(
            "ORC-260",
            "CRR Art. 233(3)/(4): the same CQS 1 institution guarantee denominated "
            "in EUR is reduced to G* = 400,000 x (1 - 8%) = 368,000 before "
            "Art. 235(1) is applied. Art. 233(4) fixes H_fx on a 10-business-day "
            "basis, so it stays 8% and is NOT scaled to the 20-day secured-lending "
            "period the collateral side would use",
            entity_type="institution",
            guarantor_cqs=1,
            guarantor_rw=_INSTITUTION_RW[1],
            amount_covered=G,
            currency="EUR",
        ),
        _guaranteed(
            "ORC-261",
            "CRR Art. 235(1) with Art. 120(1) Table 3: a CQS 3 institution guarantor carries 50%",
            entity_type="institution",
            guarantor_cqs=3,
            guarantor_rw=_INSTITUTION_RW[3],
            amount_covered=G,
        ),
        _guaranteed(
            "ORC-262",
            "CRR Art. 235(1) with Art. 201(1)(a) and Art. 114(2) Table 1: a CQS 1 "
            "central government guarantor carries 0%, so the covered portion "
            "contributes nothing to RWEA",
            entity_type="sovereign",
            guarantor_cqs=1,
            guarantor_rw=_SOVEREIGN_RW[1],
            amount_covered=G,
        ),
        _guaranteed(
            "ORC-263",
            "CRR Art. 235(1) with Art. 114(2) Table 1: a CQS 3 central government "
            "guarantor carries 50%",
            entity_type="sovereign",
            guarantor_cqs=3,
            guarantor_rw=_SOVEREIGN_RW[3],
            amount_covered=G,
        ),
        _guaranteed(
            "ORC-264",
            "CRR Art. 201(1)(b): a regional government or local authority is an "
            "eligible protection provider; Art. 115(1) weights it as an "
            "institution, so CQS 1 carries 20%",
            entity_type="rgla_sovereign",
            guarantor_cqs=1,
            guarantor_rw=_INSTITUTION_RW[1],
            amount_covered=G,
        ),
        _guaranteed(
            "ORC-265",
            "CRR Art. 201(1)(e): a public sector entity whose claims are treated "
            "under Art. 116 is an eligible protection provider; Art. 116(2) "
            "weights it as an institution, so CQS 1 carries 20%",
            entity_type="pse_sovereign",
            guarantor_cqs=1,
            guarantor_rw=_INSTITUTION_RW[1],
            amount_covered=G,
        ),
        _guaranteed(
            "ORC-266",
            "CRR Art. 201(1)(c) with Art. 117(2): a multilateral development bank "
            "on the Art. 117(2) list carries 0%",
            entity_type="mdb_named",
            guarantor_cqs=None,
            guarantor_rw=0.00,
            amount_covered=G,
        ),
        _guaranteed(
            "ORC-267",
            "CRR Art. 117(1): a multilateral development bank NOT on the "
            "Art. 117(2) list is 'treated the same as exposures to institutions', "
            "so an unrated one carries the 100% Art. 121(2) gives an unrated "
            "institution -- the same Art. 201(1)(c) eligibility, a very different "
            "weight",
            entity_type="mdb",
            guarantor_cqs=None,
            guarantor_rw=_INSTITUTION_RW[None],
            amount_covered=G,
        ),
        _guaranteed(
            "ORC-268",
            "CRR Art. 201(1)(g)(i) with Art. 122(1) Table 6: a corporate with an "
            "ECAI credit assessment IS an eligible protection provider; CQS 2 "
            "carries 50%",
            entity_type="corporate",
            guarantor_cqs=2,
            guarantor_rw=_CORPORATE_RW[2],
            amount_covered=G,
        ),
        _guaranteed(
            "ORC-269",
            "CRR Art. 201(1)(g): a corporate with NO ECAI credit assessment is not "
            "an eligible protection provider under the Standardised Approach -- "
            "limb (ii) is open only to a firm calculating under the IRB Approach. "
            "No substitution; the whole exposure keeps 150%",
            entity_type="corporate",
            guarantor_cqs=None,
            guarantor_rw=None,
            amount_covered=G,
        ),
        _guaranteed(
            "ORC-270",
            "CRR Art. 201(1): the list of eligible protection providers is "
            "exhaustive and has no retail or natural-person limb, so a guarantee "
            "from an individual is not recognised at all",
            entity_type="individual",
            guarantor_cqs=None,
            guarantor_rw=None,
            amount_covered=G,
        ),
        _guaranteed(
            "ORC-271",
            "CRR Art. 193(1) with Art. 122(1) Table 6: a CQS 6 corporate guarantor "
            "carries 150%, the same weight as the obligor, so recognising the "
            "protection cannot reduce RWEA and the substitution is not applied",
            entity_type="corporate",
            guarantor_cqs=6,
            guarantor_rw=None,
            amount_covered=G,
        ),
        _guaranteed(
            "ORC-272",
            "CRR Art. 235(1): where G_A equals E the whole exposure takes the "
            "guarantor's weight -- max(0, E - G_A) is zero and RWEA = E x g",
            entity_type="institution",
            guarantor_cqs=1,
            guarantor_rw=_INSTITUTION_RW[1],
            amount_covered=E,
        ),
        _guaranteed(
            "ORC-273",
            "CRR Art. 235(1): protection of 1,400,000 over a 1,000,000 exposure is "
            "recognised only up to E -- max(0, E - G_A) floors at zero and the "
            "excess 400,000 buys nothing",
            entity_type="institution",
            guarantor_cqs=1,
            guarantor_rw=_INSTITUTION_RW[1],
            amount_covered=1_400_000.0,
        ),
    ]


def all_oracles() -> list[dict[str, Any]]:
    """Every phase O3 oracle record."""
    return [
        *table_1_haircuts(),
        *table_3_haircuts(),
        *eligibility_gate(),
        *fx_and_liquidation_period(),
        *composition(),
        *simple_method(),
        *guarantees(),
    ]
