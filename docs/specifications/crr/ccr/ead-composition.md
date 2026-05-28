# SA-CCR — EAD composition (Art. 274(2))

The SA-CCR exposure value (EAD) is the final composition step of the
counterparty-credit-risk chain: it scales the sum of the replacement cost
(`RC`, Art. 275) and the potential future exposure (`PFE`, Art. 278) by
the supervisory **alpha multiplier** of `1.4` and emits one EAD per
netting set. The resulting figure is the **only** number that crosses
into the rest of the credit-risk pipeline — every other SA-CCR
intermediate (per-trade adjusted notional, supervisory delta, maturity
factor, per-hedging-set add-on) is reconciliation metadata at this
point.

This page documents:

- the Art. 274(2) verbatim formula and the calibration rationale for
  α = 1.4;
- the engine entry point and the alpha-override hook on `CCRConfig`;
- the downstream routing of the netting-set EAD into the unified SA /
  IRB exposure ladder via `pipeline_adapter.ccr_rows_to_exposures`; and
- the interaction with the Basel 3.1 [output floor](../../basel31/output-floor.md)
  — SA-CCR EAD enters both the un-floored `U-TREA` leg and the
  standardised `S-TREA` leg of the `TREA` formula.

## Regulatory citation

**Primary source:** PRA PS1/26 Counterparty Credit Risk (CRR) Part —
Article 274 (Exposure value). The UK regime is a verbatim re-export of
the onshored CRR text with the Basel 3.1 alpha retained at `1.4`. The
secondary calibration source is BCBS CRE52.1–52.5 (the underlying
SA-CCR methodology).

| Sub-article | Coverage | BCBS cross-reference |
|-------------|----------|----------------------|
| Art. 274(2)     | `Exposure value = α · (RC + PFE)`, α = 1.4 default | CRE52.1 |
| Art. 274(2) carve-out | α = 1 for trades with non-financial counterparties, pension scheme arrangements, or pension-default compensation entities | CRE52.1 footnote |
| Art. 274(2A)–(2B) | Transitional `alpha add-on` for legacy CVA-exempt trades (60% → 40% → 20% over 2027–2029) | n/a |
| Art. 275         | Replacement cost `RC` — see [rc-calculation.md](rc-calculation.md) | CRE52.10–52.15 |
| Art. 278         | PFE add-on and multiplier — see [pfe-multiplier.md](pfe-multiplier.md) | CRE52.16–52.25 |

### Verbatim text — PRA PS1/26 Art. 274(2)

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

— PRA PS1/26 Annex R, Counterparty Credit Risk (CRR) Part, p. 456
(source PDF: `docs/assets/ps126app1.pdf`).

### Why α = 1.4 — calibration rationale

The `1.4` multiplier is a deliberate, asset-class-agnostic
**calibration uplift** relative to the IMM EEPE methodology that
SA-CCR replaces. SA-CCR is intentionally less risk-sensitive than IMM
(it has no Monte-Carlo scenarios, no portfolio-level diversification,
and a coarse five-asset-class add-on structure), so the regulator
applies a flat scalar at the end of the chain to recover a
counterparty-level exposure broadly in line with what an internal model
would have produced for the same netting set. The `1.4` value is
inherited verbatim from BCBS CRE52.1 and from the original Basel III
IMM-EAD calibration that pre-dates SA-CCR — it represents the same
"alpha" that IMM users multiply by EEPE to get EAD under Art. 284(4).

The Art. 274(2) carve-out to **α = 1** for non-financial
counterparties, pension scheme arrangements, and pension-default
compensation entities removes the calibration uplift for end-user
counterparties whose CVA exposure profile is materially lower than the
inter-bank book that SA-CCR was originally calibrated for. This
carve-out aligns with the EMIR (Regulation (EU) No 648/2012) Article 2
point-(9) / point-(10) definitions referenced verbatim in the PS1/26
text.

