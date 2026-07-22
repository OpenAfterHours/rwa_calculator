# Report Templates in the UI, then Cell Lineage / Drill-Down

**Status:** PROPOSED (rev 3) — re-reviewed 2026-07-12 against the **completed** Phase 7 estate, and
**re-phased**: the template viewer now leads, drill-down follows.
**Parent:** `docs/plans/phase7-declarative-reporting.md` (COMPLETE) — this is a consumer slice on the
sealed ledger + the one executor. No engine/aggregator/edge change.
**Original request:** generic lineage data model (run, template, cell, metric, filter criteria,
source records, stage) + one example end-to-end (COREP C 07.00 corporates RWA) + drill-down
endpoint/page + tests + a short doc page. Constraints: no breaking API changes, extensible,
minimally invasive.

---

## 1. Why the phasing changed (rev 3)

The requested journey is *"when a user sees a report cell, they can drill into it."* **Today there is
no report cell to see.** COREP and Pillar 3 exist in the UI only as download formats
(`ui/app/main.py:167` — `EXPORT_FORMATS = ("parquet","csv","excel","corep","pillar3")`); there is no
viewer page (`ui/app/templates/` holds landing/calculator/results/comparison/reconciliation, and
nothing else).

Building lineage first would therefore ship a drill-down page that **nothing links to** — a
standalone demo, reachable only by hand-constructing a URL, whose "cell" the user never actually
saw. The premise of the feature is the rendered report.

**So: render the templates first.** Three reasons beyond "it's the missing precondition":

1. **It is independently valuable.** Seeing C 07.00 on screen — rather than downloading an Excel to
   look at one number — is a real feature with zero lineage attached.
2. **It is cheap now, and it wasn't before Phase 7.** The bundles are already uniform data
   (`dict[str, DataFrame]` per sheet, or a single `DataFrame`), and the column headers/groups are
   frozen constants (`COREPColumn(ref, name, group)`; `get_c07_columns(framework)`). A generic
   renderer covers all ~20 templates; no per-template UI code.
3. **It de-risks the lineage design.** Rendering forces the presentation contract into the open —
   the per-class sheet selector, null-vs-zero cells, the Annex II "(-)" sign convention, the CRR/B31
   column-set variants. Lineage must agree with all of it. Building lineage first means *guessing*
   that contract; building the viewer first means lineage attaches to a cell key that a real
   consumer has already validated.

**The load-bearing design rule that makes this a reordering rather than a detour:** every cell the
viewer renders carries its **cell key** (`template_id`, `sheet`, `row_ref`, `col_ref`) as data
attributes. Phase C then wires drill-down to an existing key — a link, not a redesign.

This does not delay the lineage work materially: Phase B's first slice (the `c07_plans` extraction)
is independent of the UI and can land in parallel.

---

## 2. Premise review — what stands, what the completed Phase 7 changed

### 2.1 Lineage is a stored QUERY, never stored source-record IDs

The original model persisted "source record IDs" per cell. That is an inverted index of the cell's
filter, and it is the wrong shape here: it multiplies the ledger by the cell count per template
(every leg feeds the class total, its RW-band row, its on/off-BS row, its CCF bucket…), and — worse
— it is a *second representation* of the cell computation that can silently disagree with the
reported number.

This is now more than an argument; it is the shape of the code. Phase 7 S7/S8 landed
`reporting/cellspec.py` and per-template modules, and **a cell's lineage IS its spec**:

```python
# reporting/corep/c07.py:609  — the requested cell, verbatim
"0220": CellSpec(Sum(rwa_col), predicate=member)      # member = RowPredicate(equals=terms)
```

`corep/generator.py` fell from **5,179 → 899 LOC**; every credit-risk COREP + Pillar 3 template now
runs through the one `execute()`. The executor even exposes the machinery this feature needs
(`RowPredicate.apply`; the public `subset_rows` / `matched_counts` at `cellspec.py:434,464`).

**Decision: v1 does not declare lineage — it READS the specs that already exist.** A hand-authored
lineage registry would today be a second, drifting copy of `c07.py` — the same failure the row-ID
table was rejected for, one level up. `run_id` stays a runtime parameter; the query is
run-independent.

