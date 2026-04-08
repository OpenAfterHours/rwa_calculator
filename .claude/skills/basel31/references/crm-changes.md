# Basel 3.1 CRM Changes

Credit risk mitigation method taxonomy and haircut changes.

**Regulatory Reference:** PRA PS1/26 Art. 191A, BCBS CRE22

---

## Method Taxonomy (Art. 191A)

Basel 3.1 restructures CRM with clearer names and explicit applicability:

| Method | CRR Name | Applies To |
|--------|----------|-----------|
| Financial Collateral Simple | Same | SA only |
| Financial Collateral Comprehensive | Same | SA + IRB |
| **Foundation Collateral Method (FCM)** | Various IRB collateral articles | F-IRB |
| **Parameter Substitution Method (PSM)** | Art. 236 substitution | F-IRB (unfunded) |
| **LGD Adjustment Method (LGD-AM)** | Art. 183 | A-IRB (unfunded) |

## Haircut Changes

Maturity bands expand from 3 to 5. Significant increases for equities and long-dated bonds.

### CRR Haircuts (3 maturity bands)

| Collateral Type | 0-1y | 1-5y | 5y+ |
|-----------------|------|------|-----|
| Govt bonds CQS 1 | 0.5% | 2% | 4% |
| Govt bonds CQS 2-3 | 1% | 3% | 6% |
| Corp bonds CQS 1 | 1% | 4% | 8% |
| Corp bonds CQS 2-3 | 2% | 6% | 12% |
| Main index equities | 15% | — | — |
| Other equities | 25% | — | — |
| Gold | 15% | — | — |
| Cash | 0% | — | — |

### Basel 3.1 Haircuts (5 maturity bands)

| Collateral Type | 0-1y | 1-3y | 3-5y | 5-10y | 10y+ |
|-----------------|------|------|------|-------|------|
| Govt bonds CQS 1 | 0.5% | 2% | 2% | 4% | 4% |
| Govt bonds CQS 2-3 | 1% | 3% | 4% | 6% | **12%** |
| Corp bonds CQS 1 | 1% | 4% | 6% | **10%** | **12%** |
| Corp bonds CQS 2-3 | 2% | 6% | 8% | **15%** | **15%** |
| Main index equities | **20%** | — | — | — | — |
| Other equities | **30%** | — | — | — | — |
| Gold | 15% | — | — | — | — |
| Cash | 0% | — | — | — | — |

### Key Haircut Increases

| Collateral | CRR | Basel 3.1 | Change |
|------------|-----|-----------|--------|
| Main index equities | 15% | 20% | +5pp |
| Other listed equities | 25% | 30% | +5pp |
| Govt bonds CQS 2-3 (10y+) | 6% | 12% | +6pp |
| Corp bonds CQS 1 (10y+) | 8% | 12% | +4pp |
| Corp bonds CQS 2-3 (5-10y/10y+) | 12% | 15% | +3pp |

## Overcollateralisation

Unchanged from CRR. Foundation Collateral Method retains the same ratios:

| Type | Ratio | Minimum Coverage |
|------|-------|-----------------|
| Financial | 1.0x | None |
| Receivables | 1.25x | None |
| RE / Other physical | 1.4x | 30% of EAD |

## FX Mismatch Haircut

Unchanged at **8%** (CRR Art. 224 / CRE22.54).

## Unfunded Credit Protection (Art. 213)

New requirement: protection must not be unilaterally **cancellable or changeable** by
the provider. The "or change" condition is new in Basel 3.1.

**Transitional relief (Rule 4.11):** pre-1 Jan 2027 contracts may use CRR treatment
until 30 June 2028, waiving the "or change" requirement for legacy contracts.

---

> **Full detail:** `docs/specifications/crr/credit-risk-mitigation.md` and `docs/framework-comparison/technical-reference.md`
