"""
Run the real pipeline on a tiny in-memory bundle, for CRM end-to-end tests.

Pipeline position:
    RawDataBundle (``make_raw_bundle``, loader-sealed) -> PipelineOrchestrator
    -> results frame + accumulated errors

Key responsibilities:
- One corporate obligor (GB, large, unrated: SA risk weight 100%), one or more
  GBP loans and an optional collateral table, run through
  ``PipelineOrchestrator.run_with_data`` under either regime.
- The F-IRB variant adds an internal rating (PD 1%) and a model permission, so
  the same loan routes to the Foundation approach and its collateral reaches
  the LGD* formula.

The collateral review tests (CL-01 / CL-02 / CL-09 / CL-11 / CL-14 / NT-03) use
it so each asserts a hand-calculated number on the production path rather than
on a transform called in isolation (LESSONS C9: reproduce the input shape).
"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl
from tests.fixtures.raw_bundle import make_raw_bundle

from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.contracts.errors import CalculationError
from rwa_calc.domain.enums import CRMCollateralMethod
from rwa_calc.engine.pipeline import PipelineOrchestrator

#: One reporting date per regime, each before the other's effective boundary.
REPORTING_DATES: dict[str, date] = {"crr": date(2026, 6, 30), "b31": date(2027, 6, 30)}


def counterparties(*refs: str) -> pl.DataFrame:
    """Large unrated GB corporates (SA RW 100% in both regimes)."""
    base = {
        "country_of_incorporation": "GB",
        "sector": "CORPORATE",
        "entity_type": "corporate",
        "is_sme": False,
        "apply_fi_scalar": False,
        "is_pse": False,
        "turnover_eur": 500_000_000.0,
    }
    return pl.DataFrame(
        [{**base, "counterparty_reference": r, "counterparty_name": r} for r in refs]
    )


def loans(rows: list[dict[str, Any]]) -> pl.DataFrame:
    """Senior GBP term loans; each row overrides the defaults it names."""
    base = {
        "product_type": "TERM_LOAN",
        "book_code": "BANK",
        "value_date": date(2025, 1, 1),
        "maturity_date": date(2030, 1, 1),
        "currency": "GBP",
        "seniority": "senior",
        "risk_type": "FR",
        "interest": 0.0,
    }
    return pl.DataFrame([{**base, **r} for r in rows])


def collateral(rows: list[dict[str, Any]]) -> pl.DataFrame:
    """GBP collateral at a 10-day liquidation period; rows override the defaults."""
    base = {"currency": "GBP", "maturity_date": date(2035, 1, 1), "liquidation_period_days": 10}
    return pl.DataFrame([{**base, **r} for r in rows])


def run(
    regime: str,
    *,
    firb: bool = False,
    counterparty_refs: tuple[str, ...] = ("CP1",),
    collateral_method: CRMCollateralMethod = CRMCollateralMethod.COMPREHENSIVE,
    **frames: Any,
) -> tuple[pl.DataFrame, list[CalculationError]]:
    """Run the full pipeline; return the collected results and the error list.

    ``firb=True`` attaches a 1% internal PD and a Foundation IRB permission for
    the corporate class, so the loans take the F-IRB LGD* path.
    ``collateral_method`` elects the Art. 222 Simple Method when ``SIMPLE``.
    """
    frames.setdefault("counterparties", counterparties(*counterparty_refs))
    if firb:
        frames["ratings"] = pl.DataFrame(
            [
                {
                    "rating_reference": f"R_{ref}",
                    "counterparty_reference": ref,
                    "pd": 0.01,
                    "rating_type": "internal",
                    "rating_date": date(2025, 12, 31),
                    "model_id": "M1",
                }
                for ref in counterparty_refs
            ]
        )
        frames["model_permissions"] = pl.DataFrame(
            [{"model_id": "M1", "exposure_class": "corporate", "approach": "foundation_irb"}]
        )
    mode = PermissionMode.IRB if firb else PermissionMode.STANDARDISED
    reporting_date = REPORTING_DATES[regime]
    config = (
        CalculationConfig.crr(
            reporting_date=reporting_date,
            permission_mode=mode,
            crm_collateral_method=collateral_method,
        )
        if regime == "crr"
        else CalculationConfig.basel_3_1(
            reporting_date=reporting_date,
            permission_mode=mode,
            crm_collateral_method=collateral_method,
        )
    )
    result = PipelineOrchestrator().run_with_data(make_raw_bundle(**frames), config)
    return result.results.collect(), list(result.errors)


def row(results: pl.DataFrame, reference: str) -> dict[str, Any]:
    """The one result row for ``reference``."""
    picked = results.filter(pl.col("exposure_reference") == reference)
    assert picked.height == 1, f"expected one row for {reference}, got {picked.height}"
    return picked.row(0, named=True)


def codes(errors: list[CalculationError]) -> set[str]:
    """The distinct error codes a run raised."""
    return {e.code for e in errors}
