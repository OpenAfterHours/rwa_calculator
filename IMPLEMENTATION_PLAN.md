# Implementation Plan

**Last updated:** 2026-04-05
**Current version:** 0.1.64 | **Test suite:** ~1,925 collected, ~43 skipped (benchmarks + xlsxwriter)
**CRR acceptance:** 100% (97 tests) | **Basel 3.1 acceptance:** 100% (116 tests) | **Comparison:** 100% (62 tests)
**Acceptance tests skipped at runtime:** ~90 (conditional `pytest.skip()` when fixture data unavailable)

## Status Legend
- [ ] Not started
- [~] Partial / needs rework
- [x] Complete

---

## Priority 1 — Calculation Correctness Gaps

These items affect regulatory calculation accuracy under CRR or Basel 3.1.

### P1.1 A-IRB CCF revolving restriction (CRE32.27)
- **Status:** [ ] Not implemented
- **Impact:** Basel 3.1 requires A-IRB own-estimate CCFs only for revolving facilities; non-revolving must use supervisory CCFs. `engine/ccf.py:245-265` applies modelled CCFs to all A-IRB exposures regardless of `is_revolving`. The `is_revolving` column exists in schema (`data/schemas.py:68`), is propagated through hierarchy (`engine/hierarchy.py:834-836,1098-1123`), and is used in the classifier (`engine/classifier.py:412,420`) — but ccf.py never gates on it.
- **Spec ref:** `docs/specifications/crr/credit-conversion-factors.md`
- **Fix:** In `ccf.py`, when `is_b31=True`, check `is_revolving` column before allowing own-estimate CCF. Non-revolving A-IRB should fall back to F-IRB supervisory CCFs.
- **Tests needed:** Unit tests in `tests/unit/test_ccf.py` for revolving vs non-revolving A-IRB under Basel 3.1. Acceptance test scenario in B31-C (AIRB).

### P1.2 Sovereign & institution PD floors (Basel 3.1)
- **Status:** [ ] Missing fields in PDFloors
- **Impact:** `PDFloors` in `contracts/config.py:39-98` has fields for corporate, corporate_sme, retail_mortgage, retail_other, retail_qrre_transactor, retail_qrre_revolver only. No sovereign or institution fields. `get_floor()` falls through to `self.corporate` (0.05%) for `CENTRAL_GOVT_CENTRAL_BANK`, `INSTITUTION`, `PSE`, `MDB`, `RGLA`, `DEFAULTED`, `SPECIALISED_LENDING`, `COVERED_BOND`, `EQUITY`, `OTHER`. PRA PS1/26 / CRE30.55 specifies sovereign PD floor = 0.03% and institution PD floor = 0.05%.
- **Spec ref:** Known spec issue (MEMORY.md). Need to confirm exact PRA values.
- **Fix:** Add `sovereign` and `institution` fields to `PDFloors`. Update `get_floor()` to handle all exposure classes explicitly. Update `basel_3_1()` factory.
- **Tests needed:** Unit tests in `tests/contracts/test_config.py`. Check IRB formula tests use correct floors.

### P1.3 IRB guarantor PD substitution for expected loss (CRR path)
- **Status:** [~] Basel 3.1 implemented; CRR not implemented
- **Impact:** Under CRR Art. 161(3), when an IRB guarantor provides unfunded credit protection, EL should use the guarantor's PD for the protected portion. The CRR code path in `engine/irb/guarantee.py:467-484` only adjusts EL for SA guarantors (line 475: `guarantor_approach == "sa"`). IRB guarantor EL is left unchanged under CRR. The Basel 3.1 parameter substitution path (lines 440-465) correctly blends IRB EL using guarantor PD.
- **Evidence:** `tests/unit/irb/test_irb_el_guarantee.py:136-160` explicitly tests and documents gap with docstring "PD substitution not yet implemented".
- **Spec ref:** CRR Art. 161(3) / CRE36.
- **Fix:** In the CRR branch of `_adjust_expected_loss()`, apply guarantor PD substitution for IRB guarantors (similar to Basel 3.1 but using CRR PD floors and LGD).
- **Tests needed:** Update `test_irb_guarantor_el_unchanged` to expect adjusted EL. Add acceptance scenario.

