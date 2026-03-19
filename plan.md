# Documentation Review & Update Plan

## Review Summary

After comparing all documentation files against the actual codebase, the following discrepancies and issues have been identified. Items are grouped by priority.

---

## Priority 1: Stale Test Counts & Statistics

Multiple documents reference outdated test counts. The actual counts (as of today) are:

| Category | Documented | Actual | Where Documented |
|----------|-----------|--------|-----------------|
| Unit | 1,485 | **1,522** | `docs/development/testing.md` |
| Acceptance | 275 | 275 (correct) | `docs/development/testing.md` |
| Contract | 123 | 123 (correct) | `docs/development/testing.md` |
| Integration | **5** | **100** | `docs/development/testing.md` |
| Benchmarks | 27-34 | 27-34 (correct) | `docs/development/testing.md` |
| **Total** | **~1,915** | **~2,047** | `docs/development/testing.md` |

Additionally:
- **`docs/index.md:148`** says "1,286+ tests" — should be ~2,047
- **`CLAUDE.md`** says "~1,050 unit tests" and "~74 acceptance tests" — vastly outdated
- **`docs/plans/roadmap.md:22`** says "CRR Acceptance Tests: 74 tests (71 pass, 3 skip)" — outdated, now 97 CRR acceptance tests per milestones.md

### Files to update:
1. `docs/development/testing.md` — Update unit count (1,522), integration count (100), total (~2,047)
2. `docs/index.md:148` — Update test count from "1,286+" to "2,047+"
3. `CLAUDE.md` — Update test counts from "~1,050 unit / ~74 acceptance" to "~1,522 unit / ~275 acceptance"
4. `docs/plans/roadmap.md` — Update Phase 1 CRR test count and Basel 3.1 status (no longer "Not Started")

---

## Priority 2: Outdated Version in Specifications

- **`docs/specifications/overview.md:8`** says version "0.1.29 (Pre-Release)" — should be **0.1.37**

### Files to update:
1. `docs/specifications/overview.md` — Update version to 0.1.37

---

## Priority 3: Roadmap/Milestones vs Actual State

**`docs/plans/roadmap.md`** has several outdated entries:

- Phase 1: "Basel 3.1 Expected Outputs" marked "Not Started" — this is **complete** (116 Basel 3.1 acceptance tests exist and pass)
- Phase 3: "Risk weight tables" Basel 3.1 status marked "Planned" — **complete** (`data/tables/b31_risk_weights.py` exists)
- Phase 3: Several test counts are stale (e.g., CCF: 57, Loader: 31, Hierarchy: 66, etc.)
- Phase 2: Contract test count says 97 — actual contracts tests are 123

The roadmap's phase statuses are inconsistent with `docs/specifications/milestones.md` which correctly shows most milestones as "Done".

### Files to update:
1. `docs/plans/roadmap.md` — Reconcile all statuses with actual codebase; mark Basel 3.1 expected outputs as Complete; update test counts

---

## Priority 4: Loader Code Example Missing Fields

**`docs/architecture/components.md:63-83`** shows the `ParquetLoader.load()` code example with only 10 fields in `RawDataBundle`. The actual `RawDataBundle` also includes:
- `fx_rates`
- `facility_mapping`
- `model_permissions`

The code example is incomplete.

### Files to update:
1. `docs/architecture/components.md` — Update `ParquetLoader` code example to include all RawDataBundle fields

---

## Priority 5: Namespace Count Discrepancy

**`CLAUDE.md`** references "8 Custom Namespaces" but there are actually **9** (the equity namespace `lf.equity` exists in `engine/equity/namespace.py` but is not listed in CLAUDE.md's namespace list).

The `docs/architecture/components.md` namespace table is also missing the equity namespace.

### Files to update:
1. `CLAUDE.md` — Add equity namespace to the list, update count
2. `docs/architecture/components.md` — Add `lf.equity` / `expr.equity` to namespace table

---

## Priority 6: Changelog "Unreleased" Section

**`docs/appendix/changelog.md`** has an `[Unreleased]` section with features that appear to already be implemented in the codebase (model_id move, on-balance sheet netting, COREP templates, model-level IRB permissions, etc.). These should either:
- Be moved under a released version heading (if they shipped in 0.1.37), or
- Be confirmed as truly unreleased and left as-is

### Files to update:
1. `docs/appendix/changelog.md` — Verify whether unreleased items are in 0.1.37 and adjust accordingly

---

## Priority 7: Minor Inconsistencies

1. **`docs/specifications/overview.md:24`** says "9 exposure classes" — the `ExposureClass` enum has **14** members (central_govt_central_bank, institution, corporate, corporate_sme, retail_mortgage, retail_qrre, retail_other, specialised_lending, equity, defaulted, pse, mdb, rgla, other)
2. **`docs/index.md:167`** says "Basel 3.1 Support: In Development" — given all Basel 3.1 milestones are marked "Done" in milestones.md, this should say "Complete" or "Full"
3. **`docs/plans/roadmap.md`** Phase 3 shows Equity Calculator Basel 3.1 as "N/A" — but equity has Basel 3.1-specific weights in the codebase
4. **`docs/development/testing.md`** test structure tree doesn't show `bdd/` directory (which exists in `tests/bdd/`)

### Files to update:
1. `docs/specifications/overview.md` — Update exposure class count
2. `docs/index.md` — Update Basel 3.1 support status
3. `docs/plans/roadmap.md` — Update Equity Basel 3.1 status
4. `docs/development/testing.md` — Mention `bdd/` directory in test structure

---

## Summary of All Files Requiring Updates

| File | Changes Needed |
|------|---------------|
| `docs/development/testing.md` | Test counts, integration count, add bdd/ dir |
| `docs/index.md` | Test count, Basel 3.1 status |
| `CLAUDE.md` | Test counts, namespace list |
| `docs/plans/roadmap.md` | Phase statuses, test counts, Basel 3.1 items |
| `docs/specifications/overview.md` | Version number, exposure class count |
| `docs/architecture/components.md` | Loader code example, namespace table |
| `docs/appendix/changelog.md` | Unreleased section review |

**Estimated scope**: 7 files, mostly numerical/status updates. No structural documentation changes needed — the docs are well-organized and architecturally accurate.
