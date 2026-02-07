# Foundation IRB Specification

Foundation IRB calculation with supervisory LGD, PD floors, and correlation formulas.

**Regulatory Reference:** CRR Articles 153-154, 161-163

**Test Group:** CRR-B

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

## PD Floor

**CRR:** Single floor of **0.03%** for all exposure classes (Art. 163).

See [Framework Differences](../basel31/framework-differences.md) for Basel 3.1 differentiated PD floors.

## Asset Correlation Formula (CRR Art. 153)

### Corporate, Institution, Sovereign

PD-dependent correlation with exponential decay factor of 50:

```
f(PD) = (1 - exp(-50 x PD)) / (1 - exp(-50))
R = 0.12 x f(PD) + 0.24 x (1 - f(PD))
```

### SME Firm-Size Adjustment

For corporates with turnover < EUR 50m, correlation is reduced:

```
s = max(5, min(turnover_EUR, 50))
adjustment = 0.04 x (1 - (s - 5) / 45)
R_adjusted = R - adjustment
```

Turnover is stored in GBP and converted to EUR via the configured FX rate.

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

A **1.25x** multiplier applied to the capital requirement for large or unregulated financial sector entities.

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
