# COREP Template Generator — Implementation Plan

## Context

The COREP generator was built against an incorrect understanding of the template structures. After reviewing the actual EBA/PRA reference templates (Regulation (EU) 2021/451 Annex I and PRA PS1/26 Annex I), plus the reporting instructions (Annex II for both frameworks), the generator needs substantial rework.

**Reference documents** (in `docs/assets/`):

- `corep-own-funds.xlsx` — CRR template layouts (sheets "7", "8.1", "8.2")
- `annex-ii-instructions-for-reporting-on-own-funds.pdf` — CRR column instructions (270pp)
- `annex-i-of-07-00-credit-risk-sa-reporting-template.xlsx` — Basel 3.1 OF 07.00 layout
- `annex-ii-reporting-instructions.pdf` — Basel 3.1 column instructions (322pp)

**Key structural problems**:

1. Generator treats exposure class as a row dimension (one row per class). Actual template is one submission per exposure class with 5 internal row sections.
2. Column refs (010-090) don't match actual COREP refs (0010-0240). Column meanings are wrong.
3. Risk weight breakdown is Section 3 within C 07.00, not a separate template.
4. C 08.01 maturity is in years; COREP requires days.
5. C 08.02 uses pre-defined PD bands; actual template uses dynamic firm-specific obligor grades.
6. Many populatable columns in the pipeline are not wired to the generator.
7. Several COREP columns require pipeline features that don't exist yet.

---

## Completion Status

| Task | Status | Notes |
|------|--------|-------|
| 1A: Template definitions | **DONE** | CRR + B3.1 columns, row sections, risk weight bands all defined. Backward-compatible aliases kept for generator. 130 tests pass. |
| 1B: Generator rewrite | **DONE** | Per-exposure-class output, 5-section row structure, 4-digit column refs, framework awareness, maturity in days. |
| 1C: Tests + Excel export | **DONE** | Tests rewritten for new dict-based API. 134 COREP tests pass (3 Excel skipped). Excel export updated for per-class sheets. |

---

## Task List

Tasks are ordered by dependency. Each task is self-contained: it modifies a focused set of files, has clear acceptance criteria, and leaves the test suite passing. Tasks within the same phase can be parallelised unless noted otherwise.

### Phase 1: Structural Rewrite

Phase 1 tasks are tightly coupled — they form an atomic rewrite of the template definitions, generator, bundle, tests, and export. Tasks 1A-1C must be done in order.

---

#### Task 1A: Rewrite template definitions with correct COREP structure

**Goal**: Replace incorrect column/row definitions in `templates.py` with the actual COREP structure from the reference documents.

**Files to modify**:
- `src/rwa_calc/reporting/corep/templates.py`

**What to do**:

1. Replace `C07_COLUMNS` (9 cols, refs 010-090) with `CRR_C07_COLUMNS` — the actual 24 CRR C 07.00 columns with correct 4-digit refs:
   - 0010: Original exposure pre conversion factors
   - 0030: (-) Value adjustments and provisions
   - 0040: Exposure net of value adjustments and provisions
   - 0050: (-) Guarantees
   - 0060: (-) Credit derivatives
   - 0070: (-) Financial collateral: Simple method
   - 0080: (-) Other funded credit protection
   - 0090: (-) Substitution outflows
   - 0100: Substitution inflows (+)
   - 0110: Net exposure after CRM substitution pre CCFs
   - 0120: Volatility adjustment to exposure
   - 0130: (-) Financial collateral: adjusted value (Cvam)
   - 0140: (-) Of which: volatility and maturity adjustments
   - 0150: Fully adjusted exposure value (E*)
   - 0160: Off-BS by CCF: 0%
   - 0170: Off-BS by CCF: 20%
   - 0180: Off-BS by CCF: 50%
   - 0190: Off-BS by CCF: 100%
   - 0200: Exposure value
   - 0210: Of which: arising from CCR
   - 0211: Of which: CCR excl CCP
   - 0215: RWEA pre supporting factors
   - 0216: (-) SME supporting factor adjustment
   - 0217: (-) Infrastructure supporting factor adjustment
   - 0220: RWEA after supporting factors
   - 0230: Of which: with ECAI credit assessment
   - 0240: Of which: credit assessment derived from central govt

2. Add `B31_C07_COLUMNS` for Basel 3.1 OF 07.00:
   - Adds: 0035 (on-BS netting), 0171 (40% CCF)
   - Changes: 0160 → 10% CCF (was 0%)
   - Removes: 0215-0217 (supporting factors)
   - Adds: 0235 (without ECAI)

