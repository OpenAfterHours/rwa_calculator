# Report Cell Lineage / Drill-Down — v1 Vertical Slice

**Status:** PROPOSED — premise reviewed 2026-07-11 against the Phase 7 declarative-reporting plan.
**Parent:** `docs/plans/phase7-declarative-reporting.md` (this feature is a Phase-7-adjacent consumer
slice; it builds on the S2 sealed reporting projection and pre-pins the S8 C07 predicate).
**Requested scope:** generic lineage data model (run, template, cell, metric, filter criteria,
source records, stage) + one end-to-end example (COREP C 07.00 corporates RWA) + drill-down
endpoint/page + tests + short doc page. Constraints: no breaking API changes, extensible,
minimally invasive.

---

## 1. Premise review — what changes vs the request

The user journey is right and the timing is good: Phase 7 S2 (merged 2026-07-11) sealed the
reporting projection (`reporting_class`, `reporting_class_origin`, `reporting_leg_role`,
`reporting_ead`, `reporting_rw`, …) on `AGGREGATOR_EXIT_EDGE`, so every column a drill-down needs
is already on the one canonical ledger that `CalculationResponse.scan_results()` reads. No engine,
aggregator, or edge change is needed — the whole slice is additive consumer code.

Two elements of the proposed data model are corrected:

### 1.1 Lineage is a stored QUERY, not stored source-record IDs

The proposed model persists "source record IDs" per cell. That is an inverted index of the cell's
filter, and it is the wrong shape for this codebase:

- **It duplicates massively.** Every ledger leg contributes to many cells (class-sheet total, RW-band
  row, on/off-BS row, CCF row, ECAI split…). Materialising memberships multiplies the ledger by the
  cell count per template.
- **It can silently disagree with the reported number.** A stored membership table is a second
  representation of the cell computation; any drift between it and the generator is invisible.
  Deriving rows from the same predicate that defines the cell makes agreement structural.
- **Phase 7 already decided this.** The measured cell taxonomy (§3.2 of the Phase 7 plan) shows the
  dominant cell kind is pure filter+aggregate over the sealed ledger; CellSpec = `RowPredicate` +
  `ValueBinding`. A cell's lineage **is** its predicate. And §8.6 bans introducing a new normalised
  frame beside the ledger.

Verified concretely for the example cell — C 07.00 corporates, row 0010, col 0220 (RWEA post
supporting factor) is exactly:

```
sum(rwa_final) over rows where
    (approach_applied == "standardised" OR risk_type == "CCR_SFT")
    AND exposure_class_applied ∈ {corporate, specialised_lending}   # SL merged per Art. 112(1)(g)
```

(`reporting/corep/generator.py::_c07_sa_data:4109`, `_generate_all_c07:1522-1556`,
`_c07_rwea_factor_cols:3330`.)

**Decision: the lineage record stores the query (predicate + metric + basis), never row IDs.
Contributing rows are derived on demand by applying the predicate to the run's sealed results
frame.** `run_id` is a runtime parameter of the drill-down, not a field of the spec — the spec is
run-independent, which is what makes it cacheable, testable, and eventually generatable from S7
`TemplateSpec`s.

### 1.2 "Calculation stage" is a different axis — trimmed to a `basis` label in v1

Cell → contributing-rows lineage (horizontal) and row → rule/stage provenance (vertical) are
different features. The vertical axis already has partial machinery: the sealed row carries its own
explanation (`reporting_leg_role`, `reporting_class_origin` vs `reporting_class`, `risk_weight`,
`sa_cqs`, approach columns), and the bundle carries per-row attribution frames (`floor_impact`,
`supporting_factor_impact`) plus the opt-in `audit_cache`. A full cross-stage provenance graph is a
large feature in its own right and is **out of scope for v1**.

v1 keeps a `basis` field on the lineage record (the sealed edge the query runs on —
`"aggregator_exit"`) and answers "which rules contributed" by returning the row's already-sealed
explanatory columns. Deeper per-row provenance is a recorded follow-up (§7).

### 1.3 Grain warning: contributing rows are LEGS, not exposures

