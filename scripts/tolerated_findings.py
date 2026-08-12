"""
Tolerated-findings ratchet — the one mechanism behind every parked register.

Pipeline position:
    (not a pipeline stage) — a gate primitive, imported by
    ``scripts/check_parked_registers.py`` and by
    ``tests/acceptance/reporting/test_supervisory_validations.py``.

Key responsibilities:
- Diff a register of tolerated findings against a committed baseline of ids.
- Parse the OWNER token that names the plan bullet responsible for an entry.

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

References:
- `.claude/LESSONS.md` B7 (a strict xfail is a decision to ship the wrong
  number), B8 (ratchet the accumulator)
- `docs/development/escape-log.md` — 2026-08-09 entry 4, ``caught-and-parked``
- ``IMPLEMENTATION_PLAN.md`` P5.41
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

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

    The FIRST token wins. An entry whose reason quotes several bullets is owned
    by the one it leads with, so a reason may cite context without diluting
    responsibility.
    """
    match = OWNER_TOKEN.search(reason)
    return match.group(1) if match else None


def unowned[K](entries: Mapping[K, str]) -> tuple[K, ...]:
    """The register ids whose reason text names no owning plan bullet."""
    return tuple(sorted(key for key, reason in entries.items() if owner_of(reason) is None))
