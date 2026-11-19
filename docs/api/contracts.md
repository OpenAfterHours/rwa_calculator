# Contracts API

The `rwa_calc.contracts` package defines the data transfer types, error handling, and
protocol interfaces that glue the pipeline together. Every pipeline stage receives and
returns frozen dataclass bundles — never raw dicts — ensuring type safety and immutability
across the calculation flow.

**Why contracts matter:** The pipeline processes regulatory capital calculations where
correctness is paramount. Typed contracts catch structural errors at development time
rather than at runtime inside a 100K-exposure production run. The protocol-driven design
also allows any component to be swapped or mocked without modifying callers.

---

## Data Bundles

### Module: `rwa_calc.contracts.bundles`

Each bundle is a `@dataclass(frozen=True)` containing Polars `LazyFrame` fields. Bundles
flow through the pipeline in order:

```
Loader → RawDataBundle → HierarchyResolver → ResolvedHierarchyBundle
    → Classifier → ClassifiedExposuresBundle → CRMProcessor → CRMAdjustedBundle
    → SA/IRB/Slotting/Equity Calculators → Result Bundles
    → OutputAggregator → AggregatedResultBundle
```

#### `RawDataBundle`

Output from the data loader. Contains all raw input data as LazyFrames, exactly as loaded
from source systems with no transformations applied.

```python
@dataclass(frozen=True)
class RawDataBundle:
    # Required fields
    facilities: pl.LazyFrame           # Credit facility records
    loans: pl.LazyFrame                # Drawn loan records
    counterparties: pl.LazyFrame       # Counterparty/borrower information
    facility_mappings: pl.LazyFrame    # Facility hierarchy mappings
    lending_mappings: pl.LazyFrame     # Lending group mappings (for retail aggregation)

    # Optional fields
    org_mappings: pl.LazyFrame | None = None        # Organisational hierarchy
    contingents: pl.LazyFrame | None = None         # Off-balance sheet contingent items
    collateral: pl.LazyFrame | None = None          # Security/collateral items
    guarantees: pl.LazyFrame | None = None          # Guarantee/credit protection items
    provisions: pl.LazyFrame | None = None          # IFRS 9 provisions (SCRA/GCRA)
    ratings: pl.LazyFrame | None = None             # Internal and external credit ratings
    specialised_lending: pl.LazyFrame | None = None # Specialised lending metadata (slotting)
    equity_exposures: pl.LazyFrame | None = None    # Equity exposure details
    fx_rates: pl.LazyFrame | None = None            # FX rates for currency conversion
    model_permissions: pl.LazyFrame | None = None  # Per-model IRB approach permissions
```

#### `CounterpartyLookup`

Resolved counterparty hierarchy information. All lookups are LazyFrames — use joins to
look up values instead of dict access.

```python
@dataclass(frozen=True)
class CounterpartyLookup:
    counterparties: pl.LazyFrame         # Counterparty data with resolved hierarchy
    parent_mappings: pl.LazyFrame        # child_counterparty_reference → parent_counterparty_reference
    ultimate_parent_mappings: pl.LazyFrame  # counterparty_reference → ultimate_parent_reference, hierarchy_depth
    rating_inheritance: pl.LazyFrame     # counterparty_reference → rating info with inheritance metadata
```

#### `ResolvedHierarchyBundle`

Output from the hierarchy resolver. Contains exposures with fully resolved counterparty
hierarchies (for rating inheritance), facility hierarchies (for CRM inheritance), and
lending group aggregation (for retail threshold checks).

```python
@dataclass(frozen=True)
class ResolvedHierarchyBundle:
    exposures: pl.LazyFrame                          # Unified exposure records with hierarchy metadata
    counterparty_lookup: CounterpartyLookup           # Resolved counterparty information
    lending_group_totals: pl.LazyFrame                # Aggregated exposures by lending group
    collateral: pl.LazyFrame | None = None            # Collateral with beneficiary hierarchy resolved
    guarantees: pl.LazyFrame | None = None            # Guarantees with beneficiary hierarchy resolved
    provisions: pl.LazyFrame | None = None            # Provisions with beneficiary hierarchy resolved
    equity_exposures: pl.LazyFrame | None = None      # Equity exposure details (passed through)
    model_permissions: pl.LazyFrame | None = None    # Per-model IRB approach permissions
    hierarchy_errors: list = field(default_factory=list)  # Errors encountered during resolution
```

#### `ClassifiedExposuresBundle`

Output from the classifier. Contains all exposures classified by exposure class
(`ExposureClass`) and calculation approach (`ApproachType`) on a single unified
frame — downstream consumers filter on the `approach` column.

```python
@dataclass(frozen=True)
class ClassifiedExposuresBundle:
    all_exposures: pl.LazyFrame                        # All exposures with classification metadata
    equity_exposures: pl.LazyFrame | None = None       # Equity exposures (SA only under Basel 3.1)
    collateral: pl.LazyFrame | None = None             # Collateral data for CRM processing
    guarantees: pl.LazyFrame | None = None             # Guarantee data for CRM processing
    provisions: pl.LazyFrame | None = None             # Provision data for CRM processing
    counterparty_lookup: CounterpartyLookup | None = None  # Counterparty data for guarantor risk weights
    classification_audit: pl.LazyFrame | None = None   # Audit trail of classification decisions
    classification_errors: list = field(default_factory=list)  # Errors during classification
```

