# CRR IRB Parameters

Quick-reference for Foundation IRB and Advanced IRB parameters under CRR.

**Regulatory Reference:** CRR Articles 153-154, 161-163

---

## F-IRB Supervisory LGD (Art. 161)

| Collateral Type | Supervisory LGD |
|----------------|-----------------|
| Unsecured (senior) | 45% |
| Subordinated | 75% |
| Financial collateral | 0% |
| Receivables | 35% |
| Residential real estate | 35% |
| Commercial real estate | 35% |
| Other physical | 40% |

## PD Floor (Art. 163)

**CRR:** Single floor of **0.03%** for all exposure classes.

(Basel 3.1 introduces differentiated PD floors — see the `basel31` skill.)

## Asset Correlation Formulas (Art. 153)

### Corporate, Institution, Sovereign

```
f(PD) = (1 - exp(-50 x PD)) / (1 - exp(-50))
R = 0.12 x f(PD) + 0.24 x (1 - f(PD))
```

Correlation ranges from 0.12 (high PD) to 0.24 (low PD).

### SME Firm-Size Adjustment

For corporates with turnover < EUR 50m:

```
s = max(5, min(turnover_EUR, 50))
adjustment = 0.04 x (1 - (s - 5) / 45)
R_adjusted = R - adjustment
```

Maximum reduction of 0.04 (at turnover = EUR 5m).

### Retail Mortgage

Fixed: **R = 0.15**

### Qualifying Revolving Retail (QRRE)

Fixed: **R = 0.04**

### Other Retail

```
f(PD) = (1 - exp(-35 x PD)) / (1 - exp(-35))
R = 0.03 x f(PD) + 0.16 x (1 - f(PD))
```

## FI Scalar (Art. 153(2))

**1.25x** multiplier on the correlation coefficient for large or unregulated financial
sector entities. Applied to R before K calculation.

## Capital Requirement Formula (Art. 153)

```
K = LGD x N[(1-R)^(-0.5) x G(PD) + (R/(1-R))^(0.5) x G(0.999)] - PD x LGD
```

Where N(x) = cumulative normal CDF, G(x) = inverse normal CDF, G(0.999) = 3.0902323.

K is floored at 0.

## Maturity Adjustment (Art. 162)

Applied to non-retail exposures only (retail: MA = 1.0):

```
b = (0.11852 - 0.05478 x ln(PD))^2
MA = (1 + (M - 2.5) x b) / (1 - 1.5 x b)
```

Maturity M clamped to [1.0, 5.0] years.

## RWA Formula

```
RWA = K x 12.5 x 1.06 x EAD x MA
```

The **1.06** is the CRR scaling factor (removed in Basel 3.1).

## Expected Loss

```
EL = PD x LGD x EAD
```

## A-IRB Differences from F-IRB

| Parameter | F-IRB | A-IRB (CRR) |
|-----------|-------|-------------|
| LGD | Supervisory (above) | Bank's own estimate, **no floor** |
| CCF | Supervisory | Bank's own estimate |
| Maturity | 2.5y default | Bank's own estimate (clamped 1-5y) |

Under CRR, A-IRB has **no LGD floors**. Basel 3.1 introduces floors — see the `basel31` skill.

---

> **Full detail:** `docs/specifications/crr/firb-calculation.md` and `docs/specifications/crr/airb-calculation.md`
