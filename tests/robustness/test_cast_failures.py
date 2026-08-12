"""
The seal's cast failure — a garbage feed passes silently, end to end.

Pipeline position:
    CSV / typed feed -> EdgeContract.conform_lenient (cast strict=False)
        -> RawDataBundle -> full pipeline -> a plausible, wrong number

The gap
-------
``contracts/edges.py::conform_lenient`` casts every declared column whose dtype
does not match with ``strict=False``. Polars turns an uncastable value into a
NULL rather than raising, ``missing`` comes back empty, and no data-quality
error is emitted — the behaviour is pinned deliberately in
``tests/contracts/test_edge_contracts.py``. The input contract's own rule is
that null is never a domain violation (``data/column_spec.py``), correctly: a
missing PD is IRB004's business, not a range error. The two rules compose into a
hole. A value that could not be read becomes indistinguishable from a value that
was never supplied.

Measured on this branch, CRR, one GBP 1,000,000 CQS 1 senior corporate loan
whose ``drawn_amount`` arrives as the string ``"1,000,000.00"`` — a plain CSV
export with a thousands separator:

===================================  ==============  ==============
``drawn_amount`` as supplied         ``rwa_final``   Signal raised
===================================  ==============  ==============
``1000000.0`` (Float64)              GBP 200,000     none (correct)
``"1,000,000.00"`` (String)          GBP **0.00**    **none**
===================================  ==============  ==============

The exposure is not rejected, not flagged, and not visibly absent — it is
present in the results frame carrying ``ead_final = 0.00`` and
``rwa_final = 0.00``. A 100% understatement of that exposure's capital, and the
reviewer reading the output sees a populated row.

``CSVLoader`` (``engine/loader.py``) reads with ``pl.scan_csv``, which infers a
column containing ``1,000,000.00`` as ``String``; the seal then nulls it. So the
shape above is not contrived — it is what a CSV feed with a locale-formatted
amount does today.

What to do about it is a design question, not this suite's call
--------------------------------------------------------------
``conform_lenient`` is load-bearing for every stage, so this module demonstrates
the behaviour and does not change it. The recommendation, for the record: count
the cast failures at the seal (``value.is_not_null() & cast.is_null()``, one
count per column, one aggregate error each, at the SAME place the missing-column
DQ001 is emitted) and raise a new code — a cast failure is NOT ``DQ003``
``ERROR_TYPE_MISMATCH``, which Phase 0 deliberately retired as unfirable. It is
cheap (one extra expression per already-cast column, and only for columns whose
dtype actually mismatched) and it is the only signal that separates "unreadable"
from "absent".

References:
- docs/plans/test-space-correctness-proposal.md — Phase 2
- src/rwa_calc/contracts/edges.py — conform_lenient
- tests/contracts/test_edge_contracts.py — the unit-level pin of the same behaviour
- .claude/LESSONS.md B4: absence is this project's dominant escape class
"""

from __future__ import annotations

import polars as pl
import pytest
from hypothesis import given
from hypothesis import strategies as st

from rwa_calc.contracts.errors import ERROR_MISSING_FIELD
from tests.properties.portfolios import ExposureSpec, build_bundle
from tests.robustness.harness import Injection, assert_accounted, run, triage, with_columns
from tests.robustness.strategies import SEARCH_SETTINGS, base_portfolios

#: The exposure the measured table above is built on.
_CQS1_CORPORATE = ExposureSpec(entity_type="corporate", drawn=1_000_000.0, external_cqs=1)
_MEASURED_RWA_CORRECT = 200_000.0

#: Strings a real numeric feed contains that Polars cannot cast to Float64.
#: Every one of these is an ordinary export artefact, not corruption.
UNCASTABLE_NUMERICS: tuple[str, ...] = (
    "1,000,000.00",  # thousands separator (any en-GB/en-US CSV export)
    "£1000000",  # currency symbol
    "1 000 000",  # non-breaking / plain space separator (fr, de exports)
    "(1000000)",  # accounting negative
    "n/a",
    "",
    "1.0e",  # truncated scientific notation
)