#### `CRMAdjustedBundle`

Output from the CRM processor. Contains exposures with credit risk mitigation applied:
collateral effects (haircuts, allocation), guarantee effects (substitution), and provision
effects (SCRA/GCRA). EAD and LGD values are adjusted based on CRM.

```python
@dataclass(frozen=True)
class CRMAdjustedBundle:
    exposures: pl.LazyFrame                            # Unified frame with CRM-adjusted EAD and LGD
    equity_exposures: pl.LazyFrame | None = None       # Equity exposures (passed through, no CRM)
    collateral_allocation: pl.LazyFrame | None = None  # How collateral was allocated to exposures
    crm_errors: list = field(default_factory=list)     # Errors during CRM processing
```

The per-exposure CRM audit projection is sunk to the opt-in audit cache
(`crm_audit.parquet`), not carried as a bundle field.

#### Result Bundles

The SA / IRB / slotting calculators return plain `pl.LazyFrame`s from
`calculate_branch()` (the aggregator consumes the collected branch frames
directly). Equity — the separate path — keeps a result bundle:

```python
@dataclass(frozen=True)
class EquityResultBundle:
    """Equity exposure results under Article 133 (SA) or Article 155 (IRB Simple)."""
    results: pl.LazyFrame                          # Equity results with risk weights and RWA
    calculation_audit: pl.LazyFrame | None = None  # Detailed calculation breakdown
    approach: str = "sa"                           # "sa" (Art. 133) or "irb_simple" (Art. 155)
    errors: list = field(default_factory=list)
```

#### `ELPortfolioSummary`

Portfolio-level expected loss summary with T2 credit cap. Aggregates per-exposure EL
shortfall/excess into portfolio totals and applies the T2 credit cap per CRR Art. 62(d).

**Why this exists:** Under IRB, provisions and expected loss interact with regulatory
capital through T2 credit (for excess provisions) and CET1/T2 deductions (for shortfalls).
This summary captures the full EL-to-capital flow in one place.

```python
@dataclass(frozen=True)
class ELPortfolioSummary:
    total_expected_loss: float         # Sum of EL across all IRB exposures
    total_provisions_allocated: float  # Sum of provisions allocated to IRB exposures
    total_el_shortfall: float          # Sum of max(0, EL - provisions) per exposure
    total_el_excess: float             # Sum of max(0, provisions - EL) per exposure
    total_irb_rwa: float               # Total IRB RWA (denominator for T2 cap)
    t2_credit_cap: float               # 0.6% of total IRB RWA (CRR Art. 62(d))
    t2_credit: float                   # min(total_el_excess, t2_credit_cap) — addable to T2 capital
    cet1_deduction: float              # 100% of total_el_shortfall — deducted from CET1 (Art. 36(1)(d))
    t2_deduction: float                # Always zero (no T2 deduction for shortfall)
```

#### `AggregatedResultBundle`

Final aggregated output from the output aggregator. Combines SA, IRB, slotting, and equity
results with output floor application (Basel 3.1) and supporting factor adjustments (CRR).

```python
@dataclass(frozen=True)
class AggregatedResultBundle:
    results: pl.LazyFrame                                  # Final RWA results with all adjustments
    sa_results: pl.LazyFrame | None = None                 # Original SA results (for floor comparison)
    irb_results: pl.LazyFrame | None = None                # Original IRB results (before floor)
    slotting_results: pl.LazyFrame | None = None           # Original slotting results
    equity_results: pl.LazyFrame | None = None             # Equity calculation results
    floor_impact: pl.LazyFrame | None = None               # Output floor impact analysis (Basel 3.1)
    supporting_factor_impact: pl.LazyFrame | None = None   # Supporting factor impact (CRR only)
    summary_by_class: pl.LazyFrame | None = None           # RWA summarised by exposure class
    summary_by_approach: pl.LazyFrame | None = None        # RWA summarised by approach
    pre_crm_summary: pl.LazyFrame | None = None            # Pre-CRM summary (gross view by original class)
    post_crm_detailed: pl.LazyFrame | None = None          # Post-CRM detailed view (split rows for guarantees)
    post_crm_summary: pl.LazyFrame | None = None           # Post-CRM summary (net view by effective class)
    el_summary: ELPortfolioSummary | None = None           # Portfolio-level EL summary with T2 credit cap
    errors: list = field(default_factory=list)              # All errors accumulated throughout pipeline
```

#### Comparison and Impact Bundles

These bundles support dual-framework comparison during the Basel 3.1 transition:

