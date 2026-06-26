# Reconciliation page UX redesign — live progress + large-data navigation

**Status:** Phase 1 ✅ done · Phase 2 ✅ done · Phases 3–4 optional/deferred ·
**Owner:** UI surface (`src/rwa_calc/ui/`) · **Created:** 2026-06-26

## Why

The server-rendered reconciliation page has two operator-facing problems, both
confirmed in the code:

1. **No live progress.** `POST /reconciliation`
   (`ui/app/main.py::run_reconciliation`) runs `CreditRiskCalc(...).reconcile()`
   **synchronously on the request thread** and only shows an indeterminate
   busy-overlay spinner. Reconcile is strictly *heavier* than `/calculate`
   because it embeds a full `self.calculate()` run (`api/service.py`) **plus** the
   legacy load + full-outer join — yet it has none of the stage stepper the
   calculator page gained in `feat(ui): live calculation progress` (commit
   `0ae40784`). Worse: the `ReconciliationBundle` frames are **lazy**, so the
   heavy join + bucketing actually executes on the **first `collect_*` during the
   result-page render** (`api/models.py::_collect_cached`) — the tab can freeze
   twice (blocking POST, then result render).

2. **The results page cannot survive large output.** The page renders **seven
   tables in one HTML document**, and the Tier-3 "breaks worklist"
   (`templates/reconciliation.html` line ~128) is dumped **uncapped** — one `<tr>`
   per `(key × component)` break, every row pushed through `to_dicts()`. For a
   large portfolio that is hundreds of thousands to millions of rows → tens of MB
   of HTML held in server memory and shipped at once. The forensic per-loan tier
   is hard-capped at **200 rows** (`_FORENSIC_LIMIT`) with **no way to page past
   it**; the only "filter" (bucket links) **re-renders the whole page**; there is
   **no search, no sort, no per-loan drill-down**.

## Design at a glance

Two **independent** halves that ship as separate PRs:

- **Half A — live progress:** reuse the existing calc-progress machine almost
  verbatim. The whole `progress.py` stack (`Job`, `submit_job` + `_active_job`
  contextvar isolation, `_ProgressLogHandler`, the SSE `/jobs/{id}/events`
  stream, `calculating.js`, the stepper CSS) is **generic** — it keys off the
  pipeline's `stage_timer` telemetry, not anything calculation-specific. Reconcile
  drives the same engine pipeline, so the engine stages stream **for free** once
  the worker runs under `submit_job`.

- **Half B — progressive-disclosure navigation:** reconciliation work is "find
  the breaks, not scroll all rows", so the default page must **never materialise
  the full diff frame**. Land on an aggregates-only overview (the 7 small summary
  frames + charts + a ranked "biggest breaks" top-N), and reach the row-level
  frame only by drilling: overview → server-paged explorer → single-loan detail.

This came out of a multi-agent investigation (5 parallel code-mappers + 3
independently-designed approaches + a scored judge panel). The progressive-
disclosure design won on fit / scalability / UX / effort; it grafts the clean
endpoint contract from the server-paged approach and the per-component-card loan
view from the client-grid approach.

## Key correctness insight (load-bearing)

`reconcile()` returns a bundle of **LazyFrames**; every `collect_*` accessor
lazily collects on first access (`api/models.py:478-490`). The heavy full-outer
join + bucketing therefore fires on the **first collect**, which today happens
during the result-page GET. An honest stepper **must warm the summary caches
inside the background worker** so that compute runs *under the stepper*, not on
the result-page render. Without this, the recon-tail step would tick instantly
and lie, and the result page would still freeze.

---

## Phase 1 — Live progress (ship first)

Smallest, lowest-risk, biggest single UX win. All UI-layer; touches none of the
single-stream shared engine files.

### Changes

- **`ui/app/progress.py`** — add `RECON_STAGE_SEQUENCE = STAGE_SEQUENCE +
  (StageInfo("recon_reconcile", "Reconcile & summarise", heavy=False),)`. The
  engine stages are marked by the existing `_ProgressLogHandler` (already in
  `KNOWN_STAGE_NAMES`); the recon-tail stage is marked **directly** by the worker
  (`job.mark_stage("recon_reconcile")`), so the logging tap and
  `KNOWN_STAGE_NAMES` need no change.
- **`api/rest.py`** — add `register_reconciliation_with_id(recon_id, response)`
  mirroring `register_run_with_id`, so `job_id == recon_id` and the existing
  `done`-event handoff resolves to `/reconciliation/{job_id}`.
- **`ui/app/main.py`**
  - `_reconciliation_worker(...)` (mirrors `_calculation_worker`): run
    `.reconcile(settings)`, **warm every frame the result page collects**
    (summaries + tie-out + class-allocation + breaks_detail + the wide
    component_reconciliation), then `job.mark_stage("recon_reconcile")`,
    `register_reconciliation_with_id(job.job_id, response)`, `save_last_run(...)`,
    `job.finish(success=response.success)`.
  - Rewrite `POST /reconciliation`: parse the TOML synchronously (bad TOML →
    re-render the form with a 400, exactly as today), then `create_job()` +
    `submit_job(_reconciliation_worker(...))` + `303 → /reconciling/{job_id}`.
  - New `GET /reconciling/{job_id}` rendering `reconciling.html` (404 when the job
    is unknown), mirroring `GET /calculating/{job_id}`.
  - `GET /reconciliation/{recon_id}` is unchanged — it now serves the result keyed
    by the job_id.
