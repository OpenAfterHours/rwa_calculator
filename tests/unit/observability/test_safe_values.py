"""
Tests for ``observability.safe_values.loggable`` — CWE-117 log-record forging.

The property under test is not "the output looks tidy". It is that a value a
stranger controls cannot produce something a reader of the log will mistake for
a record this system authored. So the tests are written as attacks: each names
the forgery it attempts and asserts the attack does not survive.
"""

from __future__ import annotations

import logging

import pytest

from rwa_calc.observability import loggable
from rwa_calc.observability.safe_values import _MAX_LENGTH

# One entry per way a log line can be forged or a terminal driven.
FORGERIES = [
    pytest.param("a\nINFO forged record", "newline splits the record", id="newline"),
    pytest.param("a\r\nINFO forged", "CRLF splits it on Windows readers", id="crlf"),
    pytest.param("a\rWIPED", "bare CR rewrites the line in a terminal", id="carriage-return"),
    pytest.param("a\x1b[2KWIPED", "ANSI erases what was already printed", id="ansi-escape"),
    pytest.param("a\x00b", "NUL truncates in some log consumers", id="nul"),
    pytest.param("a\tb", "tab fakes a column separator", id="tab"),
    pytest.param("a b", "unicode line separator", id="unicode-line-sep"),
]


@pytest.mark.parametrize(("hostile", "why"), FORGERIES)
def test_a_forged_record_does_not_survive(hostile: str, why: str) -> None:
    """No control or line-breaking character reaches the record. (%s)"""
    # Act
    rendered = loggable(hostile)

    # Assert — the specific characters that make forgery possible are gone, and
    # nothing outside the allowlist replaced them.
    assert "\n" not in rendered, why
    assert "\r" not in rendered, why
    assert "\x1b" not in rendered, why
    assert "\x00" not in rendered, why
    assert "\t" not in rendered, why
    assert " " not in rendered, why
    assert all(ch.isprintable() for ch in rendered)


def test_the_legitimate_value_it_is_meant_to_carry_survives_intact() -> None:
    """A real cell address must read exactly as itself, or the guard is useless."""
    # Arrange — the values this project actually logs: a template id, a sheet, a
    # predicate key, a run id, a path.
    for benign in (
        "c08_03/corporate/0010 (ours)",
        "reporting_gross_on_bs",
        "9f2c1ab4e6d3417f8b0a5c7e2d1f4a6b",
        "/data/legacy_output.csv",
        "C 08.03 - IRB PD ranges",
        "user@example.com",
        "rwa_final+ead_final",
    ):
        # Act / Assert
        assert loggable(benign) == benign, benign


def test_a_forged_record_is_visibly_replaced_not_silently_dropped() -> None:
    """A reader must see that something was removed, not a plausible short value."""
    # Act
    rendered = loggable("ok\nINFO forged")

    # Assert — the newline becomes a visible marker, so the line reads as
    # tampered rather than as a legitimately odd value.
    assert rendered == "ok?INFO forged"


def test_an_oversized_value_cannot_bury_the_records_around_it() -> None:
    """Truncation is bounded and marked, so a cut is distinguishable from a short value."""
    # Arrange
    flood = "A" * (_MAX_LENGTH * 3)

    # Act
    rendered = loggable(flood)

    # Assert
    assert len(rendered) == _MAX_LENGTH + len("...")
    assert rendered.endswith("...")


def test_a_value_at_the_limit_is_not_marked_as_truncated() -> None:
    """The boundary is exact — an unmarked value really was not cut."""
    # Arrange
    exact = "A" * _MAX_LENGTH

    # Act / Assert
    assert loggable(exact) == exact
    assert loggable("A" * (_MAX_LENGTH + 1)).endswith("...")


def test_a_non_string_is_rendered_rather_than_raising() -> None:
    """Callers log ints and None; the helper must not become a source of errors."""
    # Act / Assert
    assert loggable(None) == "None"
    assert loggable(42) == "42"
    assert loggable(3.5) == "3.5"


def test_a_non_positive_limit_is_a_programming_error() -> None:
    """Reserve exceptions for programming errors — a zero limit is one."""
    # Act / Assert
    with pytest.raises(ValueError, match="max_length must be positive"):
        loggable("x", max_length=0)


def test_the_guard_holds_through_a_real_log_record(caplog: pytest.LogCaptureFixture) -> None:
    """End to end: the emitted record carries one line, not two.

    Interpolation happens inside ``logging``, so a guard that works on the
    string but not through the formatter would pass every test above and still
    let a forged line reach the log.
    """
    # Arrange
    logger = logging.getLogger("rwa_calc.test.safe_values")
    hostile = "corporate\nINFO  rwa_calc.engine  totals reconciled"

    # Act
    with caplog.at_level(logging.INFO, logger="rwa_calc.test.safe_values"):
        logger.info("sheet=%s", loggable(hostile))

    # Assert — one record, and its rendered message is a single line.
    assert len(caplog.records) == 1
    assert "\n" not in caplog.records[0].getMessage()
