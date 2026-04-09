# Regulatory Compliance Matrix

## CRR (Basel 3.0) — Current UK Rules

| CRR Article | Topic | Status |
|-------------|-------|--------|
| Art. 111 | Credit conversion factors (CCF) | Done |
| Art. 112–134 | SA risk weights by exposure class | Done |
| Art. 120–121 | Institution risk weights (ECAI-based, sovereign-derived) | Done |
| Art. 127 | Defaulted exposure SA (provision-coverage 100%/150%) | Done |
| Art. 132–132B | CIU treatment (fallback, look-through, mandate-based) | Done |
| Art. 133 | Equity SA (flat 100%) | Done |
| Art. 143–154 | IRB approach (F-IRB and A-IRB) | Done |
| Art. 153(5) | Specialised lending slotting | Done |
| Art. 153(1)(ii) | Defaulted exposure F-IRB (K=0) | Done |
| Art. 154(1)(i) | Defaulted exposure A-IRB (K=max(0, LGD−BEEL)) | Done |
| Art. 155 | Equity IRB Simple (290%/190%/370%) | Done |
| Art. 158 | Expected loss by exposure type (omitted from UK CRR by SI 2021/1078; PRA Rulebook) | Done |
| Art. 159 | EL vs provisions comparison (retained in UK CRR) | Done |
| Art. 161–163 | F-IRB supervisory LGD | Done |
| Art. 166 | Off-balance sheet EAD and CCF application | Done |
| Art. 192–241 | Credit risk mitigation framework | Done |
| Art. 207–224 | Collateral eligibility and haircuts | Done |
| Art. 213–217 | Guarantee and credit derivative substitution | Done |
| Art. 224 | Supervisory haircut table | Done |
| Art. 230 | Overcollateralisation ratios (Foundation Collateral Method) | Done |
| Art. 238 | Maturity mismatch adjustment | Done |
| Art. 501 | SME supporting factor (tiered: 0.7619/0.85) | Done |
| Art. 501a | Infrastructure supporting factor (0.75) | Done |

## Basel 3.1 (PRA PS1/26) — Upcoming UK Rules

| PRA PS1/26 Article | Topic | Status |
|---------------------|-------|--------|
| Art. 112, Table A2 | Revised exposure class hierarchy and waterfall | Done |
| Art. 114 | Sovereign SA risk weights | Done |
| Art. 120–121 | Institution SA: ECRA and SCRA (replaces sovereign-derived) | Done |
| Art. 122(5)–(11) | Corporate SA sub-categories (IG 65%, non-IG 135%, SME 85%) | Done |
| Art. 122A–122B | SA specialised lending (rated/unrated, pre-op PF) | Done |
| Art. 123–123A | Retail SA, currency mismatch multiplier (1.5x) | Done |
| Art. 124A–124L | Real estate: loan-splitting, qualifying criteria, LTV bands | Done |
| Art. 127(1)–(1A) | Defaulted SA: provision-coverage split (100%/150%) | Done |
| Art. 129 | Covered bond risk weights (rated Table 6A/Table 7, unrated derivation Art. 129(5)) | Done |
| Art. 132–132B | CIU treatment (fallback 1,250%, mandate-based, look-through) | Done |
| Art. 133 | Equity SA (listed 250%, speculative 400%) | Done |
| Art. 143–154 | IRB approach revisions (PD/LGD floors, 1.06 removal) | Done |
| Art. 147A | Model permissions and approach restrictions | Done |
| Art. 153(5) | Revised slotting weights (maturity split removed) | Done |
| Art. 158–159 | Provisions and EL comparison (Art. 158(6A) monotonicity) | Done |
| Art. 161 | F-IRB supervisory LGD (40% non-FSE senior, 45% FSE) | Done |
| Art. 164(4) | A-IRB LGD floors (25% corporate, 5%–15% retail) | Done |
| Art. 166C–166D | Revised CCF: SA-aligned, full-facility EAD for revolving | Done |
| Art. 191A–241 | Revised CRM: 5-band haircuts, equity 20%/30% | Done |
| Art. 92(2A)–(2D) | Output floor (PRA 4-year: 60%–72.5%, 2027–2030) | Done |
| Rules 4.1–4.8 | Equity transitional schedule (2027–2030) | Done |
| — | Removal of SME supporting factor | Done |
| — | Removal of equity IRB (all equity → SA) | Done |
| — | Removal of 1.06 scaling factor | Done |

## Acceptance Test Summary

### CRR Scenarios (169 tests)

| Group | Scenarios | Tests | Pass Rate |
|-------|-----------|-------|-----------|
| CRR-A: Standardised Approach | A1–A9, A11 | 14 | 100% |
| CRR-B: Foundation IRB | B1–B7 | 13 | 100% |
| CRR-C: Advanced IRB | C1–C3 | 7 | 100% |
| CRR-D: Credit Risk Mitigation | D1–D6 | 9 | 100% |
| CRR-D (Advanced): CRM Advanced | D7–D14, G4–G6 | 36 | 100% |
| CRR-E: Specialised Lending | E1–E8 | 13 | 100% |
| CRR-F: Supporting Factors | F1–F7 | 15 | 100% |
| CRR-G: Provisions | G1–G3 | 17 | 100% |
| CRR-H: Complex/Combined | H1, H3 | 4 | 100% |
| CRR-I: Defaulted Exposures | I1–I3 | 9 | 100% |
| CRR-J: Equity | J1–J20 | 32 | 100% |
| **Total** | **80 scenarios** | **169** | **100%** |