- **`ui/app/static/calculating.js`** — generalise `finishOk()` to navigate to
  `root.getAttribute("data-result-base") + jobId` (default `/results/`). No SSE
  shape change.
- **`ui/app/templates/calculating.html`** — set `data-result-base="/results/"`.
- **`ui/app/templates/reconciling.html`** — new, near-copy of `calculating.html`
  with `stages = RECON_STAGE_SEQUENCE` and `data-result-base="/reconciliation/"`.
- **`ui/app/templates/reconciliation.html`** — drop `data-busy-overlay` from the
  form (it opts into the real stepper, like the calculator form).

### Tests (`tests/integration/test_ui_reconciliation.py`)

The existing tests encode the **old synchronous contract** and must move to the
async pattern (mirroring the calc-progress tests):

- POST → `303 → /reconciling/{job_id}`; the stepper page renders with
  `data-stage="recon_reconcile"` and `/static/calculating.js`.
- `_wait_for_job` → `done`; then `GET /reconciliation/{job_id}` renders the four
  tiers + inline SVG.
- SSE `/jobs/{job_id}/events` replays `stage` events and a terminal `done`.
- bad TOML still 400s on the POST (synchronous parse).
- prefill / reset tests wait for the job before asserting the save.
- unknown `/reconciling/{id}` → 404.

### Acceptance

`uv run pytest tests/integration/test_ui_reconciliation.py tests/integration/test_ui_app.py`
green; full suite green; `ruff`, `ty`, `arch_check` clean; changelog updated.

---

## Phase 2 — Progressive-disclosure navigation (second PR)

The Half-B data-navigation rebuild. Independent of Phase 1.

- **Tier A — Overview** (`GET /reconciliation/{id}`, rewritten): render only the 7
  small pre-aggregated frames + charts + a **"Biggest breaks" top-N**
  (`scan_breaks_detail().head(N)` — add a lazy accessor so the top-N never forces
  the wide-frame cache). **Delete** the unbounded `breaks_table → to_dicts()`
  render. Every segment row (class / approach / bucket) links into the explorer
  with the filter pre-applied. The overview never calls
  `collect_component_reconciliation()` → constant-time, constant-DOM for any
  portfolio size.
- **Tier B — Explorer**
  (`GET /reconciliation/{id}/rows?bucket=&class=&approach=&worst_component=&q=&sort=&dir=&page=&page_size=`):
  filter + sort + `.slice(offset, page_size)` server-side in Polars over the
  cached eager frame, projected via the existing `_readable_recon_columns`,
  rendered through a shared `_recon_table.html` partial with prev/next +
  "rows X–Y of Z". A `Page` frozen dataclass; `sort_by` whitelisted against the
  dynamic component schema (unknown col → 400). Same `?param=` round-trip idiom
  the bucket filter already uses — no client framework.
- **Tier C — Single-loan detail** (`GET /reconciliation/{id}/loan/{recon_key}`):
  `scan_component_reconciliation().filter(_recon_key == key).collect()` (filter
  pushdown keeps it cheap even cold). Render the full per-component panel for that
  loan — every `legacy_/our_/Δ/bucket` plus the **explain/input driver columns
  every on-screen table drops today** plus that key's break rows. URL-encode the
  `||`-joined composite key.
- New view fns in `ui/views/reconciliation.py`: `biggest_breaks(response, n)`,
  `forensic_page(...) -> Page`, `loan_detail(response, recon_key)`.
- Consolidate the three re-inlined `<table class="data">` markups
  (reconciliation / comparison / results) onto the shared `_recon_table.html`
  partial.

## Phase 3 (optional) — fragment-swap JS

Add a ~70-line vanilla `recon-tables.js` that hydrates the explorer's data div:
delegate sortable-header/pager clicks to `fetch` + `innerHTML` swap, debounce
search. The no-JS fallback is the **same** Phase-2 route, so endpoints just gain
an `Accept: application/json` / fragment dual response. Skip unless local
round-trips feel laggy (this is a local app — round-trips are cheap).

## Phase 4 (optional, only on demand) — virtual-scroll grid

A single vanilla virtual-scroll grid scoped to the **explorer tier in
server-windowed mode only**. Highest effort/risk and the largest client surface;
defer until there is evidence analysts need to fluidly scroll a multi-million-row
explorer rather than triage ranked breaks.

## Honest limits / follow-ups (out of scope here, track separately)

- **Server RAM is the real ceiling.** Paging caps transport + DOM, not memory.
  The eager wide frame still lives in the in-process `_RECON_RUNS` dict —
  hundreds of MB to GBs at tens of millions of rows. The true future lift is
  **parquet-spilling the wide frame and scanning per page** (mirroring the
  parquet-cached `CalculationResponse`).
- **`_RECON_RUNS` (and `_RUNS`) have no TTL/eviction**, so a server restart 404s
  the overview + explorer + loan routes mid-session. A long drilling session
  widens that window; wants a companion LRU/TTL.
- **First explorer drill** pays the wide-frame materialisation unless the worker
  also warms it (trades worker latency + session-long RAM for instant drill).
  Recommendation: lazy + spinner for v1.

## Decisions taken

- Generalise `calculating.js` via a `data-result-base` attribute (no SSE shape
  change) rather than threading a `result_url` through the `done` event.
- Persist the design here before code lands (this document).
- Build order: **Phase 1 first, then Phase 2** (the two halves are independent).
