# LESSONS — traps this project has already paid for

**Every agent reads this file before starting work.** It is the working set of
mistakes that have reached production or cost a batch, written so you can
*detect* them, not just nod at them.

> **Tracked in git since 2026-08-08, and that is load-bearing.** This file was
> untracked for its whole life, so it existed only in the main checkout. A git
> worktree materialises tracked files only — which meant that every agent
> dispatched by `/next-items` into `.claude/worktrees/<item>/`, and every agent
> in the independent-validation batch, was told "read `.claude/LESSONS.md`
> first" and got *file does not exist*. The accumulated trap knowledge was
> invisible to precisely the agents it was written for. If you move or rename
> this file, keep it tracked.

This is **not an archive**. An entry earns its place only while it is still
prose. The moment a lesson can be expressed as a check — an `arch_check.py`
rule, a ratchet entry, a contract test — it graduates out of this file and
into the gate, leaving one line in the Graduation ledger at the bottom. If
this file grows past ~30 entries, the retro is failing to graduate things.

Format: **Trap** (what goes wrong) → **Why** (the mechanism) → **Detect** (the
concrete thing you run or grep).

---

## A. Premise and regulatory sourcing

### A1. Assume the plan bullet is wrong until you have checked it

**Trap.** A bullet in `IMPLEMENTATION_PLAN.md` states a gap that does not
exist, or states a real gap with the wrong rule, wrong direction, or wrong
scope. The whole pipeline then implements the wrong thing, greenly.

**Why.** Bullets are written by an auditing pass that reads code and
regulation separately and joins them by inference. Measured rates: **6 of 10**
bullets materially wrong (batch 20260724), **10 of 10** (batch 20260724b). Two
prescribed fixes in that second batch were actively *unsafe* — one would have
under-capitalised defaulted real estate, one would have applied a provision
PS1/26 never deleted.

**Detect.** Wave 0 exists for this. Before designing anything, try to *refute*
the bullet: quote the article verbatim from the PDF, then read the cited code.
Report `PREMISE: refuted` as a success, not a failure. Specific tells:

- The bullet says "flat X%" or "uniform" about a rule that has a cap, a blend,
  or a secured/unsecured split.
- The bullet names a field as missing when a default already exists (an
  unrated sovereign is not "missing" — Art. 114(1) defines it at 100%).
- The bullet's `Ev:` pointer has drifted; the underlying audit entry in
  `docs/plans/compliance-audit-crr-111-241-rectification.md` §5 usually
  preserves information the bullet lost. Read both.

### A2. Read the PDFs with pymupdf — never reconstruct an article from memory

**Trap.** An agent "confirms a citation" by reconstructing the article from
model memory, in confident language, and is wrong.

**Why.** The `Read` TOOL fails on `docs/assets/*.pdf` — it shells out to
`pdftoppm`, which is not installed. An agent that stops there silently falls
back to in-repo transcriptions (`docs/specifications/`) and to training data.
Both have been observed wrong.

**Corrected 2026-08-08.** This entry used to say sub-agents *cannot* read the
PDFs and that only the orchestrator could paste text in. That is false, and it
was costing accuracy — it sent agents to the transcriptions on purpose. The
limitation is the `Read` tool, not the agent: **pymupdf via Bash works for
anyone.** The C3 oracle build sourced all 123 of its regulatory constants from
article text this way and found two real engine defects that the skill
transcriptions would not have settled.

**Detect.** Extract the text yourself:

```bash
uv run python -c "
import fitz  # pymupdf is installed; pypdf is not
doc = fitz.open(r'C:\Users\philm\PycharmProjects\rwa_calculator\docs\assets\crr.pdf')
print(doc[119].get_text())          # CRR Art. 121 + Table 5
"
```

Two mechanics that otherwise waste a cycle:

- `docs/assets/` is **gitignored**, so the PDFs are absent from every git
  worktree. Use an ABSOLUTE path into the main checkout.
- Search for the article rather than guessing the page: iterate
  `doc[i].get_text()` looking for `"Article 121"`, then read the `[Note:
  corresponds to Article NNN]` line (see A3) rather than the heading number.

**Mandatory whenever the change reduces RWA.** Quote the text you actually read
into the derivation note; do not paraphrase it.

### A3. PS1/26 renumbers, and its two "[Note: ...]" forms are not synonyms

**Trap.** Citing a PS1/26 article number as if it were the CRR number, or
treating a provision as deleted when it survives.

**Why.** In `ps126app1.pdf`, the `[Note: corresponds to Article NNN]` line is
the CRR mapping — the heading number is not. Separately, two notes appear:

- `[Note: Provision left blank]` = **deleted** under Basel 3.1.
- `[Note: Provision not in PRA Rulebook]` = **survives in CRR**, and PS1/26
  may still cross-reference it.

Art. 119 shows both in one article. P1.286 was refuted on exactly this:
Art. 119(5) is cross-referenced 7 times in PS1/26. Known survivors: 114(7),
115(4), 116(5), 119(5), 119(6). Known deleted: 116(4), 119(2)/(3)/(4).

**Detect.** Read the `[Note: ...]` line, never the heading number. Grep the
whole PDF for the article before declaring it deleted. Also confirm the
enclosing `Article NNN` heading — the same CIU ×1.2 multiplier text appears at
Art. 132(4) (SA) and Art. 152(8) (IRB) with near-identical wording, so
grepping the rule text alone lands on the wrong article.

**Note.** `docs/assets/` has **no** PRA Credit Risk Mitigation Part, so any
PS1/26-side CRM citation rests on text nobody here can read. Say so rather
than implying verification.

---

### A4. The rulepack is the source of truth for every regulatory value

**Trap.** An agent takes a risk weight, floor or threshold from a skill file, a
spec page, or its own memory, designs a scenario around it, and the number is
not what the engine uses.

**Why.** Values had four homes — the pack, the skills, the spec pages and model
memory — and only one of them is what `resolve(regime, date)` actually returns.
Measured: corporate CQS5 under Basel 3.1 was stated as **100%** in three skill
files against a pack, engine and PS1/26 Art. 122(2) Table 6 value of **150%**;
the QRRE limit was stated as GBP 100k against a pack value of GBP 90k; and an
earlier CRR institution CQS 2 hint (30%, the Basel 3.1 ECRA value, not the CRR
50%) **seeded a wrong scalar into the P8.20 fixture** before a reviewer caught
it. Three instances, one of which reached a fixture.

**Detect.** Never read a value out of prose. In order of preference:

1. The generated table in the skill reference file — inside
   `<!-- BEGIN/END GENERATED -->`, rendered from the pack with its citation.
2. `rg '<entry_name>' src/rwa_calc/rulebook/packs/` for the cited source.
3. `docs/data-model/regulatory-tables.md` for every entry, both regimes.

If a PDF and the pack disagree, the finding is against the **pack** — fix it
there and regenerate, never patch the prose. Note that the skill files can no
longer carry a stale value (see the Graduation ledger), but **spec pages under
`docs/specifications/` are still hand-written** and remain a drift risk.

## B. Silent failure and negative space

### B1. A presence guard on a wrong column name fails silently, forever

