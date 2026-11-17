"""
Integration test: the return reconciliation over a loan-split real-estate leg (``b31/rich``).

Pipeline position:
    PipelineOrchestrator (b31/rich) -> reporting.membership.cell_membership
        -> analysis.return_recon.row_migration

Key responsibilities tested:
- Basel 3.1 OF 07.00 reports an Art. 124F / 124H loan-split exposure in its two
  parts (PS1/26 Annex II p.94; ``reporting/kernel/rw_parts.py``), so the plan
  frame membership reads holds the leg twice under one ``exposure_reference``.
  Each part must carry ITS OWN share of every money column membership publishes
  (``ead_final`` and ``rwa_final``): the two parts on one row add back to the
  leg, and never carry the whole leg's figure each.
- The migration matrix's money equals the group's DISTINCT-LEG total
  (``analysis/return_recon.py::row_migration``'s stated invariant), for both
  money columns, against a figure derived from the sealed results frame and not
  from membership — the residual part was dropped by ``.first()`` pricing once
  the parts existed (adversarial finding O-06 knock-on; escape log 2026-11-16).

The portfolio is the registered ``b31/rich`` book under its own gate config
(``tests/acceptance/reporting/test_supervisory_validations.py::_b31_config``),
run once per module: its ``RP-LN-RRE`` mortgage is the loan-split leg, and the
adequacy assertions below say so rather than trusting that name.

References:
- PS1/26 Annex II, OF 07.00 rows 0140-0280 (p.94): loan-split exposures
  "shall be reported in two parts"
- docs/plans/return-reconciliation.md (the migration matrix)
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.analysis.return_recon import (
    MIGRATION_MONEY_COLUMNS,
    ReturnRecon,
    build_recon,
    row_migration,
)
from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator
from rwa_calc.reporting.membership import CellMembership, cell_membership
from tests.fixtures.reporting_portfolio import build_reporting_bundle

FRAMEWORK = "BASEL_3_1"
TEMPLATE = "c07_00"
SHEET = "real_estate"
#: The total row of the real-estate sheet and the exposure-value / RWEA columns.
TOTAL_ROW = "0010"
EXPOSURE_VALUE_COL = "0200"
RWEA_COL = "0220"


class _FrameSource:
    """A ``ResultsSource`` over one sealed results frame."""

    def __init__(self, frame: pl.LazyFrame) -> None:
        self._frame = frame
        self.framework = FRAMEWORK

    def scan_results(self) -> pl.LazyFrame:
        return self._frame


@pytest.fixture(scope="module")
def results() -> pl.DataFrame:
    """The sealed ``b31/rich`` results, under the gate's own Basel 3.1 IRB config."""
    config = CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 1),
        permission_mode=PermissionMode.IRB,
        enforce_retail_granularity=False,
    )
    bundle = PipelineOrchestrator().run_with_data(build_reporting_bundle(), config)
    return bundle.results.collect()


@pytest.fixture(scope="module")
def membership(results: pl.DataFrame) -> CellMembership:
    return cell_membership(_FrameSource(results.lazy()), [TEMPLATE])


@pytest.fixture(scope="module")
def recon(results: pl.DataFrame) -> ReturnRecon:
    source = _FrameSource(results.lazy())
    return build_recon(source, source, [TEMPLATE])


@pytest.fixture(scope="module")
def sheet(results: pl.DataFrame) -> pl.DataFrame:
    corep = COREPGenerator().generate_from_lazyframe(results.lazy(), framework=FRAMEWORK)
    return corep.c07_00[SHEET]


def _group_key(membership: CellMembership) -> str:
    """The predicate group serving the total row's exposure-value cell."""
    served = membership.columns.filter(
        (pl.col("template_id") == TEMPLATE)
        & (pl.col("sheet") == SHEET)
        & (pl.col("row_ref") == TOTAL_ROW)
        & (pl.col("col_ref") == EXPOSURE_VALUE_COL)
    )
    assert served.height == 1, "the total row's exposure value is served by no single group"
    return str(served["predicate_key"][0])


def _group_legs(membership: CellMembership, predicate_key: str) -> pl.DataFrame:
    return membership.legs.filter(
        (pl.col("template_id") == TEMPLATE)
        & (pl.col("sheet") == SHEET)
        & (pl.col("predicate_key") == predicate_key)
    )


def _split_references(legs: pl.DataFrame) -> list[str]:
    """Legs listed more than once on one row of the group: the two-part legs."""
    doubled = legs.group_by("row_ref", "exposure_reference").len().filter(pl.col("len") > 1)
    return sorted(set(doubled["exposure_reference"].to_list()))


def _cell(sheet: pl.DataFrame, row_ref: str, col_ref: str) -> float:
    return float(sheet.filter(pl.col("row_ref") == row_ref)[col_ref][0])


