# Report Cell Lineage / Drill-Down — v1 Vertical Slice

**Status:** PROPOSED (rev 2) — **re-reviewed 2026-07-12 against the completed Phase 7 estate.**
Rev 1 (2026-07-11) was written when CellSpec did not exist; its central sequencing decision is
now obsolete and is superseded below. The design is materially simpler and materially more
general as a result.
**Parent:** `docs/plans/phase7-declarative-reporting.md` (COMPLETE) — this is a consumer slice
built on the sealed ledger + the one executor.
**Requested scope:** generic lineage data model (run, template, cell, metric, filter criteria,
source records, stage) + one example end-to-end (COREP C 07.00 corporates RWA) + drill-down
endpoint/page + tests + a short doc page. Constraints: no breaking API changes, extensible,
minimally invasive.

---

## 1. What changed since rev 1 — and why the plan gets smaller

Rev 1 reasoned: *"CellSpec/TemplateSpec don't exist yet (Phase 7 S7); don't wait, and don't invent
a rival vocabulary — hand-author one registry entry using the Phase-7 predicate vocabulary, and
record that S7/S8 supersede it."*

**S7 and S8 have since landed. That supersession is now due, before the feature is built.** The
predicate vocabulary is real code, and every credit-risk COREP + Pillar 3 template is executed
through it:

- `reporting/cellspec.py` (608 LOC) — `RowPredicate`, the binding verbs (`Sum`, `SafeSum`, `Mean`,
  `WeightedAvg`, `Ratio`, `Count`, `FirstNonNull`, `SideContext`, `PriorPeriod`, `Formula`),
  `CellSpec`, `TemplateSpec`, and the one `execute()`.
- Per-template modules: `corep/{c02,c07,c08,c09,of02}.py`, `pillar3/{cr4..cr10,ov1,cms1,cms2}.py`.
- `corep/generator.py` fell from **5,179 → 899 LOC**.

The requested cell is now *literally a declarative object in the codebase*. C 07.00, row 0010
(Total exposures), column 0220 (RWEA) is:

```python
# reporting/corep/c07.py:609
"0220": CellSpec(Sum(rwa_col), predicate=member)      # member = RowPredicate(equals=terms)
```

with `terms == ()` for row 0010, executed over the sheet frame produced by `generate_c07`
(`c07.py:197-224`): population filter → SL-into-corporate merge → derived discriminator columns →
partition by `reporting_class_origin`.

**Therefore: v1 must not declare lineage. It must READ the specs that already exist.**

Rev 1's hand-authored registry entry would today be a *second, drifting copy* of `c07.py` — the
exact failure rev 1 argued against when it rejected materialised row-ID tables. Same argument, one
level up.

### 1.1 What survives from rev 1 (re-confirmed, now structurally guaranteed)

**Lineage is a QUERY, not stored source-record IDs.** Rev 1 argued this on duplication and
drift-risk grounds. It is now stronger than an argument — it is the shape of the code: a cell's
lineage *is* `spec.predicate ∧ spec.cells[(row, col)].predicate`, and the executor already exposes
the machinery to evaluate it (`RowPredicate.apply`, and the public `subset_rows` / `matched_counts`
kernels at `cellspec.py:434,464`, which read as if they were built for this question).

Persisting cell→row memberships would multiply the ledger by the cell count per template and could
silently disagree with the reported number. **Decision unchanged: derive contributing rows on
demand from the same spec object the generator ran.** `run_id` stays a runtime parameter.

### 1.2 What this buys: coverage becomes generic, not one-cell

Rev 1's model covered exactly one hand-authored cell. Reading the real specs means the *mechanism*
covers **every cell of every declarative template** — roughly 20 templates across COREP and
Pillar 3 — with per-template wiring that is a few lines each (§2.2). v1 still ships **C 07.00 only**
as the wired, tested, documented example (the requested thin slice); the rest are a clean 404 and a
short registration.

