"""
P1.291 — an unsolicited ECAI assessment must not be silently used.

Pipeline position:
    HierarchyResolver -> apply_short_term_rating_override -> error channel

What this pins:
    CRR / PS1-26 Art. 138 chapeau, verbatim (``crr.pdf`` PAGE_INDEX 134):

        "An institution shall use solicited credit assessments. However it may
        use unsolicited credit assessments if the competent authority has
        confirmed that unsolicited credit assessments of an ECAI do not differ
        in quality from solicited credit assessments of this ECAI."

    ``is_solicited`` was declared on ``RATINGS_SCHEMA`` and read **nowhere** in
    ``src/`` — a firm could mark an assessment unsolicited and the engine would
    use it with no signal of any kind.

Why a warning and NOT a filter:
    The bullet offered "consume the flag (config switch + DQ warning) or remove
    the dead column". Both prescriptions are wrong as stated, for the same
    reason: **the Art. 138 permission is per-ECAI and supervisor-granted.** It
    is not a property of the rating row and no input carries it.

    - **Filtering** on ``is_solicited`` alone would suppress every unsolicited
      assessment, denying ratings a firm is entitled to use wherever the
      confirmation exists — wrong in the denying direction.
    - **Deleting** the column would remove the only carrier for a real
      provision, on a flag that is genuinely regulatorily meaningful.

    So the engine surfaces the condition and leaves the decision with the firm,
    which is what the error channel is for (errors accumulate, never raise).

    One warning per run, not per row: which ECAI confirmations a firm holds is a
    portfolio-level governance fact, not a defect in any individual rating.
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.contracts.errors import CalculationError, ErrorSeverity
from rwa_calc.engine.stages.hierarchy.enrich import apply_short_term_rating_override

_DQ_UNSOLICITED = "DQ015"


def _ratings(*solicited: bool | None) -> pl.LazyFrame:
    n = len(solicited)
    return pl.DataFrame(
        {
            "rating_reference": [f"RT{i}" for i in range(n)],
            "counterparty_reference": [f"CP{i}" for i in range(n)],
            "rating_type": ["external"] * n,
            "cqs": [3] * n,
            # No short-term assessments: the override path short-circuits, which
            # keeps this test on the solicitation flag alone. The DQ015 census
            # runs ahead of that short-circuit by design — an unsolicited
            # long-term assessment is exactly as much an Art. 138 question as a
            # short-term one.
            "is_short_term": [False] * n,
            "scope_type": [None] * n,
            "scope_id": [None] * n,
            "rating_date": [None] * n,
            "is_solicited": pl.Series(list(solicited), dtype=pl.Boolean),
        },
        schema_overrides={
            "scope_type": pl.String,
            "scope_id": pl.String,
            "rating_date": pl.Date,
        },
    ).lazy()


def _exposures() -> pl.LazyFrame:
    return pl.DataFrame(
        {
            "exposure_reference": ["E1"],
            "counterparty_reference": ["CP0"],
            "exposure_type": ["loan"],
        }
    ).lazy()


def _run(ratings: pl.LazyFrame | None) -> list[CalculationError]:
    errors: list[CalculationError] = []
    apply_short_term_rating_override(_exposures(), ratings, errors=errors).collect()
    return [e for e in errors if e.code == _DQ_UNSOLICITED]


def test_p1_291_an_unsolicited_assessment_raises_a_warning() -> None:
    """An explicit ``is_solicited=False`` produces exactly one DQ015 warning.

    This is the assertion that fails before the fix: the column was declared and
    read nowhere, so no error of any code was produced.
    """
    found = _run(_ratings(False))

    assert len(found) == 1, (
        "P1.291: an unsolicited ECAI assessment must be surfaced. Art. 138 permits "
        "it only where the competent authority has confirmed the ECAI's unsolicited "
        "assessments match its solicited ones, and the engine cannot verify that "
        "from the input."
    )
    assert found[0].severity is ErrorSeverity.WARNING, (
        "P1.291: this is a governance condition the firm must confirm, not a data "
        "error that should block a run — the engine still uses the rating."
    )
    assert "138" in (found[0].regulatory_reference or "")


def test_p1_291_solicited_assessments_are_silent() -> None:
    """A solicited assessment produces no warning — the survives-the-change half.

    Without this, a fix that warned on every rating row would satisfy the
    assertion above while making the signal useless.
    """
    assert _run(_ratings(True)) == []


def test_p1_291_a_null_flag_is_silent() -> None:
    """A null ``is_solicited`` is not treated as unsolicited.

    The column is nullable with a ``True`` default, so null means "not stated"
    rather than "unsolicited". Warning on null would fire for every firm that
    never populates the field — the false-positive shape P1.354 fixed on the
    neighbouring DQ006, where a code that cries wolf on ordinary input trains
    readers to ignore it.
    """
    assert _run(_ratings(None)) == []


def test_p1_291_one_warning_per_run_not_per_row() -> None:
    """Three unsolicited assessments still produce one warning, carrying the count.

    Which ECAI confirmations a firm holds is a portfolio-level fact. Emitting
    one per row would bury it under repetition on a book that uses an
    unsolicited ECAI systematically — exactly the population that most needs to
    read it.
    """
    found = _run(_ratings(False, False, False))

    assert len(found) == 1
    assert "3" in found[0].message, (
        f"the warning should carry the count so the scale is visible: {found[0].message}"
    )


def test_p1_291_absent_ratings_frame_is_safe() -> None:
    """No ratings table at all produces no warning and does not raise."""
    assert _run(None) == []


@pytest.mark.parametrize("solicited", [True, False, None])
def test_p1_291_the_rating_is_used_either_way(solicited: bool | None) -> None:
    """The engine still returns a frame whatever the flag says.

    The fix must not have turned the warning into a filter by accident. Art. 138
    leaves the decision with the firm, so the assessment is used and flagged —
    never suppressed.
    """
    out = apply_short_term_rating_override(_exposures(), _ratings(solicited), errors=[]).collect()

    assert out.height == 1, "the exposure must survive regardless of the solicitation flag"
