# Securitisation Pool Allocation — Phase 1 (Flag & Exclude)

**Status:** Phase 1 (flag + exclude) shipped.
**Out of scope (phase 2+):** SEC-SA / SEC-IRBA / SEC-ERBA RWA calculation,
significant risk transfer assessment, tranche-level capital, retained interest.

## Purpose

Firms originate loans and other exposures and routinely transfer some or
all of their economic interest into securitisation pools (traditional
SPVs or synthetic transactions). Once significant risk transfer is
achieved (CRR Art. 244–246 / PS1/26 equivalents), the originator excludes
the securitised portion from standard credit-risk RWA and instead
calculates RWA under the securitisation framework (CRR Art. 248–264 /
SEC-SA, SEC-IRBA — PS1/26 Art. 147A(1)(j)).

Phase 1 lets users **flag** the securitised portion so downstream
reporting can carve it out of standard RWA totals. The securitisation
RWA framework itself is deferred to phase 2.

## Input schema

The user supplies an optional `securitisation_allocations` table —
many rows per exposure when the exposure is split across more than one
pool. Loaded from `securitisation/securitisation_allocations.parquet`
via the data source registry.

| Column | Type | Required | Notes |
|---|---|---|---|
| `exposure_reference` | String | Yes | Native key on the source table (loan_reference / contingent_reference / facility_reference). |
| `exposure_type` | String | Yes | One of `loan`, `contingent`, `facility`. Validated by `COLUMN_VALUE_CONSTRAINTS`. |
| `pool_reference` | String | Yes | Free-text pool / SPV identifier. |
| `allocation_pct` | Float64 | Yes | Fraction transferred to this pool. Each row must be in `(0, 1]`; per-exposure sums must be in `[0, 1]`. |
| `transfer_type` | String | No | `traditional` (default) or `synthetic`. Carried for future use; not consumed in phase 1. |
| `significant_risk_transfer` | Boolean | No | SRT assertion by the firm (default `True`). Phase 1 trusts the flag — the engine does not validate Art. 244–246 conditions. |
| `effective_date` | Date | No | Carried for audit trail. |

When `exposure_type = "facility"`, the allocation applies to the
synthetic `facility_undrawn` exposure derived from that facility's
unused commitment — not to any drawn loan mapped to the facility.

## Algebra

For every per-row pipeline output, the aggregator multiplies every
monetary column by `securitisation_residual_pct`:

```
on_balance_sheet_ead  = ead_final  × securitisation_residual_pct
on_balance_sheet_rwa  = rwa_final  × securitisation_residual_pct
on_balance_sheet_el   = expected_loss × securitisation_residual_pct
```

where `securitisation_residual_pct = 1 - sum(allocation_pct)`, clipped
to `[0, 1]`. Per-pool contributions are derived by exploding the
`securitisation_pool_allocations` struct list and multiplying by each
`allocation_pct`:

```
pool_X_ead = ead_final × allocation_pct_X     # for each pool in the struct list
```

The two sets reconcile: `residual + sum(pool_pct) = 1` (when not
over-allocated) implies `on_balance_sheet_ead + sum(pool_ead) = ead_final`.

## Why late multiplication (not pre-CRM scaling)?

The CRM → RWA formula is linear in (EAD, collateral) when both scale
by the same factor. For a single exposure with direct-attached
collateral:

- £1m loan, £600k collateral, 50% securitised, secured_rw = 35%,
  unsecured_rw = 100%
- Late multiplication: full RWA = 600k × 0.35 + 400k × 1.00 = £610k;
  residual = ×0.5 → 300k × 0.35 + 200k × 1.00 = **£305k**
- Pre-CRM scaling: scale EAD + collateral to £500k / £300k; RWA =
  300k × 0.35 + 200k × 1.00 = **£305k**

Same answer. LTV-band step-functions also produce the same answer
because `LTV = collateral / EAD` is invariant to a common scaling
factor. The linearity property is pinned in
`tests/integration/test_securitisation_pipeline.py::test_sec_06_residual_equals_pro_rata_via_linearity`.

The only place these two approaches diverge is **shared counterparty /
facility-level collateral** that allocates pro-rata across multiple
exposures of the same counterparty. Pre-CRM scaling would re-distribute
the spare collateral to the un-securitised siblings; late multiplication
leaves it where the CRM stage put it on the full inputs. That second-
order effect is a known phase-1 limitation (see below).