**Trap.** `if "col" in cols:` where `col` is a name no pipeline run produces.
The cell publishes nothing, on every submission, and nothing raises.

**Why.** Measured on COREP C 07.00 cols 0160-0190: the code bucketed on
`ccf_applied`, a name that exists only in `data/schemas.py` and on synthetic
unit frames — the sealed aggregator exit carries `ccf`. Those columns published
nothing for the template's entire life.

**Detect.** Use a named carrier ladder (`_CCF_CARRIERS = ("ccf", "ccf_applied")`
via `pick()`), and log a WARNING when it resolves to nothing *and there is data
it should have described*. Gate the warning on "is there anything to report?"
so it stays quiet on legitimately empty frames.

**And the mirror image: NULL and ABSENT are different code paths, and both
occur on the same side at once.** A presence guard that *is* correct can still
be untested, because your fixtures always take one of its branches. Measured on
`return_recon._key_rungs` (2026-08-30): the membership legs carry
`source_exposure_reference` as a typed **null** (`MEMBERSHIP_SCHEMA`), while the
projected legacy plan frame **lacks the column outright** — the projection emits
only the join key, the mapped components and the mapped carriers. Deleting the
presence filter raises `ColumnNotFoundError` on every real reconciliation, and
the whole suite stayed green, because every fixture pinned the column into
`schema_overrides` as a typed null and `_Leg.row` always writes it. **A fixture
that pins a column into `schema_overrides` cannot reproduce an absent-column
production path**; build one frame that genuinely omits the column.

### B2. The same failure in mapping form: an unmatched dict key zero-fills

**Trap.** A class→row map keyed on strings that are not enum members. Unmatched
classes vanish from the breakdown while the independently-computed parent row
still counts them — so the template looks internally plausible.

**Why.** `C02_00_SA_CLASS_MAP` was keyed on invented strings (`central_government`,
`retail`) against a sealed carrier holding real `ExposureClass` values
(`central_govt_central_bank`, `retail_mortgage`).

**Detect.** Key every class/row map on the enum, and **assert that in a test**:
`{m.value for m in ExposureClass}`. Never assert against a hand-written list.

### B3. A test that shares production's wrong assumption validates nothing

**Trap.** The phantom map above passed `test_sa_class_map_covers_major_classes`
— because the test fixture used the *same* invented class strings.

**Detect.** Anchor assertions to a source of truth that cannot drift with the
code under test: the enum, the sibling template's sheet map,
`validations/scope.py::SHEET_INDEX_MAPS`. If your test and your code were
written from the same sentence, the test proves nothing.

### B4. Assert what should be there, not only what is

**Trap.** Tests assert the values of cells that exist. Nothing asserts that a
sheet was emitted, or that a cell expected to carry money is non-null. The
dominant production escape class in this project is **absence**, not wrongness.

**Detect.** Every reporting test asserts (a) the sheet/template is emitted, and
(b) the cells in scope are non-null where the portfolio has exposure. Note that
`sheet_not_emitted` conflates "no exposure" (fixable) with "no bundle key" (not)
— distinguish them explicitly.

### B5. A "cosmetic" coverage gap is a hiding place for a self-concealing defect

**Trap.** Deprioritising a coverage gap because "there's no defect there" —
when the absence of a defect report *is caused by* the absence of coverage.

**Why.** Four compounding C 07.00 defects were invisible because the golden
portfolio was 100% drawn loans, so no data ever flowed through the off-balance
sheet columns. The supervisory rules that would have caught them
(`boe_b0471`, `v6364_m`, `v1659_m`, `v1661_m`) were never evaluated. The circle
only broke when `reporting_offbs_portfolio.py` was built as a nice-to-have.

**Detect.** Any new fixture that exercises a previously-dead column **must** be
added to `RUNS` in `tests/acceptance/reporting/test_supervisory_validations.py`.
The gate fails open — an unread bundle makes every rule NOT_EVALUATED, which is
indistinguishable from a clean estate.

**⚠ RECURRED 2026-08-08 (batch 20260808-1624), in a form `RUNS` registration does
not catch.** The portfolio *was* registered; the **cell** was dead. C 08.01
r0253 held `0.00` in all six golden portfolios, so `tests/acceptance/reporting`
ran fully green under a simulated fix and the mandatory Tier 2 gate was
structurally incapable of seeing a change to that column. Closing it took a
**two-leg** fixture — a live cell that *survives* the change plus one that
*moves* — because a single moving row leaves the cell at `0.00` afterwards, and
a test that cannot tell "the fix worked" from "the fix zeroed the cell" is not a
test of the change. Result: five previously-`VACUOUS` rules activated to `PASS`,
including `boe_b0752_27`, the r0253 tie-out itself.

**This is the second production-class recurrence, so it graduates rather than
staying prose: the executable form is the `dead_cells` / `never_evaluated_rules`
ratchet already specified in P5.21** (`scripts/coverage_report.py` computes both
today and gates on neither). Registration-in-`RUNS` is necessary and not
sufficient; the ratchet is what makes a dead *cell* fail. Until P5.21 lands, the
manual form is: before trusting a green Tier 2 on a reporting-adjacent change,
measure the cell you are changing across every golden portfolio and confirm it
is non-zero somewhere.

### B6. An (approach, class) pair with no row is invisible to every published rule

**Trap.** After a re-key, RWEA falls out of the breakdown rows while the parent
total still counts it. No rule objects, because rules only check rows that exist.

**Why.** Measured: moving C 02.00's IRB class key produced
`(foundation_irb, retail_other)` — Art. 151(4) makes retail A-IRB only — and
~2.0m (CRR) / 1.7m (B31) of RWEA vanished from rows 0250-0410.

**Detect.** After any class/approach re-key, sum the RWEA whose pair matches no
row builder and assert `0.00`. Do **not** verify by reading the row list — the
missing pair is by definition not in it.

### B7. A parked finding with no owner has only aged, not been handled

**Trap.** *Graduated 2026-08-12 — see the ledger. Only the ungated residual
survives here.* Registering an oracle or conformance disagreement is the right
immediate move and is now mechanically constrained: the population can only
shrink, and every entry must carry an `OWNER: P<n>.<n>` token.

**Why the residual still needs a human.** No check gates **how long** an entry
may sit. Shrink-only stops the register growing and the owner token stops it
being anonymous, but an owned entry that no one works is indistinguishable from
one being worked. Seven of the eight oracle entries understate capital.

**Detect.** When you touch a register entry for any reason, check its owning
bullet is still open and still describes the disagreement. An `OWNER:` pointing
at a closed or drifted bullet is the review finding.

### B8. Ratchet the quantity you care about, not a ratio of it nor its complement

**Trap.** Gating on a coverage *ratio* (or on a "dead" complement) and reading it
as a floor. A ratio's denominator moves with its numerator, so it can improve while
the thing you care about shrinks.

**Why.** Measured on the reporting coverage ratchet: `template_cell_liveness_bp` is
`live / declared` and `dead_cells` is `declared − live`, so dropping N declared
cells of which K are live passes **both** whenever `K / N <= 0.1285`. Deleting the
`b31/rich` portfolio loses **689 live cells** while liveness *improves*
1285 -> 1374bp and dead cells *improve* 55,553 -> 47,123. Across 16 leave-one-out
runs the two cell metrics never caught a loss on their own, and on 4 of 16 they
reported an improvement while real coverage fell.