---

## 2. Target design

### 2.1 The one structural obstacle, and the fix

`execute(spec, frame, ctx)` does **not** see the sealed ledger. It sees a frame the template module
prepared. For C 07.00 (`c07.py:197-224`) that is four steps:

1. `c07_population(results, cols)` — SA book (`reporting_approach_origin == "standardised"`) plus
   FCCM SFT synthetics (`risk_type == "CCR_SFT"`); SA-CCR derivatives excluded (they report C 34).
2. Art. 112(1)(g) merge — `specialised_lending` rows relabelled `corporate` before keying.
3. `_prepare(...)` — the module-derived discriminator columns (`c07_defaulted`, `c07_rw_band`,
   `c07_ccf_bucket`, `c07_bs`, `c07_substituted`, …) that the row predicates key on.
4. Partition by `reporting_class_origin` → one sheet per obligor class.

A lineage module that re-implemented those four steps would be exactly the drifting copy §1 rejects.

**Fix — extract, don't duplicate.** Refactor `generate_c07` to build its execution plan through a
new module-public function, and have both the generator and lineage consume it:

```python
# reporting/corep/c07.py  (number-neutral extraction of the existing body)
@dataclass(frozen=True)
class SheetPlan:
    spec: TemplateSpec
    frame: pl.DataFrame            # the prepared, partitioned sheet frame
    ctx: ReportingContext
    row_terms: dict[str, _Terms | None]
    negative_cols: frozenset[str]  # the Annex II §1.3 "(-)" post-pass set

def c07_plans(results, cols, framework, errors) -> dict[str, SheetPlan]: ...

def generate_c07(results, cols, framework, errors) -> dict[str, pl.DataFrame]:
    return {
        sheet: _negate_deduction_cols(_null_empty_rows(execute(p.spec, p.frame, p.ctx), ...))
        for sheet, p in c07_plans(results, cols, framework, errors).items()
    }
```

This is a mechanical extraction of code that already exists, gated by the 95 goldens (the C 07.00
goldens are structure-exact + rtol 1e-9). It is the only change to an existing production module in
the whole feature.

### 2.2 The generic lineage model — `src/rwa_calc/reporting/lineage.py` (new)

Frozen dataclasses, `from __future__ import annotations`, no upward imports (arch check 12:
`reporting` may not import `rwa_calc.api` / `rwa_calc.ui`, even under `TYPE_CHECKING` — so the entry
point takes the **`ResultsSource`** protocol at `reporting/metadata.py:41`, exactly as the
generators do).

```python
@dataclass(frozen=True)
class FilterTerm:
    """One human-readable criterion: column, op, value, and whether it is a
    SEALED ledger column or a module-derived discriminator."""
    column: str
    op: Literal["eq", "in", "between", "any_of"]
    value: object
    source: Literal["ledger", "derived"]

@dataclass(frozen=True)
class CellQuery:
    """The run-INDEPENDENT lineage record, read off the TemplateSpec."""
    template_id: str                     # "c07_00" — the ReportingTemplateSet id space
    sheet: str | None                    # "corporate" (None for single-frame templates)
    row_ref: str                         # "0010"
    col_ref: str                         # "0220"
    row_name: str
    kind: Literal["rows", "formula", "side_context", "prior_period",
                  "constant", "unbound"]
    metric: str | None                   # "sum" | "safe_sum" | "weighted_avg" | ...
    metric_columns: tuple[str, ...]      # ("rwa_final",)
    filter_terms: tuple[FilterTerm, ...] # template predicate ∧ cell predicate, flattened
    scope: tuple[str, ...]               # the module scope steps (§2.1) in words
    refs: tuple[str, ...]                # Formula: the cells it derives from
    basis: str = "aggregator_exit"       # the sealed edge the query runs on
    sign: Literal["positive", "negated"] = "positive"   # Annex II §1.3 post-pass

@dataclass(frozen=True)
class CellLineage:
    """The answer for ONE run."""
    query: CellQuery
    run_id: str
    cell_value: float | None        # AS REPORTED — read from the generated template
    contribution_total: float | None  # recomputed from the contributing rows
    total_rows: int
    rows: pl.DataFrame              # paginated projection
```

