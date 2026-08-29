# Return reconciliation — sense-checking a template against the firm's current return

**Status:** Proposed 2026-08-29 · **Owner:** reporting + analysis + UI surfaces ·
**Depends on:** the sealed reporting ledger (Phase 7) and the cell-lineage
instrumentation (`docs/plans/report-cell-lineage.md`)

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

Worse, several of the most common causes are **already known to this codebase**
and written down in prose the analyst never sees. For C 08.03 alone,
`LINEAGE_PLANS["c08_03"].scope` and `reporting/corep/templates.py` already record
that:

- Row allocation uses `pd_floored` under CRR but the **pre-input-floor** `pd`
  under Basel 3.1 (`corep/c08.py::_pd_alloc_col`), while column 0050 **always**
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
| 2 | Are the same exposures in the same **row**? | **Row placement** — banding rule differs (the PD-band question) | Nothing |
| 3 | Are they on the same **sheet / template**? | **Sheet placement** — class or approach assignment differs | Partial: the exposure-grain asset-class allocation table |
| 4 | Same exposures, same row — different number? | **Measurement** — EAD / RW / PD / LGD / CCF differs | Exists, but cannot be filtered to a cell |

The design below makes all four computable, and — for money cells — makes them
**sum to the cell delta**, so the four numbers are a waterfall the analyst can
sanity-check rather than four unrelated reports.

## Design at a glance

Three artifacts and one new grain. Nothing recomputes a reported figure; every
layer reads the specs the generators actually execute.

- **A · Cell membership** (`reporting/membership.py`, new) — for each
  lineage-instrumented template, the long frame
  `(template_id, sheet, row_ref, leg_id, class, approach, ead, rwa, …)` saying
  **which template rows each leg landed in**. Built generically from
  `plan.spec.predicate ∧ cells[(row, col)].predicate` over `plan.frame` — the
  same conjunction `reporting/lineage.py::describe_cell` already uses, so
  membership can never disagree with the reported number. This is the enabler:
  it is what makes questions 1–3 answerable at all.
- **B · Return ingest** (`analysis/return_ingest.py`, new) — the firm's current
  return loaded into the **same long shape `reporting/facts.py` already exports**:
  `(template_id, sheet, row_ref, col_ref, value)`. One mapping config handles
  sheet-name synonyms, row/col ref normalisation, units/scale, and a
  `their_row_label → our_row_ref` map. Because both sides are fact frames, the
  cell diff is a join, not a new engine.
- **C · Cell-delta decomposition** (`analysis/return_recon.py`, new) — joins
  A + B + the existing exposure-grain recon into the four-way waterfall, plus the
  UI surfaces that render it.

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

## Phase 2 — Ingest the firm's current return

**Change.** New `analysis/return_ingest.py` + a TOML grammar mirroring
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
`unmapped` rows on the diff rather than being dropped — a silently dropped row
is how a real difference disappears.

**Tests.** Round-trip: our own exported fact frame re-ingested reconciles to
zero on every cell (the mapping identity test). Unmapped labels surface as
warnings, never silent drops.

## Phase 3 — Cell diff overlay on the template grid

**Change.** `report_templates.html` gains a compare mode. The grid already
stamps `data-template/sheet/row/col` on every cell, so the overlay is a join on
that key and a render change only:

- each cell shows **ours / theirs / Δ**, heat-shaded by |Δ| relative to the
  sheet's largest delta;
- a sheet header strip: total Δ, count of cells over the materiality threshold,
  and the count of rows present on one side only;
- a ranked **"worst cells"** list under the grid, each linking to the Phase 4
  explanation;
- rows that exist on only one side render as a distinct band — a **missing row
  is not a zero**, and the grid must never let them look alike (the same
  null-vs-zero rule `ui/views/report_templates.py` already enforces).

Materiality is set once per compare (absolute and % of cell), because a firm's
return is rounded to £000s and float-exact diffing produces noise, not findings.

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
our PD, their implied PD, **our allocation basis** and the delta that would
close the gap. That single view is the direct answer to *"why is the PD band
different"*, and the same matrix serves CR6, C 08.02, CR5's RW buckets and
C 07.00's CQS columns without any per-template code.

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

## Phase 7 (optional) — reverse lookup: "where does this loan appear?"

Membership inverted: given an exposure reference, every cell it touches across
the whole estate. Answers the other half of the sense check — *"we can't find
loan L123 on your return"* — and costs nothing extra once Phase 1 exists.

## Honest limits

- **Membership frame size.** One row per (leg × instrumented template × sheet ×
  row), with hierarchical templates contributing ~2 rows per leg. At tens of
  millions of legs this must spill to parquet and be scanned per sheet, not held
  in `_RECON_RUNS` — the RAM ceiling already recorded in
  `docs/plans/reconciliation-ux-redesign.md` applies here with a larger constant.
- **Cells with no exposure population.** `Formula`, `SideContext`, `PriorPeriod`
  and `constant` cells have no legs. The compare must report the cell kind (which
  `CellQuery` already carries) and link to the referenced cells, not fabricate a
  decomposition.
- **Row placement needs their PD, not just their row.** The migration matrix works
  from row labels alone, but *"their implied PD"* needs the firm's exposure
  extract too. The full explanation therefore wants **both** inputs — the return
  and the exposure file. Design for graceful degradation: return-only gives the
  matrix and the money, return + extract gives the per-obligor reason.
- **Templates outside `LINEAGE_PLANS`** get the Phase 3 cell diff (a fact-frame
  join needs no instrumentation) but no decomposition. That is the honest
  boundary, and the UI must state it.
- **Their return may be at a different consolidation scope or reporting date.**
  Guard on `FilingMetadata` (`reporting/metadata.py`) and refuse to compare
  mismatched scope/date rather than producing a large meaningless delta.

## Build order and payoff

Phases 2 + 3 alone (ingest + cell diff overlay) already replace the
two-spreadsheets-side-by-side step and are independent of Phase 1. Phase 1 + 4 is
where the "why" arrives. Recommended order: **3 → 1 → 4 → 6 → 5 → 7**, shipping
the overlay first so the ingest mapping gets real-world exercise before the
decomposition is built on top of it.

## Open decisions

1. **Ingest formats** — is a filled COREP xlsx a required v1 input, or is
   long-form csv/parquet (what a vendor filing tool emits) enough?
2. **Where does it live** — a compare mode on the existing template viewer, or a
   third top-level tab beside Reconciliation?
3. **Does sign-off extend to cells?** The exposure-grain sign-off
   (`ui/app/recon_signoff.py`, keyed on `_recon_key`) has an obvious cell-grain
   analogue: accept a cell delta with a reason and burn down the residual.
   Worth confirming whether migration evidence is expected at cell grain.