## Validation rules

The allocator stage runs five validation checks in order:

| Code | Trigger | Severity | Outcome |
|---|---|---|---|
| `SEC002` | `allocation_pct <= 0` or `> 1` or null | ERROR | Row dropped before per-exposure aggregation. |
| `SEC003` | `exposure_reference` does not resolve to any loan / contingent / facility | WARNING | Row dropped. |
| `SEC004` | Duplicate `(exposure_reference, pool_reference)` | WARNING | First row kept, others dropped. |
| `SEC001` | Per-exposure sum > 1 (after dedup) | ERROR | All pool slices dropped for that exposure; residual_pct = 1.0; `audit_status = "over_allocated"`. |
| `SEC005` | Per-exposure sum == 1 (residual = 0) | WARNING | Exposure flows through pipeline with zero on-balance-sheet contribution; `audit_status = "fully_securitised"`. |

All errors accumulate in `RawDataBundle.errors` (the loader-validation
channel) so the original `SEC###` codes survive verbatim into
`AggregatedResultBundle.errors`.

## Bundle wiring

- `RawDataBundle.securitisation_allocations` — raw input table.
- `ResolvedHierarchyBundle.securitisation_audit` — resolved per-exposure
  lookup (one row per securitised exposure carrying residual_pct,
  pool_allocations struct list, audit_status).
- `ClassifiedExposuresBundle.securitisation_audit` — pass-through.
- `CRMAdjustedBundle.securitisation_audit` — pass-through.
- `AggregatedResultBundle.securitisation_summary` — per-pool grouping
  (`pool_reference`, `exposure_count`, `total_ead`,
  `total_rwa_placeholder`, `total_expected_loss`).
- `AggregatedResultBundle.securitisation_audit` — per-exposure
  reconciliation (`exposure_reference`, `parent_ead`, `residual_ead`,
  `securitised_ead`, `reconciliation_delta`, `audit_status`).

The `total_rwa_placeholder` column is a memorandum value computed as
`standard_rwa × allocation_pct`. It is **not** regulatory capital — the
actual securitisation-framework RWA (SEC-SA / SEC-IRBA) lands in phase 2.

## Pipeline position

```
Loader → SecuritisationAllocator → HierarchyResolver → Classifier
       → CRMProcessor → RealEstateSplitter → SA/IRB/Slotting Calculators
       → OutputAggregator
```

The allocator runs immediately after the loader. It does **not** scale
any input amounts — its sole job is to resolve the allocations table
into the per-exposure columns and emit the audit frame. Every other
pipeline stage runs unmodified; the new columns ride through.

## Known limitations (phase 1)

- **Shared collateral re-allocation**: counterparty-level or facility-
  level collateral that the CRM stage pro-rates across multiple
  exposures of the same counterparty does **not** re-allocate to the
  un-securitised siblings when one exposure is securitised. The CRM
  stage runs on the full inputs; only the multiplier at the aggregator
  reflects securitisation. For single-exposure metrics with directly-
  attached collateral this is mathematically equivalent to pro-rata
  scaling (linearity argument above); for shared collateral it
  understates the residual book's secured ratio. Fixing this properly
  requires re-running the CRM allocation against the residual amounts —
  deferred to phase 2.
- **No SRT validation**: the engine trusts the firm's
  `significant_risk_transfer` flag. Art. 244–246 conditions (operational
  requirements, third-party investor, etc.) are not checked.
- **No securitisation-framework RWA**: pool slices carry a placeholder
  `total_rwa_placeholder = standard_rwa × allocation_pct` for memorandum
  reporting only. SEC-SA / SEC-IRBA / SEC-ERBA calculation, retained
  interest treatment, and tranche-level capital are deferred to phase 2.
- **No COREP / Pillar 3 templates**: the per-pool summary is exposed on
  the bundle but is not yet wired into the regulatory reporting
  templates (OF 02.01, Pillar 3 SEC tables).

## References

- **CRR Art. 109** — gateway to the securitisation framework.
- **CRR Art. 244** — traditional securitisation, significant risk transfer.
- **CRR Art. 245** — synthetic securitisation.
- **CRR Art. 246** — early-amortisation operational safeguards.
- **CRR Art. 248–264** — securitisation RWA framework (phase 2).
- **PRA PS1/26 Art. 147A(1)(j)** — securitisation positions excluded from IRB.