```python
@dataclass(frozen=True)
class ComparisonBundle:
    """Dual-framework comparison results (M3.1).
    Holds CRR and Basel 3.1 pipeline results side by side."""
    crr_results: AggregatedResultBundle       # Full CRR pipeline output
    b31_results: AggregatedResultBundle       # Full Basel 3.1 pipeline output
    exposure_deltas: pl.LazyFrame             # Per-exposure CRR vs B31 RWA, risk weights, EAD
    summary_by_class: pl.LazyFrame            # Delta RWA aggregated by exposure class
    summary_by_approach: pl.LazyFrame         # Delta RWA aggregated by calculation approach
    errors: list = field(default_factory=list)

@dataclass(frozen=True)
class TransitionalScheduleBundle:
    """Transitional floor schedule modelling (M3.3).
    Models the year-by-year output floor from 60% (2027) to 72.5% (2030+)."""
    timeline: pl.LazyFrame                         # Year-by-year floor impact summary
    yearly_results: dict[int, AggregatedResultBundle] = field(default_factory=dict)
    errors: list = field(default_factory=list)

@dataclass(frozen=True)
class CapitalImpactBundle:
    """Capital impact analysis (M3.2).
    Decomposes RWA delta between CRR and Basel 3.1 into regulatory drivers:
    scaling factor removal, supporting factor removal, output floor, methodology changes."""
    exposure_attribution: pl.LazyFrame    # Per-exposure driver attribution
    portfolio_waterfall: pl.LazyFrame     # Portfolio-level waterfall steps (CRR baseline to B31)
    summary_by_class: pl.LazyFrame        # Attribution aggregated by exposure class
    summary_by_approach: pl.LazyFrame     # Attribution aggregated by calculation approach
    errors: list = field(default_factory=list)
```

### Helper Functions

Factory functions for creating empty bundles, primarily used in testing:

| Function | Returns | Purpose |
|----------|---------|---------|
| `create_empty_raw_data_bundle()` | `RawDataBundle` | Empty bundle with empty LazyFrames for required fields |
| `create_empty_counterparty_lookup()` | `CounterpartyLookup` | Empty lookup with correct schemas for all 4 fields |
| `create_empty_resolved_hierarchy_bundle()` | `ResolvedHierarchyBundle` | Empty bundle using `create_empty_counterparty_lookup()` |
| `create_empty_classified_bundle()` | `ClassifiedExposuresBundle` | Empty bundle with an empty `all_exposures` LazyFrame |
| `create_empty_crm_adjusted_bundle()` | `CRMAdjustedBundle` | Empty bundle with an empty `exposures` LazyFrame |

---

## Error Handling

### Module: `rwa_calc.contracts.errors`

The error handling system uses error accumulation rather than exceptions. Data quality
issues are collected as `CalculationError` instances and propagated through bundles —
the pipeline continues processing all exposures and reports all issues at the end.

**Why accumulation over exceptions:** A regulatory calculation that throws on the first
bad exposure and stops is far less useful than one that processes all valid exposures
and produces a complete error report. Auditors and risk analysts need to see every issue,
not just the first one.

#### `CalculationError`

Immutable representation of a calculation error or warning:

```python
@dataclass(frozen=True)
class CalculationError:
    code: str                                  # Error code (e.g., "CRM001", "DQ003")
    message: str                               # Human-readable description
    severity: ErrorSeverity                    # WARNING, ERROR, or CRITICAL
    category: ErrorCategory                    # DATA_QUALITY, BUSINESS_RULE, etc.
    exposure_reference: str | None = None      # Affected exposure identifier
    counterparty_reference: str | None = None  # Affected counterparty identifier
    regulatory_reference: str | None = None    # Regulatory article (e.g., "CRR Art. 153")
    field_name: str | None = None              # Name of the problematic field
    expected_value: str | None = None          # Description of expected value/format
    actual_value: str | None = None            # Actual value that caused the error
```

Methods:

- `__str__()` — Human-readable format: `[DQ001] ERROR: Required field 'pd' is missing | Exposure: EXP001 | Ref: CRR Art. 153`
- `to_dict()` — Dictionary serialisation of all fields

!!! note
    There is no separate `CalculationWarning` class. Warnings are `CalculationError`
    instances with `severity=ErrorSeverity.WARNING`.

#### Error Code Constants

Error codes are prefixed by domain and numbered sequentially:

| Code | Constant | Domain | Description |
|------|----------|--------|-------------|
| `DQ001` | `ERROR_MISSING_FIELD` | Data Quality | Required field is missing or null. Two producers at two granularities: the loader seal names the **column** (`missing_required_column_error`, category `SCHEMA_VALIDATION`) when a required column is absent from the input file; the referential-integrity gate names the **row** (`absent_reference_error`, category `DATA_QUALITY`) when a declared foreign key is null, so the row asserts no link to its parent table at all. Both can fire on one feed — after the seal an absent column and an all-null one are indistinguishable — and the categories are what tell them apart. Distinct from `DQ005`: a null reference is repaired in **this** row, an orphan in the **parent** feed |
| `DQ002` | `ERROR_INVALID_VALUE` | Data Quality | Invalid value for a field |
| `DQ003` | `ERROR_TYPE_MISMATCH` | Data Quality | **Reserved — no producer.** Its sole emitter was `validate_schema_to_errors`, deleted when the loader edge seal made a downstream schema-shape check unfirable: `conform_lenient` casts every declared column to its declared dtype (`strict=False`), so a mismatch cannot reach a consumer. Kept reserved rather than recycled so old audit records stay readable. The same finding taken **upstream** of that cast, where it does fire on real feeds, is `DQ014` |
| `DQ004` | `ERROR_DUPLICATE_KEY` | Data Quality | A natural key names more than one input row. Two producers: `engine/hierarchy/graph.py` for a duplicated `org_mappings` child (WARNING — the resolver de-duplicates the mapping deterministically and no exposure is lost), and `validation.py::validate_duplicate_keys` for the tables in `TABLE_UNIQUE_KEYS` (ERROR — a duplicated `loan_reference` / `contingent_reference` / `facility_reference` is collapsed by the model-permission de-dupe, so the extra row's capital leaves the portfolio total, and a duplicated `counterparty_reference` multiplies every exposure that joins to it). **Uncapped, one error per duplicated key**: unlike the domain gates this names a row, not a column, so a sampled duplicate would leave the un-sampled rows exactly as unaccounted-for as before |
| `DQ005` | `ERROR_ORPHAN_REFERENCE` | Data Quality | A declared foreign key (`data/schemas.py::TABLE_FOREIGN_KEYS`) holds a value that resolves to no row in its parent table. The row is **never dropped** — every counterparty-attribute join in the hierarchy stage is `how="left"` deliberately, because an exposure that has left the portfolio is worse than one priced off a fallback — so it survives carrying the substituted treatment named in the declaration's `reason`. Measured on CRR, one GBP 1m senior loan: a CQS 6 corporate is Art. 122 150% and the orphan fallback returns 100%, a 33.3% understatement; at CQS 1 the same fallback is a 5x overstatement, so the defect is not conservative in either direction. Sampled per the `sample_cap` contract (5 row-named errors per table/column, then one summary carrying the omitted count). Emitted by `validation.py::validate_referential_integrity` |
| `DQ006` | `ERROR_INVALID_COLUMN_VALUE` | Data Quality | Column value not in allowed set |
| `DQ012` | `ERROR_NEGATIVE_AMOUNT` | Data Quality | Amount column negative where a negative cannot be a netting convention. Distinct from `DQ010`, which warns on a negative that *is* legitimately a netting position |
| `DQ014` | `ERROR_UNREADABLE_INPUT_DTYPE` | Data Quality | Input column supplied in a dtype whose cast to the declared dtype can destroy values — a String amount (`"1,000,000.00"`, `£1000000`, `n/a`), a float into a declared integer, a numeric into a declared String key. The loader seal casts non-strictly, so an unparseable value becomes null, and null is legitimately "not supplied" everywhere downstream: without this code a value that could not be **read** is indistinguishable from one never **supplied** and from a genuine zero (measured: a GBP 1m `drawn_amount` published `rwa_final = 0.00` with an empty error list). A writer's own type choice — any integer into any integer/float, an all-null column, `Float32`→`Float64`, `Date`→`Datetime` — is **not** reported. Emitted by `EdgeContract.conform_lenient` via `engine/loader.py::_seal_table`. Distinct from `DQ001`: absent column → extend the feed; unreadable column → re-type and re-send it |
| `DQ017` | `ERROR_ISSUED_ITEM_ON_COMMITMENT_RISK_TYPE` | Data Quality | WARNING. A contingent with a non-zero `nominal_amount` carries a commitment `risk_type` (`MR` = NIF / RUF, `OC` = other commitment) while `is_obs_commitment` is False — the contingent default, which marks an issued item. Under CRR F-IRB the row takes the Art. 166(10)(b) issued-item 50% instead of the Art. 166(8)(d) 75% the bucket names; under Basel 3.1 A-IRB it is not a revolving loan commitment, so no own estimate applies (PS1/26 Art. 166D(1)(b)). Reported, not resolved: set `is_obs_commitment` True for a commitment booked as a contingent, or use `MR_ISSUED` for an issued medium-risk item. Emitted by `validation.py::_validate_issued_item_on_commitment_risk_type` |
| `HIE001` | `ERROR_CIRCULAR_HIERARCHY` | Hierarchy | Circular reference in hierarchy |
| `HIE002` | `ERROR_MISSING_PARENT` | Hierarchy | Parent counterparty not found |
| `HIE003` | `ERROR_HIERARCHY_DEPTH` | Hierarchy | Hierarchy exceeds maximum depth |
| `HIE004` | `ERROR_UNCOMMITTED_FACILITY_RISK_TYPE` | Hierarchy | **WARNING.** A `committed=False` facility declares a `risk_type` other than `LR`. An uncommitted facility is an accepted, unconditionally cancellable commitment (PS1/26 Glossary "commitment"), so its undrawn row is priced in the UCC bucket `LR` regardless — CRR Annex I 4(a) 0%, PS1/26 Table A1 row (7) 10%. `exposure_reference` carries the facility reference, `actual_value` the declared type. Emitted by `engine/hierarchy/facility_warnings.py`. HIE004-HIE006 each follow the `sample_cap` contract: up to 5 facilities named per code, then one summary (`exposure_reference` null, `actual_value` = the omitted count) |
| `HIE005` | `ERROR_FACILITY_HEADROOM_FX_RATE_MISSING` | Hierarchy | **WARNING.** An amount could not be put in its facility's currency because the run holds no FX rate for it: a loan / contingent drawn in another currency (**not netted** against the headroom, so the undrawn commitment is measured gross of it), or an MOF sub-facility limit in a currency other than its umbrella's (the sub takes no slice of the waterfall). One per (facility, currency). Not raised when `apply_fx_conversion=False`. Ref CRR Art. 4(1)(56) |
| `HIE006` | `ERROR_FACILITY_LIMIT_MISSING` | Hierarchy | **WARNING.** A facility other than an MOF umbrella has a null `limit`: its undrawn commitment cannot be measured, so no undrawn row is generated (the engine does not invent a limit). On an umbrella a null limit means "uncapped above the sub-limits" and is not reported. Ref CRR Art. 4(1)(56) |
| `CLS001` | `ERROR_UNKNOWN_EXPOSURE_CLASS` | Classification | Cannot determine exposure class |
| `CLS002` | `ERROR_APPROACH_NOT_PERMITTED` | Classification | Requested approach not permitted by config |
| `CLS003` | `ERROR_MISSING_RATING` | Classification | No rating available for rated class |
| `CLS004` | `ERROR_QRRE_COLUMNS_MISSING` | Classification | QRRE-specific input columns missing for retail revolving classification |
| `CLS005` | `ERROR_RETAIL_POOL_MGMT_MISSING` | Classification | Retail pool-management columns required for retail-pool aggregation are missing |
| `CLS012` | `ERROR_SLOTTING_CATEGORY_MISSING` | Classification | **WARNING, both regimes.** Row(s) routed to the slotting approach whose `slotting_category` is null or not one of `strong` / `good` / `satisfactory` / `weak` / `default`. CRR / PS1/26 Art. 153(5) weight a slotted exposure by the grade the institution assigns; the engine applies the cited pack default (`satisfactory`) to the risk weight and expected-loss rate, and this aggregate warning (with the row count) makes that visible. Emitted by `engine/classify/audit.py::collect_classified_frame_warnings` |
| `CRM001` | `ERROR_INELIGIBLE_COLLATERAL` | CRM | Collateral type not eligible for CRM |
| `CRM002` | `ERROR_MATURITY_MISMATCH` | CRM | Collateral maturity < exposure maturity |
| `CRM003` | `ERROR_CURRENCY_MISMATCH` | CRM | Collateral currency ≠ exposure currency |
| `CRM004` | `ERROR_COLLATERAL_OVERALLOCATION` | CRM | Collateral allocated exceeds available amount |
| `CRM005` | `ERROR_INVALID_GUARANTEE` | CRM | Guarantee does not meet eligibility criteria |
| `CCR027` | `ERROR_SFT_COLLATERAL_NOT_RECOGNISED` | CRM (SFT FCCM) | **WARNING**, one per SFT collateral row. The row's `collateral_type` is not financial collateral the SFT path prices from the Art. 224 Tables 1 / 3 (`data/schemas.py::SFT_FCCM_HAIRCUT_LOOKUP_TYPES` — real estate, receivables, other physical, a bare `bond`, fund units, an unknown string, a null), or it is a bond failing the Art. 197(1)(b)–(d) CQS test, or it is keyed to a `netting_set_id` that holds no SFT trade. It contributes nothing to `E*` (CRR / PS1/26 Art. 223(1) values *financial* collateral only). Emitted by `engine/sft/fccm.py` |
| `CCR028` | `ERROR_SFT_NETTING_NOT_RECOGNISED` | CCR legal (SFT FCCM) | **WARNING**, one per SFT netting set holding more than one trade whose trades do not all carry `under_master_netting_agreement` **and** `is_legally_enforceable` (an eligible MNA, Art. 220(1) / 206; PS1/26 Art. 111(2A)). The set is split into one exposure per trade; collateral not linked to one of its trades by `trade_id` is not recognised and is named. Emitted by `engine/sft/netting.py` |
| `CCR029` | `ERROR_SFT_MULTI_COUNTERPARTY_NETTING_SET` | Data Quality (SFT FCCM) | **ERROR**, one per SFT netting set naming more than one `counterparty_reference`. A master netting agreement is bilateral (Art. 220(4)), so the set is split into one exposure per trade, each on its own counterparty — never booked whole against the first counterparty's risk weight. Emitted by `engine/sft/netting.py` |
| `CRM027` | `ERROR_TRANCHED_PROTECTION_NOT_RECOGNISED` | CRM | **WARNING.** Guarantee covers a band of the loss (`attachment_amount` > 0 or any `detachment_amount`): Art. 234 sends a tranched transfer to the securitisation framework and Art. 235(2) allows substitution only for equal seniority, so it is not recognised. One per guarantee row |
| `CRM028` | `ERROR_GUARANTEE_REFERENCE_INCONSISTENT` | CRM | **WARNING.** Rows sharing a `guarantee_reference` (one contract, one cap) state different `amount_covered` values — the largest is used as the cap — or repeat one beneficiary. One per reference and cause |
| `CRM029` | `ERROR_NOT_ELIGIBLE_PROTECTION_TYPE` | CRM | **WARNING.** `guarantee_type` is a letter of comfort or keepwell — not an explicitly documented obligation to pay (Art. 213(1)(b)-(d), 215(1)(b)); not recognised. One per guarantee row |
| `CRM030` | `ERROR_PROTECTION_TYPE_MISMATCH` | CRM | **WARNING.** `guarantee_type` names a credit derivative while `protection_type` does not; the row is treated as a credit derivative (Art. 233(2) applies when restructuring is excluded). One per guarantee row |
| `CRM023` | `ERROR_COLLATERAL_CURRENCY_UNKNOWN` | CRM | Collateral with no stated currency, treated as currency-mismatched (H_fx applied; Art. 224 / PS1/26 Art. 230(1)(b)). Rolled up per run |
| `CRM024` | `ERROR_ON_DEMAND_NETTED_DEPOSIT` | CRM | Netted deposit with no maturity date treated as repayable on demand (residual 0, Art. 238(1)); relief against later-maturing loans removed by Art. 237(1). One per netting agreement |
| `CRM025` | `ERROR_CCR_ONLY_COLLATERAL_POOL` | CRM | Loan-table collateral pledged only to CCR netting-set / failed-trade / default-fund rows, which take no loan-table collateral (CRR Art. 223(5A), PS1/26 Art. 191A(4)). Rolled up per run |
| `CRM026` | `ERROR_NON_ART197_FLAGGED_FINANCIAL` | CRM | Non-Art. 197 collateral flagged `is_eligible_financial_collateral`; the flag is ignored for the SA (the Comprehensive Method's exposure-value reduction and the Simple Method's risk-weight substitution). Rolled up per run |
| `IRB001` | `ERROR_PD_OUT_OF_RANGE` | IRB | PD value outside valid range **[0, 1]**. The lower bound is **closed**: CRR Art. 160(1) does not reach central governments or central banks, and the CRR pack carries `pd_floors["sovereign"] = 0`, so PD = 0 is admissible sovereign input and a half-open `(0, 1]` domain would reject every sovereign IRB exposure |
| `IRB002` | `ERROR_LGD_OUT_OF_RANGE` | IRB | LGD value outside valid range **[0, 1.25]**. 1.0 is not a hard ceiling — own-estimate downturn LGD can exceed 100% where workout costs exceed the exposure |
| `IRB003` | `ERROR_MATURITY_INVALID` | IRB | Effective maturity outside [1, 5] range |
| `IRB004` | `ERROR_MISSING_PD` | IRB | No PD value available for IRB exposure |
| `IRB005` | `ERROR_MISSING_LGD` | IRB | No LGD value available for A-IRB exposure |
| `IRB006` | `ERROR_MISSING_EXPECTED_LOSS` | IRB | Expected-loss value missing on an IRB exposure where EL is required |
| `IRB008` | `ERROR_CCF_OUT_OF_RANGE` | IRB | Own-estimate CCF outside `[0, 1.5]`. Retail A-IRB additional drawdown can exceed 100%, so 1.0 is not the ceiling; null is valid (the field is optional) |
| `SA001` | `ERROR_INVALID_CQS` | SA | CQS value not in valid range |
| `SA002` | `ERROR_MISSING_RISK_WEIGHT` | SA | Cannot determine risk weight |
| `SA003` | `ERROR_INVALID_LTV` | SA | LTV ratio invalid for property class |
| `SA005` | `ERROR_EQUITY_IN_MAIN_TABLE` | SA | Equity exposure incorrectly present in the main SA exposure table (must route through the equity calculator) |
| `SA006` | `ERROR_PF_PHASE_UNEVIDENCED` | SA | **WARNING, Basel 3.1 only.** Project-finance exposure(s) whose `project_phase` is null or not one of `pre_operational` / `operational` / `high_quality_operational`. PS1/26 Art. 122B(3) defines the operational phase by conditions the firm must show, so the exposure is treated as pre-operational — the Art. 122B(2)(c) 130% when unrated, on SA rows and on the output-floor SA-equivalent of slotted rows. One aggregate warning carrying the row count, emitted by the classifier (`engine/classify/audit.py::collect_classified_frame_warnings`) |
| `SA008` | `ERROR_CIU_HOLDING_CLASS_UNSUPPORTED` | SA | **WARNING.** A `ciu_holdings` row whose `exposure_class` is null or outside the `ExposureClass` vocabulary (compared case-insensitively — e.g. `securitisation`, `subordinated_debt`, `sovereign`). Such an underlying cannot be weighted "as if directly held" (PS1/26 Art. 132A(1)), so a look-through fund holding it takes the Art. 132(2) 1,250% fall-back on that holding's value. One rolled-up warning naming the values, emitted by the input-domain gate (`contracts/validation.py::_validate_ciu_holding_classes`); the weight is applied by `engine/equity/calculator.py::_holding_rw_expr` |
| `SF001` | `ERROR_SME_MISSING_COUNTERPARTY_REF` | Supporting Factors | SME supporting-factor application requires a `counterparty_reference` and none was supplied |
| `RE005` | `ERROR_RE_NO_PROPERTY_EVIDENCE` | Real Estate | **WARNING**, one roll-up per run. Exposures whose real-estate class rests on a mortgage `product_type` alone — no `real_estate` collateral linked at any level and no LTV (collateral `property_ltv` or loan `ltv`). A product label is not "a charge on immovable property" (PS1/26 Glossary; CRR Art. 125(1)), so no preferential real-estate weight is given: a Standardised-Approach exposure takes its counterparty's class, an IRB exposure keeps its IRB class with a counterparty-class Standardised-equivalent (output-floor) weight. Emitted by `engine/classify/audit.py::collect_classified_frame_warnings` |
| `RE006` | `ERROR_RE_LTV_DERIVED` | Real Estate | **WARNING**, one roll-up per run. `property_ltv` was not supplied for a linked, valued property, so the LTV was derived as (drawn + accrued interest + undrawn committed amount) / market value + `prior_charge_ltv` (PS1/26 Art. 124C(1)-(3); the conservative bound for CRR Art. 125(2)(d) / 126(2)(d)) by `engine/hierarchy/re_ltv.py`. Supply `property_ltv` to use the firm's own figure |
| `CFG001` | `ERROR_INVALID_CONFIG` | Configuration | Invalid configuration parameter |
| `CFG002` | `ERROR_MISSING_PERMISSION` | Configuration | Required IRB permission not granted |
| `CFG003` | `ERROR_EQUITY_TRANSITIONAL_CONFIG` | Configuration | Equity transitional (PS1/26 General Provisions rules 4.1–4.10) not applied as configured: a firm with IRB permission on 31 Dec 2026 receives the Art. 133 weights because rules 4.5–4.6 are not implemented, or `opt_out` was set by a firm with no rule 4.9 election (warning) |
| `BR001` | `ERROR_UNKNOWN_BRANCH_FALLBACK` | Branch Reason | **WARNING.** A row whose `*_branch_reason` column reads `UNKNOWN_FALLBACK`: the branch it was priced on could not be justified, either because the deciding predicate evaluated to **null** (Polars sends both `False` and `null` to `otherwise`, so the row took a fallback the engine never chose) or because a value was substituted for input that was simply absent. WARNING rather than ERROR deliberately — such a row is *unjustified*, not provably wrong, and an ERROR would redden every run touching a known-open defect until someone switched the gate off. Emitted at the pipeline exit by `contracts/validation.py::validate_branch_reasons`, which folds into the collect `validate_aggregated_bundle` already pays for. The population is ratcheted by `scripts/check_branch_census.py` |

#### Error Factory Functions

Convenience functions for creating common error types:

```python
def missing_field_error(
    field_name: str,
    exposure_reference: str | None = None,
    regulatory_reference: str | None = None,
) -> CalculationError:
    """Create a DQ001 missing field error."""

def invalid_value_error(
    field_name: str,
    actual_value: str,
    expected_value: str,
    exposure_reference: str | None = None,
    regulatory_reference: str | None = None,
) -> CalculationError:
    """Create a DQ002 invalid value error."""

def business_rule_error(
    code: str,
    message: str,
    exposure_reference: str | None = None,
    regulatory_reference: str | None = None,
    severity: ErrorSeverity = ErrorSeverity.ERROR,
) -> CalculationError:
    """Create a business rule violation error with custom code and severity."""

def hierarchy_error(
    code: str,
    message: str,
    exposure_reference: str | None = None,
    counterparty_reference: str | None = None,
) -> CalculationError:
    """Create a hierarchy-related error (HIE001-HIE003)."""

def crm_warning(
    code: str,
    message: str,
    exposure_reference: str | None = None,
    regulatory_reference: str | None = None,
) -> CalculationError:
    """Create a CRM-related warning (severity=WARNING, category=CRM)."""
```

---

## Protocols

### Module: `rwa_calc.contracts.protocols`

All pipeline components implement structural `Protocol` interfaces (PEP 544). This means
any class with the right method signatures satisfies the protocol — no inheritance required.
All protocols are `@runtime_checkable`.

**Why protocols over ABCs:** Protocols enable structural (duck) typing. A test mock that
implements `calculate()` with the right signature automatically satisfies
`SACalculatorProtocol` without inheriting from it. This makes testing and alternative
implementations frictionless.

### Pipeline Stage Protocols

#### `LoaderProtocol`

```python
class LoaderProtocol(Protocol):
    def load(self) -> RawDataBundle:
        """Load all required data and return as a RawDataBundle."""
        ...
```

#### `HierarchyResolverProtocol`

```python
class HierarchyResolverProtocol(Protocol):
    def resolve(
        self,
        data: RawDataBundle,
        config: CalculationConfig,
    ) -> ResolvedHierarchyBundle:
        """Resolve all hierarchies and return enriched data."""
        ...
```

#### `ClassifierProtocol`

```python
class ClassifierProtocol(Protocol):
    def classify(
        self,
        data: ResolvedHierarchyBundle,
        config: CalculationConfig,
    ) -> ClassifiedExposuresBundle:
        """Classify exposures and split by approach."""
        ...
```

#### `CRMProcessorProtocol`

```python
class CRMProcessorProtocol(Protocol):
    def get_crm_unified_bundle(
        self,
        data: ClassifiedExposuresBundle,
        config: CalculationConfig,
    ) -> CRMAdjustedBundle:
        """Apply CRM and return the unified bundle (no approach split).
        Errors accumulate on CRMAdjustedBundle.crm_errors."""
        ...
```

### Calculator Protocols

Calculator protocols provide `calculate_branch()` for pre-filtered rows, with an
optional `errors=` accumulator (the branch-path error channel — the pipeline merges
accumulated warnings into the result bundle with their original codes). SA additionally
provides `calculate_unified()` for the Basel 3.1 output floor (which needs SA-equivalent
risk weights on all rows in a single pass).

#### `SACalculatorProtocol`

```python
class SACalculatorProtocol(Protocol):
    def calculate_unified(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
        *,
        errors: list[CalculationError] | None = None,
    ) -> pl.LazyFrame:
        """Apply SA risk weights on unified frame (single-pass pipeline)."""
        ...

    def calculate_branch(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
        *,
        errors: list[CalculationError] | None = None,
    ) -> pl.LazyFrame:
        """Calculate SA RWA on pre-filtered SA-only rows."""
        ...
```

#### `IRBCalculatorProtocol`

```python
class IRBCalculatorProtocol(Protocol):
    def calculate_branch(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
        *,
        errors: list[CalculationError] | None = None,
    ) -> pl.LazyFrame:
        """Calculate IRB RWA on pre-filtered IRB-only rows
        (expected loss columns included in the output)."""
        ...
```

#### `SlottingCalculatorProtocol`

```python
class SlottingCalculatorProtocol(Protocol):
    def calculate_branch(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
        *,
        errors: list[CalculationError] | None = None,
    ) -> pl.LazyFrame:
        """Calculate slotting RWA on pre-filtered slotting-only rows."""
        ...
```

#### `EquityCalculatorProtocol`

```python
class EquityCalculatorProtocol(Protocol):
    def get_equity_result_bundle(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> EquityResultBundle:
        """Calculate equity RWA and return as bundle."""
        ...
```

#### `OutputAggregatorProtocol`

```python
class OutputAggregatorProtocol(Protocol):
    def aggregate(
        self,
        sa_results: pl.LazyFrame,
        irb_results: pl.LazyFrame,
        slotting_results: pl.LazyFrame,
        equity_bundle: EquityResultBundle | None,
        config: CalculationConfig,
        securitisation_audit: pl.LazyFrame | None = None,
    ) -> AggregatedResultBundle:
        """Aggregate calculator outputs into the final result bundle
        (output floor, supporting-factor impact, summaries)."""
        ...
```

### Orchestration Protocols

#### `PipelineProtocol`

```python
class PipelineProtocol(Protocol):
    def run(self, config: CalculationConfig) -> AggregatedResultBundle:
        """Execute the complete RWA calculation pipeline."""
        ...

    def run_with_data(
        self,
        data: RawDataBundle,
        config: CalculationConfig,
    ) -> AggregatedResultBundle:
        """Execute pipeline with pre-loaded data."""
        ...
```

#### `ComparisonRunnerProtocol`

```python
class ComparisonRunnerProtocol(Protocol):
    def compare(
        self,
        data: RawDataBundle,
        crr_config: CalculationConfig,
        b31_config: CalculationConfig,
    ) -> ComparisonBundle:
        """Run both frameworks on the same data and produce comparison."""
        ...
```

#### `CapitalImpactAnalyzerProtocol`

```python
class CapitalImpactAnalyzerProtocol(Protocol):
    def analyze(
        self,
        comparison: ComparisonBundle,
    ) -> CapitalImpactBundle:
        """Decompose comparison deltas into driver-level attribution."""
        ...
```

### Validation and Export Protocols

#### `SchemaValidatorProtocol`

```python
class SchemaValidatorProtocol(Protocol):
    def validate(
        self,
        lf: pl.LazyFrame,
        expected_schema: dict[str, pl.DataType],
        context: str,
    ) -> list[str]:
        """Validate LazyFrame schema against expected schema.
        Returns list of error messages (empty if valid)."""
        ...
```

#### `DataQualityCheckerProtocol`

```python
class DataQualityCheckerProtocol(Protocol):
    def check(
        self,
        data: RawDataBundle,
        config: CalculationConfig,
    ) -> list:
        """Run data quality checks on raw data.
        Returns list of CalculationError for any issues found."""
        ...
```

#### `ResultExporterProtocol`

```python
class ResultExporterProtocol(Protocol):
    def export_to_parquet(
        self,
        response: CalculationResponse,
        output_dir: Path,
    ) -> ExportResult:
        """Export results to Parquet files."""
        ...

    def export_to_csv(
        self,
        response: CalculationResponse,
        output_dir: Path,
    ) -> ExportResult:
        """Export results to CSV files."""
        ...

    def export_to_excel(
        self,
        response: CalculationResponse,
        output_path: Path,
    ) -> ExportResult:
        """Export results to a multi-sheet Excel workbook."""
        ...
```

---

## Related

- [Domain API](domain.md) — enums used by contracts (`ErrorSeverity`, `ErrorCategory`, etc.)
- [Engine API](engine.md) — implementations of these protocols
- [Configuration API](configuration.md) — `CalculationConfig` referenced by all protocols
- [Architecture - Design Principles](../architecture/design-principles.md)
