# Output Schemas

This page documents the schemas for calculation results and output data produced by each
calculator and the final aggregated output.

> **Source of truth**: All schemas are defined in `src/rwa_calc/data/schemas.py`.
> Result bundles are defined in `src/rwa_calc/contracts/bundles.py`.

## SA Result Schema

Results from Standardised Approach calculation. Each exposure gets a risk weight looked up
from regulatory tables by exposure class and CQS, then RWA = EAD × risk weight.

**Source**: `SA_RESULT_SCHEMA` in `data/schemas.py`

| Column | Type | Description |
|--------|------|-------------|
| `exposure_reference` | `String` | Exposure identifier |
| `exposure_class` | `String` | Regulatory exposure class |
| `final_ead` | `Float64` | Exposure at default (from CRM stage) |
| `sa_cqs` | `Int8` | Credit Quality Step used (1–6, 0 = unrated) |
| `sa_base_risk_weight` | `Float64` | Base RW from regulatory lookup table |
| `sa_rw_adjustment` | `Float64` | Any adjustments applied (e.g., defaulted uplift) |
| `sa_rw_adjustment_reason` | `String` | Reason for adjustment |
| `sa_final_risk_weight` | `Float64` | Final SA risk weight |
| `sa_rw_regulatory_ref` | `String` | CRR article or CRE reference |
| `sa_rwa` | `Float64` | `final_ead × sa_final_risk_weight` |

## IRB Result Schema

Results from IRB approach calculation (F-IRB and A-IRB). Includes the full IRB formula
breakdown: PD → LGD → correlation → capital requirement K → maturity adjustment → RWA.

**Source**: `IRB_RESULT_SCHEMA` in `data/schemas.py`

| Column | Type | Description |
|--------|------|-------------|
| `exposure_reference` | `String` | Exposure identifier |
| `exposure_class` | `String` | Regulatory exposure class |
| `final_ead` | `Float64` | Exposure at default |
| `irb_pd_original` | `Float64` | PD before flooring |
| `irb_pd_floor` | `Float64` | Applicable PD floor |
| `irb_pd_floored` | `Float64` | `max(pd_original, pd_floor)` |
| `irb_lgd_type` | `String` | `"supervisory"` (F-IRB) or `"modelled"` (A-IRB) |
| `irb_lgd_original` | `Float64` | LGD before flooring |
| `irb_lgd_floor` | `Float64` | Applicable LGD floor (Basel 3.1 only) |
| `irb_lgd_floored` | `Float64` | `max(lgd_original, lgd_floor)` |
| `irb_maturity_m` | `Float64` | Effective maturity in years |
| `irb_correlation_r` | `Float64` | Asset correlation from formula |
| `irb_maturity_adj_b` | `Float64` | Maturity adjustment factor `b` |
| `irb_capital_k` | `Float64` | Capital requirement K |
| `irb_scaling_factor` | `Float64` | 1.06 (CRR) or 1.0 (Basel 3.1) |
| `irb_risk_weight` | `Float64` | `12.5 × K × scaling_factor` |
| `irb_rwa` | `Float64` | `final_ead × irb_risk_weight` |
| `irb_expected_loss` | `Float64` | `PD × LGD × EAD` |

## Slotting Result Schema

Results from slotting approach calculation for specialised lending. Risk weights are
assigned by supervisory category, lending type, and (under CRR) remaining maturity.

**Source**: `SLOTTING_RESULT_SCHEMA` in `data/schemas.py`

| Column | Type | Description |
|--------|------|-------------|
| `exposure_reference` | `String` | Exposure identifier |
| `sl_type` | `String` | Specialised lending type (see Specialised Lending Schema) |
| `slotting_category` | `String` | `strong`/`good`/`satisfactory`/`weak`/`default` |
| `remaining_maturity_years` | `Float64` | Remaining maturity (CRR maturity-band differentiation) |
| `is_hvcre` | `Boolean` | High Volatility CRE indicator |
| `sl_base_risk_weight` | `Float64` | Base slotting risk weight |
| `sl_maturity_adjusted_rw` | `Float64` | RW after maturity-band adjustment (CRR) |
| `sl_final_risk_weight` | `Float64` | Final slotting risk weight |
| `sl_rwa` | `Float64` | `final_ead × sl_final_risk_weight` |

