# Regulatory Tables

This page documents the lookup tables used for regulatory risk weight assignment, CCF,
supervisory haircuts, LGD, and slotting.

> **Source of truth**: All table implementations are in `src/rwa_calc/data/tables/`.

## Risk Weight Tables

### Sovereign Risk Weights (CRR Art. 114)

Sovereign weights are identical under CRR and Basel 3.1.

| CQS | Risk Weight |
|-----|------------|
| 1 | 0% |
| 2 | 20% |
| 3 | 50% |
| 4 | 100% |
| 5 | 100% |
| 6 | 150% |
| Unrated | 100% |

**Source**: `CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS` in `data/tables/crr_risk_weights.py`

### Institution Risk Weights (CRR Art. 120–121)

| CQS | UK CRR (ECRA) | Standard CRR |
|-----|---------------|--------------|
| 1 | 20% | 20% |
| 2 | **30%** | 50% |
| 3 | 50% | 50% |
| 4 | 100% | 100% |
| 5 | 100% | 100% |
| 6 | 150% | 150% |
| Unrated | 40% | 40% |

The UK CRR deviates from the standard EU CRR at CQS 2 (30% vs 50%).

**Basel 3.1 SCRA** (for unrated institutions, CRE20.16-21):

| Grade | Risk Weight |
|-------|------------|
| A | 40% |
| B | 75% |
| C | 150% |

**Source**: `INSTITUTION_RISK_WEIGHTS_UK`, `B31_SCRA_RISK_WEIGHTS` in `data/tables/`

### Corporate Risk Weights (CRR Art. 122)

| CQS | CRR | Basel 3.1 |
|-----|-----|-----------|
| 1 | 20% | 20% |
| 2 | 50% | 50% |
| 3 | **100%** | **75%** |
| 4 | 100% | 100% |
| 5 | **150%** | **100%** |
| 6 | 150% | 150% |
| Unrated | 100% | 100% |

**Basel 3.1 corporate additions:**

| Category | Risk Weight | Reference |
|----------|------------|-----------|
| Investment grade | 65% | CRE20.47 |
| SME corporate | 85% | CRE20.49 |
| Subordinated debt | 150% | CRE20.50 |

**Source**: `CORPORATE_RISK_WEIGHTS`, `B31_CORPORATE_RISK_WEIGHTS`, `B31_CORPORATE_INVESTMENT_GRADE_RW`, `B31_CORPORATE_SME_RW`, `B31_SUBORDINATED_DEBT_RW` in `data/tables/`

### Retail Risk Weights

| Exposure Type | CRR | Basel 3.1 |
|---------------|-----|-----------|
| Retail Mortgage (LTV ≤ 80%) | 35% | LTV-based (see below) |
| Retail QRRE | 75% | 75% |
| Retail Other | 75% | 75% |

**Source**: `RETAIL_RISK_WEIGHT` in `data/tables/crr_risk_weights.py`

### CRR Residential Mortgage (CRR Art. 125)

Under CRR, residential mortgages use a split treatment based on 80% LTV threshold:

- LTV ≤ 80%: 35% risk weight
- LTV > 80%: 35% on the secured portion, 75% on the unsecured excess

**Source**: `RESIDENTIAL_MORTGAGE_PARAMS` in `data/tables/crr_risk_weights.py`

### CRR Commercial Real Estate (CRR Art. 126)

| Condition | Risk Weight |
|-----------|------------|
| LTV ≤ 50% with income cover | 50% |
| All other | 100% |

**Source**: `COMMERCIAL_RE_PARAMS` in `data/tables/crr_risk_weights.py`

### Basel 3.1 Residential Real Estate (CRE20.73-82)

#### General (whole-loan approach)

| LTV | Risk Weight |
|-----|------------|
| ≤ 50% | 20% |
| 50–60% | 25% |
| 60–70% | 25% |
| 70–80% | 30% |
| 80–90% | 40% |
| 90–100% | 50% |
| > 100% | 70% |

#### Income-producing (CRE20.82)

| LTV | Risk Weight |
|-----|------------|
| ≤ 50% | 30% |
| 50–60% | 35% |
| 60–70% | 45% |
| 70–80% | 50% |
| 80–90% | 60% |
| 90–100% | 75% |
| > 100% | 105% |