3. Replace `C08_01_COLUMNS` (11 cols, refs 010-110) with `CRR_C08_COLUMNS` — the actual 33 CRR C 08.01 columns (0010-0310). See reference doc sheet "8.1" for full list.

4. Add `B31_C08_COLUMNS` for Basel 3.1 OF 08.01:
   - Removes: 0010 (PD — moved to OF 08.02 only), 0220 (double default), 0255-0257 (supporting factors)
   - Adds: 0035, 0101-0104 (slotting FCCM), 0125/0265 (of which: defaulted), 0251-0254 (post-model adj), 0275-0276 (output floor), 0281-0282 (EL adj)

5. Replace `SA_EXPOSURE_CLASS_ROWS` with `SA_ROW_SECTIONS` — a structure defining the 5 row sections within each C 07.00:
   - Section 1: Total (0010) + "of which" (0015, 0020, 0030, 0035, 0040, 0050, 0060)
   - Section 2: Exposure types (0070, 0080, 0090-0130)
   - Section 3: Risk weights (0140-0280)
   - Section 4: CIU approach (0281-0283)
   - Section 5: Memorandum (0290-0320)

6. Add `B31_SA_ROW_SECTIONS` for Basel 3.1 with additional rows (0021-0026 specialised lending, 0330-0360 RE detail, 0261 400% RW, 0371-0380 memorandum).

7. Replace `IRB_EXPOSURE_CLASS_ROWS` with `IRB_ROW_SECTIONS` for C 08.01 row structure.

8. Add `B31_IRB_ROW_SECTIONS` for OF 08.01 with additional rows (0017, 0031-0035, 0175, 0190, 0200).

9. Keep `SA_EXPOSURE_CLASS_ROWS` and `IRB_EXPOSURE_CLASS_ROWS` as lookup dicts (still needed by generator for filtering), but update docstrings to clarify they're filter values, not row definitions.

10. Keep `PD_BANDS` for C 08.02 aggregation convenience, add docstring noting actual template uses firm-specific grades.

11. Keep `SA_RISK_WEIGHT_BANDS` but add `B31_SA_RISK_WEIGHT_BANDS` with the 29 Basel 3.1 bands.

**Acceptance criteria**:
- `uv run pytest tests/unit/test_corep.py::TestTemplateDefinitions -v` passes (update these tests first to validate new definitions)
- `uv run ruff check src/rwa_calc/reporting/corep/templates.py`
- `uv run mypy src/rwa_calc/reporting/corep/templates.py`
- **Completed**: 126 COREP tests pass (130 collected, 4 Excel skipped). All 1691 unit tests pass.

**Implementation notes**:
- `international_org` was added to `SA_EXPOSURE_CLASS_ROWS` (was missing from the original plan).
- CRR C 07.00 has 27 columns (not 24 as originally stated — plan was missing 0211, 0215, 0216).
- CRR C 08.01 has 37 columns (not 33 as originally stated).
- B3.1 OF 07.00 has 27 columns (not 22 as originally stated).
- 3 pre-existing test failures from missing fixture parquet files (test_hierarchy, test_loader) are unrelated to COREP work.

---

#### Task 1B: Rewrite generator for per-exposure-class output with row sections

**Goal**: Restructure the generator to produce per-exposure-class DataFrames with the correct 5-section row structure for C 07.00 and 3-section structure for C 08.01.

**Files to modify**:
- `src/rwa_calc/reporting/corep/generator.py`
- `src/rwa_calc/reporting/corep/__init__.py` (if exports change)

**What to do**:

1. Restructure `_generate_c07()` to:
   - Accept an exposure class filter parameter
   - Produce a DataFrame with all 5 row sections for that class
   - Row 0010 (Total): aggregate all exposures for that class
   - "Of which" rows (0015-0060): conditional filters on the class data (defaulted, SME, etc.)
   - Section 2 (0070/0080): group by `bs_type` or `exposure_type`
   - Section 3 (0140-0280): group by `risk_weight` into bands
   - Section 5 (0290-0320): filter memorandum conditions
   - Use 4-digit column refs from Task 1A definitions

2. Remove `_generate_c07_rw_breakdown()` entirely — it's now Section 3 of C 07.00.

