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

The UI dependencies (FastAPI, Uvicorn, Jinja, Marimo) ship with the base
package — no extra is required.

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
| **Workbench** | `/workbench` | Launch the editable Marimo notebook editor (port 8002) |

Charts on the results, comparison and reconciliation pages are rendered as inline
SVG themed with the documentation palette.

---

## Calculator

The calculator (`/calculator`) runs the full pipeline through a form.

| Field | Description |
|-------|-------------|
| **Data path** | Directory of Parquet/CSV inputs (see [Input Schemas](../data-model/input-schemas.md)) |
| **Framework** | CRR (Basel 3.0) or Basel 3.1 |
| **Permission mode** | Standardised (all SA) or IRB (driven by `model_permissions`) |
| **Data format** | Parquet (recommended) or CSV |
| **Reporting date** | Calculation reference date |

Submitting validates the data path, runs the calculation, and redirects to the
results page for that run. Results show total RWA/EAD, exposure count and average
risk weight; the RWA/IRB/SA/Slotting split and output-floor impact; charts of RWA
and EAD by exposure class and RWA by approach; and a sample of the exposure-level
output. Any data-quality issues are listed beneath the results.

---

## Comparison

The comparison page (`/comparison`) runs the portfolio through **both**
frameworks and shows an executive summary, the additive capital-impact waterfall
(scaling factor, supporting factor, methodology, output floor), and a per-class
breakdown. It takes roughly twice a single-framework run.

---

## Reconciliation

The reconciliation page (`/reconciliation`) reconciles this calculator's output
against a **legacy** calculator's output, component by component, for migration
confidence. Enter your data path, edit the TOML mapping (which names the legacy
file, the join keys and how each legacy column maps to a canonical component)
directly in the form, and run. The result is shown across four drill-down tiers —
the headline tie-out and per-component summary, the by-bucket / by-class /
by-approach segmentation, the break worklist ranked by materiality, and a per-key
forensic table with a bucket filter — plus CSV / Excel downloads of the full
per-key detail. See the [Reconciliation guide](../reconciliation/index.md) for the
mapping grammar and the output reference.

---

## Workbench

The polished pages above are read-only. For ad-hoc analysis, the Workbench page
launches the **Marimo editor** (a separate edit server on port 8002) pointed at
`workspaces/`. Marimo notebooks are reactive, reproducible, and git-friendly
plain-Python files; new notebooks start from `workspaces/templates/starter.py`,
which wires in the engine API and the shared sidebar.

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
| `POST` | `/api/reconcile` | Reconcile against a legacy output; returns a `recon_id` + tiers |
| `GET`  | `/api/reconcile/export/{csv\|excel}?recon_id=…` | Download the reconciliation |
| `GET`  | `/api/export/{parquet\|csv\|excel\|corep}?run_id=…` | Download an export |

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