## Calculation Output Schema

The master output schema covering all exposure-level results with full audit trail.
Designed so that users can investigate why results occurred and replicate calculations
from the output data alone.

**Source**: `CALCULATION_OUTPUT_SCHEMA` in `data/schemas.py`

### Identification and lineage

| Column | Type | Description |
|--------|------|-------------|
| `calculation_run_id` | `String` | Unique run identifier for audit trail |
| `calculation_timestamp` | `Datetime` | When calculation was performed |
| `exposure_reference` | `String` | Links to source loan/facility/contingent |
| `exposure_type` | `String` | `"loan"`, `"facility"`, `"contingent"` |
| `counterparty_reference` | `String` | Links to counterparty |
| `book_code` | `String` | Portfolio/book classification |
| `currency` | `String` | Exposure currency |
| `model_id` | `String` | IRB model identifier (for model-level permission audit trail) |
| `basel_version` | `String` | `"3.0"` or `"3.1"` |

### Counterparty hierarchy (rating inheritance)

| Column | Type | Description |
|--------|------|-------------|
| `counterparty_has_parent` | `Boolean` | Whether counterparty is part of org hierarchy |
| `parent_counterparty_reference` | `String` | Immediate parent in org structure |
| `ultimate_parent_reference` | `String` | Top-level parent |
| `counterparty_hierarchy_depth` | `Int8` | Levels from ultimate parent (0 = top) |
| `rating_inherited` | `Boolean` | Whether rating came from parent |
| `rating_source_counterparty` | `String` | Counterparty whose rating was used |
| `rating_inheritance_reason` | `String` | `"own_rating"`, `"parent_rating"`, etc. |

### Lending group hierarchy (retail threshold)

| Column | Type | Description |
|--------|------|-------------|
| `lending_group_reference` | `String` | Lending group parent if applicable |
| `lending_group_total_exposure` | `Float64` | Aggregated exposure across group |
| `retail_threshold_applied` | `Float64` | £1m (CRR) or £880k (Basel 3.1) |
| `retail_eligible_via_group` | `Boolean` | Whether retail classification based on group |

### Exposure hierarchy (facility structure)

| Column | Type | Description |
|--------|------|-------------|
| `exposure_has_parent` | `Boolean` | Whether exposure is child of a facility |
| `parent_facility_reference` | `String` | Parent facility reference |
| `root_facility_reference` | `String` | Top-level facility in hierarchy |
| `facility_hierarchy_depth` | `Int8` | Levels from root facility |
| `facility_hierarchy_path` | `List(String)` | Full path from root to this exposure |

### CRM inheritance (from hierarchy)

| Column | Type | Description |
|--------|------|-------------|
| `collateral_source_level` | `String` | `"exposure"`, `"facility"`, `"counterparty"` |
| `collateral_inherited_from` | `String` | Reference of entity collateral inherited from |
| `collateral_allocation_method` | `String` | `"direct"`, `"pro_rata"`, `"waterfall"`, `"optimised"` |
| `guarantee_source_level` | `String` | `"exposure"`, `"facility"`, `"counterparty"` |
| `guarantee_inherited_from` | `String` | Reference of entity guarantee inherited from |
| `provision_source_level` | `String` | `"exposure"`, `"facility"`, `"counterparty"` |
| `provision_inherited_from` | `String` | Reference of entity provision inherited from |
| `crm_allocation_notes` | `String` | Explanation of how CRM was allocated |

### Exposure classification

| Column | Type | Description |
|--------|------|-------------|
| `exposure_class` | `String` | Determined regulatory class |
| `exposure_class_reason` | `String` | Explanation of classification decision |
| `approach_permitted` | `String` | `"standardised"`, `"foundation_irb"`, `"advanced_irb"` based on permissions |
| `approach_applied` | `String` | Actual approach used |
| `approach_selection_reason` | `String` | Why this approach was selected |

