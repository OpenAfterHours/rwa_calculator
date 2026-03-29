# COREP Generator Gap Analysis: Current Implementation vs Actual Template Structures

## Context

After reviewing the actual COREP templates from the EBA/PRA reference documents against the current generator implementation, there are significant structural and content gaps. The documentation has been corrected; now the code needs to follow.

## Gap Summary

### 1. Fundamental Structural Issue: Template Orientation

**Current**: The generator treats exposure class as a **row dimension** — it produces one DataFrame with one row per exposure class (e.g., corporate, institution, retail) plus a total row.

**Actual**: Each COREP template is submitted **once per exposure class**. The exposure class is a filter/selector. Within each submission, rows are: totals, "of which" breakdowns, exposure type breakdown (on-BS/off-BS/CCR), risk weight breakdown, and memorandum items.

**Impact**: The current output shape is fundamentally different from what a regulatory submission requires. The risk weight breakdown (currently a separate `c07_rw_breakdown` template) is actually **Section 3 within C 07.00**, not a separate template.

### 2. Column Reference Numbering

**Current `C07_COLUMNS`** uses refs: 010, 020, 030, 040, 050, 060, 070, 080, 090
**Actual C 07.00** uses refs: 0010, 0030, 0040, 0050, 0060, 0070, 0080, 0090, 0100, 0110, 0120, 0130, 0140, 0150, 0160, 0170, 0180, 0190, 0200, 0210, 0211, 0215, 0216, 0217, 0220, 0230, 0240

The current column refs don't match any actual COREP column refs, and the column meanings are simplified/wrong:
- Current "040: Funded CRM (collateral)" ≠ Actual 0040 "Exposure net of value adjustments"
- Current "050: Unfunded CRM (guarantees)" ≠ Actual 0050 "(-) Guarantees"
- Current "070: Exposure value post CCF" ≠ Actual 0070 "(-) Financial collateral: Simple method"

**Current `C08_01_COLUMNS`** uses refs: 010, 020, 030, 040, 050, 060, 070, 080, 090, 100, 110
**Actual C 08.01** uses refs: 0010, 0020, 0030, 0040, 0050, 0060, 0070, 0080, 0090, 0100, 0110, 0120, 0130, 0140, 0150-0210, 0220, 0230, 0240, 0250, 0255, 0256, 0257, 0260, 0270, 0280, 0290, 0300, 0310

### 3. Missing Columns — Populatable from Existing Pipeline Data

These COREP columns can be populated using data the pipeline already produces:

**C 07.00:**
| COREP Col | Name | Pipeline Source |
|-----------|------|-----------------|
| 0010 | Original exposure | `drawn_amount + undrawn_amount` (already done, wrong ref) |
| 0030 | (-) Provisions | `scra_provision_amount + gcra_provision_amount` (already done, wrong ref) |
| 0040 | Net exposure | Derived: 0010 - 0030 (already done, wrong ref) |
| 0050 | (-) Guarantees | `guaranteed_portion` (available, mapped as "050" currently) |
| 0110 | Net after CRM substitution | Derivable from pre/post CRM columns |
| 0150 | Fully adjusted exposure (E*) | `ead_final` (pre-CCF value not separately tracked — gap) |
| 0200 | Exposure value | `ead_final` (mapped as "070" currently) |
| 0215 | RWEA pre supporting factors | `rwa_pre_factor` or `rwa_before_floor` (available) |
| 0216 | (-) SME supporting factor adj | `sme_supporting_factor` * RWA (available, not used) |
| 0217 | (-) Infrastructure factor adj | `infra_supporting_factor` * RWA (available, not used) |
| 0220 | RWEA after supporting factors | `rwa_final` (mapped as "080" currently) |
| 0230 | Of which: with ECAI | Filter on `sa_cqs` (already done, wrong ref) |

**Row sections populatable:**
| Section | Pipeline Source |
|---------|-----------------|
| Total (row 0010) | Sum all |
| Exposure types (0070/0080) | `exposure_type` = "loan" → on-BS, "contingent"/"facility" → off-BS |
| Risk weight breakdown (0140-0280) | `risk_weight` column — pivot by band (currently separate template) |
| CCF breakdown (0160-0190) | `ccf_applied` column — group by CCF bucket |

**C 08.01:**
| COREP Col | Name | Pipeline Source |
|-----------|------|-----------------|
| 0010 | PD assigned | `irb_pd_floored` (already done, wrong ref) |
| 0020 | Original exposure | `drawn_amount + undrawn_amount` (already done) |
| 0110 | Exposure value | `ead_final` (already done) |
| 0180 | Eligible financial collateral | `collateral_adjusted_value` (available, not split by type) |
| 0230 | Weighted avg LGD | `irb_lgd_floored` (already done) |
| 0250 | Weighted avg maturity (days) | `irb_maturity_m` × 365 (currently in years, template wants days) |
| 0255 | RWEA pre supporting factors | `rwa_pre_factor` (available, not used) |
| 0256 | (-) SME factor adj | Derivable from supporting factor columns |
| 0257 | (-) Infrastructure factor adj | Derivable |
| 0260 | RWEA after supporting factors | `rwa_final` (already done) |
| 0280 | Expected loss | `irb_expected_loss` (already done) |
| 0290 | (-) Provisions | `provision_held` (already done) |
| 0300 | Number of obligors | `counterparty_reference.n_unique()` (already done) |

