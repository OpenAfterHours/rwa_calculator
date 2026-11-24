"""
Tolerated-findings ratchet — the one mechanism behind every parked register.

Pipeline position:
    (not a pipeline stage) — a gate primitive, imported by
    ``scripts/check_parked_registers.py`` and by
    ``tests/acceptance/reporting/test_supervisory_validations.py``.

Key responsibilities:
- Diff a register of tolerated findings against a committed baseline of ids.
- Parse the OWNER token that names the plan bullet responsible for an entry.
- Read which plan bullets are still open, so an owner the plan has closed or
  pruned is a finding rather than a token that merely parses.

Why this module exists at all
-----------------------------
This repository holds at least four parallel registers of findings a gate
*found* and the estate then agreed to *tolerate*:

===================================  ==========================================
``KNOWN_DISAGREEMENTS``              ``tests/oracle/test_oracle.py``
``[[known_disagreement]]``           ``tests/conformance/classification_table.toml``
``known_broken_rules``               ``tests/expected_outputs/reporting/
``known_vacuous_rules``                validation_known_breaks.json``
===================================  ==========================================

``docs/development/escape-log.md``'s ``caught-and-parked`` class exists for
exactly the failure they share: a gate fires, the finding is recorded, and the
wrong number ships anyway. Four bespoke ratchets would be four places to get the
direction wrong, so the set arithmetic, the owner grammar and the wording of the
failures live here once. The *runners* differ and must (see the note on
placement in ``check_parked_registers.py``); the mechanism does not.

The two directions are NOT gated alike, and that asymmetry is the point
----------------------------------------------------------------------
``diff()`` is direction-neutral — it reports ``added`` and ``removed`` and takes
no view. Its callers apply this contract:

- **Additions are shrink-only.** An id in the register that is not in the
  baseline is a HARD FAILURE. There is deliberately no bulk affordance that
  banks one: ``--update-baseline`` refuses to add. Banking a new parked finding
  means hand-editing the baseline file, which is a reviewable diff in a file
  whose entire purpose is to be reviewed. This is stronger than the two-way
  ratchets it was extracted from — ``REGEN_VALIDATION_BASELINE=1`` and
  ``--update-baseline`` elsewhere will happily bank an increase — and the reason
  for the difference is that an entry in *these* registers is a decision to ship
  a number we have independent evidence is wrong. `.claude/LESSONS.md` B7.

- **Removals are free.** An id in the baseline that has left the register is
  reported and is NOT a failure. Fixing the defect is the outcome the register
  exists to provoke, and a gate that reddens on a fix teaches people to stop
  fixing. The register's own ``xfail(strict=True)`` already forces the entry's
  removal in the same change (an entry that starts agreeing XPASSes and fails
  hard), so a stale baseline id is short-lived by construction.

  **Residual hole, stated rather than hidden:** while a baseline id is stale, it
  is slack in the addition gate — re-parking that same id would pass. Closing it
  would mean gating removals, which is the thing above. Prune with
  ``--update-baseline`` in the same change as the fix and the window is zero.

Ratchet the accumulator, never a ratio (`.claude/LESSONS.md` B8): the quantity
here is the *id set*, so a register cannot grow by one and shrink by one and
call it flat.

An owner must be OPEN, not merely present
-----------------------------------------
A token that parses is not an owner if the bullet it names is closed. Measured:
at ``d426393`` the plan marked P1.369 ``[x]`` while four ``OWNER: P1.369`` tokens
(three supervisory-register reasons and a note) stayed, and every gate was green. So
:func:`open_bullets` reads ``IMPLEMENTATION_PLAN.md`` and :func:`stale_owners`
reports an entry ANY of whose tokens names a bullet the plan does not hold open —
every token, not only the owning first one (:func:`closed_owners`): a note can park
several decisions with an owner each, and a token naming a closed bullet as history
still reads as an owner to ``grep 'OWNER: P'``, so history is written as prose.
Closed bullets are pruned from the plan, so a bullet that is absent is a closed one.
This makes the gates that call it read the plan: a change that closes or prunes an
owning bullet fails until it re-owns or removes the entries it owned, or reopens the
bullet — which is the change that should have to.

References:
- `.claude/LESSONS.md` B7 (a strict xfail is a decision to ship the wrong
  number), B8 (ratchet the accumulator)
- `docs/development/escape-log.md` — 2026-08-09 entry 4, ``caught-and-parked``
- ``IMPLEMENTATION_PLAN.md`` P5.41 (the ratchet), P5.83 (an owner must be open)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Mapping

#: The grammar for requirement (c). An entry must name the plan bullet that owns
#: the defect it parks, and it must do so with an explicit token — NOT with a
#: bare ``P1.234`` anywhere in the prose. Bare-regex matching was tried and
#: rejected: ``tests/oracle/test_oracle.py``'s ``_ART_154_4A_B_SCOPE`` already
#: contains "Since P1.319, engine/irb/adjustments.py gates on…", which is a
#: HISTORICAL reference to the bullet that narrowed the gate, not an owner for
#: the residual finding. A gate that accepted it would have passed the one entry
#: whose owner was hardest to establish and failed the seven whose owner was
#: obvious — i.e. it would have measured prose style, not ownership.
OWNER_TOKEN = re.compile(r"\bOWNER:\s*(P\d+\.\d+)\b")

#: What to print when an entry names no bullet. Kept here so the oracle register,
#: the classification table and any future register say the same thing.
UNOWNED_GUIDANCE = (
    "An entry with no owner is the review finding, not the xfail "
    "(.claude/LESSONS.md B7). Add `OWNER: P<tier>.<n>` to the entry's reason "
    "text, naming the IMPLEMENTATION_PLAN.md bullet that owns the fix — and "
    "file that bullet in the same change if it does not exist yet."
)

#: What to print when an entry's owner is not an open plan bullet. Names every
#: remedy, because the change that trips it is often a plan-only edit by someone
#: who does not own the register.
STALE_OWNER_GUIDANCE = (
    "An owner that is not an open IMPLEMENTATION_PLAN.md bullet owns nothing "
    "(.claude/LESSONS.md B7): the bullet was closed or pruned while the entry it owned "
    "stayed parked. If the closing change fixed the finding, remove the entry; if it "
    "did not, re-own the entry with `OWNER: P<tier>.<n>` naming an open bullet (filing "
    "one if none fits); if the bullet closed too early, reopen it."
)

#: How ``IMPLEMENTATION_PLAN.md`` states a work-queue bullet's status: a list item
#: that leads with the id in bold — the bold may run on past the id, as in
#: ``- **P8.48 (partial)** [ ]`` — followed by a status box. Lines that name an id
#: and carry no box state no status: the DO NOT RE-FILE list
#: (``- **P2.62, P2.64, P2.65, P2.66** (2026-11-16) — ...``), the completed reference
#: list, and prose that says a bullet "stays open". A lettered sub-id (``P1.288a``)
#: is not an id here, as it is not one in :data:`OWNER_TOKEN`.
PLAN_BULLET = re.compile(r"^\s*- \*\*(P\d+\.\d+)\b[^*\n]*\*\* \[([^\]\n]*)\]")
#: A detail section (``### P1.9 Output Floor ...``) states its status on a
#: ``- **Status:** [~]`` line under the heading instead.
PLAN_SECTION = re.compile(r"^#+ (P\d+\.\d+)\b")
SECTION_STATUS = re.compile(r"^\s*- \*\*Status:\*\* \[([^\]\n]*)\]")
#: The one status box that closes a bullet. Every other box — ``[ ]``, ``[~]``,
#: ``[partial]`` — is work still owed.
CLOSED_BOX = "x"


@dataclass(frozen=True)
class RegisterDiff[K]:
    """What moved between a register and its committed baseline.

    Direction-neutral by design: this type reports, and the caller decides which
    direction is a failure. See the module docstring for the contract every
    caller in this repository applies.
    """

    added: tuple[K, ...]
    """Register ids absent from the baseline — a NEW parked finding."""

    removed: tuple[K, ...]
    """Baseline ids absent from the register — a finding that has gone away."""

    held: tuple[K, ...]
    """Ids in both — the tolerated population that did not move."""

    @property
    def moved(self) -> bool:
        """True when the register and the baseline are not the same set."""
        return bool(self.added or self.removed)


def diff[K](register: Iterable[K], baseline: Iterable[K]) -> RegisterDiff[K]:
    """Set-diff a register's ids against the baseline's, sorted for stable output.

    Generic over the id type on purpose. The declared registers key on ``str``
    (``ORC-280``, ``D1b-…``); the supervisory register keys on its ``RuleKey``
    ``NamedTuple`` because 85 rule ids appear under both regimes and a key on the
    id alone silently drops half. Both are sortable, which is all this needs.
    """
    current = set(register)
    banked = set(baseline)
    return RegisterDiff(
        added=tuple(sorted(current - banked)),
        removed=tuple(sorted(banked - current)),
        held=tuple(sorted(current & banked)),
    )


def owner_of(reason: str) -> str | None:
    """The plan bullet named by an entry's reason text, or None if it names none.

    The FIRST token wins. An entry whose reason names several bullets is owned
    by the one it leads with — it is what a baseline banks — so a reason may name
    a second bullet without diluting responsibility. Every token is still held to
    an open bullet (:func:`closed_owners`), so a closed bullet cited as history is
    written as prose (``plan item P<n>.<n>``), not as a token.
    """
    match = OWNER_TOKEN.search(reason)
    return match.group(1) if match else None


def unowned[K](entries: Mapping[K, str]) -> tuple[K, ...]:
    """The register ids whose reason text names no owning plan bullet."""
    return tuple(sorted(key for key, reason in entries.items() if owner_of(reason) is None))


def open_bullets(plan_text: str) -> frozenset[str]:
    """The ids ``IMPLEMENTATION_PLAN.md`` holds open: a status box other than ``[x]``.

    Read from a bullet's own box (:data:`PLAN_BULLET`) or from the Status line of a
    detail section headed by the id (:data:`PLAN_SECTION`). An id with several
    bullets is open if any of them is. An id with no status at all — pruned, or
    named only in prose — is not open.
    """
    open_ids: set[str] = set()
    section: str | None = None
    for line in plan_text.splitlines():
        if line.startswith("#"):
            heading = PLAN_SECTION.match(line)
            section = heading.group(1) if heading else None
            continue
        status = _status_of(line, section)
        if status is not None and status[1].strip().lower() != CLOSED_BOX:
            open_ids.add(status[0])
    return frozenset(open_ids)


def stale_owners[K](entries: Mapping[K, str], open_ids: Collection[str]) -> tuple[K, ...]:
    """The register ids whose reason names, with any token, a plan bullet that is not open.

    An entry with no owner is not stale; it is :func:`unowned`, a separate finding.
    """
    return tuple(sorted(key for key, reason in entries.items() if closed_owners(reason, open_ids)))


def closed_owners(reason: str, open_ids: Collection[str]) -> tuple[str, ...]:
    """Every bullet a reason names with an ``OWNER:`` token that is not open, in order.

    Every token, not only the first that :func:`owner_of` returns: a reason or note
    can park more than one decision, each with its owner, and a closed one behind
    an open one owns nothing just the same.
    """
    return tuple(owner for owner in OWNER_TOKEN.findall(reason) if owner not in open_ids)


def _status_of(line: str, section: str | None) -> tuple[str, str] | None:
    """``(id, status box)`` if this plan line states one, else None."""
    bullet = PLAN_BULLET.match(line)
    if bullet:
        return bullet.group(1), bullet.group(2)
    status = SECTION_STATUS.match(line)
    if status and section:
        return section, status.group(1)
    return None
