"""P1.346 — the Simple-Method decline on the production path, and its C 07.00 trail.

Pipeline position:
    RawDataBundle -> PipelineOrchestrator (SIMPLE elected) -> results
    -> COREPGenerator -> C 07.00 / OF 07.00 col 0070

One book, four GBP loans, run under both regimes with the Art. 222 Financial
Collateral Simple Method elected:

    ref        obligor (own RW)                 Simple-Method collateral
    L_SOV_EUR  GB sovereign (0%, Art. 114(4))   1,000,000 EUR cash (Art. 222(3) 20% floor)
    L_SOV_BND  GB sovereign (0%)                500,000 CQS 3 corporate bond (100% / 75%)
    L_CORP_EQ  unrated corporate (100%)         400,000 main-index equity (100% / 250%)
    L_CORP_CSH unrated corporate (100%)         300,000 GBP cash (Art. 222(6)(a) 0%)

Before the fix the uncapped Art. 222(3) blend RAISED the first three: 0% -> 20%,
0% -> 50% (CRR) / 37.5% (Basel 3.1), and 100% -> 124% (Basel 3.1, 2027). CRR
Art. 193(1) forbids that outright; PS1/26 Art. 193(2A) lets the firm disregard
the protection, and the owner elected to. Each declined leg is held on its
unsecured weight, and C 07.00 col 0070 — "the portion ... identified as
collateralised under article 222(3)" — reports only the collateral that was
actually substituted, so the outflow and the RWEA move on one decision.

L_CORP_EQ is the regime split: under CRR equity collateral weighs 100%, equal to
the obligor, so the substitution stands (equality is not "higher"); under Basel
3.1 it weighs 160% in 2027 (General Provisions rule 4.2 for a firm with no IRB
permission on 31 December 2026, P1.392; 250% from 2030), above the obligor, and
is declined. L_CORP_CSH is the control that must not move.

References:
- CRR Art. 193(1); Art. 222(3), (6)(a); Art. 114(4)
- PRA PS1/26 Art. 193(1) (left blank), (2A); Art. 222(3)
- COREP Annex II C 07.00 col 0070; PS1/26 Annex II OF 07.00 col 0070
"""

from __future__ import annotations

from datetime import date
from functools import cache
from typing import Any

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.domain.enums import CRMCollateralMethod
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator
from tests.fixtures.raw_bundle import make_raw_bundle

_REGIMES: tuple[str, ...] = ("crr", "b31")
_FRAMEWORK: dict[str, str] = {"crr": "CRR", "b31": "BASEL_3_1"}
_REPORTING_DATE: dict[str, date] = {"crr": date(2026, 6, 30), "b31": date(2027, 6, 30)}

_DRAWN = 1_000_000.0
_EUR_AT_PAR = pl.DataFrame([{"currency_from": "EUR", "currency_to": "GBP", "rate": 1.0}])

#: Per loan and regime: (risk weight after CRM, Simple-Method substitution applied).
_EXPECTED: dict[str, dict[str, tuple[float, bool]]] = {
    "L_SOV_EUR": {"crr": (0.0, False), "b31": (0.0, False)},
    "L_SOV_BND": {"crr": (0.0, False), "b31": (0.0, False)},
    "L_CORP_EQ": {"crr": (1.0, True), "b31": (1.0, False)},
    "L_CORP_CSH": {"crr": (0.70, True), "b31": (0.70, True)},
}

#: The uncapped Art. 222(3) blend each loan carried before the fix — the adequacy
#: evidence that every declined leg really would have raised its weight.
_PRE_FIX_BLEND: dict[str, dict[str, float]] = {
    "L_SOV_EUR": {"crr": 0.20, "b31": 0.20},
    "L_SOV_BND": {"crr": 0.50, "b31": 0.375},
    "L_CORP_EQ": {"crr": 1.00, "b31": 1.24},
    "L_CORP_CSH": {"crr": 0.70, "b31": 0.70},
}


def _bundle() -> Any:
    counterparties = pl.DataFrame(
        [
            {
                "counterparty_reference": "CP_SOV",
                "counterparty_name": "CP_SOV",
                "entity_type": "sovereign",
                "country_code": "GB",
            },
            {
                "counterparty_reference": "CP_CORP",
                "counterparty_name": "CP_CORP",
                "entity_type": "corporate",
                "country_code": "GB",
                "is_sme": False,
                "turnover_eur": 500_000_000.0,
            },
        ]
    )
    loan_base = {
        "product_type": "TERM_LOAN",
        "book_code": "BANK",
        "value_date": date(2025, 1, 1),
        "maturity_date": date(2030, 1, 1),
        "currency": "GBP",
        "seniority": "senior",
        "risk_type": "FR",
        "interest": 0.0,
        "drawn_amount": _DRAWN,
    }
    loans = pl.DataFrame(
        [
            {**loan_base, "loan_reference": "L_SOV_EUR", "counterparty_reference": "CP_SOV"},
            {**loan_base, "loan_reference": "L_SOV_BND", "counterparty_reference": "CP_SOV"},
            {**loan_base, "loan_reference": "L_CORP_EQ", "counterparty_reference": "CP_CORP"},
            {**loan_base, "loan_reference": "L_CORP_CSH", "counterparty_reference": "CP_CORP"},
        ]
    )
    pledge_base = {
        "beneficiary_type": "loan",
        "is_eligible_financial_collateral": True,
        "maturity_date": date(2035, 1, 1),
        "liquidation_period_days": 10,
        "currency": "GBP",
    }
    collateral = pl.DataFrame(
        [
            {
                **pledge_base,
                "collateral_reference": "C_EUR_CASH",
                "beneficiary_reference": "L_SOV_EUR",
                "collateral_type": "cash",
                "market_value": 1_000_000.0,
                "currency": "EUR",
            },
            {
                **pledge_base,
                "collateral_reference": "C_CORP_BOND",
                "beneficiary_reference": "L_SOV_BND",
                "collateral_type": "corporate_bond",
                "issuer_type": "corporate",
                "issuer_cqs": 3,
                "residual_maturity_years": 3.0,
                "market_value": 500_000.0,
            },
            {
                **pledge_base,
                "collateral_reference": "C_EQUITY",
                "beneficiary_reference": "L_CORP_EQ",
                "collateral_type": "equity",
                "is_main_index": True,
                "is_listed": True,
                "market_value": 400_000.0,
            },
            {
                **pledge_base,
                "collateral_reference": "C_GBP_CASH",
                "beneficiary_reference": "L_CORP_CSH",
                "collateral_type": "cash",
                "market_value": 300_000.0,
            },
        ]
    )
    return make_raw_bundle(
        loans=loans, counterparties=counterparties, collateral=collateral, fx_rates=_EUR_AT_PAR
    )


