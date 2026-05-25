# Audit cache

The audit cache is an **opt-in** side-effect of a pipeline run that persists
key intermediate frames as parquet files on disk. It exists so users can
inspect *what the engine actually did* — most often to confirm whether the
Art. 224 / Art. 233 FX volatility haircut (`H_fx`) is firing on a specific
collateral row — without re-running internal components manually.

The feature is off by default. When off it is a true no-op: no files, no
collects, no measurable overhead.

> **Contract**: the audit cache is for **operational diagnostics and audit
> trail only**. It must never perturb the calculation. The integration test
> `tests/integration/test_audit_cache_pipeline.py::test_audit_cache_does_not_perturb_rwa_totals`
> pins this — a run with the cache on must produce identical RWA totals to a
> run with it off.

## Enabling the cache

Set `audit_cache_dir` on `CalculationConfig` (or pass it through
`CreditRiskCalc`). Optionally cap the on-disk history with
`audit_cache_max_runs`:

```python
from datetime import date
from pathlib import Path
from rwa_calc.contracts.config import CalculationConfig

config = CalculationConfig.crr(
    reporting_date=date(2024, 12, 31),
    audit_cache_dir=Path("./.rwa_audit"),
    audit_cache_max_runs=10,  # retain the 10 most recent runs
)
```

```python
from rwa_calc.api import CreditRiskCalc

response = CreditRiskCalc(
    data_path="/path/to/data",
    framework="CRR",
    reporting_date=date(2024, 12, 31),
    audit_cache_dir=Path("./.rwa_audit"),
    audit_cache_max_runs=10,
).calculate()
```

## On-disk layout

Each pipeline run writes one subdirectory under `audit_cache_dir`, named for
its `run_id` (the same 12-hex-char id that appears between square brackets on
every text log line and as the `run_id` field on every JSON log line — see
[Observability](observability.md)).

```text
.rwa_audit/
├── a3f0c1b24e1c/
│   ├── collateral_haircuts.parquet
│   ├── collateral_allocation.parquet
│   ├── crm_audit.parquet
│   ├── rating_inheritance.parquet
│   ├── classification_audit.parquet
│   ├── re_split_audit.parquet
│   ├── equity_calculation_audit.parquet
│   ├── pre_crm_summary.parquet
│   ├── post_crm_summary.parquet
│   ├── post_crm_detailed.parquet
│   ├── summary_by_class.parquet
│   ├── summary_by_approach.parquet
│   ├── sa_results.parquet
│   ├── irb_results.parquet
│   ├── slotting_results.parquet
│   ├── equity_results.parquet
│   ├── floor_impact.parquet               # Basel 3.1 only
│   ├── supporting_factor_impact.parquet   # CRR only
│   ├── securitisation_audit.parquet       # only when allocations supplied
│   ├── securitisation_summary.parquet     # only when allocations supplied
│   ├── results.parquet
│   └── manifest.json
└── 7b2c9e0f5d11/
    └── …
```

Writes are atomic: each parquet is staged as `<name>.parquet.tmp` and
`os.replace`'d into its final location, so partial writes never surface to
readers. Failures (disk full, permission denied, streaming-unsupported
expression) are logged at `WARNING` and swallowed — the calculation
continues to completion.

## Artifact reference

### CRM stage

| File | Source | Per-row scope | Why you'd open it |
|---|---|---|---|
| `collateral_haircuts.parquet` | (not on a bundle — only via this cache) | per collateral pledge | **Primary diagnostic.** Confirm whether `H_fx`, `H_c`, or the maturity-mismatch adjustment is firing on a row. |
| `collateral_allocation.parquet` | `CRMAdjustedBundle.collateral_allocation` | per exposure | See how much EAD each collateral category absorbed and the resulting LGD. |
| `crm_audit.parquet` | `CRMAdjustedBundle.crm_audit` | per exposure | Exposure-level CRM waterfall (`ead_gross → ead_after_collateral → ead_after_guarantee → ead_final`). |

### Early pipeline stages

| File | Source | Per-row scope | Why you'd open it |
|---|---|---|---|
| `rating_inheritance.parquet` | `ResolvedHierarchyBundle.counterparty_lookup.rating_inheritance` | per counterparty | Dual-track best-rating resolution. Answers "why does this CP carry CQS=4? Was it inherited from a parent? Is the PD internal or external?" |
| `classification_audit.parquet` | `ClassifiedExposuresBundle.classification_audit` | per exposure | Classification reason trail. Answers "why was this exposure routed to SA instead of IRB? Was it SME? Defaulted?" |
| `re_split_audit.parquet` | `CRMAdjustedBundle.re_split_audit` | per split parent | Real-estate loan-splitter reconciliation: parent EAD, secured/residual split, target class, triggering regime (CRR Art. 125/126 vs B3.1 Art. 124F/H). Only present when at least one row triggered RE splitting. |

### Calculators

