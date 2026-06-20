# SA-CCR — Maturity factor (Art. 279c)

The maturity factor `MF` scales each trade's effective notional to reflect
how much of the supervisory horizon (one year) the trade actually spans.
SA-CCR carries **two** branches: unmargined netting sets use a residual-
maturity formula capped at one year (Art. 279c(1)); margined netting sets
use a margin-period-of-risk (MPOR) formula calibrated to the supervisory
close-out horizon (Art. 279c(2)). The MPOR itself is derived from a
cascade of Art. 285(2)–(5) rules that escalate the close-out window for
large, illiquid, or disputed portfolios.

This page is asset-class-agnostic — the same formulas apply across IR,
FX, credit, equity, and commodity trades. It feeds the per-asset-class
add-on aggregation in
[`pfe.md`](pfe.md) (forthcoming) via the trade-level
`effective_notional = supervisory_delta × adjusted_notional × maturity_factor`.

## Unmargined formula — Art. 279c(1)

For trades in an **unmargined** netting set:

```
MF_unmargined = sqrt( min(M, 1y) / 1y )
```

where `M` is the residual maturity in years from the reporting date to
the trade's maturity date, with the regulatory floor

```
M >= 10 business days = 10 / 250 = 0.04 years
```

applied upstream when populating `years_to_maturity` (250 business-day
year convention per BCBS CRE52.40 footnote).

The `1y` cap means any trade with `M >= 1y` collapses to `MF = 1.0`. The
`10 BD` floor means very short-dated trades never collapse below
`sqrt(0.04) ≈ 0.20`.

Engine entry point:

```python
from rwa_calc.engine.ccr.maturity_factor import compute_maturity_factor_unmargined

def compute_maturity_factor_unmargined(trades: pl.LazyFrame) -> pl.LazyFrame:
    """MF = sqrt(min(M, 1y) / 1y). Reads `years_to_maturity`,
    writes `maturity_factor`. See `src/rwa_calc/engine/ccr/maturity_factor.py`."""
```

Source: `src/rwa_calc/engine/ccr/maturity_factor.py::compute_maturity_factor_unmargined`.

## Margined formula — Art. 279c(2)

For trades in a **margined** netting set (one with a legally enforceable
margin agreement requiring at least daily exchange of variation margin):

```
MF_margined = 1.5 × sqrt( MPOR_eff / 250 )
```

where:

- The `1.5` supervisory multiplier (Art. 279c(2)) reflects the
  conservatism added on top of the diffusion shape.
- `MPOR_eff` is the **effective margin period of risk in business days**
  produced by the Art. 285 cascade (next section).
- The `250` divisor expresses `MPOR_eff` as a fraction of the
  business-day year.

When `MPOR_eff = 10` (the OTC base — the only base this derivatives-only
engine uses), `MF_margined = 1.5 × sqrt(10/250) ≈ 0.30`. When `MPOR_eff = 20`
(large or illiquid netting sets), `MF_margined ≈ 0.42`.

Engine entry point:

```python
from rwa_calc.engine.ccr.maturity_factor import compute_maturity_factor_margined

def compute_maturity_factor_margined(trades: pl.LazyFrame) -> pl.LazyFrame:
    """MF = 1.5 * sqrt(MPOR_eff / 250). MPOR_eff is the Art. 285 cascade.
    See `src/rwa_calc/engine/ccr/maturity_factor.py`."""
```

Source: `src/rwa_calc/engine/ccr/maturity_factor.py::compute_maturity_factor_margined`.

## MPOR cascade — Art. 285(2)–(5)

`MPOR_eff` is built up in five sequential steps, each broadcast across
the trades in a netting set via `.over("netting_set_id")`.

### Step 1 — Base MPOR (Art. 285(2))

| Netting-set composition                              | Base MPOR        | Constant                              |
| ---------------------------------------------------- | ---------------- | ------------------------------------- |
| OTC derivative netting set (Art. 285(2)(b))          | **10 BD**        | `MF_MARGINED_FLOOR_DAYS_OTC`          |

The base is a **constant 10 BD**: this engine's SA-CCR maturity factor is
**derivatives-only**, so every netting set reaching
`compute_maturity_factor_margined` is an OTC derivative netting set and the
Art. 285(2)(b) 10 BD floor always applies.