@cache
def _run(regime: str) -> tuple[pl.DataFrame, dict[str, pl.DataFrame]]:
    """The book through one regime: (results, C 07.00 / OF 07.00 sheets)."""
    factory = CalculationConfig.crr if regime == "crr" else CalculationConfig.basel_3_1
    config = factory(
        reporting_date=_REPORTING_DATE[regime],
        permission_mode=PermissionMode.STANDARDISED,
        crm_collateral_method=CRMCollateralMethod.SIMPLE,
    )
    result = PipelineOrchestrator().run_with_data(_bundle(), config)
    corep = COREPGenerator().generate_from_lazyframe(
        result.results,
        framework=_FRAMEWORK[regime],
        output_floor_summary=result.output_floor_summary,
    )
    assert corep.c07_00, f"{regime}: no C 07.00 sheet was emitted at all"
    return result.results.collect(), corep.c07_00


def _row(results: pl.DataFrame, reference: str) -> dict[str, Any]:
    picked = results.filter(pl.col("exposure_reference") == reference)
    assert picked.height == 1, f"expected one row for {reference}, got {picked.height}"
    return picked.row(0, named=True)


def _cell(sheet: pl.DataFrame, row_ref: str, col: str) -> float | None:
    row = sheet.filter(pl.col("row_ref") == row_ref)
    return None if row.height == 0 or col not in sheet.columns else row[col][0]


# =============================================================================
# The engine: no Simple-Method leg ends above its unsecured weight
# =============================================================================


@pytest.mark.parametrize("reference", list(_EXPECTED))
@pytest.mark.parametrize("regime", _REGIMES)
def test_simple_method_collateral_never_raises_the_rwea(regime: str, reference: str) -> None:
    """Each loan's post-CRM weight and RWEA, absolute, per regime.

    Arrange: the four-loan book, SIMPLE elected.
    Act:     PipelineOrchestrator.run_with_data.
    Assert:  the collateral reached the Simple Method (adequacy), the uncapped
             blend of every declined leg is above its unsecured weight, and the
             final weight / RWEA are the expected absolute figures.
    """
    # Arrange
    expected_rw, applied = _EXPECTED[reference][regime]

    # Act
    row = _row(_run(regime)[0], reference)

    # Assert — adequacy first (LESSONS C11).
    assert row["fcsm_collateral_value"] > 0.0, f"{reference}: no Simple-Method collateral"
    assert row["fcsm_collateral_rw"] * row["fcsm_collateral_value"] / _DRAWN + (
        1.0 - row["fcsm_collateral_value"] / _DRAWN
    ) * row["pre_fcsm_risk_weight"] == pytest.approx(_PRE_FIX_BLEND[reference][regime])
    if not applied:
        assert row["fcsm_collateral_rw"] > row["pre_fcsm_risk_weight"], (
            f"{reference}: the collateral does not outweigh the obligor - nothing to decline"
        )
    assert row["risk_weight"] == pytest.approx(expected_rw, abs=1e-9)
    assert row["rwa_final"] == pytest.approx(_DRAWN * expected_rw, abs=1e-3)
    assert row["fcsm_substitution_applied"] is applied


# =============================================================================
# Reporting: col 0070 reports only the substitution that was applied
# =============================================================================


@pytest.mark.parametrize("regime", _REGIMES)
def test_c07_col_0070_reports_only_applied_simple_method_collateral(regime: str) -> None:
    """The total sheet's col 0070 is the collateral of the APPLIED legs alone.

    A declined leg has no "substitution effect on the exposure" (the block
    heading) and is not "identified as collateralised under article 222(3)"
    (OF 07.00 col 0070), so it reports nothing — exactly as a declined
    guarantee reports nothing in cols 0050 / 0060.

    Arrange: the four-loan book.
    Act:     generate C 07.00 / OF 07.00.
    Assert:  |col 0070| on the total sheet = 300,000 (L_CORP_CSH) plus, under
             CRR only, L_CORP_EQ's 400,000 applied at equality. Before the fix
             it was 2,200,000 in both regimes.
    """
    # Arrange
    applied_collateral = 300_000.0 + (400_000.0 if regime == "crr" else 0.0)

    # Act
    _results, sheets = _run(regime)

    # Assert
    col_0070 = _cell(sheets["total"], "0010", "0070")
    assert col_0070 is not None, f"{regime}: total-sheet col 0070 is not reported"
    assert abs(col_0070) == pytest.approx(applied_collateral, abs=0.005)