**Detect.** Ratchet the absolute accumulator — here `cells_live`, a union over runs
that cannot fall unless coverage genuinely falls. Keep the ratio as a *reported*
figure, and never write "may not fall" next to a ratio in a comment: every
reviewer who does not do the algebra will read it as a floor.

### B9. A log line is not a gate — and neither is an alarm that always fires

**Trap.** A hazard that the code *knows about* and reports at runtime, with
nothing asserting on it. Or an alarm that does fire, on everything, so its firing
carries no information.

**Why.** Both measured on `analysis/return_recon.py` (2026-08-30). The
`_group_legs` collapse hazard self-announced for the feature's whole life —
`row_migration` logs a WARNING reading *"the first is used and the matrix may be
wrong"* — and no test asserted the conservation identity the warning is about;
collapsing that key silently discards 40,000 of `rwa_final`. Separately, the
waterfall's `population_ours_only` / `population_theirs_only` terms fired on
**every** split exposure in the book — a guarantee, an RE split, a facility —
and produced **identical output** for (a) nothing wrong, (b) a leg moved to
another row, and (c) a leg genuinely lost. A saturated alarm is worse than a
silent one because it looks like coverage: the analyst who learns the scope
alarm always fires stops reading it, which disarms the one term that would have
pointed at scope on the day it fired legitimately.

**Detect.** For a logged hazard: the log line names the invariant — write the
assertion it implies, on a fixture that can violate it. For an alarm: **run it on
the case where nothing is wrong**, and on the case it exists to catch, and check
the two outputs differ. If they do not, the alarm has no discriminating power
however loud it is. This is the production-alarm form of the rule that a test
green in both states guards nothing (`/next-items` C1.11).

---

## C. Test validity

### C1. Defect-pinning tests are endemic — find them before you implement

**Trap.** A pre-existing test pins the *old, wrong* premise. It either blocks
your fix, or worse, passes anyway and hides that the fix did nothing.

**Why.** Five found in a single batch. Two passed after the fix because their
assertions were **relative to a baseline** (`rwa_override > rwa_default`), so a
48% RWA movement sailed through green.

**Detect.** Grep test names and docstrings for **"uniform"**, **"all classes"**,
**"flat"**, **"backward compat"**, **"ignored for"**, **"has no effect on"**
before implementing. Treat any relative assertion over an absolute one as
suspect.

### C2. A 0%-RW leg cannot verify a basis move

**Trap.** A cross-template tie-out passes with one side migrated and one side
not, because the only boundary-crossing leg carries 0% RW. Green means nothing.

**Why.** The `crm-substitution` portfolio's one IRB→SA crossing leg was
guaranteed by a domestic CGCB (Art. 114(4) 0% short-circuit). Re-pointing it to
a CQS2 institution made the crossing RWEA 2,450,000 (CRR) / 1,470,000 (B31) and
both ties broke by exactly that amount — then went green when both sides crossed.

**Detect.** Before trusting a substitution/basis test, **measure the crossing
amount**: filter `reporting_approach_origin` IRB and `reporting_approach ==
"standardised"`, sum `rwa_final`. If it is `0.00`, you do not have a test.

### C3. A green suite is not evidence — the validation register is

**Trap.** Concluding correctness from "10,552 tests green".

**Why.** On the CRM substitution block, a fully green 10k-test suite found
**none** of ten real defects; wiring the new portfolio into `RUNS` found three
in its first hour. On the C 07.00 CCF block, review found three defects the
suite could not.

**Detect.** For anything touching `reporting/`, the meaningful gate is
`tests/acceptance/reporting/` — the supervisory ratchet and the goldens — not
the unit count.

### C4. Rule counts mislead

**Trap.** Optimising the number of failing supervisory rules.

**Why.** Binding the approach rows scored *worse* (B3.1 18→21) — until you read
the four "new" breaks and find they are two duplicated identities jointly
pointing at the real root cause. Optimising the count would have buried it.

**Detect.** Read every changed rule outcome. Never report a delta alone.

### C5. A failing published rule is not always our defect

**Trap.** Contorting output to satisfy an unsatisfiable published rule.

**Why.** BoE summation templates do not distinguish additive from averaged
columns; one template is applied across ~36 columns of a family, so wherever it
lands on an exposure-weighted average (LGD, maturity, coverage %) the identity
is arithmetically unsatisfiable unless N == 1. Confirmed across three families.

**Detect.** Check whether a genuinely per-row column varies across the rows, and
look for float dust (`1672.9999999999995` vs `1673.0`) — a broadcast constant
produces neither. If both hold, record "limit of the published rule" and move on.
Also check the rule's home table before changing output: `.a`/`.b` DPM variants
are column partitions bound to one frame, so a failure can be an evaluation
artifact.

### C6. Enumerate a rule family by ID prefix, never by the members someone quoted

**Trap.** Building to the two rule members named in a brief.

**Why.** `boe_b0752_8`/`_9` were briefed as "the C 08.01 r0070 = sum(C 08.02)
tie-out". They are 4 of ~56 members — `boe_b0752_1..36` and `boe_b0814_01..21`
restate the same identity once per shared column, all live ERROR. Building to
the named two produced 5 new ERROR breaks the moment the parent moved.

**Detect.** Grep the register for the ID prefix and enumerate the whole family.

---

### C7. A conservation identity can be satisfied in one regime by an offsetting basis change

**Trap.** A conservation identity over a two-regime quantity is checked under one
regime only — or parametrised over both, seen to fail in one, and "fixed" until
both are green. It passes in the other regime not because the engine is correct
there, but because a regime-specific change of basis happens to cancel the error
exactly.

**Why.** Two measured instances from the RE loan-split carrier duplication
(2026-08-09), of two different kinds.

*Regime-dependent satisfaction, and the carrier that caused it.*
`reporting_crm_lgd_real_estate` was inherited whole onto both split legs. On a
four-exposure portfolio pledging 4,500,000 of property, CRR summed to
**7,500,000** — a 3,000,000 violation of `collateral <= pledged`. Basel 3.1
summed to **exactly 4,500,000** and the inequality HELD; the post-fix value is
**2,700,000**, so that green assertion had been concealing **1,800,000 of pure
duplication**. The decisive detail: the DUPLICATION was present in BOTH regimes —
the raw, regime-invariant `collateral_re_market_value` summed to 7,500,000 under
Basel 3.1 too. What differed was not the defect but the CARRIER:
`reporting_crm_lgd_*` reports a method-dependent basis, and the B31 adjusted
basis was small enough that doubling it landed on the pledge. **A basis-dependent
carrier can mask a defect that a basis-invariant carrier beside it exposes in
every regime.**

*Regime-dependent severity.* The sibling collapse defect (a carrier allocated
across legs but not summed when they collapse back) understated a 40,000 interest
parent by **23% under CRR and 47% under Basel 3.1** — the Art. 124F 55% cap
shrinks the secured leg, and `.first()` kept that smaller leg.

