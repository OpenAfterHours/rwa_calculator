# Report Cell Lineage

Ask a reported figure where it came from: **which exposures and which rules produced this cell?**

Given a cell address — template, sheet, row ref, column ref — lineage answers what the cell *means*
(its metric, its filter criteria, the scope of its population) and lists the ledger legs that fed it.

## Using it

Open the [report template viewer](report-template-viewer.md) for a run and **click any cell**. The
drill-down page shows:

- the **reported value**, the **sum of contributions**, and whether the two reconcile (allowing for the
  deduction-column sign convention — a mismatch is flagged as a defect, not hidden);
- what the cell measures, and the criteria a leg must satisfy to be counted;
- the population the criteria were applied to;
- the contributing exposure legs, largest first.

Cells are only offered as links on templates that have lineage — a link never leads to a shrug.

## The key idea: lineage is a query, not an index

A cell's lineage **is its specification**. Every declarative template is a `TemplateSpec` whose cells
are a value binding plus a row predicate — so C 07.00's RWEA cell literally *is*
`CellSpec(Sum("rwa_final"), predicate=…)`.

Lineage therefore **reads the spec the generator executes** and re-runs that same predicate over the
same prepared frame. It does not store cell → row-id memberships, and it does not re-implement a
template's row selection. A second copy of that logic could silently disagree with the figure actually
reported — the one thing a lineage feature must never do.

Two consequences worth knowing:

- **The reported value wins.** `cell_value` is read from the *generated template* — the number you
  clicked — and is never recomputed. `contribution_total` is the sum over the returned legs, reported
  separately, with a `sign` flag ("positive" / "negated") that reconciles the two across the COREP
  Annex II §1.3 deduction-column convention.
- **A contributor is a *leg*, not an exposure.** A guaranteed exposure is physically split into a
  guaranteed leg (under the guarantor's class) and a retained leg. Every row carries
  `reporting_leg_role`, both class endpoints, and `source_exposure_reference` so the split is visible
  rather than looking like a stray exposure.

## The six kinds of cell

Not every cell has contributing exposures, and a drill-down that pretends otherwise is lying. The kind
falls straight out of the cell's binding:

| Kind | Meaning | What you get |
|---|---|---|
| `rows` | An aggregate over ledger legs (sum, mean, weighted average, ratio, count) | The contributing legs |
| `formula` | Derived from *other cells* — e.g. C 07.00 `0040 = 0010 − 0030` | The cell refs it derives from |
| `side_context` | An out-of-frame value — e.g. the C 07.00 substitution inflow | The context key |
| `prior_period` | Evaluated over the previous period (CR8, C 08.04 opening RWEA) | The prior run's basis |
| `constant` | A source the engine never produces (structurally null) | Why it is blank |
| `unbound` | No binding — the template's empty-cell policy applies | The policy (COREP 0.0 / Pillar III null) |

!!! warning "A reported zero is not always a measured zero"

    Some cells sum a column the engine does not produce (C 07.00 col 0030 sums SCRA/GCRA provision
    amounts, which are not on the calculation ledger). Under the COREP zero policy such a cell still
    **reports `0.0`** — but that zero is a structural artefact, not a measurement.

    Lineage says so explicitly: `is_source_backed` is `false`, `missing_columns` names the absent
    sources, and `contribution_total` is `null` rather than a misleading `0`. This is the difference
    between *"we computed zero"* and *"we cannot compute this"* — a distinction the template viewer
    alone cannot make.

## The API

```
GET /api/lineage?run_id=…&template=c07_00&sheet=corporate&row=0010&col=0220
```

```json
{
  "cell": {"template": "c07_00", "sheet": "corporate", "row_ref": "0010",
           "col_ref": "0220", "row_name": "TOTAL EXPOSURES"},
  "kind": "rows",
  "metric": "sum",
  "metric_columns": ["rwa_final"],
  "is_source_backed": true,
  "filter_terms": [],
  "scope": [
    "Standardised-approach legs, plus BOTH counterparty-credit-risk populations — FCCM SFT rows and SA-CCR derivative netting sets. The CCR rows are admitted by risk type (not by the approach label, which the output floor relabels), and Annex II breaks them out in rows 0090-0130",
    "Specialised lending is merged into corporate (Art. 112(1)(g): under the standardised approach SL is a corporate sub-type)",
    "Sheet: obligor class = corporate"
  ],
  "basis": "aggregator_exit",
  "sign": "positive",
  "cell_value": 1000000.0,
  "contribution_total": 1000000.0,
  "total_rows": 1,
  "columns": ["exposure_reference", "reporting_leg_role", "…", "rwa_final"],
  "rows": [{"exposure_reference": "LN-P1147-001", "reporting_leg_role": "whole", "rwa_final": 1000000.0}]
}
```

`filter_terms` are the cell's row-selection criteria, each tagged `ledger` (a sealed fact about the
exposure) or `derived` (a discriminator the template computes for its own row structure, such as a
risk-weight band). `scope` names the population steps that ran before the predicate. Together they are
the full, reviewable answer to "which rules contributed".

