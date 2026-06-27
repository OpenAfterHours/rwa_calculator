# From Workbench to Web App: Reconciliation and the RWA Driver Chain

*The blog spent eight posts on the engine and never once mentioned the thing a risk team actually opens: the app. This is that post. An editable Marimo workbench came out, a server-rendered FastAPI app went in, and the headline feature is a single-loan forensic that turns "our number disagrees with the legacy file by £1m" into "here is the one driver that moved, and here is why."*

Published 2026-09-15. Code references are pinned to commit [`7e7ed7ec`](https://github.com/OpenAfterHours/rwa_calculator/tree/7e7ed7ec).

---

This post picks the series back up after the season-one finale. That post — [What I Got Wrong, What's Next](2026-08-04-what-i-got-wrong-whats-next.md) — called itself the last one and closed the ledger on the engine. It was honest about the gap between a reference implementation and a regulated production system, and it was right that the engine is most of the work. But it left a hole I have been quietly uncomfortable about for the whole run: every post talked about bundles, frozen dataclasses, the output floor, and the agent swarm, and none of them talked about the surface a human actually touches. There is now a real one, and it is not what season one described.

So season two opens on the application. The calculator is at version 0.3.5 as I write; the commit this post pins to is a handful past it, in `[Unreleased]`. Two things changed since the finale that are worth a post between them. First, the editable Marimo workbench the docs used to point at is gone, removed cleanly enough that it is a small case study in deleting a feature. Second, in its place is a loopback FastAPI app whose centre of gravity is *reconciliation* — running this engine in parallel with a firm's incumbent one and explaining, loan by loan and driver by driver, where the two disagree. Everything below was built by the same agent swarm from [post 4](2026-06-09-building-with-an-agent-swarm.md); I will come back to that, because the way these features got built is its own story for the post after this one.

## Removing a feature cleanly

The old UI was a Marimo workbench: an editable notebook you launched on a side port, good for poking at a portfolio interactively. It is gone as of commit [`1e4b8852`](https://github.com/OpenAfterHours/rwa_calculator/commit/1e4b8852) (PR #408), `chore: remove the Marimo workbench feature`. The reason is unglamorous — maintenance cost, and a sibling project that does interactive exploration better — but the *way* it came out is the part I want to keep.

A Marimo page registers a browser service worker (`public-files-sw.js`) to serve its static assets. Service workers outlive the page that installed them. They outlive the *server* that installed them. A user who had the old workbench open in a tab last month still has a registration sitting in their browser, scoped to whatever path that tab was on, and the browser dutifully re-fetches that worker script on every in-scope navigation. Delete the route that served it and every one of those fetches is a 404, forever, in a tab the user forgot about — a dead worker that never uninstalls because nothing ever tells it to.

The clean removal is not "delete the route." It is *tombstone the worker*. The new app serves a tiny self-unregistering script at every path the old worker could have been scoped to ([`ui/app/main.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/ui/app/main.py)):

```javascript
self.addEventListener('install', function () { self.skipWaiting(); });
self.addEventListener('activate', function (event) {
  event.waitUntil(self.registration.unregister().catch(function () {}));
});
```

The browser's periodic update check fetches the new script, sees it has changed, installs it, and on activation the worker unregisters *itself*. It has no `fetch` handler, so while it waits to uninstall it intercepts nothing. Two routes serve it — one at the root, one at `/{sw_scope:path}/public-files-sw.js` for nested scopes — and they are registered *first*, before the `/{run_id}` parameter routes, so the literal worker path wins over the wildcards. The code deliberately does *not* force any tab to reload: a forced reload would also reload an unrelated stale tab (an old `/results/<id>` page whose in-memory result died with the previous server) straight into a 404. Removing a feature, it turns out, has a correct sequence and a sloppy one, and the difference is whether the users who never asked for the change ever notice it. This one they will not.

## The new surface

What replaced it is a server-rendered FastAPI app, the `rwa-ui` console script ([`ui/app/main.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/ui/app/main.py), entry point `rwa_calc.ui.app.main:main`). It binds to `127.0.0.1` only, opens your browser at `http://localhost:8000`, and mounts the project's REST API *in the same process* — the UI consumes the exact library-first API that an automated caller would, so the screen can never show a number the API would not. The pages are plain: a landing page, a calculator form, a results explorer with SVG charts, a CRR-versus-Basel-3.1 comparison, and reconciliation. It is styled with the shared `--oah-*` design tokens (nineteen of them in [`static/tokens.css`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/ui/app/static/tokens.css)) so it matches the Zensical docs site rather than looking like a different product.

It is a local single-user tool, but "local" is not the same as "unguarded," and a UI that writes files to a folder you type into a form is exactly the kind of thing a malicious web page would love to drive on your behalf. There are three guards, and they do different jobs:

- **`TrustedHostMiddleware`** with an allowlist of `localhost` / `127.0.0.1` is the DNS-rebinding defence: the server simply refuses to answer to any other `Host` header, so an attacker-controlled name that resolves to your loopback cannot talk to it.
- **`require_same_origin`** is a FastAPI dependency on every state-changing route — the routes that write to disk. A browser always attaches `Sec-Fetch-Site` (and `Origin`) to a cross-origin form POST, so a page on some other origin cannot silently fire `/calculate` or `/results/{id}/save`. A local non-browser client sends neither header and is allowed, because it already runs as you.
- **`validate_output_path`** is the belt to that brace: an output folder must be absolute and resolvable, an existing path must be a writable directory, and a non-existing one must have an existing parent — so a typo cannot quietly create a deep tree in a surprising place. Errors accumulate into a `ValidationResponse`; nothing raises.

None of this is novel security engineering. It is the minimum a loopback tool owes a user before it is allowed to turn a text field into a filesystem write, and it is the kind of thing the engine's error-accumulation discipline ([post 2](2026-05-12-the-pipeline.md)) made natural to write — validation that collects and reports rather than throws.

## Progress for free

The first genuinely satisfying piece of engineering in the new app is the live progress stepper, and it is satisfying precisely because it required *zero* engine changes.

A real portfolio takes long enough to run that a synchronous `POST /calculate` would hand the browser a frozen tab. So `/calculate` is asynchronous: it dispatches the run to a background `ThreadPoolExecutor`, then immediately `303`-redirects to `/calculating/{job_id}` ([`ui/app/progress.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/ui/app/progress.py)). That page needs to show *honest* progress — which stage is running — and the obvious bad way to do that is to invent a percentage and race a bar to 90% while the heavy step hangs.

The honest way reuses telemetry that already exists. Recall from [post 2](2026-05-12-the-pipeline.md)'s June update that the pipeline became a fold over a literal stage registry, with `engine/orchestrator.py::run_stages` wrapping every registered stage in `stage_timer`. That decision was made for observability — every stage gets entry/exit timing for free by being in the registry. It turns out the same telemetry is a perfect progress source. `stage_timer` ([`observability/context.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/observability/context.py)) emits, on the way out of each stage:

```python
logger.info("%s completed in %.1f ms", stage, elapsed_ms, extra=exit_extra)
```

where `exit_extra` carries `stage` and `elapsed_ms`. So the UI does not ask the engine for progress. It *listens*. A `logging.Handler` attached to the `rwa_calc` namespace logger reads those records and marks the matching stage done on the active job:

```python
def emit(self, record: logging.LogRecord) -> None:
    job = _active_job.get()
    if job is None:
        return
    stage = getattr(record, "stage", None)
    if stage in KNOWN_STAGE_NAMES and getattr(record, "elapsed_ms", None) is not None:
        job.mark_stage(stage)
```

The one subtlety is correlating a log record to the right job when up to four jobs run in a shared thread pool. The handler runs synchronously in the thread that emitted the record, so the job is carried on a `contextvars` `ContextVar`: each worker runs in a copied context with `_active_job` set, and pooled threads never leak progress between jobs. This is the same ContextVar side-channel the engine already uses internally for materialisation — no new pattern, no engine edit.

The stepper is driven off completed-stage **order**, never a synthesised percentage. The ten registry stages (`securitisation_allocator → hierarchy_resolver → ccr_sa_ccr → sft_fccm → classifier → crm_processor → re_splitter → calculators → equity_calculator → aggregator`) become a fixed checklist; the client ticks each off as the server reports it. One stage, `calculators`, is flagged `heavy=True`, because the lazy Polars graph concentrates its real compute in that branch's `.collect()`. So the spinner honestly parks on "Risk-weight calculators" instead of pretending nine-tenths of the work is done. The events reach the browser over Server-Sent Events (`/jobs/{id}/events`), with the stage checklist replayed on each reconnect so EventSource's auto-reconnect is idempotent, and a JSON-poll of `/jobs/{id}` as the fallback when EventSource is unavailable. The reconciliation path adds one synthetic tail step, `recon_reconcile`, which the worker marks itself after the engine stages — because the legacy join is a plain function, not a registry stage, and that step is exactly where the heavy full-outer join is forced to execute.

A feature that, in a less disciplined codebase, would have meant threading a progress callback through every stage, instead fell out of a logging convention. That is the dividend of having made the stages uniform.

## Reconciliation at scale

The reason the app exists at all is reconciliation, and reconciliation has a scale problem the rest of the UI does not. A results page shows aggregates and a 100-row sample — bounded by construction. A reconciliation against a legacy file is a full-outer join of *every* exposure on both sides, and a real book is millions of rows. You cannot render that, and you must not collect it just to draw a summary.

The report is therefore built aggregates-first. The overview ([`_reconciliation_result` in `ui/app/main.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/ui/app/main.py)) renders only small pre-aggregated frames: a headline tie-out (our total versus legacy total per additive component), a per-component bucket summary, segment tables by bucket / exposure class / approach, and a ranked top-50 "biggest breaks" worklist. It never collects the wide per-key frame, so it renders in constant time and constant DOM for any portfolio size. The background worker *warms* the cheap summary caches on its thread, under the progress stepper, but deliberately leaves the wide `component_reconciliation` frame lazy — the overview never touches it.

That wide frame is reached only by drilling down, and the drill is paged on the server. The per-key explorer (`/reconciliation/{id}/rows`) takes a `ForensicFilters` request — filter by bucket, exposure class, approach, or worst component; a literal substring match on the join key; a sort column validated against the projected display columns (an unknown column answers `400`, not a 500); a page and a clamped page size capped at 500 ([`ui/views/reconciliation.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/ui/views/reconciliation.py)). The browser only ever receives one page. The whole design is the same lazy-versus-eager discipline the engine lives by, applied to a UI: collect the small things eagerly and cache them; keep the big thing lazy and slice it.

## The RWA driver chain

The drill bottoms out at a single loan, and this is the feature the whole app is built around. `loan_detail` ([`ui/views/reconciliation.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/ui/views/reconciliation.py#L360)) filters the lazy per-key frame to one join key — filter pushdown keeps it cheap even when the eager cache is cold — and lays the result out as an **ordered RWA-driver chain**. The chain is the order an analyst actually reads a risk-weighted-asset build, from [`recon_registry.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/analysis/recon_registry.py):

> exposure class → approach → CQS / rating → PD → LGD → maturity → CCF → collateral → guarantee → EAD → risk weight → supporting factor → expected loss → RWA

Each step in that chain is a `ReconcilableComponent` in the registry, and each renders one row with **legacy | ours | absΔ | relΔ | status**. Only the components your legacy file actually maps appear; an unmapped driver simply isn't a step. The status comes from the engine's bucketing — `exact_match`, `within_tolerance`, `break`, or `missing` on one side — using a per-component tolerance (`CQS` has an absolute tolerance of zero, so any difference is a break; additive money components like `EAD` and `RWA` use a relative tolerance of 1%).

What makes this *forensic* rather than just a diff is what hangs off each step. `collateral`, `guarantee`, and `CQS` are first-class reconcilable components, not buried inside EAD — so a CRM disagreement shows up as its own row, not as an unexplained EAD wobble. And each component carries `explain_columns` (our rationale: which floor bound bit, which rating source was chosen) and `input_columns` (the raw upstream drivers that fed the value). The forensic view nests those under the relevant chain step as our-side-only "drivers," de-duplicated so a column that is itself a promoted component (collateral feeding EAD, say) shows once under its own step rather than twice.

Make that concrete. Suppose the headline tie-out flags a £1,000,000 gap in total RWA, you filter the explorer to the `break` bucket, and you open the worst offender — a £2,000,000 corporate exposure on the Standardised Approach. The driver chain reads (numbers illustrative):

| step | legacy | ours | absΔ | status |
|---|---|---|---|---|
| exposure class | corporate | corporate | — | match |
| approach | standardised | standardised | — | match |
| CQS / rating | 3 | 4 | 1 | **break** |
| EAD | 2,000,000 | 2,000,000 | 0 | match |
| risk weight | 0.50 | 1.00 | 0.50 | **break** |
| RWA | 1,000,000 | 2,000,000 | 1,000,000 | **break** |

The £1m break is not a classification dispute and not an EAD dispute — those rows are green. It is one notch of credit-quality step, propagating through the risk weight (CQS 3 maps to 50%, CQS 4 to 100% for this class) into a doubled RWA. And nested under the CQS row are the explain/input drivers our side recorded: `sa_rating_source` and `external_cqs`. They say *why* we landed on CQS 4 — the counterparty had three external ratings, and under CRR Art. 138 the rule is per-agency dedup then take the **second-best** of three, not the legacy engine's "most recent wins." (That Art. 138 misreading was itself a real bug, recounted in [post 8](2026-08-04-what-i-got-wrong-whats-next.md); here it is the *kind of disagreement a legacy engine plausibly still has*, and the chain surfaces it in one screen.)

This is the difference between a reconciliation that tells you *that* two engines disagree by £1m and one that tells you *which driver* moved and *why*. The first is a spreadsheet. The second is a triage tool: a risk analyst signing off a parallel run can look at that chain and decide in seconds whether the break is a data-mapping fix on their side or a genuine methodology difference to escalate. Multiply that by the thousands of breaks a first parallel run throws off and the per-loan explainability is the entire value of the feature.

## Output folders, and not recomputing

A smaller feature, but one that matters to anyone who has watched a long run finish and then had nowhere to put the results. The calculator form takes an output folder and a set of formats — Parquet, CSV, Excel, or a COREP workbook (PR #411). After `calculate()` returns, the background worker writes the selected formats to disk, *outside* the stage sequence so the stepper's stage count is unchanged and the page stays responsive.

The write surface ([`ui/app/output_writer.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/ui/app/output_writer.py)) has two properties worth naming. First, every write lands in a run-stamped subfolder, `rwa_export_<run_id>/`, so a re-export can never silently clobber a different run's files and the four-worker pool cannot race two runs onto the same fixed filenames. Excel and COREP workbooks are written to a temp name and atomically `os.replace`-d into place, so a re-save can never shadow a good workbook with a half-written one. Second, each format is written independently and failures are captured, never raised: a missing `xlsxwriter` for the Excel/COREP path becomes a per-format user-facing message ("install it with `uv add xlsxwriter`") while Parquet and CSV still succeed. The UI surfaces the outcome; it never returns a 500 because one of four formats could not be written.

And because a finished run is held in the in-memory registry, the "Save to folder" route on the results page re-exports an *already-computed* run to a chosen folder without recomputing it. You ran the portfolio once; you can write it to three folders in three formats without paying for the pipeline three more times.

## The analysis layer underneath

None of the UI does any regulatory work itself — it is a thin view over an `analysis/` package that landed as migration Phase 6, sitting cleanly above the engine. Five modules, each a single responsibility:

- [`comparison.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/analysis/comparison.py) — `DualFrameworkRunner.compare()` runs CRR and Basel 3.1 from one shared upstream plan (the lazy-graph dedup from [post 2](2026-05-12-the-pipeline.md)), and `CapitalImpactAnalyzer.analyze()` produces the impact bundle behind the `/comparison` page.
- [`attribution.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/analysis/attribution.py) — a pairing-keyed registry of delta-attributors. The CRR→Basel-3.1 waterfall decomposes the RWA delta into named drivers — removal of the 1.06 IRB scaling factor, removal of the supporting factors, the output floor, and a methodology residual — registered under the `('crr', 'b31')` pairing; any unregistered pairing falls back to a neutral delta-only attributor. This is the engine behind the capital-impact waterfall that [post 5](2026-06-23-the-output-floor-and-why-basel-31-bites.md) explains the regulation for.
- [`reconciliation.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/analysis/reconciliation.py) — the parallel-run engine: collapse our guarantee/RE sub-rows to the key grain, full-outer join against the mapped legacy file, bucket every component, attach the explain/input columns. Distinct from `comparison.py`: there the other side is *our* engine on a different regime; here it is an opaque external file.
- [`recon_registry.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/analysis/recon_registry.py) — the canonical `RECONCILABLE_COMPONENTS` tuple (the chain above) and the `LegacyColumnMapping` / `ComponentMapping` grammar that maps a legacy file's columns onto our components, with per-component scale, unit, value-map and tolerance overrides.
- [`transition.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/src/rwa_calc/analysis/transition.py) — the transitional output-floor schedule (60% in 2027 rising to 72.5% in 2030+ under PRA PS1/26 Art. 92(5)), a run per reporting date.

Note one thing the reconciliation module's docstring is careful about: reconciliation is *not* a regulatory calculation, so it carries no `@cites` decorators — it describes how a finished run is checked, not how capital is computed. That boundary is deliberate. The regulatory surface stays in the engine and the rulepack packs where the audit team reads it ([post 2](2026-05-12-the-pipeline.md)); the analysis layer is comparison and explanation, and it is allowed to be pragmatic.

## What the surface taught me

Two things, writing this app, that the engine posts did not surface.

The first is that good engine architecture pays unexpected UI dividends. The live progress stepper is the *direct* consequence of having made every pipeline stage uniform enough to wrap in one timer. The aggregates-first reconciliation report is the engine's lazy/eager discipline applied one layer up. The form validation that re-renders with an error instead of throwing is the engine's error-accumulation contract. I did not design those engine properties for a UI — there wasn't one — but a surface built on a disciplined core inherits the discipline almost for free. The inverse is the more common experience: a UI bolted onto an undisciplined engine re-invents every guarantee the engine failed to make.

The second is that the feature a risk team most needs is not "compute the number" — the engine has done that for a year — it is "explain the disagreement." A reference implementation that produces correct numbers in isolation is interesting; one that can sit next to a firm's incumbent engine and localise a £1m break to a single credit-quality step, with the reason attached, is *useful* in a way the raw engine never was. The driver chain is small — a couple of hundred lines of view code over a registry — but it is the closest this project has come to the thing the season-one finale said was missing: a credible path from "reference implementation" to "something a firm can actually run a parallel-run discipline against." That path runs through explainability, and explainability is a UI feature with an engine underneath it.

The next post returns to the swarm — two months on from [post 4](2026-06-09-building-with-an-agent-swarm.md), with these features as the evidence. Every line of the app above was written by the same four role-bounded agents, and what they got right, what they got wrong, and what the orchestration grew into is worth a second look now that there is a season of output to judge it by.

---

**Read next:** *The Swarm, Two Months On* — [2026-09-29](2026-09-29-the-swarm-two-months-on.md) (in progress).

**Further reading:**

- [Parallel-Run Reconciliation](../reconciliation/index.md) — the full spec for the feature this post demonstrates: why you reconcile before you switch, the component grammar, and the triage workflow.
- [Interactive UI](../user-guide/interactive-ui.md) — the user-facing guide to the `rwa-ui` app: pages, the calculator form, and the export options.
- [Comparison & Impact Analysis](../framework-comparison/impact-analysis.md) — the CRR-versus-Basel-3.1 waterfall the `/comparison` page renders.
- [Architecture: Pipeline](../architecture/pipeline.md) — the ten-stage fold and the `stage_timer` telemetry the progress stepper taps.
- [`scripts/blog_counts.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/7e7ed7ec/scripts/blog_counts.py) — the canonical-counts script behind the figures in this series, if you want live numbers rather than the ones pinned here.