A Basel-3.1-only test would have concluded the collateral defect did not exist. A
both-regimes test whose author trusted the green half would have concluded the
same.

**Detect.** Mechanical, no judgement required:
- Any conservation identity over a carrier whose BASIS differs by regime — the
  `reporting_crm_lgd_*` family, anything resolved through `approach_applied`,
  anything the pack expresses as a regime `Feature` — must be parametrised over
  both regimes AND shown to fail in each regime SEPARATELY. One red across a
  both-regimes parametrisation proves one regime, not two.
- Where a quantity is available as both a raw, regime-invariant carrier and a
  basis-adjusted one, state the identity over the RAW carrier. The adjusted one
  can be satisfied by its own basis; the raw one cannot.
- An identity stated as an INEQUALITY that passes as an exact EQUALITY is an
  alarm, not a reassurance. `4,500,000 <= 4,500,000` on a path containing
  haircuts, caps and eligibility gates means something cancelled.
- If a regime CANNOT be made to fail, that is a FINDING, not a licence to drop it
  from the parametrisation. Record which regime could not be reddened and why,
  keep it parametrised, and treat the gap as owed coverage.
- Both instances were found by MEASUREMENT, not review. Print both sides per
  regime and read the numbers.

---

### C8. A measurement and the claim you attach to it are separate assertions

**Trap.** You measure something correctly, then state a consequence that does not
follow, in the same confident breath. The measurement survives review because it
is right; the consequence rides along unchecked.

**Why.** Five instances in one batch (2026-08-09), each time the *plausible*
reading:
- `interest` measured as understated 23.1% on the per-parent collapse ->
  claimed "a false reconciliation break". It is not a reconciliation component.
- A mutation probe reported a vacuity guard as not failing -> claimed "the guard
  is vacuous". The probe had applied a different mutation than the guard catches.
- `collateral_financial_value == 0.00` for a `bond` pledge -> claimed "the pledge
  contributes nothing, 1,500,000 dead in our own fixture". It receives the SAME
  relief as `government_bond` (-485,857.86); the working carrier is
  `collateral_adjusted_value`. **The direction of the whole finding was
  backwards.**
- "Nothing reads those carriers off the collapsed frame" -> `reconciliation.py`
  reads `explain_columns` and `input_columns`, not only `our_columns`. Five
  allocated columns were being read.
- A scenario reported "eight newly-live columns"; the census — the authoritative
  measure — said seven, and chasing the eighth found a registration defect.

The third would have shipped a plan item whose prescribed fix pointed the wrong
way. Note the fourth: the rule derived from the first three would have caught it,
and the error predates the drafting.

**Detect.**
- **Measure the noun in the claim.** If the sentence says EAD, RWA, a template
  cell, or a reconciliation break, measure EAD, RWA, that cell, or that
  comparison. This engine carries many near-synonymous money carriers —
  `collateral_financial_value` vs `_adjusted_value` vs `_cash_value` vs the
  `_market_value` twins vs `reporting_crm_lgd_*` — and reading the wrong one
  yields a plausible wrong answer every time.
- Before asserting a consequence for a named consumer, **enumerate the
  consumers** — grep the registry, the cellspec, the edge contract. "X is wrong,
  therefore Y breaks" needs Y's definition read, not assumed.
- When a probe reports a *negative*, suspect the probe first: a mutation that
  does not redden a test may be the wrong mutation rather than a dead assertion.
- Prefer a set diff to arithmetic on totals. Net +7 live / -7 dead is equally
  consistent with 8 gained and 1 lost; diff the id sets.

### C9. On a user report, reproduce the customer's input SHAPE before concluding the engine is correct

**Trap.** A user reports a wrong number. You build a test case from the
description, it produces the right answer, and you close the report as "engine
is correct — check your data".

**Why.** The estate's effective input domain is *the union of the shapes our
fixtures happen to have*, and every fixture starts from a valid portfolio built
by someone who knew the schema. A customer's shape differs in ways the
description never mentions: nested facilities, partial collateral links, an
absent optional file, an unusual entity mix, a column present but null
throughout, a reference that points nowhere. Reconstructing from prose
reproduces *your* mental model of their data, which is the thing under
suspicion. Two measured instances of the class this closes: the input contract
was unreachable from production for months while 48 green unit tests covered it
(2026-08-12 escape-log entry), and an uncastable value is still silently nulled
at the loader seal with no error raised at all — so "the pipeline reported
nothing" is not evidence the input was clean.

**Detect.** Standing policy on any user report: get the actual input, or a
structurally faithful anonymisation of it, and run it through
`PipelineOrchestrator` end to end **before** forming a view. Then:

- Read `result.errors` first, not the numbers. An empty error list on a report
  of a wrong number is itself suspicious given the above.
- Check the row survived: join input rows to output on
  `source_exposure_reference`, not `exposure_reference` (the RE-splitter turns
  one parent into `_sec`/`_res` children). A vanished row is neither a result
  nor an error.
- Check for silent nulling: compare the raw file's values against the sealed
  frame's. `conform_lenient` casts with `strict=False`, so a type-mismatched
  value becomes null and reports nothing.
- If the shape turns out to be one no fixture has, that is a
  `path-never-exercised` escape — register the portfolio in `RUNS`, do not just
  fix the number.

### C10. Careless about scope, not about facts

**Trap.** You verify a mechanism on **one** path and then write a sentence that
quantifies over **all** paths. Every individual fact in it is true. The sentence
is false, and because each fact checks out, re-reading it does not find the
error.

**Why.** Six instances in a single batch (2026-08-30), named by the agent that
committed four of them into one function's docstrings. *"The seal guarantees the
column"* — true of our frame, written about both sides, when the legacy plan
frame has no such column at all. *"The false branch is reachable only from a
hand-built `ResultsSource`"* — it is the branch **every real reconciliation**
takes. *"`dict.fromkeys` is what collapses the settings"* — a real effect
attributed to the nearest line rather than the one doing the work. Plus a
security guard's docstring claiming a scheme-relative URL could not reach it (it
could) and that it returns `""` for a non-same-origin input (it raises on a
malformed one).

**Detect.** Any docstring or design sentence containing an implicit **always**,
**only**, **never**, **both sides** or **every** is the thing to re-check, and
two questions clear it — *"which call site did I measure this on, and is there a
second one?"* and *"which line did I actually vary?"*. Three of the four
instances above fall to the first, the fourth to the second. This is C8's
neighbour: C8 is about the claim you attach to a measurement, C10 is about the
population you attach it to.

### C11. A fixture is a claim — assert its adequacy, and check its label against its cause

**Trap.** Two halves of trusting a fixture's description. (a) A test passes
because its fixture cannot express the condition under test, so it has been
vacuous since the day it was written. (b) A fixture whose docstring is right
about the *shape* and wrong about the *cause*, which hides the branch it actually
reaches.

**Why.** Both measured on `return_recon` (2026-08-30). For (a), the conservation
test for the `_group_legs` hazard is only meaningful if the group holds a split
exposure **and** the two legs carry different money — the pre-existing
`_combined` fixture fails the first of those, which is exactly why its sibling
test proved nothing for the life of the feature. For (b), `_recon_split` is documented
as a **real-estate** split, but RE legs share the obligor and therefore the PD,
so they would land in one band; the differing PDs it actually gives them are
natural only for a **guarantee** split. Read as "an RE split", two different
bands look like a fixture artefact nobody would assert on; read as "a two-leg
substitution", it is the ordinary case. The mislabelling is plausibly what left
the single-leaf rule unasserted.

