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
    "Standardised-approach legs, plus FCCM SFT rows (SA-CCR derivatives are excluded — they report under C 34)",
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

## Coverage

Lineage is available for templates whose execution plan is exposed (`LINEAGE_PLANS`). Today that is
**C 07.00**. Any other template — including C 34.x and CCR1–8, which are still imperative and have no
`TemplateSpec` to read — returns a clean `404`: *no lineage*, never a re-derived guess.

Instrumenting the next template is small and mechanical: expose its `<template>_plans()` (the same
extraction `c07.py` made, splitting plan-building from execution) and register it.

## References

- Regulation (EU) 2021/451, Annex I/II — COREP; CRR Part 8 — Pillar III
- [Report Template Viewer](report-template-viewer.md) — where a cell key comes from
- `docs/plans/report-cell-lineage.md` — the design, and what is deliberately out of scope
