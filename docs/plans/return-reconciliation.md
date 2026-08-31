# Return reconciliation — sense-checking a template against the firm's current return

**Status:** **IMPLEMENTED 2026-08-29** (Phases 1-6; Phases 7-8 remain optional and
undone) · **Owner:** reporting + analysis + UI surfaces · **Depends on:** the
sealed reporting ledger (Phase 7) and the cell-lineage instrumentation
(`docs/plans/report-cell-lineage.md`)

Templates in scope: `c07_00`, `c08_01`, `c08_03` under both frameworks — OF 07.00
/ OF 08.01 / OF 08.03 proved to be the *same* ids and the *same* generator
functions branched internally on `framework`, so the six requested templates are
three implementations. Modules: `analysis/legacy_ledger.py`,
`reporting/membership.py`, `analysis/return_recon.py`, `ui/views/return_recon.py`,
route `GET /reconciliation/{recon_id}/templates`.

## As built — where reality diverged from this plan

Five things this document got wrong or under-specified. Each was found by
measurement, and each is recorded because the plan reads plausibly without them.

1. **A template row does not have one population.** The plan assumed all
   `rows`-kind cells on a row share a predicate. True only for C 08.03. On
   C 07.00 and C 08.01 it is false on *every* row (the F3 two-basis split plus
   per-column narrowings): a C 08.01 row's origin-basis predicate serves 19
   columns and its post-basis predicate others. A single population per row was
   wrong on 27/90 cells (CRR) and 47/110 (B3.1), by exactly the substituted legs.
   Membership is therefore keyed on `predicate_key`, and every consumer addresses
   a cell's population through `CellMembership.columns`.

2. **`is_parent_row` cannot be a two-state flag.** Rows holding *identical* leg
   sets are indistinguishable from the data, and reporting `False` there made
   leaves-only sums run 3.00x over true. It is a nullable tri-state, and **no
   flag makes "sum the leaves" reconstruct a total** — read the group's
   de-duplicated legs. Nor can the sheet be aggregated: `~is_parent_row` is
   legitimately EMPTY on a co-extensive sheet (0.00 against real money on four of
   ten sheets in the fixture).

3. **An unmapped carrier does not always degrade to null.**
   `ensure_gross_side_carriers` injects an *all-null* column, and `col_sum` totals
   that to `0.0` — a false zero, not a null. Worse, an unguarded decomposition
   attributes it to **`measurement`**, which *reconciles*, so it reads as a
   credible engine discrepancy rather than a gap. `LedgerCoverage` must therefore
   be passed to arm the refusal; a `None` default silently disarms it.

4. **A requirement of the form `sealed OR (a AND b)` must be expressible.** The
   first cut modelled cell requirements as a conjunction of OR-groups, which
   cannot state that. `drawn` and `interest` are ADDENDS, so mapping one alone
   satisfied the group and published a confident 0.0 — and drove C 07.00 col 0110
   *negative*. Now DNF. The leave-one-out sweep written to catch it found four
   further under-reports nobody had enumerated, including that an absent input to
   a Formula cell reads as ZERO in the waterfall rather than null.

5. **Reachability and population are different questions.** Conflating them
   reproduces the recorded `sheet_not_emitted` trap: an all-SA book was reported
   "C 08.01 unreachable" with nothing named to fix — while keying refusal on
   population instead would have hidden *"your return is missing your entire IRB
   book"* (44 cells, 18 with a non-zero delta). Reachable is a statement about the
   MAPPING; populated is about the BOOK.

**Decisions taken 2026-08-29** (they close the three questions this plan opened):

1. **The legacy side is generated, not uploaded.** The exposure extract the
   reconciliation process already takes carries the reporting fields — PD, LGD,
   EAD, class, approach — so their side of every template is *projected* from
   that same file rather than ingested as a filled return.
2. **It lives inside the existing reconciliation tab**, as one of the views
   there — not a compare mode on the template viewer, and not a new tab.
3. **Ingesting the actually-filed return is still offered**, as an optional
   extra input, because it may be required and it catches a class of difference
   the extract structurally cannot explain.

## Why

A migrating firm's actual question is *"our C 08.03 says £412m of RWEA in the
0.25 to <0.50 band and yours says £388m — why?"*. Today the product cannot be
asked that question at all, because the two halves of the answer live at two
different grains and never meet:

