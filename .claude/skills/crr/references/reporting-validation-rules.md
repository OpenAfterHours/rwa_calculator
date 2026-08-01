# CRR Reporting Validation Rules (EBA)

The EBA publishes the **machine-readable validation rules** that supervisors run against a
submitted COREP return. They are the authoritative statement of which cross-cell, cross-sheet
and cross-template identities our generated templates must satisfy — far larger and more
specific than anything we assert in-house.

**Use this when:** implementing or changing a COREP template, debugging a template figure that
"looks wrong", or deciding whether two templates should tie out at all.

---

## Where the files live

| What | Path / command |
|------|----------------|
| Raw workbook (gitignored) | `docs/assets/eba-validation-rules.xlsx` |
| Refresh the raw workbook | `uv run python scripts/download_docs.py` |
| Committed extract (credit risk only) | `src/rwa_calc/reporting/validations/rules/crr-eba-v3.0-credit-risk.json` (package data — ships in the wheel) |
| Regenerate the extract | `uv run python scripts/extract_validation_rules.py` (`--check` to verify it is current) |
| Extract provenance / schema | `docs/reference/validation-rules/index.md` |
| Source URL | https://www.eba.europa.eu/sites/default/files/2026-06/12d2a6ae-9f58-47ab-a684-cdc9924ed4aa/%28up%20to%203.5%29%20EBA_validation_rules_2026-06-10.xlsx |
| Publisher landing page | https://www.eba.europa.eu/risk-and-data-analysis/reporting/reporting-frameworks |

The raw `.xlsx` is ~13 MB and gitignored — **read the committed JSON extract first**. Only open
the workbook when you need a rule the extract does not carry (e.g. a non-credit-risk template);
`uv run --with openpyxl python ...` with `load_workbook(..., read_only=True)` handles it in a
few seconds.

The extract is `{source, filter, rules}`; each rule carries `id`, `severity`, `type`, `status`,
`tables`, `rows` / `columns` / `sheets` (parsed scope) alongside `rows_scope` / `columns_scope` /
`sheets_scope` (raw), `formula`, `prerequisites` and the change-history fields.

## Which sheet to read

The workbook holds **19 sheets**, one per framework release (v2.0 through 3.5) plus an
`Explanation` sheet. Rules are re-numbered and re-scoped between releases, so reading the wrong
sheet gives rules for templates whose row/column numbering does not match ours.

> **Read sheet `v3.0(3.0.1)`** — the framework version matching current CRR reporting.

Each row is one rule. The load-bearing columns are `ID`, `Type`, `Severity`, `T1`…`T7` (the
tables the rule touches), `rows`, `columns`, `sheets` (the scope), `Formula`, plus
`Deactivated on` / `Reacti-vated on` / `Dele-ted` (liveness).

## Coverage of our estate

Counts below cover the rules on sheet `v3.0(3.0.1)` that touch the credit-risk templates we
generate (C 02.00, C 07.00.x, C 08.0x, C 09.0x, C 34.x). The extract carries all 1,011 matched
rules — deactivated and deleted ones included — each with a `status` marker.

> ### Do not filter on `status == ["live"]` alone
>
> It returns 588 and **silently discards 153 rules that are currently enforced**. The EBA workbook
> has a `Reactivated on` column: 220 in-scope rules were deactivated and later reactivated, but
> because they still carry a `Deactivated on` date the extract labels every one of them
> `deactivated`. 153 of those were never deleted, so they are in force today.
>
> Use `reactivated_on` alongside `status`, or take the extract's own
> **`filter.live_or_reactivated`** count.

**741 is the number of rules our CRR templates must satisfy today**, and it is the basis used
throughout this page.

| Basis | Count | Error | Warning |
|-------|-------|-------|---------|
| **Currently enforced** — live + reactivated, excluding deleted | **741** | **340** | **401** |
| `status == ["live"]` — what the field alone returns | 588 | 276 | 312 |
| Not deactivated, including not-in-XBRL | 605 | 292 | 313 |
| Rules matching a credit-risk template (everything in the extract) | 1,011 | — | — |

`v5745_q` (deactivated 2018-03-09, **reactivated 2018-04-17**) is one of the 153 — and it is the
EBA rule that the live BoE rule `boe_b0190` names as its equivalent. A reader filtering on
`status` would wrongly conclude that CRR dropped the identity.

Two smaller wrinkles in the 741:

- One of the 153, **`v0340_m`**, is reactivated *and* flagged `not_in_xbrl`. It is the entire
  difference between the extract's `live_or_reactivated: 741` and the 740 you get if you also
  require XBRL implementation. A `not_in_xbrl` rule is **published and substantively binding but
  not machine-enforced at submission** — it will not reject a return, so it ranks below an Error
  for us, but it is not dead. Counting every enforced rule regardless of XBRL gives 758.
- The 4 `Unique identifier` rules are all `not_in_xbrl`, so they appear on the 605 basis and not
  on the other two.

Rule mix on the 741 basis:

| Severity | Count | Type | Count |
|----------|-------|------|-------|
| Warning | 401 | Manual | 346 |
| Error | 340 | Identity | 161 |
| | | eQuivalence | 77 |
| | | Sign | 68 |
| | | Hierarchy | 65 |
| | | Nonexistence check | 19 |
| | | Allowed values for metric | 5 |

Which templates a rule reaches:

| Measure | Enforced (741) | `["live"]` (588) |
|---------|----------------|------------------|
| References **only** credit-risk templates | **686** | 537 |
| Of those, references only templates we generate **declaratively** (excludes C 34.x, still imperative) | **578** | 429 |
| Reaches outside the credit-risk estate — own funds (C 01.00 / C 03.00), C 04.00, large exposures | 55 | 51 |

The out-of-scope rules cannot be evaluated from our template bundle alone.

## Severity semantics

| Severity | Supervisory convention |
|----------|------------------------|
| **Error** | **Blocks the submission.** A return failing an Error rule is rejected — treat a break as a bug in our template, not a tolerance question. |
| **Warning** | Submission is accepted but the firm must **explain the break** to the supervisor. A Warning break is still a finding worth reporting. |

## Scope columns — how a rule expands

A rule's formula is a *template* and the `rows` / `columns` / `sheets` columns are its scope.
The formula is evaluated **once per member of the scope**, substituting the free axis.

| Formula shape | Scope column used | Expansion |
|---------------|-------------------|-----------|
| `{c0090} = {c0050} + …` (columns named, row free) | `rows` = `(0010;0020;…)` | once per listed **row** |
| `{r0490} = +{r0500} + {r0510}` (rows named, column free) | `columns` = `(0010)` | once per listed **column** |
| `{C 07.00.a} >= 0` (whole table) | both `rows` **and** `columns` | once per row x column cell |
| any of the above | `sheets` = `(All)` | repeated on **every z-axis sheet** (per exposure class) |
| fully qualified `{r0150, c0215} = …` | scope columns empty | evaluated once |

An empty scope column with a fully-qualified formula means the rule is already pinned to a
single cell — no expansion.

> **A formula on its own is often not a rule.** Of the 741 enforced rules, **178 contain no row
> reference and 222 contain no column reference** (161 / 202 of the 588 `["live"]` ones) — they
> are meaningless until expanded over their `rows` / `columns` scope. Never read, quote or
> implement a `formula` without its scope columns. This is exactly the BoE `scope(...)` trap
> documented in the `basel31` skill; the difference between the two publishers is only
> **presentational** — EBA puts the domain in sibling columns, BoE wraps it in the expression.

## Formula grammar

| Syntax | Meaning |
|--------|---------|
| `{c0090}` | column 0090, on the row supplied by the row scope |
| `{r0150, c0215}` | one cell, fully qualified |
| `{C 07.00.a, c0200}` | column 0200 of table C 07.00.a (cross-table reference) |
| `s0002` | z-axis **sheet** selector — the per-exposure-class sheet |
| `[CEG=eba_GA:x1]` | dimensional filter (here, geography) |
| `==` / `=` | equality (`==` in Identity rules, `=` in Manual rules) |
| `*` with a percentage | scalar multiply, e.g. `* 1250%` |

Two columns qualify how a rule is evaluated:

- **`Arithmetic approach`** (`arithmetic_approach`) — `Interval` means the comparison is
  **rounding-tolerant**, `Point` means exact. Of the 741 enforced rules, 457 are Interval and 93
  Point (the rest not applicable). Do not assert bit-exact equality for an Interval rule.
- **`Prerequisites`** (`prerequisites`) — the tables that must be reported for the rule to apply.
  Populated on all 741; a rule whose prerequisite table we do not produce simply does not fire.

## Worked examples

All verified against sheet `v3.0(3.0.1)`.

### `v0305_m` — column roll-up, Manual, **Error**, C 07.00.a

```
rows:    (0010;0020;0030;0040;0050;0060;0070;0080)   sheets: (All)
formula: {c0090} = {c0050} + {c0060} + {c0070} + {c0080}
```

Total exposure = the sum of its four components, checked on each of the eight listed rows, on
every exposure-class sheet. One rule expanding to 8 x n-sheets assertions.

### `v0318_m` … `v0328_m` — RW-band identities, Manual, **Error**, C 07.00.a

Each risk-weight band row must reproduce its own risk weight — the fixed-RW rows are not free:

| Rule | Formula | Band |
|------|---------|------|
| `v0318_m` | `{r0150, c0215} = {r0150, c0200} * 2%` | 2% |
| `v0319_m` | `{r0170, c0215} = {r0170, c0200} * 10%` | 10% |
| `v0321_m` | `{r0190, c0215} = {r0190, c0200} * 35%` | 35% |
| `v0324_m` | `{r0220, c0215} = {r0220, c0200} * 75%` | 75% |
| `v0325_m` | `{r0230, c0215} = {r0230, c0200}` | 100% (no multiplier) |
| `v0326_m` | `{r0240, c0215} = {r0240, c0200} * 150%` | 150% |
| `v0328_m` | `{r0270, c0215} = {r0270, c0200} * 1250%` | 1250% |

