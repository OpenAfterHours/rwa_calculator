"""Declarative C 08.03 cell bindings.

Kept separate from the wider C 08 family module so the explicit origin/post-CRM
column matrix remains reviewable without growing that already-large module.
"""

from __future__ import annotations

from collections.abc import Mapping

from rwa_calc.reporting.cellspec import (
    CellSpec,
    Count,
    Formula,
    RowPredicate,
    SafeSum,
    Sum,
    WeightedAvg,
)

_IRB_RETAIL_CLASSES: frozenset[str] = frozenset({"retail_mortgage", "retail_qrre", "retail_other"})


def _null(_cells: Mapping[str, float | None], _prior_available: bool) -> None:
    return None


def build_c08_03_cells(  # noqa: PLR0913 - the complete C 08.03 column surface
    band_rows: list[tuple[str, str, str]],
    cols: set[str],
    ead_col: str,
    rwa_col: str,
    pd_report_col: str,
    lgd_col: str | None,
    exposure_class: str,
    basis_origin: str,
    basis_post: str,
) -> dict[tuple[str, str], CellSpec]:
    """Build every C 08.03 cell on its prescribed origin or post-CRM basis."""
    cells: dict[tuple[str, str], CellSpec] = {}
    for ref, label, term_col in band_rows:
        terms = ((term_col, label),)
        origin_member = RowPredicate(equals=((basis_origin, True), *terms))
        post_member = RowPredicate(equals=((basis_post, True), *terms))
        cells[(ref, "0010")] = CellSpec(Sum("reporting_gross_on_bs"), predicate=origin_member)
        cells[(ref, "0020")] = CellSpec(Sum("reporting_gross_off_bs"), predicate=origin_member)
        cells[(ref, "0030")] = CellSpec(
            WeightedAvg("ccf", weight="reporting_gross_off_bs"),
            predicate=origin_member,
            empty_cell="null",
        )
        cells[(ref, "0040")] = CellSpec(Sum(ead_col), predicate=post_member)
        cells[(ref, "0050")] = CellSpec(
            WeightedAvg(pd_report_col, weight=ead_col),
            predicate=post_member,
            empty_cell="null",
        )
        cells[(ref, "0060")] = (
            CellSpec(Count("counterparty_reference", distinct=True), predicate=origin_member)
            if "counterparty_reference" in cols
            else CellSpec(Count("exposure_reference"), predicate=origin_member)
        )
        cells[(ref, "0070")] = (
            CellSpec(
                WeightedAvg(lgd_col, weight=ead_col),
                predicate=post_member,
                empty_cell="null",
            )
            if lgd_col is not None
            else CellSpec(Formula(refs=(), fn=_null))
        )
        cells[(ref, "0080")] = (
            CellSpec(Formula(refs=(), fn=_null))
            if exposure_class in _IRB_RETAIL_CLASSES
            else CellSpec(
                WeightedAvg("irb_maturity_m", weight=ead_col),
                predicate=post_member,
                empty_cell="null",
            )
        )
        cells[(ref, "0090")] = CellSpec(Sum(rwa_col), predicate=post_member)
        # Expected loss is calculated after CRM substitution and therefore
        # follows the resultant obligor, alongside EAD and RWEA.  Keeping it on
        # the origin predicate reports the covered leg against the borrower
        # instead of the protection provider (EBA Q&A 2023_6718).
        cells[(ref, "0100")] = CellSpec(Sum("expected_loss"), predicate=post_member)
        cells[(ref, "0110")] = CellSpec(
            SafeSum(("scra_provision_amount", "gcra_provision_amount")),
            predicate=origin_member,
        )
    return cells