3. Restructure `_generate_c08_01()` similarly:
   - Per-exposure-class with row sections
   - Fix maturity: multiply `irb_maturity_m` by 365 for col 0250 (days, not years)
   - Use correct column refs

4. Update `_generate_c08_02()`:
   - Keep PD banding but use correct column refs
   - Each band row gets an obligor grade identifier (col 0005)

5. Update `generate_from_lazyframe()` to:
   - Get distinct exposure classes
   - Generate per-class templates
   - Return updated bundle structure

6. Update `COREPTemplateBundle`:
   - Replace `c07_00: pl.DataFrame` with `c07_00: dict[str, pl.DataFrame]` (keyed by exposure class), or a single DataFrame with `sa_exposure_class` partition column
   - Remove `c07_rw_breakdown` field
   - Similarly for `c08_01`, `c08_02`

7. Add framework-awareness: when `framework == "CRR"` use CRR columns/rows, when `"BASEL_3_1"` use B31 versions.

8. Update `_empty_c07()` and `_empty_c08_01()` schemas to match new column refs.

9. Populate columns from existing pipeline data where possible:
   - 0010: `drawn_amount + undrawn_amount`
   - 0030: `scra_provision_amount + gcra_provision_amount`
   - 0040: 0010 - 0030
   - 0050: `guaranteed_portion`
   - 0200: `ead_final`
   - 0220: `rwa_final`
   - 0230: `rwa_final` where `sa_cqs.is_not_null()`
   - Columns without pipeline source: set to `null` with a comment (e.g., "# 0060: Credit derivatives — not yet tracked in pipeline")

**Acceptance criteria**:
- `uv run ruff check src/rwa_calc/reporting/corep/`
- `uv run mypy src/rwa_calc/reporting/corep/`
- Generator produces per-exposure-class output with correct row sections
- Column refs match actual COREP numbering

**Implementation notes (completed)**:
- `COREPTemplateBundle` changed from flat DataFrames to `dict[str, pl.DataFrame]` keyed by exposure class.
- `c07_rw_breakdown` field removed — risk weight breakdown is now Section 3 of each per-class C 07.00 DataFrame.
- Generator collects SA/IRB data once, then filters per-class for efficiency.
- Column computation uses `_compute_c07_values()` and `_compute_c08_values()` helpers that map each 4-digit COREP ref to its pipeline source.
- Columns without pipeline sources set to `None` with comments indicating which Phase 2/3 task will populate them.
- Risk weight section uses `_compute_rw_section_rows()` which assigns bands via chained `when/then` expression.
- Maturity (col 0250) multiplied by 365 to convert from pipeline years to COREP days.
- ECAI check (col 0230) uses `sa_cqs.is_not_null()` (not `> 0` as before).
- Framework parameter now actually used: CRR vs BASEL_3_1 selects different column/row section definitions.
- 1699 unit tests pass (3 pre-existing fixture failures unrelated to COREP).

---

#### Task 1C: Rewrite tests and update Excel export

**Goal**: Update all COREP tests for the new structure and fix the Excel export.

**Files to modify**:
- `tests/unit/test_corep.py`
- `src/rwa_calc/reporting/corep/generator.py` (export_to_excel method only)
- `src/rwa_calc/api/models.py` (if `to_corep()` references bundle fields)
- `src/rwa_calc/api/export.py` (if `export_to_corep()` references bundle fields)

**What to do**:

1. Rewrite `tests/unit/test_corep.py`:
   - `TestTemplateDefinitions`: verify new CRR/B31 column and row section definitions
   - `TestC0700`: test per-exposure-class output shape, verify 5 row sections present, verify correct 4-digit column refs, test aggregation within each section
   - `TestC0700RWBreakdown`: remove this class (merged into C 07.00 Section 3)
   - `TestC0801`: test per-exposure-class, verify row sections, verify maturity in days (not years), correct column refs
   - `TestC0802`: test obligor grade rows with PD banding, correct column refs
   - `TestExcelExport`: test updated sheet structure
   - `TestCombined`: test SA/IRB separation with per-class output
   - Test both CRR and Basel 3.1 framework paths

2. Update `export_to_excel()`:
   - Iterate over per-class DataFrames
   - Sheet naming: "C 07.00 - Corporate", "C 07.00 - Institution", etc. (or single sheet with class filter)
   - Remove the "C 07.00 RW Breakdown" sheet
   - Add multi-level column headers if feasible with xlsxwriter

