"""
CRR Art. 113(6) core-UK-group 0% RW eligibility computed by the scope resolver.

The resolver sets ``intragroup_zero_rw_eligible`` on facility / loan / contingent
rows when ALL three pinned conditions hold: an individual-basis run, the
reporting entity in the core UK group, and the row's ``intragroup_entity_reference``
naming a core-UK-group entity. Each condition is falsified in isolation here, plus
the pack Feature off-switch. See docs/plans/multi-entity-reporting.md ("Wave 4").

References:
- CRR Art. 113(6): core-UK-group 0% risk weight (individual basis).
- docs/plans/multi-entity-reporting.md: Wave 4 design record.
"""

from __future__ import annotations

from datetime import date

import polars as pl
from tests.fixtures.raw_bundle import make_raw_bundle

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ReportingBasis
from rwa_calc.engine.stages.scope import resolver

_ENTITIES = ("GRP", "BANK_A", "BANK_B")
_PARENTS = (None, "GRP", "GRP")


def _tree(core_uk_group: dict[str, bool] | None = None) -> pl.DataFrame:
    """GRP apex over BANK_A / BANK_B; per-entity ``core_uk_group`` flags."""
    cug = core_uk_group or {}
    return pl.DataFrame(
        {
            "entity_reference": list(_ENTITIES),
            "parent_entity_reference": list(_PARENTS),
            "core_uk_group": [cug.get(e, False) for e in _ENTITIES],
        }
    )


_MAPPING = pl.DataFrame(
    {
        "book_code": ["BOOK_A", "BOOK_B"],
        "reporting_entity_reference": ["BANK_A", "BANK_B"],
    }
)


def _loans(rows: list[tuple[str, str, str, str | None]]) -> pl.DataFrame:
    """rows: (loan_reference, book_code, counterparty_reference, intragroup)."""
    return pl.DataFrame(
        {
            "loan_reference": [r[0] for r in rows],
            "book_code": [r[1] for r in rows],
            "counterparty_reference": [r[2] for r in rows],
            "intragroup_entity_reference": [r[3] for r in rows],
        }
    )


def _loan_with_stray_carrier(ref: str, book: str, cp: str, intragroup: str | None) -> pl.DataFrame:
    """A single loan row shipping a stray ``intragroup_zero_rw_eligible=True`` input."""
    return pl.DataFrame(
        {
            "loan_reference": [ref],
            "book_code": [book],
            "counterparty_reference": [cp],
            "intragroup_entity_reference": [intragroup],
            "intragroup_zero_rw_eligible": [True],
        }
    )


def _bundle(loans: pl.DataFrame, tree: pl.DataFrame):
    return make_raw_bundle(
        loans=loans,
        reporting_entities=tree,
        book_entity_mappings=_MAPPING,
    )


def _carrier(result) -> list[bool | None]:
    return result.loans.collect()["intragroup_zero_rw_eligible"].to_list()


def _resolve(bundle, entity: str, basis: ReportingBasis, *, feature: bool = True):
    config = CalculationConfig.crr(
        reporting_date=date(2026, 1, 1), reporting_entity=entity, reporting_basis=basis
    )
    return resolver.resolve_scope(bundle, config, intragroup_zero_rw=feature)


def _eligible_refs(result) -> set[str]:
    """Loan references the resolver flagged Art. 113(6)-eligible (True)."""
    df = result.loans.collect()
    assert "intragroup_zero_rw_eligible" in df.columns
    return set(df.filter(pl.col("intragroup_zero_rw_eligible"))["loan_reference"].to_list())


# ---------------------------------------------------------------------------
# The positive case: all three conditions hold
# ---------------------------------------------------------------------------


def test_individual_cug_run_marks_intragroup_to_cug_member_eligible():
    """Individual basis + reporting entity CUG + target CUG -> the intragroup row is eligible."""
    bundle = _bundle(
        _loans(
            [
                ("EXT", "BOOK_A", "CP_EXT", None),
                ("IG", "BOOK_A", "BANK_B", "BANK_B"),
            ]
        ),
        _tree({"GRP": True, "BANK_A": True, "BANK_B": True}),
    )

    result = _resolve(bundle, "BANK_A", ReportingBasis.INDIVIDUAL)

    assert _eligible_refs(result) == {"IG"}


def test_external_row_is_never_eligible():
    """An external (null-tag) row stays False even on a fully-eligible CUG run."""
    bundle = _bundle(
        _loans([("EXT", "BOOK_A", "CP_EXT", None)]),
        _tree({"GRP": True, "BANK_A": True, "BANK_B": True}),
    )

    result = _resolve(bundle, "BANK_A", ReportingBasis.INDIVIDUAL)

    assert _eligible_refs(result) == set()


