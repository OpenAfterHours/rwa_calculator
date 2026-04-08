# CRR Provisions & Expected Loss

Quick-reference for provision treatment under SA and IRB.

**Regulatory Reference:** CRR Articles 110, 111(1)(a)-(b), 158-159

---

## Pipeline Position

Provisions are resolved **before** CCF application:

```
resolve_provisions -> CCF -> initialize_ead -> collateral -> guarantees -> finalize_ead
```

## Multi-Level Beneficiary Resolution

| Level | Description |
|-------|-------------|
| Direct | Matched to a specific exposure (loan/exposure/contingent) |
| Facility | Distributed pro-rata across facility's exposures by ead_gross |
| Counterparty | Distributed pro-rata across all counterparty exposures by ead_gross |

Direct allocations applied first; facility and counterparty distributed proportionally.

## SA Approach (Art. 110, 111(1)(a)-(b))

Drawn-first deduction:

```
provision_on_drawn    = min(provision_allocated, max(0, drawn_amount))
provision_on_nominal  = min(remainder, nominal_amount)
nominal_after_provision = nominal_amount - provision_on_nominal
ead_from_ccf          = nominal_after_provision x CCF
EAD = (max(0, drawn) - provision_on_drawn) + interest + ead_from_ccf
```

`finalize_ead()` does NOT subtract provisions again (already baked into ead_pre_crm).

## IRB / Slotting Approach (Art. 158-159)

Provisions are tracked (`provision_allocated`) but **not deducted** from EAD.

```
provision_deducted = 0
provision_on_drawn = 0
provision_on_nominal = 0
```

Instead, Expected Loss is computed: `EL = PD x LGD x EAD`

### EL vs Provisions Comparison

| Outcome | Treatment | Reference |
|---------|-----------|-----------|
| EL > Provisions (shortfall) | 50/50 deduction from CET1 and T2 | Art. 159 |
| EL < Provisions (excess) | Added to T2, capped at 0.6% of IRB RWA | Art. 62(d) |

---

> **Full detail:** `docs/specifications/crr/provisions.md`
