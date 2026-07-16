"""
P1.183: PS1/26 Art. 164(4)/(5) portfolio-level A-IRB retail-RE LGD floor —
Basel 3.1 regime-inertness control.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> IRBCalculator
        -> Aggregator (new portfolio-level LGD-floor helper) -> AggregatedResultBundle

Key responsibilities:
- Confirm the CRR-only portfolio-level Art. 164(4) check does NOT fire under
  Basel 3.1 — the pack Feature ``crr_retail_re_portfolio_lgd_floor`` is off
  under B31 (see
  tests/unit/rulebook/test_retail_re_portfolio_lgd_floor_pack_entries.py),
  because B31's own PER-EXPOSURE ``airb_lgd_floor`` (Art. 164(4)(a), 5% for
  retail residential RE) already achieves the same regulatory outcome at the
  exposure level, making a second portfolio-level check redundant there.

Same breach book as the CRR sibling
(tests/acceptance/crr/test_p1_183_art_164_portfolio_lgd_floor.py) — the SAME
exposures that raise IRB007 under CRR must raise NOTHING under B31.

Defect under test (pre-fix):
    No portfolio-level LGD-floor check exists at all yet under either
    regime, so this file's assertion (zero IRB007) trivially passes today
    for the wrong reason (nothing exists) — it must keep passing once the
    engine-implementer adds the CRR-only check, for the RIGHT reason (the
    B31 pack Feature is off).

NOTE: under B31 the per-exposure ``airb_lgd_floor`` Feature WILL clip input
LGDs that fall below the 5% retail-mortgage floor before they ever reach the
aggregator. That's expected and irrelevant here — the sole assertion in this
file is "no IRB007", not any LGD or RWA value (the CRR sibling covers those).

References:
    - PRA PS1/26 Art. 164(4)(a): 5% PER-EXPOSURE A-IRB LGD floor for retail
      residential RE (engine/irb/formulas.py::_lgd_floor_expression, gated
      by the pre-existing ``airb_lgd_floor`` Feature).
    - CRR Art. 164(4)/(5): the CRR-only PORTFOLIO-level check this file
      proves does not leak into B31 (see the CRR sibling for the full
      hand-calc this fixture is shared with).
    - tests/fixtures/p1_183/p1_183.py: fixture builder and scenario
      constants (shared with the CRR sibling).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.contracts.bundles import AggregatedResultBundle, RawDataBundle
from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.p1_183.p1_183 import LOAN_E1_REF, LOAN_E2_REF
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_183"

# B31-effective reporting date — same convention as other B31 acceptance
# tests. The fixture's flag semantics don't depend on regime-effective-date
# arithmetic, only which pack Feature is switched on
# (crr_retail_re_portfolio_lgd_floor: CRR on / B31 off).
_REPORTING_DATE = date(2027, 1, 1)

# IRB007 does not exist as a named constant yet — see the CRR sibling for
# the same reasoning (string literal, not an import).
_IRB007 = "IRB007"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_breach_bundle() -> RawDataBundle:
    """
    Build a RawDataBundle carrying only the breach book (LN_E1_P183 +
    LN_E2_P183) — the same two loans that raise IRB007 under CRR (EW-avg
    LGD 7.25% < 10%). No guarantee row is needed (E5, the only guaranteed
    loan, is not in this book).
    """
    loan_refs = (LOAN_E1_REF, LOAN_E2_REF)
    loans = pl.scan_parquet(_FIXTURES_DIR / "loan.parquet").filter(
        pl.col("loan_reference").is_in(list(loan_refs))
    )

    return make_raw_bundle(
        facilities=pl.LazyFrame(
            schema={"facility_reference": pl.String, "counterparty_reference": pl.String}
        ),
        loans=loans,
        counterparties=pl.scan_parquet(_FIXTURES_DIR / "counterparty.parquet"),
        facility_mappings=pl.LazyFrame(
            schema={
                "parent_facility_reference": pl.String,
                "child_reference": pl.String,
                "child_type": pl.String,
            }
        ),
        lending_mappings=pl.LazyFrame(
            schema={
                "parent_counterparty_reference": pl.String,
                "child_counterparty_reference": pl.String,
            }
        ),
        ratings=pl.scan_parquet(_FIXTURES_DIR / "rating.parquet"),
        model_permissions=pl.scan_parquet(_FIXTURES_DIR / "model_permission.parquet"),
    )


def _basel_31_config() -> CalculationConfig:
    """Basel 3.1 A-IRB config."""
    return CalculationConfig.basel_3_1(
        reporting_date=_REPORTING_DATE,
        permission_mode=PermissionMode.IRB,
    )


def _irb007_errors(errors: list) -> list:
    """Filter a CalculationError list down to IRB007 (portfolio LGD floor) entries."""
    return [e for e in errors if e.code == _IRB007]


# ---------------------------------------------------------------------------
# P1.183 acceptance tests — Basel 3.1 regime-inertness control
# ---------------------------------------------------------------------------


class TestP1183Art164PortfolioLGDFloorB31:
    """P1.183: the CRR-only portfolio-level Art. 164(4) check is inert under B31."""

    @pytest.fixture(scope="class")
    def breach_book_results_b31(self) -> AggregatedResultBundle:
        """B31 A-IRB pipeline results for the same breach book as the CRR sibling."""
        bundle = _build_breach_bundle()
        results = PipelineOrchestrator().run_with_data(bundle, _basel_31_config())
        assert results.irb_results is not None, (
            "IRB results should not be None — check PermissionMode.IRB config"
        )
        return results

    def test_p1_183_breach_book_raises_zero_irb007_under_b31(
        self, breach_book_results_b31: AggregatedResultBundle
    ) -> None:
        """
        P1.183 regime-inertness control: the CRR breach book raises NO
        IRB007 under Basel 3.1.

        Arrange: LN_E1_P183 + LN_E2_P183 — under CRR this book's EW-avg LGD
                 is 7.25% (< 10% floor) and raises exactly one IRB007 (see
                 tests/acceptance/crr/test_p1_183_art_164_portfolio_lgd_floor.py).
        Act:     Basel 3.1 A-IRB pipeline over the SAME two loans.
        Assert:  zero IRB007 (the ``crr_retail_re_portfolio_lgd_floor``
                 pack Feature is off under B31 — B31's own per-exposure 5%
                 floor already covers this ground per-exposure).

        PASSES today (nothing implemented yet) and MUST still pass after —
        this is the negative control proving the CRR-only scoping, not a
        discriminating test on its own.
        """
        irb007 = _irb007_errors(breach_book_results_b31.errors)

        assert len(irb007) == 0, (
            f"P1.183 (B31): the breach book (CRR EW-avg LGD 7.25%) must "
            f"raise zero IRB007 under Basel 3.1 — the portfolio-level check "
            f"is CRR-only (crr_retail_re_portfolio_lgd_floor Feature off "
            f"for B31). Got {len(irb007)}. "
            f"All errors: {[(e.code, e.message) for e in breach_book_results_b31.errors]}"
        )