3. Update API integration points (`api/models.py`, `api/export.py`) if they reference `c07_rw_breakdown`.

**Acceptance criteria**:
- `uv run pytest tests/unit/test_corep.py -v` — all tests pass
- `uv run pytest tests/ -v --benchmark-skip` — no regressions in full suite
- `uv run ruff check`

**Implementation notes (completed)**:
- Tasks 1B and 1C were implemented together since they're tightly coupled.
- Tests rewritten for new dict-based bundle API: `bundle.c07_00["corporate"]` instead of filtering.
- Column assertions use 4-digit refs: `corp["0200"][0]` instead of `corp["exposure_value_070"][0]`.
- `TestC0700RWBreakdown` replaced by `TestC0700RiskWeightSection` testing Section 3 rows.
- New tests: `test_framework_affects_column_set`, `test_corporate_sme_separate_from_corporate`.
- Excel export writes per-class sheets: "C 07.00 - Corporates", "C 08.01 - Corporates - Other", etc.
- 134 COREP tests pass (3 Excel skipped due to missing xlsxwriter in sandbox).

---

### Phase 2: Wire Up Existing Pipeline Data

Each Phase 2 task is independent and can run in any order or in parallel. Each adds new columns/rows to the generator using data already available in the pipeline.

**Prerequisite**: Phase 1 complete.

---

#### Task 2A: Add supporting factor columns (CRR only)

**Goal**: Populate COREP cols 0215-0217 (C 07.00) and 0255-0257 (C 08.01) for CRR framework.

**Files**: `src/rwa_calc/reporting/corep/generator.py`, `tests/unit/test_corep.py`

**Pipeline source**: `sme_supporting_factor`, `infra_supporting_factor`, `rwa_pre_factor`, `supporting_factor_benefit`

**Map**:
- 0215/0255: `rwa_pre_factor.sum()` (RWEA pre factors)
- 0216/0256: SME factor benefit = `(rwa_pre_factor - rwa_final)` where SME factor applied
- 0217/0257: Infrastructure factor benefit (similar)
- Skip these columns when `framework == "BASEL_3_1"`

**Verify**: `uv run pytest tests/unit/test_corep.py -v -k "supporting_factor"`

---

#### Task 2B: Add exposure type row breakdown (Section 2)

**Goal**: Populate C 07.00/C 08.01 Section 2 rows (on-BS, off-BS) from `exposure_type`/`bs_type`.

**Files**: `src/rwa_calc/reporting/corep/generator.py`, `tests/unit/test_corep.py`

**Pipeline source**: `exposure_type` ("loan" | "facility" | "contingent"), `bs_type` ("ONB" | "OFB")

**Map**:
- Row 0070: filter `bs_type == "ONB"` or `exposure_type == "loan"`, aggregate all columns
- Row 0080: filter `bs_type == "OFB"` or `exposure_type in ("contingent", "facility")`, aggregate
- Rows 0090-0130 (CCR): leave as zero/null (CCR not implemented)

**Verify**: `uv run pytest tests/unit/test_corep.py -v -k "exposure_type"`

---

#### Task 2C: Add CCF breakdown columns

**Goal**: Populate off-BS CCF breakdown (cols 0160-0190 for CRR; cols 0160, 0170, 0171, 0180, 0190 for Basel 3.1).

**Files**: `src/rwa_calc/reporting/corep/generator.py`, `tests/unit/test_corep.py`

**Pipeline source**: `ccf_applied` (0.0, 0.1, 0.2, 0.4, 0.5, 1.0), off-BS exposures only

**Map**: Group off-BS exposures by `ccf_applied`, sum the fully adjusted exposure value (E*) into the appropriate CCF column. CRR has 0%/20%/50%/100%; Basel 3.1 has 10%/20%/40%/50%/100%.

**Verify**: `uv run pytest tests/unit/test_corep.py -v -k "ccf_breakdown"`

---

#### Task 2D: Add output floor columns (Basel 3.1 only)

**Goal**: Populate OF 08.01 cols 0275/0276 with SA-equivalent values for output floor.

**Files**: `src/rwa_calc/reporting/corep/generator.py`, `tests/unit/test_corep.py`

**Pipeline source**: `sa_equivalent_rwa` (or `sa_rwa`), `ead_final`

**Map**:
- 0275: `ead_final.sum()` (SA-equivalent exposure value)
- 0276: `sa_equivalent_rwa.sum()` (SA-equivalent RWEA)
- Only populate when `framework == "BASEL_3_1"`

