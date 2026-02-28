# Implementation Plan

## Priority 1 — CRR Completion (v1.0)

- [ ] **CRR-A7: Commercial RE acceptance test** — skipped, fixture gaps. Investigate what test data/fixture is missing and implement. See `specs/sa-calculator.md`.
- [ ] **CRR-A8: OBS CCF acceptance test** — skipped, fixture gaps. Investigate what test data/fixture is missing and implement. See `specs/sa-calculator.md`.
- [ ] **CRR-C3: SL A-IRB acceptance test** — skipped, fixture gaps. Investigate what test data/fixture is missing and implement. See `specs/irb-calculator.md`.
- [ ] **CI/CD pipeline** (M1.6) — currently partial. Complete linting, type checking, and test automation. See `specs/milestones.md`.

## Priority 2 — Basel 3.1 Core (v1.1)

- [ ] **LTV-based residential RE risk weights** (FR-1.2 / CRE20.71) — Not Started. SA risk weights that vary by loan-to-value ratio. See `specs/sa-calculator.md`.
- [ ] **Revised SA risk weight tables** (FR-1.2 / CRE20.7–26) — Partial. Complete the Basel 3.1 SA risk weight mappings. See `specs/sa-calculator.md`.
- [ ] **A-IRB LGD floors** (FR-1.5 / CRE32) — Not Started. Minimum LGD values by collateral type. See `specs/irb-calculator.md`.
- [ ] **Differentiated PD floors** (FR-1.9) — Not Started. Per-class PD floors (sovereign, bank, corporate, retail sub-classes) replacing uniform 0.03%. See `specs/irb-calculator.md`.
- [ ] **Configurable PD/LGD floors in CalculationConfig** (FR-5.4) — Partial. Expose new floors via config factory methods. See `specs/configuration.md`.
- [ ] **Output floor phase-in validation tests** (M2.6) — engine done, tests pending. Write acceptance tests for 2027–2032 schedule. See `specs/output-reporting.md`.
- [ ] **Basel 3.1 expected outputs** (M2.1) — Not Started. Hand-calculated reference workbooks for B31 scenarios. See `specs/milestones.md`.
- [ ] **Basel 3.1 acceptance tests** (M2.5) — Not Started. B31-A (SA revised) and B31-F (output floor) scenarios. See `specs/regulatory-compliance.md`.

## Priority 3 — Dual-Framework Comparison (v1.2)

- [ ] **Side-by-side CRR vs Basel 3.1 comparison output** (M3.1) — Not Started. See `specs/milestones.md`.
- [ ] **Capital impact analysis** (M3.2) — Not Started. Delta RWA by approach, class, portfolio. See `specs/milestones.md`.
- [ ] **Transitional floor schedule modelling** (M3.3) — Not Started. Year-by-year output floor impact. See `specs/milestones.md`.
- [ ] **Enhanced Marimo workbooks for impact analysis** (M3.4) — Not Started. See `specs/milestones.md`.

## Priority 4 — Output & Export

- [ ] **Excel / Parquet export** (FR-4.7) — Partial. Complete export functionality. See `specs/output-reporting.md`.
- [ ] **COREP template generation** (FR-4.6) — Not Started. P3, deferred to v2.0. See `specs/output-reporting.md`.

## Learnings

_(Updated by the loop as issues are discovered and resolved)_
