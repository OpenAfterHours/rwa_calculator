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
| 2A: Supporting factors | **DONE** | Cols 0215-0217 (C 07.00) and 0255-0257 (C 08.01) wired to rwa_before_sme_factor, sme/infra benefit computed. CRR only. |
| 2B: Exposure type rows | **DONE** | Section 2 rows 0070 (on-BS) and 0080 (off-BS) populated from bs_type column for C 07.00 and C 08.01. |
| 2C: CCF breakdown | **DONE** | Cols 0160-0190 populated from ccf_applied. CRR: 0%/20%/50%/100%. B3.1: 10%/20%/40%/50%/100% (inc. col 0171). Off-BS grouping. |
| 2D: Output floor | **DONE** | Cols 0275 (EAD) and 0276 (sa_equivalent_rwa) populated for B3.1 C 08.01. CRR excluded by column filtering. |
| 2E: ECAI unrated split | **DONE** | Col 0235 (unrated RWEA) already computed in Phase 1; verified with tests. Rated + unrated = total. |
| 2F: LFSE sub-columns | **DONE** | Cols 0030/0140/0240/0270 populated from apply_fi_scalar. Weighted avg LGD for LFSE. Zero when no LFSE in class. |
| 2G: "Of which" rows | **DONE** | C 07.00 rows 0015 (defaulted) and 0020 (SME) populated. C 08.01 cols 0125/0265 (defaulted EAD/RWEA) populated. |
| 2H: CRM substitution flows | **DONE** | C 07.00 cols 0090/0100/0110. C 08.01 cols 0040/0070/0080/0090. Pre-computed per-class inflows; outflows from subset. |
| 3D: On-BS netting | **DONE** | Col 0035 wired for B3.1 (C 07.00 + C 08.01). CRM processor tracks netting amounts. 7 new tests. |
| 3G: SL detail rows | **DONE** | Rows 0021-0026 wired for B3.1 OF 07.00. project_phase added to schema. 9 new tests. |
| 3H: RE detail rows | **DONE** | Rows 0330-0344, 0360 wired for B3.1 OF 07.00. materially_dependent_on_property added. 0350-0354 deferred. 9 new tests. |
| 3I: Equity transitional | **DONE** | Rows 0371-0374 wired for B3.1 OF 07.00 memorandum. equity_transitional_approach added. 6 new tests. |
| 3A: Collateral method split | **DONE** | Per-type collateral tracking in CRM processor. C 07.00 cols 0070/0080/0120/0140/0150. C 08.01 cols 0150-0210 (type breakdown). 8 new tests. |
| 3B: Credit derivatives | **DONE** | protection_type field added to guarantee schema. CRM processor carries type through pipeline. C 07.00 col 0060, C 08.01 cols 0050/0160/0310 wired. 8 new tests. |

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

**Implementation notes (completed)**:
- `rwa_before_sme_factor` used for pre-factor RWEA (0215/0255), falls back to `rwa_final` if not available.
- SME benefit (0216/0256) = `rwa_before_sme_factor - rwa_final` where `sme_supporting_factor_applied == True`.
- Infrastructure benefit (0217/0257) = same pattern with `infrastructure_factor_applied`.
- Columns filtered out for Basel 3.1 by existing framework column selection.
- 5 new tests in `TestSupportingFactors` class.

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

**Implementation notes (completed)**:
- `_filter_on_bs()` and `_filter_off_bs()` helpers filter on `bs_type` ("ONB"/"OFB"), falling back to `exposure_type` if `bs_type` not available.
- C 07.00 Section 2: row 0070 (on-BS) and 0080 (off-BS) populated with full column computation.
- C 08.01 Section 2: row 0020 (on-BS) and 0030 (off-BS) populated similarly.
- CCR rows (0090-0130) remain null — CCR not implemented.
- On-BS + off-BS = total verified in tests.
- 6 new tests in `TestExposureTypeRows` class.

---

#### Task 2C: Add CCF breakdown columns