- **`/reconciliation` is exposure-grain.** `analysis/reconciliation.py` full-outer
  joins our per-exposure results against a mapped *exposure extract*
  (`api/reconciliation.py` accepts csv/parquet keyed on `exposure_reference`) and
  buckets 15 canonical components (`analysis/recon_registry.py`). It answers
  *"which loans differ, and on which component"*. It has no concept of a
  template, a row ref, or a column ref.
- **`/results/{run}/templates` is cell-grain and one-sided.** The grid stamps
  every cell with `(template_id, sheet, row_ref, col_ref)` and links it to the
  lineage drill-down (`reporting/lineage.py`), which explains *our* cell
  beautifully — metric, filter criteria, population scope, sign convention, and
  the legs behind it. There is nowhere to put the firm's own number, so nothing
  is ever compared.

So the analyst does the bridging by hand: eyeball two spreadsheets, guess which
of four completely different causes is at work, then go hunting in an
exposure-grain break list that is not filtered to the cell they were looking at.
That hand-bridging is the whole cost of a parallel run, and it is the thing that
decides whether a migration takes two weeks or two quarters.

**The input for the fix already exists.** The legacy extract the firm supplies
today carries the fields the templates aggregate. Nothing new has to be
collected to produce their side of a return — it only has to be projected
through the generators we already run for ours.

Worse, several of the most common causes are **already known to this codebase**
and written down in prose the analyst never sees. For C 08.03 alone,
`LINEAGE_PLANS["c08_03"].scope` and `reporting/corep/templates.py` already record
that:

- Row allocation uses `pd_floored` under CRR but the **pre-input-floor** `pd`
  under Basel 3.1 (`corep/pd_scale.py::pd_band_col`), while column 0050 **always**
  reports the post-floor PD. A legacy engine that bands on post-floor PD moves
  every floored obligor a band — with no change in any number the analyst can see
  on the face of the return.
- The PD scale is **hierarchical, not a partition**: rows 0010 / 0070 / 0100 /
  0130 overlap and equal the sum of their children (`C08_03_PD_PARENT_REFS`).
  A legacy extract flattened to 17 disjoint buckets double-counts on comparison.
- Basel 3.1 splits the first band again at 0.05% (rows 0015 / 0025 replacing
  CRR row 0020) — **18 rows against 17**, so a CRR-shaped legacy return has no
  counterpart row at all.
- **Slotting is excluded** (it discloses on C 08.06), so a legacy engine that
  bands supervisory-slotting SL into C 08.03 shows as pure population difference.
- The sheet axis keys `reporting_class_origin` — the **obligor origination**
  class, *before* guarantee substitution. A legacy engine that sheets
  post-substitution puts a guaranteed exposure on a different sheet entirely.
- Rows are **sparse**: only populated bands emit. A missing row is not a zero.

Every one of those is a five-second answer the tool could give and today does
not.

## The four questions, and what answers each

A cell delta has exactly four mutually exclusive causes. Naming them is what
turns "it's different" into "it's fine" or "that's a bug":

| # | Question | Cause | Today |
|---|---|---|---|
| 1 | Are the same exposures in scope at all? | **Population** — in ours, not theirs (or vice versa) | Portfolio-wide only (`missing_left` / `missing_right`), never scoped to a cell |
| 2 | Are the same exposures in the same **row**? | **Row placement** — banding differs (the PD-band question) | Nothing |
| 3 | Are they on the same **sheet / template**? | **Sheet placement** — class or approach assignment differs | Partial: the exposure-grain asset-class allocation table |
| 4 | Same exposures, same row — different number? | **Measurement** — EAD / RW / PD / LGD / CCF differs | Exists, but cannot be filtered to a cell |

The design below makes all four computable, and — for money cells — makes them
**sum to the cell delta**, so the four numbers are a waterfall the analyst can
sanity-check rather than four unrelated reports.

## Design at a glance

Three artifacts and one new grain. Nothing recomputes a reported figure; every
layer reads the specs the generators actually execute.

- **A · Cell membership** (`reporting/membership.py`, new) — for a generated
  template, the long frame `(template_id, sheet, row_ref, leg_id, class,
  approach, ead, rwa, …)` saying **which template rows each leg landed in**.
  Built generically from `plan.spec.predicate ∧ cells[(row, col)].predicate`
  over `plan.frame` — the same conjunction `reporting/lineage.py::describe_cell`
  already uses, so membership can never disagree with the reported number.
  **It runs unchanged on both sides**, because both sides are produced by the
  same executor.