Directly checkable against our C 07.00 generator: if an exposure lands in the wrong RW band row,
these fire even though the totals still foot.

### `v3697_s` — sign rule, **Error**, C 07.00.a

```
rows:    (0010;0015;…;0283)   columns: (0200;0215;0220)   sheets: (All)
formula: {C 07.00.a} >= 0
```

Exposure value (0200), pre-factor exposure (0215) and RWEA (0220) must be **non-negative** on
every row and sheet. This is the published form of the negative-gross problem: a netting or
deposit-convention bug shows up here first.

### `v0309_m` — cross-sheet, Manual, **Error**

```
rows:    (0090;0110;0130)
formula: {C 07.00.a, c0200} = {C 07.00.b, c0210}
```

The `a` and `b` variants of C 07.00 must agree cell-for-cell on the listed rows.

### `v3332_i` — cross-template identity, **Error**, C 02.00 vs C 07.00.a

```
formula: {C 02.00, r0070, c0010} == {C 07.00.a, r0010, c0220, s0002}
```

The C 02.00 line for one exposure class equals the total-row RWEA of the corresponding
C 07.00 **sheet** (`s0002`). `v3333_i` / `v3334_i` do the same for other classes/sheets — the
published, per-class form of our aggregate `sa_rwea_c07_vs_c02` tie-out.

### `v0150_h` — hierarchy, **Error**, C 02.00

```
columns: (0010)
formula: {r0490} = +{r0500} + {r0510}
```

A parent row is the sum of its children — the row-hierarchy family that keeps C 02.00
internally consistent.

### `v5739_h` — hierarchy inequality, **Error**, C 08.01.a

```
columns: (0020;0030;0080;…;0300)   sheets: (All)
formula: {r0010} >= +{r0015}
```

A total row must dominate its of-which row, over ~19 columns x every sheet.

### `v6277_q` — out-of-scope example, eQuivalence, Warning

```
formula: {C 09.01.a, r0170, c0050, [CEG=eba_GA:x1]} = {C 04.00, r0170, c0010}
```

Reaches into C 04.00, which we do not generate — one of the 55 enforced rules we cannot evaluate.

## Mapping a rule onto our generated frames

Our COREP frames are Polars `DataFrame`s whose **column names are the COREP column codes** and
which carry a **`row_ref`** column of zero-padded 4-digit row ids:

| Rule reference | Our frame |
|----------------|-----------|
| `{r0010, c0200}` in table T | `<t_frame>.filter(pl.col("row_ref") == "0010")["0200"]` |
| `{c0090}` with `rows: (0010;0020)` | same, once per listed `row_ref` |
| `s0002` / `sheets: (All)` | the per-exposure-class sheets are **separate frames** in the template bundle (e.g. `bundle.c07_00[<class>]`) — `(All)` means loop the dict |
| `{C 07.00.a, c0200}` | the other template's frame in the same bundle |

That correspondence is exact, which is what makes the published rules directly runnable against
our output — see the `_cell` / `_rows_sum` / `_sheet_total` helpers in
`src/rwa_calc/reporting/tieouts.py` for readers already written in this shape.

## Relationship to our in-house checker

`src/rwa_calc/reporting/tieouts.py` describes itself as "the first in-house analogue of the
supervisory validation rules". It encodes **5 curated ties** (plus 6 recorded
`NonComparablePair`s). The published sets give **1,258** enforced rules evaluable purely from the
templates we generate declaratively today (578 EBA + 680 BoE), rising to **1,481** once the
C 34.x counterparty-credit-risk estate joins them (686 EBA + 795 BoE).

> The published rules are the authority. `tieouts.py` is a small, deliberately curated subset —
> a green tie-out run is not evidence that a template is submission-valid.

Note the complementary strength: `NON_COMPARABLE_PAIRS` records identities that must **not** be
asserted (obligor vs post-substitution basis). The published rules do not assert those either —
if you find yourself wanting a tie the EBA does not publish, check the non-comparable list first.

## How to use this when implementing or changing a template

1. **Before** changing a template's rows, columns or aggregation, search the extract for the
   template id — the rules tell you which cells are load-bearing for other templates.
2. Treat every **Error** rule touching a cell you changed as a required post-condition.
3. When a golden file moves, check whether the move breaks a published identity: a legitimate
   fix keeps every Error rule satisfied.
4. If a rule looks unsatisfiable given our data, the answer is usually a **basis** difference —
   confirm against `tieouts.py`'s `NON_COMPARABLE_PAIRS` and the per-template basis decisions in
   `docs/plans/phase7-declarative-reporting.md` section 6 before assuming the rule is wrong.
5. New cross-template ties worth encoding permanently belong in `TIE_OUTS`, quoting the EBA rule
   id in the `regulatory_reference`.

---

> **Basel 3.1 counterpart:** the BoE publishes the equivalent rules for the OF templates — see
> the `basel31` skill, `references/reporting-validation-rules.md`. Many BoE rules name their EBA
> equivalent id, so the two sets cross-reference directly.