**Source**: `B31_RESIDENTIAL_GENERAL_LTV_BANDS`, `B31_RESIDENTIAL_INCOME_LTV_BANDS` in `data/tables/b31_risk_weights.py`

### Basel 3.1 Commercial Real Estate (CRE20.86)

#### General

| LTV | Risk Weight |
|-----|------------|
| ≤ 60% | min(60%, counterparty RW) |
| > 60% | counterparty RW |

#### Income-producing

| LTV | Risk Weight |
|-----|------------|
| ≤ 60% | 70% |
| 60–80% | 90% |
| > 80% | 110% |

#### ADC Exposures

| Condition | Risk Weight |
|-----------|------------|
| ADC (standard) | 150% |
| ADC (pre-sold) | 100% |

**Source**: `B31_COMMERCIAL_INCOME_LTV_BANDS`, `B31_ADC_RISK_WEIGHT`, `B31_ADC_PRESOLD_RISK_WEIGHT` in `data/tables/b31_risk_weights.py`

---

## Credit Conversion Factors

### Risk Type Categories (CRR Art. 111)

| Code | Full Value | SA CCF | F-IRB CCF | Description |
|------|------------|--------|-----------|-------------|
| `FR` | `full_risk` | 100% | 100% | Direct credit substitutes, guarantees, acceptances |
| `MR` | `medium_risk` | 50% | 75% | NIFs, RUFs, standby LCs, committed undrawn |
| `MLR` | `medium_low_risk` | 20% | 75% | Documentary credits, trade finance |
| `LR` | `low_risk` | 0% | 0% | Unconditionally cancellable commitments |

**F-IRB 75% Rule (CRR Art. 166(8)):** Under F-IRB, both MR and MLR categories use 75% CCF.

**F-IRB Exception (CRR Art. 166(9)):** Short-term letters of credit arising from the
movement of goods retain 20% CCF under F-IRB. Flag these with `is_short_term_trade_lc = True`.

---

## Supervisory Haircuts (CRR Art. 224 / CRE22.52-53)

### CRR Financial Collateral Haircuts (3 maturity bands)

| Collateral Type | ≤ 1yr | 1–5yr | > 5yr |
|-----------------|-------|-------|-------|
| Cash | 0% | 0% | 0% |
| Government CQS 1 | 0.5% | 2% | 4% |
| Government CQS 2-3 | 1% | 3% | 6% |
| Corporate CQS 1 | 1% | 4% | 8% |
| Corporate CQS 2-3 | 2% | 6% | 12% |
| Equity (main index) | 15% | — | — |
| Equity (other) | 25% | — | — |
| Gold | 15% | — | — |

### Basel 3.1 Financial Collateral Haircuts (5 maturity bands)

| Collateral Type | ≤ 1yr | 1–3yr | 3–5yr | 5–10yr | > 10yr |
|-----------------|-------|-------|-------|--------|--------|
| Cash | 0% | 0% | 0% | 0% | 0% |
| Government CQS 1 | 0.5% | 2% | 2% | 4% | 4% |
| Government CQS 2-3 | 1% | 3% | 4% | 6% | 12% |
| Corporate CQS 1-2 | 1% | 4% | 6% | 10% | 12% |
| Corporate CQS 3 | 2% | 6% | 8% | 15% | 15% |
| Equity (main index) | **25%** | — | — | — | — |
| Equity (other) | **35%** | — | — | — | — |
| Gold | 15% | — | — | — | — |

### Non-Financial Collateral Haircuts

| Collateral Type | Haircut |
|-----------------|--------|
| Receivables | 20% |
| Other physical | 40% |

### Additional Haircuts

| Condition | Haircut |
|-----------|--------|
| Currency mismatch | +8% |

**Source**: `COLLATERAL_HAIRCUTS`, `BASEL31_COLLATERAL_HAIRCUTS`, `FX_HAIRCUT` in `data/tables/crr_haircuts.py`

---

## Slotting Risk Weights

### CRR Non-HVCRE Specialised Lending (CRR Art. 153(5))

