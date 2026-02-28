# Configuration

## Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-5.1 | Framework toggle: CRR vs Basel 3.1 via factory methods (`CalculationConfig.crr()` / `.basel_3_1()`) | P0 | Done |
| FR-5.2 | IRB approach configuration: F-IRB, A-IRB, or hybrid (per-exposure-class permissions) | P0 | Done |
| FR-5.3 | Configurable reporting date (drives regulatory parameter selection) | P0 | Done |
| FR-5.4 | Configurable PD floors, LGD floors, output floor percentage | P1 | Partial |
| FR-5.5 | Configurable scaling factor (1.06 CRR, 1.0 Basel 3.1) | P0 | Done |
| FR-5.6 | Target currency for FX conversion | P1 | Done |

## Factory Methods

- `CalculationConfig.crr()` — CRR (Basel 3.0) configuration with 1.06 scaling factor, SME supporting factors
- `CalculationConfig.basel_3_1()` — Basel 3.1 configuration with 1.0 scaling factor, no SME factors, output floor

## Outstanding Work

- FR-5.4: Configurable PD floors and LGD floors not yet fully exposed via config (linked to FR-1.5, FR-1.9)
