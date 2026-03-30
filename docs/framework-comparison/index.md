# CRR vs Basel 3.1

UK firms transition from CRR to Basel 3.1 (PRA PS1/26) on 1 January 2027, with the output
floor phasing in through 2032. This section brings together all framework comparison content
in one place.

## At a Glance

| Area | CRR (until 31 Dec 2026) | Basel 3.1 (from 1 Jan 2027) |
|------|-------------------------|----------------------------|
| **1.06 Scaling Factor** | Applied to all IRB RWA | Removed |
| **Output Floor** | None | 72.5% of SA (phased from 50%) |
| **SME Supporting Factor** | 0.7619 / 0.85 tiered | Removed |
| **Infrastructure Factor** | 0.75 | Removed |
| **PD Floors** | 0.03% uniform | Differentiated (0.03%–0.10%) |
| **A-IRB LGD Floors** | None | Yes (5%–50% by collateral) |
| **IRB Restrictions** | F-IRB or A-IRB for all | Large corp/bank/financial sector: F-IRB only; equity: SA only |
| **SA Risk Weights** | Flat per CQS | LTV-based RE, revised corporate weights |
| **Retail Risk Weights** | Flat 75% | Differentiated: 45% transactor, 35% payroll/pension |
| **Equity Risk Weights** | 100% (standard) | 250%/400% (with transitional phase-in) |
| **CCF (Unconditionally Cancellable)** | 0% | 10% |
| **Haircuts (Equities)** | 15% / 25% | 25% / 35% |
| **Currency Mismatch** | None | 1.5x RW multiplier for unhedged FX retail/RE |
| **CRM Methods** | Scattered provisions | Foundation Collateral Method, Parameter Substitution |
| **COREP Templates** | C prefix (C 07.00, C 08.01–08.07, C 09.01–09.02) | OF prefix (OF 07.00, OF 08.01–08.07, OF 09.01–09.02) |

## In This Section

<div class="grid cards" markdown>

-   **[Key Differences](key-differences.md)**

    ---

    Comprehensive side-by-side comparison of all regulatory parameters — risk weights,
    IRB floors, supporting factors, CCFs, slotting, and capital impact analysis.

-   **[Reporting Differences](reporting-differences.md)**

    ---

    COREP template changes — column additions and removals, expanded risk weight bands,
    new real estate breakdowns, output floor columns, and post-model adjustments.

-   **[Disclosure Differences](disclosure-differences.md)**

    ---

    Pillar III disclosure template changes — OV1 output floor rows, CR5 expanded risk
    weight columns, CR6 post-model adjustments, CR7-A slotting CRM, CR10 HVCRE split.

-   **[Impact Analysis](impact-analysis.md)**

    ---

    Dual-framework comparison tooling, capital impact attribution waterfall, and
    transitional output floor schedule modelling.

-   **[Technical Reference](technical-reference.md)**

    ---

    Developer-facing specification of parameter differences — PD/LGD floors, supervisory
    LGD, slotting weights, and configuration examples.

</div>

## Quick Links

- [CRR framework details](../user-guide/regulatory/crr.md)
- [Basel 3.1 framework details](../user-guide/regulatory/basel31.md)
- [Full COREP template specifications](../features/corep-reporting.md)
- [Full Pillar III disclosure specifications](../features/pillar3-disclosures.md)
- [Configuration guide](../user-guide/configuration.md)
