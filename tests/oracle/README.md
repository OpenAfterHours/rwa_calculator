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
| `drivers.py` | The only module here that imports `rwa_calc`. Supplies *inputs* to a calculator's `calculate_branch` — or, for phase O3, to the CRM stage and then the SA branch — and collects the row back. Derives nothing. |
| `test_oracle.py` | Pytest module. Compares engine output against the oracle within relative error 1e-6, asserts the doc-hash lock, and asserts the derivation modules never import the engine. |

### Layout of `derivations/`

| Module | Phase | Scope |
|---|---|---|
| `formulas.py` | — | Shared scalar arithmetic: correlations, maturity adjustment, conditional PD, supporting factors, band blends. |
| `record.py` | — | The oracle record shape. |
| `sa_crr.py` | O1 | Standardised Approach, UK CRR, every exposure class. |
| `sa_b31.py` | O1 | Standardised Approach, PRA PS1/26. |
| `irb.py` | O2 | Foundation and Advanced IRB, both regimes, including parameter floors. |
| `crm_sa.py` | O3 | Credit risk mitigation, SA side — Art. 222 / 223 / 224 / 233 / 235. CRR only. |
| `specialised.py` | O4 | Slotting and IRB equity. |

Phase O3 is **partially** covered: the Simple Method, the Comprehensive Method's
supervisory volatility adjustments, the currency-mismatch adjustment and the
guarantee substitution are in; F-IRB `LGD*`, maturity mismatch and the whole
Basel 3.1 side are not. See the roadmap below and the "Scope not yet covered"
section of `ORACLE_DERIVATIONS.md`.

## Running

```bash
uv run pytest tests/oracle -n 0
```

Pass `-n 0`. Phases O1, O2 and O4 are scalar arithmetic against direct calculator
calls; letting xdist spin up workers costs more than they do. Phase O3 runs the
CRM stage per oracle and dominates the runtime — the whole suite is around a
minute, most of it O3.

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

Phase O3 added two more mouths for the same trap, and the same protection —
`drivers._reject_unknown_frame_columns`, keyed on `CLASSIFIER_EXIT_EDGE.columns`
for the exposure and on the loader schema for the collateral and guarantee
frames. Both are live risks, not hypotheticals:

- The exposure frame is sealed with `seal_lenient`, whose last act is
  `lf.select(emitted)` over the columns the **edge** declares. A column the edge
  does not declare is projected away in silence. `residual_maturity_years` is one
  such column: the classifier-exit contract carries `maturity_date` and
  `effective_maturity` instead, so an oracle setting it would have been testing
  the null.
- The collateral frame's real maturity column is `maturity_date`. An existing
  helper under `tests/unit/crm/` declares `collateral_maturity_date` in its
  schema — a name `COLLATERAL_SCHEMA` does not contain — so that column has never
  done anything. The O3 driver rejects it rather than accepting it.

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
- **Not an integration test.** Phases O1, O2 and O4 bypass hierarchy, classifier
  and CRM by calling the relevant calculator's `calculate_branch` directly. This
  is deliberate: the oracle isolates regulatory math from pipeline plumbing.
  Phase O3 is the one exception — it runs the CRM stage and then the SA branch,
  because the CRM stage *is* what O3 tests. It still bypasses hierarchy and the
  classifier.
- **Not exhaustive.** 215 exposures across phases O1, O2, O3 and O4.
  Off-balance-sheet conversion factors and the entity-level output floor are out
  of scope, as are the O3 items listed in the roadmap below — see the "Scope not
  yet covered" section of `ORACLE_DERIVATIONS.md`.

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

1. ✅ **Financial collateral, simple method (Art. 222 / 197)** — ORC-244 to
   ORC-258, ORC-274 to ORC-281.
2. ✅ **Comprehensive method: supervisory volatility adjustments (Art. 224) and
   the `E* = max(0, E·(1+H_E) − C·(1−H_C−H_FX))` composition (Art. 223)** —
   ORC-200 to ORC-232, ORC-241 to ORC-243, ORC-282. The whole populated domain of
   Art. 224(1) Table 1 (excluding securitisations) and every row of Table 3, at
   all three Art. 224(2) liquidation periods. `H_E` is structurally zero for
   these fact patterns — Art. 223(3) applies it only where the exposure is itself
   a security — so the `(1+H_E)` limb is documented, not exercised.
