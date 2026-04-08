# Comparison & Impact Analysis

The RWA Calculator supports dual-framework comparison, capital impact attribution, and
transitional floor schedule modelling. These features help firms prepare for the CRR to Basel 3.1
transition by quantifying the impact on their credit risk capital requirements.

## Why Comparison Matters

UK firms must operate under both CRR (until 31 Dec 2026) and Basel 3.1 (from 1 Jan 2027)
during the transition period. Understanding the RWA impact at exposure, portfolio, and
timeline levels is essential for capital planning, board reporting, and ICAAP stress testing.
The comparison module runs both frameworks against the same portfolio from a single codebase,
ensuring consistent methodology and eliminating reconciliation issues.

## Dual-Framework Comparison (M3.1)

`DualFrameworkRunner` runs the same portfolio through both CRR and Basel 3.1 pipelines and
joins the results on `exposure_reference`.

### Usage

```python
from datetime import date
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.comparison import DualFrameworkRunner

runner = DualFrameworkRunner()

crr_config = CalculationConfig.crr(reporting_date=date(2026, 12, 31))
b31_config = CalculationConfig.basel_3_1(reporting_date=date(2030, 6, 30))

comparison = runner.compare(data, crr_config, b31_config)
```

### Output: `ComparisonBundle`

| Field | Type | Description |
|-------|------|-------------|
| `crr_results` | `AggregatedResultBundle` | Full CRR calculation results |
| `b31_results` | `AggregatedResultBundle` | Full Basel 3.1 calculation results |
| `exposure_deltas` | `pl.LazyFrame` | Per-exposure delta analysis |
| `summary_by_class` | `pl.LazyFrame` | Aggregated deltas by exposure class |
| `summary_by_approach` | `pl.LazyFrame` | Aggregated deltas by calculation approach |
| `errors` | `list` | Combined errors from both runs |

### Exposure Deltas

The `exposure_deltas` LazyFrame contains per-exposure comparison columns:

| Column | Description |
|--------|-------------|
| `exposure_reference` | Unique exposure identifier |
| `exposure_class` | Coalesced from CRR then B31 |
| `approach_applied` | Coalesced from CRR then B31 |
| `rwa_final_crr` | RWA under CRR |
| `rwa_final_b31` | RWA under Basel 3.1 |
| `delta_rwa` | `rwa_final_b31 - rwa_final_crr` |
| `delta_rwa_pct` | Percentage change from CRR to B31 |
| `delta_risk_weight` | Risk weight change |
| `delta_ead` | EAD change |

**Delta convention:** Positive delta = Basel 3.1 is higher (increased capital).

The join uses a full outer join, so exposures unique to one framework (e.g., equity exposures
removed from IRB under Basel 3.1) still appear with nulls filled to 0.0.

## Capital Impact Analysis (M3.2)

`CapitalImpactAnalyzer` decomposes the RWA delta into four regulatory drivers using a
sequential waterfall methodology. The four drivers sum exactly to the total delta.

### Usage

```python
from rwa_calc.engine.comparison import CapitalImpactAnalyzer

analyzer = CapitalImpactAnalyzer()
impact = analyzer.analyze(comparison)
```

### Waterfall Drivers

The waterfall applies sequentially, with each driver capturing a specific regulatory change:

| Step | Driver | Direction | Applies To |
|------|--------|-----------|------------|
| 1 | **Scaling factor removal** | Negative | IRB only |
| 2 | **Supporting factor removal** | Positive | SA and IRB |
| 3 | **Methodology & parameter changes** | Varies | All |
| 4 | **Output floor impact** | Positive | IRB only |

**Step 1 — Scaling factor removal (1.06x):** CRR multiplies IRB capital by 1.06. Basel 3.1
removes this. Always negative for IRB exposures, zero for SA.

**Step 2 — Supporting factor removal:** CRR applies SME (0.7619/0.85) and infrastructure
(0.75) factors as RWA discounts. Basel 3.1 removes them. Typically positive (removing the
discount increases RWA).

**Step 3 — Methodology & parameter changes:** The residual after accounting for the other
three drivers. Captures PD/LGD floor changes, SA risk weight table revisions, F-IRB
supervisory LGD changes, correlation formula updates, and all other rule differences.