The ledger is per-leg for guaranteed exposures (`__G_<guarantor>` / `__REM` / `__REM_FL` /
`__REM_SEN`). A corporate cell can contain an inflow leg whose *origin* class is something else
(guaranteed leg reporting under the guarantor's class). If the drill-down presents bare rows, users
will report "unknown exposures" as bugs. The response must therefore always include
`reporting_leg_role`, `reporting_class`, `reporting_class_origin`, and the base reference
(`source_exposure_reference` where sealed; otherwise derived), and the doc page must explain the
two-leg ledger in one paragraph.

*(Note: C07 sheets bucket on `exposure_class_applied` — the origin/applied class, uniform across
legs — so for THIS cell no cross-class inflow leg appears; the columns are still returned so the
model generalises to post-substitution-keyed cells without change.)*

### 1.4 Scope note: there is no rendered report to click yet

The UI does not render COREP templates on screen (COREP exists only as an export format), so
"click a cell in the report" cannot literally ship in v1. v1 ships the lineage API plus a
standalone drill-down page linked from the run's results page. Clickable rendered templates are a
natural later slice (after S8 stranglers migrate templates through the executor, rendering them
server-side becomes cheap).

### 1.5 Sequencing vs Phase 7 — build it CellSpec-shaped, don't wait for S7

CellSpec/`TemplateSpec` don't exist yet (S7). Waiting blocks the feature on S4–S6; building an
unrelated predicate language creates a rival vocabulary. The middle path: give the v1 lineage model
**exactly the Phase-7 §3.2 predicate vocabulary** (a subset of `RowPredicate` fields + a `Sum`
binding), hand-author the single registry entry for the example cell, and record that S7/S8
supersede the hand-authored entry by generating lineage records from `TemplateSpec`s. The v1
tie-out test then doubles as an early pin of the C07 predicate — de-risking the S8 C07 strangler
(F4).

---

## 2. Target design

### 2.1 Data model — `src/rwa_calc/reporting/lineage.py` (new module)

All frozen dataclasses; no Polars namespace registration; module logger; full type hints.

```python
@dataclass(frozen=True)
class LineagePredicate:
    """Row-selection criteria, compiled to a single pl.Expr against sealed column names.

    Field vocabulary deliberately mirrors the Phase 7 §3.2 RowPredicate so S7 can absorb it.
    Only sealed AGGREGATOR_EXIT_EDGE names — no candidate ladders (Phase 7 invariant 5).
    """
    approaches: tuple[str, ...] = ()          # approach_applied ∈ …
    include_risk_types: tuple[str, ...] = ()  # OR-branch: risk_type ∈ … (e.g. CCR_SFT)
    classes: tuple[str, ...] = ()             # exposure_class_applied ∈ …
    leg_role: str | None = None               # reporting_leg_role
    on_balance_sheet: bool | None = None      # reporting_on_balance_sheet

@dataclass(frozen=True)
class LineageMetric:
    kind: Literal["sum"]                      # v1: Sum only (kind 1, the dominant taxonomy kind)
    column: str                               # e.g. "rwa_final"

@dataclass(frozen=True)
class CellLineage:
    template_id: str                          # "C_07.00"
    sheet: str | None                         # exposure-class sheet key, e.g. "corporate"
    row_ref: str                              # "0010"
    col_ref: str                              # "0220"
    label: str                                # human-readable cell name
    metric: LineageMetric
    predicate: LineagePredicate
    basis: str = "aggregator_exit"            # sealed edge the query runs on
    citation: str | None = None               # e.g. "Reg 2021/451 Annex I, C 07.00"
```

Registry + resolution + execution (module-level, plain typed functions):

```python
LINEAGE_REGISTRY: dict[tuple[str, str | None, str, str], CellLineage]  # ONE entry in v1

def resolve_cell(template_id, sheet, row_ref, col_ref) -> CellLineage | None
def compile_predicate(p: LineagePredicate) -> pl.Expr
def drilldown(results: pl.LazyFrame, cell: CellLineage, *, offset, limit) -> LineageDrilldown
```

`LineageDrilldown` (frozen) carries: `cell_value: float | None`, `total_rows: int`,
`rows: pl.DataFrame` (paginated projection), `columns: tuple[str, ...]`. The row projection is a
fixed explanatory set: `exposure_reference`, `source_exposure_reference` (if sealed; else derived
by suffix-strip), `reporting_leg_role`, `reporting_class`, `reporting_class_origin`,
`reporting_method`, `ead_final`, `risk_weight`, `rwa_final`, `sa_cqs`. Sorted `rwa_final`
descending so the biggest contributors surface first.

The v1 registry entry:

```python
CellLineage(
    template_id="C_07.00", sheet="corporate", row_ref="0010", col_ref="0220",
    label="Corporates — risk weighted exposure amount post supporting factors",
    metric=LineageMetric("sum", "rwa_final"),
    predicate=LineagePredicate(
        approaches=("standardised",),
        include_risk_types=("CCR_SFT",),
        classes=("corporate", "specialised_lending"),   # Art. 112(1)(g) SL merge
    ),
    citation="Reg 2021/451 Annex I, C 07.00 col 0220; CRR Art. 112(1)(g)",
)
```

Notes:
- The predicate reads **exact sealed names** (`approach_applied`, `exposure_class_applied`,
  `risk_type`, `rwa_final`) — no `_pick` ladders (Phase 7 invariant 5 / §9 ban). The legacy
  generator's ladders exist for pre-existing frames; lineage only ever runs on sealed output.
- The generator's `unique(subset=exposure_reference)` dedup after the SFT concat is defensive
  (`standardised` and `CCR_SFT` are disjoint populations); a single OR filter is equivalent and
  the tie-out test (§4, L4) proves it.
- Framework-agnostic in v1: col 0220 exists in both CRR C 07.00 and B31 OF 07.00 with the same
  filter semantics (B31 has no supporting factors, so post-SF ≡ RWEA). No regime branch anywhere
  (check 17 stays trivially satisfied).

### 2.2 API — one additive endpoint in `api/rest.py`

```
GET /api/lineage?run_id=&template=C_07.00&sheet=corporate&row=0010&col=0220&offset=0&limit=50
```

- Mirrors `GET /api/results` conventions exactly: `_require_run(run_id)` (404 unknown run),
  `response.scan_results()`, `_df`-style `{columns, rows}` payload.
- Unregistered cell → **404** with detail `"lineage not yet available for this cell"` — the
  extensibility contract: adding coverage = adding registry entries, never an API change.
- Response body: `{run_id, cell: {template, sheet, row, col, label, citation}, metric,
  predicate: {…as declared…}, basis, cell_value, total_rows, offset, limit, columns, rows}`.
  Returning the predicate verbatim makes the endpoint self-describing (the "filter criteria"
  field of the requested model).
- No existing endpoint changes. No new persistence: run retrieval reuses `_RUNS` + the calc-reuse
  `run_index` exactly as `/api/results` does.

### 2.3 UI — one page following the recon-explorer pattern

- `ui/views/lineage.py` — pure view function `cell_lineage_page(response, cell, offset, limit)`
  (no FastAPI/Jinja imports), wrapping `reporting.lineage.drilldown` and formatting for display —
  mirrors `ui/views/reconciliation.py::forensic_page`.
- Route `GET /results/{run_id}/lineage` in `main.py::_register_pages` (query params for cell key +
  paging, defaulting to the one registered cell) → `cell_lineage.html` extends `base.html`:
  cell identity + citation, headline cell value, the predicate rendered as plain English
  ("Standardised approach rows (plus FCCM SFT synthetics) in classes corporate,
  specialised-lending"), paginated contributors table with leg-role/class-origin columns.
- One link from `results.html` ("Report cell lineage") — the only touch to an existing template.

### 2.4 What this deliberately does NOT touch

- **No single-stream files**: `contracts/edges.py`, `engine/aggregator/*`, `contracts/bundles.py`,
  `engine/pipeline.py` are untouched — S2 already sealed every needed column.
- **No generator changes**: COREP output is byte-identical; the 95 goldens are untouched by
  construction.
- **No lineage persistence**: nothing new written to `$RWA_STATE_DIR`.

---

## 3. Mapping to the requested model (for the record)

| Requested field | Where it landed |
|---|---|
| run ID | runtime parameter of the drill-down (spec is run-independent) |
| template ID / cell ID | `CellLineage.template_id/sheet/row_ref/col_ref` registry key |
| metric | `LineageMetric` (v1: `Sum`) |
| filter criteria | `LineagePredicate` (typed fields → one `pl.Expr`) |
| source record IDs | **derived on demand, never stored** (§1.1) |
| calculation stage | `basis` label (`aggregator_exit`) + per-row explanatory columns; cross-stage provenance deferred (§1.2, §7) |

---

## 4. Execution slices (each independently green; total ≈ 4 PR-sized steps or 1 feature PR)

### L1 — Lineage core (`reporting/lineage.py`) + unit tests
- Model, registry (one entry), `compile_predicate`, `drilldown`.
- `tests/unit/reporting/test_lineage.py`: predicate compilation (each field, combinations,
  empty predicate rejected), sum over a hand-built frame, pagination/sort, unknown-cell resolution,
  empty-results run → `cell_value = 0.0` per COREP zero policy, and a **sealed-names guard**: every
  column referenced by every registry entry (predicate + metric + row projection) is asserted to be
  declared on `AGGREGATOR_EXIT_EDGE` — mechanically enforcing Phase 7 invariant 5 for this module.
- Gate: arch_check, ruff, ty, unit tests.

### L2 — Fidelity tie-out (the load-bearing test)
- `tests/acceptance/reporting/test_lineage_tieout.py`: run the rich
  `tests/fixtures/reporting_portfolio.py` through the **real pipeline** (reuse the golden-gate
  session fixture), generate C 07.00 via `COREPGenerator`, read corporates sheet / row 0010 /
  col 0220, and assert `drilldown(...).cell_value` matches **rtol 1e-9 / atol 1e-6** (the recorded
  golden tolerance — never byte-exact). Membership sanity: every returned row satisfies the
  declared predicate; row count > 0.
- This test is the feature's correctness anchor AND an early pin of the C07 predicate for the S8
  strangler (F4 support).
- Gate: acceptance test green in the default dev-loop profile.

### L3 — REST endpoint + integration tests
- `GET /api/lineage` per §2.2; tests alongside the existing `/api/results` TestClient tests:
  200 happy path (value + rows + predicate echo), 404 unknown run, 404 unregistered cell,
  paging params, additive-API guard (existing endpoint tests untouched).

### L4 — UI page
- `ui/views/lineage.py` + route + `cell_lineage.html` + one link from `results.html`.
- View unit tests mirroring the existing `ui/views` test style (pure-function tests, no server).

### L5 — Docs + changelog
- One docs page (e.g. `docs/reporting/cell-lineage.md`, added to zensical nav): the journey, the
  query-not-materialised design decision, the two-leg ledger caveat (§1.3), API shape, extension
  path (§6), current coverage (one cell) and how to add a cell.
- `docs/appendix/changelog.md` entry under Unreleased.
- `uv run zensical build` green.

**Suggested delivery:** single feature branch, L1→L5 as separate commits, one PR. Nothing here
forces single-stream handling; it can run as a normal `/next-items`-style worktree item if batched.

---

## 5. Invariants (inherited + local)

1. Additive only: no existing endpoint, template, bundle, or edge changes; goldens untouched.
2. Lineage reads only sealed `AGGREGATOR_EXIT_EDGE` names + `CalculationResponse` paths — no
   candidate ladders, no unsealed frames (Phase 7 invariants 4 & 5).
3. The tie-out test compares against the real generator output at rtol 1e-9 — if the generator and
   the predicate ever drift, the suite fails; the registry entry is corrected (or the drift is a
   found generator bug — escalate, don't paper over).
4. No regime string-branching in lineage code (check 17 discipline; v1 entry is regime-agnostic).
5. Unknown cells are a clean 404, not a fallback computation.

---

## 6. Extension path (recorded, not built)

- **S7/S8 supersession:** when `TemplateSpec`/CellSpec land, lineage records are *generated* from
  the specs (predicate and binding are the same objects), the hand-authored registry entry is
  deleted, and drill-down coverage becomes automatic for every migrated template. The v1 module is
  designed so this is a source swap, not a redesign.
- **More metrics:** `WeightedAvg`/`Ratio`/`Count` arrive with the S7 kernel primitives — lineage
  reuses them rather than growing its own.
- **Per-row "why" enrichment:** join `floor_impact` / `supporting_factor_impact` (and F8's
  `rwa_benefit` once decided) into the drill-down row projection.
- **Vertical provenance:** row → stage/rule trail via the opt-in `audit_cache` (per-run parquets)
  — a separate plan when demanded.
- **Rendered templates with clickable cells:** after S8 migrates templates through the executor.

---

## 7. Out of scope for v1 (explicit)

1. Materialised lineage tables/parquets (banned by design, §1.1).
2. Cross-stage provenance graphs (§1.2).
3. Coverage beyond the one registered cell (the model covers it; the registry doesn't yet).
4. Formula cells (C07 0040/0110/0150) — need `Formula` bindings; deferred to S7 vocabulary.
5. Any COREP/Pillar 3 generator refactor — that is Phase 7 S8's job.