!!! info "Transitional alpha add-on — Art. 274(2A) (legacy CVA-exempt trades)"
    For trades **entered into prior to 1 January 2027** with a
    counterparty referred to in CVA Part 7.1(1)(a) or (b) — broadly,
    the CVA-exempt sovereign / NFC / pension counterparties — Art.
    274(2A) requires a transitional `alpha add-on` to be added back on
    top of the α = 1 EAD. The add-on is defined as `EAD(α=1.4) −
    EAD(α=1)` and is phased in at **60% (2027) → 40% (2028) → 20%
    (2029) → 0% (2030+)**. The transitional does not apply to the
    leverage-ratio EAD per Art. 274(2B). The engine implements only the
    steady-state α = 1.4 path today (see `CCRConfig.alpha` below);
    the transitional add-on is a documented gap and will be re-routed
    here when the corresponding engine batch ships.

## Engine entry point

```python
from rwa_calc.engine.ccr.sa_ccr import compute_ead

def compute_ead(
    netting_sets: pl.LazyFrame,
    config: CCRConfig | None = None,
) -> pl.LazyFrame:
    """SA-CCR exposure value per CRR Art. 274(2): EAD = α × (RC + PFE).

    Pure composition layer that consumes pre-computed netting-set-grain
    columns ``rc_unmargined`` (Art. 275) and ``pfe_addon`` (Art. 278). α
    defaults to 1.4 (Art. 274(2)) but may be overridden via
    ``config.alpha``. Returns the input frame with a new ``ead_ccr``
    column."""
```

Source: `src/rwa_calc/engine/ccr/sa_ccr.py::compute_ead`.

The function is a **pure composition layer** — it does not re-derive RC
or PFE, it merely combines them. The inputs are:

| Input column      | Type      | Producer                                                        | Citation        |
|-------------------|-----------|------------------------------------------------------------------|-----------------|
| `rc_unmargined`   | `Float64` | [rc-calculation.md](rc-calculation.md) — `compute_rc_unmargined` | Art. 275(1)     |
| `pfe_addon`       | `Float64` | [pfe-multiplier.md](pfe-multiplier.md) — `compute_pfe`           | Art. 278(1)–(3) |

The output column is:

| Output column | Type      | Formula                                | Citation     |
|---------------|-----------|----------------------------------------|--------------|
| `ead_ccr`     | `Float64` | `α × (rc_unmargined + pfe_addon)`      | Art. 274(2)  |

### Alpha override — `CCRConfig.alpha`

The `α` value defaults to `1.4` when `config` is `None`. When a
`CCRConfig` instance is supplied, `compute_ead` reads
`float(config.alpha)` and applies it to every row uniformly. This is
the engine hook for the Art. 274(2) **α = 1 carve-out** (non-financial
counterparties / pension schemes) — firms wiring the carve-out branch
must invoke `compute_ead` twice, once with `α = 1.4` on the in-scope
netting sets and once with `α = 1` on the carve-out netting sets, then
concatenate the resulting frames. The current orchestrator at
`engine/ccr/pipeline_adapter.py::ccr_rows_to_exposures` applies the
default `α = 1.4` to all netting sets — the per-counterparty carve-out
gate is a documented engine gap (see the "Pending" note below).

`CCRConfig` is defined at `src/rwa_calc/contracts/config.py` with
`alpha: Decimal = Decimal("1.4")` as the default field value.

## Downstream routing into the SA / IRB exposure ladder

SA-CCR EAD is **not** a terminal output — it is an input to the
standard credit-risk pipeline. The orchestrator at
`engine/ccr/pipeline_adapter.py::ccr_rows_to_exposures` shapes each
netting-set-grain `ead_ccr` value into a **synthetic exposure row**
that mirrors the unified `RAW_EXPOSURE_SCHEMA`. From that point on the
row is indistinguishable from an on-balance-sheet loan as far as the
Classifier, CRM processor, and SA / IRB calculators are concerned.

### Synthetic exposure row contract

The `ccr_rows_to_exposures` function emits one row per netting set with
the following provenance-bearing fields:

| Column                    | Value                                              | Purpose                                                              |
|---------------------------|----------------------------------------------------|----------------------------------------------------------------------|
| `exposure_reference`      | `"ccr__<netting_set_id>"`                          | Unique key for the downstream chain                                  |
| `exposure_type`           | `"ccr_netting_set"`                                | Source-discriminator (vs `"loan"`, `"facility"`, etc.)               |
| `risk_type`               | `"CCR_DERIVATIVE"`                                 | Identifies the row as a CCR exposure (consumed by COREP reporting)   |
| `ccr_method`              | `"sa_ccr"`                                         | Identifies SA-CCR (vs IMM in a future batch)                         |
| `source_netting_set_id`   | original `netting_set_id`                          | Reconciliation key back to the input `NETTING_SET_SCHEMA`            |
| `drawn_amount`            | `ead_ccr` (Art. 274(2))                            | The full SA-CCR EAD enters the pipeline as already-utilised exposure |
| `interest`                | `0.0`                                              | No accrued interest concept for CCR                                  |
| `undrawn_amount`          | `0.0`                                              | No commitment / CCF for CCR EAD (already in EAD)                     |
| `nominal_amount`          | `0.0`                                              | Notional is upstream input only                                      |
| `counterparty_reference`  | from `NETTING_SET_SCHEMA`                          | Drives Classifier exposure-class assignment                          |
| `currency`                | first trade currency in the netting set            | For reporting only — EAD is already in base currency                 |
| `value_date`              | `reporting_date`                                   | The CCR EAD is as-of-reporting-date by construction                  |
| `maturity_date`           | `max(trade.maturity_date)` in the netting set      | Conservative — longest trade's maturity                              |
| `seniority`               | `"senior"`                                         | Conservative default                                                 |

Plus the SA-CCR provenance columns kept for reconciliation: `addon_aggregate`,
`addon_by_asset_class` (struct of the five Art. 277(1) classes), `pfe_multiplier`,
`pfe_addon`, `rc_unmargined`, and `ead_ccr`. These let the COREP exports
reconcile a single `RWA` value back to its `α × (RC + PFE)` decomposition
without re-running the SA-CCR chain.

### Pipeline ordering — orchestrator view

```
RawCCRBundle
  → apply_legal_enforceability_gate   (Art. 272(4); see legal-enforceability.md)
  → ccr_rows_to_exposures             (chains the SA-CCR pipeline, this page)
      └─ compute_ead                  (Art. 274(2))            ← this page's entry point
  → synthetic exposure row (RAW_EXPOSURE_SCHEMA shape)
  → concat with on-balance-sheet exposures (how="diagonal_relaxed")
  → Classifier                        (resolves counterparty class)
  → CRMProcessor                      (no-op: drawn_amount already net of collateral via RC)
  → SA / IRB / Slotting Calculators   (risk-weight lookup, RWA = EAD × RW)
  → OutputAggregator                  (firm-level totals + output floor)
```

The `how="diagonal_relaxed"` concat in the orchestrator means any
`RAW_EXPOSURE_SCHEMA` columns absent from the synthetic CCR row (e.g.
`loan_to_value`, `property_type`) are filled with nulls. The downstream
Classifier and CRM processor are CCR-unaware — they consume the CCR
row identically to any other exposure.

### Why the SA-CCR row is CRM-passthrough

