# Regulatory Compliance Matrix

## CRR (Basel 3.0) — Current UK Rules

| CRR Article | Topic | Status |
|-------------|-------|--------|
| Art. 111 | Credit conversion factors (CCF) | Done |
| Art. 112–134 | SA risk weights by exposure class | Done |
| Art. 143–154 | IRB approach (F-IRB and A-IRB) | Done |
| Art. 153(5) | Specialised lending slotting | Done |
| Art. 155 | Equity IRB Simple | Done |
| Art. 133 | Equity SA | Done |
| Art. 161–163 | F-IRB supervisory LGD | Done |
| Art. 153(1)(ii) | Defaulted exposure F-IRB (K=0) | Done |
| Art. 154(1)(i) | Defaulted exposure A-IRB (K=max(0, LGD−BEEL)) | Done |
| Art. 207–224 | Collateral eligibility and haircuts | Done |
| Art. 213 | Guarantee substitution | Done |
| Art. 224 | Supervisory haircut table | Done |
| Art. 230 | Overcollateralisation ratios | Done |
| Art. 238 | Maturity mismatch adjustment | Done |
| Art. 501 | SME supporting factor (tiered) | Done |
| Art. 501a | Infrastructure supporting factor | Done |

## Basel 3.1 (PRA PS9/24) — Upcoming UK Rules

| BCBS Standard | Topic | Status |
|---------------|-------|--------|
| CRE20.7–26 | SA risk weights (revised: SCRA, investment-grade, subordinated) | Done |
| CRE20.71 | LTV-based residential RE risk weights | Done |
| CRE30–36 | IRB approach revisions | Done |
| CRE32.9–12 | Overcollateralisation (carried forward) | Done |
| CRE32 | A-IRB LGD floors | Done |
| — | Differentiated PD floors | Done |
| — | Output floor (50%–72.5% phase-in) | Done |
| — | Removal of 1.06 scaling factor | Done |
| — | Removal of SME supporting factor | Done |
| — | Removal of equity IRB | Done |

## Acceptance Test Summary

### CRR Scenarios (91 tests)

| Group | Scenarios | Tests | Pass Rate |
|-------|-----------|-------|-----------|
| CRR-A: Standardised Approach | A1–A12 | 14 | 100% |
| CRR-C: Advanced IRB | C1–C3 | 7 | 100% |
| CRR-D: Credit Risk Mitigation | D1–D6 | 9 | 100% |
| CRR-E: Specialised Lending | E1–E4 | 9 | 100% |
| CRR-F: Supporting Factors | F1–F7 | 15 | 100% |
| CRR-G: Provisions | G1–G3 | 7 | 100% |
| CRR-H: Complex/Combined | H1–H4 | 4 | 100% |
| CRR-I: Defaulted Exposures | I1–I3 | 9 | 100% |
| Additional CRR scenarios | | 17 | 100% |
| **Total** | | **91** | **100%** |

### Basel 3.1 Scenarios (112 tests)

| Group | Scenarios | Tests | Pass Rate |
|-------|-----------|-------|-----------|
| B31-A: SA (Revised) | A1–A10+ | 112 | 100% |
| B31-F: Output Floor | F1–F3 | 6 | 100% |
| **Total** | | **112** | **100%** |

### Comparison Scenarios (62 tests)

| Group | Scenarios | Tests | Pass Rate |
|-------|-----------|-------|-----------|
| Dual-framework comparison (M3.1) | CRR vs Basel 3.1 | 62 | 100% |
| Capital impact analysis (M3.2) | Driver attribution | included | 100% |
| Transitional floor modelling (M3.3) | Phase-in schedule | included | 100% |
| **Total** | | **62** | **100%** |

## Regulatory References

| Reference | URL |
|-----------|-----|
| PRA Rulebook (CRR firms) | https://www.prarulebook.co.uk/pra-rules/crr-firms |
| UK CRR (EU 575/2013) | https://www.legislation.gov.uk/eur/2013/575/contents |
| PRA PS9/24 (Basel 3.1) | https://www.bankofengland.co.uk/prudential-regulation/publication/2024/september/implementation-of-the-basel-3-1-standards-near-final-policy-statement-part-2 |
| BCBS CRE Standards | https://www.bis.org/basel_framework/standard/CRE.htm |
| PRA CP16/22 | https://www.bankofengland.co.uk/prudential-regulation/publication/2022/november/implementation-of-the-basel-3-1-standards |
