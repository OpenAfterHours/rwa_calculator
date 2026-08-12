"""
Generator 5 — sign flips on amounts, duplicate keys, and orphan foreign keys.

Pipeline position:
    corpus portfolio -> broken key / flipped sign -> full pipeline
        -> triage invariant

Two live gaps this module was built to demonstrate
--------------------------------------------------

**DQ005 ``ERROR_ORPHAN_REFERENCE`` is declared and emitted nowhere.** It appears
in ``contracts/errors.py`` and in the ``contracts/__init__.py`` re-export, and in
no other file under ``src/``. The counterparty enrichment join is ``how="left"``
(``engine/stages/hierarchy/enrich.py``), so a loan whose ``counterparty_reference``
matches no counterparty survives with null obligor attributes, classifies to
``other``, and takes the 100% fallback risk weight.

Measured on this branch, CRR, one GBP 1,000,000 senior loan:

=====================================  ==============  ==============
Counterparty                           ``rwa_final``   Signal raised
=====================================  ==============  ==============
CQS 6 corporate (Art. 122, 150%)       GBP 1,500,000   none (correct)
same loan, ``counterparty_reference``  GBP 1,000,000   **none**
pointed at a reference that does not
exist
=====================================  ==============  ==============

A **33.3% understatement** on a one-character typo in a feed, with no exception,
no null and no ``CalculationError``. The direction runs the other way for a CQS 1
corporate (GBP 200,000 correct against GBP 1,000,000 — a 5x overstatement), so
the defect is not conservative in either direction; it is a coin flip whose face
depends on the obligor's true class. A null ``counterparty_reference`` reaches the
identical fallback.

**Duplicate keys collapse silently.** ``engine/stages/classify/permissions.py``
de-duplicates on ``exposure_reference`` after the model-permission join — correct
for its own purpose, which is to stop a fan-out when several permissions match —
but it also collapses genuine duplicate INPUT rows. Three input loan rows produce
two output rows and no error. That is clause (e) in the harness docstring, and it
is why :func:`triage` counts input ROWS rather than input references.

Both are reported to the operator; neither is xfailed and neither is worked
around. A generator that avoided them would be tuned to report success.

References:
- docs/plans/test-space-correctness-proposal.md — Phase 2, generator 5
- CRR Art. 122: corporate SA risk weights by CQS (the measured table above)
- .claude/LESSONS.md B4 (absence is this project's dominant escape class)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl
import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from tests.properties.portfolios import ExposureSpec, build_bundle
from tests.robustness.harness import (
    Injection,
    assert_accounted,
    inject,
    present_columns,
    run,
    triage,
    with_columns,
)
from tests.robustness.strategies import SEARCH_SETTINGS, TABLE_SCHEMAS, base_portfolios

if TYPE_CHECKING:
    from tests.properties.portfolios import Portfolio

#: A reference no table contains.
ORPHAN_REFERENCE = "CP_DOES_NOT_EXIST"

#: The measured pair from the module docstring. CQS 6 because that is where the
#: fallback UNDERSTATES: Art. 122 puts a CQS 6 corporate at 150% and the
#: ``other`` fallback at 100%.
_CQS6_CORPORATE = ExposureSpec(entity_type="corporate", drawn=1_000_000.0, external_cqs=6)
_MEASURED_RWA_CQS6 = 1_500_000.0
_MEASURED_RWA_ORPHANED = 1_000_000.0

#: The foreign keys a feed actually breaks, as ``(table, column)``.
_FOREIGN_KEYS: tuple[tuple[str, str], ...] = (
    ("loans", "counterparty_reference"),
    ("contingents", "counterparty_reference"),
    ("facilities", "counterparty_reference"),
    ("collateral", "beneficiary_reference"),
    ("guarantees", "beneficiary_reference"),
    ("guarantees", "guarantor"),
    ("provisions", "beneficiary_reference"),
    ("ratings", "counterparty_reference"),
    ("specialised_lending", "counterparty_reference"),
)

#: Amount columns whose sign a feed flips — a credit-note convention, a
#: sign-reversed extract, or a subtraction that went the wrong way.
_AMOUNT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("loans", "drawn_amount"),
    ("loans", "interest"),
    ("contingents", "nominal_amount"),
    ("facilities", "limit"),
    ("collateral", "market_value"),
    ("collateral", "nominal_value"),
    ("guarantees", "amount_covered"),
    ("provisions", "amount"),
)


# =============================================================================
# Orphan foreign keys — the DQ005 gap
# =============================================================================


def test_an_orphan_counterparty_reference_understates_a_cqs6_corporate_silently() -> None:
    """The measured DQ005 case. EXPECTED TO FAIL until DQ005 has a producer.

    Asserts the thing that ought to be true — an exposure whose obligor cannot
    be found is either rejected or flagged — rather than pinning the wrong
    number. The measured values are asserted first so that a failure here is
    unambiguously about the missing signal and not about the risk weights having
    moved underneath the test.
    """
    # Arrange
    clean_bundle = build_bundle((_CQS6_CORPORATE,))
    clean_rwa = float(run(clean_bundle).results.collect()["rwa_final"].sum())

    orphaned = with_columns(
        clean_bundle, "loans", pl.lit(ORPHAN_REFERENCE).alias("counterparty_reference")
    )

    # Act
    result = run(orphaned)
    orphaned_rwa = float(result.results.collect()["rwa_final"].sum())

    # Assert
    assert clean_rwa == pytest.approx(_MEASURED_RWA_CQS6), (
        f"control moved: a CQS 6 corporate is CRR Art. 122 150%, got {clean_rwa:,.2f}"
    )
    assert orphaned_rwa == pytest.approx(_MEASURED_RWA_ORPHANED), (
        "the orphan fallback moved; re-measure this module's docstring table "
        f"(got {orphaned_rwa:,.2f})"
    )
    assert result.errors, (
        f"an exposure whose counterparty_reference '{ORPHAN_REFERENCE}' matches no "
        f"counterparty produced GBP {orphaned_rwa:,.2f} against a correct GBP "
        f"{clean_rwa:,.2f} — a {1 - orphaned_rwa / clean_rwa:.1%} understatement — "
        "and the run raised NO error at all. DQ005 ERROR_ORPHAN_REFERENCE is "
        "declared in contracts/errors.py and emitted nowhere in src/."
    )


def test_a_null_counterparty_reference_reaches_the_same_fallback() -> None:
    """Null and orphan are the same defect wearing different clothes.

    Stated separately because a fix that only handles the non-null orphan case
    would leave this one open, and because a null foreign key is the MORE common
    feed shape — an outer join upstream, or a column that was never populated.
    """
    # Arrange
    bundle = build_bundle((_CQS6_CORPORATE,))
    mutated = with_columns(
        bundle, "loans", pl.lit(None, dtype=pl.String).alias("counterparty_reference")
    )

    # Act
    result = run(mutated)
    rwa = float(result.results.collect()["rwa_final"].sum())

    # Assert
    assert rwa == pytest.approx(_MEASURED_RWA_ORPHANED), (
        f"a null counterparty_reference no longer reaches the 'other' 100% "
        f"fallback (got {rwa:,.2f}); re-measure before reading the next assertion"
    )
    assert result.errors, (
        "an exposure with no counterparty_reference at all produced "
        f"GBP {rwa:,.2f} and no error names it"
    )


@SEARCH_SETTINGS
@given(portfolio=base_portfolios(), target=st.sampled_from(_FOREIGN_KEYS))
def test_an_orphan_foreign_key_accounts_for_every_row(
    portfolio: Portfolio, target: tuple[str, str]
) -> None:
    """Every input row survives a broken foreign key, or something names it.

    ``assume`` rather than ``pytest.skip``: inside a Hypothesis property a skip
    on one unlucky example abandons the WHOLE property, so a single portfolio
    that happens not to populate the drawn table would disarm the sweep and
    report green.
    """
    # Arrange
    table, column = target
    bundle = build_bundle(portfolio)
    assume(present_columns(bundle, [(table, column)]))

    # Act
    mutated = with_columns(bundle, table, pl.lit(ORPHAN_REFERENCE).alias(column))

    # Assert
    assert_accounted(mutated, run(mutated), [Injection(table, column, "orphan foreign key")])


# =============================================================================
# Duplicate keys
# =============================================================================


def test_a_duplicated_loan_row_does_not_vanish_without_a_word() -> None:
    """EXPECTED TO FAIL: three input loan rows produce two output rows, silently.

    A duplicated row is what a re-run extract, a double-appended file or a
    re-delivered daily feed produces, and it is the one pathology where the
    reference IS present in the output — so a per-reference identity cannot see
    it. Whether the right behaviour is to reject the duplicate or to compute
    both legs is a design question; that the run says nothing is not.
    """
    # Arrange
    portfolio = (
        ExposureSpec(entity_type="corporate", drawn=1_000_000.0, external_cqs=3),
        ExposureSpec(entity_type="individual", drawn=200_000.0, external_cqs=3),
    )
    bundle = build_bundle(portfolio)
    duplicated = inject(bundle, loans=pl.concat([bundle.loans, bundle.loans.head(1)]))

    # Act
    injections = [Injection("loans", "loan_reference", "duplicated row")]
    result = run(duplicated)
    report = triage(duplicated, result, injections)

    # Assert
    assert report.input_rows == 3, (
        f"expected 2 loans + 1 duplicate = 3 input exposure rows, got "
        f"{report.input_rows}; the fixture changed and the count below means nothing"
    )
    assert report.ok, report.describe(injections)


@SEARCH_SETTINGS
@given(portfolio=base_portfolios(max_size=3))
def test_duplicating_every_loan_row_accounts_for_every_row(portfolio: Portfolio) -> None:
    """The same shape at portfolio scale — a whole file delivered twice."""
    # Arrange
    bundle = build_bundle(portfolio)
    duplicated = inject(bundle, loans=pl.concat([bundle.loans, bundle.loans]))

    # Act / Assert
    assert_accounted(
        duplicated,
        run(duplicated),
        [Injection("loans", "loan_reference", "whole file delivered twice")],
    )


# =============================================================================
# Sign flips
# =============================================================================


@SEARCH_SETTINGS
@given(portfolio=base_portfolios(), target=st.sampled_from(_AMOUNT_COLUMNS))
def test_a_sign_flipped_amount_accounts_for_every_row(
    portfolio: Portfolio, target: tuple[str, str]
) -> None:
    """A negative amount must not silently subtract capital from the portfolio.

    ``loans.drawn_amount`` and ``loans.interest`` are DELIBERATELY outside
    ``contracts/validation.py``'s non-negative set — a negative on-balance-sheet
    amount is the CRR Art. 195/219 netting convention, and flagging it would be
    a false positive on valid data. They are swept here anyway: the invariant
    asks whether the row is accounted for, which is a fair question of a netting
    convention too.
    """
    # Arrange
    table, column = target
    bundle = build_bundle(portfolio)
    assume(present_columns(bundle, [(table, column)]))

    # Act
    mutated = with_columns(bundle, table, (-pl.col(column).abs()).alias(column))

    # Assert
    assert_accounted(mutated, run(mutated), [Injection(table, column, "sign flip")])


def test_the_foreign_key_and_amount_populations_are_declared_columns() -> None:
    """The two hand-written column lists must name columns that still exist.

    A list of ``(table, column)`` pairs is exactly the shape that rots silently:
    a rename leaves the sweep skipping every example and reporting green. Anchored
    to the schema declarations rather than to a second hand-written list
    (`.claude/LESSONS.md` B3).
    """
    # Arrange / Act
    undeclared = [
        (table, column)
        for table, column in (*_FOREIGN_KEYS, *_AMOUNT_COLUMNS)
        if column not in TABLE_SCHEMAS.get(table, {})
    ]

    # Assert
    assert not undeclared, f"these columns are no longer declared in data/schemas.py: {undeclared}"
