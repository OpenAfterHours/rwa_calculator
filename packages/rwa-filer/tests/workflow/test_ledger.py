"""The audit ledger: appended in order, and any later alteration is detected."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from rwa_filer.workflow.ledger import (
    EVENT_ADJUSTMENT,
    EVENT_BUILD,
    EVENT_SIGNOFF,
    GENESIS,
    append_entry,
    read_ledger,
    verify_ledger,
)

AT = datetime(2027, 4, 20, 9, 30, tzinfo=UTC)


def ledger(tmp_path: Path) -> Path:
    path = tmp_path / "filing.ledger.jsonl"
    append_entry(path, EVENT_ADJUSTMENT, {"adjustments": [{"cell": "A"}]}, author="Ann", at=AT)
    append_entry(path, EVENT_BUILD, {"sha256": "abc"}, author="Ann", at=AT)
    append_entry(path, EVENT_SIGNOFF, {"approver": "Bo"}, author="Bo", at=AT)
    return path


def rewrite(path: Path, edit) -> None:  # noqa: ANN001 - a small test helper
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    edit(lines)
    path.write_text("".join(json.dumps(line, sort_keys=True) + "\n" for line in lines))


def test_entries_are_numbered_and_each_names_the_one_before(tmp_path: Path) -> None:
    # Act
    entries = read_ledger(ledger(tmp_path))

    # Assert
    assert [(e.sequence, e.event, e.author) for e in entries] == [
        (1, EVENT_ADJUSTMENT, "Ann"),
        (2, EVENT_BUILD, "Ann"),
        (3, EVENT_SIGNOFF, "Bo"),
    ]
    assert entries[0].previous == GENESIS
    assert [e.previous for e in entries[1:]] == [e.hash for e in entries[:-1]]
    assert entries[0].at == "2027-04-20T09:30:00+00:00"


def test_an_intact_ledger_verifies(tmp_path: Path) -> None:
    assert verify_ledger(ledger(tmp_path)) == []


def test_an_altered_entry_is_detected(tmp_path: Path) -> None:
    # Arrange — the build's recorded checksum is edited.
    path = ledger(tmp_path)
    rewrite(path, lambda lines: lines[1]["payload"].update(sha256="other"))

    # Act / Assert
    assert verify_ledger(path) == ["entry 2 has been altered since it was written"]


def test_a_removed_entry_is_detected(tmp_path: Path) -> None:
    path = ledger(tmp_path)
    rewrite(path, lambda lines: lines.pop(1))

    problems = verify_ledger(path)

    assert "entry 2 is numbered 3: an entry is missing or out of order" in problems
    assert "entry 2 does not follow the entry before it" in problems


def test_an_altered_author_is_detected(tmp_path: Path) -> None:
    path = ledger(tmp_path)
    rewrite(path, lambda lines: lines[0].update(author="Someone else"))

    assert verify_ledger(path) == ["entry 1 has been altered since it was written"]


def test_a_missing_or_empty_ledger_does_not_verify(tmp_path: Path) -> None:
    """ "Nothing recorded" and "the record is gone" must not look alike."""
    empty = tmp_path / "empty.ledger.jsonl"
    empty.write_text("")

    assert verify_ledger(tmp_path / "absent.ledger.jsonl") == ["absent.ledger.jsonl does not exist"]
    assert verify_ledger(empty) == ["empty.ledger.jsonl holds no entry"]


def test_a_broken_ledger_is_never_extended(tmp_path: Path) -> None:
    """An entry chained onto a broken chain would look intact from then on."""
    # Arrange
    path = ledger(tmp_path)
    rewrite(path, lambda lines: lines[1]["payload"].update(sha256="other"))

    # Act / Assert
    with pytest.raises(ValueError, match="does not verify and was not extended"):
        append_entry(path, EVENT_BUILD, {}, author="Ann", at=AT)
    assert len(read_ledger(path)) == 3


def test_an_entry_needs_an_author(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="needs an author"):
        append_entry(tmp_path / "x.ledger.jsonl", EVENT_BUILD, {}, author="  ", at=AT)


def test_a_file_that_is_not_a_ledger_is_reported_not_raised_by_verify(tmp_path: Path) -> None:
    path = tmp_path / "x.ledger.jsonl"
    path.write_text("not json\n")

    assert "line 1 is not a ledger entry" in verify_ledger(path)[0]