### Original exposure values

| Column | Type | Description |
|--------|------|-------------|
| `drawn_amount` | `Float64` | Original drawn balance |
| `undrawn_amount` | `Float64` | Undrawn commitment amount |
| `original_maturity_date` | `Date` | Contractual maturity |
| `residual_maturity_years` | `Float64` | Years to maturity |

### CCF application (off-balance sheet conversion)

| Column | Type | Description |
|--------|------|-------------|
| `ccf_applied` | `Float64` | CCF percentage (0%, 20%, 40%, 50%, 100%) |
| `ccf_source` | `String` | Reference to regulatory article |
| `converted_undrawn` | `Float64` | `undrawn_amount × ccf_applied` |

### CRM — collateral impact

| Column | Type | Description |
|--------|------|-------------|
| `collateral_references` | `List(String)` | IDs of collateral items used |
| `collateral_types` | `List(String)` | Types of collateral |
| `collateral_gross_value` | `Float64` | Total market value before haircuts |
| `collateral_haircut_applied` | `Float64` | Weighted average haircut percentage |
| `fx_haircut_applied` | `Float64` | FX mismatch haircut (8% or 0%) |
| `maturity_mismatch_adjustment` | `Float64` | Adjustment for maturity mismatch |
| `collateral_adjusted_value` | `Float64` | Net collateral value after haircuts |

### CRM — guarantee impact (substitution approach)

| Column | Type | Description |
|--------|------|-------------|
| `guarantee_references` | `List(String)` | IDs of guarantees used |
| `guarantor_references` | `List(String)` | Guarantor counterparty IDs |
| `guarantee_coverage_pct` | `Float64` | Percentage of exposure guaranteed |
| `guaranteed_amount` | `Float64` | Amount covered by guarantee |
| `guarantor_risk_weight` | `Float64` | RW of guarantor (for substitution) |
| `guarantee_benefit` | `Float64` | RWA reduction from guarantee |

### Pre/post CRM counterparty tracking

| Column | Type | Description |
|--------|------|-------------|
| `pre_crm_counterparty_reference` | `String` | Original borrower reference |
| `pre_crm_exposure_class` | `String` | Original exposure class |
| `post_crm_counterparty_guaranteed` | `String` | Guarantor reference for guaranteed portion |
| `post_crm_exposure_class_guaranteed` | `String` | Derived from guarantor's entity_type |
| `guarantor_reference` | `String` | Foreign key to guarantor data |
| `is_guaranteed` | `Boolean` | Whether exposure has effective guarantee |
| `guaranteed_portion` | `Float64` | EAD covered by guarantee |
| `unguaranteed_portion` | `Float64` | EAD not covered |
| `pre_crm_risk_weight` | `Float64` | Borrower's RW before substitution |
| `guarantee_benefit_rw` | `Float64` | RW reduction from guarantee |
| `rwa_irb_original` | `Float64` | IRB RWA before guarantee substitution |
| `risk_weight_irb_original` | `Float64` | IRB RW before guarantee substitution |
| `guarantee_method_used` | `String` | `"SA_RW_SUBSTITUTION"`, `"PD_SUBSTITUTION"`, or `"NO_GUARANTEE"` |
| `guarantee_status` | `String` | Detailed status |

### CRM — provision impact

| Column | Type | Description |
|--------|------|-------------|
| `provision_references` | `List(String)` | IDs of provisions applied |
| `scra_provision_amount` | `Float64` | Specific provisions |
| `gcra_provision_amount` | `Float64` | General provisions |
| `provision_capped_amount` | `Float64` | Amount eligible for CRM |

### EAD calculation