CRR differentiates by remaining maturity (≥ 2.5 years vs < 2.5 years).

| Category | ≥ 2.5yr | < 2.5yr |
|----------|---------|---------|
| Strong | 70% | **50%** |
| Good | **90%** | **70%** |
| Satisfactory | 115% | 115% |
| Weak | 250% | 250% |
| Default | 0% | 0% |

### CRR HVCRE (CRR Art. 153(5) Table 2)

HVCRE has **higher** risk weights than standard specialised lending.

| Category | ≥ 2.5yr | < 2.5yr |
|----------|---------|---------|
| Strong | **95%** | **70%** |
| Good | **120%** | **95%** |
| Satisfactory | **140%** | **140%** |
| Weak | 250% | 250% |
| Default | 0% | 0% |

### Basel 3.1 Non-HVCRE Operational

| Category | Risk Weight |
|----------|------------|
| Strong | 70% |
| Good | 70% |
| Satisfactory | 115% |
| Weak | 250% |

### Basel 3.1 Project Finance Pre-Operational

| Category | Risk Weight |
|----------|------------|
| Strong | 80% |
| Good | 100% |
| Satisfactory | 120% |
| Weak | 350% |

### Basel 3.1 HVCRE

| Category | Risk Weight |
|----------|------------|
| Strong | 95% |
| Good | 120% |
| Satisfactory | 140% |
| Weak | 250% |

**Source**: `SLOTTING_RISK_WEIGHTS`, `SLOTTING_RISK_WEIGHTS_SHORT`, `SLOTTING_RISK_WEIGHTS_HVCRE`, `SLOTTING_RISK_WEIGHTS_HVCRE_SHORT` in `data/tables/crr_slotting.py`

---

## F-IRB Supervisory LGD (CRR Art. 161)

### CRR Values

| Exposure Type | LGD |
|---------------|-----|
| Senior unsecured | 45% |
| Subordinated | 75% |
| Secured — Financial collateral | 0% |
| Secured — Receivables | 35% |
| Secured — Residential RE | 35% |
| Secured — Commercial RE | 35% |
| Secured — Other physical | 40% |

### Basel 3.1 Values (PRA PS1/26)

| Exposure Type | LGD | Change |
|---------------|-----|--------|
| Senior unsecured | **40%** | ↓ from 45% |
| Subordinated | 75% | — |
| Secured — Financial collateral | 0% | — |
| Secured — Receivables | **20%** | ↓ from 35% |
| Secured — Residential RE | **20%** | ↓ from 35% |
| Secured — Commercial RE | **20%** | ↓ from 35% |
| Secured — Other physical | **25%** | ↓ from 40% |

### Overcollateralisation Requirements

| Collateral Type | Min Ratio | Min Threshold |
|-----------------|-----------|---------------|
| Financial | 1.0x | 0% of EAD |
| Receivables | 1.25x | 0% of EAD |
| Real estate | 1.4x | 30% of EAD |
| Other physical | 1.4x | 30% of EAD |

**Source**: `FIRB_SUPERVISORY_LGD`, `BASEL31_FIRB_SUPERVISORY_LGD`, `FIRB_OVERCOLLATERALISATION_RATIOS` in `data/tables/crr_firb_lgd.py`

---

## A-IRB LGD Floors (Basel 3.1 only)

Under CRR, A-IRB has no LGD floors. Basel 3.1 introduces LGD floors:

| Collateral Type | LGD Floor |
|-----------------|-----------|
| Unsecured senior | 25% |
| Unsecured subordinated | 50% |
| Financial collateral | 0% |
| Receivables | 10% |
| Commercial real estate | 10% |
| Residential real estate | 5% |
| Other physical | 15% |

---

## PD Floors

| Exposure Class | CRR | Basel 3.1 |
|----------------|-----|-----------|
| Corporate | 0.03% | 0.05% |
| Institution | 0.03% | 0.05% |
| Retail Mortgage | 0.03% | 0.05% |
| Retail QRRE (transactor) | 0.03% | 0.03% |
| Retail QRRE (revolver) | 0.03% | 0.10% |
| Retail Other | 0.03% | 0.05% |

