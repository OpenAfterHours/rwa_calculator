---
name: crr
description: >
  Look up UK CRR (Capital Requirements Regulation) credit risk rules. Use when you need
  SA risk weights, IRB parameters, CCFs, credit risk mitigation haircuts, slotting tables,
  supporting factors, provision treatment, or exposure classification under the current
  CRR framework (EU 575/2013 as onshored, effective until 31 Dec 2026).
---

# CRR — Capital Requirements Regulation Reference

The UK CRR (EU Regulation 575/2013, as onshored) defines the current credit risk framework
for UK banks, effective until 31 December 2026 when Basel 3.1 takes over.

## Quick Navigation

Use this guide to find the right reference file for your question:

| Question | Reference File |
|----------|---------------|
| What risk weight applies to exposure class X? | [references/sa-risk-weights.md](references/sa-risk-weights.md) |
| What are the FIRB/AIRB parameters (LGD, PD, correlation)? | [references/irb-parameters.md](references/irb-parameters.md) |
| What CCF applies to off-balance sheet item X? | [references/credit-conversion-factors.md](references/credit-conversion-factors.md) |
| What haircut applies to collateral type X? | [references/credit-risk-mitigation.md](references/credit-risk-mitigation.md) |
| What are the slotting risk weights / equity treatments? | [references/slotting-and-equity.md](references/slotting-and-equity.md) |
| How are provisions treated (SA vs IRB)? | [references/provisions-and-el.md](references/provisions-and-el.md) |
| What are the SME/infrastructure supporting factors? | [references/supporting-factors.md](references/supporting-factors.md) |
| How are exposures classified by entity type? | [references/exposure-classification.md](references/exposure-classification.md) |

## External Regulatory Sources

- **PRA Rulebook (CRR firms):** https://www.prarulebook.co.uk/pra-rules/crr-firms
- **UK CRR (legislation.gov.uk):** https://www.legislation.gov.uk/eur/2013/575/contents

## Project Specification Files

These are the authoritative implementation specs with full detail, test scenarios, and
acceptance test results:

| Spec File | Topic |
|-----------|-------|
| `docs/specifications/crr/sa-risk-weights.md` | SA risk weights for all exposure classes (CRR + Basel 3.1) |
| `docs/specifications/crr/firb-calculation.md` | Foundation IRB: supervisory LGD, PD floors, correlation, maturity |
| `docs/specifications/crr/airb-calculation.md` | Advanced IRB: own LGD/CCF, LGD floors (Basel 3.1), PMAs |
| `docs/specifications/crr/credit-conversion-factors.md` | CCFs for SA, FIRB, and AIRB |
| `docs/specifications/crr/credit-risk-mitigation.md` | Collateral haircuts, overcollateralisation, guarantees |
| `docs/specifications/crr/slotting-approach.md` | Specialised lending slotting and equity treatments |
| `docs/specifications/crr/provisions.md` | Provision resolution, EL comparison, EL shortfall/excess |
| `docs/specifications/crr/supporting-factors.md` | SME and infrastructure supporting factors |
| `docs/specifications/common/hierarchy-classification.md` | Counterparty hierarchy, rating inheritance, classification |

## Key CRR Articles

| Article(s) | Topic |
|------------|-------|
| Art. 111 | CCFs for off-balance sheet items |
| Art. 112-134 | SA exposure classes and risk weights |
| Art. 114 | Sovereign risk weights |
| Art. 120-121 | Institution risk weights (UK CQS 2 = 30%) |
| Art. 122 | Corporate risk weights |
| Art. 123 | Retail risk weights (75%) |
| Art. 125 | Residential mortgage risk weights (35%) |
| Art. 126 | Commercial real estate (50%/100%) |
| Art. 127 | Defaulted exposures (100%/150%) |
| Art. 133 | Equity risk weights |
| Art. 134 | Other items |
| Art. 143-154 | IRB approach (PD, LGD, correlation, K formula) |
| Art. 153(2) | FI scalar (1.25x correlation) |
| Art. 153(5) | Slotting approach for specialised lending |
| Art. 155 | Equity IRB simple method (290%/190%/370%) |
| Art. 158-159 | Expected loss and EL shortfall/excess |
| Art. 161-163 | Supervisory LGD values and PD floor (0.03%) |
| Art. 166 | FIRB CCFs |
| Art. 192-241 | Credit risk mitigation (collateral, guarantees) |
| Art. 224 | Supervisory haircuts |
| Art. 230 | Overcollateralisation ratios |
| Art. 233 | FX mismatch haircut (8%) |
| Art. 238 | Maturity mismatch adjustment |
| Art. 501 | SME supporting factor (0.7619/0.85) |
| Art. 501a | Infrastructure supporting factor (0.75) |

## CRR SA Exposure Classes (Art. 112)

1. Central governments and central banks (Art. 114)
2. Regional governments and local authorities (Art. 115)
3. Public sector entities (Art. 116)
4. Multilateral development banks (Art. 117)
5. Institutions (Art. 120-121)
6. Corporates (Art. 122)
7. Retail (Art. 123)
8. Secured by immovable property (Art. 124-126)
9. Defaulted exposures (Art. 127)
10. Equity (Art. 133)
11. Other items (Art. 134)

## Approach Decision Tree

```
Exposure
├── Is it equity? → Equity SA (Art. 133) or IRB Simple (Art. 155)
├── Is it specialised lending without PD model? → Slotting (Art. 153(5))
├── Does the firm have IRB permission for this class?
│   ├── Yes + internal PD available → IRB
│   │   ├── AIRB permission + own LGD? → A-IRB (Art. 153-154)
│   │   └── Otherwise → F-IRB (Art. 153, supervisory LGD Art. 161)
│   └── No (or no internal rating) → SA (Art. 112-134)
└── SA risk weight by exposure class and CQS
```
