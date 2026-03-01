# Implementation Plan

Status legend: `[ ]` = not started, `[~]` = partial, `[x]` = done

## Priority 1 — CRR Completion (v1.0) — COMPLETE

All Priority 1 items are done. **87/87 CRR acceptance tests pass (100%)**. CI/CD pipeline deployed. All 3 quality gates pass: ruff clean, mypy clean, all tests pass.

## Priority 2 — Basel 3.1 Core (v1.1)

### 2a. Engine gaps — COMPLETE

Completed: PD floor per exposure class, LGD floor per collateral type, F-IRB supervisory LGD, A-IRB CCF floor, CCF for unconditionally cancellable commitments, Equity calculator Basel 3.1 routing, A-IRB LGD floor enforcement (gated on `is_airb`, subordinated unsecured 50%).

### 2b. SA risk weight revisions — COMPLETE

- [x] **LTV-based residential RE risk weights** (FR-1.2 / CRE20.71-88) — Done.
- [x] **Revised SA risk weight tables** (FR-1.2 / CRE20.7-26) — Done.

### 2c. CRM Basel 3.1 adjustments — PARTIAL

Done: Revised supervisory haircut tables (CRE22.52-53, 5 maturity bands), F-IRB supervisory LGD framework dispatch (CRE32.9-12), framework-conditional HaircutCalculator/CRMProcessor, A-IRB LGD floor enforcement (CRE30.41, `is_airb` gating).

Remaining (needs specification work):

- [ ] **SFT minimum haircut floors** (CRE56) — New Basel 3.1 requirement for securities financing transactions.
- [ ] **Unfunded credit protection eligibility restrictions** (CRE22.70-85) — Revised eligibility criteria for guarantees and credit derivatives.

### 2d. Testing and validation — COMPLETE

111 Basel 3.1 acceptance tests across 8 files (SA 14, F-IRB 16, A-IRB 13, CRM 15, slotting 13, output floor 6, provisions 20, complex 10). Expected outputs at `tests/expected_outputs/basel31/expected_rwa_b31.json`.

### 2e. Output floor engine — COMPLETE

`sa_rwa` column stored for all rows when output floor is enabled. Floor binding/non-binding detection works correctly.

### 2f. EL shortfall/excess computation — COMPLETE

`compute_el_shortfall_excess()` in IRB namespace. Per-exposure `el_shortfall` / `el_excess` computed in all 3 IRB calculator paths. Aggregator sums `total_el_shortfall` / `total_el_excess`. 14 unit tests, 9 acceptance tests.

## Priority 3 — Dual-Framework Comparison (v1.2)

### 3a. Side-by-side comparison — COMPLETE

- [x] **Side-by-side CRR vs Basel 3.1 comparison output** (M3.1) — Done. `DualFrameworkRunner` in `engine/comparison.py` orchestrates two separate `PipelineOrchestrator` instances (one per framework) on the same `RawDataBundle`. Produces `ComparisonBundle` with per-exposure deltas (delta_rwa, delta_risk_weight, delta_ead, delta_rwa_pct) and summary views by exposure class and approach. 22 unit tests + 19 acceptance tests (SA and F-IRB comparison scenarios).

### 3b. Transitional floor schedule modelling — PARTIAL

Done:

- [x] **Transitional floor schedule modelling** (M3.3) — Done. `TransitionalScheduleRunner` in `engine/comparison.py` runs 6 separate `PipelineOrchestrator` instances (one per transitional year 2027-2032) with freshly created `CalculationConfig.basel_3_1()` configs. Produces `TransitionalScheduleBundle` (frozen dataclass in `contracts/bundles.py`) with a `timeline` LazyFrame (reporting_date, floor_pct, total_rwa, total_ead, irb_rwa_pre_floor, sa_rwa, floor_impact_rwa, floor_binding_count, floor_non_binding_count) and collected errors. `_extract_floor_metrics()` back-calculates SA RWA from `floor_rwa / floor_pct` since `floor_rwa = floor_pct x SA_RWA`. 19 unit tests + 19 acceptance tests.

Remaining:

- [ ] **Capital impact analysis** (M3.2) — Not Started. Would add delta attribution by driver (PD floor changes, LGD floor changes, scaling factor removal, supporting factor removal, output floor binding).
- [ ] **Enhanced Marimo workbooks for impact analysis** (M3.4) — Not Started. Would add comparison visualization, floor schedule slider, drill-down from portfolio delta to exposure-level drivers.

## Priority 4 — Output & Export

- [~] **Excel / Parquet export** (FR-4.7) — Partial. No programmatic export API yet.
- [ ] **COREP template generation** (FR-4.6) — Not Started. Deferred to v2.0.

## Infrastructure & Cleanup

