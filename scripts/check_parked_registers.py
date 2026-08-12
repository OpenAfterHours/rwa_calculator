"""
Ratchet the DECLARED registers of parked findings — oracle + classification table.

Pipeline position:
    (not a pipeline stage) — a gate. Run by
    ``tests/contracts/test_parked_register_ratchet.py`` on every dev-loop pytest
    run, and available standalone:

        uv run python scripts/check_parked_registers.py            # census
        uv run python scripts/check_parked_registers.py --check    # the gate
        uv run python scripts/check_parked_registers.py --update-baseline

Key responsibilities:
- Read the two registers whose membership is DECLARED rather than measured:
  ``KNOWN_DISAGREEMENTS`` (``tests/oracle/test_oracle.py``) and
  ``[[known_disagreement]]`` (``tests/conformance/classification_table.toml``).
- Ratchet them against ``scripts/parked_registers_baseline.json`` through the
  shared mechanism in ``scripts/tolerated_findings.py``:
  (a) no register entry outside the committed baseline — additions are
      shrink-only, and this script will not bank one;
  (c) every entry names an owning plan bullet via an ``OWNER: P<n>.<n>`` token.
  Requirement (b) — no baseline entry that no longer disagrees — is already
  discharged by ``xfail(strict=True)`` on both registers and is deliberately not
  re-implemented here; see "Why (b) is absent" below.

Why a script here, and pytest-native there
------------------------------------------
The four registers split cleanly on ONE property: **what it costs to compute the
current membership.**

- ``known_broken_rules`` / ``known_uncovered_templates`` / ``known_vacuous_rules``
  are **measured**. Membership is a union over sixteen pipeline runs, and only
  pytest owns the session fixtures that produce them. A script would have to
  rebuild the whole reporting estate to ask the question, so that ratchet stays
  where the data already is —
  ``tests/acceptance/reporting/test_supervisory_validations.py``.
- ``KNOWN_DISAGREEMENTS`` and ``[[known_disagreement]]`` are **declared**. Their
  membership is a dict literal and a TOML array; reading it is a file parse of a
  few milliseconds. Nothing about them needs a pipeline.

So the two halves cannot share a runner. What they share is the mechanism — the
set arithmetic, the owner grammar and the wording — and that is factored into
``scripts/tolerated_findings.py``, which both import. One mechanism, two runners,
for a stated reason rather than by accident.

The script form buys one thing the pytest form cannot: an explicit
``--update-baseline`` verb, so *banking* is a separate act from *checking* and
shows up in review as its own command in a commit message. That verb is
deliberately crippled — it prunes and refreshes, and REFUSES to add — which is
what makes additions shrink-only.

Why (b) is absent
-----------------
Both registers attach every entry as ``pytest.mark.xfail(strict=True)``, so an
entry whose engine defect gets fixed becomes an XPASS and fails the suite hard
until it is removed. That is requirement (b), already enforced, at the only place
that can enforce it — the place that actually runs the comparison. Re-asserting
it from a static parse is impossible (this script never runs the engine) and
duplicating it in the supervisory register's style would be a second, weaker
copy. What this script adds is the direction ``strict=True`` is blind to:
GROWTH.

References:
- ``IMPLEMENTATION_PLAN.md`` P5.41 (a)(b)(c)
- ``docs/development/escape-log.md`` — 2026-08-09 entry 4, ``caught-and-parked``
- `.claude/LESSONS.md` B7, B8
- ``scripts/check_doc_links.py`` — the ``--check`` / ``--update-baseline`` shape
- ``scripts/check_template_cell_coverage.py`` — the set-diff baseline shape
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tolerated_findings import (  # noqa: E402  (needs REPO_ROOT on sys.path)
    UNOWNED_GUIDANCE,
    diff,
    owner_of,
    unowned,
)

BASELINE_PATH = REPO_ROOT / "scripts" / "parked_registers_baseline.json"
CLASSIFICATION_TABLE_PATH = REPO_ROOT / "tests" / "conformance" / "classification_table.toml"

BASELINE_COMMENT = (
    "Parked-findings ratchet (scripts/check_parked_registers.py --check). Each "
    "entry is a finding a gate MADE and the estate agreed to tolerate, so the id "
    "set may only SHRINK: --update-baseline prunes and refreshes owners but "
    "refuses to add, and banking a new parked finding means hand-editing this "
    "file so the decision appears in review. See IMPLEMENTATION_PLAN.md P5.41 "
    "and docs/development/escape-log.md 2026-08-09 entry 4."
)


# ---------------------------------------------------------------------------
# The registers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Register:
    """One declared register of parked findings."""

    name: str
    """Key in the baseline file."""

    source: str
    """Where a reader edits the register itself."""

    entries: dict[str, str]
    """``{finding id: the reason text a reader sees on the failure}``."""


def load_registers() -> tuple[Register, ...]:
    """Every declared register, read from its own home.

    Both are read the way the tests read them, not re-parsed into a private
    shape: the oracle register is IMPORTED (so the f-string reasons are the exact
    strings pytest puts on the xfail marks — an AST parse would have to re-fold
    ``_ART_197_FCSM_ELIGIBILITY`` and could drift), and the classification table
    is parsed with ``tomllib``, which is what ``tests/conformance/table.py`` does.
    """
    return (_oracle_register(), _classification_register())


def _oracle_register() -> Register:
    from tests.oracle.test_oracle import KNOWN_DISAGREEMENTS

    return Register(
        name="oracle_known_disagreements",
        source="tests/oracle/test_oracle.py::KNOWN_DISAGREEMENTS",
        entries=dict(KNOWN_DISAGREEMENTS),
    )


def _classification_register() -> Register:
    raw = tomllib.loads(CLASSIFICATION_TABLE_PATH.read_text(encoding="utf-8"))
    return Register(
        name="classification_known_disagreements",
        source="tests/conformance/classification_table.toml [[known_disagreement]]",
        entries={str(entry["id"]): str(entry["detail"]) for entry in raw["known_disagreement"]},
    )


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


def check(registers: tuple[Register, ...], baseline: dict[str, dict[str, str]]) -> tuple[int, str]:
    """Ratchet every register against the baseline. Returns ``(exit code, report)``.

    Failing conditions, and nothing else:
      * an entry the baseline does not admit to (an ADDITION — shrink-only);
      * an entry naming no owning plan bullet (requirement (c));
      * a baseline register key with no register behind it (structural drift —
        a register renamed or deleted without its baseline, which would silently
        stop gating).

    A removal is reported and passes. See ``tolerated_findings`` for why the two
    directions are not symmetric.
    """
    lines: list[str] = []
    failed = False

    known = {register.name for register in registers}
    orphans = sorted(set(baseline) - known)
    if orphans:
        failed = True
        lines.append(
            f"STRUCTURE: {len(orphans)} baseline register(s) have no register behind them: "
            f"{', '.join(orphans)}\n"
            "  A register that was renamed or deleted takes its ratchet with it. Repoint "
            "load_registers() or delete the baseline block deliberately."
        )

    for register in registers:
        banked = baseline.get(register.name, {})
        movement = diff(register.entries, banked)
        missing = unowned(register.entries)

        if register.name not in baseline:
            failed = True
            lines.append(
                f"STRUCTURE: `{register.name}` has no block in {BASELINE_PATH.name}, so all "
                f"{len(register.entries)} of its entries read as new. Add the block by hand."
            )
        elif movement.added:
            failed = True
            lines.append(
                f"NEW PARKED FINDING ({register.source}): {len(movement.added)} entry/entries "
                f"outside the committed baseline:\n"
                + "\n".join(
                    f"    {key}  (owner: {owner_of(register.entries[key]) or 'NONE'})"
                    for key in movement.added
                )
                + "\n  This register may only SHRINK. Every entry is a number we have "
                "independent evidence is WRONG and are shipping anyway, so growing the "
                "population is a decision, not a side effect.\n"
                "  FIX THE DEFECT. If the finding is genuinely accepted, hand-edit "
                f"{BASELINE_PATH.name} to add the id with its owning bullet — --update-baseline "
                "will not do it for you."
            )

        if missing:
            failed = True
            lines.append(
                f"NO OWNING BULLET ({register.source}): {len(missing)} entry/entries name no "
                f"plan bullet:\n"
                + "\n".join(f"    {key}" for key in missing)
                + f"\n  {UNOWNED_GUIDANCE}"
            )

        if movement.removed:
            lines.append(
                f"IMPROVED ({register.source}): {len(movement.removed)} baseline entry/entries "
                f"have left the register: {', '.join(movement.removed)}\n"
                "  Not a failure — this is the outcome the register exists to provoke. Prune "
                "the baseline in the same change:\n"
                "    uv run python scripts/check_parked_registers.py --update-baseline"
            )

    if not failed:
        total = sum(len(register.entries) for register in registers)
        lines.append(
            f"[OK] {total} parked finding(s) across {len(registers)} register(s), "
            "every one baselined and owned"
        )
    return (1 if failed else 0, "\n".join(lines) + "\n")


def update_baseline(registers: tuple[Register, ...], baseline: dict[str, dict[str, str]]) -> int:
    """Prune departed ids and refresh owners. REFUSES to add — additions are the gate.

    This is the crippled half of the usual ``--update-baseline`` verb, and the
    crippling is the feature. Every other ratchet in this repo can be satisfied
    by re-banking a worse number; this one cannot, because the thing it counts is
    findings we have agreed to ship wrong.
    """
    payload: dict[str, dict[str, str]] = {}
    blocked: list[str] = []
    for register in registers:
        banked = baseline.get(register.name, {})
        movement = diff(register.entries, banked)
        blocked.extend(f"{register.name}: {key}" for key in movement.added)
        payload[register.name] = {
            key: owner_of(register.entries[key]) or "UNOWNED" for key in movement.held
        }
        if movement.removed:
            sys.stderr.write(
                f"pruned {len(movement.removed)} entry/entries from {register.name}: "
                f"{', '.join(movement.removed)}\n"
            )

    _write_baseline(registers, payload)
    sys.stderr.write(
        f"baseline banked at {sum(len(block) for block in payload.values())} parked finding(s)\n"
    )
    if blocked:
        sys.stderr.write(
            f"\nREFUSED to bank {len(blocked)} NEW entry/entries:\n  "
            + "\n  ".join(blocked)
            + f"\nAdditions are shrink-only. Fix the defect, or hand-edit {BASELINE_PATH.name} "
            "so the decision to ship a known-wrong number appears in the diff.\n"
        )
        return 1
    return 0


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def read_baseline() -> dict[str, dict[str, str]]:
    """``{register name: {finding id: owning bullet}}`` from the committed file."""
    if not BASELINE_PATH.exists():
        return {}
    raw = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    return {
        str(name): {str(key): str(owner) for key, owner in block.items()}
        for name, block in raw.get("registers", {}).items()
    }


def _write_baseline(registers: tuple[Register, ...], payload: dict[str, dict[str, str]]) -> None:
    sources = {register.name: register.source for register in registers}
    document = {
        "_comment": BASELINE_COMMENT,
        "registers": dict(sorted(payload.items())),
        "sources": dict(sorted(sources.items())),
    }
    BASELINE_PATH.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def _census(registers: tuple[Register, ...]) -> Iterator[str]:
    for register in registers:
        yield f"{register.name}  ({register.source})"
        for key, reason in sorted(register.entries.items()):
            yield f"  {key:<48} {owner_of(reason) or 'NO OWNER'}"
        yield f"  -- {len(register.entries)} entry/entries"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Shrink-only ratchet over the declared registers of parked findings."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="run the gate (exit 1 on a failure)")
    mode.add_argument(
        "--update-baseline",
        action="store_true",
        help="prune departed ids and refresh owners; refuses to add new ids",
    )
    args = parser.parse_args()

    registers = load_registers()
    if args.update_baseline:
        return update_baseline(registers, read_baseline())
    if args.check:
        code, report = check(registers, read_baseline())
        sys.stderr.write(report)
        return code
    sys.stderr.write("\n".join(_census(registers)) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