- **B · The legacy ledger projection** (`analysis/legacy_ledger.py`, new) — map
  the reconciliation extract onto the sealed reporting-ledger column names and
  run **the same `<template>_plans()` and `execute()`** over it. Their side of a
  return is generated, not uploaded. No second reporting engine exists, so every
  template we ever add gets a legacy side for free.
- **C · Cell-delta decomposition** (`analysis/return_recon.py`, new) — joins
  A + B + the existing exposure-grain buckets into the four-way waterfall and the
  migration matrices, surfaced as a template view inside the reconciliation tab.

Optional fourth input, offered but never required: the **filed return** itself
(Phase 7), for the tie-out that catches what happens to a number *after* the
legacy engine produces it.

## Phase 1 — Cell membership as a first-class artifact

**Change.** New `reporting/membership.py`:

```python
def cell_membership(source: ResultsSource, template_ids: Sequence[str] | None = None)
    -> pl.DataFrame:  # one row per (template_id, sheet, row_ref, leg_id)
```

Walks `LINEAGE_PLANS`, and for each sheet plan evaluates each row's membership
predicate once (row-level, **not** per column — every `rows`-kind cell on a row
shares the row predicate, so per-column membership would multiply the frame by
~11 for no information). Carries the leg's identity (`exposure_reference`,
`source_exposure_reference`, `reporting_leg_role`) and the money it brought
(`ead_final`, `rwa_final`, the sealed gross carriers) so a placement difference
can be priced immediately.

Because the signature takes a `ResultsSource`, the **legacy projection of Phase 2
is a valid argument**. One function produces both sides' membership, and the
migration matrix is a join between the two.

**Why it is safe.** It reuses `plan.spec` and `plan.frame` — no second copy of a
template's row selection, which is the one rule `reporting/lineage.py` is built
around. Templates outside `LINEAGE_PLANS` resolve to no membership, never a
guess; the compare surface says "not instrumented" rather than inventing rows.

**Note the hierarchy.** A leg legitimately appears in **both** a parent row and
its child (C 08.03 rows 0010 + 0020). Membership must carry an `is_parent_row`
flag off `C08_03_PD_PARENT_REFS` (and the CR6/CR9 equivalents) so every consumer
either excludes parents or knowingly double-counts. This is the single most
likely way a naive implementation ships a wrong number.

**Tests.** `tests/unit/reporting/test_membership.py` — for every instrumented
template, Σ membership EAD per (sheet, leaf row) equals the reported EAD cell of
that row; parent rows equal the sum of their children; a leg appears in exactly
one leaf row per sheet.

## Phase 2 — Project the legacy extract into the reporting ledger

**The decision.** Their side of a template is **generated from the extract the
reconciliation already loads**, by renaming its mapped components onto the
sealed reporting-ledger column names and running the same generators. Their PD
is therefore available per exposure, which is what makes the row-placement
analysis exact rather than inferential.

**Change.** New `analysis/legacy_ledger.py`:

```python
def project_legacy_ledger(legacy: pl.LazyFrame, mapping: LegacyColumnMapping)
    -> tuple[pl.LazyFrame, LedgerCoverage]
```

It emits a frame in the sealed ledger's own column vocabulary
(`reporting_class_origin`, `reporting_approach_origin`, `ead_final`,
`pd_floored`, `lgd_floored`, `irb_maturity_m`, `ccf`, `rwa_final`,
`expected_loss`, …) from the components the mapping already declares, plus a
`LedgerCoverage` record of what it could **not** supply.

**This is safe because the generators already tolerate absence.** `corep/c08.py`
`_prepare` states it plainly — the derived discriminators are added *"each only
when its sources exist — underived columns make their tolerant terms match
nothing"* — and `pick(cols, …)` resolves every metric by presence. So an
unmapped carrier yields an empty or null cell, which is exactly the honest
outcome. The one rule the projection must never break is the codebase's
null-vs-zero discipline: **an unsupplied carrier is null, never 0.0**, and the
compare must render it as *not mapped* rather than as a legacy zero. A false
zero here would manufacture the largest delta on the sheet.

**The carrier gap, measured on C 08.03.** Of its eleven columns, the existing 15
components already cover cols 0030 (`ccf`), 0040 (`ead`), 0050 (`pd`), 0070
(`lgd`), 0080 (`maturity`), 0090 (`rwa`) and 0100 (`expected_loss`), and the
sheet/population axes (`exposure_class`, `approach`). Four things are missing:

| Needs | For | Proposed mapping |
|---|---|---|
| `reporting_gross_on_bs` | col 0010 | new component `gross_on_balance_sheet` |
| `reporting_gross_off_bs` | cols 0020, and the col 0030 CCF weight | new component `gross_off_balance_sheet` |
| `scra_provision_amount` + `gcra_provision_amount` | col 0110 | new component `provisions` |
| `counterparty_reference` | col 0060, distinct obligor count | identity mapping, not a reconciled component |

The first three are genuinely reconcilable amounts a legacy engine reports, so
they join `RECONCILABLE_COMPONENTS` and get bucketed like any other — they earn
their place on the exposure-grain view too. The obligor reference is an
identity, so it is mapped alongside the join keys; without it col 0060 falls
back to the row count the generator already uses.

**Template reachability is a first-class output.** From the mapping, compute
which templates the legacy side can produce and which columns of each are
supported, and show it before the compare runs: *"your mapping supports C 07.00,
C 08.03, CR4 and CR6; map `provisions` to unlock C 08.03 column 0110."* An
analyst should learn what their file cannot answer from the tool, not from a
suspiciously empty column.

**Tests.** Feed **our own** results back in as the legacy extract through an
identity mapping: every generated template must come out cell-identical to ours.
That single test proves the projection is faithful and the executor is shared.
Then a coverage test: an unmapped carrier produces nulls, never zeros, and is
reported in `LedgerCoverage`.

## Phase 3 — The template view inside the reconciliation tab

**The decision.** This is a view within `/reconciliation`, alongside the tiers
that are there today — not a second home for reconciliation, and not a compare
mode bolted onto the results-page template viewer.

It fits the page's existing progressive disclosure exactly. The tab is already
*headline → segment → worklist → per-loan*; a template is simply **another
segment axis**, and it drills into the per-key explorer that already exists:

```
headline tie-out
  └─ segment ── by bucket / class / approach / method          (today)
             └─ by return template   ← new: pick a template + sheet
                  ├─ cell grid: ours / theirs / Δ, heat-shaded
                  ├─ worst cells, ranked
                  └─ row-migration matrix
                       └─ per-key explorer, filtered to the cell   (today)
                            └─ single-loan driver chain            (today)
```

**Changes.** A template + sheet picker and a cell grid on the reconciliation
page; the existing explorer gains a cell filter (`template`, `sheet`, `row`,
`col`) alongside its bucket/class/approach filters. Because the drill target is
unchanged, the sign-off flow, the CSV/Excel export and the fingerprinting all
work as they do today.

Materiality is set once per compare (absolute and % of cell) — a firm's return
is rounded to £000s, and float-exact diffing produces noise, not findings.

A cell that exists on only one side renders as a distinct band. **A missing row
is not a zero**, and the grid must never let them look alike — the same
null-vs-zero rule `ui/views/report_templates.py` already enforces.

Our own cell keeps its link into the existing lineage drill-down, so *"what does
this cell of ours mean"* stays one click away without duplicating that surface.

## Phase 4 — Explain the delta: the four-way waterfall

**Change.** `analysis/return_recon.py` — given a cell, produce:

```
Cell C 08.03 / corporate / row 0050 / col 0090 (RWEA)
  ours                                    388,412,000
  theirs                                  412,006,000
  Δ                                       -23,594,000
    ├─ population   (in theirs only)       -4,100,000   17 exposures
    ├─ population   (in ours only)         +1,250,000    3 exposures
    ├─ row placement (moved band)         -19,900,000   41 exposures
    ├─ sheet placement (moved class)         -844,000    2 exposures
    └─ measurement  (same row, diff value)      0        —
```

**Row placement is the headline feature: the migration matrix.** For a sheet,
a rows×rows matrix — our row down, their row across — of the money that moved.
The diagonal is agreement; every off-diagonal cell is a banding difference,
priced. Clicking an off-diagonal cell lists the exposures that moved, each with
our PD, **their PD** and the band boundary crossed. The same matrix serves CR6,
C 08.02, CR5's RW buckets and C 07.00's CQS columns without any per-template
code.

**Because their PD is now known per exposure, row placement splits in two** —
and the split is the whole diagnosis:

