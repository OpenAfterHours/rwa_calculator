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

### CRR Scenarios (97 tests)

| Group | Scenarios | Tests | Pass Rate |
|-------|-----------|-------|-----------|
| CRR-A: Standardised Approach | A1–A12 | 14 | 100% |
| CRR-B: Foundation IRB | B1–B13 | 13 | 100% |
| CRR-C: Advanced IRB | C1–C7 | 7 | 100% |
| CRR-D: Credit Risk Mitigation | D1–D9 | 9 | 100% |
| CRR-E: Specialised Lending | E1–E9 | 9 | 100% |
| CRR-F: Supporting Factors | F1–F15 | 15 | 100% |
| CRR-G: Provisions | G1–G17 | 17 | 100% |
| CRR-H: Complex/Combined | H1–H4 | 4 | 100% |
| CRR-I: Defaulted Exposures | I1–I9 | 9 | 100% |
| **Total** | | **97** | **100%** |

### Basel 3.1 Scenarios (116 tests)

| Group | Scenarios | Tests | Pass Rate |
|-------|-----------|-------|-----------|
| B31-A: SA (Revised) | A1–A14 | 14 | 100% |
| B31-B: Foundation IRB | B1–B16 | 16 | 100% |
| B31-C: Advanced IRB | C1–C13 | 13 | 100% |
| B31-D: Credit Risk Mitigation | D1–D15 | 15 | 100% |
| B31-D7: Parameter Substitution | D7.1–D7.5 | 5 | 100% |
| B31-E: Specialised Lending | E1–E13 | 13 | 100% |
| B31-F: Output Floor | F1–F6 | 6 | 100% |
| B31-G: Provisions | G1–G24 | 24 | 100% |
| B31-H: Complex/Combined | H1–H10 | 10 | 100% |
| **Total** | | **116** | **100%** |

### Comparison Scenarios (62 tests)

| Group | Scenarios | Tests | Pass Rate |
|-------|-----------|-------|-----------|
| M3.1: Dual-framework comparison | CRR vs Basel 3.1 | 19 | 100% |
| M3.2: Capital impact analysis | Driver attribution | 24 | 100% |
| M3.3: Transitional floor modelling | Phase-in schedule | 19 | 100% |
| **Total** | | **62** | **100%** |

## Regulatory References

| Reference | URL |
|-----------|-----|
| PRA Rulebook (CRR firms) | https://www.prarulebook.co.uk/pra-rules/crr-firms |
| UK CRR (EU 575/2013) | https://www.legislation.gov.uk/eur/2013/575/contents |
| PRA PS9/24 (Basel 3.1) | https://www.bankofengland.co.uk/prudential-regulation/publication/2024/september/implementation-of-the-basel-3-1-standards-near-final-policy-statement-part-2 |
| BCBS CRE Standards | https://www.bis.org/basel_framework/standard/CRE.htm |
| PRA CP16/22 | https://www.bankofengland.co.uk/prudential-regulation/publication/2022/november/implementation-of-the-basel-3-1-standards |