**Consequence — coverage is generic, not one-cell.** Reading the real specs means the *mechanism*
covers every cell of every declarative template (~20). v1 still wires **C 07.00 only** as the
tested, documented example.

### 2.2 "Calculation stage" — an axis, trimmed deliberately

Cell → contributing-rows (horizontal) and row → rule/stage provenance (vertical) are different
features. v1 answers the vertical question with the row's already-sealed explanatory columns plus a
`basis` label (`aggregator_exit`) and a named `scope` chain; a cross-stage provenance graph is its
own plan (§7). Partial machinery already exists for it (`floor_impact`,
`supporting_factor_impact`, `guarantee_rwa_benefit`, the opt-in `audit_cache`).

### 2.3 Contributing rows are LEGS, not exposures

Guaranteed exposures are physically split (`__G_<guarantor>` / `__REM` / `__REM_FL` / `__REM_SEN`).
A drill-down that presents bare rows will draw "unknown exposure" bug reports. Every row projection
carries `exposure_reference`, `source_exposure_reference`, `reporting_leg_role`, `reporting_class`,
`reporting_class_origin`, `reporting_method`, `reporting_ead`, `risk_weight`, `rwa_final`,
`guarantee_rwa_benefit`. The doc page explains the two-leg ledger in one paragraph.

---

## 3. Phase A — the template viewer (leads)

### A.1 Read path
`CalculationResponse` (a `ResultsSource`) → `COREPGenerator.generate(response)` /
`Pillar3Generator.generate(response)` → `COREPTemplateBundle` / `Pillar3TemplateBundle`.

Bundle shape (already uniform enough for one renderer):
- **per-sheet dicts** (`dict[str, DataFrame]`): `c07_00`, `c08_01..06` (by class), `c09_01`/`c09_02`
  (by country), `c34_02` (by netting set), `cr6`, `cr7a`, `cr9`, `cr9_1`, `cr10`
- **single frames**: `c08_07`, `of_02_01`, `c_02_00`, `c34_01/04/08`, `ov1`, `cr4`, `cr5`, `cr6a`,
  `cr7`, `cr8`, `cms1`, `cms2`, `ccr1/2/3/8`
- every frame: `row_ref`, `row_name`, then one Float64 column per column ref
- headers/groups from the frozen layout constants (`COREPColumn(ref, name, group)`, `P3Column`)
- **template ids are already a real key space** — the bundle field names *are* the ids in
  `ReportingTemplateSet.corep` / `.pillar3` (`rulebook/model.py:274`), pack-cited per regime.

### A.2 Slices
- **A1 — bundle cache.** Generating a bundle per page view is wasteful; cache per `run_id` beside
  `_RUNS` (`rest.py:63`), same lifecycle. (Template generation is 7–15× faster post-Phase-7, so this
  is a comfort, not a rescue.)
- **A2 — `GET /api/templates` + `GET /api/templates/{template_id}`** (additive; mirrors
  `/api/results` conventions: `_require_run`, `_RESP_404`, `.fill_nan(None)`, `{columns, rows}`).
  The list endpoint returns available ids + sheet keys for the run's framework; the detail endpoint
  returns one sheet's rows plus the column headers/groups. Export endpoints untouched.
- **A3 — the viewer page.** `ui/views/templates.py` (pure) + route `GET /results/{run_id}/templates`
  + `report_templates.html`: template picker → sheet picker (for dict templates) → the grid, with
  grouped column headers, right-aligned numerics, and **null rendered distinctly from 0.0** (the
  COREP-zero vs Pillar 3-null drift is real and must not be flattened in the UI). Link from
  `results.html`.
- **A4 — the cell-key contract (the hinge).** Every value cell renders
  `data-template`, `data-sheet`, `data-row`, `data-col`. Phase C reads exactly these. Pin it with a
  view-level test so it cannot regress.
- **A5 — docs + changelog.**

### A.3 Presentation facts the viewer must respect (found in the code, not invented)
- Cells are **post-post-pass**: inert/empty rows render all-null (`_null_empty_rows`), and the Annex
  II §1.3 "(-)" columns (`0030 0035 0050 0060 0070 0080 0090 0130 0140`) are **negated**
  (`_negate_deduction_cols`). The viewer shows what the generator produced; it does not re-sign.