| Column | Type | Description |
|--------|------|-------------|
| `gross_ead` | `Float64` | `drawn + converted_undrawn` |
| `ead_after_collateral` | `Float64` | After collateral CRM |
| `ead_after_guarantee` | `Float64` | Portion not guaranteed |
| `final_ead` | `Float64` | Final EAD for RWA calculation |
| `ead_calculation_method` | `String` | `"simple"`, `"comprehensive"`, `"supervisory_haircut"` |

### Risk weight determination — SA

| Column | Type | Description |
|--------|------|-------------|
| `sa_cqs` | `Int8` | Credit Quality Step (1–6, 0 = unrated) |
| `sa_rating_source` | `String` | Rating agency or `"internal"` |
| `sa_base_risk_weight` | `Float64` | Base RW from lookup table |
| `sa_rw_adjustment` | `Float64` | Adjustments applied |
| `sa_rw_adjustment_reason` | `String` | Reason for adjustment |
| `sa_final_risk_weight` | `Float64` | Final SA risk weight |
| `sa_rw_regulatory_ref` | `String` | CRR article or CRE reference |

### Risk weight determination — IRB

| Column | Type | Description |
|--------|------|-------------|
| `irb_pd_original` | `Float64` | PD before flooring |
| `irb_pd_floor` | `Float64` | Applicable PD floor |
| `irb_pd_floored` | `Float64` | `max(pd_original, pd_floor)` |
| `irb_lgd_type` | `String` | `"supervisory"` (F-IRB) or `"modelled"` (A-IRB) |
| `irb_lgd_original` | `Float64` | LGD before flooring |
| `irb_lgd_floor` | `Float64` | LGD floor (Basel 3.1) |
| `irb_lgd_floored` | `Float64` | `max(lgd_original, lgd_floor)` |
| `irb_maturity_m` | `Float64` | Effective maturity (M) |
| `irb_correlation_r` | `Float64` | Asset correlation |
| `irb_maturity_adj_b` | `Float64` | Maturity adjustment factor |
| `irb_capital_k` | `Float64` | Capital requirement (K) |
| `irb_risk_weight` | `Float64` | `12.5 × K × scaling_factor` |

### Specialised lending and equity

| Column | Type | Description |
|--------|------|-------------|
| `sl_type` | `String` | SL category if applicable |
| `sl_slotting_category` | `String` | `strong`/`good`/`satisfactory`/`weak`/`default` |
| `sl_risk_weight` | `Float64` | Slotting RW |
| `equity_type` | `String` | Equity category if applicable |
| `equity_risk_weight` | `Float64` | Equity RW |

### Real estate specific

| Column | Type | Description |
|--------|------|-------------|
| `property_type` | `String` | `"residential"` / `"commercial"` |
| `property_ltv` | `Float64` | Loan-to-value ratio |
| `ltv_band` | `String` | LTV band for RW lookup |
| `is_income_producing` | `Boolean` | CRE income flag |
| `is_adc` | `Boolean` | ADC exposure flag |
| `mortgage_risk_weight` | `Float64` | LTV-based RW |

### Final RWA calculation

| Column | Type | Description |
|--------|------|-------------|
| `rwa_before_floor` | `Float64` | `EAD × RW` (before output floor) |
| `sa_equivalent_rwa` | `Float64` | SA RWA for floor comparison |
| `output_floor_pct` | `Float64` | Floor percentage (72.5% for Basel 3.1) |
| `output_floor_rwa` | `Float64` | `sa_equivalent_rwa × floor_pct` |
| `floor_binding` | `Boolean` | Whether floor increased RWA |
| `floor_impact` | `Float64` | Additional RWA from floor |
| `final_rwa` | `Float64` | `max(rwa_before_floor, output_floor_rwa)` |
| `risk_weight_effective` | `Float64` | `final_rwa / final_ead` (implied RW) |

### Expected loss (IRB)

| Column | Type | Description |
|--------|------|-------------|
| `irb_expected_loss` | `Float64` | `PD × LGD × EAD` |
| `provision_held` | `Float64` | Total provision amount |
| `el_shortfall` | `Float64` | `max(0, EL − provision)` |
| `el_excess` | `Float64` | `max(0, provision − EL)` |