**The six `kind`s are the honest answer to "which rules contributed", and they fall straight out of
the binding vocabulary** — this is what makes the model generic rather than C07-shaped:

| kind | when | what the drill-down shows |
|---|---|---|
| `rows` | `Sum`/`SafeSum`/`Mean`/`WeightedAvg`/`Ratio`/`Count`/`FirstNonNull` | the contributing ledger legs (the main journey) |
| `formula` | `Formula` (C07 0040/0110/0150 waterfalls) | the referenced cells — "derived from 0010 − 0030", not rows |
| `side_context` | `SideContext` (C07 0100 substitution inflow) | the out-of-frame value + its `ReportingContext` key |
| `prior_period` | `PriorPeriod` (CR8, C 08.04 opening RWEA) | the prior run's rows |
| `constant` | the structural-null Formulas (0210/0211/0240; 0230/0235 when `sa_cqs` is unsealed) | "not produced — permanently null (Phase 7 F6)" |
| `unbound` | no CellSpec | "template empty-cell policy: 0.0 (COREP) / null (Pillar 3)" |

That last pair matters: the drill-down tells the truth about cells that are structurally empty
rather than inventing a filter for them. Today a user cannot tell an empty cell from a
never-produced one.

Resolution + execution:

```python
type PlanFn = Callable[..., dict[str | None, SheetPlan]]
LINEAGE_PLANS: dict[str, PlanFn] = {"c07_00": c07_plans}   # v1: one entry

def describe_cell(plan, sheet, row_ref, col_ref) -> CellQuery         # spec -> record
def drilldown(source: ResultsSource, template_id, sheet, row_ref, col_ref,
              *, offset, limit) -> CellLineage | None                  # None = not instrumented
```

Extending to any other declarative template = extract its `*_plans` the same way and add one
`LINEAGE_PLANS` entry. **C 34.01/02/04/08 and CCR1/2/3/8 remain imperative** (never strangled —
the Phase 7 S8-pre deferral) and therefore have **no** lineage; they 404 with that reason. This is
stated in the doc page rather than hidden.

### 2.3 Two honesty requirements (new in rev 2 — post-passes did not exist in rev 1's model)

The rendered template cell is **not** the raw executor output. Two module post-passes run after
`execute()`:

- `_null_empty_rows` — a row whose subset is empty renders **all-null**, not zeros.
- `_negate_deduction_cols` — Annex II §1.3 "(-)"-labelled columns (`0030 0035 0050 0060 0070 0080
  0090 0130 0140`) are **negated** after the waterfalls consumed positive magnitudes.

So a drill-down that recomputes a cell from rows can legitimately disagree in *sign* with what the
user clicked. v1 handles this explicitly rather than accidentally:

1. **`cell_value` is read from the generated template frame** — the number the user actually saw is
   ground truth, never recomputed.
2. **`contribution_total` is the sum over the returned rows**, and `CellQuery.sign` records whether
   the column is in the negation set. A test asserts `cell_value == ±contribution_total` per the
   recorded sign policy. (The example cell, 0220, is `positive` — but the model is correct for the
   deduction columns from day one.)

### 2.4 Grain warning (carried from rev 1 — still load-bearing)

Contributing rows are **legs**, not exposures: guaranteed exposures are physically split into
`__G_<guarantor>` / `__REM` / `__REM_FL` / `__REM_SEN`. The row projection therefore always carries
`exposure_reference`, `source_exposure_reference`, `reporting_leg_role`, `reporting_class`,
`reporting_class_origin`, `reporting_method`, `reporting_ead`, `risk_weight`, `rwa_final`, and
`guarantee_rwa_benefit` (sealed at Phase 7 F8) — sorted by the metric column descending, so the
biggest contributors surface first. The doc page explains the two-leg ledger in one paragraph.

