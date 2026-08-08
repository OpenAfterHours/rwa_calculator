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

### B6. An (approach, class) pair with no row is invisible to every published rule

**Trap.** After a re-key, RWEA falls out of the breakdown rows while the parent
total still counts it. No rule objects, because rules only check rows that exist.

**Why.** Measured: moving C 02.00's IRB class key produced
`(foundation_irb, retail_other)` — Art. 151(4) makes retail A-IRB only — and
~2.0m (CRR) / 1.7m (B31) of RWEA vanished from rows 0250-0410.

**Detect.** After any class/approach re-key, sum the RWEA whose pair matches no
row builder and assert `0.00`. Do **not** verify by reading the row list — the
missing pair is by definition not in it.

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

### D2. Deleting a short-circuit changes the expression's column footprint

**Trap.** Removing a short-circuit and testing only the subdirectory you edited.

**Why.** P1.277 made `is_qrre_transactor` newly dereferenced, breaking 6 tests
in files no agent thought to run. Per-subdirectory verification structurally
cannot see this.

**Detect.** Run the **full** `tests/unit` after any change to a conditional
expression's structure.

### D3. Measure blast radius with the suite, not with grep

**Trap.** Estimating how many fixtures a new eligibility gate will zero out by
grepping for the field.

**Why.** The Art. 199 gate zeroed non-financial collateral in every fixture
lacking `is_eligible_irb_collateral=True` — 4 files, 38 tests, none obvious
from grep.

**Detect.** Run the full unit suite before reporting a gate's scope.

### D4. An edge-contract dtype violation reddens the whole acceptance suite

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
- **The ruff `--fix` PostToolUse hook strips a momentarily-unused import**
  between edits (and unquotes `Literal["x"]`). Add imports after the usage
  exists.
- **Background Bash tasks are hard-killed at ~600s.** The full suite must run as
  two **foreground** chunks: `tests/unit`, then
  `acceptance + integration + contracts + oracle`.
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

Candidates currently identified but not yet graduated (file as plan bullets):

- **B2** → a contract test asserting every class/row map's key set is a subset
  of `{m.value for m in ExposureClass}`, across all templates at once.
- **B5** → an `arch_check` rule (or contract test) asserting every reporting
  fixture portfolio module is referenced in `RUNS`.
- **G/fixtures** → an `arch_check` rule asserting every `tests/fixtures/*.py`
  builder is called from `generate_all.py`.
- **D1** → an `arch_check` rule flagging any new column read by an
  `engine/sa/` transform without a recorded output-floor impact note.