**Detect.** Make the adequacy an assertion at the top of the test, with the
reason in the message — the shipped form is

```python
assert bases.count(_WHOLE_LOAN.reference) == 2, (
    "the group holds no split exposure - collapsing the key would "
    "be a no-op and this test would prove nothing"
)
assert _SPLIT_G_LEG.ead != _SPLIT_REM_LEG.ead, "equal legs make .first() undetectable"
```

and when you reuse someone else's fixture, derive its cause from the columns it
sets rather than from its docstring.

### C12. A green mutation probe is a claim that needs its own evidence — four ways one lies

**Trap.** You mutate production code, the suite stays green, and you conclude the
property is untested. Four distinct mechanisms produce that green, **the cheap
check that clears each one is different**, and doing the wrong check leaves you
confident. All four occurred in one batch (2026-08-30).

**Why / Detect** — one per mechanism, because they do not share a remedy:

1. **The output was mis-read.** The run was right, the reading was wrong — a
   harness parsed `FAILED` line prefixes while pytest was emitting ANSI colour,
   and reported 0 red for ten probes. *Check:* grep the **summary line** for
   `failed`, never the colour or the prefixes.
2. **The mutation never applied.** The harness thought it patched and did not
   (`x or None` on an object defining no `__bool__` returns `x`). *Check:* have
   the harness **print that it applied**, and assert the patched attribute is not
   the original object.
3. **The wrong code was measured.** The mutation landed in a file the interpreter
   never loaded — a mid-edit file in a shared tree, or `PYTHONPATH=.` in a
   worktree resolving `rwa_calc` to the main checkout. *Check:*
   `print(module.__file__)`, check mtimes, re-run on a quiet tree.
4. **The mutation is vacuous.** Everything worked and the mutated branch is
   unreachable from any fixture — one probe mutated empty-segment filtering while
   every key in the corpus was a bare single token with no separator, so mutant
   and original returned the same object on every call the suite makes. *Check:*
   **diff the mutant's output against the original's on the inputs the suite
   actually passes.** This is the one that separates *undetected* from
   *unreachable*, and no amount of staring at the diff will do it.

Red probes have their own failure mode — a mutation that reddens for the wrong
reason — recorded in the graduation ledger's 2026-08-29 row. Together the rule
is: **a probe owes you a demonstrated behaviour change before its colour means
anything, and the demonstration must be on a fixture the suite already runs, not
one you invent to make the point.** `tests/mutations/README.md` carries the
working plugins and the two rules for writing another.

---

## D. Blast radius

### D1. Every `engine/sa/` transform is an indirect IRB consumer

**Trap.** Concluding a change is safe because "only `engine/sa/` reads it, and
IRB rows never reach the SA branch".

**Why.** `engine/sa/calculator.py::calculate_unified` runs the risk-weight
pipeline **unconditionally** so every row carries an SA-equivalent RW for the
Basel 3.1 output floor. Most of those adjustments are benefit-only capped
(`min_horizontal(blended, risk_weight)`), so populating a carrier they consume
can only *lower* the SA-equivalent — lowering the output floor wherever it
binds. That makes the change **RWA-reducing and unshippable** without its own
review and output-floor regression evidence.

**Detect.** Grep for consumers, then ask *separately* whether the output-floor
path reaches them. Treat "no IRB code reads X" as almost always wrong.

### D2. Measure blast radius with the suite — not with grep, and not with the subdirectory you edited

*Merged 2026-08-30 from two entries with one remedy (old D2 + D3). Both traps
kept; nothing dropped.*

**Trap.** Two different errors, one instrument. (a) Estimating how many fixtures
a new eligibility gate will zero out by **grepping** for the field. (b) Removing
a short-circuit and testing only the **subdirectory** you edited.

**Why.** For (a), the Art. 199 gate zeroed non-financial collateral in every
fixture lacking `is_eligible_irb_collateral=True` — 4 files, 38 tests, none of
them obvious from grep. For (b), P1.277 made `is_qrre_transactor` newly
dereferenced and broke 6 tests in files no agent thought to run: **deleting a
short-circuit changes the expression's column footprint**, and per-subdirectory
verification structurally cannot see that.

**Detect.** Run the **full** `tests/unit` — before reporting a gate's scope, and
after any change to a conditional expression's structure.

### D3. An edge-contract dtype violation reddens the whole acceptance suite

**Trap.** Misattributing a wall of acceptance failures to another agent.

**Why.** `cp_sovereign_cqs` is `Int32` while `cqs` is `Int8`; any lift needs
`.cast(pl.Int8)`, and **no unit test can catch the omission** — only the sealed
`sa_branch` edge enforces it. Cost: 200 acceptance failures.

**Detect.** Check the bundle error list for `edge '…' contract violated` before
attributing a red suite to anyone.

---

## E. Reporting and goldens

### E1. Never bulk-regen goldens to green

**Trap.** `REGEN_REPORTING_GOLDENS=1` to clear a red gate.

**Why.** Regenerating banks a live defect as expected behaviour. `REGEN`
rewrites **all** goldens; `_capture_frames` deletes and rewrites every
`*.ndjson` in a regime directory, clobbering concurrent agents' frames.

**Detect.** Every moved golden cell carries a recorded preserve-or-fix decision
citing its sign-off. When agents share the tree, write a surgical regenerator
for your own `corep__<template>_*` frames only, and patch **both**
`manifest["frames"]` and `manifest["meta"]["corep"][<member>]` (the key list —
the golden test compares meta separately). Afterwards `git checkout` any file
whose `git diff` is empty but which shows modified: those are eol-only rewrites.

Same rule for the validation baseline: hold `REGEN_VALIDATION_BASELINE=1` until
fixes land, and never hand-edit the register. The ratchet failing *because you
fixed something* is the design working — remove the entry deliberately.

### E2. A breakdown cell must sum the carrier its parent total sums

**Trap.** Picking the plausible carrier for a breakdown column.

**Why.** Otherwise the footing identity can only hold by coincidence.

**Detect.** Trace what the parent row actually sums and match it. Verify; don't
infer from the column name.

### E3. Subtotal columns double-count if you subtract both the breakdown and the subtotal

**Trap.** C 07.00 col 0070 is the subtotal `0040 + 0050 + 0060`; col 0090 is
`0020 - 0035 - 0070 + 0080`. Subtracting the breakdown *and* the subtotal
double-counts. Inflow and outflow must bind the **same capped magnitude** —
reading the raw carrier on one side and the Annex II-capped twin on the other
*creates* exposure.

**Detect.** The register catches this if the portfolio reaches those columns.
See B5.

### E4. The PD scale is hierarchical

**Trap.** Summing all PD-band rows.

**Why.** C 08.03/05 and CR6/CR9 parent bands **overlap** and sum their children.
COREP under B3.1 is 18 rows (0015/0025 split at 0.05%); Pillar 3 stays 17. Band
labels live only in the template xlsx, not the instruction PDFs.

