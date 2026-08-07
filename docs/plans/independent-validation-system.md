# Independent Validation System

**Status:** proposed
**Author:** drafted 2026-08-07
**Problem:** too many defects reach the reporting templates — both wrong
calculator output (RWA, exposure class, approach) and correct output that the
templates fail to pull through.

---

## 1. Diagnosis — why a large green suite keeps shipping defects

The estate is not under-tested. It is **under-*independently*-tested**. Almost
every assertion in it is causally downstream of the code it checks, so it
detects *change* rather than *wrongness*.

### 1.1 The measurements

| Asset | Size | Independent of the engine? |
|---|---|---|
| `tests/unit`, `tests/acceptance`, … | ~10,500 tests | **No** — written from the same reading of the rule as the code |
| `tests/expected_outputs/{crr,basel31}` | 51 CRR scenarios | **No** — recorded engine output (stated in `tests/oracle/test_oracle.py` §docstring) |
| `tests/expected_outputs/reporting/**` | 293 golden frames | **No** — captured engine output |
| `scripts/arch_check.py` | 17 checks + 9 ratchets | Structural only — says nothing about numbers |
| `reporting/validations/` (EBA/BoE) | 741 CRR / 808 B31 rules | **Yes** — published, externally authored |
| `reporting/tieouts.py` | 5 ties, 6 recorded non-comparable | Partly — internal identities, curated |
| `tests/oracle/` | **3 exposures** | **Yes** — stdlib-only, hash-locked hand derivations |

**Three exposures.** `ORC-001` (SA corporate unrated), `ORC-002` (SA sovereign
CQS 2), `ORC-003` (F-IRB corporate). That is the entire independent numeric
oracle for a calculator spanning SA, F-IRB, A-IRB, slotting, equity, CRM, the
output floor, CCR and SFT, across two regimes.

Everything else answers "did the number change?", not "is the number right?".
A defect present when the baseline was captured is invisible forever.

### 1.2 The published rules are the strongest oracle — and they are mostly dark

From `tests/expected_outputs/reporting/validation_known_breaks.json`:

| Run | enforced | executed | of which VACUOUS | **binding** | binding % |
|---|---|---|---|---|---|
| `crr/rich` | 741 | 256 | 80 | 176 | **24%** |
| `b31/rich` | 808 | 415 | 219 | 196 | **24%** |
| `crr/off-bs` | 741 | 118 | 69 | 49 | 7% |
| `crr/irb-classes` | 741 | 109 | 25 | 84 | 11% |
| `b31/irb-classes` | 808 | 343 | 180 | 163 | 20% |

Roughly **three-quarters of the published rules never bind on any single run**,
and `check_supervisory_validations` **fails open** — an unreachable rule is
`NOT_EVALUATED`, which on the error channel is indistinguishable from a clean
estate. The register itself documents this (test docstring §(c)/(d)), and
`LESSONS.md` B5 records the consequence: four compounding C 07.00 defects lived
for the template's entire life because the golden portfolio was 100% drawn, so
the conversion-factor columns were never populated and the four rules written
over them were never evaluated.

**The binding constraint is portfolio reachability, not rule count.** Coverage
is currently raised by hand, reactively, one portfolio at a time.

### 1.3 No second opinion exists on the reporting side

`reporting/lineage.py` is explicit and correct about this: *"a cell's lineage IS
its spec"* — it re-runs the generator's own `RowPredicate` rather than declaring
a second copy. That is the right call for lineage (a divergent copy would
explain a number nobody reported), but it means **nothing anywhere re-derives a
cell independently of `cellspec.py`**.

So a wrong `CellSpec` — wrong carrier, wrong filter, wrong sign, wrong scope —
produces a number that is self-consistent, lineage-explicable, golden-matching
and rule-passing, and still wrong. That is exactly the "templates are not
pulling the calculation through correctly" failure mode. `LESSONS.md` B1/B2/E2
are three instances of it already paid for.