### P1.4 Junior charges for residential RE loan-splitting (Art. 124F(2))
- **Status:** [ ] Not modelled
- **Impact:** Under Basel 3.1, the 55% secured ratio threshold for residential RE loan-splitting should be reduced when a junior/second charge exists. `b31_risk_weights.py:49` has explicit comment: "Junior charges (Art. 124F(2)) reduce the 55% threshold but are not yet modelled." Both `b31_residential_rw_expr()` (line 228) and `b31_commercial_rw_expr()` (line 285) hardcode `0.55` with no lien position adjustment.
- **Spec ref:** `docs/specifications/crr/sa-risk-weights.md`, PRA PS1/26 Art. 124F(2), 124G(2), 124I(3).
- **Fix:** Add `prior_charge_amount` or `lien_position` field to loan/facility schema. In `b31_residential_rw_expr()`, reduce the 55% threshold by the prior charge amount. Similarly for income-producing RE Art. 124G(2) and commercial RE Art. 124I(3).
- **Tests needed:** Unit tests for junior charge scenarios. Acceptance tests in B31-A.

### P1.5 Financial Collateral Simple Method (Art. 222)
- **Status:** [ ] Not implemented
- **Impact:** CRR Art. 222 / CRM method taxonomy Part A allows a Simple Method for financial collateral (20% RW floor, SA-only). Only the Comprehensive (haircut) Method is implemented. COREP generator at line 1046 confirms: "simple method not implemented -> always 0".
- **Spec ref:** `docs/specifications/crr/credit-risk-mitigation.md`
- **Fix:** Add a configuration option to select Simple vs Comprehensive Method. Implement Simple Method logic in `engine/crm/collateral.py`. Update COREP row 0070 to report non-zero when Simple Method is used.
- **Tests needed:** Unit and acceptance tests for Simple Method scenarios.

### P1.6 LGDFloors residential vs commercial RE distinction
- **Status:** [~] Field exists but routing incomplete
- **Impact:** `LGDFloors` in `contracts/config.py` has both `commercial_real_estate` and `residential_real_estate` fields (both 10% under Basel 3.1), but `get_floor()` maps `CollateralType.IMMOVABLE` solely to `self.commercial_real_estate` (line 125). There is no `CollateralType` member for residential RE — `PropertyType` has RESIDENTIAL/COMMERCIAL but `CollateralType` only has IMMOVABLE. Currently both floors are 10% so no incorrect result, but the code cannot distinguish if floors ever diverge.
- **Fix:** Either split `CollateralType.IMMOVABLE` into `IMMOVABLE_RESIDENTIAL` / `IMMOVABLE_COMMERCIAL`, or add a secondary lookup parameter (e.g., `PropertyType`) to `get_floor()`.
- **Tests needed:** Unit tests confirming correct LGD floor for residential vs commercial collateral.

### P1.7 Output Floor OF-ADJ capital-tier decomposition
- **Status:** [ ] Not implemented
- **Impact:** PRA PS1/26 Art. 92(5) defines the output floor as `TREA = max(U-TREA, x * S-TREA + OF-ADJ)` where OF-ADJ has four components: IRB_T2 (EL shortfall/excess difference), IRB_CET1 (equity/securitisation deductions), GCRA (general credit risk adjustment), SA_T2 (SA T2 deductions). The current implementation in `engine/aggregator/_floor.py` applies a simplified exposure-level max(`IRB_RWA`, `SA_RWA * floor_pct`) without OF-ADJ. No code references OF-ADJ, IRB_T2, IRB_CET1, GCRA, or SA_T2 in the engine.
- **Spec ref:** `docs/specifications/output-reporting.md` (Output Floor section), PRA PS1/26 Art. 92(5).
- **Fix:** Implement portfolio-level OF-ADJ calculation in `engine/aggregator/_floor.py`. Requires capital-tier data (EL shortfall, equity deductions, GCRA) from the aggregation pipeline. Add OF-ADJ components to `AggregatedResultBundle` or a new `OutputFloorBundle`.
- **Tests needed:** Unit tests for OF-ADJ components. Acceptance test validating portfolio-level floor with adjustment.