**Detect.** Never sum all rows; sum the leaves.

---

## F. Concurrency and shared-tree hygiene

### F1. Never `git add -A` while agents are running

**Trap.** It once swept a withdrawn design and a silent ratchet bump into a
docs commit. Shared-file staging races have cost two misattributed commits.

**Detect.** Stage explicit paths. Bar agents from `changelog.md`,
`citation-matrix.md`, `citation_snapshot.json`, and `arch_metrics.json` — the
orchestrator owns those.

### F2. The pre-commit gate goes red on any agent's mid-edit state

**Why.** `arch_check` + `ruff` run on the whole tree, so one agent mid-edit
blocks everyone's commit. Never `--no-verify`.

**Detect.** Commit between waves, or accept a queue.

### F3. Re-verify a suspected concurrency bug on a quiet tree

**Why.** A reported `group_by` race was really a teammate regenerating while
another landed a fix. A concurrent write has also silently dropped another
agent's import line, surfacing as a `NameError` elsewhere.

**Detect.** Before filing, re-run on a quiet tree. To prove a failure
pre-existing, use `git worktree add --detach HEAD` rather than `git stash -u`,
and run the checker from the venv binary rather than `uv run`.

---

## G. Tooling traps

- **Fixture parquets are generated.** `tests/fixtures/**/*.parquet` are
  git-ignored build artifacts. Edit the sibling `.py` builder and regenerate via
  `tests/fixtures/generate_all.py`. **A new fixture parquet must be registered in
  `generate_all.py`** or it works locally and fails on a fresh checkout.
- **New `@cites` need a citation-matrix snapshot regen *before* the suite** —
  `scripts/generate_citation_matrix.py`.
- **A SonarQube taint finding is a flow, not a line — fetch it before fixing.**
  The rule title names the sink family and says nothing about the source, and a
  sink can be reported for a tainted **argument** rather than a tainted path,
  which inverts the remedy. `pythonsecurity:S2083` on
  `generate_regulatory_tables.py` cost **two** failed fixes (`2b1be086` and its
  successor) designed from the title: both restructured the write *path*, while
  the reported flow was `_splice`'s `read_text` content reaching `write_text`'s
  *data* argument. Beware the plausible tell — an unflagged `read_text` beside a
  flagged `write_text` on the same loop variable looks like proof that provenance
  is the variable; it only means the read takes no tainted argument. **Detect:**
  SonarCloud uploads SARIF to GitHub code scanning, so the flow needs no
  SonarCloud credentials (which the sandbox cannot reach anyway):
  ```
  gh api "repos/OpenAfterHours/rwa_calculator/code-scanning/analyses?tool_name=SonarCloud&ref=refs/heads/master" --jq '.[0].id'
  gh api "repos/OpenAfterHours/rwa_calculator/code-scanning/analyses/<id>" -H "Accept: application/sarif+json"
  ```
  Read `.runs[].results[].codeFlows[].threadFlows[].locations[]` (each carries a
  `Source:`/`Sink:` message). Swap `ref=` for `pr=<n>` on a PR. Mint the token
  with `git credential fill` — see the `gh` auth note in memory.
- **The ruff `--fix` PostToolUse hook strips a momentarily-unused import**
  between edits (and unquotes `Literal["x"]`). Add imports after the usage
  exists.
- **Background Bash tasks are hard-killed at ~600s.** The full suite must run as
  two **foreground** chunks: `tests/unit`, then
  `acceptance + integration + contracts + oracle`.
- **Run `scripts/defect_injection.py` in the FOREGROUND only** — a campaign or
  even a `--reachability-only` probe. It restores mutated files through a
  `finally` and an `atexit` hook, and **SIGKILL runs neither**; a 22-mutant probe
  takes ~1,164s against the ~600s kill above, so the kill is the expected
  outcome, not an edge case. A killed run leaves a mutation applied in `src/` and
  every agent sharing the tree then measures a mutated engine without knowing it
  — measured 2026-08-09, three agents spent an hour mistrusting their own results
  before the stray mutation was traced. Chunk with `--mutants` / `--categories`
  if it will not fit one window. If a run vanishes, do **not** re-run it: check
  `git status` for a modified catalogue target and `git checkout --` it first.
  The harness's dirty-target refusal is the second line of defence, not the
  first. Note `git diff --stat` may show the whole file changed — the restore
  path normalises CRLF to LF — so check `git diff --ignore-cr-at-eol` too.
- **xdist workers crash transiently** ("node down"). Re-run before trusting red.
- **`uv sync` strips the dev extra** (ty, pytest, pytest-cov live in
  optional-dependencies). Use `uv sync --all-extras`.
- **LOC and fill-null ratchets bind.** `max_engine_module_loc` is a MAX over
  engine modules with near-zero headroom on the largest file — an item touching
  it fails on its first added line, so extract as you go.
  `engine_fill_null_sites` is tighter still; share predicates rather than
  duplicating a `fill_null` site. `max_reporting_test_file_loc` ratchets
  `tests/unit/reporting/**` — put new tests in a sibling file rather than
  squeezing comments out of the largest one.
- **`~` on an all-null Polars column raises.** `fill_null` before negating.
- **Never fill Float/String nulls to 0.0** — it is anti-conservative.
- **`rwa_final` is already post-floor.** Adding `floor_impact_rwa`
  double-counts.
- **Goldens are structure-exact + rtol 1e-9**, never byte-exact.
- **Test helpers that call weight functions directly bypass the input
  contract**, so a newly-read engine column must be added there too.
- **Head every new brief with "This is a NEW item. It is NOT `<previous>`"** —
  agents routinely misread a new assignment as a re-run.

---

## Graduation ledger

A lesson graduates when it becomes something that fails automatically. Record
the move here and delete the prose entry above.