- [ ] **BDD test scaffold** — Empty scaffold, no actual BDD tests. Low priority.
- [ ] **Runtime skip pattern inconsistency** — Audit remaining runtime skips.

## Test Counts

| Suite | Passed | Skipped |
|---|---|---|
| Unit | 1,357 | 0 |
| Contracts | 123 | 0 |
| Acceptance (CRR) | 91 | 0 |
| Acceptance (Basel 3.1) | 111 | 0 |
| Acceptance (Comparison) | 38 | 0 |
| Integration | 5 | 0 |
| Benchmarks | 4 | 22 |
| **Total** | **1,725** | **22** |

## Learnings

### Architecture & design

- `CRMProcessor(is_basel_3_1=True)` controls both haircut table selection AND F-IRB supervisory LGD values. Pipeline auto-creates processor with `config.is_basel_3_1`.
- `_ensure_components_initialized()` caches the `CRMProcessor` with the first config's `is_basel_3_1` flag and never recreates it. This is why `DualFrameworkRunner` and `TransitionalScheduleRunner` each create separate `PipelineOrchestrator` instances.
- `PDFloors.get_floor()` and `LGDFloors.get_floor()` exist in config but are never called by the engine — the engine uses vectorized `_pd_floor_expression()` / `_lgd_floor_expression()` helpers instead.
- `approach_applied` column uses enum string values: `"standardised"`, `"foundation_irb"`, `"advanced_irb"`, `"slotting"` — not the enum names `"SA"`, `"FIRB"`, etc. Tests must filter on the `.value` form.

### Regulatory rules

- CRM haircut table: CRR uses 3 maturity bands (0-1y, 1-5y, 5y+), Basel 3.1 uses 5 (0-1y, 1-3y, 3-5y, 5-10y, 10y+). Equity haircuts increase from 15%/25% (CRR) to 25%/35% (Basel 3.1).
- CRR Art. 126 CRE treatment: Commercial RE is not a separate exposure class — it's a corporate exposure with commercial property collateral.
- Investment-grade corporate 65% only applies to unrated corporates. SCRA grading only applies to unrated institutions.
- Subordinated debt 150% is checked first in Basel 3.1 override chain because it overrides ALL other treatments.
- A-IRB LGD floors apply only to A-IRB own-estimate LGDs (`is_airb` gating); F-IRB supervisory LGDs are regulatory values and don't need flooring (CRE30.41).
- **B31 SME impact:** Basel 3.1 SME corporates get 85% RW (vs CRR 100%) but lose the 0.7619 supporting factor. Net effect: effective RW rises from 76.19% to 85%, a 12% RWA increase.
- **Maturity effect in transitional schedule:** Total post-floor RWA is NOT monotonically non-decreasing across years because effective maturity shortens as reporting date advances (e.g., a 2033 loan has 6y maturity from 2027 but only 5y from 2028). The maturity adjustment decrease can outweigh the floor increase. The correct monotonicity invariant is that `floor_impact_rwa` is non-decreasing, not total RWA.
- EL shortfall/excess: T2 credit cap (0.6% of IRB RWA per CRR Art. 62(d)) is not yet computed at portfolio level — only per-exposure shortfall/excess is tracked.

### Testing patterns

- F-IRB acceptance tests require `IRBPermissions.firb_only()` (not `full_irb()`) and reporting date 2027-06-30 to get meaningful maturities from fixture loans (maturity dates 2028-2033).
- For QRRE PD floors, `is_qrre_transactor` column does not exist yet. Defaults to revolver floor (0.10%) which is conservative.
- For LGD floors, `collateral_type` column may not be available at IRB stage. Default unsecured floor (25%) is applied when absent.
- Orphaned collateral/guarantee fixtures (`LOAN_COLL_TEST_CORP_*`, `LOAN_GUAR_TEST_*`, `LOAN_PROV_TEST_*`) are safe to ignore — beneficiary references point to non-existent dedicated test loans.

### Known discrepancies

- Workbook `regulatory_params.py` uses BCBS schedule (starts 2025) while engine uses PRA PS9/24 UK schedule (starts 2027). Engine is correct for UK firms.
- Workbook PD floor: `PD_FLOORS["CORPORATE"] = 0.0003` (CRR 0.03%) vs production config `0.0005` (Basel 3.1 0.05% per CRE30.20). Workbook needs updating.
- **Spec inconsistencies:** `specs/regulatory-compliance.md`, `specs/nfr.md`, `specs/milestones.md` have stale test counts and status flags.

### SA RWA back-calculation

`_extract_floor_metrics()` back-calculates SA RWA from `floor_rwa / floor_pct` since `floor_rwa = floor_pct x SA_RWA`. This avoids requiring SA RWA to be separately tracked in the aggregated result.