Everything runs on `basis: aggregator_exit` — the sealed per-leg ledger.

!!! success "What it found first: a scope note that was not true"
    The `scope` line above used to read *"Standardised-approach legs, plus FCCM SFT rows (SA-CCR
    derivatives are excluded — they report under C 34)"*. An operator read it in the drill-down and
    asked why. The answer: C 07.00 and C 34 are **not alternatives** — Annex II puts CCR exposures in
    C 07.00 rows 0090–0130, and a derivative belongs in both templates. Under Basel 3.1 the
    derivatives were being dropped from C 07.00 entirely, understating SA exposure value and RWEA.

    That sentence was never a scope decision; it rationalised a defect. Making a hidden scope
    decision *visible* is how it got caught — see the
    [changelog](../appendix/changelog.md) for the four templates the resulting fix moved.

## Coverage

Lineage is available for templates whose execution plan is exposed (`LINEAGE_PLANS`). Today that is
the **multi-sheet** templates **C 07.00** (SA credit risk, per obligor class), **C 08.01** (IRB
totals, per exposure class), **C 08.02** (IRB by PD grade, per exposure class), **C 08.04** (IRB RWEA
flow, per exposure class) and **CR7-A** (extent of IRB CRM techniques, per origin approach); the
**single-frame** COREP **C 08.07** (IRB scope of use) and the Basel-3.1-only **OF 02.01**
(output-floor comparison); and the single-frame Pillar 3 templates **OV1** (overview of RWEAs),
**CR4** (SA exposure and CRM effects), **CR5** (SA risk-weight allocation), **CR6-A** (scope of IRB
use), **CR7** (credit-derivatives effect on RWEA), **CR8** (IRB RWEA flow) and the Basel-3.1-only
**CMS1** / **CMS2** (modelled vs standardised RWEA, by risk type / by asset class). Any other
template — including C 34.x and CCR1–8, which are still imperative and have no `TemplateSpec` to
read — returns a clean `404`: *no lineage*, never a re-derived guess.