def test_an_uncastable_amount_zeroes_an_exposure_silently() -> None:
    """EXPECTED TO FAIL: GBP 1m of exposure becomes GBP 0 with no signal.

    Asserts what ought to be true — a value that could not be read is reported —
    rather than pinning the zero. The two measured values are asserted first so a
    failure is unambiguously about the missing signal.
    """
    # Arrange
    clean_bundle = build_bundle((_CQS1_CORPORATE,))
    clean_rwa = float(run(clean_bundle).results.collect()["rwa_final"].sum())

    poisoned = with_columns(clean_bundle, "loans", pl.lit("1,000,000.00").alias("drawn_amount"))

    # Act
    sealed_values = poisoned.loans.select("drawn_amount").collect().to_series().to_list()
    result = run(poisoned)
    row = result.results.collect().to_dicts()[0]

    # Assert
    assert clean_rwa == pytest.approx(_MEASURED_RWA_CORRECT), (
        f"control moved: a CQS 1 corporate is CRR Art. 122 20%, got {clean_rwa:,.2f}"
    )
    assert sealed_values == [None], (
        f"the seal no longer nulls an uncastable amount (got {sealed_values}); "
        "re-measure this module's docstring table before reading on"
    )
    assert result.errors, (
        "a GBP 1,000,000 exposure whose drawn_amount arrived as the string "
        f"'1,000,000.00' produced ead_final={row['ead_final']}, "
        f"rwa_final={row['rwa_final']} against a correct GBP {clean_rwa:,.2f}, and "
        "the run raised NO error at all. conform_lenient casts with strict=False, "
        "so an unreadable value is indistinguishable from an absent one."
    )


@pytest.mark.parametrize("garbage", UNCASTABLE_NUMERICS)
def test_every_uncastable_form_of_a_numeric_feed_is_reported(garbage: str) -> None:
    """EXPECTED TO FAIL for the forms Polars cannot parse.

    Parametrised over the export artefacts rather than over one of them, because
    a fix that special-cases thousands separators would leave the rest open. A
    form Polars CAN parse is skipped and named, so this list documents which
    strings survive the seal and which do not.
    """
    # Arrange
    bundle = build_bundle((_CQS1_CORPORATE,))
    poisoned = with_columns(bundle, "loans", pl.lit(garbage).alias("drawn_amount"))

    # Act
    sealed = poisoned.loans.select("drawn_amount").collect().to_series().to_list()
    if sealed != [None]:
        pytest.skip(f"Polars parses {garbage!r} to {sealed} — no cast failure to report")
    result = run(poisoned)

    # Assert
    assert result.errors, (
        f"drawn_amount={garbage!r} could not be cast, was silently nulled, and "
        "produced a zero-capital exposure with no error"
    )


@SEARCH_SETTINGS
@given(portfolio=base_portfolios(), garbage=st.sampled_from(UNCASTABLE_NUMERICS))
def test_an_uncastable_amount_still_accounts_for_every_row(
    portfolio: tuple[ExposureSpec, ...], garbage: str
) -> None:
    """The triage invariant over the same pathology.

    Passes today, and that is the point worth stating: the row IS accounted for
    — it carries a finite, in-bounds ``rwa_final`` of ``0.00``. Zero is in
    bounds. No structural invariant over the output frame can distinguish a
    genuine zero-capital exposure from an unreadable one; only a signal at the
    seal can. This test exists so that a future change which turns the silent
    null into a DROPPED row is caught immediately.
    """
    # Arrange
    bundle = build_bundle(portfolio)
    poisoned = with_columns(bundle, "loans", pl.lit(garbage).alias("drawn_amount"))

    # Act / Assert
    assert_accounted(
        poisoned, run(poisoned), [Injection("loans", "drawn_amount", f"uncastable {garbage!r}")]
    )


def test_an_uncastable_value_is_not_reported_as_a_missing_column() -> None:
    """The two absences must not be conflated in the error channel either.

    ``conform_lenient`` returns ``missing`` for columns that were absent, and
    DQ001 is emitted from it. An uncastable value is present and unreadable,
    which is a different finding with a different remedy — the feed must be
    re-sent, not extended. Asserted so that a fix which routes cast failures
    through DQ001 is a deliberate choice rather than an accident.
    """
    # Arrange
    bundle = build_bundle((_CQS1_CORPORATE,))
    poisoned = with_columns(bundle, "loans", pl.lit("n/a").alias("drawn_amount"))

    # Act
    injections = [Injection("loans", "drawn_amount", "uncastable")]
    result = run(poisoned)
    report = triage(poisoned, result, injections)
    missing_column_errors = [error for error in result.errors if error.code == ERROR_MISSING_FIELD]

    # Assert
    assert report.ok, report.describe(injections)
    assert not missing_column_errors, (
        "an uncastable value was reported as a MISSING COLUMN; the column is "
        f"present and unreadable: {[e.message for e in missing_column_errors]}"
    )