### 1.4 Classification has no oracle at all

"The reported exposure class is wrong" is checked only by tests written from the
same sentence as the classifier — `LESSONS.md` B3 is the general form
("a test that shares production's wrong assumption validates nothing") and B2
the worked example, where `C02_00_SA_CLASS_MAP` was keyed on invented strings
and its test used the same invented strings.

### 1.5 Absence dominates wrongness

`LESSONS.md` B4, stated flatly: *"the dominant production escape class in this
project is **absence**, not wrongness."* Nothing systematically asserts that a
cell which should carry money does.

### 1.6 Summary of root causes

| # | Root cause | Failure mode it produces |
|---|---|---|
| R1 | Expected values are recorded engine output | Wrong number baselined as correct, forever |
| R2 | Published-rule coverage ~24%, gate fails open | Whole template families unchecked |
| R3 | Coverage bounded by 6 hand-built portfolios | Dead columns hide self-concealing defects |
| R4 | No independent re-derivation of template cells | Wrong `CellSpec` is undetectable |
| R5 | No classification oracle | Wrong class/approach flows through silently |
| R6 | No presence contract | Null cells ship |
| R7 | No detection-rate measurement | No evidence any of this is improving |

---

## 2. Design principle

> **Every validation layer's source of truth must be causally independent of the
> code it validates** — a different author, a different derivation route, a
> different representation, or an external publisher.

Two corollaries, both of which the current estate violates in places:

- A baseline captured from the system under test is a **regression** gate, never
  a **correctness** gate. Both are worth having; they must never be confused.
- A gate that cannot fail is not coverage. Vacuous passes, `NOT_EVALUATED`
  rules, and structural identities (`r0090 = r0090`) must be reported
  separately from real passes — the register already does this for rules and
  the principle should extend estate-wide.

---

## 3. The system — six components

Ordered by value-per-unit-effort, not by build order.

### C1. Numeric change-impact report on every change *(smallest effort, largest immediate return)*

`scripts/parity_gate.py` already captures a full pipeline snapshot over the
deterministic 10k stress set across all four framework/permission configs and
diffs it to float-reassociation tolerance. It is used only for refactor phases
that are *meant* to move nothing.

**Generalise it into a standing report.** Every change touching `engine/` or
`reporting/` emits a diff against the previous commit, aggregated at four
grains:

1. total RWA per regime,
2. RWA by (approach, exposure class),
3. every generated template cell,
4. the error-code histogram.

Non-zero movement is not a failure — it is a **prompt that must be answered in
writing** before merge, in the same style as the golden preserve-or-fix
decisions. Unexplained movement blocks.

This alone would have caught the CRM double-count, the C 02.00 re-key
disappearance (`LESSONS.md` B6, ~2.0m RWEA), and the C 07.00 subtotal
double-count — all of which moved numbers that nobody was asked about.

- **Build:** ~2–3 days. The capture/compare harness exists; the work is the
  by-cell grain, the report format, and the CI wiring.
- **Owner:** `scripts/parity_gate.py` → `scripts/impact_report.py`.

### C2. Property and invariant suite *(no second implementation required)*

Regulation-derived properties that must hold for **any** portfolio. These find
wrongness without anyone deriving an expected value.

**Structural / conservation**

- No `NaN`/`Inf` in any output column, at every sealed edge. (The `AGG001`
  incident had non-finite inputs spread portfolio-wide through the B31 floor.)
- Σ EAD at ledger seal == Σ EAD at aggregator exit == Σ EAD in each template's
  in-scope population, or the difference is explicitly attributed.
- Every leg lands in exactly one row of each template's row axis; Σ(unmapped) ==
  `0.00`. **This is `LESSONS.md` B6 as an executable check** and generalises it
  beyond class/approach re-keys.
- `0 ≤ RW ≤ 1250%` with an explicit allowlist of recorded exceptions.

**Monotonicity** (each an independent statement of regulatory intent)

