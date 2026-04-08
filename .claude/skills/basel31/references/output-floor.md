# Basel 3.1 Output Floor

Mechanics, formula, transitional schedule, and OF-ADJ.

**Regulatory Reference:** PRA PS1/26 Art. 92(5)

---

## Core Formula

```
TREA = max(U-TREA, x * S-TREA + OF-ADJ)
```

Where:

- **U-TREA** = un-floored total risk exposure (using internal models where permitted)
- **S-TREA** = standardised total risk exposure (entire portfolio recalculated using SA only)
- **x** = floor percentage (see transitional schedule)
- **OF-ADJ** = adjustment for IRB expected loss vs SA credit risk adjustments

## OF-ADJ

Reconciles the different provision treatments:
- Under IRB, expected loss shortfall adds to capital requirements
- Under SA, general credit risk adjustments reduce risk exposure

Without OF-ADJ, the floor comparison would not be on a like-for-like basis.

## Transitional Phase-In Schedule

| Year | Floor % |
|------|---------|
| 2027 | 60.0% |
| 2028 | 65.0% |
| 2029 | 70.0% |
| 2030+ | 72.5% |

## Worked Example

```
Portfolio:
  SA RWA (S-TREA): GBP 100m
  IRB RWA (U-TREA): GBP 30m

CRR:
  Final RWA: GBP 30m (70% capital saving)

Basel 3.1 (fully phased):
  Floor: GBP 100m x 72.5% = GBP 72.5m
  Final RWA: max(GBP 30m, GBP 72.5m) = GBP 72.5m (27.5% capital saving only)
```

## Impact

The output floor primarily affects firms with:
- Strong IRB models producing low RWA
- High-quality, low-risk portfolios
- Large proportion of IRB-modelled exposures

The floor ensures a minimum level of capitalisation regardless of model sophistication.

## Calculator Implementation

The calculator computes SA-equivalent RWA for all exposures via `calculate_unified()`,
which runs the SA risk weight logic on the full portfolio (including IRB exposures).
The output floor comparison is then applied at the aggregation stage.

---

> **Full detail:** `docs/framework-comparison/technical-reference.md` and `docs/framework-comparison/key-differences.md`
