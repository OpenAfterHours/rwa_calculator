# Foundation IRB Specification

Basel 3.1 Foundation IRB changes: reduced senior LGD, higher PD floors, covered bond LGD,
1.06 scaling removal, and GBP-native SME correlation thresholds.

**Regulatory Reference:** PRA PS1/26 Art. 153–163, CRE31–32
**Test Group:** B31-B

---

## Requirements Status

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-3.1 | Revised supervisory LGD: 40% non-FSE senior (was 45%) | P0 | Done |
| FR-3.2 | FSE senior LGD distinction: 45% (Art. 161(1)(aa)) | P0 | Done |
| FR-3.3 | PD floor increase: 0.05% corporate (was 0.03%) | P0 | Done |
| FR-3.4 | Retail PD floors: mortgage 0.10%, QRRE revolver 0.10%, other 0.05% | P0 | Done |
| FR-3.5 | 1.06 scaling factor removed | P0 | Done |
| FR-3.6 | Covered bond LGD: 11.25% (Art. 161(1B)) | P0 | Done |
| FR-3.7 | Collateral-type LGDS reductions (receivables, RE, other physical) | P0 | Done |
| FR-3.8 | GBP-native SME correlation thresholds (£4.4m–£44m) | P0 | Done |

---

## Overview

Basel 3.1 makes significant changes to the F-IRB framework, primarily reducing the benefit of
internal models by tightening supervisory parameters and removing the scaling factor.

### Key Changes from CRR

| Parameter | CRR | Basel 3.1 | Reference |
|-----------|-----|-----------|-----------|
| Senior unsecured LGD (non-FSE) | 45% | **40%** | Art. 161(1)(a) |
| Senior unsecured LGD (FSE) | 45% | **45%** | Art. 161(1)(aa) |
| Subordinated LGD | 75% | 75% | Art. 161(1)(b) |
| Covered bond LGD | — | **11.25%** | Art. 161(1B) |
| Corporate PD floor | 0.03% | **0.05%** | Art. 160(1) |
| Sovereign/institution PD floor | 0.03% | **0.05%** | Art. 160(1) |
| Scaling factor | 1.06 | **1.00** (removed) | Art. 153(1) |
| SME turnover range | EUR 5m–50m | **GBP 4.4m–44m** | Art. 153(4) |

---

## Supervisory LGD (Art. 161)

### Unsecured Exposures

| Category | LGD | Reference |
|----------|-----|-----------|
| Senior unsecured (non-FSE) | **40%** | Art. 161(1)(a) |
| Senior unsecured (FSE) | **45%** | Art. 161(1)(aa) |
| Subordinated | **75%** | Art. 161(1)(b) |
| Covered bonds | **11.25%** | Art. 161(1B) |

!!! note "FSE Distinction — New in Basel 3.1"
    Basel 3.1 introduces a new distinction for financial sector entities (FSEs). Non-FSE senior
    unsecured exposures benefit from a reduced 40% LGD, while FSE senior unsecured retains the
    CRR 45% rate. This recognises the higher loss severity observed for financial institution
    defaults. FSE is defined per Art. 4(1)(146).

### Collateral-Type LGDS Values (Art. 230, CRE32.9–12)

When exposures are secured by eligible collateral, the F-IRB supervisory LGDS values apply:

| Collateral Type | CRR LGDS | Basel 3.1 LGDS | Reference |
|----------------|----------|----------------|-----------|
| Financial collateral / cash | 0% | 0% | — |
| Receivables | 35% | **20%** | CRE32.9 |
| Residential RE | 35% | **20%** | CRE32.10 |
| Commercial RE | 35% | **20%** | CRE32.11 |
| Other physical | 40% | **25%** | CRE32.12 |

### Overcollateralisation Requirements

Unchanged from CRR:

| Collateral Type | OC Ratio | Min Threshold |
|----------------|----------|---------------|
| Financial | 1.00× | 0% |
| Receivables | 1.25× | 0% |
| Residential RE | 1.40× | 30% |
| Commercial RE | 1.40× | 30% |
| Other physical | 1.40× | 30% |

### Blended LGD Formula (Art. 230)

For partially secured exposures, the effective LGD blends secured and unsecured components:

```
LGD_effective = (E_unsecured / EAD) x LGDU + sum_i((E_i / EAD) x LGDS_i)
```

Where:

- `LGDU` = unsecured LGD (40% non-FSE senior, 45% FSE, 75% subordinated)
- `LGDS_i` = secured LGD for collateral type i
- `E_unsecured` = exposure amount not covered by collateral
- `E_i` = exposure amount secured by collateral type i

See [CRM Specification](credit-risk-mitigation.md) for haircut application details.

---

## PD Floors (Art. 160, 163)

### Corporate, Sovereign, and Institution

