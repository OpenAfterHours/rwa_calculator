# CRR Supporting Factors

**Regulatory Reference:** CRR Articles 501, 501a

**CRR only** — supporting factors are withdrawn under Basel 3.1 (`supporting_factors`
turns off), which is a material part of the SME capital increase.

> Values are generated from the rulepack — see the table below. Regenerate with
> `uv run python scripts/generate_regulatory_tables.py`.

---

## SME Supporting Factor (Art. 501)

**Eligibility:** the counterparty is classified Corporate SME and group turnover is below
the `regulatory_thresholds` SME test.

**Tiered application:** a lower factor applies up to the Art. 501 exposure threshold and a
higher one above it, blended where an exposure spans both tiers:

```
SF = [min(D, threshold) x tier1_factor + max(D - threshold, 0) x tier2_factor] / D
```

D is the on-balance-sheet amount aggregated **at counterparty level**, not per exposure —
a common source of hand-calc mismatch.

## Infrastructure Supporting Factor (Art. 501a)

A flat factor for qualifying infrastructure lending, applied regardless of exposure size.
The exposure must be flagged `is_infrastructure = true`.

Art. 501a is one of the few alphanumeric CRR articles the citation index covers — cite it
as `501a`, not as a PS1/26 paragraph.

## Combined application

Where both factors apply the calculator takes the **minimum** (most beneficial) factor —
they do not compound.

<!-- BEGIN GENERATED: crr-supporting-factors -->
| Name | CRR | Basel 3.1 | Citation |
|---|---|---|---|
| `supporting_factors` | on | off | CRR Art. 501 / PS1/26, paragraph 501 |

### `supporting_factors_values`

**CRR** — CRR Art. 501
 *(SME 0.7619/0.85 + infrastructure 0.75 multipliers)*

| Parameter | Value |
|---|---|
| `sme_factor_under_threshold` | `0.7619` |
| `sme_factor_above_threshold` | `0.85` |
| `infrastructure_factor` | `0.75` |

**Basel 3.1** — PS1/26, paragraph 501
 *(supporting factors removed (all 1.0))*

| Parameter | Value |
|---|---|
| `sme_factor_under_threshold` | `1.0` |
| `sme_factor_above_threshold` | `1.0` |
| `infrastructure_factor` | `1.0` |

### `regulatory_thresholds`

**CRR** — CRR Art. 123
 *(EUR monetary thresholds (× EUR/GBP rate → GBP))*

| Parameter | Value |
|---|---|
| `sme_turnover_threshold` | `50000000` |
| `sme_balance_sheet_threshold` | `43000000` |
| `sme_exposure_threshold` | `2500000` |
| `large_corporate_revenue_threshold` | `0` |
| `retail_max_exposure` | `1000000` |
| `qrre_max_limit` | `100000` |
| `lfse_total_assets_threshold` | `70000000000` |

**Basel 3.1** — PS1/26, paragraph 147
 *(PRA-native GBP thresholds (sme_balance_sheet frozen))*

| Parameter | Value |
|---|---|
| `sme_turnover_threshold` | `44000000` |
| `sme_balance_sheet_threshold` | `37547600` |
| `sme_exposure_threshold` | `0` |
| `large_corporate_revenue_threshold` | `440000000` |
| `retail_max_exposure` | `880000` |
| `qrre_max_limit` | `90000` |
| `lfse_total_assets_threshold` | `79000000000` |

| Name | CRR | Basel 3.1 | Citation |
|---|---|---|---|
| `regulatory_thresholds_fx_derived` | on | off | CRR Art. 123 / PS1/26, paragraph 147 |
<!-- END GENERATED: crr-supporting-factors -->

---

> **Full detail:** `docs/specifications/crr/supporting-factors.md`
> **All pack entries:** `docs/data-model/regulatory-tables.md`
