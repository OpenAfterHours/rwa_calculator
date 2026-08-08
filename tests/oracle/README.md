# Oracle Test Suite

A small set of RWA tests whose expected values are **independently
hand-derived** from the regulation, not recorded engine outputs.

## Why this suite exists

The audit report identified a structural weakness in the existing
`tests/expected_outputs/{crr,basel31}/*` golden files: their expected
values are produced *by the engine* and updated alongside the code in the
same commits. They catch regressions, but they cannot tell you whether the
engine's output matches the regulation — only whether it matches an earlier
version of itself.

This suite breaks the loop by deriving expected RWA values from the
regulation directly, with full intermediate arithmetic shown in
`ORACLE_DERIVATIONS.md` and reproduced programmatically by
`derive.py` (which uses **only** Python stdlib and does not import any
`rwa_calc` code).

It is also the only layer that can catch a **wrong constant**. If a risk weight
is 45% where the regulation says 50%, conservation still holds, monotonicity
still holds, bounds still hold, and every property in `tests/properties/`
passes. That defect class belongs to this suite alone.

## Files in this directory

| File | Purpose |
|---|---|
| `ORACLE_DERIVATIONS.md` | Narrative derivations with paragraph citations and full arithmetic. The independent source of truth. |
| `derivations/` | The shadow calculator. Stdlib-only modules that recompute the expected values. **Never imports `rwa_calc`.** |
| `derive.py` | Assembles the derivation records and writes `expected_values.json`. |
| `expected_values.json` | Generated. Carries a SHA-256 hash of `ORACLE_DERIVATIONS.md` so the doc and JSON cannot drift apart. |
| `drivers.py` | The only module here that imports `rwa_calc`. Supplies *inputs* to a calculator's `calculate_branch` and collects the row back. Derives nothing. |
| `test_oracle.py` | Pytest module. Compares engine output against the oracle within relative error 1e-6, asserts the doc-hash lock, and asserts the derivation modules never import the engine. |

### Layout of `derivations/`

| Module | Phase | Scope |
|---|---|---|
| `formulas.py` | — | Shared scalar arithmetic: correlations, maturity adjustment, conditional PD, supporting factors, band blends. |
| `record.py` | — | The oracle record shape. |
| `sa_crr.py` | O1 | Standardised Approach, UK CRR, every exposure class. |
| `sa_b31.py` | O1 | Standardised Approach, PRA PS1/26. |
| `irb.py` | O2 | Foundation and Advanced IRB, both regimes, including parameter floors. |
| `specialised.py` | O4 | Slotting and IRB equity. |

Phase O3 (credit risk mitigation) is not scaffolded — see the "Scope not yet
covered" section of `ORACLE_DERIVATIONS.md`.

## Running

```bash
uv run pytest tests/oracle -n 0
```

Pass `-n 0`. The suite is scalar arithmetic against direct calculator calls and
runs in a few seconds; letting xdist spin up workers costs more than the tests.

If the doc-hash test fails, see the failure message — it has the recovery recipe
inline.

## Two locks

1. **The doc hash.** `expected_values.json` embeds the SHA-256 of
   `ORACLE_DERIVATIONS.md`, LF-normalised. The doc and the JSON can only move
   together, and the move is a deliberate, auditable act.
2. **The import ban.** `test_derivations_never_import_rwa_calc` parses every
   module in `derivations/` plus `derive.py` and fails on any `rwa_calc` import.
   A value that came from the engine, however indirectly, is worthless as
   evidence about the engine.

## When the oracle and the engine disagree

**Do not adjust the oracle.** A disagreement is the most valuable output this
suite produces: it is either a real engine defect or a real error in the
derivation, and both are worth knowing. Silently tuning the oracle to agree
destroys the whole point.

Record it in `KNOWN_DISAGREEMENTS` in `test_oracle.py` as a strict xfail, with
the article, both figures, which intermediate diverges, and the direction of the
error. Remove the entry when the *engine* changes — never when the oracle does.

**Enumerate the whole rule family before stating a direction.** A defect found
at two members of a table is not thereby characterised: the Art. 121 Table 5
finding reads as purely conservative at CQS 1 and 2, agrees by coincidence at
CQS 3–5, and is anti-conservative at CQS 6. Reporting the direction from the
first two members alone would have under-prioritised a capital shortfall. Pin
every member, including the ones that pass — those are exactly the ones a future
change can move silently.