### P1.8 Unfunded credit protection transitional (PRA Rule 4.11)
- **Status:** [ ] Not implemented
- **Impact:** PRA PS1/26 Rule 4.11 provides transitional treatment for unfunded credit protection entered into before 1 Jan 2027: such protection continues to receive CRR treatment until 30 June 2028. No code in `engine/crm/` or `engine/irb/guarantee.py` references Rule 4.11, transitional dates, or inception-date-based CRM treatment selection.
- **Spec ref:** `docs/specifications/crr/credit-risk-mitigation.md` (Method Selection, Unfunded Credit Protection Transitional)
- **Fix:** Add `protection_inception_date` field to guarantee schema. In CRM and guarantee processing, when `is_b31=True` and `reporting_date < 2028-07-01` and `protection_inception_date < 2027-01-01`, apply CRR unfunded credit protection treatment instead of Basel 3.1.
- **Tests needed:** Unit tests for transitional date logic. Acceptance test with mixed pre/post-2027 guarantees.

### P1.9 CRM maturity mismatch hardcoded exposure maturity (Art. 238)
- **Status:** [~] Simplified — conservative but incorrect
- **Impact:** `engine/crm/haircuts.py:300-316` in `apply_maturity_mismatch()` hardcodes the exposure residual maturity T=5 years instead of using the actual `exposure_maturity` column (which IS available in the data — populated by `engine/crm/processor.py:145,202`). The CRR Art. 238 formula is `CVAM = CVA × (t - 0.25) / (T - 0.25)` where T is the residual maturity of the exposure (capped at 5). Hardcoding T=5 gives the smallest adjustment factor (most conservative), so results are never non-conservative, but they may overstate CRM benefit for shorter-maturity exposures.
- **Spec ref:** CRR Art. 238 / `docs/specifications/crr/credit-risk-mitigation.md`
- **Fix:** Replace `5.0` with `pl.col("exposure_maturity").clip(upper_bound=5.0)` in the maturity mismatch calculation. Guard against null exposure maturity (fall back to 5.0).
- **Tests needed:** Unit tests in `tests/unit/crm/` for maturity mismatch with varying exposure maturities.

---

## Priority 2 — COREP Reporting Completeness

### P2.1 COREP template rework — structure alignment
- **Status:** [~] Needs rework
- **Impact:** Current COREP generator (`reporting/corep/generator.py`) uses simplified column sets and one-row-per-class structure. Column references and row structures don't match actual EBA/PRA templates. Only C 07.00, C 08.01, C 08.02 (and their OF variants) are implemented. Full-width CRR/B31 column definitions exist in `templates.py` (lines 1–651) but the generator still uses backward-compatibility aliases (`C07_COLUMNS`, `C08_01_COLUMNS`, `C08_02_COLUMNS` at lines 660–689) with old 9/11-column definitions marked "used by generator until Task 1B rewrites it".
- **Spec ref:** `docs/specifications/output-reporting.md`, `docs/features/corep-reporting.md`
- **Fix:** Migrate generator to use `CRR_C07_COLUMNS`/`B31_C07_COLUMNS` etc. Remove backward-compatibility aliases. Rework row/column logic to match EBA/PRA templates.
- **Tests needed:** Rewrite COREP tests (currently 250 tests in `tests/unit/test_corep.py`) to validate correct template structure.

### P2.2 COREP templates C 02.00, C 08.03–08.07, OF 02.01
- **Status:** [ ] Not implemented
- **Templates (per `docs/specifications/output-reporting.md` and `docs/features/corep-reporting.md`):**
  - C 02.00 / OF 02.00 — Own Funds Requirements
  - OF 02.01 — Output Floor (Basel 3.1 only, new template with no CRR equivalent)
  - C 08.03 / OF 08.03 — CR IRB PD ranges (11 columns, 17 PD range rows)
  - C 08.04 / OF 08.04 — CR IRB RWEA flow statements (1 column, 9 rows)
  - C 08.06 / OF 08.06 — CR IRB specialised lending slotting (10/11 columns)
  - C 08.07 / OF 08.07 — CR IRB scope of use (5/18 columns, significantly expanded for B31)