3. ✅ **The Art. 233(3) 8% currency-mismatch haircut** — ORC-233, ORC-234,
   ORC-238, ORC-240 on the collateral side (where Art. 224(2) scales it) and
   ORC-259 / ORC-260 on the guarantee side (where Art. 233(4) fixes it at the
   10-day basis). The pair is what pins the difference.
4. ✅ **Guarantees under the risk-weight substitution method (Art. 235),
   including partial cover and the Art. 201 eligibility list** — ORC-259 to
   ORC-273: seven eligible provider limbs, two ineligible ones, the Art. 193(1)
   non-beneficial case, partial, full and excess cover.
5. ⬜ **F-IRB collateral LGD under Art. 230 (`LGD*`) and the multi-collateral
   Art. 231 composition** — which also feeds the PS1/26 Art. 161(5)(b) and
   164(4)(c) variable LGD input floors. Untouched: every O3 oracle is SA.
6. ⬜ **Maturity mismatch adjustment (Art. 237 / 238).** Untouched, and every O3
   oracle deliberately holds it *off* — see the note below.
7. ⬜ **The Basel 3.1 side of items 1–4.** Every O3 oracle is CRR. PS1/26 revises
   the Art. 224 tables (five maturity bands rather than three, and different gold
   and equity adjustments), so this is a distinct reading rather than a
   re-parametrisation.

### Two things to know before extending O3

**The CRM driver.** `drivers.run_crm_sa` runs `CRMProcessor` and then the SA
branch. `run_sa` delegates to it whenever an oracle supplies `collateral`,
`guarantees`, `guarantors`, `crm_method` or `exposure_maturity_years`, so O3
records stay on `approach: "SA"` and `test_oracle.py`'s dispatch table needs no
new key. Art. 235(1) splits a guaranteed exposure into two legs, so the driver
returns the **aggregate**: total `ead_final`, total RWA, and `risk_weight` as
their ratio, which is exactly the weight Art. 235(1) defines.

**Maturity mismatch will eat your haircut oracle.** Art. 238(1) caps the
underlying's effective maturity at five years and the engine assumes that cap
when the exposure carries no maturity, so a pledge maturing inside five years
silently picks up a `(t − 0.25)/(T − 0.25)` factor. Every O3 collateral oracle
sets `exposure_maturity_years = 0.25` to make that factor exactly 1.0. The first
draft of `crm_sa.py` omitted it and read a 42% "understatement" at CQS 1 that was
Art. 238 working correctly — the ratios matched `(3 − 0.25)/(5 − 0.25)` exactly,
which is how it was caught. Measure the ratio before believing a bond-collateral
disagreement.

### What phase O3 asserts, and what it only documents

`test_oracle.py::_COMPARISONS` has no CRM entries, so the CRM intermediates the
records publish (`collateral_volatility_adjusted_value_CVA`,
`collateralised_portion_risk_weight`, `protection_value_after_fx_G_star`, …) are
**not** compared — they are there so a failure can be read. What *is* asserted
covers the substance anyway:

- Under the Comprehensive Method the whole effect is in the exposure value, and
  `ead` → `ead_final` is asserted, so `E*` pins `H_C` and `H_fx` exactly. The
  `risk_weight = 1.50` assertion alongside it is the check that the benefit is
  taken once, on the exposure value, and not again on the weight.
- Under the Simple Method the whole effect is in the weight, and `risk_weight` is
  asserted, so the blended weight pins the collateral's own weight exactly. The
  `ead` assertion is the check that Art. 222 does **not** reduce EAD.
- For guarantees, `risk_weight` pins `G_A` and `g` jointly; the same-currency /
  EUR pair separates `H_fx` from `g`.

Adding `ead_post_crm`, `collateral_adjusted_value`, `fcsm_collateral_rw` and
`guaranteed_portion` to `_COMPARISONS` would make the intermediates binding as
well, and would make a failure name the CRM step rather than the outcome.