def test_the_group_holds_a_loan_split_leg_in_two_parts(membership: CellMembership) -> None:
    """Adequacy: without a two-part leg every assertion below is vacuous."""
    # Arrange
    legs = _group_legs(membership, _group_key(membership))

    # Act
    split = _split_references(legs)

    # Assert
    assert split, "the group holds no two-part leg - the loan split never reached OF 07.00"
    on_total = legs.filter(
        (pl.col("row_ref") == TOTAL_ROW) & pl.col("exposure_reference").is_in(split)
    )
    assert on_total["ead_final"].n_unique() > 1, (
        "the two parts carry equal exposure values - .first() pricing would be undetectable"
    )


@pytest.mark.parametrize("money_column", MIGRATION_MONEY_COLUMNS)
def test_each_part_carries_its_own_share_of_the_legs_money(
    membership: CellMembership, results: pl.DataFrame, money_column: str
) -> None:
    """On a row holding both parts, the parts add back to the leg — never twice it."""
    # Arrange
    legs = _group_legs(membership, _group_key(membership))
    split = _split_references(legs)
    sealed = dict(
        results.filter(pl.col("exposure_reference").is_in(split))
        .select("exposure_reference", money_column)
        .iter_rows()
    )

    # Act
    per_row = (
        legs.filter(pl.col("exposure_reference").is_in(split))
        .group_by("row_ref", "exposure_reference")
        .agg(pl.col(money_column).sum(), pl.len().alias("parts"))
        .filter(pl.col("parts") == 2)
    )

    # Assert
    assert per_row.height > 0
    for row in per_row.iter_rows(named=True):
        assert row[money_column] == pytest.approx(sealed[row["exposure_reference"]]), (
            f"row {row['row_ref']}: the parts of {row['exposure_reference']} carry "
            f"{row[money_column]:,.2f} of {money_column} for a leg of "
            f"{sealed[row['exposure_reference']]:,.2f}"
        )


def test_a_parts_own_row_carries_the_rwea_that_row_reports(
    membership: CellMembership, results: pl.DataFrame, sheet: pl.DataFrame
) -> None:
    """A part alone on its risk-weight row carries that row's RWEA, not the whole leg's."""
    # Arrange
    legs = _group_legs(membership, _group_key(membership))
    split = _split_references(legs)
    assert len(split) == 1, f"expected the one loan-split leg of b31/rich, found {split}"
    leg = results.filter(pl.col("exposure_reference") == split[0])
    assert leg["rwa_final"][0] == pytest.approx(leg["rwa_pre_floor"][0]), (
        "the leg's rwa_final differs from the RWEA OF 07.00 reports - this comparison is moot"
    )
    alone = (
        legs.filter(pl.col("exposure_reference") == split[0])
        .group_by("row_ref")
        .agg(pl.col("rwa_final").sum(), pl.len().alias("parts"))
        .filter(pl.col("parts") == 1)
    )

    # Act
    carried = dict(alone.select("row_ref", "rwa_final").iter_rows())

    # Assert
    assert len(carried) == 2, f"expected one row per part, found {sorted(carried)}"
    for row_ref, amount in carried.items():
        assert amount == pytest.approx(_cell(sheet, row_ref, RWEA_COL)), row_ref


@pytest.mark.parametrize("money_column", MIGRATION_MONEY_COLUMNS)
def test_the_migration_matrix_conserves_the_groups_distinct_leg_money(
    recon: ReturnRecon,
    membership: CellMembership,
    results: pl.DataFrame,
    money_column: str,
) -> None:
    """The matrix's money equals the group's distinct-leg total on each side.

    The independent figure is the SEALED leg money of the group's distinct
    references, read off the results frame — not off membership, whose part rows
    are the thing under test.
    """
    # Arrange
    predicate_key = _group_key(membership)
    references = _group_legs(membership, predicate_key)["exposure_reference"].unique()
    expected = float(
        results.filter(pl.col("exposure_reference").is_in(references.implode()))[money_column].sum()
    )
    assert expected > 0.0, "the group holds no money - the conservation check is vacuous"

    # Act
    matrix = row_migration(recon, TEMPLATE, SHEET, predicate_key, money_column=money_column)

    # Assert
    assert matrix["money_ours"].sum() == pytest.approx(expected)
    assert matrix["money_theirs"].sum() == pytest.approx(expected)


def test_the_matrix_exposure_value_is_the_sheets_reported_total(
    recon: ReturnRecon, membership: CellMembership, sheet: pl.DataFrame
) -> None:
    """Second anchor: the group's exposure value is what row 0010 col 0200 reports."""
    # Arrange
    predicate_key = _group_key(membership)

    # Act
    matrix = row_migration(recon, TEMPLATE, SHEET, predicate_key, money_column="ead_final")

    # Assert
    assert matrix["money_ours"].sum() == pytest.approx(_cell(sheet, TOTAL_ROW, EXPOSURE_VALUE_COL))