- Column sets are framework-variant (CRR C 07.00 = 24 cols; B31 OF 07.00 = 22, adding `0035`/`0171`/
  `0235`, dropping the supporting-factor `0215-0217`).
- Some cells are **structurally null** (never-produced sources — e.g. `0230`/`0235` need `sa_cqs`,
  which the seal strips). They look identical to "genuinely zero" today. Phase B is what finally
  distinguishes them (§4.2) — worth knowing the viewer alone cannot.

---

## 4. Phase B — lineage core + API

### 4.1 The one structural obstacle, and the fix
`execute(spec, frame, ctx)` does **not** see the sealed ledger — it sees a frame the module prepared.
For C 07.00 (`c07.py:197-224`): population filter (SA book + FCCM SFT synthetics; SA-CCR excluded →
C 34) → Art. 112(1)(g) specialised-lending-into-corporate merge → `_prepare` derived discriminators
(`c07_defaulted`, `c07_rw_band`, `c07_ccf_bucket`, `c07_bs`, `c07_substituted`, …) → partition by
`reporting_class_origin`.

A lineage module re-implementing those four steps is exactly the drifting copy §2.1 rejects.
**Extract, don't duplicate:**

```python
# reporting/corep/c07.py — number-neutral extraction of the existing body
@dataclass(frozen=True)
class SheetPlan:
    spec: TemplateSpec
    frame: pl.DataFrame              # prepared, partitioned sheet frame
    ctx: ReportingContext
    row_terms: dict[str, _Terms | None]
    negative_cols: frozenset[str]

def c07_plans(results, cols, framework, errors) -> dict[str, SheetPlan]: ...

def generate_c07(...):               # becomes the consumer of c07_plans
```

Gated by the C 07.00 goldens (structure-exact, rtol 1e-9). **This is the only edit to existing
production code in the entire feature.**

### 4.2 The model — `src/rwa_calc/reporting/lineage.py` (new)
Frozen dataclasses; `from __future__ import annotations`; entry point takes the **`ResultsSource`**
protocol (`reporting/metadata.py:41`) because arch check 12 forbids `reporting` importing
`rwa_calc.api`/`ui` — even under `TYPE_CHECKING`.

```python
@dataclass(frozen=True)
class FilterTerm:
    column: str
    op: Literal["eq", "in", "between", "any_of"]
    value: object
    source: Literal["ledger", "derived"]      # sealed column vs module discriminator

@dataclass(frozen=True)
class CellQuery:                              # run-INDEPENDENT; read off the TemplateSpec
    template_id: str                          # "c07_00" — the ReportingTemplateSet id space
    sheet: str | None                         # "corporate"
    row_ref: str; col_ref: str; row_name: str
    kind: Literal["rows","formula","side_context","prior_period","constant","unbound"]
    metric: str | None                        # "sum" | "weighted_avg" | ...
    metric_columns: tuple[str, ...]           # ("rwa_final",)
    filter_terms: tuple[FilterTerm, ...]      # template predicate ∧ cell predicate, flattened
    scope: tuple[str, ...]                    # the module scope chain (§4.1), in words
    refs: tuple[str, ...]                     # Formula: the cells it derives from
    basis: str = "aggregator_exit"
    sign: Literal["positive", "negated"] = "positive"

@dataclass(frozen=True)
class CellLineage:                            # the answer for ONE run
    query: CellQuery
    run_id: str
    cell_value: float | None                  # AS REPORTED — read from the generated template
    contribution_total: float | None          # recomputed from the contributing rows
    total_rows: int
    rows: pl.DataFrame
```

**The six `kind`s fall straight out of the binding vocabulary — this is what makes the model generic
rather than C07-shaped, and it is the honest answer to "which rules contributed":**

