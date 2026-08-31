# CRR Provisions & Expected Loss

**Regulatory Reference:** CRR Articles 110, 111(1)(a)-(b), 158-159

> Values are generated from the rulepack — see the table below. Regenerate with
> `uv run python scripts/generate_regulatory_tables.py`.

---

## Pipeline position

Provisions are resolved **before** CCF application:

```
resolve_provisions -> CCF -> initialize_ead -> collateral -> guarantees -> finalize_ead
```

## Multi-level beneficiary resolution

| Level | Description |
|-------|-------------|
| Direct | Matched to a specific exposure (loan / exposure / contingent) |
| Facility | Distributed pro-rata across the facility's exposures by `ead_gross` |
| Counterparty | Distributed pro-rata across all counterparty exposures by `ead_gross` |

Direct allocations are applied first; facility and counterparty amounts are then
distributed proportionally over what remains.

## SA treatment (Art. 110, 111(1)(a)-(b))

Drawn-first deduction:

```
provision_on_drawn      = min(provision_allocated, max(0, drawn_amount))
provision_on_nominal    = min(remainder, nominal_amount)
nominal_after_provision = nominal_amount - provision_on_nominal
ead_from_ccf            = nominal_after_provision x CCF
EAD = (max(0, drawn) - provision_on_drawn) + interest + ead_from_ccf
```

`finalize_ead()` does **not** subtract provisions again — they are already baked into
`ead_pre_crm`.

## IRB / Slotting treatment (Art. 158-159)

Provisions are tracked in `provision_allocated` but **not deducted** from EAD;
`provision_deducted`, `provision_on_drawn` and `provision_on_nominal` are all zero.
Expected loss carries the effect instead: `EL = PD x LGD x EAD`.

### EL vs provisions

| Outcome | Treatment | Reference |
|---------|-----------|-----------|
| EL above provisions (shortfall) | Split deduction from CET1 and T2 | Art. 159 |
| EL below provisions (excess) | Added to T2, subject to the Art. 62(d) cap | Art. 62(d) |

The Art. 62(d) cap is an **own-funds composition** limit, not an RWA parameter — it sits
outside this engine and therefore outside the rulepack.

## Defaulted-exposure thresholds

The SA defaulted risk weight turns on provisions as a proportion of the exposure **plus
the provision already deducted**. Both regimes' thresholds are below.

<!-- BEGIN GENERATED: crr-provisions-values -->
| Name | CRR | Basel 3.1 | Citation |
|---|---|---|---|
| `crr_defaulted_provision_threshold` | `0.20` | — | CRR Art. 127 |
| `crr_defaulted_rw_high_provision` | `1.00` | — | CRR Art. 127 |
| `crr_defaulted_rw_low_provision` | `1.50` | — | CRR Art. 127 |
| `b31_defaulted_provision_threshold` | — | `0.20` | PS1/26, paragraph 127 |
| `b31_defaulted_rw_high_provision` | — | `1.00` | PS1/26, paragraph 127 |
| `b31_defaulted_rw_low_provision` | — | `1.50` | PS1/26, paragraph 127 |
| `sa_revised_defaulted_treatment` | off | on | CRR Art. 127 / PS1/26, paragraph 127 |
<!-- END GENERATED: crr-provisions-values -->

---

> **Full detail:** `docs/specifications/crr/provisions.md`
> **All pack entries:** `docs/data-model/regulatory-tables.md`