### Supporting factors (CRR only)

| Column | Type | Description |
|--------|------|-------------|
| `sme_supporting_factor` | `Float64` | SME factor (0.7619/0.85), CRR only |
| `infra_supporting_factor` | `Float64` | Infrastructure factor (0.75), CRR only |
| `supporting_factor_benefit` | `Float64` | RWA reduction from factors |

### Warnings and validation

| Column | Type | Description |
|--------|------|-------------|
| `calculation_warnings` | `List(String)` | Issues or assumptions made during calculation |
| `data_quality_flags` | `List(String)` | Missing or imputed values |

## Framework-Specific Output Additions

### CRR (Basel 3.0) additions

**Source**: `CRR_OUTPUT_SCHEMA_ADDITIONS` in `data/schemas.py`

| Column | Type | Description |
|--------|------|-------------|
| `regulatory_framework` | `String` | `"CRR"` |
| `crr_effective_date` | `Date` | Regulation effective date |
| `sme_supporting_factor_eligible` | `Boolean` | Turnover < EUR 50m |
| `sme_supporting_factor_applied` | `Boolean` | Whether factor was applied |
| `sme_supporting_factor_value` | `Float64` | 0.7619 |
| `rwa_before_sme_factor` | `Float64` | RWA before SME factor |
| `rwa_sme_factor_benefit` | `Float64` | RWA reduction from SME factor |
| `infrastructure_factor_eligible` | `Boolean` | Qualifies as infrastructure |
| `infrastructure_factor_applied` | `Boolean` | Whether factor was applied |
| `infrastructure_factor_value` | `Float64` | 0.75 |
| `rwa_infrastructure_factor_benefit` | `Float64` | RWA reduction |
| `crr_exposure_class` | `String` | CRR-specific classification |
| `crr_exposure_subclass` | `String` | Sub-classification where applicable |
| `crr_mortgage_treatment` | `String` | `"35_pct"` or `"split_treatment"` |
| `crr_mortgage_ltv_threshold` | `Float64` | 80% LTV threshold |
| `crr_pd_floor` | `Float64` | 0.03% single floor |
| `crr_airb_lgd_floor_applied` | `Boolean` | Always `False` under CRR (per-exposure floors not applicable; CRR Art. 164(4) portfolio-level floors are not implemented — see D3.38) |

### Basel 3.1 (PRA PS1/26) additions

**Source**: `BASEL31_OUTPUT_SCHEMA_ADDITIONS` in `data/schemas.py`

| Column | Type | Description |
|--------|------|-------------|
| `regulatory_framework` | `String` | `"BASEL_3_1"` |
| `b31_effective_date` | `Date` | 1 January 2027 |
| `output_floor_applicable` | `Boolean` | Whether floor applies |
| `output_floor_percentage` | `Float64` | 72.5% (fully phased in) |
| `rwa_irb_unrestricted` | `Float64` | IRB RWA before floor |
| `rwa_sa_equivalent` | `Float64` | Parallel SA calculation |
| `rwa_floor_amount` | `Float64` | `sa_equivalent × floor_pct` |
| `rwa_floor_impact` | `Float64` | Additional RWA from floor |
| `is_floor_binding` | `Boolean` | Whether floor increased RWA |
| `b31_ltv_band` | `String` | LTV band (e.g., `"0-50%"`, `"50-60%"`) |
| `b31_ltv_band_rw` | `Float64` | Risk weight for LTV band (20%–70%) |
| `b31_pd_floor_class` | `String` | Exposure class for PD floor |
| `b31_pd_floor_value` | `Float64` | 0.03%/0.05%/0.10% by class |
| `b31_pd_floor_binding` | `Boolean` | Whether PD floor was binding |
| `b31_lgd_floor_class` | `String` | Classification for LGD floor |
| `b31_lgd_floor_value` | `Float64` | 0%/5%/10%/15%/25% by collateral |
| `b31_lgd_floor_binding` | `Boolean` | Whether LGD floor was binding |
| `b31_sme_factor_note` | `String` | `"Not available under Basel 3.1"` |

