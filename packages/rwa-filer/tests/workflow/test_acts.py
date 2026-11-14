"""The recorded acts the CLI and the dashboard share: build, sign-off, verify."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from pack_builders import VALID_LEI
from rwa_filer.cli import main
from rwa_filer.workflow.acts import ledger_beside, record_signoff, verify_filing
from rwa_filer.workflow.ledger import EVENT_BUILD, EVENT_SIGNOFF, append_entry, read_ledger
from rwa_filer.workflow.signoff import SignOffError

HEADER_ARGS = ["--entity", VALID_LEI, "--reference-date", "2027-03-31", "--module", "PRA001"]
#: An exposure and a value adjustment with nothing else: a broken rule.
SOURCE_CSV = (
    "table,sheet,row,column,value\n"
    "OF07.00.01.01,0008,0010,0010,1000000\n"
    "OF07.00.01.01,0008,0010,0030,-5000\n"
)
AT = datetime(2027, 4, 20, 9, 30, tzinfo=UTC)


@pytest.fixture
def forced(tmp_path: Path) -> Path:
    """A package written despite a broken rule, with a ledger; its manifest."""
    (tmp_path / "source.csv").write_text(SOURCE_CSV)
    main(
        [
            "build",
            str(tmp_path / "source.csv"),
            "--out",
            str(tmp_path / "out"),
            *HEADER_ARGS,
            "--force",
            "--author",
            "A. Preparer",
        ]
    )
    (manifest,) = (tmp_path / "out").glob("*.manifest.json")
    return manifest


def test_a_refused_sign_off_leaves_the_ledger_as_it_was(forced: Path) -> None:
    """The findings are not acknowledged, so there is no sign-off — and the
    ledger must not say there was one. (It used to record the entry first.)"""
    # Arrange
    ledger = ledger_beside(forced)
    before = [entry.event for entry in read_ledger(ledger)]

    # Act
    with pytest.raises(SignOffError, match="acknowledged explicitly"):
        record_signoff(forced, ledger=ledger, approver="C. Approver", role="Head", at=AT)

    # Assert
    assert before == [EVENT_BUILD]
    assert [entry.event for entry in read_ledger(ledger)] == before


def test_a_sign_off_is_recorded_in_the_ledger_and_bound_to_its_head(forced: Path) -> None:
    # Act
    approval = record_signoff(
        forced,
        ledger=ledger_beside(forced),
        approver="C. Approver",
        role="Head",
        at=AT,
        acknowledge_findings=True,
    )

    # Assert
    entries = read_ledger(ledger_beside(forced))
    assert [entry.event for entry in entries] == [EVENT_BUILD, EVENT_SIGNOFF]
    assert approval.ledger_head == entries[-1].hash
    assert verify_filing(forced) == []


def test_verify_notices_a_ledger_the_sign_off_was_not_recorded_in(
    forced: Path, tmp_path: Path
) -> None:
    # Arrange — signed off against the package's own ledger; another intact one is named.
    record_signoff(
        forced,
        ledger=ledger_beside(forced),
        approver="C. Approver",
        role="Head",
        at=AT,
        acknowledge_findings=True,
    )
    other = tmp_path / "other.ledger.jsonl"
    append_entry(other, EVENT_BUILD, {"instance": "elsewhere.xbrl"}, author="B. Other", at=AT)

    # Act
    problems = verify_filing(forced, ledger=other)

    # Assert
    assert "the audit ledger is not the one the sign-off was recorded in" in problems


def test_an_unsigned_package_fails_verify_unless_a_sign_off_is_not_required(
    forced: Path,
) -> None:
    assert verify_filing(forced) == ["the package has not been signed off"]
    assert verify_filing(forced, require_signoff=False) == []