### 4. Missing Columns — NOT Available in Pipeline (Require New Features)

These COREP columns require data the pipeline does not currently produce:

**C 07.00:**
| COREP Col | Name | What's Missing |
|-----------|------|----------------|
| 0060 | (-) Credit derivatives | CRM doesn't track credit derivatives separately |
| 0070 | (-) Financial collateral: Simple method | Collateral not split by CRM method (simple vs comprehensive) |
| 0080 | (-) Other funded credit protection | Not split from financial collateral |
| 0090/0100 | CRM substitution out/inflows | Not tracked as separate flows |
| 0120 | Volatility adjustment to exposure | FCCM intermediate values not preserved |
| 0130/0140 | (-) Cvam / vol+mat adjustments | FCCM intermediate values not preserved |
| 0210/0211 | Of which: CCR / CCR excl CCP | CCR module not implemented |

**C 08.01:**
| COREP Col | Name | What's Missing |
|-----------|------|----------------|
| 0030 | Of which: large financial sector entities | Entity classification not implemented |
| 0050 | (-) Credit derivatives | Not tracked separately |
| 0060 | (-) Other funded credit protection | Not split |
| 0150-0210 | CRM in LGD estimates (detailed collateral) | Collateral not broken down by type in output |
| 0220 | Double default treatment | Not implemented |
| 0240 | Avg LGD for large financial entities | Entity classification not implemented |
| 0310 | Pre-credit derivatives RWEA | Credit derivatives not tracked |

**Basel 3.1 specific:**
| COREP Col | Name | What's Missing |
|-----------|------|----------------|
| 0035 | On-balance sheet netting | Not tracked |
| 0251-0254 | Post-model adjustments | Not implemented |
| 0275-0276 | Output floor SA-equivalent | `sa_equivalent_rwa` exists but not wired to COREP |
| 0281-0282 | Post-model EL adjustments | Not implemented |

### 5. C 08.02 Structural Issue

**Current**: Groups into 8 pre-defined PD bands (0%-0.15%, 0.15%-0.25%, etc.)
**Actual**: Template has dynamic rows — one per firm-specific internal rating grade/pool, ordered by PD. No pre-defined bands.

The current PD banding approach is a reasonable simplification for reporting purposes (firms may aggregate into bands), but doesn't match the actual template structure which expects individual obligor grades.

### 6. Maturity Unit Mismatch

**Current**: `irb_maturity_m` is in **years** and the generator uses it directly.
**Actual**: COREP column 0250 requires "Exposure-weighted average maturity value (**days**)".

## Recommended Approach

### Phase 1: Structural Corrections (templates.py + generator.py)

1. **Fix column references** to match actual COREP numbering (0010, 0030, 0040... not 010, 020, 030)
2. **Restructure C 07.00 output** to be per-exposure-class with row sections:
   - Section 1: Total row (0010) + "of which" breakdowns (0015, 0020, etc.)
   - Section 2: Exposure type breakdown rows (0070 on-BS, 0080 off-BS)
   - Section 3: Risk weight breakdown rows (0140-0280) — merge current `c07_rw_breakdown` into main template
   - Section 5: Memorandum items (0290-0320)
3. **Remove `c07_rw_breakdown`** as separate template — it becomes Section 3 of C 07.00
4. **Fix C 08.01 maturity** to output in days (× 365)
5. **Add framework-aware column sets** — CRR columns (with supporting factors) vs Basel 3.1 columns (with output floor)

### Phase 2: Populate Available Columns

1. **Add supporting factor columns** to C 07.00 and C 08.01 (0215-0217 / 0255-0257) for CRR
2. **Add exposure type row breakdown** (on-BS/off-BS) using `exposure_type` column
3. **Add CCF breakdown rows** (0160-0190) using `ccf_applied`
4. **Add output floor columns** (0275-0276) for Basel 3.1 using existing `sa_equivalent_rwa`
5. **Wire up pre/post CRM columns** for CRM substitution reporting

### Phase 3: Future Pipeline Enhancements (Out of Scope Now)

Document as backlog items:
- Credit derivatives tracking in CRM
- Financial collateral simple vs comprehensive method split
- FCCM intermediate values (volatility adj, Cvam)
- CRM substitution flow tracking (outflows/inflows)
- Large financial sector entity classification
- Double default treatment
- Post-model adjustments (Basel 3.1)
- CCR module integration

## Key Files to Modify

- `src/rwa_calc/reporting/corep/templates.py` — Fix column refs, add row section definitions, add framework-specific columns
- `src/rwa_calc/reporting/corep/generator.py` — Restructure to per-exposure-class output with row sections
- `src/rwa_calc/reporting/corep/__init__.py` — Update exports if bundle structure changes
- `src/rwa_calc/contracts/bundles.py` — Update COREPTemplateBundle if structure changes
- `tests/unit/test_corep.py` — Rewrite tests for new structure

## Verification

- Run existing tests: `uv run pytest tests/unit/test_corep.py -v`
- Verify column refs match actual COREP numbering
- Verify Excel export produces sheets matching actual template structure
- Compare output against reference Excel templates in `docs/assets/`
