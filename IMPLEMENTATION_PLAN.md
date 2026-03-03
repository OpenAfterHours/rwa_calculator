# Documentation Update Implementation Plan

Full audit of `docs/` vs `src/rwa_calc/` completed 2026-03-02. This plan covers all
discrepancies, outdated content, and missing documentation.

**Completed:** Priority 1 (API Reference), Priority 2 (Data Model), Priority 3.1-3.3 (Features),
Priority 5.1-5.3 (Specs/Nav). See git history for detailed completion notes.

---

## Bugs Found & Fixed During Documentation Audit

### CRM Corporate Bond Haircut CQS Grouping (CRR Art. 224)

The code grouped corporate bond haircuts as CQS 1-2 / CQS 3, but CRR Art. 224 Table 1 specifies
CQS 1 / CQS 2-3. CRR >5yr corporate bond haircuts were wrong: code had 6%/8% vs regulation
8%/12%. The CQS grouping error also affected Basel 3.1 values (CQS 2 was getting CQS 1 haircuts
instead of CQS 2-3 haircuts).

Fixed in 6 files: `crr_haircuts.py`, `haircuts.py`, `haircuts_namespace.py`,
`test_crm_basel31.py`, `workbooks/data/crr_params.py`, `workbooks/calculations/crr_haircuts.py`.

### SA Methodology Doc Corrections (found via code comparison)

- CRR Corporate CQS 3: 75% -> 100% (confirmed per CRR Art. 122, matches code)
- Basel 3.1 RRE LTV bands: entire table was shifted by one row (verified against `b31_risk_weights.py`)
- Equity risk weights: 150% values didn't exist in code; corrected to 250%/400% per `crr_equity_rw.py`
- QRRE transactor 45%: not specified in specs, not implemented in code -- removed from docs
- Defaulted SA provision-coverage treatment: not implemented -- removed from docs
- CRR residential mortgage: added split treatment note
- CRE LTV thresholds: added CRR preferential 50% treatment
- Code snippet line references: removed stale line numbers
- SME threshold: corrected GBP approximation
- Propagated CRR CQS 3 error fixed in 4 additional doc files

---

## Priority 1 -- Critical: API Reference Out of Sync with Source

**COMPLETED 2026-03-02.** All API reference docs (1.1-1.6) rewritten to match source code:
bundles, errors, protocols, domain enums, engine modules, configuration.

---

## Priority 2 -- High: Data Model Schemas Use Wrong Column Names

**COMPLETED 2026-03-02.** All data model docs (2.1-2.5) rewritten to match source code:
intermediate/output/input schemas, validation functions, regulatory tables.

---

## Priority 3 -- Medium: Missing Feature Documentation

**3.1-3.3 COMPLETED 2026-03-03.** COREP reporting, comparison & impact analysis, FX conversion
docs created/verified.

### 3.4 Document `api/` subpackage modules

**Source**: `src/rwa_calc/api/`

- [ ] Add export section to `docs/api/service.md` (or create separate page)
- [ ] Document `ResultsCache` -- caching behaviour, cache directory, invalidation
- [ ] Document `DataPathValidator` and data directory structure expectations
- [ ] Document `ResultFormatter` for custom formatting

---

## Priority 4 -- Low: User Guide & Architecture Accuracy Check

### 4.1 Review User Guide Methodology pages against source

- [x] `docs/user-guide/methodology/standardised-approach.md` -- Fixed CRR Corporate CQS 3
  (75%->100%), Basel 3.1 RRE LTV table row shift, equity risk weights (150%->250%/400%), removed
  unimplemented QRRE transactor and defaulted provision-coverage, added CRR residential split
  treatment and CRE preferential 50%, corrected SME threshold GBP approximation, removed stale
  line numbers. Also found and fixed CRM haircut CQS grouping bug (see above).
- [x] `docs/user-guide/methodology/irb-approach.md` -- Fixed IRBCalculator API signature
  (takes CRMAdjustedBundle, returns LazyFrameResult), calculate_expected_loss import path
  (formulas not calculator), removed fictional scipy fallback, fixed A-IRB LGD floors to PRA
  values, added Basel 3.1 F-IRB LGD column, added SME EUR conversion to correlation section
  and worked example, replaced all stale snippet line references with method name references.
- [x] `docs/user-guide/methodology/crm.md` -- Fixed corporate bond CQS grouping (CQS1/CQS2-3
  not CQS1-2/CQS3), added Basel 3.1 F-IRB LGD column to physical collateral table, added
  5-year cap to maturity mismatch formula, fixed data structure column names (beneficiary_reference
  not counterparty_id, market_value not value, etc.), replaced stale snippet references,
  added get_crm_adjusted_bundle to processor API example.
- [ ] `docs/user-guide/methodology/specialised-lending.md` (293 lines)
- [x] `docs/user-guide/methodology/equity.md` -- Added Basel 3.1 removes IRB equity note,
  expanded IRB Simple table with missing types (unlisted, speculative, CIU), added
  framework-aware approach determination table.
- [x] `docs/user-guide/methodology/supporting-factors.md` -- Fixed API example (uses
  SupportingFactorCalculator class not module-level functions), corrected GBP threshold
  approximations (44m->43.7m, 2.2m->2.18m) to match 0.8732 rate, updated worked example.
- [x] `docs/user-guide/methodology/fx-conversion.md` -- Fixed column names (currency_from/
  currency_to not source_currency/target_currency), corrected GBP SME threshold, removed
  misleading base_currency config parameter.

### 4.2 Review Architecture pages for accuracy

- [ ] `docs/architecture/components.md` (748 lines)
- [ ] `docs/architecture/pipeline.md` (503 lines)
- [ ] `docs/architecture/data-flow.md` (471 lines)
- [ ] `docs/architecture/pipeline-collect-barriers.md` (121 lines)