*(C 07.00 keys the obligor-origin class, so its sheets do not mix in guarantor-class inflow legs —
the columns are returned anyway so the model generalises unchanged to post-substitution-keyed
templates such as Pillar 3 CR5.)*

### 2.5 API — one additive endpoint

```
GET /api/lineage?run_id=&template=c07_00&sheet=corporate&row=0010&col=0220&offset=0&limit=50
```

Mirrors `GET /api/results` (`rest.py:221-237`) exactly: `_require_run(run_id)` → 404 on unknown run
(reuse `_RESP_404`), `limit` clamped to `_MAX_PAGE`, `.fill_nan(None)` before `to_dicts()`, and the
same envelope `{run_id, total, offset, limit, columns, rows}` — extended with `cell` (identity +
`row_name` + citation), `kind`, `metric`, `filter_terms`, `scope`, `basis`, `sign`, `cell_value`,
`contribution_total`. Echoing the predicate back makes the endpoint self-describing: that *is* the
"filter criteria" field the request asked for.

An uninstrumented template/cell → **404** with the reason (`"template c34_01 is not declarative —
no lineage"` / `"unknown cell"`). No existing endpoint, model, or response shape changes.

### 2.6 UI — one page, recon-explorer pattern

`ui/views/lineage.py` (pure, no FastAPI/Jinja) → route `GET /results/{run_id}/lineage` in
`ui/app/main.py::_register_pages` → `cell_lineage.html` (extends `base.html`): cell identity +
citation, the reported value, the predicate rendered in plain English ("Standardised-approach legs,
plus FCCM SFT rows, whose obligor class is corporate (specialised lending merged in per Art.
112(1)(g))"), the scope steps, then the paginated contributors table. One link added from
`results.html`.

**Scope note (unchanged from rev 1):** the UI does not render COREP templates on screen — COREP is
an export format today — so "click a cell in the report" cannot literally ship. v1 is the API plus a
standalone drill-down page. Rendering clickable templates is now cheap to add later precisely
because the templates are declarative.

### 2.7 What this deliberately does not touch

No engine, aggregator, contracts, or edge change (Phase 7 sealed every column needed). No generator
behaviour change — the only production edit to existing code is the number-neutral `c07_plans`
extraction inside `c07.py`. No new persistence. No changes to the 95 goldens.

---

## 3. Mapping to the requested data model

| Requested field | Where it landed |
|---|---|
| run ID | runtime parameter (`CellLineage.run_id`); the query itself is run-independent |
| template ID | `CellQuery.template_id` — the existing `ReportingTemplateSet` id space (`c07_00`, `cr5`, …) |
| cell ID | `(sheet, row_ref, col_ref)` |
| metric | `CellQuery.kind` + `metric` + `metric_columns`, read off the `ValueBinding` |
| filter criteria | `CellQuery.filter_terms` + `scope`, read off `RowPredicate` + the module plan |
| source record IDs | **derived on demand, never stored** (§1.1) |
| calculation stage | `basis` (`aggregator_exit`) + `scope` (population → merge → derive → partition) + the per-row explanatory columns. Cross-stage per-row provenance stays out of scope (§6). |

---

## 4. Execution slices

### L1 — `c07_plans` extraction (NUMBER-NEUTRAL)
Extract the plan-building body of `generate_c07` into `c07_plans(...) -> dict[str, SheetPlan]`;
`generate_c07` becomes its consumer. **Gate:** C 07.00 goldens structure-identical (rtol 1e-9);
`tests/unit/reporting/corep/test_c07.py` green; full unit suite green.

### L2 — `reporting/lineage.py` + unit tests
The model, `LINEAGE_PLANS` (one entry), `describe_cell`, `drilldown`.
`tests/unit/reporting/test_lineage.py`: a `CellQuery` for each of the six `kind`s off the real C07
spec (rows / formula 0040 / side_context 0100 / constant 0210 / unbound / prior_period via a CR8
spec once instrumented); predicate flattening incl. `any_of` and `between`; ledger-vs-derived term
classification; pagination + sort; unknown cell → None.
**Arch constraints:** no `rwa_calc.api` / `rwa_calc.ui` import (check 12); **no multi-candidate
`pick(cols, a, b)`** — the `reporting_multi_candidate_picks` ratchet is at 30 and may not increase;
module ≤ 2,010 LOC and the new test file ≤ 1,581 LOC (existing MAX ratchets — ample headroom).

### L3 — Fidelity tie-out (the correctness anchor)
`tests/acceptance/reporting/test_lineage_tieout.py`: run `tests/fixtures/reporting_portfolio.py`
through the real pipeline (reuse the golden-gate fixture), generate the COREP bundle, and for
C 07.00 / corporate assert:
(a) `drilldown(...).cell_value` equals the bundle's cell (rtol 1e-9);
(b) `contribution_total == ±cell_value` per the recorded `sign` policy;
(c) every returned row satisfies the declared predicate; `total_rows > 0`;
(d) **sweep**: for *every* row×column of the corporates sheet, the lineage `kind` is consistent with
the rendered cell (a `rows` cell with an empty subset renders null; a `constant` cell renders null).
That sweep is what makes the model trustworthy beyond the one showcased cell.

### L4 — `GET /api/lineage` + integration tests
Happy path (value, rows, predicate echo), 404 unknown run, 404 uninstrumented template, 404 unknown
cell, paging clamps. Existing `/api/results` tests untouched (additive-API guard).

### L5 — UI page + view unit tests (§2.6).

### L6 — Docs + changelog
`docs/reporting/cell-lineage.md` (nav-registered): the journey, the query-not-materialised decision,
the two-leg ledger caveat, the six cell kinds, the sign/null post-pass caveat, current coverage
(C 07.00; C 34/CCR excluded and why), and the ~10-line recipe to instrument the next template.
`docs/appendix/changelog.md` under Unreleased. `uv run zensical build` green.

**Delivery:** one feature branch, L1–L6 as separate commits, one PR. Nothing here touches the
forced-single-stream file list, so it can also run as a normal `/next-items` worktree item.

---

## 5. Invariants

1. **Additive only** — no existing endpoint/bundle/edge/template output changes; goldens untouched.
2. **One source of truth** — lineage reads the same `TemplateSpec` object the generator executes.
   A lineage module that re-implements a template's row selection is the failure mode; if a
   template's plan cannot be extracted, it is not instrumented (404), never re-derived.
3. **Reported value wins** — `cell_value` comes from the generated template, never recomputed.
4. **Reads only the sealed ledger + `ReportingContext`** (Phase 7 invariant 4). Note: the sealed-
   column read-allowlist ratchet was *deferred* at Phase 7 Sn (it would fail on the F6 columns), so
   this is a review criterion here, not a machine check.
5. **Uninstrumented = clean 404**, never a fallback computation.

---

## 6. Out of scope for v1 (explicit)

1. Materialised lineage tables (banned by design, §1.1).
2. Cross-stage per-row provenance (row → which rule/stage set this RW). The vertical axis has
   partial machinery already (`floor_impact`, `supporting_factor_impact`, `guarantee_rwa_benefit`,
   the opt-in `audit_cache`, `classify/audit.py`); a provenance graph is its own plan.
3. Templates beyond C 07.00 (mechanism is generic; wiring is per-template and cheap).
4. C 34.x / CCR1/2/3/8 — still imperative; no spec to read (Phase 7 S8-pre deferral).
5. Rendered, clickable COREP/Pillar 3 templates in the UI.