- RWA is non-decreasing in EAD, PD, LGD, maturity.
- RWA is non-increasing in eligible collateral value and in guarantee amount.
- Substituting a guarantor with a strictly lower RW cannot increase RWA.

**Homogeneity**

- Scaling every EAD by *k* scales total RWA by *k* — except where a threshold
  binds (SME supporting factor cap, retail granularity, large-exposure
  thresholds). Those exceptions are themselves worth asserting explicitly,
  because each is a regulatory discontinuity that should be deliberate.

**Identities**

- B3.1: `rwa_final ≥ 0.725 × SA-equivalent RWA` on every run. Cheap, and it
  directly guards the `engine/sa/` → output-floor coupling that `LESSONS.md` D1
  warns is the most misjudged blast radius in the codebase.
- `rwa_final` is post-floor — assert it is never re-floored or re-added
  downstream.

Drive these with Hypothesis over generated portfolios, seeded deterministically,
with the failing portfolio auto-minimised and written to `tests/fixtures/`.

- **Build:** ~1–2 weeks for the first 20 properties.
- **Why it is high value:** it is the only layer that scales coverage
  *automatically* — it explores portfolios nobody thought to build, which is
  root cause R3.

### C3. Extended independent oracle — the shadow calculator

Grow `tests/oracle/` from 3 exposures to a **scalar reference implementation**
of the full calculation.

Design constraints, all inherited from what already works in `derive.py`:

- **stdlib only** — `math`, `statistics`, `decimal`. Never imports `rwa_calc`.
  Enforce with a new `arch_check` rule so it cannot rot.
- **Row-at-a-time, deliberately naive.** Readability over speed; ~500–1,000
  rows, not 10k. If it is hard to read, it is not an oracle.
- **Hash-locked to `ORACLE_DERIVATIONS.md`**, as today — the mechanism that
  makes it impossible to silently re-pin oracle values to engine output.
- **Written from the article text, by a different pass than the engine change**
  (see C6).

Phase by coverage of the (approach × exposure class × regime) grid:

| Phase | Scope | Exposures |
|---|---|---|
| O1 | SA, every exposure class, both regimes | ~40 |
| O2 | F-IRB + A-IRB, corporate/retail/institution, incl. floors | ~30 |
| O3 | CRM — financial collateral, guarantees, FCCM haircuts, maturity mismatch | ~25 |
| O4 | Slotting, equity, output floor | ~15 |
| O5 | CCR / SFT EAD | ~20 |

Report per-exposure diffs with the driver attributed (RW vs EAD vs LGD vs
factor), not a bare assert — a diff report is triageable, an assert is not.

- **Build:** ~2–4 weeks per phase. Real, sustained cost.
- **Honest risk:** a second implementation can be wrong the same way as the
  first if one person writes both from one reading. C6 exists to prevent that.
  The derivations doc plus the hash lock is the mitigation that already works.

### C4. Classification and cell-mapping conformance *(root causes R4, R5)*

Two decision tables, authored **outside** the code they check.

**C4a — Classification decision table.** A CSV/TOML of
(input attribute combination) → (expected exposure class, approach, treatment),
each row carrying its citation. Then:

- Generate the discriminating input space **combinatorially** and assert the
  classifier reproduces the table on every combination.
- **A combination with no verdict in the table is a hard failure**, not a
  silent default. This is what turns R5 from "we test what we thought of" into
  "we test the space".
- Key every class/row map on the enum and assert it — graduating `LESSONS.md`
  B2 from prose to a check, as the Graduation ledger already nominates.

**C4b — Independent cell re-derivation.** For each money cell in the priority
templates (C 02.00, C 07.00, C 08.01, OV1 first), a **second, separately
authored** predicate + metric sourced from the Annex II instruction text, held
in a data file rather than in `cellspec.py`. The gate asserts the two agree on
every run.