- **Value-driven** — their PD differs from ours, so the same banding rule puts
  the exposure elsewhere. The fix is upstream, in the data or the PD model, and
  the exposure-grain `pd` component already prices it.
- **Rule-driven** — the PDs agree but the bands do not. That is a *reporting*
  difference, not a credit one, and it is where the pre- vs post-input-floor
  allocation basis shows up. Detectable whenever their extract carries their own
  band or grade label (map it as `legacy_row_label`), and always detectable when
  the filed return is supplied (Phase 7).

Telling a firm *"41 exposures moved band, and 38 of them moved because your
banding uses the post-floor PD"* is a different quality of answer from *"41
exposures moved band"*.

**Sheet placement** is the same matrix on the sheet axis (which exposure class),
plus a cross-template variant for the big migrations — SA `C 07.00` ↔ IRB
`C 08.0x`, slotting to `C 08.06`, equity — which is where "it isn't on this
return at all" gets answered.

**Measurement** hands off to the machinery that already exists: the exposure-grain
component recon, filtered to the cell's membership. The per-loan driver chain
(`ui/views/reconciliation.py::_driver_chain`) then explains the individual loan
exactly as it does today. No new forensic surface is needed — it only needs to
be reachable *from a cell*.

**The additivity contract.** For an additive money column the four terms must sum
to the cell delta, and a contract test must assert it (the same discipline
`reporting/tieouts.py` applies to cross-template ties). If they do not sum, the
decomposition is wrong and must say so rather than presenting a plausible-looking
waterfall.

## Phase 5 — Non-additive cells: the rate/mix split

Columns 0030 (avg CCF), 0050 (EW-avg PD), 0070 (EW-avg LGD) and 0080 (EW-avg
maturity) are weighted averages — the four-way waterfall does not apply, and
pretending it does is a wrong number. For those, decompose instead into the
classic two terms:

- **rate effect** — same population, different per-exposure value;
- **mix effect** — same values, different exposure weights (which is exactly what
  a row-placement difference *does* to a weighted average).

This matters more than it sounds: on C 08.03 the mix effect is how a *population*
or *banding* difference shows up in the PD column, and an analyst who reads it as
a PD-calibration difference goes looking in entirely the wrong place.

## Phase 6 — Basis banner and the known-divergence checklist

Above a compared sheet, surface the reporting-basis decisions that most often
explain a *whole-row* shift, as a checklist the analyst can tick against their own
return. The prose already exists in `LINEAGE_PLANS[*].scope`; it is only
unreachable. For C 08.03 that is six lines: PD allocation basis (pre- vs
post-input-floor), hierarchical parent rows, the 18-vs-17 row split under Basel
3.1, slotting exclusion, obligor-origin vs post-substitution sheeting, and
sparse rows. Each carries a *"does your return do this?"* toggle; a mismatch is
recorded as a **declared basis difference** and shown separately from the
unexplained residual — the residual is the only number a migration actually
needs to burn down.

Phase 2 sharpens this: because their PD is known, several toggles can be
*proposed* rather than merely asked. Re-banding their exposures on the other
basis and seeing the residual collapse is direct evidence of which basis they
use, and the banner should offer that as a one-click test.

## Phase 7 (optional, offered) — ingest the filed return

Everything above compares **our engine against their engine**. It cannot see
what happens to a number after their engine produces it: manual adjustments and
overlays, late reclassifications, rounding and unit conventions, and whatever
their filing tool's own mapping does. Those are real, they are common in a
migration, and no exposure extract will ever explain them. So the filed return
stays on offer as an extra input.

**Change.** `analysis/return_ingest.py` + a TOML grammar mirroring
`api/reconciliation.py`'s:

```toml
return_file   = "./our_current_c0803.csv"
return_format = "csv"          # csv | parquet | xlsx
template      = "c08_03"
scale         = 1_000          # their £000s -> our units
[sheets]      # their sheet name -> our reporting_class_origin
"Corporate — Other" = "corporate"
[rows]        # optional: their row label -> our row ref
"0.25% - 0.50%" = "0050"
[columns]     # their column header -> our col ref
"RWEA" = "0090"
```

Two accepted shapes: **long** (`template, sheet, row, col, value` — what a
vendor filing tool exports, and what our own `/export` produces) and **wide**
(one sheet per class, rows down, cols across — what a firm's own return looks
like). Wide is normalised into long on load. Unmapped rows/cols become explicit
`unmapped` rows rather than being dropped — a silently dropped row is how a real
difference disappears.