- **Spec ref:** `docs/specifications/output-reporting.md`, `docs/features/corep-reporting.md`
- **Fix:** Add template definitions and generator methods for each. Expand `COREPTemplateBundle` dataclass.

### P2.3 COREP C 09.01–09.02 (Geographical Breakdown)
- **Status:** [ ] May require geographical data not in current schema
- **Impact:** C 09.01 (SA) and C 09.02 (IRB) require country-level breakdown of exposures. Input schema may need a `country_of_exposure` field. C 09.01 has 13/10 columns (CRR/B31), C 09.02 has 17/15 columns.
- **Spec ref:** `docs/features/corep-reporting.md`
- **Fix:** Add `country_of_exposure` to exposure schema if missing. Add template definitions and generator methods.

### P2.4 COREP C 08.01 Section 3 "Calculation Approaches"
- **Status:** [ ] Entirely null output
- **Impact:** Section 3 of C 08.01 reports IRB calculation approach usage — currently outputs all nulls (`generator.py:524`). Confirmed by test at `test_corep.py:1552`.
- **Fix:** Populate from approach assignment data in the pipeline.

### P2.5 COREP "Other real estate" rows (0350–0354)
- **Status:** [ ] Missing RE sub-classification
- **Impact:** Rows 0350–0354 require an "other real estate" regulatory category not currently in the classification pipeline. Confirmed at `generator.py:663-665`.
- **Fix:** Add RE sub-classification (residential / commercial / other) to classifier output. Populate COREP rows.

### P2.6 COREP CCR rows (0090–0130 in C 07.00, CCR section in C 08.01)
- **Status:** [ ] Not implemented (CCR engine out of scope)
- **Impact:** Counterparty Credit Risk is out of scope per `docs/specifications/overview.md`. These rows will remain null unless CCR is added. Confirmed at `generator.py:363` and `generator.py:521`. ~15 COREP tests assert None for CCR-related columns (0200, 0210, 0211).
- **Decision needed:** Accept null CCR rows as out-of-scope, or add placeholder documentation.

### P2.7 COREP memorandum rows (0300, 0320)
- **Status:** [ ] Not implemented
- **Impact:** Confirmed at `generator.py:411`: "Other memorandum rows (0300, 0320) -- not yet implemented".
- **Fix:** Implement memorandum item aggregation in generator.

---

## Priority 3 — Pillar III Disclosures

### P3.1 Pillar III disclosure code
- **Status:** [ ] Not started — no code exists in `src/`, no `reporting/pillar3/` directory, no tests
- **Impact:** 9 disclosure templates specified: OV1, CR4, CR5, CR6, CR6-A, CR7, CR7-A, CR8, CR10. Full column/row definitions documented in `docs/features/pillar3-disclosures.md` with both CRR and Basel 3.1 variants.
- **Spec ref:** `docs/specifications/output-reporting.md` (Pillar III section), `docs/features/pillar3-disclosures.md`, `docs/framework-comparison/disclosure-differences.md`
- **Fix:** Create `src/rwa_calc/reporting/pillar3/` package with generator, templates, and protocol. Add to `ResultExporterProtocol`.
- **Tests needed:** Unit tests for each template. Acceptance tests for end-to-end disclosure generation.

---

## Priority 4 — Documentation & Consistency Fixes

### P4.1 Output floor transitional schedule inconsistency
- **Status:** [~] Code is correct; docs disagree
- **Impact:** Code uses PRA compressed 4-year schedule (60%/65%/70%/72.5% for 2027–2030) which is correct per PRA PS1/26. But `docs/plans/implementation-plan.md` and `docs/framework-comparison/technical-reference.md` show BCBS 6-year schedule (50%–72.5% for 2027–2032). Additionally, `TransitionalScheduleBundle` docstring in `bundles.py` references "50% (2027) to 72.5% (2032+)" — inconsistent with the PRA schedule.
- **Fix:** Update stale docs, technical-reference.md, and bundle docstring to match PRA schedule.

