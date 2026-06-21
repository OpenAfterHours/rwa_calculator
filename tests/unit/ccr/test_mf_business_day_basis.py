"""
Unit tests locking the unmargined maturity-factor business-day basis (Art. 279c(1)).

Pipeline position:
    pipeline_adapter (business_days_to_maturity via pl.business_day_count)
    -> compute_maturity_factor_unmargined  (← this stage)

Methodology under test: the unmargined maturity factor is measured on the
250-business-day-year basis, the same "1 year" the margined branch divides MPOR
by (CRR Art. 279c shares the denominator across both branches):

    MF = sqrt(min(BD, 250) / 250)

where BD = business_day_count(reporting_date, maturity_date) (Mon-Fri, no
holiday calendar). A trade with ≥ 250 business days to maturity collapses to
MF = 1.0; the calendar-day / 365.25 basis is NOT used here.

NOTE: FRESH figures — a 2025-06-30 reporting date and maturities unrelated to any
earlier worked example — so the methodology is pinned independently.

References:
- CRR Art. 279c(1): unmargined maturity factor.
- BCBS CRE52.50-52.
"""

from __future__ import annotations

import math
from datetime import date

import polars as pl
import pytest

from rwa_calc.engine.ccr.maturity_factor import compute_maturity_factor_unmargined

_REPORTING = date(2025, 6, 30)


@pytest.mark.parametrize(
    ("business_days", "expected_mf"),
    [
        (300, 1.0),  # ≥ 250 BD → capped at 1.0
        (250, 1.0),  # exactly one BD-year → 1.0
        (200, math.sqrt(200 / 250)),  # 0.8944271909999159
        (125, math.sqrt(0.5)),  # 0.7071067811865476
        (40, math.sqrt(40 / 250)),  # 0.4
    ],
)
def test_mf_business_day_formula(business_days: int, expected_mf: float) -> None:
    """MF = sqrt(min(BD, 250) / 250) for a range of business-day residual maturities."""
    lf = pl.LazyFrame({"business_days_to_maturity": [business_days]})

    result = compute_maturity_factor_unmargined(lf).collect()

    assert result["maturity_factor"][0] == pytest.approx(expected_mf, rel=1e-12), (
        f"BD={business_days}: expected MF={expected_mf}, got {result['maturity_factor'][0]!r}. "
        "CRR Art. 279c(1) on the 250-business-day basis."
    )


def test_mf_reads_business_days_built_from_dates() -> None:
    """End-to-end: business_days_to_maturity from real dates drives the MF.

    Fresh dates: reporting 2025-06-30, maturity 2025-12-30 (a sub-year tenor).
    The MF must reflect the BUSINESS-DAY count (via pl.business_day_count), not
    the calendar-day / 365.25 measure — proving the two bases diverge for sub-1y
    trades and the engine uses the business-day one.
    """
    maturity = date(2025, 12, 30)
    lf = pl.LazyFrame({"maturity_date": [maturity]}).with_columns(
        pl.business_day_count(pl.lit(_REPORTING), pl.col("maturity_date")).alias(
            "business_days_to_maturity"
        )
    )

    bd = lf.collect()["business_days_to_maturity"][0]
    result = compute_maturity_factor_unmargined(lf).collect()

    expected_bd_mf = math.sqrt(min(max(bd, 10), 250) / 250)
    calendar_days = (maturity - _REPORTING).days
    calendar_mf = math.sqrt(min(calendar_days / 365.25, 1.0))

    assert result["maturity_factor"][0] == pytest.approx(expected_bd_mf, rel=1e-12), (
        f"Engine MF must use the business-day count (BD={bd} → {expected_bd_mf:.6f}), "
        f"got {result['maturity_factor'][0]!r}."
    )
    assert expected_bd_mf != pytest.approx(calendar_mf, rel=1e-4), (
        "Sanity: for this sub-1y tenor the business-day MF must differ from the "
        f"calendar/365.25 MF ({calendar_mf:.6f}) — confirming the basis switch bites."
    )


@pytest.mark.parametrize(
    ("business_days", "expected_mf"),
    [
        (0, 0.2),  # matured / 0 BD → floored to 10 BD
        (5, 0.2),  # below the floor
        (9, 0.2),  # just below the floor
        (10, 0.2),  # at the floor: sqrt(10/250) = 0.2
        (11, math.sqrt(11 / 250)),  # 0.20976... just above the floor
    ],
)
def test_mf_floors_residual_maturity_at_10_business_days(
    business_days: int, expected_mf: float
) -> None:
    """M is floored at 10 BD, so MF never drops below sqrt(10/250) = 0.20.

    CRR Art. 279c(1) / BCBS CRE52.47-52.48 (footnote 13). Distinct from the
    Art. 279b start-date floor and the Art. 285 margined MPOR floors.
    """
    lf = pl.LazyFrame({"business_days_to_maturity": [business_days]})

    result = compute_maturity_factor_unmargined(lf).collect()

    assert result["maturity_factor"][0] == pytest.approx(expected_mf, rel=1e-12), (
        f"BD={business_days}: expected MF={expected_mf} (10-BD floor on M), "
        f"got {result['maturity_factor'][0]!r}. CRR Art. 279c(1) / BCBS CRE52.47-52.48 fn.13."
    )


def test_mf_floor_end_to_end_from_dates_below_10bd() -> None:
    """A sub-10-BD trade routed via pl.business_day_count clamps to MF = 0.20 end-to-end.

    Fresh dates: reporting 2026-01-15 (Thu), maturity 2026-01-22 (Thu) → 5 business
    days. Without the floor MF would be sqrt(5/250) = 0.1414 (anti-conservative); the
    Art. 279c(1) floor lifts it to sqrt(10/250) = 0.20.
    """
    reporting = date(2026, 1, 15)
    lf = pl.LazyFrame({"maturity_date": [date(2026, 1, 22)]}).with_columns(
        pl.business_day_count(pl.lit(reporting), pl.col("maturity_date")).alias(
            "business_days_to_maturity"
        )
    )

    bd = lf.collect()["business_days_to_maturity"][0]
    assert bd == 5, f"expected 5 business days for the fixture dates, got {bd}"

    result = compute_maturity_factor_unmargined(lf).collect()

    assert result["maturity_factor"][0] == pytest.approx(0.2, rel=1e-12), (
        f"A 5-BD trade must clamp to the 10-BD floor (MF = 0.20), "
        f"got {result['maturity_factor'][0]!r}."
    )