**Step 4 — Output floor impact:** Basel 3.1 floors IRB RWA at a percentage of SA RWA.
Additional RWA from the floor binding. Zero for SA exposures.

### Additivity Invariant

For every exposure:

```
scaling_factor_impact + supporting_factor_impact + output_floor_impact + methodology_impact == delta_rwa
```

This invariant is enforced by computing the methodology impact as the residual.

### Output: `CapitalImpactBundle`

| Field | Type | Description |
|-------|------|-------------|
| `exposure_attribution` | `pl.LazyFrame` | Per-exposure driver decomposition |
| `portfolio_waterfall` | `pl.LazyFrame` | 4-row waterfall with cumulative RWA |
| `summary_by_class` | `pl.LazyFrame` | Driver totals by exposure class |
| `summary_by_approach` | `pl.LazyFrame` | Driver totals by calculation approach |
| `errors` | `list` | Propagated from comparison |

### Portfolio Waterfall

The `portfolio_waterfall` LazyFrame has 4 rows:

| Column | Description |
|--------|-------------|
| `step` | Step number (1–4) |
| `driver` | Human-readable driver label |
| `impact_rwa` | Aggregate RWA impact of this driver |
| `cumulative_rwa` | Running total from CRR baseline |

The final `cumulative_rwa` equals the total Basel 3.1 RWA.

## Transitional Floor Schedule (M3.3)

`TransitionalScheduleRunner` models the output floor phase-in from 2027 to 2030 by running
the Basel 3.1 pipeline at each transitional reporting date.

### PRA Output Floor Phase-In Schedule

| Year | Reporting Date | Floor % |
|------|---------------|---------|
| 2027 | 30 Jun 2027 | 60.0% |
| 2028 | 30 Jun 2028 | 65.0% |
| 2029 | 30 Jun 2029 | 70.0% |
| 2030 | 30 Jun 2030 | 72.5% |

### Usage

```python
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.comparison import TransitionalScheduleRunner

runner = TransitionalScheduleRunner()

schedule = runner.run(
    data=raw_data_bundle,
    permission_mode=PermissionMode.IRB,
)

# Access the timeline
timeline = schedule.timeline.collect()
print(timeline)

# Access individual year results
result_2027 = schedule.yearly_results[2027]
result_2030 = schedule.yearly_results[2030]
```

### Custom Reporting Dates

```python
from datetime import date

# Model specific dates instead of the default 4-year schedule
schedule = runner.run(
    data=raw_data_bundle,
    permission_mode=PermissionMode.IRB,
    reporting_dates=[date(2027, 12, 31), date(2030, 12, 31)],
)
```

### Output: `TransitionalScheduleBundle`

| Field | Type | Description |
|-------|------|-------------|
| `timeline` | `pl.LazyFrame` | Year-by-year floor metrics |
| `yearly_results` | `dict[int, AggregatedResultBundle]` | Full results per year |
| `errors` | `list` | Accumulated errors |

### Timeline Columns

| Column | Type | Description |
|--------|------|-------------|
| `reporting_date` | `Date` | As-of date |
| `year` | `Int32` | Calendar year |
| `floor_percentage` | `Float64` | Output floor % for that year |
| `total_rwa_pre_floor` | `Float64` | Total IRB RWA before floor |
| `total_rwa_post_floor` | `Float64` | Total RWA after floor (final regulatory) |
| `total_floor_impact` | `Float64` | Additional RWA from floor binding |
| `floor_binding_count` | `UInt32` | Exposures where floor binds |
| `total_irb_exposure_count` | `UInt32` | Total IRB exposures |
| `total_ead` | `Float64` | Total EAD |
| `total_sa_rwa` | `Float64` | Total SA-equivalent RWA (floor benchmark) |

## Regulatory References

| Reference | Topic |
|-----------|-------|
| PRA PS1/26 | UK Basel 3.1 implementation (output floor schedule) |
| CRR Art. 153(1) | 1.06 scaling factor (removed by Basel 3.1) |
| CRR Art. 501, 501a | SME and infrastructure supporting factors (removed by Basel 3.1) |
| BCBS CRE30–36 | IRB approach revisions including PD/LGD floors |
