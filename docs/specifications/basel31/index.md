# Basel 3.1 Specifications

Formal specifications for the Basel 3.1 (PRA PS1/26) credit risk framework, effective 1 January 2027.

These specifications document the **changes from CRR** introduced by PRA PS1/26 — the UK implementation
of the Basel III final reforms. Where rules are unchanged from CRR, the corresponding
[CRR specification](../crr/sa-risk-weights.md) remains the authoritative reference.

**Primary Regulatory Source:** PRA PS1/26 Appendix 1 (Near-Final Rules)

---

## Specification Index

| Specification | Description | Regulatory Reference | Test Group |
|--------------|-------------|---------------------|------------|
| [SA Risk Weights](sa-risk-weights.md) | Revised SA risk weights: ECRA/SCRA, corporate sub-categories, RE loan-splitting, SA specialised lending | Art. 112–134 | B31-A |
| [Foundation IRB](firb-calculation.md) | Reduced senior LGD (40%), higher PD floor (0.05%), covered bond LGD, 1.06 removal | Art. 153–163 | B31-B |
| [Advanced IRB](airb-calculation.md) | LGD floors, post-model adjustments, CCF floor, double default removal | Art. 153–154, 161, 164, 166D | B31-C |
| [Credit Risk Mitigation](credit-risk-mitigation.md) | Revised 5-band haircut tables, equity haircuts, IRB parameter substitution | Art. 191A–241 | B31-D, B31-D7 |
| [Slotting Approach](slotting-approach.md) | Revised slotting weights, maturity split removal, no pre-op PF distinction | Art. 147(8), 153(5) | B31-E |
| [Output Floor](output-floor.md) | PRA 4-year transitional floor, OF-ADJ capital adjustment | Art. 92(2A)–(2D), Rules 3.1–3.3 | B31-F |
| [Provisions](provisions.md) | EL with revised LGD, Art. 158(6A) monotonicity, shortfall/excess | Art. 158–159 | B31-G |
| [Defaulted Exposures](defaulted-exposures.md) | Provision-coverage split (100%/150%), RESI RE exception, IRB defaulted | Art. 127, 153(1), 154(1) | B31-K |
| [Equity Approach](equity-approach.md) | New SA equity regime (250%/400%), IRB equity removal, transitional phase-in, CIU | Art. 133, 147A, Rules 4.1–4.8 | B31-L |
| [Model Permissions](model-permissions.md) | Art. 147A approach restrictions: FSE, large corporate, institution, equity routing | Art. 147A, 4(1)(146) | B31-M |

## Relationship to CRR Specifications

Each Basel 3.1 specification documents **only the changes** from the CRR framework. For unchanged rules,
refer to the corresponding [CRR specification](../crr/sa-risk-weights.md).

Specifications that have no Basel 3.1 equivalent:

- **Supporting Factors** — SME (Art. 501) and infrastructure (Art. 501a) factors are **removed** under Basel 3.1.
  The SME corporate exposure class (85% RW, Art. 122(4)) replaces the supporting factor mechanism.
- **Credit Conversion Factors** — B31 CCF changes are documented within the [CRR CCF specification](../crr/credit-conversion-factors.md)
  as comparison tables, since the structure is unchanged and only values differ.

## Test Coverage

| Group | Scenarios | Tests | Description |
|-------|-----------|-------|-------------|
| B31-A | A1–A10 | 14 | Standardised Approach |
| B31-B | B1–B7 | 16 | Foundation IRB |
| B31-C | C1–C3 | 13 | Advanced IRB |
| B31-D | D1–D6 | 15 | Credit Risk Mitigation |
| B31-D7 | D7, D7b–D7e | 5 | IRB Parameter Substitution |
| B31-E | E1–E4 | 13 | Slotting Approach |
| B31-F | F1–F3 | 6 | Output Floor |
| B31-G | G1–G3 | 24 | Provisions |
| B31-H | H1, H3 | 10 | Complex/Combined |
| B31-K | K1–K12 | 31 | Defaulted Exposures |
| B31-L | L1–L23 | 49 | Equity Approach |
| B31-M | M1–M12 | 16 | Model Permissions |
| **Total** | **90** | **212** | |
