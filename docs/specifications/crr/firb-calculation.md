# Foundation IRB Specification

Foundation IRB calculation with supervisory LGD, PD floors, and correlation formulas.

**Regulatory Reference:** CRR Articles 153-154, 161-163

**Test Group:** CRR-B

---

## Requirements Status

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-1.3 | F-IRB capital requirement (K): PD, supervisory LGD, maturity adjustment | P0 | Done |
| FR-1.8 | Defaulted exposure treatment: F-IRB (K=0) | P0 | Done |

---

## Supervisory LGD Values (CRR Art. 161)

Under F-IRB, LGD is prescribed by the regulator based on collateral type:

| Collateral Type | Supervisory LGD |
|----------------|-----------------|
| Unsecured (senior) | 45% |
| Subordinated | 75% |
| Financial collateral | 0% |
| Receivables | 35% |
| Residential real estate | 35% |
| Commercial real estate | 35% |
| Other physical | 40% |

### Basel 3.1 F-IRB LGD Changes (PRA PS1/26 Art. 161(1))

Under Basel 3.1, senior unsecured LGD is differentiated by whether the counterparty is a **financial sector entity (FSE)**:

| Collateral Type | CRR LGD | Basel 3.1 LGD | Reference |
|----------------|---------|---------------|-----------|
| Unsecured (senior, non-FSE) | 45% | **40%** | Art. 161(1)(aa) |
| Unsecured (senior, FSE) | 45% | **45%** | Art. 161(1)(a) |
| Subordinated | 75% | 75% | Art. 161(1)(b) |
| Covered bonds | — | **11.25%** | Art. 161(1B) |
| Financial collateral | 0% | 0% | Art. 161(1)(d) |
| Receivables | 35% | **20%** | CRE32.9 |
| Residential real estate | 35% | **20%** | CRE32.10 |
| Commercial real estate | 35% | **20%** | CRE32.11 |
| Other physical | 40% | **25%** | CRE32.12 |

!!! note "FSE Definition"
    Financial sector entity includes banks, building societies, investment firms, insurance companies, and any entity primarily engaged in financial intermediation. See Art. 4(1)(27) CRR.

## PD Floor

**CRR:** Single floor of **0.03%** (3 basis points) for all non-defaulted exposure classes (Art. 160(1)).

### Basel 3.1 PD Floors by Exposure Class (PRA PS1/26 Art. 160/163)

Under Basel 3.1, PD floors are differentiated by exposure class:

| Exposure Class | CRR PD Floor | Basel 3.1 PD Floor | Reference |
|---------------|-------------|--------------------|-----------| 
| Corporate / SME | 0.03% | **0.05%** | Art. 160(1) |
| Sovereign | 0.03% | 0.05% | Art. 160(1) |
| Institution | 0.03% | 0.05% | Art. 160(1) |
| Retail — mortgage | 0.03% | **0.10%** | Art. 163(1)(b) |
| Retail — QRRE (transactor) | 0.03% | **0.05%** | Art. 163(1)(c) |
| Retail — QRRE (revolver) | 0.03% | **0.10%** | Art. 163(1)(a) |
| Retail — other | 0.03% | **0.05%** | Art. 163(1)(c) |

!!! note "Sovereign/Institution PD Floors"
    Under Basel 3.1, sovereign and institution exposures retain a PD floor but are restricted under Art. 147A (sovereign = SA only, institution = FIRB only). PD floors are still relevant for any grandfathered or transitional IRB treatment.

See [Framework Differences](../../framework-comparison/technical-reference.md) for Basel 3.1 differentiated PD floors.

## Asset Correlation Formula (CRR Art. 153)

### Corporate, Institution, Sovereign

PD-dependent correlation with exponential decay factor of 50:

```
f(PD) = (1 - exp(-50 x PD)) / (1 - exp(-50))
R = 0.12 x f(PD) + 0.24 x (1 - f(PD))
```

### SME Firm-Size Adjustment

For corporates with turnover < EUR 50m, correlation is reduced:

**CRR (Art. 153(4)):**
```
s = max(5, min(turnover_EUR, 50))
adjustment = 0.04 x (1 - (s - 5) / 45)
R_adjusted = R - adjustment
```

