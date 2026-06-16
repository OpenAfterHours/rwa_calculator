# SA-CCR — PFE multiplier and add-on aggregation (Art. 278)

The Potential Future Exposure (PFE) is the forward-looking limb of the SA-CCR
exposure value. It composes a single per-netting-set figure from two
ingredients:

1. The **aggregate add-on** `AddOn_aggregate` — the plain sum across the five
   asset-class add-ons produced upstream by the hedging-set partition and
   asset-class aggregation steps (Art. 277(1) / Art. 277a).
2. The **PFE multiplier** — a between-`F` and `1` scaling factor that
   recognises excess (over-)collateralisation and / or in-the-money market
   value at the netting-set level, capped at `1.0` and floored at `F = 0.05`
   (Art. 278(3)).

Final PFE is then `pfe_addon = multiplier × AddOn_aggregate` (Art. 278(1)),
and the netting-set EAD per Art. 274(2) is `EAD = α × (RC + PFE)` with
`α = 1.4`.

This page documents:

- the asset-class add-on aggregation rule (Art. 278(1)–(2));
- the multiplier formula and its `F = 0.05` floor (Art. 278(3));
- the engine entry point, the pipeline ordering, and two worked numeric
  examples (multiplier biting and multiplier capped).

## Regulatory citation

**Primary source:** PRA Rulebook — Counterparty Credit Risk (CRR) Part,
Article 278 (Potential Future Exposure), and Article 274(2) (alpha
multiplier `α = 1.4`). PS1/26 Appendix 1 carries this forward into the
Basel 3.1 regime with the alpha multiplier retained and the `α = 1.0`
carve-out for non-financial counterparties and pension scheme arrangements
sitting on the EAD composition rather than on the PFE itself
(PS1/26 Art. 274(2)).

| Sub-article    | Coverage                                                                 | BCBS cross-reference |
| -------------- | ------------------------------------------------------------------------ | -------------------- |
| Art. 278(1)    | `PFE = multiplier × AddOn_aggregate`                                     | CRE52.20             |
| Art. 278(2)    | `AddOn_aggregate = Σ_{asset class} AddOn_class` — plain sum across IR, FX, credit, equity, commodity | CRE52.21–22 |
| Art. 278(3)    | Multiplier formula and `F = 0.05` floor                                  | CRE52.23             |
| Art. 274(2)    | `EAD = α × (RC + PFE)` with `α = 1.4`                                    | CRE52.1              |
| Art. 275(1)    | Unmargined `RC = max(V − C, 0)` — supplies the `V` and `C` that feed the multiplier | CRE52.10 |
| Art. 277, 277a | Asset-class add-ons that compose `AddOn_aggregate` upstream             | CRE52.30–69          |

---

## Asset-class add-on aggregation — Art. 278(1)–(2)

The five SA-CCR asset classes produce one per-netting-set add-on each:

```
AddOn_aggregate = AddOn_IR + AddOn_FX + AddOn_credit + AddOn_equity + AddOn_commodity
```