**C 08.04** and **CR7-A** are the first multi-sheet instrumentations since C 07.00: a lineage request
names the sheet (an exposure class for C 08.04, an origin approach for CR7-A). C 08.04 is the CR8-clone
RWEA flow — its provider drills the **current-period** view (no prior frame), so its opening (row 0010,
a `prior_period` cell) and residual (row 0080, a `formula` deriving from it) rows are **refused** with
the same distinct `404` as CR8's opening/residual rows, while the reported generator keeps threading
the prior frame. **C 08.07** and **OF 02.01** each carry post-execute passes (C 08.07's col-0040
percentage rescale and its fixed structural-null rows; OF 02.01's fixed out-of-scope rows) that live on
the *reported* frame — the drill-down reads a cell's value from there, so it honours them rather than
contradicting the sheet.

**C 08.01** and **C 08.02** are per-exposure-class IRB templates that share one value surface. C 08.01
carries the first large Annex II §1.3 "(-)" deduction set through lineage since C 07.00 (columns
0035/0040/0050/0060/0070/0102/0103/0256/0257/0290) — the sweep proves the sign-aware reconciliation on
a live negated cell (col 0256, the CRR SME supporting-factor adjustment, fires non-zero on the
*corporate_sme* sheet). Its Total-row col 0080 is the cross-sheet CRM substitution **inflow**, a
`side_context` cell whose plan threads the real per-class value (the C 07.00 pattern) — so it drills
down normally rather than being refused. C 08.02 breaks the same book down by **data-driven** rows
(firm rating grades, else PD bands) and deliberately holds col 0080 at a constant `0.0` at grade grain
(there is no obligor-basis grade home for a cross-class inflow); its string row-label column 0005 is
injected post-execute and is **not** an addressable report cell — the drill-down offers lineage only
for the numeric value columns.

**CMS1 / CMS2 and OF 02.01 are produced only under Basel 3.1**, so a lineage request for one on a CRR
run degrades to the same clean `404` as an uninstrumented template — the provider's `plans()` yields
nothing rather than crashing. **OV1** is the first instrumented template with an out-of-frame
`side_context` cell
(row 27's OF-ADJ) and a `first_non_null` cell (row 26's output-floor multiplier). The drill-down's plan
carries no output-floor summary, but the *reported* template is generated **with** the run's summary —
so row 27 would render null on the drill-down against a real figure on the screen. Rather than break
the never-disagree promise, the resolver **refuses** row 27 with a distinct `404` (*cell reads an
out-of-frame side value this drill-down does not carry*), exactly as CR8 refuses its prior-period rows.
The refusal is **conditional**, not blanket: C 07.00's col 0100 is also a `side_context` cell, but its
plan threads the real per-sheet substitution inflow, so that value is present and the cell drills down
normally. Row 26 (`first_non_null`) reads the sealed `output_floor_pct` and drills down normally.

A single-frame template has no sheet axis, so its cells report `sheet = null` and the `sheet` query
parameter is ignored. CR8 is the first template whose opening row (a `prior_period` cell) and residual
row (a `formula` deriving from it) carry **prior-period** figures. The drill-down runs on the
current-period ledger only, so it cannot reproduce those figures — asking for one returns a distinct
`404` (*cell derives from the prior period; drill-down covers the current-period ledger only*) rather
than a `200` with a null that would contradict a comparative-period report. The closing row (current
period) drills down normally. This keeps the never-disagree promise: a drill-down never shows a value
that differs from the figure on the screen.

The drill-down machinery is template-agnostic (the `SheetPlan` container lives in
`reporting/plans.py`, shared by every generator), so instrumenting the next template is small and
mechanical — a few lines, no new lineage logic:

1. **Extract the plan** — in the template's module, split `generate_<t>` into a
   `<t>_plans(results, cols, framework, errors) -> dict[str, SheetPlan]` builder plus a thin
   `generate_<t>` that executes each plan. Pass `negative_cols` **explicitly** (the Annex II §1.3
   "(-)" deduction set for this template, or `frozenset()` if it has none — it is required, so no
   template silently inherits another's sign convention). This extraction is number-neutral and
   golden-gated.
2. **Register it** — add one `_Provider` entry to `LINEAGE_PLANS` in `reporting/lineage.py`, wiring
   `plans=<t>_plans`, `generate=generate_<t>`, the population `scope` steps in words, and the
   `sheet_label`. For a template with no sheet axis (a single frame), set `single_frame=True`: its
   cells report `sheet = None` and its `plans()`/`generate()` return a one-entry dict.
3. **Add the tie-out** — append `(template_id, sheet)` to `_TIEOUT_CASES` in
   `tests/acceptance/reporting/test_lineage_tieout.py`. The parametrised sweep then checks every
   cell of that sheet (value, kind, predicate satisfaction, sign-aware reconciliation) with no new
   test code.
4. **Note the coverage** — add the template to the "Today that is …" line above.

## References

- Regulation (EU) 2021/451, Annex I/II — COREP; CRR Part 8 — Pillar III
- [Report Template Viewer](report-template-viewer.md) — where a cell key comes from
- `docs/plans/report-cell-lineage.md` — the design, and what is deliberately out of scope