| Date | Lesson | Graduated to |
|---|---|---|
| 2026-08-08 | Skill files restate rulepack values and drift (CQS5 100%→150% in 3 files; QRRE 100k vs pack 90k; CRR institution CQS2 30% vs 50%, which reached the P8.20 fixture) | `scripts/generate_regulatory_tables.py` now renders pack values into marked regions of the `basel31`/`crr` skill files, and `scripts/check_skill_values.py` bans percentages in skill prose outside those regions. Both gated by `tests/contracts/test_docs_freshness.py`. Prose entry A4 keeps only the *lookup order*, which no check can express. |
| 2026-08-08 | A guard set is complete against the wrong implementations the author imagined, but not against the variant the **repo's own sibling code** suggests (P1.316: a maturity-gated trade-finance exclusion copied from `risk_weights.py:1504` passed all ten guards and re-opened a 30pp understatement outside the guarded maturity band) | **Attack 8** in `.claude/agents/skeptic.md` — for every predicate a design adds, find the nearest sibling gating on the same column and check whether copying its shape passes every guard. A design that cites a sibling as precedent must pin its difference from that sibling. |
| 2026-08-08 | An oracle case can exhibit a disagreement production cannot reach, because `tests/oracle/drivers.py` bypasses hierarchy/classifier/CRM — and the plan then files it as a defect (P1.319 ORC-141: `commercial_mortgage` is SA-bound and never reaches the IRB branch) | **Attack 9** in `.claude/agents/skeptic.md` — probe production-reachability of any oracle-sourced claim by enumerating the population through the full `PipelineOrchestrator`, not by reasoning from the enum. |
| 2026-08-08 | A design can reach the right expression by an argument that is false, and a reviewer that fails it on the reasoning alone destroys correct work (P1.316 r2: two false narrative claims, correct prescription) | **Attack 10** in `.claude/agents/skeptic.md` — state which of prescription and justification is broken. `revise` is for a wrong prescription, or reasoning whose falsity would change what a later wave *does*. |
| 2026-08-08 | **B5 recurrence** — a registered portfolio can still leave the *cell* dead, so Tier 2 passes green over a change it cannot see (C 08.01 r0253 was `0.00` in all six goldens) | Pointed at **P5.21**'s `dead_cells` / `never_evaluated_rules` ratchet, which `scripts/coverage_report.py` already computes and gates on neither. B5's prose now carries the two-leg fixture pattern as the interim manual form. |
| 2026-08-09 | **B5 PARTIALLY GRADUATED, and recurred a THIRD time in a new form** | **Graduated:** `scripts/check_template_cell_coverage.py` + `scripts/template_cell_coverage_baseline.json` + `tests/contracts/test_template_cell_coverage.py` two-way ratchet the **(template, column)** live/dead sets over 28 portfolio×regime runs, 339 pairs / 210 live / 129 dead, each dead column classified `ENGINE_CANNOT_PRODUCE` (53) or `NO_FIXTURE` with a reason verified against generator source — reason codes deliberately exceed P5.21's spec, because a classified dead column is reviewable where a counted one is only tracked. Gated per-PR by the `template-coverage` job in `.github/workflows/ci.yml` (~5 min, invoking `--check` directly so the exit code is the gate's own). The census **fails loudly** — a raising portfolio, a silently-degraded one, and a short matrix are each a hard exit, all three demonstrated. **THIRD FORM FOUND:** the `fcsm` fixture was registered in `RUNS` against `_sa_config`, which defaults to `comprehensive`, while the portfolio exists to exercise the Art. 222 SIMPLE Method — so it sat inside the gate with its own feature silenced (col 0070 reads 0.00 vs non-zero on the identical bundle; the census showed 30→28 runs left 210/129 unchanged, i.e. it contributed no liveness). So B5 is now: "unregistered" → "registered, dead cell" → **"registered, WRONG CONFIG, dead cell"**. Registration is necessary; so is a live column; neither is sufficient if the config silences the feature. **STILL OPEN, narrowed to three:** (i) the **cell**-granular case (the C 08.01 r0253 shape); (ii) the **row**-granular case, which this ratchet is also blind to (C 08.04's single column is live while six of nine movement rows never carry a figure); (iii) `never_evaluated_rules`, the supervisory-register half. |

| 2026-08-12 | **The estate's dominant meta-pattern — build the instrument, stop before wiring it.** Fifth measured instance, three prior escape-log entries already classed `gate-not-run` for it: 10 of the 14 public validators in `contracts/validation.py` (402 lines, all carrying green unit tests) were unreachable from any production path, so a feed sending PD = 1.5 to mean "1.5%" returned an RWA understated by 99.95% silently | **`arch_check` check 20** (`scripts/arch_check.py::check_guard_reachability`) — every public function in `contracts/validation.py`, and every guard-*named* public function elsewhere under `contracts/`, must be transitively reachable from `src/`. Scoped by guard shape rather than module path, so a future `contracts/checks.py` is covered from the day it is written. `GUARD_REACHABILITY_ALLOWLIST` is empty by design and stale entries are themselves violations, so it can only be drained. `CONTRACTS_GUARD_SURFACE` pins the population so the check cannot be satisfied by *deleting* the guard it measures — and that pin is itself asserted by `tests/contracts/test_guard_reachability_gate.py`, because as first shipped it was an unasserted constant that one edit could empty. |
| 2026-08-12 | **A register of tolerated findings is a resting place, not a record.** 16 parked findings across two registers with no size gate at all and 0 of 16 naming an owner; 7 of the 8 oracle entries understate capital. `xfail(strict=True)` catches an entry that starts *agreeing*, so a silent fix was impossible — but nothing whatever constrained growth, and the population went 4 → 11 in one batch with every gate green | **`scripts/tolerated_findings.py`** — ONE shared set-diff + `OWNER: P<n>.<n>` grammar backing all four registers, gated by `scripts/check_parked_registers.py --check` against `scripts/parked_registers_baseline.json` and driven in-suite by `tests/contracts/test_parked_register_ratchet.py`. Additions are **shrink-only**: `--update-baseline` prunes and refreshes owners but refuses to add, so parking a new known-wrong number is a hand edit that appears in review. Removals stay free — a gate that reddens on a fix teaches people to stop fixing. Closes P5.41. |
| 2026-08-15 | **Attack 8 fired THREE times in one batch, and its third form is new: a design can ASSERT a guard it never checked.** P1.314 named two existing tests as "leak detectors" for a deliberate non-target; both passed under the correct code **and** the wrong code (neither set the field the limb keys on), and the branch they "guarded" turned out to be dead in both regimes. Plus the two ordinary forms: a sibling returning a *composite* expression (reusing it for the RGLA sites was RWA-reducing and invisible to the whole suite under B31) and a sibling dividing by `pl.len()` (copying it passed every leg but one). | **`C1.10` and `C1.11` in `/next-items` Step 4d.** C1.10 requires a proposal whose expression has an in-repo sibling to name it by file:line and state its difference. C1.11 requires every test called a "leak detector" / "must stay green" to come with the mutation it detects **and** evidence it FAILS under that mutation — a test green in both states guards nothing, and labelling it a detector is worse than none because it stops anyone looking. |
| 2026-08-15 | **`PYTHONPATH=.` in a worktree silently measures the MAIN tree.** The shared venv's `_editable_impl_rwa_calc.pth` puts the main checkout's `/src` on `sys.path`, so `PYTHONPATH=.` makes only `tests` importable while `import rwa_calc` resolves to the main checkout. The P1.314 implementer's first post-fix run came back a falsely **unchanged** "10 failed, 23 passed". Every worktree agent in every prior batch using that preamble measured code it had not changed. | **The `/next-items` worktree preamble** now mandates `PYTHONPATH=.:src` **and** a verification step (`print(m.__file__)` must show a worktree path), plus the note that `PYTHONPATH=.` is a free pre-fix baseline. The same section now documents committing inside a worktree, where the pre-commit gate's bare `uv run` creates an empty `.venv` in the worktree and fails on `No module named 'watchfire'`. |

| 2026-08-29 | **C1.11 recurrence, and the form that defeats it: a mutation that reddens can redden for the WRONG REASON.** Three instances in one batch. (i) A probe reported as 6-red evidence that a null-fill direction was guarded changed *two* things — the fill value AND a collapse of the leaf resolution; isolated to the fill alone it was **0 of 69 red**, so the cited guard guarded nothing. (ii) The re-pointed replacement failed the same way: "a strict parent row is never a placement" holds under both states, because dropping the filter sends legs to UNDECIDABLE rather than onto the parent — one unfalsifiable assertion swapped for another. The property that actually fails is **placement, not absence**. (iii) In the other direction, a docstring reading "NOT A DETECTOR ... leaves this green" was stale: the test HAD become a detector via a later assertion limb, and the prose invited deleting the call it protected. | **C1.11 is necessary and not sufficient.** A mutation must change **exactly one thing**, and a probe needs its *cause* checked whichever colour comes back — red for the wrong reason manufactures false confidence, and a probe that does NOT redden is evidence about the TEST, not only about the probe (both dead ends here were green probes their author refused to dismiss) — a confounded probe manufactures false confidence in the guard it cites. Two corollaries: name the specific tests that detect a property (verified red under the isolating mutation) rather than asserting "guarded here"; and a docstring that mis-states its own guard is a defect in EITHER direction — understating a working guard invites deleting what it protects, overstating a dead one stops anyone looking. Keep a confounded probe, renamed "CONFOUNDED — do not cite", so retracted evidence stays visible instead of vanishing. **And a reviewer must not reuse the author's mutation harness** — all three instances here were caught by the skeptic's own independently-written plugins and missed by the author's, because a confounded probe is confounded identically for whoever runs it. A relayed list of detectors is evidence to re-measure, not to transcribe: asked to name three, the author re-ran the isolating mutation and found seven parametrisations across FOUR tests — the fourth being the re-pointed test itself, which transcribing would have missed. |
| 2026-09-05 | **A nested Polars window goes quadratic in group count, and no correctness gate anywhere can see it.** P1.320 (`8ec7d302`) put a `cum_sum().over([cp, fac])` and a `max().over([cp, fac])` inside the INPUT of `.sum().over(cp)`; Polars re-evaluates a window's input once per outer group, so the classify stage went 495 ms -> 5,640 ms at 374k rows and shipped that way from v0.3.27 to v0.3.32 with every correctness gate green. Every fixture is under 40k rows, where the penalty is ~60 ms, and the CI `benchmarks` job recorded the 11x regression on every push while comparing it against nothing. | **`arch_check` check 21** (`check_no_nested_window_expressions`) — an AST scan banning any `.over()` in `engine/` whose input reaches another `.over()`, following local-name bindings and resolving each to the last binding ENDING STRICTLY BEFORE the outer window's line (without that rule `engine/supporting_factors.py`'s legitimate window flags itself). No allowlist. Plus **`tests/unit/classifier/test_p1_320_qrre_aggregate_scaling.py`**, an unmarked dev-loop scaling test asserting the 400k frame costs <8x the 100k one and <3 s, with adequacy assertions so it cannot time a dead path; and **`tests/contracts/test_nested_window_gate.py`**, which pins the check's registration, both flagged shapes, the two-step remedy and the `supporting_factors.py` false-positive shape. Graduated on the FIRST occurrence rather than the second, because the trap is mechanically checkable from the AST and prose would only have delayed the check. Full account: `docs/development/escape-log.md`, 2026-09-05. |

Candidates currently identified but not yet graduated (file as plan bullets):

> **The file is over the ~30 cap** — **35** numbered entries as of 2026-08-30,
> which by this file's own rule means the retro is failing to graduate things.
>
> A deletion pass on the stated criterion (*an entry earns its place only while
> it is still prose*) found **nothing to delete**: every entry whose executable
> form has landed was already trimmed to its ungated residual by an earlier retro
> — A4 keeps only the lookup order, B7 keeps only the missing expiry gate, and
> B5 is explicitly protected because neither ratchet can express its two-leg
> fixture pattern. Two of the standing candidates below were re-checked against
> the tree on 2026-08-30 and **neither has been built**: no contract test asserts
> any class/row map's key set against `ExposureClass` (B2), and nothing under
> `scripts/` or `tests/contracts/` gates fixture-builder registration
> (`generate_all`) — `test_ccr_fixture_builders.py` only names the script in an
> error message. So the overage is owed graduation work, not owed pruning, and
> the only reduction available without loss was merging old D2 and D3, which
> shared one remedy.
>
> **Draining the four *numbered* candidates below — C12, C11, B2, D1 — takes the
> file to 31.** C12 and C11 are the two added that day with an executable form
> already in hand, so start there. The other two candidates do not move the count:
> the `generate_all` rule would retire a bullet in section G, which is unnumbered,
> and B5's prose stays whatever happens to its ratchet.

- **C12** → a shared plugin base in `tests/mutations/`, so mechanisms 1–4 are
  structural rather than remembered. Prose has already failed at this once: the
  README's rule 2 was written from three false greens, and a fourth followed.
  Concretely, one `mutation.py` module next to the plugins exposing a single
  `apply(target, attr, replacement)` used from every plugin's `autouse` fixture,
  which does four things the plugin author currently has to remember:

  1. **Proves it patched.** Resolve `target` from `sys.modules` *after* import,
     capture `original = getattr(target, attr)`, and assert
     `getattr(target, attr) is not original` after `setattr`. Closes mechanism 2
     — the `x or None` no-op could not survive it, because the replacement would
     be the original object.
  2. **Proves it patched the code under test.** Assert
     `Path(target.__file__).is_relative_to(Path.cwd())`, and print it. Closes
     mechanism 3, including the `PYTHONPATH=.`-in-a-worktree form, which is
     already its own ledger row (2026-08-15) and recurred here anyway.
  3. **Proves the mutation is not vacuous.** Wrap both callables and record every
     `(args, original_result, mutant_result)` the session actually makes; at
     session teardown, fail if the two agreed on **every** call. Closes mechanism
     4, which is the only one that separates *undetected* from *unreachable* —
     and note it needs no new fixtures, because it observes the calls the suite
     already makes.
  4. **Reports its own colour.** Emit the plugin name, the applied-patch proof,
     the call count and the divergence count in a `pytest_terminal_summary` hook,
     so the evidence is read off pytest's summary rather than off a scraped
     transcript. Closes mechanism 1.

  Sizing and placement: it is ~60 lines and pure pytest, it belongs beside the
  plugins rather than under `tests/unit/`, and the five committed plugins are its
  first callers — porting them is the acceptance test, since each must keep the
  exact red set the README records. The base must be **fail-closed**: a plugin
  that cannot prove (1) or (2) errors the session rather than running green.
- **C11** → the adequacy assertion has a shipped form
  (`test_return_recon.py:1528`) but nothing requires one. The mechanical half is
  a reviewer criterion in `/next-items` Step 4d: a test whose fixture could make
  it a no-op must assert the property that stops it being one, in the same way
  C1.11 requires a named detector to come with the mutation it detects.
- **B2** → a contract test asserting every class/row map's key set is a subset
  of `{m.value for m in ExposureClass}`, across all templates at once.
- **B5** → an `arch_check` rule (or contract test) asserting every reporting
  fixture portfolio module is referenced in `RUNS`.
- **G/fixtures** → an `arch_check` rule asserting every `tests/fixtures/*.py`
  builder is called from `generate_all.py`.
- **D1** → an `arch_check` rule flagging any new column read by an
  `engine/sa/` transform without a recorded output-floor impact note.
