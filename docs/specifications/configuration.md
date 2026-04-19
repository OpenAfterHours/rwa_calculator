# Configuration

## Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-5.1 | Framework toggle: CRR vs Basel 3.1 via factory methods (`CalculationConfig.crr()` / `.basel_3_1()`) | P0 | Done |
| FR-5.2 | IRB approach configuration: F-IRB, A-IRB, or hybrid (per-exposure-class permissions) | P0 | Done |
| FR-5.3 | Configurable reporting date (drives regulatory parameter selection) | P0 | Done |
| FR-5.4 | Configurable PD floors, LGD floors, output floor percentage | P1 | Done |
| FR-5.5 | Configurable scaling factor (1.06 CRR, 1.0 Basel 3.1) | P0 | Done |
| FR-5.6 | Target currency for FX conversion | P1 | Done |
| FR-5.7 | Configurable logging (`log_level`, `log_format`) — see [Observability](observability.md) | P1 | Done |

## Factory Methods

- `CalculationConfig.crr()` — CRR (Basel 3.0) configuration with 1.06 scaling factor, SME supporting factors
- `CalculationConfig.basel_3_1()` — Basel 3.1 configuration with 1.0 scaling factor, no SME factors, output floor

## Key Scenarios

!!! note "Test Coverage"
    Configuration is validated implicitly through all acceptance test groups — every CRR and B31 scenario relies on `CalculationConfig.crr()` or `.basel_3_1()` factory methods. The scenario IDs below document key configuration behaviours.

| Scenario ID | Description |
|-------------|-------------|
| CONFIG-1 | CRR factory — `CalculationConfig.crr()` sets scaling factor 1.06, enables SME supporting factors |
| CONFIG-2 | Basel 3.1 factory — `CalculationConfig.basel_3_1()` sets scaling factor 1.0, enables output floor, disables supporting factors |
| CONFIG-3 | Reporting date — drives transitional parameter selection (e.g., equity weights, output floor percentage) |
| CONFIG-4 | PD/LGD floor configuration — floor values propagated to IRB calculators per framework |
| CONFIG-5 | IRB permissions — per-exposure-class approach assignment (F-IRB, A-IRB, or SA fallback) |
| CONFIG-6 | Target currency — FX conversion rate applied to all monetary thresholds and outputs |
| CONFIG-7 | Logging fields — `log_level` (`DEBUG`/`INFO`/`WARNING`/`ERROR`/`CRITICAL`) and `log_format` (`"text"`/`"json"`) configure the `rwa_calc` namespace logger; defaults `"INFO"` and `"text"` |

## Outstanding Work

None — all configuration requirements are complete.
