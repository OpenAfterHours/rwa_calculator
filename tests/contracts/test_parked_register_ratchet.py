"""
Contract: the registers of parked findings may only shrink, and every entry is owned.

Pipeline position:
    (not a pipeline stage) — a gate over ``tests/`` itself.

Key responsibilities:
- Run ``scripts/check_parked_registers.py --check`` for real, on every dev-loop
  pytest run, so the ratchet cannot rot unwired.
- Drive the shared mechanism in ``scripts/tolerated_findings.py`` through
  synthetic register/baseline pairs, so BOTH directions of the ratchet, the
  owner grammar and the open-owner rule are demonstrable in milliseconds rather
  than argued from code.

Why the wiring test is in-suite rather than a CI job:
    ``docs/development/escape-log.md`` 2026-08-09 entry 1 is the whole argument.
    A ratchet wired only into ``.github/workflows/ci.yml`` was defeated six ways
    while its invocation guard stayed green (``run:`` commented out, ``if:
    false``, ``continue-on-error: true``, the step deleted with the command left
    in a comment, the workflow's ``on:`` triggers removed, and the guard asserting
    that CI *invokes* the script rather than that the script *works*). The census
    here costs milliseconds — it is a dict literal and a TOML parse, not a
    pipeline run — so it belongs where nobody has to remember to run it.

References:
- ``IMPLEMENTATION_PLAN.md`` P5.41, P5.83 (an owner must be an open bullet)
- `.claude/LESSONS.md` B7 (an xfail needs an owner), B8 (ratchet the accumulator)
- ``docs/development/escape-log.md`` — 2026-08-09 entry 4, ``caught-and-parked``
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from scripts.check_parked_registers import (
    Register,
    check,
    load_registers,
    read_baseline,
    read_open_bullets,
)
from scripts.tolerated_findings import closed_owners, diff, owner_of, stale_owners, unowned

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# The gate itself, against the real registers
# ---------------------------------------------------------------------------


def test_the_parked_registers_hold_no_entry_outside_the_baseline() -> None:
    """Requirement (a) — a new parked finding must be a deliberate, banked act.

    Arrange: the two declared registers and the committed baseline.
    Act:     run the real gate.
    Assert:  it passes.
    """
    # Arrange / Act
    code, report = check(load_registers(), read_baseline(), read_open_bullets())

    # Assert
    assert code == 0, f"\n{report}"


def test_every_parked_finding_names_an_owning_plan_bullet() -> None:
    """Requirement (c) — an entry naming no bullet is the review finding.

    Stated separately from the gate above so the failure says which of the two
    conditions broke without anyone reading the report text.

    Arrange: the two declared registers.
    Act:     find entries whose reason names no ``OWNER: P<n>.<n>`` token.
    Assert:  there are none.
    """
    # Arrange / Act
    orphaned = {
        register.source: unowned(register.entries)
        for register in load_registers()
        if unowned(register.entries)
    }

    # Assert
    assert not orphaned, "parked findings with no owning plan bullet:\n" + "\n".join(
        f"  {source}: {', '.join(keys)}" for source, keys in orphaned.items()
    )


def test_every_parked_finding_is_owned_by_an_open_plan_bullet() -> None:
    """Requirement (d) — an owner the plan has closed or pruned owns nothing.

    Stated separately for the same reason as (c): the failure names the condition.

    Arrange: the two declared registers and the plan's open bullets.
    Act:     find entries naming, with any token, a bullet that is not open.
    Assert:  there are none.
    """
    # Arrange
    open_ids = read_open_bullets()

    # Act
    stale = {
        register.source: [
            f"{key} ({', '.join(closed_owners(register.entries[key], open_ids))})"
            for key in stale_owners(register.entries, open_ids)
        ]
        for register in load_registers()
    }

    # Assert
    assert not any(stale.values()), "parked findings owned by a closed bullet:\n" + "\n".join(
        f"  {source}: {', '.join(keys)}" for source, keys in stale.items() if keys
    )


def test_the_ratchet_runs_as_a_script() -> None:
    """The CLI is the reviewable form of this gate — it must actually run.

    A gate that only works when imported in-process is a gate whose
    ``--update-baseline`` verb nobody can trust, and that verb is what makes an
    addition deliberate.

    Arrange: the repo root.
    Act:     shell out to ``--check``.
    Assert:  exit 0.
    """
    # Arrange / Act
    result = subprocess.run(  # noqa: S603
        [sys.executable, "scripts/check_parked_registers.py", "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    # Assert
    assert result.returncode == 0, f"\n{result.stdout}{result.stderr}"


# ---------------------------------------------------------------------------
# The mechanism, driven synthetically — the gate watched failing
# ---------------------------------------------------------------------------


def _register(entries: dict[str, str]) -> tuple[Register, ...]:
    return (Register(name="synthetic", source="synthetic register", entries=entries),)


_OWNED = "OWNER: P9.99. a synthetic parked finding"
#: The plan bullets the synthetic legs treat as open.
_OPEN = frozenset({"P9.99"})


def test_an_entry_outside_the_baseline_fails_the_gate() -> None:
    """A ninth disagreement, with a perfectly good reason and owner, still fails.

    This is the whole point of P5.41: the register grew 4 -> 11 in one batch and
    every entry was well written. Quality of the reason is not the constraint —
    membership is.

    Arrange: a register holding one more entry than the baseline admits.
    Act:     run the gate.
    Assert:  it fails, and says the entry is new.
    """
    # Arrange
    registers = _register({"ORC-001": _OWNED, "ORC-999": _OWNED})
    baseline = {"synthetic": {"ORC-001": "P9.99"}}

    # Act
    code, report = check(registers, baseline, _OPEN)

    # Assert
    assert code == 1
    assert "NEW PARKED FINDING" in report
    assert "ORC-999" in report
    assert "ORC-001" not in report.split("NEW PARKED FINDING")[1]


def test_an_entry_naming_no_plan_bullet_fails_the_gate() -> None:
    """Requirement (c), watched failing — remove the owner and the gate fires.

    Arrange: a baselined entry whose reason names no bullet.
    Act:     run the gate.
    Assert:  it fails on ownership, not on membership.
    """
    # Arrange
    registers = _register({"ORC-001": "a reason with no owning bullet at all"})
    baseline = {"synthetic": {"ORC-001": "P9.99"}}

    # Act
    code, report = check(registers, baseline, _OPEN)

    # Assert
    assert code == 1
    assert "NO OWNING BULLET" in report
    assert "NEW PARKED FINDING" not in report


def test_an_entry_owned_by_a_closed_bullet_fails_the_gate() -> None:
    """Requirement (d), watched failing — an owner the plan no longer holds open.

    The shape is the real one: ``scripts/parked_registers_baseline.json`` still
    maps seven oracle ids to P1.330, which closed on 2026-08-13 and was pruned
    from the plan. Had any of those entries stayed in the register, its token
    would still have parsed, and only this condition says it owns nothing.

    Arrange: a baselined entry owned by P1.330, with only P9.99 open.
    Act:     run the gate.
    Assert:  it fails on the closed owner, naming the entry and the bullet, and
             on nothing else.
    """
    # Arrange
    registers = _register({"ORC-257": "OWNER: P1.330. a finding whose bullet closed"})
    baseline = {"synthetic": {"ORC-257": "P1.330"}}

    # Act
    code, report = check(registers, baseline, _OPEN)

    # Assert
    assert code == 1
    assert "OWNER NOT OPEN" in report
    assert "ORC-257" in report and "P1.330" in report
    assert "NO OWNING BULLET" not in report and "NEW PARKED FINDING" not in report


def test_a_closed_bullet_named_after_an_open_owner_fails_the_gate() -> None:
    """Requirement (d) reads every ``OWNER:`` token, not only the owning first one.

    The first token is the entry's owner — it is what the baseline banks — but a
    second token naming a closed bullet still reads as an owner to anyone who
    greps for one. A closed bullet cited as history is written as prose.

    Arrange: a baselined entry owned by open P9.99 that also carries a token for
             P1.330, which closed and was pruned.
    Act:     run the gate.
    Assert:  it fails on the closed token, naming P1.330, and on nothing else.
    """
    # Arrange
    registers = _register({"ORC-257": "OWNER: P9.99. a finding; was OWNER: P1.330"})
    baseline = {"synthetic": {"ORC-257": "P9.99"}}

    # Act
    code, report = check(registers, baseline, _OPEN)

    # Assert
    assert code == 1, report
    assert "OWNER NOT OPEN" in report and "P1.330" in report
    assert "NO OWNING BULLET" not in report and "NEW PARKED FINDING" not in report


def test_the_open_owner_condition_does_not_fire_on_an_open_bullet() -> None:
    """The mirror of (d): the same entry passes once its bullet is open.

    Arrange: the entry above, with P1.330 open.
    Act:     run the gate.
    Assert:  it passes.
    """
    # Arrange
    registers = _register({"ORC-257": "OWNER: P1.330. a finding whose bullet is open"})
    baseline = {"synthetic": {"ORC-257": "P1.330"}}

    # Act
    code, report = check(registers, baseline, frozenset({"P1.330"}))

    # Assert
    assert code == 0, report


def test_a_removed_entry_passes_the_gate_and_asks_to_be_pruned() -> None:
    """Removals are FREE — fixing the defect is the outcome, not a regression.

    Arrange: a baseline holding an entry the register has dropped.
    Act:     run the gate.
    Assert:  it passes, and points at ``--update-baseline``.
    """
    # Arrange
    registers = _register({"ORC-001": _OWNED})
    baseline = {"synthetic": {"ORC-001": "P9.99", "ORC-002": "P9.99"}}

    # Act
    code, report = check(registers, baseline, _OPEN)

    # Assert
    assert code == 0, report
    assert "IMPROVED" in report
    assert "ORC-002" in report


def test_a_register_that_lost_its_baseline_block_fails_the_gate() -> None:
    """Deleting the ratchet's own data is not a way to pass it.

    The failure mode this closes is the one ``.claude/LESSONS.md`` B8 records in
    a different shape: a gate satisfiable by removing the thing it measures.

    Arrange: a baseline with no block for the register.
    Act:     run the gate.
    Assert:  it fails structurally.
    """
    # Arrange / Act
    code, report = check(_register({"ORC-001": _OWNED}), {}, _OPEN)

    # Assert
    assert code == 1
    assert "STRUCTURE" in report


def test_a_baseline_block_with_no_register_behind_it_fails_the_gate() -> None:
    """The mirror: renaming a register away silently takes its ratchet with it.

    Arrange: a baseline naming a register ``load_registers`` no longer returns.
    Act:     run the gate.
    Assert:  it fails structurally and names the orphan.
    """
    # Arrange
    baseline = {"synthetic": {"ORC-001": "P9.99"}, "deleted_register": {"X-1": "P9.99"}}

    # Act
    code, report = check(_register({"ORC-001": _OWNED}), baseline, _OPEN)

    # Assert
    assert code == 1
    assert "deleted_register" in report


# ---------------------------------------------------------------------------
# The owner grammar
# ---------------------------------------------------------------------------


def test_a_historical_bullet_reference_is_not_an_owner() -> None:
    """The grammar is a token, not a bare P-code anywhere in the prose.

    Measured on the real register: ``_ART_154_4A_B_SCOPE`` in
    ``tests/oracle/test_oracle.py`` says "Since P1.319, engine/irb/adjustments.py
    gates on the first two and not the third" — a reference to the bullet that
    NARROWED the gate, not an owner for what is left. A bare-regex gate would
    have passed the one entry whose ownership was hardest to establish.

    Arrange: two reasons, one citing a bullet historically and one owning it.
    Act:     parse each.
    Assert:  only the token counts.
    """
    # Arrange / Act / Assert
    assert owner_of("Since P1.319, the gate was narrowed to two limbs.") is None
    assert owner_of("OWNER: P1.337. Since P1.319, the gate was narrowed.") == "P1.337"


def test_the_first_owner_token_wins() -> None:
    """A second token does not dilute who is responsible; (d) still holds it open."""
    assert owner_of("OWNER: P1.330. Related to OWNER: P1.337 and P1.303.") == "P1.330"


# ---------------------------------------------------------------------------
# The set arithmetic
# ---------------------------------------------------------------------------


def test_the_diff_reports_both_directions_and_takes_no_view() -> None:
    """``diff`` is direction-neutral; the CALLER decides which way is a failure.

    Keeping the asymmetry in one place — the caller — is why one mechanism can
    serve a shrink-only register and the supervisory register's two-way one.
    """
    movement = diff(["a", "b", "c"], ["b", "c", "d"])

    assert movement.added == ("a",)
    assert movement.removed == ("d",)
    assert movement.held == ("b", "c")
    assert movement.moved is True


def test_a_register_that_grew_by_one_and_shrank_by_one_has_moved() -> None:
    """The accumulator is the id SET, never a count (`.claude/LESSONS.md` B8).

    A count-based ratchet reads this as flat and banks a fresh capital
    understatement in exchange for a fix somewhere else.
    """
    movement = diff(["a", "x"], ["a", "b"])

    assert movement.added == ("x",)
    assert movement.removed == ("b",)


def test_the_diff_is_generic_over_the_id_type() -> None:
    """The supervisory register keys on a NamedTuple, the declared ones on str.

    85 rule ids appear under both regimes there, so its key must carry the
    regime. The mechanism must not assume a string, or it can only serve half
    the registers it was extracted to serve.
    """
    movement = diff([("b31", "r1"), ("crr", "r1")], [("crr", "r1")])

    assert movement.added == (("b31", "r1"),)
    assert movement.removed == ()
