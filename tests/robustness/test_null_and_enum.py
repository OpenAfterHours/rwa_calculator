"""
Generators 3 and 4 — one null optional field at a time, and unknown enum strings.

Pipeline position:
    corpus portfolio -> one field nulled / one categorical replaced with garbage
        -> full pipeline -> triage invariant

Generator 3: null each optional field in turn
---------------------------------------------
The point is NOT that nulling a field changes the answer — of course it does.
The point is the third mechanism in the proposal's diagnosis: *Polars turns
absence into a number, not an error.* A null predicate takes the ``otherwise``
branch, nulls vanish from ``sum()``, and the engine's own debt ratchet records
472 ``fill_null`` sites. Each is a place where a missing field becomes a
confident value. This generator walks every optional column of every input table
one at a time and asks the only question that scales: is the row still accounted
for, or did it quietly leave the portfolio?

One field at a time, deliberately. Nulling several at once finds the same
defects but names none of them — the counter-example would be a portfolio rather
than a field.

Generator 4: unknown enum strings, including case and whitespace variants
-------------------------------------------------------------------------
``validate_column_values`` lower-cases both sides but does NOT strip, so
``"Corporate"`` is accepted and ``"corporate "`` is not. Both come out of the
same Excel round-trip. The garbage set in ``strategies.ENUM_GARBAGE`` carries
both, plus the empty string, ``"n/a"``, ``"NULL"`` and ``"-"``, which are what a
feed actually sends for "no value" when the column is typed as text.

DQ006 is a WARNING with ``exposure_reference=None``, so an unknown enum reaches
the invariant through clause (c) and never through clause (b). That is worth
knowing before reading a green run here as "unknown enums are handled": what is
asserted is that the row is accounted for, not that its risk weight is right.
A garbage ``entity_type`` classifies to ``other`` at 100% — measured in
``test_referential_integrity.py``, where the same fallback is the mechanism
behind a 33% understatement.

References:
- docs/plans/test-space-correctness-proposal.md — Phase 2, generators 3 and 4
- .claude/LESSONS.md B4 (assert what should be there, not only what is)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl
import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from tests.properties.portfolios import ExposureSpec, build_bundle
from tests.robustness.harness import Injection, assert_accounted, run, with_columns
from tests.robustness.strategies import (
    SEARCH_SETTINGS,
    TABLE_SCHEMAS,
    base_portfolios,
    declared_enum_domains,
    enum_garbage,
)

if TYPE_CHECKING:
    from tests.properties.portfolios import Portfolio

#: Columns that identify a row or link it to another table. Nulling one is a
#: REFERENTIAL pathology, not an absent-optional-field one, and it has its own
#: module (``test_referential_integrity.py``) with its own expectations. Sweeping
#: them here would attribute a referential defect to generator 3.
_KEY_SUFFIXES = ("_reference", "_references")

#: The portfolio generators 3 and 4 corrupt. Deliberately broad — a nulled field
#: on a table the portfolio does not populate tests nothing, and the sweep is
#: only as good as the columns it can reach.
_BROAD: Portfolio = (
    ExposureSpec(entity_type="corporate", drawn=1_000_000.0, internal_pd=0.01, firm_lgd=0.45),
    ExposureSpec(
        entity_type="individual",
        drawn=300_000.0,
        external_cqs=3,
        collateral_value=500_000.0,
        collateral_property_type="residential",
        guarantee_amount=50_000.0,
        provision_amount=10_000.0,
    ),
    ExposureSpec(
        entity_type="corporate",
        drawn=750_000.0,
        external_cqs=2,
        off_bs_nominal=250_000.0,
        is_specialised_lending=True,
    ),
)


def _optional_columns() -> tuple[tuple[str, str], ...]:
    """Every optional, non-key column of every input table this suite corrupts."""
    return tuple(
        (table, column)
        for table, schema in TABLE_SCHEMAS.items()
        for column, spec in schema.items()
        if not spec.required and not column.endswith(_KEY_SUFFIXES)
    )


_OPTIONAL_COLUMNS = _optional_columns()
_ENUM_COLUMNS = tuple((table, column) for table, column, _ in declared_enum_domains())


# =============================================================================
# Generator 3 — one nulled optional field at a time
# =============================================================================


def test_the_optional_column_population_is_not_empty() -> None:
    """A sweep over zero optional columns is a green suite that tested nothing."""
    assert len(_OPTIONAL_COLUMNS) >= 100, (
        f"only {len(_OPTIONAL_COLUMNS)} optional input columns found across "
        f"{len(TABLE_SCHEMAS)} tables; generator 3 is nearly idle"
    )


@pytest.mark.parametrize(("table", "column"), _OPTIONAL_COLUMNS, ids=lambda v: str(v))
def test_nulling_one_optional_field_accounts_for_every_row(table: str, column: str) -> None:
    """A single absent optional field must not silently remove an exposure."""
    # Arrange
    bundle = build_bundle(_BROAD)
    frame = getattr(bundle, table, None)
    if frame is None or column not in frame.collect_schema().names():
        pytest.skip(f"the broad portfolio does not populate {table}.{column}")

    # Act
    dtype = frame.collect_schema()[column]
    mutated = with_columns(bundle, table, pl.lit(None, dtype=dtype).alias(column))

    # Assert
    assert_accounted(mutated, run(mutated), [Injection(table, column, "nulled optional field")])


@SEARCH_SETTINGS
@given(portfolio=base_portfolios(), target=st.sampled_from(_OPTIONAL_COLUMNS))
def test_nulling_one_optional_field_accounts_for_every_row_on_any_portfolio(
    portfolio: Portfolio, target: tuple[str, str]
) -> None:
    """The same sweep, over generated portfolios rather than the fixed one."""
    # Arrange
    table, column = target
    bundle = build_bundle(portfolio)
    frame = getattr(bundle, table, None)
    # ``assume`` rather than ``pytest.skip``: inside a Hypothesis property a skip
    # on one unlucky example abandons the WHOLE property.
    assume(frame is not None)
    # `assume` is a Hypothesis rejection, not a type-narrowing construct — the
    # re-assertion is what tells the type checker the frame is present.
    assert frame is not None
    assume(column in frame.collect_schema().names())

    # Act
    dtype = frame.collect_schema()[column]
    mutated = with_columns(bundle, table, pl.lit(None, dtype=dtype).alias(column))

    # Assert
    assert_accounted(mutated, run(mutated), [Injection(table, column, "nulled optional field")])


# =============================================================================
# Generator 4 — unknown enum strings
# =============================================================================


def test_the_enum_column_population_is_not_empty() -> None:
    """The declared enum population is what generator 4 walks."""
    assert len(_ENUM_COLUMNS) >= 20, (
        f"only {len(_ENUM_COLUMNS)} EnumDomain declarations found; generator 4 is nearly idle"
    )


@SEARCH_SETTINGS
@given(target=st.sampled_from(_ENUM_COLUMNS), garbage=enum_garbage())
def test_an_unknown_enum_string_accounts_for_every_row(
    target: tuple[str, str], garbage: str
) -> None:
    """Case variants, whitespace and feed sentinels on every declared enum column."""
    # Arrange
    table, column = target
    bundle = build_bundle(_BROAD)
    frame = getattr(bundle, table, None)
    assume(frame is not None)
    # `assume` is a Hypothesis rejection, not a type-narrowing construct — the
    # re-assertion is what tells the type checker the frame is present.
    assert frame is not None
    assume(column in frame.collect_schema().names())
    assume(frame.collect_schema()[column] == pl.String)

    # Act
    mutated = with_columns(bundle, table, pl.lit(garbage).alias(column))

    # Assert
    assert_accounted(mutated, run(mutated), [Injection(table, column, f"enum garbage {garbage!r}")])


@pytest.mark.parametrize("variant", ["corporate ", " corporate", "CORPORATE", "Corporate"])
def test_case_and_whitespace_variants_of_a_valid_enum_are_treated_consistently(
    variant: str,
) -> None:
    """Whitespace is a domain violation where case is not — pinned, not assumed.

    ``validate_column_values`` and ``EnumDomain.violation_expr`` both lower-case
    without stripping, so ``"CORPORATE"`` is accepted and ``"corporate "`` is
    rejected. Both are the same Excel round-trip. This test states which is which
    so that a future decision to strip is a DELIBERATE change to a stated
    contract rather than a silent widening of the input domain.
    """
    # Arrange
    bundle = build_bundle(_BROAD)
    mutated = with_columns(bundle, "counterparties", pl.lit(variant).alias("entity_type"))

    # Act
    result = run(mutated)
    flagged = [error for error in result.errors if error.field_name == "entity_type"]

    # Assert
    assert_accounted(mutated, result, [Injection("counterparties", "entity_type", variant)])
    if variant.strip() == variant:
        assert not flagged, f"{variant!r} differs from 'corporate' only in case: {flagged}"
    else:
        assert flagged, (
            f"{variant!r} carries stray whitespace and was accepted silently; a "
            "feed that round-trips through Excel produces exactly this"
        )