Turnover is stored in GBP and converted to EUR via the configured FX rate (default: 0.8732).

**Basel 3.1 (PRA PS1/26):** Thresholds converted to GBP:

| Parameter | CRR (EUR) | Basel 3.1 (GBP) |
|-----------|----------|-----------------|
| SME threshold | EUR 50m | GBP 44m |
| Floor turnover | EUR 5m | GBP 4.4m |
| Adjustment range | 45 | 39.6 |

```
s = max(4.4, min(turnover_GBP, 44))
adjustment = 0.04 x (1 - (s - 4.4) / 39.6)
R_adjusted = R - adjustment
```

### Retail Mortgage

Fixed correlation: **R = 0.15**

### Qualifying Revolving Retail (QRRE)

Fixed correlation: **R = 0.04**

### Other Retail

PD-dependent correlation with exponential decay factor of 35:

```
f(PD) = (1 - exp(-35 x PD)) / (1 - exp(-35))
R = 0.03 x f(PD) + 0.16 x (1 - f(PD))
```

## FI Scalar (CRR Art. 153(2))

A **1.25x** multiplier applied to the **asset correlation coefficient** (R) for **large financial sector entities** (total assets ≥ EUR 70bn per CRR Art. 4(1)(146)) **and unregulated financial sector entities** (per CRR Art. 153(2)).

!!! warning "Two distinct thresholds — do not conflate"
    - **EUR 70bn total assets** (≈ GBP 79bn) → 1.25x correlation multiplier (Art. 153(2)). Applies to large FSEs and all unregulated FSEs under both CRR and Basel 3.1.
    - **GBP 440m annual revenue** → F-IRB only approach restriction (Art. 147A(1)(d), Basel 3.1 only). Does not affect correlation.
    - The Art. 147A(1)(e) F-IRB restriction applies to **all** FSEs regardless of size — it is separate from the correlation uplift which only applies to *large* or *unregulated* FSEs.

## Capital Requirement Formula

```
K = LGD x N[(1-R)^(-0.5) x G(PD) + (R/(1-R))^(0.5) x G(0.999)] - PD x LGD
```

Where:

- `N(x)` = cumulative normal distribution function
- `G(x)` = inverse normal CDF
- `G(0.999)` = 3.0902323061678132
- `K` is floored at 0

## Maturity Adjustment (CRR Art. 162)

Applied to non-retail exposures only (retail exposures use MA = 1.0):

```
b = (0.11852 - 0.05478 x ln(PD))^2
MA = (1 + (M - 2.5) x b) / (1 - 1.5 x b)
```

Maturity `M` is clamped to the range [1.0, 5.0] years.

**Default supervisory maturity**: Where no maturity date is available, F-IRB uses a supervisory default of **2.5 years** (Art. 162(2)).

**Basel 3.1 revolving maturity** (Art. 162(2A)(k)): Under Basel 3.1, for revolving exposures, M shall be determined using the **maximum contractual termination date** of the facility. The institution shall not use the repayment date of the current drawing.

!!! warning "Previous Description Was Wrong"
    This section previously stated "unconditionally cancellable revolving facilities are assigned a maturity of 1 year". Art. 162(2A)(k) actually requires the **maximum contractual termination date** — not a 1-year default. Using 1 year instead of the facility termination date would systematically understate maturity and therefore RWA for revolving corporate exposures.

## RWA Calculation

**CRR:** `RWA = K x 12.5 x 1.06 x EAD x MA`

The 1.06 is the CRR scaling factor (not present in Basel 3.1).

## Expected Loss

```
EL = PD x LGD x EAD
```

Used for comparison against provisions (see [Provisions](provisions.md)).

## Key Scenarios

| Scenario ID | Description |
|-------------|-------------|
| CRR-B | Corporate F-IRB with senior unsecured (LGD 45%) |
| CRR-B | Corporate F-IRB with financial collateral (LGD 0%) |
| CRR-B | SME with firm-size adjustment |
| CRR-B | PD floor enforcement (PD < 0.03%) |
| CRR-B | FI scalar application (1.25x) |
| CRR-B | Maturity adjustment at boundaries (M=1, M=5) |