Correcting an oracle's **inputs** is a different thing and is legitimate: if a
fact pattern accidentally triggered a condition it did not mean to (a
third-country PSE without an equivalence determination, say), the inputs were
wrong, not the derived value.

**Before reporting a disagreement, check it is not your own driver.** An input
whose name matches no engine column used to be added to the frame as a dead
column: the engine then read the *default* of the column you meant to set, the
oracle silently tested the wrong fact pattern, and the result looked exactly
like an engine defect. That produced one false-positive finding
(`cp_is_equivalent_jurisdiction` reported as inert — it works correctly; the
alias for it was simply missing). `drivers.reject_unknown_columns` now rejects
any such input loudly, and ORC-130 to ORC-135 pin the real behaviour.

## Adding a new oracle

1. **Write the derivation.** Add a section to `ORACLE_DERIVATIONS.md` following
   the existing pattern: state the inputs, cite the article, show every
   intermediate value, and give the expected outputs.
2. **Reproduce it in code.** Add a record to the right module under
   `derivations/`, using only the standard library.
3. **Re-derive.** Run `uv run python tests/oracle/derive.py`. This regenerates
   `expected_values.json` with a fresh hash of the doc.
4. **Verify.** Run `uv run pytest tests/oracle -n 0`. The oracle is picked up by
   the parametrised sweep automatically; there is no per-oracle test function to
   write.
5. **Commit.** The doc, the derivation module and `expected_values.json` must
   land in the same commit.

If a value cannot be sourced from a document available here, say so rather than
reconstructing it: publish the figure and list the key in `unasserted` so the
test skips it and the gap stays visible.

## What this suite is NOT

- **Not a regression suite.** The existing acceptance tests under
  `tests/acceptance/{crr,basel31}/` already cover that role with broad
  scenario coverage and 1% tolerance. The oracle suite has narrow coverage
  and 1e-6 tolerance: it answers "is the math right?", not "does the
  pipeline still produce the same answer it produced last week?"
- **Not an integration test.** Each oracle bypasses hierarchy, classifier,
  and CRM by calling the relevant calculator's `calculate_branch` directly.
  This is deliberate: the oracle isolates regulatory math from pipeline
  plumbing.
- **Not exhaustive.** 132 exposures across phases O1, O2 and O4. Credit risk
  mitigation (O3), off-balance-sheet conversion factors and the entity-level
  output floor are out of scope — see the "Scope not yet covered" section of
  `ORACLE_DERIVATIONS.md`.

## Update protocol — the contract

`expected_values.json` may **only** be regenerated by running `derive.py`
after a corresponding update to `ORACLE_DERIVATIONS.md`. Specifically:

- You must not hand-edit `expected_values.json` to make a test pass.
- You must not regenerate `expected_values.json` from engine output.
- You must not bypass the hash check by editing the hash field directly.

The hash is the contract. If you find yourself wanting to break it, the
correct response is almost always "the engine has a bug" — that's the
oracle suite doing its job.

## Roadmap — phase O3 (credit risk mitigation)

The next phase, in priority order:

1. Financial collateral, financial collateral simple method (Art. 222 / 197).
2. Financial collateral comprehensive method: supervisory volatility
   adjustments (Art. 224), the `E* = max(0, E·(1+H_E) − C·(1−H_C−H_FX))`
   composition (Art. 223).
3. The Art. 233(3) 8% currency-mismatch haircut.
4. Guarantees under the risk-weight substitution method (Art. 235), including
   partial cover and the Art. 201 eligibility list.
5. F-IRB collateral LGD under Art. 230 (`LGD*`) and the multi-collateral
   Art. 231 composition — which also feeds the PS1/26 Art. 161(5)(b) and
   164(4)(c) variable LGD input floors.
6. Maturity mismatch adjustment (Art. 238).

Each of those exercises a distinct calculation pathway rather than another
variant of one already covered. Note that O3 needs a driver for the CRM stage:
the current `drivers.py` deliberately bypasses it.
