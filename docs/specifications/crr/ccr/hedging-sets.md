# SA-CCR — Hedging-set partition (Art. 277, 277a)

The hedging-set partition is the SA-CCR step that groups every trade in a
netting set into the smallest unit over which the supervisory aggregation
formula admits offset. The asset-class branch (Art. 277(1)) is decided by the
trade's risk driver; the within-asset partition rule (Art. 277(2)–(3)) is
then specific to that asset class. The asset-class add-on (Art. 277a) is
later composed from per-hedging-set add-ons using a supervisory correlation
matrix.

This page documents:

- the per-asset-class partition rule (a–e below);
- the inter-bucket / cross-hedging-set correlation parameters of Art. 277a
  (f below); and
- worked numeric examples per asset class (g below).

## Regulatory citation

**Primary source:** PRA PS1/26 Counterparty Credit Risk (CRR) Part —
Article 277 (hedging sets) and Article 277a (asset-class add-on aggregation).
The UK regime is a verbatim re-export of the onshored CRR text with the
Basel 3.1 alpha = 1.4 retained. References below follow the PRA-priority
convention: PRA Art. numbers first, BCBS CRE52 codes second.

| Sub-article | Coverage | BCBS cross-reference |
|-------------|----------|----------------------|
| Art. 277(1)     | Asset-class branch (IR / FX / Credit / Equity / Commodity) | CRE52.30 |
| Art. 277(2)(a)–(c) | IR maturity buckets `< 1y` / `1y–5y` / `> 5y` | CRE52.32 |
| Art. 277(3)(a)  | FX hedging set = currency pair | CRE52.34 |
| Art. 277(2)(c)  | Credit — one hedging set per netting set | CRE52.35 |
| Art. 277(2)(d)  | Equity — one hedging set per netting set | CRE52.36 |
| Art. 277(3)(b)  | Commodity — five bucket types | CRE52.37 |
| Art. 277a(1)    | Asset-class add-on: cross-bucket aggregation (IR) and entity/sub-class aggregation (credit / equity) | CRE52.46–66 |
| Art. 277a(2)    | Hedging-set add-on for FX = `SF × |D_HS|` | CRE52.55 |
| Art. 280–280c   | Supervisory factors and correlations consumed by the aggregation | CRE52.71–74 |

---

## (a) Interest rate — Art. 277(2): three maturity buckets per currency

Each interest-rate trade in a netting set is allocated to exactly one
hedging set per the pair `(currency, maturity_bucket)`, where the maturity
bucket is keyed on residual maturity `M` (years to maturity):

| Bucket | Range | Code |
|--------|-------|------|
| Bucket 1 | `M < 1 year` | `LT_1Y` |
| Bucket 2 | `1 year ≤ M ≤ 5 years` | `1Y_5Y` |
| Bucket 3 | `M > 5 years` | `GT_5Y` |

The boundary convention follows the strict inequalities in
Art. 277(2)(a)–(c) — a trade with exactly `M = 1.0` lands in Bucket 2, and a
trade with exactly `M = 5.0` also lands in Bucket 2; only `M > 5.0` rolls into
Bucket 3.

