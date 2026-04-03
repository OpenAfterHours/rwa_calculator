# Basel 3.1 Slotting Changes

Slotting risk weight restructuring from CRR to Basel 3.1.

**Regulatory Reference:** BCBS CRE33, PRA PS1/26

---

## Structural Change

**CRR:** 2-table structure (HVCRE vs non-HVCRE) x 2 maturity bands (< 2.5yr, >= 2.5yr)

**Basel 3.1:** 3-table structure (Operational, PF Pre-Operational, HVCRE), no maturity
differentiation in base weights.

## Basel 3.1 Slotting Tables

### Non-HVCRE Operational (OF, CF, IPRE, PF Operational)

| Category | Risk Weight |
|----------|-------------|
| Strong | 70% |
| Good | 90% |
| Satisfactory | 115% |
| Weak | 250% |
| Default | 0% (EL) |

### Project Finance Pre-Operational

| Category | Risk Weight |
|----------|-------------|
| Strong | 80% |
| Good | 100% |
| Satisfactory | 120% |
| Weak | 350% |
| Default | 0% (EL) |

### HVCRE

| Category | Risk Weight |
|----------|-------------|
| Strong | 95% |
| Good | 120% |
| Satisfactory | 140% |
| Weak | 250% |
| Default | 0% (EL) |

## Subgrades (Residual Maturity-Based)

Within Strong and Good categories, subgrades allow finer differentiation:

| Category | Subgrade A (< 2.5yr) | Subgrade B (>= 2.5yr) |
|----------|----------------------|----------------------|
| Strong A / B | 50% / 70% (PF Op) | 70% / 70% |
| Good C / D | 70% / 90% (PF Op) | 90% / 90% |

## Project Finance Comparison (CRR vs Basel 3.1)

| Category | CRR (>=2.5yr) | CRR (<2.5yr) | B3.1 Pre-Op | B3.1 Operational |
|----------|---------------|--------------|-------------|------------------|
| Strong | 70% | 50% | 80% | 70% |
| Good | 90% | 70% | 100% | 90% |
| Satisfactory | 115% | 115% | 120% | 115% |
| Weak | 250% | 250% | 350% | 250% |
| Default | 0% | 0% | 0% | 0% |

Key change: PF pre-operational gets higher weights than CRR (80%/100%/120%/350%),
while PF operational is broadly unchanged. Weak PF pre-op jumps from 250% to 350%.

---

> **Full detail:** `docs/specifications/crr/slotting-approach.md` and `docs/framework-comparison/technical-reference.md`