The replacement-cost calculation at Art. 275 already nets the
counterparty's posted collateral (`V − C`), so by the time `ead_ccr`
emerges, no further collateral haircut applies at the CRM stage. The
CRM processor's `_initialize_ead` step therefore sees `drawn_amount =
ead_ccr` and produces `ead_pre_crm = ead_ccr` unchanged — there is no
double-count of collateral. CRM **guarantees** and **credit
derivatives** purchased on the CCR counterparty itself would still
flow through the standard CRM substitution branch if supplied, but the
CCR netting agreement's own collateral pool is already consumed by
Art. 275.

## Interaction with the Basel 3.1 output floor

The Art. 274(2) EAD contributes to **both** legs of the Basel 3.1
output-floor formula (`TREA = max{U-TREA; x × S-TREA + OF-ADJ}`) — it
is a credit-risk RWA in both the un-floored and standardised
computations:

- **U-TREA leg (Art. 92(3)):** the IRB-permissioned firm risk-weights
  the synthetic CCR row through IRB if the counterparty has an IRB
  model; otherwise SA. The resulting RWA enters `U-TREA` directly.
- **S-TREA leg (Art. 92(3A)):** the synthetic CCR row is re-run
  through the SA calculator (no IRB), producing an SA-equivalent RWA
  that enters `S-TREA`. The SA-CCR EAD itself does not change between
  the two legs — only the downstream risk-weight lookup changes.

The α = 1.4 multiplier therefore amplifies the floor impact for IRB
firms whose IRB CCR EAD methodology (IMM, if permissioned) would
produce a lower exposure number than SA-CCR. Conversely, an IRB firm
using SA-CCR for its U-TREA leg sees identical EAD in both legs —
only the risk weight differs.

See [`basel31/output-floor.md`](../../basel31/output-floor.md#floor-calculation)
for the full `TREA` formula and the 4-year transitional schedule (PRA
Art. 92(5): 60% → 65% → 70% → 72.5%).

!!! note "EAD vs RWA in the floor"
    The output floor operates on **RWA**, not EAD. The SA-CCR EAD
    documented on this page is the input to the risk-weight stage that
    follows. A counterparty with `ead_ccr = £100m` classified as a
    Basel 3.1 Bucket A institution at 40% RW (Art. 121) produces
    `RWA = £40m` — and that £40m flows into both `U-TREA` and
    `S-TREA` (subject to the IRB vs SA risk-weight delta on the
    U-TREA leg).

## Worked numeric example — CCR-A1 unmargined IR swap

The simplest end-to-end example uses the **CCR-A1** acceptance scenario
(`tests/acceptance/ccr/test_ccr_a1_unmargined_ir_swap.py`): one
unmargined single-trade netting set containing a 1-year USD receive-fixed
interest-rate swap with notional `100,000,000 USD`, mark-to-market value
`0`, and no posted collateral.

```
Inputs to compute_ead (post per-trade SA-CCR chain, per-NS grain):

netting_set_id  = "NS_CCR_A1"
rc_unmargined   = max(V − C, 0) = max(0 − 0, 0) = 0.0                  (Art. 275(1))
pfe_addon       = multiplier × AddOn_aggregate
                = 1.0 × (SF_IR × |D_HS|)
                = 1.0 × (0.005 × 1.0 × 100m × 1.0 × MF_unmargined)
                ≈ 1.0 × (0.005 × 100,000,000 × 0.99965770)
                ≈ 499,828.85                                            (Art. 278)

Apply Art. 274(2) with default α = 1.4:

ead_ccr         = α × (rc_unmargined + pfe_addon)
                = 1.4 × (0.0 + 499,828.85)
                ≈ 699,760.39                                            (Art. 274(2))
```

The synthetic exposure row emitted by `ccr_rows_to_exposures` for
CCR-A1 is then:

```
exposure_reference     = "ccr__NS_CCR_A1"
exposure_type          = "ccr_netting_set"
risk_type              = "CCR_DERIVATIVE"
ccr_method             = "sa_ccr"
source_netting_set_id  = "NS_CCR_A1"
drawn_amount           ≈ 699,760.39           (= ead_ccr)
ead_ccr                ≈ 699,760.39
rc_unmargined          = 0.0
pfe_addon              ≈ 499,828.85
pfe_multiplier         = 1.0
addon_aggregate        ≈ 499,828.85
addon_by_asset_class   = {interest_rate: 499,828.85, fx: 0, credit: 0,
                          equity: 0, commodity: 0}
