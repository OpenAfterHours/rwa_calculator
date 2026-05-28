# Counterparty Credit Risk (SA-CCR) — Basel 3.1

Cross-reference page. The Standardised Approach for Counterparty Credit
Risk (SA-CCR) under PRA PS1/26 is **inherited unchanged** from the
onshored CRR text — Part Three, Title II, Chapter 6 (Art. 271–311) is a
verbatim re-export with the Basel 3.1 calibration (α = 1.4 default,
unchanged supervisory factors at Art. 280 Table 1) retained. There are
no Basel 3.1 SA-CCR per-article specs in this directory because there
are no per-article rule changes — only two cross-framework deltas worth
flagging at the Basel 3.1 layer (the Art. 274(2) α carve-out wording and
the explicit Art. 92(2A) output-floor inclusion of SA-CCR EAD).

!!! info "Calculator parity by default"
    Calculator behaviour is identical between CRR and Basel 3.1 modes
    for the SA-CCR EAD chain (`compute_adjusted_notional_*` →
    `compute_supervisory_delta_*` → `compute_maturity_factor_*` →
    `assign_hedging_set` → `compute_addon_per_asset_class` →
    `compute_rc_unmargined` → `compute_pfe` → `compute_ead`). No
    separate Basel 3.1 per-article specs exist. The canonical
    regulatory content lives under
    [SA-CCR (CRR)](../crr/ccr/index.md) — readers go there for
    formulas, tables, hedging-set partition rules, supervisory
    factors, and worked CCR-A1 / CCR-A2 acceptance scenarios.

**Primary regulatory source:** PRA PS1/26 Part Three Title II Chapter 6
(Art. 271–311) — Counterparty Credit Risk (CRR) Part, Annex R. The
SA-CCR regime is a verbatim re-export of the onshored CRR text.

---

## Basel 3.1-specific deltas

### (a) α-factor carve-out for non-financial counterparties (Art. 274(2))

PS1/26 retains the SA-CCR exposure-value formula `EAD = α × (RC + PFE)`
from CRR Art. 274(2), with α = 1.4 as the default scalar. The verbatim
text (PS1/26 Annex R, Counterparty Credit Risk (CRR) Part, p. 456;
source PDF `docs/assets/ps126app1.pdf`) is:

> "Institutions shall calculate the exposure value of a netting set
> under the standardised approach for counterparty credit risk as
> follows:
>
>     Exposure value = α · (RC + PFE)
>
> where:
>
> - RC = the replacement cost calculated in accordance with Article 275; and
> - PFE = the potential future exposure calculated in accordance with Article 278;
> - α = 1.4, unless the counterparty is a non-financial counterparty or
>   a pension scheme arrangement or an entity established to provide
>   compensation to members of a pension scheme arrangement in case of
>   default, in which case, α = 1."

The α = 1 carve-out applies to derivative contracts with:

- **non-financial counterparties** below the EMIR clearing threshold,
  as defined in Regulation (EU) No 648/2012 Art. 2(9);
- **pension scheme arrangements** as defined in EMIR Art. 2(10); and
- entities established to provide **default compensation to members of
  a pension scheme arrangement**.

