"""
Integration test: legacy-ledger coverage names the Basel 3.1 OF 07.00 rows no mapping can key.

Pipeline position:
    PipelineOrchestrator (b31/rich, b31/equity-transitional) -> COREPGenerator (OF 07.00)
        -> analysis.legacy_ledger.ledger_coverage(...).unavailable_rows

Key responsibilities tested:
- Basel 3.1 OF 07.00 places legs on three sealed carriers that NO legacy
  mapping can supply — ``recon_registry`` has no component or carrier for any of
  them, which is asserted here rather than assumed:
  ``reporting_class_pre_default`` (memorandum rows 0300 / 0320 on the class
  sheet before default, ``corep/c07_sheet_scope.py``), the ``sa_loan_split_*``
  carriers (a loan-split exposure in two parts, ``kernel/rw_parts.py``) and
  ``risk_weight_pre_equity_transitional`` (transitional equity on its Article
  133 row, ``corep/c07_rw_bands.py``).
- So a projected ledger, which lacks all three, reports different rows from
  ours for the same book. Every OF 07.00 cell that dropping them moves must
  sit on a row ``LedgerCoverage.unavailable_rows`` names (or in a column
  ``unavailable_refs`` names) — the same property
  ``tests/unit/analysis/test_legacy_ledger.py::
  test_dropping_any_mapping_changes_no_cell_coverage_does_not_name`` holds for
  the mappable carriers. Before this, the corporate sheet's row 0320 lost
  1,000,000 and real-estate rows 0180 / 0220 collapsed into 0280 on ``b31/rich``
  with coverage naming none of them (adversarial finding O-06 knock-on).
- CRR is untouched: none of the three is read there, so none of the rows is
  named.

References:
- PS1/26 Annex II, OF 07.00 rows 0140-0280 (p.94-96), memorandum rows 0300 /
  0320 (para 54, p.97)
- docs/plans/return-reconciliation.md, Phase 2 (the legacy ledger projection)
"""

from __future__ import annotations

from datetime import date
from functools import cache
from typing import TYPE_CHECKING

import polars as pl
import pytest

from rwa_calc.analysis.legacy_ledger import MULTI_TARGET_COMPONENTS, ledger_coverage
from rwa_calc.analysis.recon_registry import LEDGER_CARRIERS, RECONCILABLE_COMPONENTS
from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.contracts.edges import (
    AGGREGATOR_EXIT_EDGE,
    LOAN_SPLIT_CARRIERS,
    REPORTING_CLASS_PRE_DEFAULT_COL,
)
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator
from tests.fixtures.reporting_equity_transitional_portfolio import (
    build_reporting_equity_transitional_bundle,
)
from tests.fixtures.reporting_portfolio import build_reporting_bundle

if TYPE_CHECKING:
    from collections.abc import Callable

    from rwa_calc.contracts.bundles import RawDataBundle

FRAMEWORK = "BASEL_3_1"
TEMPLATE = "c07_00"

#: The sealed carriers Basel 3.1 OF 07.00 places legs on and no mapping targets.
UNMAPPABLE_PLACEMENT_CARRIERS: tuple[str, ...] = (
    REPORTING_CLASS_PRE_DEFAULT_COL,
    *LOAN_SPLIT_CARRIERS,
    "risk_weight_pre_equity_transitional",
)

_REPORTING_DATE = date(2027, 6, 1)

#: The registered Basel 3.1 books holding live legs on the three carriers, under
#: their own gate configs (``test_supervisory_validations.py::RUNS``): ``rich``
#: holds a defaulted corporate leg and a loan-split mortgage, and
#: ``equity-transitional`` the class (p) equity of a standardised firm.
_PORTFOLIOS: dict[str, tuple[Callable[[], RawDataBundle], Callable[[], CalculationConfig]]] = {
    "rich": (
        build_reporting_bundle,
        lambda: CalculationConfig.basel_3_1(
            reporting_date=_REPORTING_DATE,
            permission_mode=PermissionMode.IRB,
            enforce_retail_granularity=False,
        ),
    ),
    "equity-transitional": (
        build_reporting_equity_transitional_bundle,
        lambda: CalculationConfig.basel_3_1(
            reporting_date=_REPORTING_DATE, permission_mode=PermissionMode.STANDARDISED
        ),
    ),
}


