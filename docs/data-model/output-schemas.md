# Output Schemas

This page documents the schemas for calculation results and output data.

## SA Result Schema

Results from Standardised Approach calculation.

| Column | Type | Description |
|--------|------|-------------|
| `exposure_id` | `Utf8` | Exposure identifier |
| `counterparty_id` | `Utf8` | Counterparty identifier |
| `facility_id` | `Utf8` | Facility identifier |
| `exposure_class` | `Utf8` | Regulatory exposure class |
| `ead` | `Float64` | Exposure at default |
| `cqs` | `Int32` | Credit quality step |
| `risk_weight` | `Float64` | Applied risk weight |
| `rwa_base` | `Float64` | RWA before factors |
| `sme_factor` | `Float64` | SME supporting factor |
| `infrastructure_factor` | `Float64` | Infrastructure factor |
| `rwa` | `Float64` | Final RWA |

## IRB Result Schema

Results from IRB approach calculation.

| Column | Type | Description |
|--------|------|-------------|
| `exposure_id` | `Utf8` | Exposure identifier |
| `counterparty_id` | `Utf8` | Counterparty identifier |
| `facility_id` | `Utf8` | Facility identifier |
| `exposure_class` | `Utf8` | Regulatory exposure class |
| `approach_type` | `Utf8` | FIRB or AIRB |
| `ead` | `Float64` | Exposure at default |
| `pd_input` | `Float64` | Input PD |
| `pd_floored` | `Float64` | PD after floor |
| `lgd_input` | `Float64` | Input LGD |
| `lgd_floored` | `Float64` | LGD after floor |
| `correlation` | `Float64` | Asset correlation |
| `k` | `Float64` | Capital requirement |
| `effective_maturity` | `Float64` | Effective maturity |
| `maturity_adjustment` | `Float64` | Maturity adjustment |
| `scaling_factor` | `Float64` | CRR scaling (1.06 or 1.0) |
| `rwa` | `Float64` | Risk-weighted assets |
| `expected_loss` | `Float64` | PD × LGD × EAD |

## Slotting Result Schema

Results from slotting approach calculation.

| Column | Type | Description |
|--------|------|-------------|
| `exposure_id` | `Utf8` | Exposure identifier |
| `counterparty_id` | `Utf8` | Counterparty identifier |
| `facility_id` | `Utf8` | Facility identifier |
| `lending_type` | `Utf8` | Specialised lending type |
| `slotting_category` | `Utf8` | Strong/Good/Satisfactory/Weak |
| `ead` | `Float64` | Exposure at default |
| `risk_weight` | `Float64` | Slotting risk weight |
| `infrastructure_factor` | `Float64` | Infrastructure factor |
| `rwa` | `Float64` | Risk-weighted assets |

## Aggregated Result Schema

Combined results with totals and floor adjustments.

| Column | Type | Description |
|--------|------|-------------|
| `exposure_id` | `Utf8` | Exposure identifier |
| `counterparty_id` | `Utf8` | Counterparty identifier |
| `facility_id` | `Utf8` | Facility identifier |
| `exposure_class` | `Utf8` | Regulatory exposure class |
| `approach` | `Utf8` | SA/IRB/SLOTTING |
| `ead` | `Float64` | Exposure at default |
| `provision_allocated` | `Float64` | Total provision matched to this exposure |
| `provision_on_drawn` | `Float64` | Provision absorbed by drawn amount (SA only) |
| `provision_on_nominal` | `Float64` | Provision reducing nominal before CCF (SA only) |
| `nominal_after_provision` | `Float64` | `nominal_amount - provision_on_nominal` |
| `rwa_pre_floor` | `Float64` | RWA before output floor |
| `sa_equivalent_rwa` | `Float64` | SA equivalent (for IRB) |
| `output_floor` | `Float64` | Output floor amount |
| `floor_impact` | `Float64` | Floor add-on |
| `rwa` | `Float64` | Final RWA |
| `expected_loss` | `Float64` | Expected loss (IRB) |

## Summary Result Schema

High-level summary statistics.