### P4.2 Stale version numbers across docs
- **Status:** [~] Multiple files outdated
- **Impact:** `docs/specifications/overview.md` says 0.1.37, `docs/plans/prd.md` says 0.1.28, `milestones.md` says 0.1.28, `nfr.md` test count says 1,844; actual is 0.1.64 with ~1,925 tests.
- **Fix:** Update version references or remove hardcoded versions from docs.

### P4.3 Stale implementation plan (`docs/plans/implementation-plan.md`)
- **Status:** [~] Shows items as incomplete that are Done
- **Fix:** Update or deprecate in favour of this file.

### P4.4 Stale PRD (`docs/plans/prd.md`)
- **Status:** [~] Many FR statuses outdated
- **Fix:** Update FR status values to reflect current implementation.

### P4.5 PD floor documentation discrepancy
- **Status:** [~] Docs disagree
- **Impact:** `key-differences.md` shows retail mortgage PD floor as 0.10%, `technical-reference.md` shows 0.05%. Code uses 0.05% (`config.py:94`). Need to confirm PRA PS1/26 value.
- **Fix:** Verify against PRA PS1/26 CRE30.55 and update incorrect doc.

### P4.6 Spec file for equity approach
- **Status:** [ ] No dedicated spec — confirmed no file at `docs/specifications/crr/equity-approach.md`
- **Impact:** Equity rules spread across slotting spec and sa-risk-weights spec. Known issue per MEMORY.md.
- **Fix:** Author `docs/specifications/crr/equity-approach.md` consolidating CRR Art. 133, Art. 155, Basel 3.1 Art. 133 + transitional, and CIU treatment.

### P4.7 COREP template spec
- **Status:** [~] Thin in output-reporting.md — detailed in corep-reporting.md feature doc
- **Impact:** `docs/specifications/output-reporting.md` COREP section is high-level. Detailed column/row definitions exist in `docs/features/corep-reporting.md` (73.9KB). Need to reconcile or cross-reference.
- **Fix:** Expand `docs/specifications/output-reporting.md` COREP section with field-level mapping, or add clear cross-reference to `docs/features/corep-reporting.md`.

### P4.8 Type checker inconsistency in docs
- **Status:** [~] Docs disagree with CLAUDE.md
- **Impact:** `docs/specifications/overview.md` lists Mypy as type checker, but CLAUDE.md specifies "ty". `docs/specifications/overview.md` lists fastexcel for reading, but output-reporting export section references xlsxwriter for writing.
- **Fix:** Reconcile tool references across docs.

### P4.9 model_permissions not documented in architecture spec
- **Status:** [~] Missing from data model
- **Impact:** `docs/specifications/architecture.md` lists 12 input tables but does not include `model_permissions` (implemented at 0.1.64). `docs/specifications/configuration.md` also does not mention model_permissions.
- **Fix:** Add `model_permissions` table to architecture data model and configuration spec.

### P4.10 Stale key-differences.md implementation status claims
- **Status:** [~] Says features not implemented that are complete
- **Impact:** `docs/framework-comparison/key-differences.md` claims "Not Yet Implemented" for: (a) currency mismatch 1.5x multiplier — actually implemented at `engine/sa/calculator.py:900-966`, (b) SA Specialised Lending Art. 122A-122B — implemented at `engine/sa/calculator.py:528-533` + `b31_risk_weights.py:147-157,336`, (c) provision-coverage-based defaulted treatment CRE20.87-90 — implemented at `engine/sa/calculator.py:451-461` + `b31_risk_weights.py:171-173`.
- **Fix:** Update key-differences.md to mark these three features as implemented.

---

## Priority 5 — Test Coverage Gaps