| File | Source | Per-row scope | Why you'd open it |
|---|---|---|---|
| `equity_calculation_audit.parquet` | `EquityResultBundle.calculation_audit` | per equity exposure | CIU mandate multiplier and look-through-vs-fallback rationale. |
| `sa_results.parquet` | `AggregatedResultBundle.sa_results` | per exposure | Pre-floor SA view. Diff against `results.parquet` to attribute output-floor uplift back to SA rows. |
| `irb_results.parquet` | `AggregatedResultBundle.irb_results` | per exposure | Pre-floor IRB view. Same diff use case. |
| `slotting_results.parquet` | `AggregatedResultBundle.slotting_results` | per exposure | Pre-floor slotting view. |
| `equity_results.parquet` | `AggregatedResultBundle.equity_results` | per equity exposure | Equity approach output. |

### Aggregator

| File | Source | Per-row scope | Why you'd open it |
|---|---|---|---|
| `pre_crm_summary.parquet` | `AggregatedResultBundle.pre_crm_summary` | per exposure class | Gross view before any CRM substitution. |
| `post_crm_detailed.parquet` | `AggregatedResultBundle.post_crm_detailed` | per exposure (post-split) | Per-row view including guarantee-substitution split rows. |
| `post_crm_summary.parquet` | `AggregatedResultBundle.post_crm_summary` | per exposure class | Net view by effective class after CRM. |
| `summary_by_class.parquet` | `AggregatedResultBundle.summary_by_class` | per exposure class | Aggregated RWA by exposure class. |
| `summary_by_approach.parquet` | `AggregatedResultBundle.summary_by_approach` | per approach | Aggregated RWA by SA / IRB / Slotting / Equity. |
| `floor_impact.parquet` | `AggregatedResultBundle.floor_impact` | per exposure | Identify rows where the output floor bound (Basel 3.1 only — None under CRR). |
| `supporting_factor_impact.parquet` | `AggregatedResultBundle.supporting_factor_impact` | per exposure | SME / infrastructure factor impact (CRR only — None under Basel 3.1). |
| `securitisation_audit.parquet` | `AggregatedResultBundle.securitisation_audit` | per exposure | Per-exposure pool-allocation reconciliation with `SEC001`-`SEC005` status codes. Only present when `securitisation_allocations` was supplied. |
| `securitisation_summary.parquet` | `AggregatedResultBundle.securitisation_summary` | per pool | Per-pool EAD / RWA / EL grouping. Only present when `securitisation_allocations` was supplied. |
| `results.parquet` | `AggregatedResultBundle.results` | per exposure | Final per-exposure RWA result. |

### Conditional artifacts

Not every artifact appears in every run. The following only materialise under
specific conditions:

| Artifact | Condition |
|---|---|
| `floor_impact.parquet` | Basel 3.1 only (CRR has no output floor). |
| `supporting_factor_impact.parquet` | CRR only (Basel 3.1 removed SME / infrastructure factors). |
| `re_split_audit.parquet` | At least one exposure triggered the real-estate loan-splitter. |
| `securitisation_audit.parquet` / `securitisation_summary.parquet` | `securitisation_allocations` was supplied in the input bundle. |
| `crm_audit.parquet` | Always present when the audit cache is enabled — the orchestrator forces the projection that the unified CRM path otherwise skips for performance. |

## `manifest.json` schema

One JSON document per run, written after all parquet artifacts commit:

```json
{
  "run_id": "a3f0c1b24e1c",
  "framework": "CRR",
  "reporting_date": "2024-12-31",
  "started_at": "2026-05-25T09:54:22.831417+00:00",
  "finished_at": "2026-05-25T09:54:25.118903+00:00",
  "elapsed_ms": 2287.49,
  "config": {
    "permission_mode": "standardised",
    "base_currency": "GBP",
    "collect_engine": "cpu",
    "crm_collateral_method": "comprehensive"
  },
  "artifacts": [
    {"name": "collateral_allocation.parquet", "bytes": 12345},
    {"name": "collateral_haircuts.parquet", "bytes": 23456},
    …
  ],
  "error_count": 0
}
```

The `config` block is a deliberately narrow snapshot — it does not echo
every regulatory scalar (those live in `data/tables/`) and it does not echo
the cache fields themselves (avoid recursion). `artifacts` lists every
`*.parquet` actually present in the run directory at the time the manifest
was written, with byte sizes for quick integrity checks.

## Diagnostic recipe — *"is `H_fx` firing on my collateral row?"*

The motivating use case. With `audit_cache_dir` set, open
`collateral_haircuts.parquet` and project the diagnostic columns:

```python
import polars as pl

haircuts = pl.read_parquet(".rwa_audit/a3f0c1b24e1c/collateral_haircuts.parquet")
diag = haircuts.select(
    "collateral_reference",
    "collateral_type",
    "original_currency",
    "exposure_currency",
    "collateral_haircut",
    "fx_haircut",
    "value_after_haircut",
)
print(diag)
```

Interpretation:

- `fx_haircut == 0.0` on a real-estate / receivables / other-physical row
  with `original_currency != exposure_currency` → **expected**. CRR Art. 230
  (Foundation Collateral Method) does not apply `H_fx` to funded
  non-financial collateral; FX risk is captured upstream by the spot-rate
  `FXConverter`. The H_fx scoping fix landed in 0.2.12 and is regression-
  pinned by `tests/unit/crm/test_collateral_fx_mismatch.py`.
- `fx_haircut > 0.0` on a financial collateral row (cash / gold / bond /
  equity / covered-bond / life-insurance / credit-linked-note) with a
  currency mismatch → **expected**. Art. 224 Table 4 / Art. 226 scaling
  applies.
- `fx_haircut > 0.0` on a real-estate row → **misconfiguration**. The
  `collateral_type` value is not in the recognised synonym list at
  `src/rwa_calc/data/schemas.py:1034` (`real_estate`, `property`, `rre`,
  `cre`, `residential_re`, `commercial_re`, `residential`, `commercial`,
  `residential_property`, `commercial_property`). The `is_in` match is
  case-sensitive — normalise to one of those strings (`real_estate` is the
  canonical one; the others are accepted synonyms).
- `original_currency` missing on the input → the upstream `FXConverter`
  rebased to the reporting currency without preserving the pre-conversion
  currency, so the gate at `engine/crm/haircuts.py:210` falls back to
  `currency` (both sides post-rebasing). Fix is to populate
  `original_currency` on the collateral input.

## Diagnostic recipe — *"why was this exposure routed to SA / IRB / Slotting?"*

`classification_audit.parquet` carries one row per exposure with the inputs
that drove its approach assignment:

```python
audit = pl.read_parquet(".rwa_audit/a3f0c1b24e1c/classification_audit.parquet")
audit.filter(pl.col("exposure_reference") == "LN-12345").select(
    "counterparty_reference",
    "cp_entity_type",
    "exposure_class",
    "approach",
    "is_defaulted",
    "is_sme",
    "qualifies_as_retail",
    "reclassified_to_retail",
    "classification_reason",  # concatenated narrative
)
```

Pair it with `rating_inheritance.parquet` to confirm where the counterparty's
CQS came from (own / inherited from parent / external vs internal track):

```python
inh = pl.read_parquet(".rwa_audit/a3f0c1b24e1c/rating_inheritance.parquet")
inh.filter(pl.col("counterparty_reference") == "CP-99")
# → cqs / pd / external_cqs / internal_pd / internal_model_id
```

## Diagnostic recipe — *"did the output floor bind on this exposure?"*

Available under Basel 3.1 only. `floor_impact.parquet` carries the per-row
floor mechanics:

```python
floor = pl.read_parquet(".rwa_audit/a3f0c1b24e1c/floor_impact.parquet")
floor.filter(pl.col("is_floor_binding")).select(
    "exposure_reference",
    "approach_applied",
    "exposure_class",
    "rwa_pre_floor",
    "floor_rwa",
    "rwa_post_floor",
    "floor_impact_rwa",
    "output_floor_pct",
)
```

To attribute the uplift back to a specific approach, diff
`results.parquet` (post-floor) against `sa_results.parquet` /
`irb_results.parquet` / `slotting_results.parquet` (pre-floor) on
`exposure_reference`.

## Retention

`audit_cache_max_runs` is optional. When set, an mtime-ordered prune runs at
the **end** of each pipeline run — after the new run's artifacts and
manifest are committed — so the cap is honoured exactly: after N runs the
directory contains at most `audit_cache_max_runs` subdirectories. Without
the cap, the cache grows without bound and the user is responsible for
clean-up.

The prune only removes entries that are directories (stray files in the
cache root are left alone) and recursively deletes the directory's contents
before `rmdir`. Failures during prune are logged at `WARNING`.

## Performance and data sensitivity

The cache is opt-in for two reasons:

1. **Materialisation cost.** Several of the cached frames (notably
   `collateral_haircuts`) live inside deep lazy plans and are never
   collected on a hot pipeline run. Sinking forces a `sink_parquet`
   write — sub-second on portfolios up to ~100k collateral rows, but
   non-zero and worth measuring before turning on for very large or
   throughput-sensitive deployments.
2. **Data sensitivity.** The artifacts include counterparty / exposure /
   collateral references. They may be PII or commercially sensitive
   depending on the input data. Defaulting to a writable cache path is the
   kind of surprise that lands in a regulated-firm incident review;
   enabling the cache is a deliberate operator decision.

The cache writer is `engine/materialise.sink_audit` — the **only** place
`sink_parquet` is invoked outside the streaming-mode spill path
(`scripts/arch_check.py` enforces this rule). New artifact types should be
added by calling `sink_audit` from the existing CRM / orchestrator hook
points; no new sink call sites should appear outside `materialise.py`.

## Related

- [Observability](observability.md) — `run_id` lifecycle and log
  correlation.
- `tests/unit/observability/test_audit_cache.py` — sink and prune semantics.
- `tests/integration/test_audit_cache_pipeline.py` — end-to-end layout and
  RWA-parity regression.
- `tests/contracts/test_audit_cache_contract.py` — column-set regression
  guards for the three CRM artifacts.