| kind | binding | what the drill-down shows |
|---|---|---|
| `rows` | `Sum`/`SafeSum`/`Mean`/`WeightedAvg`/`Ratio`/`Count`/`FirstNonNull` | the contributing ledger legs — the main journey |
| `formula` | `Formula` (C07 `0040`/`0110`/`0150` waterfalls) | the referenced cells — "derived from 0010 − 0030", not rows |
| `side_context` | `SideContext` (C07 `0100` substitution inflow) | the out-of-frame value + its `ReportingContext` key |
| `prior_period` | `PriorPeriod` (CR8, C 08.04 opening RWEA) | the prior run's rows |
| `constant` | the structural-null Formulas (`0210`/`0211`/`0240`; `0230`/`0235` sans `sa_cqs`) | "not produced — permanently null (Phase 7 F6)" |
| `unbound` | no `CellSpec` | "template empty-cell policy: 0.0 (COREP) / null (Pillar 3)" |

The last two are why a user can finally tell a **structurally empty** cell from a **genuinely zero**
one — something Phase A alone cannot do.

Resolution: `LINEAGE_PLANS: dict[str, PlanFn] = {"c07_00": c07_plans}` — one entry in v1; each
further template is that same extraction plus one line. **C 34.01/02/04/08 and CCR1/2/3/8 remain
imperative** (the Phase 7 S8-pre deferral) — they have no spec, so they 404 with that reason,
stated in the docs rather than hidden.

### 4.3 Two honesty requirements
The rendered cell is not the raw executor output (`_null_empty_rows`, `_negate_deduction_cols` —
§3.3). So:
1. **`cell_value` is read from the generated template** — the number the user clicked is ground
   truth, never recomputed.
2. **`contribution_total` is the sum over returned rows**, with `CellQuery.sign` recording the
   negation policy; a test asserts `cell_value == ±contribution_total`. (The example cell `0220` is
   `positive` — but the model is right for the deduction columns from day one.)

### 4.4 API
`GET /api/lineage?run_id=&template=c07_00&sheet=corporate&row=0010&col=0220&offset=&limit=`
— mirrors `/api/results` (`rest.py:221-237`) exactly, extended with `cell`, `kind`, `metric`,
`filter_terms`, `scope`, `basis`, `sign`, `cell_value`, `contribution_total`. Echoing the predicate
back makes the endpoint self-describing — that *is* the requested "filter criteria" field.
Uninstrumented template / unknown cell → clean **404** with the reason. No existing endpoint changes.

### 4.5 Slices
- **B1** `c07_plans` extraction (number-neutral; golden-gated).
- **B2** `reporting/lineage.py` + unit tests — a `CellQuery` for each of the six kinds off the real
  C07 spec; predicate flattening incl. `any_of`/`between`; ledger-vs-derived term classification;
  pagination/sort; unknown cell → None.
- **B3 — the fidelity tie-out (correctness anchor).**
  `tests/acceptance/reporting/test_lineage_tieout.py`: run `tests/fixtures/reporting_portfolio.py`
  through the real pipeline (reuse the golden-gate fixture); for C 07.00 / corporate assert
  (a) `cell_value` equals the bundle's cell (rtol 1e-9); (b) `contribution_total == ±cell_value` per
  `sign`; (c) every returned row satisfies the declared predicate; (d) **sweep every row × column of
  the sheet**: the lineage `kind` is consistent with the rendered cell (a `rows` cell with an empty
  subset renders null; a `constant` cell renders null). The sweep is what makes the model
  trustworthy beyond the one showcased cell.
- **B4** `GET /api/lineage` + integration tests (happy path, 404 unknown run, 404 uninstrumented
  template, 404 unknown cell, paging clamps; existing `/api/results` tests untouched).

**Arch constraints for B2/B4** (verified against `scripts/arch_check.py`): no `rwa_calc.api`/`ui`
import (check 12); **no multi-candidate `pick(cols, a, b)`** — the `reporting_multi_candidate_picks`
ratchet sits at 30 and may not increase; module ≤ 2,010 LOC, new `tests/unit/reporting/**` file
≤ 1,581 LOC (ample headroom). No new reporting module trips a count ratchet.

### 4.6 Phase 0 — machinery generalisation (R19, DONE)