**With all three inputs present the view becomes a three-column tie-out** —
*ours* · *their engine* · *their filed return* — and the two gaps mean different
things:

- **ours vs their engine** — a calculation or reporting-basis difference, which
  is what Phases 3–6 decompose.
- **their engine vs their filed return** — an adjustment, an overlay, or a
  filing-tool transformation. Nothing in the calculator caused it, and saying so
  precisely is worth a great deal during a parallel run.

**Tests.** Round-trip: our own exported fact frame re-ingested reconciles to zero
on every cell (the mapping identity test). Unmapped labels surface as warnings,
never silent drops.

## Phase 8 (optional) — reverse lookup: "where does this loan appear?"

Membership inverted: given an exposure reference, every cell it touches across
the whole estate, on both sides. Answers the other half of the sense check —
*"we can't find loan L123 on your return"* — and costs nothing extra once
Phase 1 exists.

## Honest limits

- **Their side is aggregated our way.** The legacy projection applies *our*
  metric to *their* values: a weighted-average column uses our weighting, our
  distinct-count rule, our sign convention. That is the right default — it holds
  the reporting rules constant so a difference means a *data* difference — but it
  means a column where their return aggregates differently is invisible until the
  filed return is supplied. State it on the view; do not let the three-column
  tie-out of Phase 7 look like a nicety.
- **Rule-driven row placement needs a signal.** Value-driven banding differences
  fall straight out of the projection; rule-driven ones need either a mapped
  band/grade label on their extract or the filed return. Absent both, the matrix
  is still right about *what moved and what it cost* — it just cannot say whether
  the cause was the PD or the rule.
- **Carrier coverage is partial and must be visible.** A mapping that omits the
  gross on/off-balance-sheet carriers cannot populate C 08.03 cols 0010/0020 or
  weight col 0030. `LedgerCoverage` and the reachability panel exist so that
  reads as *unavailable*, never as zero.
- **Membership frame size.** One row per (leg × instrumented template × sheet ×
  row), with hierarchical templates contributing ~2 rows per leg — and now twice
  over, once per side. At tens of millions of legs this must spill to parquet and
  be scanned per sheet, not held in `_RECON_RUNS`; the RAM ceiling already
  recorded in `docs/plans/reconciliation-ux-redesign.md` applies with a larger
  constant.
- **Cells with no exposure population.** `Formula`, `SideContext`, `PriorPeriod`
  and `constant` cells have no legs. The compare must report the cell kind (which
  `CellQuery` already carries) and link to the referenced cells, not fabricate a
  decomposition. Side-context values in particular have no legacy counterpart at
  all unless the filed return supplies one.
- **Templates outside `LINEAGE_PLANS`** still generate on both sides, so they get
  the Phase 3 cell diff; only instrumented templates get the decomposition. That
  is the honest boundary, and the UI must state it.
- **Their extract may be at a different consolidation scope or reporting date.**
  Guard on `FilingMetadata` (`reporting/metadata.py`) and refuse to compare
  mismatched scope/date rather than producing a large meaningless delta.

## Build order and payoff

Phase 2 is the prerequisite for everything, and Phase 3 turns it into a usable
answer immediately: **2 → 3** already replaces the two-spreadsheets-side-by-side
step, using an input the firm has already supplied. Then **1 → 4** adds the
"why", **6** and **5** sharpen it, and **7** / **8** are the offered extras.

Recommended order: **2 → 3 → 1 → 4 → 6 → 5 → 7 → 8**.

## Open questions arising

1. **Which templates does the legacy projection cover on day one?** The
   projection is generic, but the *value* is concentrated: C 07.00, C 08.03,
   C 08.01 and CR6 probably carry most of a migration's argument. Worth
   confirming rather than assuming breadth is free.
2. **Does the extract carry a band or grade label today?** If firms' extracts
   commonly do, mapping it as `legacy_row_label` upgrades every row-placement
   finding from *"it moved"* to *"it moved because of the rule"* for very little
   work, and should move earlier in the build order.
3. **Should the three new carrier components be required or optional?** Making
   `gross_on_balance_sheet` / `gross_off_balance_sheet` / `provisions` optional
   keeps existing mappings working untouched; making them required would force
   every migration onto a complete C 08.03. Optional is the assumption here.