## Result Bundles

### `AggregatedResultBundle`

The final result from the output aggregator. Combines SA, IRB, slotting, and equity results
with output floor application and supporting factor adjustments.

**Source**: `AggregatedResultBundle` in `contracts/bundles.py`

```python
@dataclass(frozen=True)
class AggregatedResultBundle:
    """Final aggregated output from the output aggregator."""

    results: pl.LazyFrame                               # Final RWA results
    sa_results: pl.LazyFrame | None = None               # Original SA results
    irb_results: pl.LazyFrame | None = None              # Original IRB results
    slotting_results: pl.LazyFrame | None = None         # Original slotting results
    equity_results: pl.LazyFrame | None = None           # Equity results
    floor_impact: pl.LazyFrame | None = None             # Output floor impact analysis
    supporting_factor_impact: pl.LazyFrame | None = None # Supporting factor impact (CRR)
    summary_by_class: pl.LazyFrame | None = None         # RWA by exposure class
    summary_by_approach: pl.LazyFrame | None = None      # RWA by approach
    pre_crm_summary: pl.LazyFrame | None = None          # Gross view by original class
    post_crm_detailed: pl.LazyFrame | None = None        # Split rows for guarantees
    post_crm_summary: pl.LazyFrame | None = None         # Net view by effective class
    el_summary: ELPortfolioSummary | None = None          # EL summary with T2 credit cap
    errors: list = field(default_factory=list)            # All pipeline errors
```

### `ELPortfolioSummary`

Portfolio-level expected loss summary with T2 credit cap (CRR Art. 62(d)).

```python
@dataclass(frozen=True)
class ELPortfolioSummary:
    total_expected_loss: float        # Sum of EL across IRB exposures
    total_provisions_allocated: float # Sum of provisions allocated to IRB
    total_el_shortfall: float         # Sum of max(0, EL − provisions) per exposure
    total_el_excess: float            # Sum of max(0, provisions − EL) per exposure
    total_irb_rwa: float              # Total IRB RWA (denominator for T2 cap)
    t2_credit_cap: float              # 0.6% of total IRB RWA
    t2_credit: float                  # min(total_el_excess, t2_credit_cap)
    cet1_deduction: float             # 100% of total_el_shortfall (Art. 36(1)(d))
    t2_deduction: float               # Always zero (no T2 deduction for shortfall)
```

### Other result bundles

| Bundle | Key fields | Description |
|--------|-----------|-------------|
| `SAResultBundle` | `results`, `calculation_audit`, `errors` | SA calculator output |
| `IRBResultBundle` | `results`, `expected_loss`, `calculation_audit`, `errors` | IRB calculator output |
| `SlottingResultBundle` | `results`, `calculation_audit`, `errors` | Slotting calculator output |
| `EquityResultBundle` | `results`, `calculation_audit`, `approach`, `errors` | Equity calculator output |
| `ComparisonBundle` | `crr_results`, `b31_results`, `exposure_deltas`, summaries | Dual-framework comparison |
| `TransitionalScheduleBundle` | `timeline`, `yearly_results`, `errors` | Year-by-year floor impact |
| `CapitalImpactBundle` | `exposure_attribution`, `portfolio_waterfall`, summaries | RWA delta decomposition |

## Export Formats

### Parquet

```python
result.results.collect().write_parquet("rwa_results.parquet")
```

Full precision, efficient compression, schema preservation.

### CSV

```python
result.results.collect().write_csv("rwa_results.csv")
```

Human-readable, Excel-compatible.

### Excel (via API export module)

```python
from rwa_calc.api.export import ResultExporter

exporter = ResultExporter(result)
exporter.to_excel("rwa_results.xlsx")
```

## Next Steps

- [Regulatory Tables](regulatory-tables.md)
- [API Reference](../api/index.md)
- [Configuration Guide](../user-guide/configuration.md)