**Verify**: `uv run pytest tests/unit/test_corep.py -v -k "output_floor"`

---

#### Task 2E: Add ECAI unrated split (Basel 3.1 col 0235)

**Goal**: Add col 0235 (RWEA without ECAI) for Basel 3.1 alongside existing col 0230 (with ECAI).

**Files**: `src/rwa_calc/reporting/corep/generator.py`, `tests/unit/test_corep.py`

**Pipeline source**: `sa_cqs` (null = unrated)

**Map**: 0235 = `rwa_final.sum()` where `sa_cqs.is_null()`. Only for Basel 3.1.

**Verify**: `uv run pytest tests/unit/test_corep.py -v -k "ecai"`

---

#### Task 2F: Add large financial sector entity sub-columns

**Goal**: Populate C 08.01 "of which: LFSE" columns (0030, 0140, 0240, 0270).

**Files**: `src/rwa_calc/reporting/corep/generator.py`, `tests/unit/test_corep.py`

**Pipeline source**: `apply_fi_scalar` (boolean — True for LFSE counterparties)

**Map**:
- 0030: original exposure where `apply_fi_scalar == True`
- 0140: exposure value where LFSE
- 0240: EAD-weighted avg LGD where LFSE
- 0270: RWEA where LFSE

**Verify**: `uv run pytest tests/unit/test_corep.py -v -k "lfse"`

---

#### Task 2G: Add "of which" detail rows (defaulted, SME)

**Goal**: Populate C 07.00 "of which" rows 0015 (defaulted) and 0020 (SME); OF 08.01 cols 0125/0265 (of which: defaulted).

**Files**: `src/rwa_calc/reporting/corep/generator.py`, `tests/unit/test_corep.py`

**Pipeline source**: `exposure_class == "defaulted"` (SA); `irb_pd_floored >= 1.0` (IRB defaulted); `sme_supporting_factor_eligible` or `exposure_class` containing "sme"

**Map**:
- C 07.00 row 0015: filter defaulted exposures, aggregate
- C 07.00 row 0020: filter SME exposures, aggregate
- OF 08.01 col 0125: `ead_final.sum()` where defaulted
- OF 08.01 col 0265: `rwa_final.sum()` where defaulted

**Verify**: `uv run pytest tests/unit/test_corep.py -v -k "of_which"`

---

#### Task 2H: Wire up pre/post CRM substitution flows

**Goal**: Populate C 07.00 cols 0050 (guarantees), 0090 (outflows), 0100 (inflows), 0110 (net after substitution).

**Files**: `src/rwa_calc/reporting/corep/generator.py`, `tests/unit/test_corep.py`

**Pipeline source**: `guaranteed_portion`, `pre_crm_exposure_class`, `post_crm_exposure_class_guaranteed`

**Map**:
- 0050: `guaranteed_portion.sum()` for exposures in this class
- 0090: sum of `guaranteed_portion` where `pre_crm_exposure_class == this_class` AND `post_crm_exposure_class_guaranteed != this_class` (leaving this class)
- 0100: sum of `guaranteed_portion` where `post_crm_exposure_class_guaranteed == this_class` AND `pre_crm_exposure_class != this_class` (arriving in this class)
- 0110: col 0040 - col 0090 + col 0100

**Verify**: `uv run pytest tests/unit/test_corep.py -v -k "substitution"`

---

### Phase 3: Pipeline Enhancements

Each Phase 3 task extends the pipeline itself to produce data not currently available. These are larger tasks that add new functionality upstream of the COREP generator.

**Prerequisite**: Phase 1 complete. Phase 2 is recommended but not strictly required.

---

#### Task 3A: Collateral method split (simple vs comprehensive vs other funded)

**Goal**: Track financial collateral simple method, comprehensive method, and other funded protection separately through the CRM pipeline.

**COREP cols**: C 07.00: 0070, 0080, 0120-0140. C 08.01: 0170-0210.

**Current state**: Pipeline applies supervisory haircuts uniformly. No simple vs comprehensive distinction. `collateral_adjusted_value` is a single total.