**Goal**: Populate off-BS CCF breakdown (cols 0160-0190 for CRR; cols 0160, 0170, 0171, 0180, 0190 for Basel 3.1).

**Files**: `src/rwa_calc/reporting/corep/generator.py`, `tests/unit/test_corep.py`

**Pipeline source**: `ccf_applied` (0.0, 0.1, 0.2, 0.4, 0.5, 1.0), off-BS exposures only

**Map**: Group off-BS exposures by `ccf_applied`, sum the fully adjusted exposure value (E*) into the appropriate CCF column. CRR has 0%/20%/50%/100%; Basel 3.1 has 10%/20%/40%/50%/100%.

**Verify**: `uv run pytest tests/unit/test_corep.py -v -k "ccf_breakdown"`

**Implementation notes (completed)**:
- Off-BS exposures filtered by `bs_type == "OFB"`, grouped by `ccf_applied` into COREP CCF buckets.
- CRR mapping: 0.0→0160, 0.2→0170, 0.5→0180, 1.0→0190. B3.1 mapping: 0.1→0160, 0.2→0170, 0.4→0171, 0.5→0180, 1.0→0190.
- Framework detection via `"0171" in column_refs` (B3.1 has 40% CCF column, CRR doesn't).
- Value reported: `ead_final` sum for off-BS exposures in each CCF bucket.
- 5 new tests in `TestCCFBreakdown` class.

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

**Implementation notes (completed)**:
- Col 0275 = `ead_final.sum()` (SA-equivalent exposure value — same EAD used under SA).
- Col 0276 = `sa_equivalent_rwa.sum()` (from pipeline `sa_equivalent_rwa` column).
- CRR automatically excluded by column ref filtering (0275/0276 only in B3.1 column set).
- 0276 is null when `sa_equivalent_rwa` not available in pipeline data.
- 5 new tests in `TestOutputFloor` class.

---

#### Task 2E: Add ECAI unrated split (Basel 3.1 col 0235)

**Goal**: Add col 0235 (RWEA without ECAI) for Basel 3.1 alongside existing col 0230 (with ECAI).

**Files**: `src/rwa_calc/reporting/corep/generator.py`, `tests/unit/test_corep.py`

**Pipeline source**: `sa_cqs` (null = unrated)

**Map**: 0235 = `rwa_final.sum()` where `sa_cqs.is_null()`. Only for Basel 3.1.

**Verify**: `uv run pytest tests/unit/test_corep.py -v -k "ecai"`

**Implementation notes (completed)**:
- Col 0235 was already computed in Phase 1 generator (`sa_cqs.is_null()` filter).
- Added 3 tests in `TestECAIUnratedSplit`: column present in B3.1, unrated value correct, rated + unrated = total.

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

**Implementation notes (completed)**:
- `_filter_lfse()` helper: uses `apply_fi_scalar == True` to identify LFSE counterparties.
- Col 0030: original exposure (drawn + undrawn) for LFSE. Col 0140: EAD for LFSE.
- Col 0240: EAD-weighted average LGD for LFSE (uses `irb_lgd_floored`).
- Col 0270: RWEA for LFSE.
- All four cols = 0.0 when `apply_fi_scalar` exists but no LFSE in class; None when column absent.
- 6 new tests in `TestLFSESubColumns` class.
- Total: 171 COREP tests pass (3 Excel skipped), 1963 unit/contract/integration tests pass (3 pre-existing fixture failures).

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

**Implementation notes (completed)**:
- `_filter_defaulted()` helper: uses `default_status`, falls back to `exposure_class == "defaulted"`, then `irb_pd_floored >= 1.0`.
- `_filter_sme()` helper: uses `sme_supporting_factor_eligible`, falls back to `exposure_class.str.contains("sme")`.
- C 07.00 Section 1 row 0015 (defaulted) and 0020 (SME) populated with full column computation.
- C 08.01 cols 0125 (defaulted EAD) and 0265 (defaulted RWEA) populated.
- 7 new tests in `TestOfWhichDetailRows` class.
- Total: 155 COREP tests pass (3 Excel skipped), 1720 unit tests pass (3 pre-existing fixture failures).

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

**Implementation notes (completed)**:
- `_compute_substitution_flows()` helper pre-computes per-class outflows and inflows from the full collected DataFrame before per-class generation.
- Outflows: sum of `guaranteed_portion` where `pre_crm_exposure_class == class` and `post_crm_exposure_class_guaranteed != class`.
- Inflows: sum of `guaranteed_portion` where `post_crm_exposure_class_guaranteed == class` and `pre_crm_exposure_class != class`.
- `_compute_substitution_outflow()` computes outflow from any data subset (works for total row, sub-rows).
- Inflows pre-computed at class level, passed to total row only (sub-rows get 0 — full breakdown deferred to Task 3C).
- C 07.00 col 0110 formula: `0040 - 0050 - 0060 - 0070 - 0080 - 0090 + 0100` (Phase 3 cols default to 0).
- C 08.01 col 0040 (guarantees) now wired to `guaranteed_portion.sum()`.
- C 08.01 col 0090 formula: `0020 - 0040 - 0050 - 0060 - 0070 + 0080`.
- C 08.01 col 0100 (of which: off balance sheet) now wired to off-BS EAD sum.
- 9 new tests in `TestSubstitutionFlows` class.
- Total: 180 COREP tests pass (3 Excel skipped), 1870 unit/contract tests pass (3 pre-existing fixture failures).

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

**Implementation notes (completed)**:
- 5 new per-type collateral columns added to CALCULATION_OUTPUT_SCHEMA: `collateral_financial_value`, `collateral_re_value`, `collateral_receivables_value`, `collateral_other_physical_value`, `collateral_cash_value`.
- CRM processor's `_apply_collateral_unified()` extended: `_coll_category` classification (cash/financial/real_estate/receivables/other_physical), 5 per-type agg expressions in group_by, 3-level join propagation, final combine via `_sum3()`.
- Legacy (non-unified) path sets all 5 new columns to 0.0.
- C 07.00: col 0070=0.0 (comprehensive method used, simple method not implemented), col 0080=non-financial collateral sum, col 0120=0.0 (He=0 for loans), col 0140=market_value-adjusted_value, col 0150=max(0, net_after_crm - Cvam).
- C 08.01: col 0060=non-financial collateral, col 0150=guaranteed_portion, cols 0170-0173=0.0 (sub-types not tracked), col 0180=financial collateral, col 0190=RE, col 0200=other physical, col 0210=receivables.
- `_sum_cols_eager()` helper added for multi-column aggregation.
- Simple method (CRR Art. 222) deferred — current implementation uses comprehensive method. Col 0070 set to 0.0 as placeholder.
- 8 new tests in `TestCollateralMethodSplit` class.
- Total: 219 COREP tests pass (3 Excel skipped), 1887 unit/contract/integration tests pass.

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

**Implementation notes (completed)**:
- `protection_type` field added to `GUARANTEE_SCHEMA` (input) and `CALCULATION_OUTPUT_SCHEMA` (output). Values: "guarantee" or "credit_derivative".
- `VALID_PROTECTION_TYPES` validation set added. `COLUMN_VALUE_CONSTRAINTS["guarantees"]` updated.
- CRM processor: `apply_guarantees()` defaults `protection_type` to "guarantee" if absent (backward compatible). Column carried through `_apply_guarantee_splits()` group_by, all paths (no-guarantee, single, multi, remainder), and CRM audit trail.
- `_initialize_ead()` initializes `protection_type` to null for exposures before guarantee processing.
- COREP generator: `_sum_by_protection_type()` helper filters `guaranteed_portion` by protection type.
- C 07.00: col 0050 = guarantee-only portion, col 0060 = credit derivative portion. Col 0110 formula deducts both.
- C 08.01: col 0040 = guarantee-only, col 0050 = credit derivative. Col 0150 = unfunded guarantees, col 0160 = unfunded credit derivatives. Col 0310 = total RWEA (pre-credit-derivative baseline).
- Backward compatible: without `protection_type` column, all `guaranteed_portion` treated as guarantees (col 0060 = 0).
- Art. 204/216 derivative-specific eligibility conditions deferred — current implementation uses same substitution mechanics as guarantees.
- 8 new tests in `TestCreditDerivativeTracking` class.
- Total: 227 COREP tests pass (3 Excel skipped), 1965 unit/contract/integration tests pass.

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

**Implementation notes (completed)**:
- `on_bs_netting_amount` added to `CALCULATION_OUTPUT_SCHEMA` in schemas.py.
- `_join_netting_amounts()` helper in CRM processor extracts per-exposure netting amounts from synthetic netting collateral (market_value aggregated by beneficiary_reference).
- Both `get_crm_adjusted_bundle()` and `get_crm_unified_bundle()` now track netting amounts: joined from netting collateral when present, initialized to 0.0 when no netting applies.
- COREP generator wires `on_bs_netting_amount` to col 0035 in both `_compute_c07_values()` and `_compute_c08_values()`.
- Col 0035 correctly filtered out for CRR (not in CRR column refs). Present for Basel 3.1.
- Col 0040 formula includes netting: `0010 - 0030 - 0035`.
- 7 new tests in `TestOnBSNetting` class: B3.1 population, CRR absence, formula verification, zero-netting class, missing column handling.
- Total: 187 COREP tests pass (3 Excel skipped), 1979 unit/contract/integration tests pass (3 pre-existing fixture failures).

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

**Goal**: Add post-model adjustment columns for IRB RWEA and EL (PRA PS9/24, Art. 153(5A), 154(4A), 158(6A)).

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

**Implementation notes (completed)**:
- `project_phase` added to `SPECIALISED_LENDING_SCHEMA` (input). `sl_project_phase` added to `CALCULATION_OUTPUT_SCHEMA`.
- `VALID_PROJECT_PHASES` validation set added: pre_operational, operational, high_quality_operational.
- `_filter_sl_type()` helper: filters by `sl_type` column value.
- `_filter_project_phase()` helper: filters by `sl_type == "project_finance"` AND `sl_project_phase` match.
- Generator Section 1 handler: rows 0021-0023 filter by SL type, rows 0024-0026 filter by project phase.
- Rows correctly absent under CRR (not in CRR row sections).
- Phase rows sum to total PF verified: 0024 + 0025 + 0026 = 0023.
- 9 new tests in `TestSpecialisedLendingRows` class.
- Total: 196 COREP tests pass (3 Excel skipped).

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

**Implementation notes (completed)**:
- `materially_dependent_on_property` added to `CALCULATION_OUTPUT_SCHEMA`.
- `_filter_re()` helper: flexible filter supporting property_type, materially_dependent, is_sme, and is_adc criteria.
- `_RE_ROW_FILTERS` config dict maps row refs to filter kwargs, keeping the generator Section 1 handler clean.
- Rows 0330-0332 (residential), 0340-0344 (commercial with SME/dependency splits), 0360 (ADC) all wired.
- Rows 0350-0354 ("Other RE") remain null — requires a `regulatory_re_category` field to distinguish regulatory vs other RE. Documented as future work.
- 9 new tests in `TestRealEstateRows`: totals, dependency splits, SME splits, ADC, CRR absence, sum verification.
- Total: 205 COREP tests pass (3 Excel skipped).

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

**Implementation notes (completed)**:
- `equity_transitional_approach` and `equity_higher_risk` added to `CALCULATION_OUTPUT_SCHEMA`.
- `_EQUITY_TRANSITIONAL_FILTERS` config maps rows 0371-0374 to approach/higher_risk combinations.
- `_filter_equity_transitional()` helper filters by approach and higher_risk flag.
- Generator Section 5 handler wires rows with filter or falls back to null for other memorandum rows (0300, 0320, 0380).
- 6 new tests in `TestEquityTransitionalRows`: all 4 rows populated, CRR absence, missing column handling.
- Total: 211 COREP tests pass (3 Excel skipped).

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
