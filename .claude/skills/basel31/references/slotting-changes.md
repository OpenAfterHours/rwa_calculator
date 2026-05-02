# Basel 3.1 Slotting Changes

Slotting risk weight restructuring from CRR to Basel 3.1.

**Regulatory Reference:** BCBS CRE33, PRA PS1/26

---

## Structural Change

**UK CRR:** Single Non-HVCRE table (Art. 153(5) Table 1) with 2 maturity bands (>=2.5yr / <2.5yr).
HVCRE has **no UK legal basis** — the EU CRR Table 2 was not retained in UK onshoring.

**Basel 3.1 (PRA):** Two tables (Non-HVCRE and HVCRE), each with the same 2-maturity-band
structure (columns B/D for >=2.5yr default, columns A/C optional for <2.5yr). The maturity
discount is preserved on both tables. The PRA-specific changes are:
- **HVCRE re-introduced** as a distinct table (PS1/26 Art. 153(5) Table A), elevated weights
  vs Non-HVCRE.
- **PF consolidated** under Non-HVCRE — PRA does not adopt the BCBS separate pre-operational
  PF table; PF pre-operational uses the standard Non-HVCRE table.

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

Within Strong and Good categories, subgrades A/B/C/D differentiate by residual maturity
(A/C are <2.5yr, B/D are >=2.5yr):

| Exposure Type | Strong A | Strong B | Good C | Good D |
|---------------|----------|----------|--------|--------|
| OF, CF, PF, IPRE | 50% | 70% | 70% | 90% |
| HVCRE | 70% | 95% | 95% | 120% |

Source: `docs/specifications/basel31/slotting-approach.md` lines 137–140.

## Project Finance Comparison (CRR vs Basel 3.1 PRA)

| Category | CRR (>=2.5yr) | CRR (<2.5yr) | B3.1 (PRA) |
|----------|---------------|--------------|------------|
| Strong | 70% | 50% | 70% |
| Good | 90% | 70% | 90% |
| Satisfactory | 115% | 115% | 115% |
| Weak | 250% | 250% | 250% |
| Default | 0% | 0% | 0% |

Key change: PRA consolidates PF (including pre-operational) under the standard Non-HVCRE table — no BCBS-style pre-operational PF carve-out. The CRR short-maturity Strong/Good discount (50% / 70%) is preserved for both Non-HVCRE and HVCRE via the column A/C subgrade structure.

---

> **Full detail:** `docs/specifications/crr/slotting-approach.md` and `docs/framework-comparison/technical-reference.md`