v1 shipped with C 07.00 as the sole instrumented template, and the drill-down machinery still
carried C07-shaped assumptions. R19 generalised it so the remaining declarative templates (R20-R26)
can be instrumented with a few lines each. What changed from §4.1/§4.2 as written:

- **`SheetPlan` moved out of `corep/c07.py` into the shared `reporting/plans.py`.** Every template's
  `<t>_plans()` returns the SAME `SheetPlan`, so no template is typed against another's dataclass.
  `c07.py` imports it back; the extraction stayed golden-byte-identical.
- **`negative_cols` is now a REQUIRED `SheetPlan` field (no default).** It previously defaulted to
  C 07.00's Annex II deduction set — a silent mis-sign risk for any future template sharing refs
  like `0030`/`0050`/`0090`. Each template passes its own set (or `frozenset()`) explicitly.
- **Single-frame templates** (cr4, cr7, cr8, ov1, cms1/2, c08_07, of_02_01, …) register with
  `_Provider(single_frame=True)`: their cells report `sheet = None` and their `plans()`/`generate()`
  return a one-entry dict. `_resolve_sheet_key` (in `reporting/lineage.py`) is the one place that
  decides the plan key vs the reported sheet, and `sheet_lineage` logs loudly if `plans()` and
  `generate()` key differently.
- **REST `sheet` normalisation + differentiated 404s.** `GET /api/lineage` normalises an empty-string
  `sheet` to `None` (matching the UI), and both surfaces now 404 with a reason — *template not
  instrumented* vs *unknown cell* vs *unknown run* — instead of one undifferentiated "no lineage".
- **The fidelity tie-out is parametrised** over `_TIEOUT_CASES`, so an R20-R26 template earns its
  full sweep (value, kind, predicate satisfaction, sign-aware reconciliation) by adding one tuple.

The per-template recipe lives in `docs/features/report-cell-lineage.md` (§ Coverage).

---

## 5. Phase C — wire the drill-down into the cell

Each value cell in the viewer becomes a link/target on its A4 cell key → a lineage panel (or the
standalone page) showing the plain-English predicate, the scope chain, and the paginated
contributors. **This is the journey as originally requested, and by this point it is a link plus a
template partial** — the API, the model, and the tests already exist.

Also here: the small `ui/views/lineage.py` + `cell_lineage.html`, view unit tests, and the docs page
(`docs/reporting/cell-lineage.md`) covering the journey, the query-not-materialised decision, the
two-leg ledger caveat, the six cell kinds, the sign/null post-pass caveat, current coverage, and the
~10-line recipe to instrument the next template.

---

## 6. Mapping to the requested data model

| Requested field | Where it landed |
|---|---|
| run ID | runtime parameter (`CellLineage.run_id`); the query itself is run-independent |
| template ID | `CellQuery.template_id` — the existing `ReportingTemplateSet` id space |
| cell ID | `(sheet, row_ref, col_ref)` — and the Phase A `data-*` cell key |
| metric | `kind` + `metric` + `metric_columns`, read off the `ValueBinding` |
| filter criteria | `filter_terms` + `scope`, read off `RowPredicate` + the module plan |
| source record IDs | **derived on demand, never stored** (§2.1) |
| calculation stage | `basis` + `scope` + per-row explanatory columns; cross-stage provenance deferred (§7) |

---

## 7. Invariants and out-of-scope

**Invariants.** (1) Additive only — no existing endpoint/bundle/template output changes; the 95
goldens untouched. (2) **One source of truth** — lineage reads the same `TemplateSpec` the generator
executes; a template whose plan cannot be extracted is *not instrumented* (404), never re-derived.
(3) **Reported value wins** — `cell_value` comes from the generated template. (4) Reads only the
sealed ledger + `ReportingContext` (the sealed-column allowlist ratchet was *deferred* at Phase 7
Sn, so this is a review criterion, not a machine check). (5) Uninstrumented = clean 404, never a
fallback computation.

**Out of scope for v1.** Materialised lineage tables (§2.1). Cross-stage per-row provenance (its own
plan). Templates beyond C 07.00 for lineage (the viewer shows them all; lineage wiring is
per-template and cheap). C 34.x / CCR1/2/3/8 (still imperative — no spec to read). Editing or
annotating cells.
