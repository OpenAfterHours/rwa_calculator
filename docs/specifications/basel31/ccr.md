# Counterparty Credit Risk (SA-CCR) — Basel 3.1

Cross-reference page. The Standardised Approach for Counterparty Credit
Risk (SA-CCR) under PRA PS1/26 is **inherited unchanged** from the
onshored CRR text — Part Three, Title II, Chapter 6 (Art. 271–311) is a
verbatim re-export with the Basel 3.1 calibration (α = 1.4 default,
unchanged supervisory factors at Art. 280 Table 1) retained. There are
no Basel 3.1 SA-CCR per-article specs in this directory because there
are no per-article rule changes — only two cross-framework deltas worth
flagging at the Basel 3.1 layer (the Art. 274(2) α carve-out wording and
the explicit Art. 92(2A) output-floor inclusion of SA-CCR EAD), plus the
netting-set inputs the Basel 3.1 BA-CVA charge reads from SA-CCR.

!!! info "Calculator parity by default"
    Calculator behaviour is identical between CRR and Basel 3.1 modes
    for the SA-CCR EAD chain — except the supervisory alpha, where the
    Art. 274(2) α = 1 carve-out and the Art. 274(2A) add-on apply under
    Basel 3.1 only (delta (a) below) — (`compute_adjusted_notional_*` →
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

!!! info "Engine status — carve-out wired, Basel 3.1 only"
    `engine/ccr/pipeline_adapter.py::ccr_rows_to_exposures` joins the
    counterparty's `counterparty_type` onto each netting set and sets
    `alpha_applied = 1` for `non_financial`, `pension_scheme` and
    `pension_default_comp` counterparties, `1.4` otherwise. The selection is
    gated by the cited pack Feature `sa_ccr_alpha_nfc_carve_out_applicable`,
    which is **on under Basel 3.1 and off under CRR**: the CCR (CRR) Part in
    force to 31 December 2026 says only "α = 1.4", and the carve-out sentence
    above is new, underlined PS1/26 text. A CRR run therefore applies α = 1.4
    to every netting set (review CC-01 — before it, the carve-out leaked into
    CRR and understated an NFC netting set's EAD by 28.6%).

!!! note "Engine status — α per netting set"
    The SA-CCR adapter (`engine/ccr/pipeline_adapter.py`) joins the
    counterparty's `counterparty_type` onto each netting set and reduces
    it to an `alpha_applied` scalar (1 for a non-financial or
    pension-scheme counterparty, 1.4 otherwise; an absent type reads as
    1.4). `compute_pfe` / `compute_ead` read that column, and the
    synthetic `ccr__` row carries it so `ead_ccr = alpha_applied ×
    (RC + PFE)` reconciles. BA-CVA divides by the same per-netting-set
    value — see [(c) below](#c-ba-cva-netting-set-inputs-and-coverage-cva-risk-part-4).

The companion Art. 274(2A) **transitional alpha add-on** for legacy
CVA-exempt trades (60% → 40% → 20% phase-in over 2027–2029) is applied to
`is_legacy_cva_exempt` netting sets on the α = 1 carve-out — see
[`crr/ccr/ead-composition.md`](../crr/ccr/ead-composition.md).

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

### (c) BA-CVA netting-set inputs and coverage (CVA Risk Part 4)

The Basic Approach to CVA risk (`engine/cva/ba_cva.py`, `cva_ba_cva`
Feature — Basel 3.1 only; the CRR pack declares it off) reads one row per
covered derivative netting set from the SA-CCR synthetic `ccr__` rows
and joins the BA-CVA counterparty input (`cva_counterparties`:
sector, credit-quality band, `M_NS`, `cva_in_scope`). PS1/26 CVA Risk
Part 4.3 defines the netting-set terms of `SCVA_c`:

> "EAD_NS is the exposure at default of the netting set, calculated in
> the same manner in which the firm calculates exposure at default for
> determining own funds requirements for counterparty credit risk, in
> accordance with either Sections 3 to 5 of Counterparty Credit Risk
> (CRR) Part or Section 6 of Chapter 6 of Title II of Part Three of
> CRR; ... α = the value of α as specified in the Counterparty Credit
> Risk (CRR) Part"

So the engine (review item CC-15, 2026-11):

- uses the netting set's SA-CCR exposure value `ead_ccr` as `EAD_NS` —
  not the post-CRM `ead_final`, which lending-side CRM can reduce and
  guarantee substitution splits across legs (a split netting set is
  counted once);
- divides each netting set by its own `alpha_applied` (1 for a
  non-financial or pension-scheme counterparty) rather than by 1.4 for
  every netting set — the old reading understated an NFC's `SCVA_c` by
  `1 − 1/1.4 ≈ 28.6%` (NFC, EAD 10m, M 5, `OTHER` / `IG`: RWEA
  12,837,454.56 → 17,972,436.38);
- excludes FCCM SFT rows (`risk_type = "CCR_SFT"`): an SFT is a covered
  transaction only when fair-valued and its CVA risk material (Part
  1.2), neither of which the input carries.

**Coverage warning CCR030 (CC-16).** Part 4.1 requires own funds for
CVA risk on every covered transaction, and Part 1.2 makes every
derivative a covered transaction except, among others, *"(a)
derivatives transacted directly with a qualifying central
counterparty"*. A counterparty with derivative netting sets but no
`cva_counterparties` row has no sector, credit quality or `M_NS`, so it
would drop out of the BA-CVA join with a zero charge. The engine emits
one **CCR030** data-quality WARNING per such counterparty (also when
the CVA input is absent altogether), naming the counterparty. Not
warned: derivatives with a QCCP (the same predicate as the Art. 306 pin),
SFT rows, and counterparties listed with `cva_in_scope = False` — the
way to record a Part 3.2 exemption or a client-clearing exclusion
(1)(b)–(d) that the input cannot otherwise express. The charge itself
is not defaulted; the warning names the gap.

### (d) Collateral haircuts follow the Basel 3.1 Art. 224 table

PS1/26 Annex R leaves Art. 274(3), 275, 276 and 278 unamended, so collateral,
margin-agreement terms, the Art. 274(3) cap and the Art. 275(3) shared-agreement
RC work as under CRR
([rc-calculation.md](../crr/ccr/rc-calculation.md#collateral-the-art-2743-cap-and-shared-csas)).
The one regime difference is the volatility adjustment Art. 276(1)(d) takes from
Art. 223 / 224: a Basel 3.1 run values SA-CCR collateral with the PS1/26
Art. 224 table (five maturity bands; main-index equity 20%, gold 20%), read
through the `collateral_haircut_maturity_bands_revised` Feature exactly as for
lending collateral. Main-index equity variation margin at a 10-day MPOR is
therefore worth 80% of its value under Basel 3.1 against 85% under CRR.

---

## CRR per-article specifications (canonical content)

The complete SA-CCR rule set — formulas, hedging-set partition rules,
supervisory factors, worked CCR-A acceptance scenarios — lives on the
CRR per-article pages. The SA-CCR deltas above are the **only** Basel
3.1 overlays on the EAD chain; everything else is unchanged.

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
- **PRA PS1/26 CVA Risk Part 1.2, 4.1, 4.3** — "covered transaction",
  BA-CVA scope, and the `SCVA_c` netting-set terms (`EAD_NS`, α).
- **Regulation (EU) No 648/2012 (EMIR) Art. 2(9), Art. 2(10)** —
  definitions of "non-financial counterparty" and "pension scheme
  arrangement" underpinning the Art. 274(2) α = 1 carve-out.
- **BCBS CRE52.1–52.5** — Basel-level SA-CCR methodology and α = 1.4
  calibration rationale.
- **[Output floor (Basel 3.1)](output-floor.md)** — full TREA formula,
  PRA transitional schedule, OF-ADJ own-funds adjustment.
- **[SA-CCR (CRR) — EAD composition](../crr/ccr/ead-composition.md)** —
  engine entry point, per-netting-set `alpha_applied`, synthetic
  exposure-row contract, CCR-A1 worked example, the Art. 274(2)
  carve-out (Basel 3.1 only) and Art. 274(2A) transitional alpha
  add-on, and the moot Art. 274(2B) leverage-ratio exclusion.