!!! note "The Art. 285(2)(a) 5-BD SFT/repo base is not modelled here"
    Securities financing transactions (SFTs) are priced by the **FCCM**
    `sft_fccm` stage from `RawDataBundle.sft` and **never enter the SA-CCR
    chain** (SFT/FCCM separation). They therefore never reach this maturity
    factor, so the Art. 285(2)(a) 5-BD SFT/repo/margin-lending base — and the
    per-netting-set "all trades are SFT" (`transaction_type == "sft"`) test
    that selected it — has been removed from the engine. See the
    [SFT (FCCM EAD) specification](../sft/index.md).

### Step 2 — Large or illiquid upgrade (Art. 285(3))

The base MPOR is **replaced** (not added to) with 20 BD when either
condition is met:

| Trigger                                                                  | Constant                                  |
| ------------------------------------------------------------------------ | ----------------------------------------- |
| `number_of_trades > 5000` in the netting set (Art. 285(3)(a))            | `MF_MARGINED_LARGE_NETTING_SET_TRADE_COUNT` |
| `has_illiquid_collateral_or_hard_to_replace_otc == True` (Art. 285(3)(b)) | column-driven                             |

The Art. 285(3)(b) flag is populated on the netting-set input table by
the firm; the engine joins it onto each trade as `has_illiquid` at the
pipeline-adapter join site. Either trigger fires the upgrade
independently — the constant `MF_MARGINED_FLOOR_DAYS_LARGE_OR_ILLIQUID`
defines the 20 BD ceiling.

### Step 3 — Dispute doubling (Art. 285(4))

If the netting set has experienced **more than two** valid margin-call
disputes in the prior two quarters lasting longer than the applicable
MPOR, the MPOR base from Step 2 is doubled:

```
base_post_step3 = base_post_step2 × 2   if   dispute_count_qtr > 2
                                            (MF_MARGINED_DISPUTE_THRESHOLD = 2,
                                             MF_MARGINED_DISPUTE_MULTIPLIER = 2)
```

A netting set that started at 10 BD (Step 1) goes to 20 BD here. One
that started at 20 BD (Step 2) goes to 40 BD. Once the disputes fall
back below the threshold for a clean quarter, the next pipeline run
drops back to the lower base — the doubling is not sticky.

### Step 4 — Remargining-frequency adjustment (Art. 285(5))

Daily remargining is the implicit assumption behind the Art. 285(2)
bases. For less-than-daily CSA remargining, the MPOR is extended by the
remargining interval minus one business day:

```
MPOR_eff_pre_floor = base_post_step3 + remargining_frequency_days − 1
```

For daily remargining (`remargining_frequency_days = 1`) this collapses
to the Step 3 base (no extension). For weekly remargining
(`remargining_frequency_days = 5`) it adds 4 BD on top of the base.

### Step 5 — Input-MPOR floor

A final floor lets firms supply a higher MPOR directly (e.g. from
internal escalation rules or supervisory overlays):

```
MPOR_eff = max( MPOR_eff_pre_floor, mpor_days_input )
```

`mpor_days_input` is a row-level column; when no override is supplied,
the firm passes `mpor_days_input = 0` (or the engine default) so the
Step 4 result flows through unchanged.

## Engine implementation

The complete margined cascade is implemented as a single LazyFrame
chain. The function reads the per-trade inputs documented above and
writes a `maturity_factor: Float64` column:

```python
# src/rwa_calc/engine/ccr/maturity_factor.py
# Step 1 — constant Art. 285(2)(b) 10-BD OTC base. Derivatives-only engine:
# there is no all-SFT (5-BD) branch — SFTs are priced by the sft_fccm stage.
base_post_step1 = pl.lit(_MF_FLOOR_DAYS_OTC)             # 10 BD

is_large_or_illiquid = (
    pl.col("number_of_trades") > pl.lit(_MF_LARGE_NETTING_SET_TRADE_COUNT)
) | pl.col("has_illiquid")

base_post_step2 = (
    pl.when(is_large_or_illiquid)
    .then(pl.lit(_MF_FLOOR_DAYS_LARGE_OR_ILLIQUID))      # 20 BD
    .otherwise(base_post_step1)
)

base_post_step3 = (
    pl.when(pl.col("dispute_count_qtr") > pl.lit(_MF_DISPUTE_THRESHOLD))
    .then(base_post_step2 * pl.lit(_MF_DISPUTE_MULTIPLIER))
    .otherwise(base_post_step2)
)

mpor_eff_pre_floor = base_post_step3 + pl.col("remargining_frequency_days") - pl.lit(1)
# Null-safe floor: a null mpor_days_input falls back to the 10-BD OTC base
# so a missing firm-supplied MPOR never silently nulls the margined MF.
mpor_eff = pl.max_horizontal(
    mpor_eff_pre_floor, pl.col("mpor_days_input").fill_null(_MF_FLOOR_DAYS_OTC)
)

maturity_factor = (
    pl.lit(_MF_MARGINED_SCALAR)                          # 1.5
    * (mpor_eff.cast(pl.Float64) / pl.lit(float(_SA_CCR_BUSINESS_DAYS_PER_YEAR))).sqrt()
).cast(pl.Float64)

# Gated on is_margined: unmargined rows get null so the pipeline-adapter
# coalesce falls back to the unmargined MF (CRR Art. 279c(1)).
maturity_factor_margined = (
    pl.when(pl.col("is_margined")).then(maturity_factor).otherwise(None)
)
```

Constants resolve from the rulebook pack
(`src/rwa_calc/rulebook/packs/common.py`) once at module load — `engine/`
modules read the resolved pack and never inline these regulatory scalars
(project architectural rule, enforced by `scripts/arch_check.py` check 5).
The Art. 285(2)(a) 5-BD SFT/repo base param (`mf_margined_floor_days_repo_sft`)
is no longer read here — this function is derivatives-only.

## Pipeline ordering

Both `compute_maturity_factor_*` functions sit between
`compute_supervisory_delta_*` and the hedging-set / add-on stages:

```
trades → years_to_maturity
       → compute_adjusted_notional_ir(reporting_date)
       → compute_adjusted_notional_fx(base_currency, fx_rates)
       → compute_supervisory_delta_linear
       → compute_maturity_factor_unmargined          # OR _margined per NS
       → assign_hedging_set
       → compute_addon_per_asset_class
       → compute_pfe
```

The `engine/ccr/pipeline_adapter.py` orchestrator wires **both** paths
(P8.54): it denormalises the Art. 285 cascade inputs onto each trade,
computes the margined MF, and coalesces the `is_margined`-gated
`maturity_factor_margined` over the unmargined `maturity_factor` before the
PFE add-on. Unmargined netting sets (e.g. CCR-A1 .. CCR-A10) fall through to
`compute_maturity_factor_unmargined`; margined sets (CCR-A13 daily-remargin,
CCR-A14 long-remargin) take the Step 1–5 cascade above.

## Worked numeric examples

All three examples use the formula

```
MF_margined = 1.5 × sqrt(MPOR_eff / 250)
```

with the cascade producing `MPOR_eff`. Inputs are stripped to the
columns that drive each branch. Every netting set is an OTC derivative
netting set (SFTs never reach this function), so Step 1 is always the
Art. 285(2)(b) 10-BD base.

### Example 1 — OTC base (10 BD), daily remargining

```
number_of_trades            = 100
has_illiquid                = False
dispute_count_qtr           = 0
remargining_frequency_days  = 1
mpor_days_input             = 0

Step 1: base                = 10 BD     (Art. 285(2)(b) OTC base)
Step 2: base                = 10 BD     (not large, not illiquid)
Step 3: base                = 10 BD     (no dispute)
Step 4: pre-floor           = 10 + 1 − 1 = 10 BD
Step 5: MPOR_eff            = max(10, 0) = 10 BD

MF_margined = 1.5 × sqrt(10 / 250)
            = 1.5 × sqrt(0.04)
            = 1.5 × 0.20
            = 0.30
```

### Example 2 — Large netting set (20 BD upgrade), daily remargining