### P5.1 Stress / performance acceptance tests
- **Status:** [ ] Empty directory (`tests/acceptance/stress/`)
- **Fix:** Add acceptance-level stress tests (100K, 1M row portfolios) validating NFR performance targets (<2s/100K, <20s/1M).

### P5.2 Fixture referential integrity
- **Status:** [~] Pre-existing errors
- **Impact:** Collateral, guarantee, and provision test fixtures reference missing loans. Confirmed in `tests/fixtures/generate_all.py` integrity check (lines 383-428). Documented in MEMORY.md.
- **Fix:** Fix or regenerate affected fixtures via `tests/fixtures/generate_all.py`.

### P5.3 CRR CRM guarantee/provision test placeholders
- **Status:** [~] Documented as placeholders
- **Impact:** `tests/unit/crr/test_crr_crm.py:6-7` documents "Guarantee processing (placeholder)" and "Provision deduction (placeholder)" — these test categories may need expansion.
- **Fix:** Audit test coverage and add missing CRM guarantee and provision deduction tests.

### P5.4 Conditional pytest.skip() in acceptance tests
- **Status:** [~] ~90 conditional skips across acceptance tests
- **Impact:** Acceptance tests use runtime `pytest.skip()` when fixture data is unavailable. While this is valid (data-driven tests skip gracefully), it may mask untested scenarios if fixtures are never generated for certain test groups.
- **Fix:** Audit which acceptance test scenarios are always skipped and ensure fixture data exists for all specified scenarios.

---

## Priority 6 — Code Quality & Type Safety

### P6.1 Unparameterized `list` types in bundles and protocols
- **Status:** [~] Weakens type safety
- **Impact:** `hierarchy_errors`, `classification_errors`, `crm_errors`, and all `errors` fields across bundles in `contracts/bundles.py` are typed as `list` instead of `list[CalculationError]`. Similarly, `DataQualityCheckerProtocol.check()` returns untyped `list`.
- **Fix:** Add `CalculationError` type parameter to all error list fields and protocol return types.

### P6.2 Missing exports from `contracts/__init__.py` and `domain/__init__.py`
- **Status:** [~] Several classes not re-exported
- **Impact:** Not exported from `contracts/__init__.py`: `EquityResultBundle`, `EquityCalculatorProtocol`, `OutputAggregatorProtocol`, `ResultExporterProtocol`, `EquityTransitionalConfig`, `PostModelAdjustmentConfig`, `IRBPermissions`. Not exported from `domain/__init__.py`: `SCRAGrade`, `EquityType`, `EquityApproach`. Tests import directly from submodules (works but bypasses public API).
- **Fix:** Add missing re-exports to `__init__.py` files.

### P6.3 `CalculationConfig.collect_engine` docstring error
- **Status:** [~] Contradictory description
- **Impact:** Docstring at `config.py:497-498` mentions 'cpu' twice with different descriptions: first as default, then describes batch processing (formerly 'streaming') labelled as 'cpu'.
- **Fix:** Correct the docstring to accurately describe 'cpu', 'gpu', and 'streaming' engines.

### P6.4 `EquityResultBundle.approach` uses `str` instead of `EquityApproach` enum
- **Status:** [~] Weakens type safety
- **Impact:** `contracts/bundles.py:276` defines `approach: str = "sa"` but `domain/enums.py` has `EquityApproach` enum with `SA` and `IRB_SIMPLE` members. Using a bare string bypasses enum validation.
- **Fix:** Change field type to `EquityApproach` with default `EquityApproach.SA`.

### P6.5 `ELPortfolioSummary` uses `float` instead of `Decimal`
- **Status:** [~] Convention violation
- **Impact:** `contracts/bundles.py:281-319` — all 9 monetary/regulatory fields (`total_expected_loss`, `total_provisions_allocated`, `total_shortfall`, `total_excess`, `t2_credit_cap`, `t2_credit`, `cet1_deduction`, `t2_deduction`, `irb_rwa`) use `float`. CLAUDE.md convention: "Prefer `Decimal` for regulatory parameters to avoid float precision issues." These are regulatory capital figures.
- **Fix:** Change all fields to `Decimal`. Update aggregator EL calculation to produce `Decimal` values.