**Files**:
- `src/rwa_calc/contracts/config.py` — add `financial_collateral_method: Literal["simple", "comprehensive"]`
- `src/rwa_calc/engine/crm/processor.py` — split collateral processing path
- `src/rwa_calc/engine/crm/haircuts.py` — preserve FCCM intermediate values
- `src/rwa_calc/data/schemas.py` — add output columns
- `src/rwa_calc/reporting/corep/generator.py` — wire new columns to COREP
- `tests/unit/test_corep.py`, `tests/unit/test_crm_*.py` — new tests

**New output columns**:
- `financial_collateral_simple_value` → COREP col 0070
- `other_funded_protection_value` → COREP col 0080
- `volatility_adjustment_he` → COREP col 0120
- `collateral_cvam` → COREP col 0130
- `cvam_vol_mat_portion` → COREP col 0140

**Collateral type mapping for C 08.01 cols 0170-0210**:
- 0170: other funded (non-financial, non-RE, non-receivable)
- 0171: cash on deposit
- 0172: life insurance policies
- 0173: instruments held by third party
- 0180: eligible financial collateral
- 0190: real estate
- 0200: other physical collateral
- 0210: receivables

**Verify**: `uv run pytest tests/unit/test_crm_collateral.py tests/unit/test_corep.py -v`

---

#### Task 3B: Credit derivatives tracking

**Goal**: Track credit derivatives (CDS, CLN, TRS) separately from guarantees in the CRM pipeline.

**COREP cols**: C 07.00: 0060. C 08.01: 0050, 0160, 0310.

**Current state**: CRM handles guarantees only. No code path for credit derivatives.

**Depends on**: None (independent of 3A)

**Files**:
- `src/rwa_calc/data/schemas.py` — add `protection_type: Literal["guarantee", "credit_derivative"]` to guarantee schema
- `src/rwa_calc/engine/crm/processor.py` — split guarantee/derivative processing
- `src/rwa_calc/engine/crm/namespace.py` — handle derivative-specific conditions (Art. 204, 216)
- `src/rwa_calc/reporting/corep/generator.py` — wire to COREP cols
- Tests

**New output columns**:
- `guarantee_value` → COREP col 0050
- `credit_derivative_value` → COREP col 0060
- `guarantee_lgd_adj_value` → C 08.01 col 0150
- `credit_derivative_lgd_adj_value` → C 08.01 col 0160
- `rwa_pre_credit_derivatives` → C 08.01 col 0310

**Verify**: `uv run pytest tests/unit/test_crm_guarantees.py tests/unit/test_corep.py -v`

---

#### Task 3C: CRM substitution flow computation

**Goal**: Compute cross-class CRM substitution outflows and inflows as proper aggregated flows.

**COREP cols**: C 07.00: 0090, 0100. C 08.01: 0070, 0080.

**Depends on**: Task 2H (basic substitution wiring)

**Files**:
- `src/rwa_calc/reporting/corep/generator.py` or new `src/rwa_calc/reporting/corep/flows.py`
- Tests

**Implementation**:
- For each exposure where `pre_crm_exposure_class != post_crm_exposure_class_guaranteed`:
  - Record outflow from `pre_crm_exposure_class` of `guaranteed_portion`
  - Record inflow to `post_crm_exposure_class_guaranteed` of `guaranteed_portion`
- Aggregate per class → cols 0090/0100
- Net: col 0110 = col 0040 - col 0090 + col 0100

**Verify**: `uv run pytest tests/unit/test_corep.py -v -k "substitution_flow"`

---

#### Task 3D: On-balance-sheet netting (Basel 3.1 col 0035)

**Goal**: Track on-balance-sheet netting as a separate adjustment in the EAD waterfall.

**COREP cols**: OF 07.00: 0035. OF 08.01: 0035.

**Files**:
- `src/rwa_calc/data/schemas.py` — add `on_bs_netting_amount: pl.Float64` to exposure schema and output schema
- `src/rwa_calc/engine/crm/processor.py` — insert netting step after provisions, before CRM
- `src/rwa_calc/reporting/corep/generator.py` — wire to col 0035
- Tests

**Complexity**: Low. Input-driven column, straightforward waterfall insertion.

**Verify**: `uv run pytest tests/unit/test_crm_processor.py tests/unit/test_corep.py -v`

---

#### Task 3E: Double default treatment (CRR only)

**Goal**: Implement double default RW formula (CRR Art. 153(3), 202-203) for guaranteed IRB exposures.

**COREP cols**: C 08.01: 0220, affects 0230 (avg LGD).

**Current state**: Not implemented. Basel 3.1 removes this, so CRR-only.