This is the second opinion that does not exist today. It deliberately
duplicates `cellspec.py` — the duplication *is* the control. Scope it to money
cells to keep the maintenance burden bounded; structural and derived cells stay
covered by the tie-outs and the published rules.

- **Build:** C4a ~1 week; C4b ~3–4 weeks for the four priority templates.

### C5. Coverage as a ratcheted, first-class metric *(root causes R2, R3, R6)*

The register fails open, so coverage must be **measured and ratcheted upward**,
never assumed. Four new metrics in `arch_metrics.json`:

| Metric | Definition | Direction |
|---|---|---|
| `union_binding_rules_crr` / `_b31` | distinct rules reaching PASS or FAIL in **at least one** run — vacuous excluded | may not decrease |
| `template_cell_liveness` | fraction of declared cells non-null in at least one run | may not decrease |
| `regulatory_branch_coverage` | fraction of `when/then` branches in RW/CRM/IRB expressions ever taken | may not decrease |
| `dead_cells` | cells never non-null anywhere | may not increase |

Two things follow:

- **The union metric is the honest headline.** Today the summary is per-run, so
  nobody can see the estate-wide figure — and the estate-wide figure is the one
  that says whether the six-portfolio matrix is adequate.
- **A dead cell is a work item, not a curiosity.** Either the portfolio matrix
  is deficient or the cell is broken; both need to be visible. Pair this with a
  **coverage-driven fixture synthesiser** that proposes the minimal portfolio
  perturbation to light a dark cell, so raising coverage stops being purely
  manual.

Also graduate the two `LESSONS.md` nominations that bear directly on this:
an `arch_check` rule that every reporting fixture portfolio module is
referenced in `RUNS` (B5), and that every `tests/fixtures/*.py` builder is
called from `generate_all.py`.

- **Build:** ~1 week for the metrics and ratchets; the synthesiser is a
  follow-on.

### C6. Defect-injection scorecard — *how we know any of this works* (root cause R7)

Everything above is a hypothesis about what would have been caught. **Measure
it.** Build a harness that injects known-realistic defects into `engine/` and
`reporting/` and records, for each, whether the system caught it and **at which
layer**.

The mutant catalogue is not invented — it is already written down:

- **Every entry in `docs/development/escape-log.md`** becomes an injectable
  mutant. A defect that escaped once must never escape again silently.
- **Every `LESSONS.md` trap** with a mechanical form: presence guard on a wrong
  carrier name (B1), unmatched dict key (B2), an (approach, class) pair with no
  row (B6), the subtotal double-count (E3), summing hierarchical PD bands (E4).
- **Generic mutations**: perturb a risk weight by one band, flip a comparison
  operator, drop a `.cast`, swap a carrier for its plausible twin, null a
  column.

The output is a single number — **detection rate** — plus the layer that caught
each one and the mean layers-deep. That converts "we have 10,500 tests" into
"we catch 87% of realistic defects, and here are the 13% we do not".

Target: **≥ 90% detection on the escape-log-derived mutants** (these have
already escaped once; failing to catch them is inexcusable), and a published,
tracked figure on the generic set.

- **Build:** ~2 weeks. Run nightly or weekly, not per-commit.
- **This should be built early** — it is what tells you whether C1–C5 are worth
  their cost, and it is the only component that produces evidence rather than
  belief.

---

## 4. Phasing

**Phase 0 — evidence (2–3 weeks).** C6 skeleton with the escape-log mutants +
C1 impact report. Establishes the baseline detection rate *before* any new
validation is built, so every later phase can be scored against it.

**Phase 1 — cheap breadth (3–4 weeks).** C2 properties (first 20) + C5 metrics
and ratchets + the two `LESSONS.md` graduations. No second implementation
needed; largest coverage gain per line of code.

**Phase 2 — the reporting second opinion (4–6 weeks).** C4b for C 02.00,
C 07.00, C 08.01, OV1 + C4a classification table + the presence contract.
Directly attacks "templates not pulling through".