This is a **plain sum** across asset classes — Art. 278(2) does not impose a
cross-asset-class correlation. The composition with the asset-class
correlation structures (the IR three-bucket matrix, the credit / equity
systematic-idiosyncratic form, the commodity within-bucket form) sits one
layer down inside each asset-class add-on; see
[hedging-sets.md](hedging-sets.md#f-inter-bucket--asset-class-correlation--art-277a)
for the upstream cross-bucket / cross-hedging-set machinery that feeds these
five totals.

The engine derives the five per-asset-class add-ons via
`compute_addon_per_asset_class` (Art. 277a) and then performs the plain
sum in the pipeline adapter, producing the netting-set-grain
`addon_aggregate` column that is the sole input the multiplier formula
consumes:

```python
addon_per_ns = addon_per_class.group_by("netting_set_id").agg(
    pl.col("asset_class_addon").fill_null(0.0).sum().alias("addon_aggregate")
)
```

Missing asset classes for a netting set contribute `0.0` (the `fill_null`
above). The orchestrator additionally carries an `addon_by_asset_class`
struct with the five components so the reconciliation
`sum(addon_by_asset_class) == addon_aggregate` is auditable in the
synthetic exposure row.

### Asset-class coverage status

| Asset class   | Add-on engine path              | Status |
|---------------|----------------------------------|--------|
| Interest rate | `_compute_addon_ir`              | Live (this batch) |
| FX            | `_compute_addon_fx`              | Live (this batch) |
| Credit        | `_compute_addon_credit`          | Pending engine batch P8.35–P8.38 — produces `null` add-on rows that the `fill_null(0.0)` aggregator treats as zero. |
| Equity        | `_compute_addon_equity`          | Pending engine batch P8.35–P8.38 |
| Commodity     | `_compute_addon_commodity`       | Pending engine batch P8.35–P8.38 |

Until P8.35–P8.38 land, a netting set whose only trades are credit / equity
/ commodity reports `addon_aggregate = 0`, which collapses the
PFE through the `V − C / AddOn` denominator to a degenerate case (the
engine guards against division by zero through the upstream
`fill_null(0.0)` and the cap at `1.0` — over-collateralised netting sets
with zero add-on report `multiplier = 1.0`, `pfe_addon = 0.0`).

---

## PFE multiplier — Art. 278(3)

The multiplier scales `AddOn_aggregate` down when the netting set carries
either positive net market value (`V > 0`) or excess collateral
(`C > V`). The formula has three moving parts: the **floor** `F = 0.05`,
the **exponential** in `V − C`, and the **cap** at `1.0`:

```
multiplier = min(
    1,
    F + (1 − F) × exp( (V − C) / (2 × (1 − F) × AddOn_aggregate) )
)
```

where:

- `F = 0.05` is the regulatory floor (Art. 278(3) — cited pack param
  `pfe_multiplier_floor_f` in `src/rwa_calc/rulebook/packs/common.py`, read
  in `engine/ccr/pfe.py` via `_PACK.scalar_param('pfe_multiplier_floor_f')`).
  No matter how heavily a netting set is over-collateralised relative to
  its add-on, the multiplier never falls below `F`; some PFE always
  remains because no collateral arrangement perfectly hedges future market
  movements.
- `V` is the **sum of trade-level mark-to-market values** within the
  netting set (`v_net` in the engine — populated by summing `mtm_value`
  over the legally enforceable trades in the netting set).
- `C` is the **sum of collateral values** held against the netting set
  (`c_net` in the engine — sum of `collateral_value` from the CCR
  collateral table for that netting set).
- `2` is the canonical exponent coefficient (Art. 278(3); cited pack param
  `pfe_aggregate_denom_coeff`).
- `AddOn_aggregate` is the per-netting-set add-on sum above.

The exponent `(V − C) / (2 × (1 − F) × AddOn_aggregate)` carries three
distinct regimes:

| Regime                       | `V − C` sign | Exponent behaviour       | Multiplier outcome              |
| ---------------------------- | ------------ | ------------------------ | ------------------------------- |
| Over-collateralised / ITM    | `V − C ≥ 0`  | `exp(·) ≥ 1`             | `F + (1 − F) × exp(·) ≥ 1` → **capped at `1.0`**. The `min(1, …)` binds. |
| At-the-money, no collateral  | `V − C = 0`  | `exp(0) = 1`             | `F + (1 − F) × 1 = 1.0` → cap binds exactly. |
| Under-collateralised / OTM   | `V − C < 0`  | `exp(·) < 1` and decreasing in `|V − C|` | Multiplier **slides between `F` and `1`**, monotonically decreasing as the deficit grows. |
| Deeply under-collateralised  | `V − C ≪ 0`  | `exp(·) → 0`             | Multiplier **asymptotes to `F = 0.05`**. |

The cap at `1.0` is the regulatory expression of the principle that
over-collateralisation reduces — but does not eliminate — counterparty
exposure: even a netting set with `C ≫ V` and a large positive `V − C`
margin cannot reduce its PFE add-on, because the multiplier is held at
`1.0`. Conversely, the floor at `F = 0.05` is the regulatory expression of
the converse principle: even a netting set with very large under-
collateralisation cannot inflate its PFE add-on indefinitely, because the
multiplier is held at `0.05 × AddOn_aggregate` once `V − C` is sufficiently
negative.

The engine evaluates the multiplier in a single Polars `min_horizontal`
expression and then applies it to `AddOn_aggregate`:

```python
v_minus_c = pl.col("v_net") - pl.col("c_net")
denom = denom_coeff * one_minus_f * pl.col("addon_aggregate")
uncapped = floor_f + one_minus_f * (v_minus_c / denom).exp()
multiplier = pl.min_horizontal(pl.lit(1.0), uncapped)
pfe_addon = multiplier * pl.col("addon_aggregate")
```

The `min_horizontal(pl.lit(1.0), uncapped)` formulation is the lazy-plan
equivalent of `min(1, …)` and works element-wise across all netting-set
rows in the LazyFrame.

---

## Engine entry point

The full PFE composition layer — multiplier, `pfe_addon`, unmargined RC and
EAD — is implemented by a single function operating at netting-set grain:

```python
--8<-- "src/rwa_calc/engine/ccr/pfe.py:57:116"
```

Signature:
`compute_pfe(netting_sets: pl.LazyFrame, config: CCRConfig | None = None) -> pl.LazyFrame`.

Source: [`src/rwa_calc/engine/ccr/pfe.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/engine/ccr/pfe.py).

### Inputs (netting-set grain)

| Column            | Dtype     | Source                                                                                | Article          |
| ----------------- | --------- | ------------------------------------------------------------------------------------- | ---------------- |
| `v_net`           | `Float64` | Sum of `mtm_value` over the trades in the netting set (`pipeline_adapter` step 3)     | Art. 275(1)      |
| `c_net`           | `Float64` | Sum of `collateral_value` over the CCR collateral rows for the netting set (step 4)   | Art. 275(1)      |
| `addon_aggregate` | `Float64` | Plain sum over per-asset-class add-ons from `compute_addon_per_asset_class` (step 2)  | Art. 278(2)      |

### Outputs (netting-set grain)

| Column            | Dtype     | Formula                                            | Article         |
| ----------------- | --------- | -------------------------------------------------- | --------------- |
| `pfe_multiplier`  | `Float64` | `min(1, F + (1 − F) × exp((V − C) / (2 × (1 − F) × AddOn)))` | Art. 278(3)     |
| `pfe_addon`       | `Float64` | `pfe_multiplier × addon_aggregate`                 | Art. 278(1)     |
| `rc_unmargined`   | `Float64` | `max(v_net − c_net, 0)`                            | Art. 275(1)     |
| `ead_ccr`         | `Float64` | `α × (rc_unmargined + pfe_addon)` with `α = 1.4`   | Art. 274(2)     |

The `α` value defaults to `1.4` and is overridable via
`CCRConfig.alpha`; the PS1/26 `α = 1.0` carve-out for non-financial
counterparties is a config-level toggle, not a multiplier-formula
adjustment.

The margined RC path of Art. 275(2)
(`RC_margined = max(V − C, TH + MTA − NICA, 0)`) is **not** yet routed
through `compute_pfe` — the current orchestrator wires only the unmargined
path. The multiplier formula itself is unchanged between margined and
unmargined netting sets per Art. 278(3); only the inputs `V`, `C` and the
upstream maturity factor differ between the two paths
(see [maturity-factor.md](maturity-factor.md#margined-formula--art-279c2)).

---

## Pipeline ordering

`compute_pfe` is the netting-set-grain stage that consumes everything the
upstream trade-grain pipeline produced:

```
trades → adjusted_notional            (Art. 279b)
       → supervisory_delta            (Art. 279a)
       → maturity_factor              (Art. 279c)
       → assign_hedging_set           (Art. 277)
       → compute_addon_per_asset_class (Art. 277a)
       │
       ├─ group_by(netting_set_id).agg(sum)  → addon_aggregate   (Art. 278(2))
       ├─ trades.group_by(netting_set_id).agg(sum(mtm_value))    → v_net
       └─ ccr_collateral.group_by(netting_set_id).agg(sum)       → c_net
       │
       → compute_pfe                  (Art. 278(1)–(3))   ← this page
           ├─ pfe_multiplier
           ├─ pfe_addon
           ├─ rc_unmargined            (Art. 275(1))
           └─ ead_ccr                  (Art. 274(2), α = 1.4)
       │
       → pipeline_adapter.ccr_rows_to_exposures
           → synthetic exposure rows for the SA / IRB ladder
```

The orchestrator at `src/rwa_calc/engine/ccr/pipeline_adapter.py` performs
the per-netting-set aggregation of `v_net`, `c_net`, and `addon_aggregate`
in steps 3–5 before calling `compute_pfe` in step 6. The output rows
become synthetic on-balance-sheet exposures (`risk_type =
"CCR_DERIVATIVE"`, `ccr_method = "sa_ccr"`) consumed by the downstream
Classifier / SA Calculator chain.

---

## Worked numeric examples

Both examples below use one netting set with `AddOn_aggregate = 100,000`
(arbitrary units) so the arithmetic shows the multiplier behaviour
without distraction. The complete end-to-end CCR-A1 and CCR-A2 scenarios
in the acceptance suite both sit at the cap (`V = C = 0` ⇒ `multiplier =
1.0`); see the cap example below for the same arithmetic on a simpler
data shape.

### Example 1 — Multiplier capped (V ≥ C, multiplier = 1.0)

The cap binds for every netting set whose mark-to-market value is at or
above the collateral held against it — including the unmargined CCR-A1 /
CCR-A2 case where `V = C = 0` sits exactly on the boundary `V − C = 0`.

```
Inputs:
  v_net           = 0
  c_net           = 0
  addon_aggregate = 100,000

Working:
  V − C           = 0
  exponent arg    = 0 / (2 × 0.95 × 100,000) = 0
  exp(0)          = 1.0
  uncapped        = 0.05 + 0.95 × 1.0 = 1.0
  multiplier      = min(1.0, 1.0) = 1.0          (cap exact)
  pfe_addon       = 1.0 × 100,000 = 100,000
  rc_unmargined   = max(0 − 0, 0) = 0
  ead_ccr         = 1.4 × (0 + 100,000) = 140,000
```

Pinned acceptance values for the cap regime (both at `V − C = 0`):

- `tests/expected_outputs/ccr/CCR-A1.json`:
  `v_net = 0`, `c_net = 0`, `addon_aggregate = 3,914,298.228`,
  `pfe_multiplier = 1.0`, `pfe_addon = 3,914,298.228`,
  `ead_ccr = 5,480,017.519`.
- `tests/expected_outputs/ccr/CCR-A2.json`:
  `v_net = 0`, `c_net = 0`, `addon_aggregate = 3,198,904.672`,
  `pfe_multiplier = 1.0`, `pfe_addon = 3,198,904.672`,
  `ead_ccr = 4,478,466.541`.

### Example 2 — Multiplier biting (V < C, multiplier < 1)

Re-run the same `AddOn_aggregate = 100,000` netting set with a meaningful
over-collateralisation — collateral held exceeds the netting-set
mark-to-market, so `V − C < 0` and the exponential collapses below `1.0`.
Take `V = 0`, `C = 50,000`, i.e. `V − C = −50,000`:

```
Inputs:
  v_net           = 0
  c_net           = 50,000
  addon_aggregate = 100,000

Working:
  V − C           = −50,000
  exponent arg    = −50,000 / (2 × 0.95 × 100,000) = −50,000 / 190,000 ≈ −0.26316
  exp(−0.26316)   ≈ 0.76858
  uncapped        = 0.05 + 0.95 × 0.76858 ≈ 0.78015
  multiplier      = min(1.0, 0.78015) = 0.78015
  pfe_addon       = 0.78015 × 100,000 ≈ 78,015
  rc_unmargined   = max(0 − 50,000, 0) = 0       (collateral exceeds V → RC clamped at 0)
  ead_ccr         = 1.4 × (0 + 78,015) ≈ 109,221
```

Push the over-collateralisation further. With `C − V = 500,000`
(`V − C = −500,000`, five times the add-on):

```
exponent arg = −500,000 / 190,000 ≈ −2.6316
exp(−2.6316) ≈ 0.07197
uncapped     = 0.05 + 0.95 × 0.07197 ≈ 0.11837
multiplier   ≈ 0.11837
pfe_addon    ≈ 11,837
ead_ccr      ≈ 1.4 × (0 + 11,837) ≈ 16,572
```

And the asymptote — with `C − V = 10,000,000` (`V − C = −10,000,000`,
one hundred times the add-on):

```
exponent arg = −10,000,000 / 190,000 ≈ −52.63
exp(−52.63)  ≈ 1.4 × 10⁻²³            (effectively zero)
uncapped     = 0.05 + 0.95 × 0 = 0.05
multiplier   = 0.05                  (floor binds)
pfe_addon    = 0.05 × 100,000 = 5,000
ead_ccr      = 1.4 × (0 + 5,000) = 7,000
```

The floor `F = 0.05` ensures the PFE never falls below 5% of the
asset-class add-on aggregate, no matter how generously the netting set is
collateralised relative to its add-on. This is the structural lower bound
of Art. 278(3).

### Cross-check against CCR-A1

CCR-A1 (`tests/acceptance/ccr/test_ccr_a1_unmargined_ir_swap.py`) is the
shortest end-to-end demonstration of `compute_pfe` in the live pipeline.
A single 10-year GBP vanilla IR swap (`notional = 100m GBP`,
`δ = +1`, `start_date = reporting_date = 2026-01-15`,
`maturity_date = 2036-01-15`, `MtM = 0`, unmargined) feeds:

```
S, E (years)        = 0.04 (floored), 9.99863
SD(S, E)            = (exp(−0.05·0.04) − exp(−0.05·9.99863)) / 0.05  ≈ 7.82860
d  = notional · SD  = 100,000,000 · 7.82860                          ≈ 782,859,645.55
MF                  = sqrt(min(9.99863, 1) / 1) = 1.0                  (unmargined cap)
effective_notional  = 1.0 · 782,859,645.55 · 1.0                     ≈ 782,859,645.55
                                                                       (single GT_5Y bucket)
AddOn_IR            = SF_IR · |D_GT_5Y| = 0.005 · 782,859,645.55     ≈ 3,914,298.23
addon_aggregate     = 3,914,298.23                                     (only IR populated)
v_net               = 0                                                (at-par)
c_net               = 0                                                (no collateral)
V − C               = 0
PFE_multiplier      = min(1, 0.05 + 0.95 · exp(0))                   = 1.0   (cap exact)
PFE_addon           = 1.0 · 3,914,298.23                             ≈ 3,914,298.23
rc_unmargined       = max(0 − 0, 0)                                  = 0
EAD_ccr             = 1.4 · (0 + 3,914,298.23)                       ≈ 5,480,017.52
```

The CCR-A1 expected output JSON pins every figure above to three decimal
places — see `tests/expected_outputs/ccr/CCR-A1.json`.

---

## References

- **PRA Rulebook — Counterparty Credit Risk (CRR) Part, Article 278** —
  PFE composition and multiplier formula; UK-onshored re-export of the
  EU CRR text with the `F = 0.05` floor and the `α = 1.4` alpha
  multiplier retained.
- **PRA Rulebook — Counterparty Credit Risk (CRR) Part, Article 274(2)** —
  EAD = α × (RC + PFE).
- **PRA Rulebook — Counterparty Credit Risk (CRR) Part, Article 275(1)** —
  unmargined `RC = max(V − C, 0)` — supplies the `V` and `C` consumed by
  the multiplier exponent.
- **PRA PS1/26 Appendix 1 §456 (Article 274(2))** — UK Basel 3.1 carries
  the same `α = 1.4` and the SA-CCR exposure-value formula forward, with
  an `α = 1.0` carve-out for non-financial counterparties and pension
  scheme arrangements that the engine surfaces via `CCRConfig.alpha`.
- **BCBS CRE52.20–23** — Basel-level methodology for PFE composition,
  asset-class add-on aggregation and the multiplier formula.
- [`src/rwa_calc/engine/ccr/pfe.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/engine/ccr/pfe.py) —
  engine implementation of `compute_pfe` and the upstream
  `compute_addon_per_asset_class`.
- [`src/rwa_calc/engine/ccr/pipeline_adapter.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/engine/ccr/pipeline_adapter.py) —
  orchestrator that builds the netting-set-grain `v_net`, `c_net`, and
  `addon_aggregate` columns before invoking `compute_pfe`.
- [`src/rwa_calc/rulebook/packs/common.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/rulebook/packs/common.py) —
  cited pack params (`pfe_multiplier_floor_f = 0.05`,
  `pfe_aggregate_denom_coeff = 2`), read in `engine/ccr/pfe.py` via
  `_PACK.scalar_param(...)`.
- `tests/acceptance/ccr/test_ccr_a1_unmargined_ir_swap.py`,
  `test_ccr_a2_unmargined_fx_forward.py` — golden multiplier-at-the-cap
  values (`pfe_multiplier = 1.0`) pinned by `CCR-A1.json` / `CCR-A2.json`.
- [Hedging sets](hedging-sets.md) — upstream asset-class add-on
  aggregation that produces the five inputs to the Art. 278(2) plain sum.
- [Maturity factor](maturity-factor.md) — upstream MPOR cascade that
  drives the margined branch of `V`, `C` and the trade-level `MF`.
- [Adjusted notional](adjusted-notional.md) — upstream per-asset-class
  `d` formula that ultimately feeds the asset-class add-ons.
- [FX treatment](fx-treatment.md) — CCR-A2 worked example end-to-end
  through `compute_pfe`.
