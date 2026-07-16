"""
Unit tests for the portfolio-level A-IRB retail-RE LGD-floor backstop
(CRR Art. 164(4)/(5), IRB007) — ``check_retail_re_portfolio_lgd_floors``.

The P1.183 acceptance fixtures (tests/fixtures/p1_183/) are all residential,
so the commercial (15%) branch has no full-pipeline coverage. These tests
call the helper directly with small inline DataFrames to cover:
- the commercial bucket alone (residential-only fixtures never exercise it),
- both buckets breaching/compliant in the same call (bucket independence —
  one warning, not a combined/duplicated one),
- a null-LGD row's documented dilution behaviour (reviewer-adjudicated
  acceptable — conservative over-flagging, not a bug).

References:
- CRR Art. 164(4): residential 10% / commercial 15% portfolio EW-avg LGD floor.
- src/rwa_calc/engine/aggregator/_lgd_floor_check.py: helper under test.
"""

from __future__ import annotations

from datetime import date

import polars as pl

from rwa_calc.contracts.errors import ERROR_RETAIL_RE_PORTFOLIO_LGD_FLOOR
from rwa_calc.domain.enums import ErrorSeverity
from rwa_calc.engine.aggregator._lgd_floor_check import check_retail_re_portfolio_lgd_floors
from rwa_calc.rulebook.resolve import resolve

_CRR_PACK = resolve("crr", date(2026, 1, 1))

# Columns required by the helper (see module docstring "required_columns").
_BASE_COLS = {
    "is_airb": True,
    "exposure_class": "retail_mortgage",
    "is_guaranteed": False,
    "guarantor_exposure_class": None,
}


def _frame(rows: list[dict]) -> pl.DataFrame:
    """Build a minimal ``combined``-shaped DataFrame from partial row dicts.

    Each row dict supplies ``property_type``, ``lgd``, ``ead_final`` and may
    override any ``_BASE_COLS`` default (e.g. to build a non-population row).
    """
    full_rows = [{**_BASE_COLS, **row} for row in rows]
    return pl.DataFrame(
        full_rows,
        schema={
            "is_airb": pl.Boolean,
            "exposure_class": pl.String,
            "property_type": pl.String,
            "lgd": pl.Float64,
            "ead_final": pl.Float64,
            "is_guaranteed": pl.Boolean,
            "guarantor_exposure_class": pl.String,
        },
    )


class TestCommercialBucketLGDFloor:
    """Commercial (15%) branch — untested by the residential-only P1.183 fixtures."""

    def test_commercial_breach_raises_one_irb007(self) -> None:
        """
        Two commercial A-IRB retail-mortgage rows: EW-avg LGD 13.00% < 15% floor.

        1M @ lgd=0.10, 1M @ lgd=0.16 -> (100,000+160,000)/2,000,000 = 0.13 = 13.00%.
        """
        combined = _frame(
            [
                {"property_type": "commercial", "lgd": 0.10, "ead_final": 1_000_000.0},
                {"property_type": "commercial", "lgd": 0.16, "ead_final": 1_000_000.0},
            ]
        )

        warnings = check_retail_re_portfolio_lgd_floors(combined, _CRR_PACK)

        assert len(warnings) == 1, (
            f"expected exactly 1 IRB007 warning (commercial EW-avg LGD 13.00% "
            f"< 15% floor), got {len(warnings)}: {[w.message for w in warnings]}"
        )
        warning = warnings[0]
        assert warning.code == ERROR_RETAIL_RE_PORTFOLIO_LGD_FLOOR
        assert warning.severity == ErrorSeverity.WARNING
        assert "commercial" in warning.message
        assert "13.00%" in warning.message
        assert "15%" in warning.message


class TestMixedBucketIndependence:
    """Residential and commercial buckets are evaluated independently."""

    def test_residential_breach_with_commercial_compliant_raises_only_residential_warning(
        self,
    ) -> None:
        """
        Residential rows breach (EW-avg 4.00% < 10%); commercial rows comply
        (EW-avg 20.00% >= 15%) -> exactly ONE warning, and it names the
        residential bucket, not the commercial one.

        Residential: 1M @ lgd=0.05, 1M @ lgd=0.03 -> 80,000/2,000,000 = 0.04 = 4.00%.
        Commercial:  1M @ lgd=0.20 -> 200,000/1,000,000 = 0.20 = 20.00% (compliant).
        """
        combined = _frame(
            [
                {"property_type": "residential", "lgd": 0.05, "ead_final": 1_000_000.0},
                {"property_type": "residential", "lgd": 0.03, "ead_final": 1_000_000.0},
                {"property_type": "commercial", "lgd": 0.20, "ead_final": 1_000_000.0},
            ]
        )

        warnings = check_retail_re_portfolio_lgd_floors(combined, _CRR_PACK)

        assert len(warnings) == 1, (
            f"expected exactly 1 IRB007 warning (residential breaches, "
            f"commercial complies), got {len(warnings)}: "
            f"{[w.message for w in warnings]}"
        )
        warning = warnings[0]
        assert "residential" in warning.message
        assert "10%" in warning.message
        assert "commercial" not in warning.message


class TestNullLGDDilution:
    """Null-LGD rows dilute the EW-avg downward — conservative over-flagging."""

    def test_null_lgd_row_dilutes_average_and_can_trigger_a_warning(self) -> None:
        """
        Documented behaviour (reviewer-adjudicated acceptable): a null-LGD
        row's ``lgd x ead_final`` product is skipped by Polars' null-skipping
        ``.sum()`` (drops from the numerator), but its ``ead_final`` still
        contributes to the denominator sum. This dilutes the EW-avg
        downward relative to excluding the row entirely — conservative
        over-flagging, not under-flagging, so it is accepted as-is rather
        than treated as a bug to fix.

        Row 1: lgd=0.12, ead=1,000,000 (12% — compliant on its own, > 10% floor).
        Row 2: lgd=None, ead=1,000,000 (contributes 0 to the numerator, but
               its EAD still counts in the denominator).
        EW-avg = (0.12*1,000,000 + 0) / (1,000,000+1,000,000)
               = 120,000 / 2,000,000 = 0.06 = 6.00% < 10% -> WARNING fires,
        even though the only priced exposure (row 1) is individually compliant.
        """
        combined = _frame(
            [
                {"property_type": "residential", "lgd": 0.12, "ead_final": 1_000_000.0},
                {"property_type": "residential", "lgd": None, "ead_final": 1_000_000.0},
            ]
        )

        warnings = check_retail_re_portfolio_lgd_floors(combined, _CRR_PACK)

        assert len(warnings) == 1, (
            f"expected exactly 1 IRB007 warning (null-LGD row dilutes the "
            f"EW-avg from 12.00% to 6.00%, below the 10% floor), "
            f"got {len(warnings)}: {[w.message for w in warnings]}"
        )
        assert "6.00%" in warnings[0].message