# ---------------------------------------------------------------------------
# Each condition falsified in isolation
# ---------------------------------------------------------------------------


def test_condition_1_non_individual_basis_yields_no_eligibility():
    """Consolidated basis: intragroup rows are eliminated, survivors never eligible."""
    bundle = _bundle(
        _loans(
            [
                ("EXT", "BOOK_A", "CP_EXT", None),
                ("IG", "BOOK_A", "BANK_B", "BANK_B"),
            ]
        ),
        _tree({"GRP": True, "BANK_A": True, "BANK_B": True}),
    )

    result = _resolve(bundle, "GRP", ReportingBasis.CONSOLIDATED)

    # IG eliminated (member), EXT kept but not eligible — no 0% on a consolidated run.
    assert _eligible_refs(result) == set()


def test_condition_2_reporting_entity_not_cug_yields_no_eligibility():
    """Reporting entity outside the core UK group -> no row is eligible."""
    bundle = _bundle(
        _loans([("IG", "BOOK_A", "BANK_B", "BANK_B")]),
        # Target BANK_B is CUG, but the reporting entity BANK_A is NOT.
        _tree({"GRP": True, "BANK_A": False, "BANK_B": True}),
    )

    result = _resolve(bundle, "BANK_A", ReportingBasis.INDIVIDUAL)

    assert _eligible_refs(result) == set()


def test_condition_3_target_entity_not_cug_yields_no_eligibility():
    """Intragroup tag naming a non-CUG entity -> that row is not eligible."""
    bundle = _bundle(
        _loans([("IG", "BOOK_A", "BANK_B", "BANK_B")]),
        # Reporting entity BANK_A is CUG, but the target BANK_B is NOT.
        _tree({"GRP": True, "BANK_A": True, "BANK_B": False}),
    )

    result = _resolve(bundle, "BANK_A", ReportingBasis.INDIVIDUAL)

    # The intragroup row is KEPT (individual basis) but stays False.
    df = result.loans.collect()
    assert df["loan_reference"].to_list() == ["IG"]
    assert _eligible_refs(result) == set()


def test_feature_disabled_yields_no_eligibility():
    """Pack Feature off -> the resolver never computes eligibility (all False)."""
    bundle = _bundle(
        _loans([("IG", "BOOK_A", "BANK_B", "BANK_B")]),
        _tree({"GRP": True, "BANK_A": True, "BANK_B": True}),
    )

    result = _resolve(bundle, "BANK_A", ReportingBasis.INDIVIDUAL, feature=False)

    assert _eligible_refs(result) == set()


def test_carrier_column_always_present_after_resolution():
    """The carrier is sealed onto the resolved loans frame regardless of eligibility."""
    bundle = _bundle(
        _loans([("EXT", "BOOK_A", "CP_EXT", None)]),
        _tree({"GRP": False, "BANK_A": False, "BANK_B": False}),
    )

    result = _resolve(bundle, "BANK_A", ReportingBasis.INDIVIDUAL)

    df = result.loans.collect()
    assert "intragroup_zero_rw_eligible" in df.columns
    assert df["intragroup_zero_rw_eligible"].to_list() == [False]


# ---------------------------------------------------------------------------
# Bypass closure: the resolver is authoritative — a stray input True is clobbered
# ---------------------------------------------------------------------------


def test_stray_input_true_clobbered_when_reporting_entity_not_cug():
    """A user-loaded stray True is overwritten to False when the run is not CUG-eligible."""
    bundle = _bundle(
        _loan_with_stray_carrier("IG", "BOOK_A", "BANK_B", "BANK_B"),
        # Target BANK_B is CUG, but the reporting entity BANK_A is NOT — no row eligible.
        _tree({"GRP": True, "BANK_A": False, "BANK_B": True}),
    )

    result = _resolve(bundle, "BANK_A", ReportingBasis.INDIVIDUAL)

    assert _carrier(result) == [False]


def test_stray_input_true_clobbered_on_ineligible_row():
    """A stray True on a row whose target is not CUG is overwritten to False."""
    bundle = _bundle(
        _loan_with_stray_carrier("IG", "BOOK_A", "BANK_B", "BANK_B"),
        # Reporting entity BANK_A is CUG, but the target BANK_B is NOT.
        _tree({"GRP": True, "BANK_A": True, "BANK_B": False}),
    )

    result = _resolve(bundle, "BANK_A", ReportingBasis.INDIVIDUAL)

    assert _carrier(result) == [False]
