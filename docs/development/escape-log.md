# Escape log

A record of defects that **reached production**, and — the point of the file —
what now stops each one from happening again.

Every entry is written by `/postmortem`. The command's deliverable is not the
code fix; it is the answer to a single question:

> Which gate should have caught this, and why didn't it?

A defect that produced a fix commit and nothing else has taught the system
nothing, and will be paid for again. A defect that produced a new check, a new
fixture in `RUNS`, or a re-anchored assertion has been converted into
permanent capability.

## How to read an entry

- **Escape class** is one of seven, and it determines the fix:

  | Class | Meaning | Fix |
  |---|---|---|
  | `gate-not-run` | a catching gate existed but didn't run at that point | move the gate earlier |
  | `path-never-exercised` | the gate ran but no fixture reached the code | build the portfolio, register it in `RUNS` |
  | `test-shared-the-assumption` | a test covered it and passed, written from the same wrong sentence | re-anchor to a source of truth |
  | `no-assertion-of-presence` | output was absent/null rather than wrong | assert presence |
  | `wrong-premise` | the plan bullet was wrong and was faithfully implemented | strengthen Wave 0 |
  | `no-gate-exists` | nothing could have caught it | create the gate |
  | `ungateable` | not mechanically detectable | `.claude/LESSONS.md` entry, with reasoning |

- **Verified red** records how the new gate was confirmed to fail *without*
  the fix. A gate nobody has seen fail is not a gate.

## Related

- `.claude/LESSONS.md` — the working set of traps every agent reads before
  starting. Entries graduate out of it into executable checks.
- `scripts/arch_check.py` — the numbered architectural invariants. Each one is
  a lesson that graduated.
- `tests/acceptance/reporting/test_supervisory_validations.py` — the
  two-way-ratcheted register of published EBA/BoE rules; the estate's strongest
  oracle for reporting defects.

---

<!-- /postmortem appends entries below this line, newest last. -->