@cache
def _results(portfolio: str) -> pl.DataFrame:
    build_bundle, build_config = _PORTFOLIOS[portfolio]
    return PipelineOrchestrator().run_with_data(build_bundle(), build_config()).results.collect()


def _cells(frame: pl.DataFrame) -> dict[tuple[str, str, str], float | None]:
    """Every (sheet, row, col) -> value of OF 07.00 generated from ``frame``."""
    bundle = COREPGenerator().generate_from_lazyframe(frame.lazy(), framework=FRAMEWORK)
    out: dict[tuple[str, str, str], float | None] = {}
    for sheet_key, sheet in bundle.c07_00.items():
        value_cols = [c for c in sheet.columns if c not in {"row_ref", "row_name"}]
        for row in sheet.iter_rows(named=True):
            for col in value_cols:
                out[(sheet_key, row["row_ref"], col)] = row[col]
    return out


def test_no_mapping_can_supply_the_placement_carriers() -> None:
    """The premise: a projection CANNOT carry these columns, whatever is mapped."""
    # Arrange
    targets: set[str] = set()
    for spec in RECONCILABLE_COMPONENTS:
        targets |= set(MULTI_TARGET_COMPONENTS.get(spec.name, (spec.our_columns[0],)))
    targets |= {carrier.ledger_column for carrier in LEDGER_CARRIERS}

    # Act
    targetable = sorted(set(UNMAPPABLE_PLACEMENT_CARRIERS) & targets)

    # Assert
    assert targetable == [], f"a mapping can now supply {targetable}: revisit this coverage rule"


@pytest.mark.parametrize("portfolio", sorted(_PORTFOLIOS))
def test_dropping_the_placement_carriers_moves_no_cell_coverage_does_not_name(
    portfolio: str,
) -> None:
    """Every cell a projection's missing carriers move is named by coverage."""
    # Arrange
    sealed = _results(portfolio)
    projected = sealed.drop(UNMAPPABLE_PLACEMENT_CARRIERS, strict=False)
    coverage = ledger_coverage(set(projected.columns), framework=FRAMEWORK)

    # Act
    baseline, variant = _cells(sealed), _cells(projected)
    moved = {key for key in baseline | variant if baseline.get(key) != variant.get(key)}

    # Assert
    assert moved, f"b31/{portfolio} holds no leg on the carriers - this test proves nothing"
    named_rows = set(coverage.unavailable_rows(TEMPLATE, FRAMEWORK))
    named_cols = set(coverage.unavailable_refs(TEMPLATE))
    silent = sorted(
        f"{sheet}/{row}/{col}"
        for sheet, row, col in moved
        if row not in named_rows and col not in named_cols
    )
    assert silent == [], (
        f"b31/{portfolio}: a projection moves {len(silent)} OF 07.00 cell(s) on rows coverage "
        f"does not name: {silent[:12]}"
    )


@pytest.mark.parametrize(
    ("framework", "named"), [("CRR", False), ("BASEL_3_1", True)], ids=["crr", "b31"]
)
def test_only_basel_3_1_names_rows_for_the_placement_carriers(framework: str, named: bool) -> None:
    """Withholding the three carriers from a full ledger costs Basel 3.1 rows, CRR none.

    Measured against EVERY other sealed column supplied, so no other unmet
    requirement can name the same rows and hide the difference.
    """
    # Arrange
    sealed = set(AGGREGATOR_EXIT_EDGE.columns)
    full = ledger_coverage(sealed, framework=framework)
    projected = ledger_coverage(sealed - set(UNMAPPABLE_PLACEMENT_CARRIERS), framework=framework)

    # Act
    lost = set(projected.unavailable_rows(TEMPLATE, framework)) - set(
        full.unavailable_rows(TEMPLATE, framework)
    )

    # Assert
    if not named:
        assert lost == set()
        return
    assert {"0300", "0320", "0180", "0201", "0250", "0261", "0280"} <= lost