!!! note "CRR-D Advanced scenarios"
    CRR-D7–D14 cover advanced CRM techniques (non-beneficial guarantees, sovereign guarantees, CDS restructuring exclusion, gold/equity collateral, overcollateralisation, full CRM chain, multi-provision). CRR-G4–G6 are additional provision scenarios tested within the same advanced CRM test file. Scenarios A10, A12, H2, and H4 were removed due to fixture restructuring.

### Basel 3.1 Scenarios (212 tests)

| Group | Scenarios | Tests | Pass Rate |
|-------|-----------|-------|-----------|
| B31-A: SA (Revised) | A1–A10 | 14 | 100% |
| B31-B: Foundation IRB | B1–B7 | 16 | 100% |
| B31-C: Advanced IRB | C1–C3 | 13 | 100% |
| B31-D: Credit Risk Mitigation | D1–D6 | 15 | 100% |
| B31-D7: Parameter Substitution | D7–D7e | 5 | 100% |
| B31-E: Specialised Lending | E1–E4 | 13 | 100% |
| B31-F: Output Floor | F1–F3 | 6 | 100% |
| B31-G: Provisions | G1–G3 | 24 | 100% |
| B31-H: Complex/Combined | H1, H3 | 10 | 100% |
| B31-K: Defaulted Exposures | K1–K12 | 31 | 100% |
| B31-L: Equity | L1–L23 | 49 | 100% |
| B31-M: Model Permissions | M1–M12 | 16 | 100% |
| **Total** | **90 scenarios** | **212** | **100%** |

### Comparison Scenarios (60 tests)

| Group | Scenarios | Tests | Pass Rate |
|-------|-----------|-------|-----------|
| M3.1: Dual-framework comparison | CRR vs Basel 3.1 | 19 | 100% |
| M3.2: Capital impact analysis | Driver attribution | 24 | 100% |
| M3.3: Transitional floor modelling | Phase-in schedule | 17 | 100% |
| **Total** | | **60** | **100%** |

### Stress Tests (60 tests)

See the [Stress Testing Specification](common/stress-testing.md) for full scenario definitions (STRESS-1 to STRESS-14).

| Group | Description | Tests | Pass Rate |
|-------|-------------|-------|-----------|
| STRESS-1 | Row count preservation | 8 | 100% |
| STRESS-2 | Column completeness | 4 | 100% |
| STRESS-3 | Numerical stability (no NaN/Inf/negative) | 10 | 100% |
| STRESS-4 | Risk weight bounds [0%, 1250%] | 4 | 100% |
| STRESS-5 | Approach distribution (SA/IRB routing) | 5 | 100% |
| STRESS-6 | Exposure class coverage | 4 | 100% |
| STRESS-7 | Output floor at scale | 7 | 100% |
| STRESS-8 | Error accumulation (bounded) | 4 | 100% |
| STRESS-9 | Summary consistency | 2 | 100% |
| STRESS-10 | EAD consistency | 4 | 100% |
| STRESS-11 | Determinism | 1 | 100% |
| STRESS-12 | Framework comparison | 1 | 100% |
| STRESS-13 | Large scale 100K (slow) | 4 | 100% |
| STRESS-14 | Reference uniqueness | 2 | 100% |
| **Total** | | **60** | **100%** |

### Overall Acceptance Test Summary

| Category | Groups | Scenarios | Tests |
|----------|--------|-----------|-------|
| CRR | 11 | 80 | 169 |
| Basel 3.1 | 12 | 90 | 212 |
| Comparison | 3 | — | 60 |
| Stress | 14 | — | 60 |
| **Total** | **40** | **170+** | **501** |

The full test suite includes 5,034 tests across unit (4,232), acceptance (501), contracts (145), integration (122), and benchmarks (34).

## Regulatory References

| Reference | URL |
|-----------|-----|
| PRA Rulebook (CRR firms) | https://www.prarulebook.co.uk/pra-rules/crr-firms |
| UK CRR (EU 575/2013) | https://www.legislation.gov.uk/eur/2013/575/contents |
| PRA PS1/26 (Basel 3.1) | https://www.bankofengland.co.uk/prudential-regulation/publication/2026/january/implementation-of-the-basel-3-1-final-rules-policy-statement |
| BCBS CRE Standards | https://www.bis.org/basel_framework/standard/CRE.htm |
| PS1/26 Appendix 1 | https://www.bankofengland.co.uk/-/media/boe/files/prudential-regulation/policy-statement/2026/january/ps126app1.pdf |
| PS1/26 Appendix 17 | https://www.bankofengland.co.uk/-/media/boe/files/prudential-regulation/policy-statement/2026/january/ps126app17.pdf |
