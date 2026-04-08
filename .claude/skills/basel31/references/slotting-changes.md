# Basel 3.1 Slotting Changes

Slotting risk weight restructuring from CRR to Basel 3.1.

**Regulatory Reference:** BCBS CRE33, PRA PS1/26

---

## Structural Change

**CRR:** 2-table structure (HVCRE vs non-HVCRE) x 2 maturity bands (< 2.5yr, >= 2.5yr)

**Basel 3.1 (PRA):** 2-table structure (Non-HVCRE, HVCRE), no maturity
differentiation in base weights. PRA does not adopt the BCBS separate pre-operational
PF table — all non-HVCRE specialised lending (including PF pre-operational) uses the
standard non-HVCRE table.

## Basel 3.1 Slotting Tables

### Non-HVCRE (OF, CF, IPRE, PF — including pre-operational)

| Category | Risk Weight |
|----------|-------------|
| Strong | 70% |
| Good | 90% |
| Satisfactory | 115% |
| Weak | 250% |
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

## Project Finance Comparison (CRR vs Basel 3.1 PRA)

| Category | CRR (>=2.5yr) | CRR (<2.5yr) | B3.1 (PRA) |
|----------|---------------|--------------|------------|
| Strong | 70% | 50% | 70% |
| Good | 90% | 70% | 90% |
| Satisfactory | 115% | 115% | 115% |
| Weak | 250% | 250% | 250% |
| Default | 0% | 0% | 0% |

Key change: PRA removes maturity differentiation — the CRR short-maturity discount
(50%/70% for Strong/Good at <2.5yr) is eliminated. All PF uses the single non-HVCRE table.

---

> **Full detail:** `docs/specifications/crr/slotting-approach.md` and `docs/framework-comparison/technical-reference.md`