| Column | Type | Description |
|--------|------|-------------|
| `metric` | `Utf8` | Metric name |
| `value` | `Float64` | Metric value |

**Standard metrics:**
- `total_ead`
- `total_rwa`
- `sa_rwa`
- `irb_rwa`
- `slotting_rwa`
- `total_expected_loss`
- `floor_impact_total`
- `average_risk_weight`

## Breakdown Schemas

### By Exposure Class

| Column | Type | Description |
|--------|------|-------------|
| `exposure_class` | `Utf8` | Exposure class |
| `count` | `Int64` | Number of exposures |
| `ead` | `Float64` | Total EAD |
| `rwa` | `Float64` | Total RWA |
| `average_rw` | `Float64` | Average risk weight |

### By Approach

| Column | Type | Description |
|--------|------|-------------|
| `approach` | `Utf8` | Calculation approach |
| `count` | `Int64` | Number of exposures |
| `ead` | `Float64` | Total EAD |
| `rwa` | `Float64` | Total RWA |

### By Counterparty

| Column | Type | Description |
|--------|------|-------------|
| `counterparty_id` | `Utf8` | Counterparty |
| `counterparty_name` | `Utf8` | Name |
| `ead` | `Float64` | Total EAD |
| `rwa` | `Float64` | Total RWA |
| `average_rw` | `Float64` | Average risk weight |

## Result Bundle

The final result is wrapped in a bundle object:

```python
@dataclass(frozen=True)
class AggregatedResultBundle:
    """Final calculation results."""

    data: pl.LazyFrame           # Detailed exposure-level results
    errors: list[CalculationError]  # Any calculation errors
    warnings: list[CalculationWarning]  # Any warnings

    @property
    def total_rwa(self) -> float:
        """Total risk-weighted assets."""
        return self.data.select(pl.col("rwa").sum()).collect().item()

    @property
    def total_ead(self) -> float:
        """Total exposure at default."""
        return self.data.select(pl.col("ead").sum()).collect().item()

    def to_dataframe(self) -> pl.DataFrame:
        """Materialize results as DataFrame."""
        return self.data.collect()

    def to_parquet(self, path: str) -> None:
        """Export results to Parquet."""
        self.data.collect().write_parquet(path)

    def to_csv(self, path: str) -> None:
        """Export results to CSV."""
        self.data.collect().write_csv(path)

    def by_exposure_class(self) -> pl.DataFrame:
        """Get breakdown by exposure class."""
        return (
            self.data
            .group_by("exposure_class")
            .agg(
                pl.count().alias("count"),
                pl.col("ead").sum(),
                pl.col("rwa").sum(),
            )
            .collect()
        )
```

## Export Formats

### Parquet

```python
result.to_parquet("rwa_results.parquet")
```

Includes:
- Full precision numeric values
- Efficient compression
- Schema preservation

### CSV

```python
result.to_csv("rwa_results.csv")
```

Includes:
- Human-readable format
- Excel-compatible
- Standard delimiters

### JSON

```python
result.to_json("rwa_results.json")
```

Includes:
- Nested structure support
- Metadata
- Summary statistics

## Example Output

### Detailed Results

```python
result.to_dataframe().head()
```

| exposure_id | exposure_class | approach | ead | rwa |
|-------------|----------------|----------|-----|-----|
| E001 | CORPORATE | SA | 1,000,000 | 500,000 |
| E002 | CORPORATE_SME | SA | 500,000 | 207,975 |
| E003 | RETAIL_MORTGAGE | SA | 250,000 | 87,500 |
| E004 | INSTITUTION | FIRB | 5,000,000 | 1,250,000 |

### Summary

```python
print(f"Total EAD: {result.total_ead:,.0f}")
print(f"Total RWA: {result.total_rwa:,.0f}")
print(f"Average RW: {result.total_rwa / result.total_ead:.1%}")
```

```
Total EAD: 6,750,000
Total RWA: 2,045,475
Average RW: 30.3%
```

## Next Steps

- [Regulatory Tables](regulatory-tables.md)
- [API Reference](../api/index.md)
- [Configuration Guide](../user-guide/configuration.md)