**Source**: `CRR_PD_FLOOR` in `data/tables/crr_firb_lgd.py`, `PDFloors` in `contracts/config.py`

---

## Equity Risk Weights

### SA Equity (CRR Art. 133)

| Equity Type | Risk Weight |
|------------|------------|
| Central bank | 0% |
| Listed | 100% |
| Exchange traded | 100% |
| Government supported | 100% |
| Diversified private equity | 250% |
| Unlisted | 250% |
| Private equity | 250% |
| CIU | 250% |
| Other | 250% |
| Speculative | 400% |

### IRB Simple Equity (CRR Art. 155)

| Equity Type | Risk Weight |
|------------|------------|
| Central bank | 0% |
| Government supported | 190% |
| Diversified private equity | 190% |
| Listed | 290% |
| Exchange traded | 290% |
| Unlisted | 370% |
| Private equity | 370% |
| Speculative | 370% |
| CIU | 370% |
| Other | 370% |

**Note:** Under Basel 3.1, IRB equity approaches are withdrawn. All equity falls to SA.

**Source**: `SA_EQUITY_RISK_WEIGHTS`, `IRB_SIMPLE_EQUITY_RISK_WEIGHTS` in `data/tables/crr_equity_rw.py`

---

## IRB Parameters

### Maturity Bounds

| Parameter | Value |
|-----------|-------|
| PD floor (CRR) | 0.03% |
| Maturity floor | 1 year |
| Maturity cap | 5 years |

**Source**: `CRR_PD_FLOOR`, `CRR_MATURITY_FLOOR`, `CRR_MATURITY_CAP` in `data/tables/crr_firb_lgd.py`

---

## API Functions

### Risk Weight Lookup

```python
from rwa_calc.data.tables.crr_risk_weights import lookup_risk_weight

rw = lookup_risk_weight(
    exposure_class="corporate",
    cqs=2,
    use_uk_deviation=True
)
# Returns: Decimal("0.50") (50%)
```

### Residential Mortgage RW (CRR)

```python
from rwa_calc.data.tables.crr_risk_weights import calculate_residential_mortgage_rw
from decimal import Decimal

rw, description = calculate_residential_mortgage_rw(ltv=Decimal("0.85"))
# Returns: (blended_rw, "split_treatment")
```

### Basel 3.1 Residential RW

```python
from rwa_calc.data.tables.b31_risk_weights import lookup_b31_residential_rw
from decimal import Decimal

rw, band = lookup_b31_residential_rw(ltv=Decimal("0.65"), is_income_producing=False)
# Returns: (Decimal("0.25"), "60-70%")
```

### Haircut Lookup

```python
from rwa_calc.data.tables.crr_haircuts import lookup_collateral_haircut

haircut = lookup_collateral_haircut(
    collateral_type="bond",
    cqs=1,
    residual_maturity_years=3.0,
    is_main_index=False,
    is_basel_3_1=False
)
# Returns: Decimal("0.04") (4% for govt CQS1 1-5yr)
```

### F-IRB LGD Lookup

```python
from rwa_calc.data.tables.crr_firb_lgd import lookup_firb_lgd

lgd = lookup_firb_lgd(
    collateral_type="residential_re",
    is_subordinated=False,
    is_basel_3_1=False
)
# Returns: Decimal("0.35") (35% CRR) or Decimal("0.20") (20% Basel 3.1)
```

### Slotting Lookup

```python
from rwa_calc.data.tables.crr_slotting import lookup_slotting_rw

rw = lookup_slotting_rw(
    category="good",
    is_hvcre=False,
    is_short_maturity=False
)
# Returns: Decimal("0.90") (90%)
```

### Equity RW Lookup

```python
from rwa_calc.data.tables.crr_equity_rw import lookup_equity_rw

rw = lookup_equity_rw(equity_type="listed", approach="sa")
# Returns: Decimal("1.00") (100%)

rw = lookup_equity_rw(equity_type="listed", approach="irb_simple")
# Returns: Decimal("2.90") (290%)
```

## Next Steps

- [API Reference](../api/index.md)
- [Standardised Approach](../user-guide/methodology/standardised-approach.md)
- [IRB Approach](../user-guide/methodology/irb-approach.md)