For a trade with reference period start `S` and end `E`, the
residual maturity used for bucketing is `M = E` (years from the reporting
date to the reference period end), the same `E` that feeds the supervisory
duration in [adjusted-notional.md](adjusted-notional.md#interest-rate--art-279b1a).

The composite hedging-set identifier emitted by the engine is:

```
hedging_set_id = "IR-<netting_set_id>-<currency>-<maturity_bucket>"
```

so a 7-year USD swap in netting set `NS_IR_01` lands in
`IR-NS_IR_01-USD-GT_5Y`. Trades in different currencies live in different
hedging sets even when the maturity bucket coincides — there is **no
cross-currency offset** at the IR hedging-set level (that offset is supplied
by the FX asset-class branch).

## (b) FX — Art. 277(3)(a): one hedging set per currency pair

Every FX derivative belongs to one hedging set keyed on the currency pair,
with the pair ordered to be direction-independent (so EUR/USD and USD/EUR
collapse to one set):

```
pair_id        = min(currency, currency_leg2) + "/" + max(currency, currency_leg2)
hedging_set_id = "FX-<netting_set_id>-<pair_id>"
```

There are **no maturity sub-buckets** for FX — every FX trade in a given
currency pair shares one hedging set regardless of tenor. The full FX
treatment, including the two-leg trade schema, the adjusted-notional
formula, and the CCR-A2 worked example, is documented in
[fx-treatment.md](fx-treatment.md).

## (c) Credit — Art. 277(2)(c): one hedging set per netting set

Per Art. 277(2)(c), all credit derivatives within a netting set form **one
hedging set**:

```
hedging_set_id = "CR-<netting_set_id>"
```

Single-name vs index discrimination does **not** partition the hedging set —
it instead routes to different supervisory factors (`SF_CR_SN` for single
name, `SF_CR_IDX` for index, per Art. 280 Table 1) and different
correlations (`ρ_CR_SN = 0.50` for single name, `ρ_CR_IDX = 0.80` for index,
per Art. 280a) inside the aggregation step. The engine encodes this via
the `is_index` boolean and the `credit_quality` enum (`IG` / `HY` /
`NON_RATED`) on each trade row.

## (d) Equity — Art. 277(2)(d): one hedging set per netting set

Per Art. 277(2)(d), all equity derivatives within a netting set likewise
form **one hedging set**:

```
hedging_set_id = "EQ-<netting_set_id>"
```

As with credit, the single-name / index split does not partition the
hedging set — it selects the supervisory factor (`SF_EQ_SN = 32%` vs
`SF_EQ_IDX = 20%`, Art. 280 Table 1) and correlation (`ρ_EQ_SN = 0.50` vs
`ρ_EQ_IDX = 0.80`, Art. 280b) inside the aggregation step.

## (e) Commodity — Art. 277(3)(b): five buckets

Commodity derivatives split into five buckets per Art. 277(3)(b). The
regulation lists the bucket types as **energy, metals, agriculture,
climatic and other commodities**; the engine implements the same five-way
partition with the granular labels used in BCBS CRE52.37 and the
project schema:

| Engine bucket | CRR Art. 277(3)(b) family | Supervisory factor `SF_CM` |
|---------------|---------------------------|----------------------------|
| `ELECTRICITY` | Energy (electricity sub-type) | `0.40` |
| `OIL_GAS`     | Energy (oil / gas sub-type)   | `0.18` |
| `METALS`      | Metals                        | `0.18` |
| `AGRICULTURAL`| Agriculture                   | `0.18` |
| `OTHER`       | Climatic + Other              | `0.18` |

Electricity is broken out from the energy bucket because Art. 280 Table 1
gives it a materially higher supervisory factor (`SF_CM = 40%` vs `18%` for
the other four). The composite hedging-set identifier is:

```
hedging_set_id = "CO-<netting_set_id>-<commodity_type>"
```

Rows with a null `commodity_type` are dropped — there is no implicit
fallback to the `OTHER` bucket, by design. The engine schema enumerates
the five valid values at `data/schemas.py::COLUMN_VALUE_CONSTRAINTS`.

---

## (f) Inter-bucket / asset-class correlation — Art. 277a

Art. 277a composes the asset-class add-on from the per-hedging-set or
per-bucket sub-pieces, using supervisory correlations that vary by asset
class. The table below lists the parameters consumed by the engine
(canonical SA-CCR supervisory-factor and correlation params in the rulebook
[`common.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/rulebook/packs/common.py) pack, read in `engine/ccr/pfe.py` via `_PACK.scalar_param(...)`):

| Asset class | Within-piece correlation `ρ` | Cross-piece aggregation | PRA / BCBS reference |
|-------------|------------------------------|--------------------------|----------------------|
| Interest rate | `ρ_12 = 0.70`, `ρ_23 = 0.70`, `ρ_13 = 0.30` (3 × 3 bucket correlation matrix) | Full Art. 277a(1)(a) quadratic form across the three IR buckets | Art. 277a(1)(a); CRE52.50 |
| FX            | n/a (no within-pair correlation parameter)                                     | Plain sum across FX hedging sets — no cross-pair correlation         | Art. 277a(2); CRE52.55 |
| Credit (single name) | `ρ_CR_SN = 0.50`                                                        | Systematic + idiosyncratic form per Art. 277a(1)(b)                  | Art. 280a; CRE52.58 |
| Credit (index)       | `ρ_CR_IDX = 0.80`                                                       | Same systematic + idiosyncratic form, with index `ρ`                 | Art. 280a; CRE52.58 |
| Equity (single name) | `ρ_EQ_SN = 0.50`                                                        | Single hedging set; SN + IDX sub-classes summed per Art. 280b        | Art. 280b; CRE52.65 |
| Equity (index)       | `ρ_EQ_IDX = 0.80`                                                       | Same; index `ρ` selects the sub-class                                | Art. 280b; CRE52.65 |
| Commodity     | `ρ_CM = 0.40` (within-bucket only)                                             | **No cross-bucket correlation** — buckets summed in quadrature       | Art. 280c; CRE52.68–69 |

### IR cross-bucket correlation matrix (Art. 277a(1)(a))

```
        B1     B2     B3
B1  [ 1.00   0.70   0.30 ]
B2  [ 0.70   1.00   0.70 ]
B3  [ 0.30   0.70   1.00 ]
```

The IR asset-class add-on for one netting set is:

```
AddOn_IR = SF_IR × sqrt(
    D_B1² + D_B2² + D_B3²
    + 2 × ρ_12 × D_B1 × D_B2
    + 2 × ρ_23 × D_B2 × D_B3
    + 2 × ρ_13 × D_B1 × D_B3
)
```

where `D_Bk = Σ_i (δ_i × d_i × MF_i)` is the **signed** sum of per-trade
effective notionals within bucket `k`, and `SF_IR = 0.5%` (Art. 280
Table 1).

### Credit / equity systematic-idiosyncratic form (Art. 277a(1)(b))

For credit (one hedging set per netting set, with `K` distinct reference
entities), the supervisory aggregation reads:

```
EN_k     = Σ_i in entity k ( δ_i × d_i × MF_i )           (signed)
AddOn_k  = SF_CR × EN_k                                    (signed)
AddOn_CR = sqrt(
    ( Σ_k ρ_k × AddOn_k )²
    + Σ_k ( 1 − ρ_k² ) × AddOn_k²
)
```

where `ρ_k ∈ {ρ_CR_SN, ρ_CR_IDX}` depending on whether entity `k` is a
single name or an index. A single-entity netting set collapses to
`SF_CR × |EN|` because `sqrt(ρ² + (1 − ρ²)) = 1`.

Equity follows the same systematic-idiosyncratic form (Art. 280b) but with
`SF_EQ_SN / SF_EQ_IDX` and `ρ_EQ_SN / ρ_EQ_IDX`; the single-name and
index sub-classes are then summed per Art. 280b — there is no cross-sub-class
correlation.

### Commodity within-bucket form (Art. 280c, CRE52.68–69)

For each commodity bucket `b`:

```
e_i      = δ_i × d_i × MF_i                  (per trade)
D_b      = Σ_i in bucket b e_i                (signed)
sum_e²_b = Σ_i in bucket b e_i²
AddOn_b  = SF_CM[b] × sqrt( ρ_CM² × D_b² + (1 − ρ_CM²) × sum_e²_b )
```

The five bucket-level add-ons compose **without cross-bucket correlation**
per CRE52.69:

```
AddOn_CM = sqrt( Σ_b AddOn_b² )
```

This is the only branch where the within-piece correlation differs from
the credit / equity 0.50 / 0.80 split — `ρ_CM = 0.40` is a deliberate
calibration choice in Art. 280c.

---

## Engine entry point

The partition is materialised by a single Polars function that derives both
`maturity_bucket` (IR only) and `hedging_set_id` (all asset classes):

```python
--8<-- "src/rwa_calc/engine/ccr/hedging_sets.py:96:119"
```

Signature: `assign_hedging_set(trades: pl.LazyFrame) -> pl.LazyFrame`.

The function calls `assign_ir_maturity_bucket` first to populate
`maturity_bucket` on IR rows, then dispatches a five-branch
`when/then` ladder on `asset_class` to compose the `hedging_set_id`.
Non-IR rows always carry `maturity_bucket = null`; commodity rows with a
null `commodity_type` carry `hedging_set_id = null` (and are discarded
downstream by the commodity add-on).

## Pipeline ordering

The partition step sits between the per-trade SA-CCR transforms and the
asset-class add-on:

```
trades → adjusted_notional         (Art. 279b)
       → supervisory_delta         (Art. 279a)
       → maturity_factor           (Art. 279c)
       → assign_hedging_set        (Art. 277)       ← this page
       → compute_addon_per_asset_class (Art. 277a)
       → compute_pfe               (Art. 278)
       → ead = α × (RC + PFE)      (Art. 274(2))
```

`assign_hedging_set` requires `years_to_maturity` on the input frame — the
upstream maturity-factor stage adds it. Non-IR / FX asset classes accept
frames without the optional discriminator columns (`commodity_type`,
`reference_entity`, `is_index`, `credit_quality`); the engine injects
null columns at plan-resolve time so the lazy dispatch ladder type-checks.

---

## (g) Worked numeric examples

### Interest rate — three maturity buckets per currency

Consider one netting set `NS_IR_DEMO` containing three USD swaps, one per
maturity bucket. All three are at-par receive-fixed swaps (`δ = +1.0`,
unmargined, identity maturity factor for simplicity).

| Trade   | Currency | `M` (years) | Bucket  | `δ` | `d` (notional × SD) | `MF`  | `e = δ × d × MF` |
|---------|----------|-------------|---------|------|---------------------|-------|------------------|
| T_USD_A | USD      | 0.50        | `LT_1Y` | +1.0 | 200,000,000         | 0.707 | 141,421,356      |
| T_USD_B | USD      | 3.00        | `1Y_5Y` | +1.0 | 300,000,000         | 1.000 | 300,000,000      |
| T_USD_C | USD      | 7.00        | `GT_5Y` | +1.0 | 250,000,000         | 1.000 | 250,000,000      |

Per-bucket signed sums:

```
D_B1 = 141,421,356        (LT_1Y)
D_B2 = 300,000,000        (1Y_5Y)
D_B3 = 250,000,000        (GT_5Y)
```

IR asset-class add-on with `SF_IR = 0.005`, `ρ_12 = 0.70`, `ρ_23 = 0.70`,
`ρ_13 = 0.30`:

```
inner   = 141,421,356² + 300,000,000² + 250,000,000²
        + 2 × 0.70 × 141,421,356 × 300,000,000
        + 2 × 0.70 × 300,000,000 × 250,000,000
        + 2 × 0.30 × 141,421,356 × 250,000,000
       ≈ 3.91 × 10¹⁷
AddOn_IR = 0.005 × sqrt(3.91 × 10¹⁷) ≈ 0.005 × 6.25 × 10⁸ ≈ 3,127,000
```

The same three trades placed in three separate currencies would yield
three separate hedging sets (`IR-NS_IR_DEMO-USD-LT_1Y`,
`IR-NS_IR_DEMO-EUR-1Y_5Y`, `IR-NS_IR_DEMO-GBP-GT_5Y`) — each contributing
its own quadratic form with the other two `D_Bk` terms set to zero, then
**summed in quadrature** at the IR asset-class level per the standard
Art. 277a(1)(a) per-currency decomposition.

### FX — per currency pair

See [fx-treatment.md](fx-treatment.md#ccr-a2-worked-example) for the
full CCR-A2 worked example (one 1-year GBP/USD outright forward in a
single-trade netting set). The FX worked example flows through:

```
adjusted_notional  = |100m USD| × 0.80 = 80,000,000 GBP    (Art. 279b(1)(b)(i))
MF                 ≈ 0.99965770                             (Art. 279c(1))
effective_notional ≈ 79,972,616.13
AddOn_HS           = 0.04 × 79,972,616.13 ≈ 3,198,904.67    (Art. 277a(2))
AddOn_FX           = 3,198,904.67                           (single HS; no cross-pair ρ)
```

A second non-overlapping pair (e.g. EUR/JPY) in the same netting set would
contribute its own `AddOn_HS` and the two add **plainly** with no
correlation — see Art. 277a(2) / CRE52.55.

### Credit — single name vs index

> **Status:** Pending engine batch P8.35–P8.38. The partition logic
> already exists in `assign_hedging_set` (`hedging_set_id = "CR-<netting_set_id>"`),
> but the worked example below depends on the credit asset-class add-on
> aggregation acceptance scenario being live. Numerical figures will be
> pinned by `tests/expected_outputs/ccr/CCR-A?.json` when that batch
> ships and the placeholder will be replaced with a fully reconciled
> golden example.

Sketch of the form (one netting set, two single-name CDS trades on
distinct entities, both IG):

```
SF_CR_SN_IG = 0.0046       (Art. 280 Table 1)
ρ_CR_SN     = 0.50         (Art. 280a)

EN_A    = δ_A × d_A × MF_A                 (entity A)
EN_B    = δ_B × d_B × MF_B                 (entity B)
AddOn_A = SF_CR_SN_IG × EN_A
AddOn_B = SF_CR_SN_IG × EN_B

AddOn_CR = sqrt(
    (0.50 × AddOn_A + 0.50 × AddOn_B)²
    + (1 − 0.25) × (AddOn_A² + AddOn_B²)
)
```

### Equity — single name vs index sub-classes

> **Status:** Pending engine batch P8.35–P8.38. As with credit, the
> partition is in place (`hedging_set_id = "EQ-<netting_set_id>"`) but
> the cross-entity systematic-idiosyncratic worked example needs the
> equity acceptance scenario.

Sketch (mixed-sub-class equity netting set):

```
SF_EQ_SN  = 0.32, ρ_EQ_SN  = 0.50      (Art. 280 Table 1, Art. 280b)
SF_EQ_IDX = 0.20, ρ_EQ_IDX = 0.80

# Per (NS, is_index) sub-class:
sum_D       = Σ_k D_k          (signed)
sum_D_sq    = Σ_k D_k²
AddOn_sub   = SF × sqrt( (ρ × sum_D)² + (1 − ρ²) × sum_D_sq )

AddOn_EQ    = AddOn_sub_SN + AddOn_sub_IDX     (Art. 280b — no cross-sub correlation)
```

### Commodity — five buckets, no cross-bucket correlation

> **Status:** Pending engine batch P8.35–P8.38. Bucket partition exists
> in `assign_hedging_set` (`hedging_set_id = "CO-<netting_set_id>-<commodity_type>"`)
> across the five valid `commodity_type` values; the worked example
> depends on the commodity add-on acceptance scenario being live.

Sketch (one netting set, one trade per bucket):

```
SF_CM           = {ELECTRICITY: 0.40, OIL_GAS / METALS / AGRICULTURAL / OTHER: 0.18}
ρ_CM            = 0.40            (Art. 280c — within-bucket only)

# Per bucket b:
D_b             = Σ_i in b ( δ_i × d_i × MF_i )            (signed)
sum_e²_b        = Σ_i in b ( δ_i × d_i × MF_i )²
AddOn_b         = SF_CM[b] × sqrt( ρ_CM² × D_b² + (1 − ρ_CM²) × sum_e²_b )

AddOn_CM        = sqrt( Σ_b AddOn_b² )    (no cross-bucket ρ)
```

A single-trade bucket collapses cleanly: `D_b = e_1`, `sum_e²_b = e_1²`,
and `sqrt(ρ² × e_1² + (1 − ρ²) × e_1²) = |e_1|`, so
`AddOn_b = SF_CM[b] × |e_1|`.

---

## References

- **PRA PS1/26 Counterparty Credit Risk (CRR) Part — Article 277** —
  hedging-set partition per asset class.
- **PRA PS1/26 Counterparty Credit Risk (CRR) Part — Article 277a** —
  asset-class add-on aggregation and cross-bucket correlation.
- **PRA PS1/26 Counterparty Credit Risk (CRR) Part — Article 280
  Table 1** — supervisory factors per asset class / sub-class.
- **PRA PS1/26 Counterparty Credit Risk (CRR) Part — Articles 280a / 280b /
  280c** — credit / equity / commodity correlations (`0.50 / 0.80`,
  `0.50 / 0.80`, and `0.40` respectively).
- **BCBS CRE52.30–37** — Basel-level methodology for the hedging-set
  partition.
- **BCBS CRE52.46–69** — Basel-level methodology for the asset-class
  aggregation, including the IR three-bucket correlation matrix and the
  credit / equity / commodity formulas.
- **`src/rwa_calc/engine/ccr/hedging_sets.py`** — engine implementation
  of `assign_ir_maturity_bucket` and `assign_hedging_set`.
- **`src/rwa_calc/rulebook/packs/common.py`** — cited pack params for the
  SA-CCR supervisory factors and correlations (`sa_ccr_ir_bucket_correlation_*`,
  `sa_ccr_correlation_*`, `sa_ccr_supervisory_factor_*`), read in
  `engine/ccr/pfe.py` via `_PACK.scalar_param(...)`.
- **`src/rwa_calc/engine/ccr/pfe.py`** — `compute_addon_per_asset_class`
  consumes the partition and applies the Art. 277a aggregation.
- **`tests/acceptance/ccr/test_ccr_a2_unmargined_fx_forward.py`** — FX
  hedging-set worked example (golden values pinned by `CCR-A2.json`).
- **[Adjusted notional](adjusted-notional.md)** — companion page for the
  per-asset-class adjusted notional `d`.
- **[FX treatment](fx-treatment.md)** — full FX worked example end-to-end.