### 4.3 Review User Guide Exposure Classes

- [ ] `docs/user-guide/exposure-classes/central-govt-central-bank.md` (220 lines)
- [ ] `docs/user-guide/exposure-classes/institution.md` (232 lines)
- [ ] `docs/user-guide/exposure-classes/corporate.md` (284 lines)
- [ ] `docs/user-guide/exposure-classes/retail.md` (393 lines)
- [ ] `docs/user-guide/exposure-classes/other.md` (358 lines)

### 4.4 Review User Guide Regulatory Framework pages

- [ ] `docs/user-guide/regulatory/crr.md` (285 lines)
- [ ] `docs/user-guide/regulatory/basel31.md` (336 lines)
- [ ] `docs/user-guide/regulatory/comparison.md` (407 lines)

### 4.5 Review Development pages

- [ ] `docs/development/testing.md` (536 lines)
- [ ] `docs/development/extending.md` (585 lines)
- [ ] `docs/development/workbooks.md` (275 lines)
- [ ] `docs/development/benchmarks.md` (390 lines)
- [ ] `docs/development/code-style.md` (436 lines)

---

## Priority 5 -- Housekeeping: Specifications & Navigation

### 5.1 Audit Specifications section against source

**COMPLETED 2026-03-03.** Synced `docs/specifications/` from `specs/` and fixed internal
inconsistencies. Also fixed `specs/overview.md` COREP status and
`specs/regulatory-compliance.md` provisions scenario range.

**Spec verification against source code -- COMPLETED 2026-03-03.**

All 10 spec files verified exhaustively against source code. Discrepancies found and fixed:

- [x] `specs/crr/sa-risk-weights.md` -- All values match. EU Standard Unrated (100%) correctly
  documents the EU standard; code implements UK deviation (40%) which is correct for UK scope.
- [x] `specs/crr/firb-calculation.md` -- Fixed FI Scalar description: "applied to capital
  requirement" → "applied to correlation coefficient" per CRR Art. 153(2).
- [x] `specs/crr/airb-calculation.md` -- All values match exactly (LGD floors, PD floors,
  formulas, defaulted treatment). No changes needed.
- [x] `specs/crr/credit-conversion-factors.md` -- Fixed provision_on_nominal formula: added
  `min(..., nominal_amount)` cap to match code's defensive capping.
- [x] `specs/crr/credit-risk-mitigation.md` -- Fixed corporate bond CQS grouping (CQS 1-2/CQS 3
  → CQS 1/CQS 2-3), 5y+ haircut values (6%/8% → 8%/12%), maturity mismatch T definition
  (constant 5 → min(exposure_maturity, 5)), and no-adjustment conditions (collateral >= exposure
  maturity, not >= 5 years; collateral < 3 months, not exposure <= 3 months).
- [x] `specs/crr/slotting-approach.md` -- Fixed IRB Simple equity risk weights: Listed 190%→290%,
  Unlisted 290%→370%, added Private Equity Diversified at 190% per CRR Art. 155.
- [x] `specs/crr/provisions.md` -- Fixed pro-rata distribution basis: `ead_gross` →
  `max(0, drawn_amount) + interest + nominal_amount` (ead_gross doesn't exist at that pipeline
  stage). Added provision_on_nominal cap at nominal_amount.
- [x] `specs/crr/supporting-factors.md` -- Fixed blended formula variable: `E` (total exposure) →
  `D` (drawn + interest, on-balance-sheet amount) to match code behavior.
- [x] `specs/basel31/framework-differences.md` -- All values match exactly (PD floors, LGD floors,
  F-IRB supervisory LGD, scaling factors, output floor schedule, slotting weights). No changes needed.
- [x] `specs/common/hierarchy-classification.md` -- Fixed entity type to exposure class mapping
  table (RGLA, PSE, MDB are separate classes, not CENTRAL_GOVT_CENTRAL_BANK). Updated entity type
  names to match source code (lowercase). Fixed facility undrawn formula (added contingent
  deduction). Corrected CRR retail threshold approximation (GBP 880k → ~873k) and QRRE limit
  (GBP 100k → ~87k for CRR).

Also fixed `b31_risk_weights.py` CRE reference comments: investment-grade CRE20.47-49→CRE20.44,
SME CRE20.47-49→CRE20.47, subordinated debt CRE20.47→CRE20.49.

**Internal inconsistencies noted in `specs/`:**
- Acceptance test group numbering: `index.md` lists groups A-H but compliance matrix has A, C-I
- Provisions test count: `crr/provisions.md` lists CRR-G=17 but compliance matrix lists CRR-G=7

### 5.2-5.3 Navigation & Features index

**COMPLETED 2026-03-03.** mkdocs.yml and features index updated.

- [ ] Verify all existing nav entries still point to valid files
- [ ] Verify technology stack list is current

### 5.4 Update `docs/appendix/changelog.md`

- [ ] Add entry for documentation overhaul
- [ ] Verify recent changelog entries are accurate

---

## Execution Summary

1. **Priority 1** (API Reference): COMPLETED 2026-03-02
2. **Priority 2** (Data Model): COMPLETED 2026-03-02
3. **Priority 3** (Missing Features): 3.1-3.3 COMPLETED 2026-03-03; 3.4 remaining
4. **Priority 4** (User Guide): 4.1 methodology pages DONE (6 of 7); rest remaining
5. **Priority 5** (Housekeeping): 5.1-5.3 COMPLETED 2026-03-03; 5.4 remaining. Spec verification COMPLETED 2026-03-03.

**Scope:** ~15 files rewritten (P1-2 done), ~5 new files (3 done, 2 remaining), ~25 files need
review (~4 done, ~21 remaining). Total: ~45 documentation files affected.