**Files**:
- `src/rwa_calc/engine/irb/formulas.py` — add double default capital formula
- `src/rwa_calc/engine/crm/processor.py` — add eligibility check
- `src/rwa_calc/data/schemas.py` — add output columns
- `src/rwa_calc/reporting/corep/generator.py` — wire to col 0220
- Tests

**New output columns**:
- `is_double_default_eligible: bool`
- `double_default_unfunded_protection: float` → COREP col 0220
- `irb_lgd_double_default: float`

**Complexity**: Medium-high. New IRB formula variant and eligibility logic.

**Verify**: `uv run pytest tests/unit/test_irb_formulas.py tests/unit/test_corep.py -v`

---

#### Task 3F: Post-model adjustments (Basel 3.1 only)

**Goal**: Add post-model adjustment columns for IRB RWEA and EL (PRA PS1/26, Art. 153(5A), 154(4A), 158(6A)).

**COREP cols**: OF 08.01: 0251-0254 (RWEA), 0281-0282 (EL).

**Files**:
- `src/rwa_calc/contracts/config.py` — add adjustment config parameters
- `src/rwa_calc/engine/irb/calculator.py` — apply adjustments after base IRB calculation
- `src/rwa_calc/data/schemas.py` — add output columns
- `src/rwa_calc/reporting/corep/generator.py` — wire to COREP cols
- Tests

**New output columns**:
- `rwa_pre_adjustments` → col 0251
- `post_model_adjustment_rwa` → col 0252
- `mortgage_rw_floor_adjustment` → col 0253
- `unrecognised_exposure_adjustment` → col 0254
- `el_pre_adjustment` → col 0280
- `post_model_adjustment_el` → col 0281
- `el_after_adjustment` → col 0282

**Complexity**: Medium. Config-driven adjustments applied in IRB calculator.

**Verify**: `uv run pytest tests/unit/test_irb_calculator.py tests/unit/test_corep.py -v`

---

#### Task 3G: Specialised lending detail rows (Basel 3.1)

**Goal**: Add project finance phase tracking and map to OF 07.00 rows 0021-0026.

**COREP rows**: OF 07.00: 0021-0026.

**Current state**: `sl_type` exists. Missing `project_phase`.

**Files**:
- `src/rwa_calc/data/schemas.py` — add `project_phase: Literal["pre_operational", "operational", "high_quality_operational"]`
- `src/rwa_calc/reporting/corep/templates.py` — add rows to B31 sections
- `src/rwa_calc/reporting/corep/generator.py` — filter and aggregate for SL sub-rows
- Tests

**Map**:
- 0021: `sl_type == "object_finance"`
- 0022: `sl_type == "commodities"`
- 0023: `sl_type == "project_finance"` (total)
- 0024: project_finance + `project_phase == "pre_operational"`
- 0025: project_finance + `project_phase == "operational"`
- 0026: project_finance + `project_phase == "high_quality_operational"`

**Complexity**: Low.

**Verify**: `uv run pytest tests/unit/test_corep.py -v -k "specialised_lending"`

---

#### Task 3H: Real estate detail rows (Basel 3.1)

**Goal**: Add cash-flow dependency flag and map to OF 07.00 rows 0330-0360.

**COREP rows**: OF 07.00: 0330-0360.

**Current state**: `property_type`, `property_ltv`, `is_income_producing`, `is_adc` exist. Missing `materially_dependent_on_property`.

**Files**:
- `src/rwa_calc/data/schemas.py` — add `materially_dependent_on_property: bool`
- `src/rwa_calc/engine/classifier/` — add regulatory RE classification logic
- `src/rwa_calc/reporting/corep/templates.py` — add rows to B31 sections
- `src/rwa_calc/reporting/corep/generator.py` — filter and aggregate for RE sub-rows
- Tests

**Map**:
- 0330: Regulatory residential RE (total)
- 0331: RRE + not materially dependent
- 0332: RRE + materially dependent
- 0340-0344: Regulatory commercial RE + SME splits
- 0350-0354: Other RE
- 0360: ADC (`is_adc == True`)

**Complexity**: Low-medium.

**Verify**: `uv run pytest tests/unit/test_corep.py -v -k "real_estate"`

---

#### Task 3I: Equity transitional provisions (Basel 3.1)

**Goal**: Track equity transitional approach and map to OF 07.00 memorandum rows 0371-0374.

**COREP rows**: OF 07.00: 0371-0374.