counterparty_reference = "CP_CCR_A1"
maturity_date          = 2027-01-15
currency               = "USD"
```

Downstream the Classifier assigns this row to the `INSTITUTION` class
at CQS 2 (per the scenario fixture's counterparty rating), the SA
calculator looks up `RW = 50%` (CRR Art. 121 Table 3), and the
aggregator rolls `RWA = 50% × 699,760.39 ≈ 349,880.20` into the
firm-level total. Under Basel 3.1 the same row would route through
Art. 121 Bucket B at `RW = 40%` instead — but the EAD value of
`699,760.39` is identical under both frameworks (α = 1.4 is unchanged
between CRR and Basel 3.1).

### Sensitivity to α — what happens if the carve-out fires

If the same netting set were against a pension-scheme counterparty
qualifying for the Art. 274(2) **α = 1** carve-out, the EAD would
drop by a factor of `1.0 / 1.4 ≈ 0.714`:

```
ead_ccr (carve-out)  = 1.0 × (0 + 499,828.85) ≈ 499,828.85
RWA (carve-out)      = 50% × 499,828.85       ≈ 249,914.43
```

— a `28.6%` reduction in CCR-RWA on the same trade, which is the
direct mechanical effect of removing the SA-CCR calibration uplift.
The engine wiring for the carve-out gate is the pending follow-up
noted above; the math itself is exercised by the `CCRConfig.alpha`
override at the `compute_ead` boundary.

## Pending — engine gaps documented here

The following items are not yet engine-wired but are documented for
forward visibility:

1. **Art. 274(2) α = 1 carve-out gate** — per-netting-set dispatch on
   counterparty type (non-financial counterparty, pension scheme
   arrangement, pension-default compensation entity) is not yet
   implemented in `ccr_rows_to_exposures`. The math is exercised by
   the `CCRConfig.alpha` override hook on `compute_ead`; the gate
   itself awaits a follow-up batch.
2. **Art. 274(2A) transitional `alpha add-on`** — the legacy
   CVA-exempt phase-in (60% → 40% → 20% over 2027–2029) is not
   implemented. When it ships, it will be a post-`compute_ead` overlay
   that adds back `EAD(α=1.4) − EAD(α=1)` at the prescribed
   percentage for the in-scope legacy trades.
3. **Art. 274(2B) leverage-ratio exclusion** — the SA-CCR EAD that
   feeds the leverage-ratio numerator excludes the Art. 274(2A)
   transitional add-on. Out of scope until the alpha add-on ships.

## References

- **PRA PS1/26 Counterparty Credit Risk (CRR) Part — Article 274(2)** —
  `Exposure value = α · (RC + PFE)`, α = 1.4 default, α = 1 carve-out
  for non-financial counterparties / pension schemes.
- **PRA PS1/26 Counterparty Credit Risk (CRR) Part — Article 274(2A)** —
  transitional alpha add-on phase-in for legacy CVA-exempt trades
  (60% → 40% → 20% over 2027–2029).
- **PRA PS1/26 Counterparty Credit Risk (CRR) Part — Article 274(2B)** —
  alpha add-on excluded from leverage-ratio EAD.
- **PRA PS1/26 Counterparty Credit Risk (CRR) Part — Article 275** —
  replacement cost `RC` (input to Art. 274(2)).
- **PRA PS1/26 Counterparty Credit Risk (CRR) Part — Article 278** —
  potential future exposure `PFE` (input to Art. 274(2)).
- **PRA PS1/26 Required Level of Own Funds (CRR) Part — Article 92(2A) /
  92(3) / 92(3A) / 92(5)** — output floor formula and transitional
  schedule (consuming the CCR EAD via the synthetic exposure row).
- **BCBS CRE52.1** — Basel-level methodology underpinning α = 1.4.
- **Regulation (EU) No 648/2012 (EMIR) Art. 2(9), Art. 2(10)** —
  definitions of "non-financial counterparty" and "pension scheme
  arrangement" referenced by the Art. 274(2) carve-out.
- **`src/rwa_calc/engine/ccr/sa_ccr.py::compute_ead`** — engine
  implementation of `EAD = α × (RC + PFE)`.
- **`src/rwa_calc/engine/ccr/pipeline_adapter.py::ccr_rows_to_exposures`** —
  orchestrator that drives the SA-CCR chain and shapes the netting-set
  EAD into the synthetic `RAW_EXPOSURE_SCHEMA` row.
- **`src/rwa_calc/contracts/config.py::CCRConfig`** — `alpha: Decimal =
  Decimal("1.4")` default and override hook.
- **`tests/acceptance/ccr/test_ccr_a1_unmargined_ir_swap.py`** —
  golden-value end-to-end CCR-A1 scenario underpinning the worked
  example above.
- **[Replacement cost (RC)](rc-calculation.md)** — companion page for
  the Art. 275 input.
- **[PFE multiplier](pfe-multiplier.md)** — companion page for the
  Art. 278 input.
- **[Hedging sets](hedging-sets.md)** — companion page for the Art. 277
  / Art. 277a partition that feeds the per-asset-class add-on.
- **[Output floor (Basel 3.1)](../../basel31/output-floor.md)** —
  downstream consumption of the SA-CCR EAD in both `U-TREA` and
  `S-TREA` legs.
