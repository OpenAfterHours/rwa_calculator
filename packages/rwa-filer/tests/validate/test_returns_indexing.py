"""
One validation indexes the return for the rule engine once.

Pipeline position:
    CanonicalReturn  ->  validate_return / trace_return
        ->  boe.engine (the return's facts, indexed for evaluation: once)
        ->  the rule pass, then the publisher-issue pass over the same index

What is pinned:
- ``validate_return`` on a return that breaks a rule a publisher issue explains
  only in part indexes the return ONCE. The issue's label classifies every
  break inside or outside the issue's footprint, which takes a second, traced
  pass over that rule; the pass used to index the whole return again, on every
  validate, build and dashboard open (measured 2026-11-22, one index of a
  PRA001 return: 0.03 s CPU on ``rich``, 0.13 s at 200 countries, 0.37 s at 200
  countries written by their local names).
- ``trace_return`` indexes it once too.
- The two passes agree, so the second is silent: a re-trace that counted the
  rule's evaluations differently is logged as a warning, and none is.
- The rule pass still says what it did, once, at INFO.

How it is counted: at the engine's own seam for placing facts on data points
(``boe.engine.resolve_datapoints``), which it calls once per index. No clock is
read. The seam is asserted live, and the label is asserted to have classified
the break, so the count cannot pass on a validation that never took the second
pass (LESSONS C11).

Observed red before the change (2026-11-22, unchanged engine): the
``validate_return`` count was 2. The ``trace_return`` count was 1 already; it
was observed red against a mutant whose traced pass builds its own index.

References:
- docs/plans/rwa-filer-performance-review-2026-11-22.md, item 4 (plan P6.60 b)
- rwa_filer.validate.issue_labels.needs_trace — which rules take the second pass
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import date
from typing import TYPE_CHECKING

import polars as pl
import pytest

from boe_builders import T02, book, issue_register, ref, rule
from pack_builders import build_pack, build_return
from rwa_filer.boe import engine
from rwa_filer.boe.engine import STATUS_FAIL, Accuracy
from rwa_filer.model import DECIMALS_EXACT
from rwa_filer.release import release_for_pack
from rwa_filer.validate.issue_labels import needs_trace
from rwa_filer.validate.returns import trace_return, validate_return

if TYPE_CHECKING:
    from pathlib import Path

    from rwa_filer.model import CanonicalReturn
    from rwa_filer.release import Release
    from rwa_filer.validate.returns import ReturnValidation

EXACT = Accuracy(monetary_decimals=DECIMALS_EXACT, percentage_decimals=DECIMALS_EXACT)
RUN = date(2026, 11, 22)

#: T02 row 0010 = row 0020, once per sheet (the sheet axis is left open).
PER_SHEET = rule("tst_0003", f"{ref(T02, '0010')} i= {ref(T02, '0020')}", tables=(T02,))
#: The logger the rule pass and the publisher-issue pass report on.
ENGINE_LOGGER = "rwa_filer.boe.engine"
RETURNS_LOGGER = "rwa_filer.validate.returns"


@pytest.fixture
def release(tmp_path: Path) -> Release:
    """One rule, and a publisher issue that explains its breaks on sheet 0001 only."""
    register = issue_register(PER_SHEET, footprint=[{"table": T02, "sheets": ["0001"]}])
    packaged = release_for_pack(build_pack(tmp_path), book(PER_SHEET), today=RUN)
    return replace(packaged, issues=register)


@pytest.fixture
def broken() -> CanonicalReturn:
    """The rule broken once inside the issue's footprint and once outside it."""
    rows = [
        (T02, "0001", "0010", 10.0),
        (T02, "0001", "0020", 20.0),
        (T02, "0002", "0010", 10.0),
        (T02, "0002", "0020", 30.0),
    ]
    frame = pl.DataFrame(
        [(table, sheet, None, row, "0010", value, None) for table, sheet, row, value in rows],
        schema={
            "table": pl.String,
            "sheet": pl.String,
            "open_key": pl.String,
            "row": pl.String,
            "column": pl.String,
            "value": pl.Float64,
            "text_value": pl.String,
        },
        orient="row",
    )
    return build_return(frame)


@pytest.fixture
def indexings(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """One entry per time the engine places a return's facts on data points."""
    seen: list[int] = []
    resolve = engine.resolve_datapoints

    def counted(*args: object, **kwargs: object) -> pl.DataFrame:
        seen.append(len(seen) + 1)
        return resolve(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(engine, "resolve_datapoints", counted)
    return seen


def test_validating_a_return_with_a_partly_explained_break_indexes_it_once(
    release: Release, broken: CanonicalReturn, indexings: list[int]
) -> None:
    # Act
    validation = validate_return(broken, release=release, accuracy=EXACT)

    # Assert - adequacy: the break was classified, which takes the second pass.
    _assert_the_break_was_classified(validation, release)
    assert indexings == [1], (
        f"the engine indexed the return {len(indexings)} time(s) in one validation: the "
        "publisher-issue pass must read the index the rule pass built"
    )


def test_tracing_a_return_with_a_partly_explained_break_indexes_it_once(
    release: Release, broken: CanonicalReturn, indexings: list[int]
) -> None:
    # Act
    validation, trace = trace_return(broken, release=release, accuracy=EXACT)

    # Assert
    _assert_the_break_was_classified(validation, release)
    assert trace is not None
    assert len(trace.evaluations) == 2, "the trace must hold the rule's two evaluations"
    assert indexings == [1], (
        f"the engine indexed the return {len(indexings)} time(s) in one traced validation"
    )


def test_the_publisher_issue_pass_counts_what_the_rule_pass_counted(
    release: Release, broken: CanonicalReturn, caplog: pytest.LogCaptureFixture
) -> None:
    """The second pass reads the first pass's index: it must find the same evaluations."""
    # Act
    with caplog.at_level(logging.WARNING, logger=RETURNS_LOGGER):
        validation = validate_return(broken, release=release, accuracy=EXACT)

    # Assert
    warnings = [record.getMessage() for record in caplog.records if record.name == RETURNS_LOGGER]
    assert not warnings, "the re-trace for the publisher-issue label disagreed with the rule pass"
    _assert_the_break_was_classified(validation, release)


def test_the_rule_pass_is_summarised_once_per_validation(
    release: Release, broken: CanonicalReturn, caplog: pytest.LogCaptureFixture
) -> None:
    # Act
    with caplog.at_level(logging.INFO, logger=ENGINE_LOGGER):
        validation = validate_return(broken, release=release, accuracy=EXACT)

    # Assert
    _assert_the_break_was_classified(validation, release)
    summaries = [
        record.getMessage()
        for record in caplog.records
        if record.name == ENGINE_LOGGER and record.levelno == logging.INFO
    ]
    assert summaries == ["evaluated 1 rule(s) for TST001: 1 failed, 0 not evaluated"]


# =============================================================================
# Helpers
# =============================================================================


def _assert_the_break_was_classified(validation: ReturnValidation, release: Release) -> None:
    """The rule broke, the issue's footprint applies, and each break was put on a side of it."""
    assert validation.report is not None
    results = validation.report.results
    assert [result.status for result in results] == [STATUS_FAIL]
    assert needs_trace(results, release.issues, release.pack.info.module) == {"tst_0003"}, (
        "no broken rule has a footprint to classify - the validation takes no second pass "
        "and counting its indexes would prove nothing"
    )
    (note,) = validation.report.notes_for("tst_0003")
    assert (note.inside, note.outside) == (1, 1), (
        "the breaks were not classified, so no traced pass over the rule ran"
    )
