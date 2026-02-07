# Provisions Specification

Provision treatment, expected loss calculation, and EL vs provisions comparison.

**Regulatory Reference:** CRR Articles 110, 158-159

**Test Group:** CRR-G

---

## SA Approach (CRR Art. 110)

Under the Standardised Approach, specific provisions are **deducted from the exposure value** before risk weighting:

```
EAD_net = EAD_gross - specific_provisions
```

This reduces the base on which risk weights are applied.

## IRB Approach (CRR Art. 158-159)

Under IRB, provisions are not deducted from EAD. Instead, the calculator computes Expected Loss for comparison:

```
EL = PD x LGD x EAD
```

### EL vs Provisions Comparison

- **EL > Provisions (shortfall):** The difference reduces CET1 capital
- **EL < Provisions (excess):** The surplus may be added to Tier 2 capital (subject to caps)

The calculator tracks both values to support this regulatory comparison.

## Key Scenarios

| Scenario ID | Description |
|-------------|-------------|
| CRR-G | SA exposure with specific provision deducted from EAD |
| CRR-G | IRB expected loss calculation |
| CRR-G | EL vs provisions: shortfall case |
| CRR-G | EL vs provisions: excess case |