| Exposure Class | CRR Floor | Basel 3.1 Floor | Reference |
|---------------|-----------|-----------------|-----------|
| Corporate | 0.03% | **0.05%** | Art. 160(1) |
| Corporate SME | 0.03% | **0.05%** | Art. 160(1) |
| Sovereign | 0.03% | **0.05%** | Art. 160(1) |
| Institution | 0.03% | **0.05%** | Art. 160(1) |

### Retail

| Retail Sub-Class | CRR Floor | Basel 3.1 Floor | Reference |
|-----------------|-----------|-----------------|-----------|
| Retail mortgage (residential) | 0.03% | **0.10%** | Art. 163(1)(b) |
| QRRE revolver | 0.03% | **0.10%** | Art. 163(1)(a) |
| QRRE transactor | 0.03% | **0.05%** | Art. 163(1)(c) |
| Retail other | 0.03% | **0.05%** | Art. 163(1)(c) |

!!! note "QRRE Transactor vs Revolver"
    Basel 3.1 introduces differentiated PD floors for qualifying revolving retail exposures (QRRE).
    Revolvers (borrowers who carry balances) receive a higher 0.10% floor, while transactors
    (borrowers who pay in full each period) receive the lower 0.05% floor. This reflects the
    lower observed default rates for transactor populations.

---

## Capital Formula (Art. 153)

The IRB capital formula is unchanged in structure but the 1.06 scaling factor is removed:

```
K = LGD x N[(1-R)^(-0.5) x G(PD) + (R/(1-R))^(0.5) x G(0.999)] - PD x LGD
```

```
RW = K x 12.5 x MA
```

Where:

- `N[.]` = cumulative normal distribution function
- `G(.)` = inverse cumulative normal distribution (PPF)
- `R` = asset correlation (see below)
- `MA` = maturity adjustment factor
- `PD` = probability of default (floored)
- `LGD` = loss given default (supervisory or floored internal)

!!! warning "1.06 Scaling Factor Removed"
    Under CRR, the final RW was multiplied by 1.06 (Art. 153(1)). Basel 3.1 removes this factor
    entirely. The scaling factor column in output will show 1.0 for all Basel 3.1 calculations.

### Asset Correlation (Art. 153(2)–(4))

**Corporate, Sovereign, Institution:**

```
R = 0.12 x f(PD) + 0.24 x (1 - f(PD))
where f(PD) = (1 - exp(-50 x PD)) / (1 - exp(-50))
```

**SME Correlation Adjustment (Art. 153(4)):**

```
SME_adj = 0.04 x (1 - (s - 4.4) / 39.6)
R_SME = R_corporate - SME_adj
```

Where `s = clip(turnover_GBP, 4.4, 44.0)` (millions GBP).

!!! note "GBP-Native Thresholds"
    CRR uses EUR thresholds (5m–50m, denominator 45). Basel 3.1 uses GBP-native thresholds
    (4.4m–44m, denominator 39.6) per PRA PS1/26 Art. 153(4). This eliminates FX conversion
    for UK firms.

**Retail Mortgage / Residential RE:** Fixed R = 0.15

**QRRE:** Fixed R = 0.04

**Retail Other:**

```
R = 0.03 x f(PD) + 0.16 x (1 - f(PD))
where f(PD) = (1 - exp(-35 x PD)) / (1 - exp(-35))
```

### FI Scalar (Art. 153(2))

For large or unregulated financial sector entities, a **1.25× multiplier** is applied to the
asset correlation:

```
R_fse = R x 1.25
```

Triggered by `apply_fi_scalar = True` in the input data. See
[Model Permissions](model-permissions.md) for the distinction between the FI scalar
(EUR 70bn total assets, Art. 4(1)(146)) and Art. 147A approach restrictions (£440m revenue).

### Maturity Adjustment (Art. 162)

```
b = (0.11852 - 0.05478 x ln(PD))^2
MA = (1 + (M - 2.5) x b) / (1 - 1.5 x b)
```

Where:

- `M` = effective maturity, floored at 1.0 year and capped at **5.0 years**
- Default maturity (when not specified): 2.5 years
- Retail exposures: MA = 1.0 (no maturity adjustment)

---

## Key Scenarios

| Scenario ID | Description | Key Parameter |
|-------------|-------------|---------------|
| B31-B1 | Corporate senior unsecured, non-FSE — LGD 40% | LGD = 40% (was 45%) |
| B31-B2 | PD floor test: PD input < 0.05% | PD floored to 0.05% |
| B31-B3 | 1.06 scaling removed | Scaling = 1.0 |
| B31-B4 | SME firm-size correlation adjustment (GBP thresholds) | Turnover in £4.4m–44m range |
| B31-B5 | SME corporate with no supporting factor | SF = 1.0 (removed in B31) |
| B31-B6 | Long maturity (5Y cap) | M capped at 5.0 |
| B31-B7 | FSE senior unsecured — LGD 45% retained | LGD = 45% (FSE distinction) |

## Acceptance Tests

| Group | Scenarios | Tests | Pass Rate |
|-------|-----------|-------|-----------|
| B31-B: Foundation IRB | B1–B7 | 16 | 100% (16/16) |