Removing the 1.4 calibration uplift reduces SA-CCR EAD (and the
corresponding RWA) for in-scope end-user counterparties by a factor of
`1 / 1.4 ≈ 0.714` — see the worked sensitivity at
[`crr/ccr/ead-composition.md#sensitivity-to-α`](../crr/ccr/ead-composition.md#sensitivity-to-α-what-happens-if-the-carve-out-fires).

!!! warning "Engine status — α = 1 carve-out gate not yet wired"
    The α value is configurable via `CCRConfig.alpha` (defaults to
    `Decimal("1.4")` at `src/rwa_calc/contracts/config.py`), and the
    composition function at
    `src/rwa_calc/engine/ccr/sa_ccr.py::compute_ead` applies whatever
    α is supplied uniformly across the input frame. However, the
    **per-counterparty dispatch gate** that would route non-financial
    counterparty / pension-scheme netting sets through `α = 1` while
    keeping the rest at `α = 1.4` is **not yet implemented** in
    `engine/ccr/pipeline_adapter.py::ccr_rows_to_exposures` —
    today's orchestrator applies the default `α = 1.4` to every
    netting set. Firms requiring the carve-out must invoke
    `compute_ead` twice with two `CCRConfig` instances and
    concatenate the results. Tracked in the project root
    `IMPLEMENTATION_PLAN.md` as a documented engine gap; the math
    itself is exercised by the `CCRConfig.alpha` override hook.

The companion Art. 274(2A) **transitional alpha add-on** for legacy
CVA-exempt trades (60% → 40% → 20% phase-in over 2027–2029) is
documented on the CRR EAD-composition page and remains a separate
engine gap — see
[`crr/ccr/ead-composition.md#pending`](../crr/ccr/ead-composition.md#pending-engine-gaps-documented-here).

### (b) Output-floor inclusion of SA-CCR EAD (Art. 92(2A))

Under PS1/26 Art. 92(2A) the SA-CCR EAD contributes to **both** legs of
the output-floor TREA comparison:

```
TREA = max{U-TREA; x × S-TREA + OF-ADJ}
```

- **U-TREA leg (Art. 92(3))** — the IRB-permissioned firm risk-weights
  the synthetic CCR exposure row (`risk_type = "CCR_DERIVATIVE"`)
  through IRB if the counterparty has an IRB model; otherwise SA. The
  resulting RWA enters U-TREA directly.
- **S-TREA leg (Art. 92(3A))** — the same synthetic CCR row is
  re-run through the SA risk-weight calculator (IRB explicitly
  disallowed for S-TREA), producing an SA-equivalent RWA that enters
  S-TREA. **The SA-CCR EAD itself does not change between the two
  legs** — only the downstream risk-weight lookup changes. Art.
  92(3A) explicitly lists IRB, SFT VaR, SEC-IRBA, IAA, IMM, and IMA
  as the modelled approaches excluded from S-TREA; SA-CCR is **not**
  on that exclusion list and therefore feeds both legs unchanged.

The α = 1.4 multiplier therefore amplifies the floor impact for IRB
firms whose IRB CCR EAD methodology (IMM, if permissioned) would
otherwise produce a lower exposure number than SA-CCR. Conversely, an
IRB firm using SA-CCR for its U-TREA leg sees identical EAD in both
legs — only the risk weight differs.

See [`output-floor.md`](output-floor.md#floor-calculation) for the
full TREA formula, the PRA 4-year transitional schedule
(60% → 65% → 70% → 72.5% per Art. 92(5)), and the OF-ADJ
own-funds adjustment. See
[`crr/ccr/ead-composition.md#interaction-with-the-basel-31-output-floor`](../crr/ccr/ead-composition.md#interaction-with-the-basel-31-output-floor)
for the engine-side routing of the synthetic CCR row into both legs.

---

## CRR per-article specifications (canonical content)

The complete SA-CCR rule set — formulas, hedging-set partition rules,
supervisory factors, worked CCR-A acceptance scenarios — lives on the
CRR per-article pages. The two deltas above are the **only** Basel 3.1
overlays; everything else is unchanged.

- [SA-CCR (CRR) overview](../crr/ccr/index.md) — pipeline shape, asset-class coverage, scenario roadmap
- [Adjusted notional](../crr/ccr/adjusted-notional.md) — Art. 279b per-asset-class `d`
- [Supervisory delta](../crr/ccr/supervisory-delta.md) — Art. 279a linear ±1 / option Φ(d1) / CDO tranche
- [Maturity factor](../crr/ccr/maturity-factor.md) — Art. 279c unmargined, Art. 285 margined
- [Hedging sets](../crr/ccr/hedging-sets.md) — Art. 277 / 277a partition and correlations
- [Replacement cost (RC)](../crr/ccr/rc-calculation.md) — Art. 275 unmargined / margined
- [PFE multiplier](../crr/ccr/pfe-multiplier.md) — Art. 278 add-on aggregation and multiplier
- [EAD composition](../crr/ccr/ead-composition.md) — Art. 274(2) α × (RC + PFE) and downstream routing
- [Legal enforceability](../crr/ccr/legal-enforceability.md) — Art. 272(4), 295–297 netting-set gate
- [Wrong-way risk](../crr/ccr/wrong-way-risk.md) — Art. 291 specific (LGD = 100%) / general WWR
- [CCP exposures](../crr/ccr/ccp-exposures.md) — Art. 306–311 QCCP 2% trade-leg / non-QCCP fallback
- [FX treatment](../crr/ccr/fx-treatment.md) — Art. 277(3)(a), 279b(1)(b), 277a(2) FX hedging set / CCR-A2 worked example
- [Failed trades](../crr/ccr/failed-trades.md) — Art. 378–380 DvP unsettled / free deliveries multiplier ladder

---

## References

- **PRA PS1/26 Part Three Title II Chapter 6 (Art. 271–311)** —
  Counterparty Credit Risk (CRR) Part, Annex R. UK SA-CCR regime;
  verbatim re-export of onshored CRR text, no per-article changes
  versus CRR.
- **PRA PS1/26 Art. 274(2)** — `Exposure value = α × (RC + PFE)`,
  α = 1.4 default, α = 1 carve-out for non-financial counterparties /
  pension scheme arrangements / pension-default compensation entities.
- **PRA PS1/26 Art. 92(2A)** — output-floor TREA formula
  `TREA = max{U-TREA; x × S-TREA + OF-ADJ}` consuming SA-CCR EAD in
  both legs via the synthetic CCR exposure row.
- **PRA PS1/26 Art. 92(3A)** — S-TREA calculated without IRB, SFT VaR,
  SEC-IRBA, IAA, IMM, or IMA; SA-CCR is **not** on the exclusion list.
- **PRA PS1/26 Art. 92(5)** — output-floor 4-year transitional schedule
  (60% / 65% / 70% / 72.5%).
- **Regulation (EU) No 648/2012 (EMIR) Art. 2(9), Art. 2(10)** —
  definitions of "non-financial counterparty" and "pension scheme
  arrangement" underpinning the Art. 274(2) α = 1 carve-out.
- **BCBS CRE52.1–52.5** — Basel-level SA-CCR methodology and α = 1.4
  calibration rationale.
- **[Output floor (Basel 3.1)](output-floor.md)** — full TREA formula,
  PRA transitional schedule, OF-ADJ own-funds adjustment.
- **[SA-CCR (CRR) — EAD composition](../crr/ccr/ead-composition.md)** —
  engine entry point, `CCRConfig.alpha` override hook, synthetic
  exposure-row contract, CCR-A1 worked example, and pending engine
  gaps (Art. 274(2) carve-out dispatch, Art. 274(2A) transitional
  alpha add-on, Art. 274(2B) leverage-ratio exclusion).
