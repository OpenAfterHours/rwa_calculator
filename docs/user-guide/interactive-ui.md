# Interactive UI

The RWA Calculator ships a polished, locally-run web interface for configuring a
run, exploring results, and comparing CRR with Basel 3.1 — backed by a REST API
that the UI itself consumes. It is a server-rendered FastAPI + Jinja app styled
with the same design tokens as this documentation site, so no JavaScript build
step is required and it bundles cleanly for local distribution.

## Prerequisites

```bash
uv add rwa-calc      # or: pip install rwa-calc
```

The UI dependencies (FastAPI, Uvicorn, Jinja) ship with the base package — no
extra is required.

---

## Starting the UI server

=== "Installed from PyPI"

    ```bash
    rwa-ui
    ```

=== "From source"

    ```bash
    uv run rwa-ui
    # or: uv run python -m rwa_calc.ui.app.main
    ```

The server starts on [http://localhost:8000](http://localhost:8000) and opens
your browser at the landing page.

---

## Pages

| Page | URL | Purpose |
|------|-----|---------|
| **Landing** | `/` | Overview and navigation |
| **Calculator** | `/calculator` | Configure and run an RWA calculation |
| **Results** | `/results/{run_id}` | Headline metrics, charts and an exposure sample for a run |
| **Comparison** | `/comparison` | CRR vs Basel 3.1 with the capital-impact waterfall |
| **Reconciliation** | `/reconciliation` | Reconcile against a legacy calculator, component by component |

Charts on the results, comparison and reconciliation pages are rendered as inline
SVG themed with the documentation palette.

---

## Calculator

The calculator (`/calculator`) runs the full pipeline through a form.

| Field | Description |
|-------|-------------|
| **Data path** | Directory of Parquet/CSV inputs (see [Input Schemas](../data-model/input-schemas.md)) |
| **Output folder** | *Optional.* An absolute folder to write the results into when the run finishes. Leave blank to skip writing to disk (you can still download or save afterwards). |
| **Output format(s)** | Which formats to write: Parquet, CSV, Excel, COREP, Pillar III. Excel, COREP and Pillar III require `xlsxwriter` (greyed out otherwise). |
| **Framework** | CRR (Basel 3.0) or Basel 3.1 |
| **Permission mode** | Standardised (all SA) or IRB (driven by `model_permissions`) |
| **Data format** | Parquet (recommended) or CSV |
| **Reporting date** | Calculation reference date |

Submitting validates the data path (and the output folder, if set), runs the
calculation, and redirects to the results page for that run. Results show total
RWA/EAD, exposure count and average risk weight; the RWA/IRB/SA/Slotting split and
output-floor impact; charts of RWA and EAD by exposure class and RWA by approach;
and a sample of the exposure-level output. Any data-quality issues are listed
beneath the results.

### Writing results to a folder

Because the app runs locally, it can write outputs straight to a folder on your
machine. There are three ways:

- **At run time** — fill in **Output folder** and tick one or more **Output
  format(s)** on the calculator. When the run finishes, the files are written and
  the results page confirms exactly what was written and where. The folder and
  formats are remembered for next time.
- **From the results page** — the **Save to folder** form re-exports an
  already-computed run to any folder without recomputing it.
- **Download** — the **Download results** buttons stream each format to your
  browser's Downloads folder.

Each save lands in its own `rwa_export_<run_id>` subfolder of the folder you
choose, so a new run never overwrites an earlier one. The output folder must be an
absolute path whose parent already exists. Parquet preserves every column
natively; CSV has no nested types, so the handful of nested columns (e.g.
securitisation pool allocations) are JSON-encoded in the CSV rather than left
blank. If a format genuinely cannot be written — for example Excel, COREP or
Pillar III without `xlsxwriter` — that format alone is reported, and the others
still write.

!!! note "Local-only by design"
    The server binds to `127.0.0.1` and only answers to the `localhost` /
    `127.0.0.1` host names, and the write routes reject cross-origin requests — so
    a folder you name is written by your own process on your own machine, and a
    web page on another site cannot drive a write. Do not expose the app off
    loopback.

---

## Comparison

The comparison page (`/comparison`) runs the portfolio through **both**
frameworks and shows an executive summary, the additive capital-impact waterfall
(scaling factor, supporting factor, methodology, output floor), and a per-class
breakdown. It takes roughly twice a single-framework run. **Download** buttons
export the comparison — the executive summary, the by-class and by-approach
**delta** summaries, the capital-impact waterfall, and the per-exposure deltas —
as CSV, Parquet (both a zip of one file per dataset) or a single multi-sheet Excel
workbook.

---

## Reconciliation

The reconciliation page (`/reconciliation`) reconciles this calculator's output
against a **legacy** calculator's output, component by component, for migration
confidence. Enter your data path, edit the TOML mapping (which names the legacy
file, the join keys and how each legacy column maps to a canonical component)
directly in the form, and run. The result is shown across four drill-down tiers —
the headline tie-out and per-component summary, the by-bucket / by-class /
by-approach segmentation, the break worklist ranked by materiality, and a
single-loan forensic that lays out the **RWA-driver chain** (exposure class →
approach → CQS → PD → LGD → maturity → CCF → collateral → guarantee → EAD → risk
weight → RWA) with legacy beside ours at each step and our drivers nested beneath
— plus CSV / Excel downloads of the full per-key detail. Map a legacy column for
`pd`, `lgd`, `cqs`, `collateral` or `guarantee` (commented examples ship in the
default mapping) to compare those drivers side-by-side. See the
[Reconciliation guide](../reconciliation/index.md) for the mapping grammar and the
output reference.

**Reusing a calculation you already ran.** A reconciliation normally embeds a full
engine run for our side. When the *identical* calculation has already run (same data
path, framework, reporting date, permission mode and data format — and no input file
has changed since), the form offers a pre-ticked
**"Use results from the calculation completed at …"** checkbox: the engine run is
skipped and the reconciliation starts straight from that run's cached results, so
the stepper ticks every engine stage instantly and parks on the reconcile step.
Untick it to force a recompute. Freshness is verified again at submit time against
the input files' size/mtime signature — if anything changed in between, the run
silently falls back to a full recompute (never a stale reuse). If a matching run
exists but the data has changed, the form says so instead of offering the reuse.

Every run seeds the reuse pool: calculator runs, both halves of a comparison run,
and a full reconciliation's own embedded run — so any calc → compare → reconcile
order pays for each framework's pipeline once. The pool **survives an app
restart**: run caches and the reuse index persist under `~/.rwa_calc/` (or
`$RWA_STATE_DIR`), capped at the ten most recent runs. The calculator page joins
in too — when its pre-filled form matches a fresh run it shows a non-blocking
"already ran — view its results" banner linking straight to the existing results.

---

## REST API

The same server exposes a JSON API (the library-first contract — embeddable by
other tools). Interactive docs are at `/docs` (OpenAPI).

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `GET`  | `/api/frameworks` | List supported frameworks |
| `POST` | `/api/validate` | Validate a data directory |
| `POST` | `/api/calculate` | Run a calculation; returns a `run_id` + summary |
| `GET`  | `/api/results?run_id=…` | Page exposure-level results |
| `GET`  | `/api/results/summary/{class\|approach}?run_id=…` | Portfolio summary |
| `POST` | `/api/comparison` | Run CRR and Basel 3.1 with deltas |
| `GET`  | `/api/comparison/export/{csv\|parquet\|excel}?comparison_id=…` | Download a comparison |
| `POST` | `/api/reconcile` | Reconcile against a legacy output; returns a `recon_id` + tiers. Optional `run_id` reuses a registered calculation instead of re-running the pipeline (404 unknown, 422 mismatch) |
| `GET`  | `/api/reconcile/export/{csv\|excel}?recon_id=…` | Download the reconciliation |
| `GET`  | `/api/export/{parquet\|csv\|excel\|corep\|pillar3}?run_id=…` | Download an export |

```bash
curl -X POST http://localhost:8000/api/calculate \
  -H 'content-type: application/json' \
  -d '{"data_path": "/path/to/data", "framework": "CRR", "reporting_date": "2025-01-01"}'
```

The API is also importable without the web server:

```python
from rwa_calc.api import create_api_app  # a FastAPI app exposing the router
```

---

## Data requirements

The UI expects the same directory layout as the Python API:

```
your_data_directory/
├── counterparty/counterparties.parquet
├── exposures/
│   ├── facilities.parquet
│   └── loans.parquet
├── collateral/collateral.parquet     # optional
├── guarantee/guarantee.parquet       # optional
└── ratings/ratings.parquet           # optional
```

See [Input Schemas](../data-model/input-schemas.md) for field requirements.

---

## Packaging for local distribution (moonlit)

Because the UI is pure-Python and server-rendered (templates, CSS and SVG charts
ship as package data — no JS build artifact), it bundles into a single
self-contained zipapp with [moonlit](https://github.com/OpenAfterHours/moonlit):

```bash
moonlit build -e rwa_calc.ui.app.main:main -o rwa-ui.pyz
```

Recipients run `rwa-ui.pyz` with a matching Python; moonlit extracts to a local
cache on first run, so the FastAPI static files (including the brand tokens)
serve normally. No Node toolchain or internet access is required.

---

## Troubleshooting

**Port 8000 already in use** — run the app on another port:
```bash
uv run uvicorn "rwa_calc.ui.app.main:create_app" --factory --port 8080
```

**Data path not found** — use an absolute path and confirm the mandatory files
(counterparties, facilities, loans) exist in the expected layout.

**Calculation errors** — check the issues panel on the results page; see
[Data Validation](../data-model/data-validation.md) for field requirements.

---

## Next steps

- [Configuration Guide](configuration.md)
- [Calculation Methodology](methodology/index.md)
- [Data Model](../data-model/index.md)