```
number_of_trades            = 7,500     (> 5,000 threshold)
has_illiquid                = False
dispute_count_qtr           = 0
remargining_frequency_days  = 1
mpor_days_input             = 0

Step 1: base                = 10 BD
Step 2: base                = 20 BD     (Art. 285(3)(a) > 5,000 trades)
Step 3: base                = 20 BD
Step 4: pre-floor           = 20 + 1 − 1 = 20 BD
Step 5: MPOR_eff            = 20 BD

MF_margined = 1.5 × sqrt(20 / 250)
            = 1.5 × sqrt(0.08)
            = 1.5 × 0.28284
            ≈ 0.42426
```

The same `MPOR_eff = 20 BD` is reached via the Art. 285(3)(b) illiquid /
hard-to-replace-OTC flag — the engine treats the two triggers as a
logical OR.

### Example 3 — Dispute doubling + weekly remargining

```
number_of_trades            = 100
has_illiquid                = False
dispute_count_qtr           = 3         (> 2 threshold)
remargining_frequency_days  = 5         (weekly CSA)
mpor_days_input             = 0

Step 1: base                = 10 BD
Step 2: base                = 10 BD
Step 3: base                = 10 × 2 = 20 BD   (Art. 285(4) doubling)
Step 4: pre-floor           = 20 + 5 − 1 = 24 BD
Step 5: MPOR_eff            = max(24, 0) = 24 BD

MF_margined = 1.5 × sqrt(24 / 250)
            = 1.5 × sqrt(0.096)
            = 1.5 × 0.30984
            ≈ 0.46476
```

### Unmargined sanity check — Art. 279c(1)

Used by every **unmargined** CCR-A acceptance scenario (`years_to_maturity`
is the residual maturity in years):

```
M = 0.99931554 years      (1-year forward, reporting_date = 2026-01-15)
MF_unmargined = sqrt( min(0.99931554, 1.0) / 1.0 )
              = sqrt(0.99931554)
              ≈ 0.99965770
```

A 10-business-day forward sits at the floor:

```
M_floor = 10 / 250 = 0.04
MF_unmargined = sqrt(0.04) = 0.20
```

A 10-year swap collapses to the cap:

```
MF_unmargined = sqrt( min(10, 1.0) / 1.0 ) = sqrt(1.0) = 1.0
```

## References

- CRR Art. 279c(1) — unmargined maturity factor `sqrt(min(M, 1y)/1y)`.
- CRR Art. 279c(2) — margined maturity factor `1.5 × sqrt(MPOR_eff/250)`.
- CRR Art. 285(2) — base MPOR floors. This derivatives-only engine uses the
  Art. 285(2)(b) 10-BD OTC base; the Art. 285(2)(a) 5-BD SFT/repo base does
  not apply (SFTs are priced by the FCCM `sft_fccm` stage, not SA-CCR).
- CRR Art. 285(3) — 20 BD upgrade for >5,000-trade netting sets and
  illiquid / hard-to-replace OTC.
- CRR Art. 285(4) — dispute doubling when prior-quarter disputes
  exceed two.
- CRR Art. 285(5) — remargining-frequency adjustment
  `MPOR_eff = base + N − 1`.
- PRA PS1/26 Counterparty Credit Risk (CRR) Part 1.3, 3.7-3.8 — UK
  onshored equivalents; numerical values match CRR. Art. 285(2)–(5) is
  imported by reference via the Counterparty Credit Risk (CRR) Part
  paragraph 8 ("minimum liquidation period … brought in line with the
  margin period of risk that would apply under those paragraphs").
- BCBS CRE52.48–52.52 — Basel methodology underlying Art. 279c and the
  Art. 285 cascade.
- `src/rwa_calc/engine/ccr/maturity_factor.py` — engine implementation
  (both branches plus the full cascade).
- `src/rwa_calc/rulebook/packs/common.py` — cited pack params
  (`mf_margined_scalar`, `mf_margined_floor_days_*`,
  `mf_margined_large_netting_set_trade_count`,
  `mf_margined_dispute_threshold`, `mf_margined_dispute_multiplier`,
  `sa_ccr_business_days_per_year`), read in
  `engine/ccr/maturity_factor.py` via `_PACK.scalar_param(...)` /
  `_PACK.int_param(...)`.
- `tests/acceptance/ccr/test_ccr_a1_unmargined_ir_swap.py` ..
  `test_ccr_a10_mixed_asset_class.py` — unmargined-branch golden values.