**Files**:
- `src/rwa_calc/engine/equity/calculator.py` — add transitional approach tracking
- `src/rwa_calc/data/schemas.py` — add `equity_transitional_approach`, `equity_higher_risk`
- `src/rwa_calc/reporting/corep/generator.py` — wire to memorandum rows
- Tests

**Map**:
- 0371: SA transitional + higher risk (400%+ RW)
- 0372: SA transitional + other equity
- 0373: IRB transitional + higher risk
- 0374: IRB transitional + other equity

**Complexity**: Low.

**Verify**: `uv run pytest tests/unit/test_corep.py -v -k "equity_transitional"`

---

#### Task 3J: Currency mismatch multiplier (Basel 3.1)

**Goal**: Implement 1.5x RW multiplier for retail/RE when exposure currency differs from borrower income currency (Art. 123B).

**COREP rows**: OF 07.00: 0380.

**Files**:
- `src/rwa_calc/data/schemas.py` — add `borrower_income_currency: pl.String` to exposure schema
- `src/rwa_calc/engine/sa/calculator.py` — apply 1.5x multiplier post-base-RW
- `src/rwa_calc/reporting/corep/generator.py` — wire to memorandum row 0380
- Tests

**New output column**: `currency_mismatch_multiplier_applied: bool`

**Complexity**: Medium.

**Verify**: `uv run pytest tests/unit/test_sa_calculator.py tests/unit/test_corep.py -v`

---

#### Task 3K: CCR module (Counterparty Credit Risk)

**Goal**: Implement SA-CCR (CRR Art. 274-280b) for counterparty credit risk exposure values.

**COREP cols**: C 07.00: 0210, 0211. C 07.00 rows: 0090-0130 (SFT, derivatives).

**Current state**: Explicitly out of scope in PRD. No CCR module exists.

**This is a major workstream** — not a single loop task. Breaking down:

**Sub-tasks** (each a separate loop iteration):

1. **3K.1**: Define CCR data model — input schemas for derivatives/SFTs, netting set definitions, trade-level data (`data/schemas.py`)
2. **3K.2**: SA-CCR replacement cost (RC) calculation — mark-to-market, collateral, netting (`engine/ccr/replacement_cost.py`)
3. **3K.3**: SA-CCR potential future exposure (PFE) — add-on factors by asset class, aggregation formula (`engine/ccr/pfe.py`)
4. **3K.4**: SA-CCR EAD = alpha × (RC + PFE), alpha=1.4 (`engine/ccr/calculator.py`)
5. **3K.5**: CCP exposure treatment — QCCP trade exposures (2% RW), default fund contributions (`engine/ccr/ccp.py`)
6. **3K.6**: SFT exposure calculation — master netting, supervisory haircuts for SFTs (`engine/ccr/sft.py`)
7. **3K.7**: Pipeline integration — add CCR calculator as new branch alongside SA/IRB/Slotting/Equity
8. **3K.8**: COREP integration — wire CCR output to C 07.00 cols 0210/0211 and rows 0090-0130

**Complexity**: Very high. Months of work. Recommend as a separate project.

---

## Dependency Graph

```
Phase 1 (atomic — must complete together)
  1A ──→ 1B ──→ 1C
                  │
Phase 2 (independent tasks, can parallelise)
  ├── 2A Supporting factors
  ├── 2B Exposure type rows
  ├── 2C CCF breakdown
  ├── 2D Output floor
  ├── 2E ECAI unrated split
  ├── 2F LFSE sub-columns
  ├── 2G "Of which" detail rows
  └── 2H Pre/post CRM substitution
                  │
Phase 3 (pipeline enhancements)
  ├── 3A Collateral method split ──→ 3B Credit derivatives
  ├── 3C CRM substitution flows (depends on 2H)
  ├── 3D On-BS netting (low effort, independent)
  ├── 3E Double default CRR (independent)
  ├── 3F Post-model adjustments B3.1 (independent)
  ├── 3G SL detail rows (low effort, independent)
  ├── 3H RE detail rows (independent)
  ├── 3I Equity transitional (low effort, independent)
  ├── 3J Currency mismatch multiplier (independent)
  └── 3K CCR module (major workstream, 8 sub-tasks)
```

## Global Verification

After each task: `uv run pytest tests/unit/test_corep.py -v`
After each phase: `uv run pytest tests/ -v --benchmark-skip`
Final: compare output against reference Excel templates in `docs/assets/`