### P6.6 `CalculationError.to_dict()` returns bare `dict`
- **Status:** [~] Minor type safety gap
- **Impact:** `contracts/errors.py:69` returns `dict` without type parameters. Should be `dict[str, str | None]`.
- **Fix:** Add type parameters to return annotation.

### P6.7 Dead `TYPE_CHECKING` block in config.py
- **Status:** [~] Dead code
- **Impact:** `contracts/config.py:31-32` has `if TYPE_CHECKING: pass` — empty block.
- **Fix:** Remove the dead import guard.

---

## Priority 7 — Future / v2.0 (Not Yet Planned)

### P7.1 Stress testing integration
- **Status:** [ ] Not started (Milestone v2.0 M4.3)

### P7.2 Portfolio-level concentration metrics
- **Status:** [ ] Not started (Milestone v2.0 M4.4)

### P7.3 REST API
- **Status:** [ ] Not started (Milestone v2.0 M4.5)

### P7.4 Additional exposure classes
- **Status:** [ ] Future enhancement
- **Scope:** Securitisation, CIU (beyond 250% fallback), covered bonds (beyond current implementation), high-risk items.

---

## Completed Items (Reference)

These items are verified complete as of 0.1.64:

- [x] All 8 pipeline stages (loader, hierarchy, classifier, CRM, SA/IRB/slotting/equity, aggregator)
- [x] CRR SA risk weights (all exposure classes, Art. 112–134)
- [x] Basel 3.1 SA risk weights (residential/commercial RE loan-splitting, ECRA/SCRA, corporate sub-categories, ADC, equity transitional)
- [x] Basel 3.1 SA specialised lending (Art. 122A-122B) — OF/CF=100%, PF pre-op=130%, PF op=100%, PF high-quality=80%
- [x] Basel 3.1 provision-coverage-based defaulted treatment (CRE20.87-90) — 100% RW (provisions >= 50%) / 150% RW (provisions < 50%)
- [x] Currency mismatch 1.5x RW multiplier (Art. 123B / CRE20.93) — Basel 3.1 only, retail + RE classes
- [x] F-IRB calculation (supervisory LGD, PD floors, correlation, maturity adjustment, FI scalar)
- [x] A-IRB calculation (own LGD/CCF, LGD floors, post-model adjustments, mortgage RW floor 15%)
- [x] Slotting (CRR 4 tables + Basel 3.1 3 tables + subgrades)
- [x] Equity (SA Art. 133, IRB Simple Art. 155, CIU look-through/mandate/fallback, Basel 3.1 transitional)
- [x] CRM (collateral haircuts CRR 3-band + Basel 3.1 5-band, FX mismatch, maturity mismatch, multi-level allocation, guarantee substitution, netting, provisions)
- [x] Basel 3.1 parameter substitution (CRE22.70-85) — including EL adjustment for guaranteed portion
- [x] Double default (CRR Art. 153(3), Art. 202-203)
- [x] Output floor with PRA transitional schedule (60%/65%/70%/72.5%) — simplified exposure-level application
- [x] Supporting factors (CRR SME + infrastructure, removed under Basel 3.1)
- [x] CCF (SA/FIRB/AIRB, Basel 3.1 UCC changes)
- [x] Provisions (multi-level, SA drawn-first deduction, IRB EL comparison, T2 credit cap)
- [x] Dual-framework comparison (DualFrameworkRunner, CapitalImpactAnalyzer, TransitionalScheduleRunner)
- [x] COREP C 07.00 / C 08.01 / C 08.02 (basic structure, CRR + Basel 3.1 OF variants)
- [x] API (CreditRiskCalc, export to Parquet/CSV/Excel, results cache)
- [x] Model permissions (per-model FIRB/AIRB/slotting, fallback to SA)
- [x] Marimo UI (RWA app, comparison app, template workbench, landing page)
- [x] Schema validation, bundle validation, column value constraints
- [x] FX conversion (multi-currency support)
- [x] Materialisation barriers (CPU + streaming modes)