**Phase 3 — the shadow calculator (ongoing, 3–5 months).** C3 phases O1–O5,
one per batch, each scored on the C6 scorecard.

**Phase 4 — automation.** Coverage-driven fixture synthesis; mutant catalogue
extended from every new escape automatically by `/postmortem`.

Phases 1 and 2 can run in parallel — they touch disjoint files.

---

## 5. Process controls

Code alone will not fix this; the escape classes in `escape-log.md` are
predominantly process.

- **Dual authorship.** The oracle (C3), the decision tables (C4) and the engine
  change they validate may not be authored in the same pass. In `/next-items`
  terms: the oracle/table update is a separate wave with its own agent, which
  must not read the implementation diff. This is the control that prevents
  "two implementations, one wrong reading".
- **Unexplained movement blocks.** C1's report is a merge gate: every moved
  number carries a recorded preserve-or-fix decision, exactly as the reporting
  goldens already require.
- **Every escape becomes a mutant.** `/postmortem` gains a mandatory step:
  append the defect to the C6 catalogue. This is the existing learning loop
  extended from prose and checks into *measured* detection.
- **Never regen to green** — already `LESSONS.md` E1; C1 makes violations
  visible because a bulk regen shows up as unexplained movement across
  hundreds of cells at once.

---

## 6. Costs, risks and what this does *not* fix

| Risk | Mitigation |
|---|---|
| A second implementation doubles maintenance | Scope C3 to ~130 exposures, not the whole portfolio; scalar and readable; only re-derived when the rule changes |
| Both implementations wrong the same way | Dual authorship (§5); derivations doc + hash lock; verbatim article text pasted by the orchestrator (`LESSONS.md` A2) |
| Property tests produce unreproducible failures | Deterministic seeds; auto-minimise and commit the failing portfolio as a fixture |
| C4b duplication drifts from `cellspec.py` | Drift **is the signal** — the gate fires. Bound the burden by covering money cells only |
| Coverage ratchets become a merge tax | Ratchets are directional, not absolute; a justified scope-down is a recorded decision, as with the existing nine |
| More gates → slower CI | C6 nightly; C3 on `tests/oracle` (fast, scalar); C1 on the existing stress capture |

**Not fixed by this plan:** a wrong reading of the regulation that *both* the
engine and the oracle share, where no published rule binds. That residual is
irreducible without an external benchmark — the honest mitigations are the
premise-auditor wave, verbatim PDF text, and the published EBA/BoE rules. It is
also the argument for eventually validating against an independent third-party
calculation on a reference portfolio, which is out of scope here but worth
recording as the ceiling of what internal validation can achieve.

---

## 7. Recommendation — where to start

**Start with C6 + C1, in that order.**

- **C6 first** because right now there is no way to tell whether the estate's
  detection rate is 40% or 90%, and therefore no way to prioritise. Building it
  against the escape log costs ~2 weeks and immediately produces a ranked list
  of which defect classes actually get through — which should then reorder
  everything below it in this document.
- **C1 second** because it is ~2–3 days on an existing harness and it closes
  the single largest hole in the workflow: numbers move today without anyone
  being required to explain why.

Both are pure additions — no engine change, no risk to output, no regen. If
only one thing in this plan is built, build C6, because it is the component
that tells you what to build next.

---

## References

- `.claude/LESSONS.md` — B1–B6 (silent failure), C1–C6 (test validity), E1–E4
- `docs/development/escape-log.md` — the seven escape classes and their gates
- `tests/oracle/` — the existing independent oracle and its hash-lock design
- `tests/acceptance/reporting/test_supervisory_validations.py` — the two-way
  ratchet and the fail-open analysis
- `src/rwa_calc/reporting/tieouts.py` — cross-template identities and the
  recorded non-comparable pairs
- `src/rwa_calc/reporting/lineage.py` — why lineage reuses the generator's spec
- `scripts/parity_gate.py` — the capture/compare harness C1 generalises
