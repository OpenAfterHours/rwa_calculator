"""
The ledger — an append-only, hash-chained record of what was done to a filing.

Pipeline position:
    adjustments / build / sign-off  ->  append_entry  ->  <name>.ledger.jsonl
    <name>.ledger.jsonl             ->  verify_ledger ->  problems (empty when intact)

Key responsibilities:
- Record each act — an adjustment batch, a build, a sign-off — with who did it
  and when, in the order it happened.
- Make later alteration detectable. Every entry carries the hash of the entry
  before it and a hash of its own content, so changing, removing or
  re-ordering any entry breaks the chain at that point.

What the chain does and does not give: it shows that the file has not been
altered since its last entry was written, to anyone holding that last hash
(a sign-off records it). It does not stop someone rewriting the whole file and
every hash in it; that needs the last hash to be held somewhere they cannot
write, which is an organisational control, not a file format.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime
    from pathlib import Path

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

EVENT_ADJUSTMENT: Final = "adjustment"
EVENT_BUILD: Final = "build"
EVENT_SIGNOFF: Final = "signoff"

#: The ``previous`` of the first entry.
GENESIS: Final = "0" * 64

LEDGER_SUFFIX: Final = ".ledger.jsonl"


# =============================================================================
# Public API
# =============================================================================


@dataclass(frozen=True)
class LedgerEntry:
    """One recorded act.

    Attributes:
        sequence: 1 for the first entry, then consecutive.
        at: When it was recorded, ISO 8601.
        author: Who did it.
        event: ``adjustment`` / ``build`` / ``signoff``.
        payload: What was done — event-specific, JSON-ready.
        previous: The ``hash`` of the entry before, or ``GENESIS``.
        hash: SHA-256 over every other field.
    """

    sequence: int
    at: str
    author: str
    event: str
    payload: Mapping[str, Any]
    previous: str
    hash: str

    def as_record(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "at": self.at,
            "author": self.author,
            "event": self.event,
            "payload": dict(self.payload),
            "previous": self.previous,
            "hash": self.hash,
        }


def append_entry(
    path: Path, event: str, payload: Mapping[str, Any], *, author: str, at: datetime
) -> LedgerEntry:
    """Append one entry to the ledger at ``path``, creating it if absent.

    Raises:
        ValueError: ``author`` is blank, or the existing ledger does not
            verify — a broken ledger is never extended, because an entry
            chained onto a broken chain would look intact from then on.
    """
    if not author.strip():
        raise ValueError("a ledger entry needs an author")
    entries = read_ledger(path)
    problems = _chain_problems(entries)
    if problems:
        raise ValueError(f"{path.name} does not verify and was not extended: {problems[0]}")
    previous = entries[-1].hash if entries else GENESIS
    body = {
        "sequence": len(entries) + 1,
        "at": at.isoformat(timespec="seconds"),
        "author": author.strip(),
        "event": event,
        "payload": dict(payload),
        "previous": previous,
    }
    entry = LedgerEntry(**body, hash=_digest(body))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(entry.as_record(), sort_keys=True, ensure_ascii=False) + "\n")
    logger.info("ledger %s: entry %d (%s) by %s", path.name, entry.sequence, event, entry.author)
    return entry


def read_ledger(path: Path) -> list[LedgerEntry]:
    """The entries of the ledger at ``path``, in order; empty if it does not exist.

    Raises:
        ValueError: a line is not a ledger entry at all.
    """
    if not path.is_file():
        return []
    entries: list[LedgerEntry] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            entries.append(
                LedgerEntry(
                    sequence=int(record["sequence"]),
                    at=str(record["at"]),
                    author=str(record["author"]),
                    event=str(record["event"]),
                    payload=dict(record["payload"]),
                    previous=str(record["previous"]),
                    hash=str(record["hash"]),
                )
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            raise ValueError(f"{path.name} line {number} is not a ledger entry: {error}") from error
    return entries


def verify_ledger(path: Path) -> list[str]:
    """Every way the ledger at ``path`` fails to verify. Empty means intact.

    A missing ledger is reported, not passed: "nothing recorded" and "the
    record is gone" must not look the same.
    """
    if not path.is_file():
        return [f"{path.name} does not exist"]
    try:
        entries = read_ledger(path)
    except ValueError as error:
        return [str(error)]
    if not entries:
        return [f"{path.name} holds no entry"]
    return _chain_problems(entries)


# =============================================================================
# Private helpers
# =============================================================================


def _digest(body: Mapping[str, Any]) -> str:
    """SHA-256 of an entry's content, over a canonical JSON form."""
    canonical = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _chain_problems(entries: list[LedgerEntry]) -> list[str]:
    problems: list[str] = []
    previous = GENESIS
    for position, entry in enumerate(entries, start=1):
        record = entry.as_record()
        del record["hash"]
        if entry.sequence != position:
            problems.append(
                f"entry {position} is numbered {entry.sequence}: an entry is missing or out of order"
            )
        if entry.previous != previous:
            problems.append(f"entry {position} does not follow the entry before it")
        if _digest(record) != entry.hash:
            problems.append(f"entry {position} has been altered since it was written")
        previous = entry.hash
    return problems
