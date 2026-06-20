# SFT — Securities Financing Transactions (FCCM EAD)

Specifications for the **Financial Collateral Comprehensive Method (FCCM)**
exposure-at-default (EAD) for securities financing transactions (SFTs) —
repos, reverse repos, securities-borrowing/lending and margin-lending
transactions. FCCM is a **peer** of the SA-CCR derivative method, not a
sub-mode of it: the two regulatory methods diverge at the data boundary
(separate input bundles, separate pipeline stages) and share **zero**
computational code.

**Primary regulatory source:** CRR Art. 271(2) routes SFT EAD through the
FCCM (Art. 220–223), **not** the SA-CCR Art. 274 `EAD = α·(RC + PFE)`
derivative formula. References on this page follow the PRA-priority
convention: CRR Art. numbers first, PRA PS1/26 as a secondary
cross-reference.

**Engine entry point:** [`src/rwa_calc/engine/sft/fccm.py::sft_bundle_to_exposures`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/engine/sft/fccm.py)
— consumes the dedicated [`RawSFTBundle`](../../../data-model/input-schemas.md#sft-input-schemas-fccm)
(`RawDataBundle.sft`) and emits one synthetic exposure row per SFT netting
set with `risk_type = "CCR_SFT"`, `ccr_method = "fccm_sft"` and
`drawn_amount = E*`, compatible with the downstream Classifier / CRM / SA
exposure ladder.

!!! warning "Two unrelated meanings of \"SFT\" — do not conflate"
    The FCCM SFT path described on this page (`transaction_type == "sft"`,
    CCR EAD under CRR Art. 220–223) is a **completely different concept**
    from the `is_sft` Boolean carried on the loan / contingent / facility
    schemas (which drives the F-IRB 0.4-year maturity floor under CRR
    Art. 162). Same acronym, same `schemas.py`, **zero interaction**.
    See [The two meanings of "SFT"](#the-two-meanings-of-sft) below.

---

## Why SFTs are a peer subsystem, not part of SA-CCR

Before the SFT/FCCM separation, FCCM lived inside `engine/ccr/` and shared
the SA-CCR `TRADE_SCHEMA`, discriminated only by a free-text
`transaction_type` string. The two methods were physically co-mingled even
though they share no arithmetic. The separation promotes FCCM to a sibling
`engine/sft/` package so the divergence is visible at the seams a developer
naturally inspects.

| Concern | SA-CCR (derivatives) | FCCM (SFTs) |
|---|---|---|
| Regulatory EAD basis | CRR Art. 274 — `EAD = α·(RC + PFE)`, α = 1.4 | CRR Art. 271(2) → Art. 220–223 — `E* = max(0, E·(1+HE) − CVA·(1−HC−HFX))` |
| Input bundle | `RawDataBundle.ccr` (`RawCCRBundle`) | `RawDataBundle.sft` (`RawSFTBundle`) |
| Input schema | `TRADE_SCHEMA` (30 cols, derivative-shaped) | `SFT_TRADE_SCHEMA` (10 cols, lean) + optional `SFT_COLLATERAL_SCHEMA` |
| Dataload | `ccr_trades` / `ccr_netting_sets` / … | `sft_trades` (+ optional `sft_collateral`) |
| Pipeline stage | `ccr_sa_ccr` (`engine/stages/ccr.py`) | `sft_fccm` (`engine/stages/sft.py`) |
| Shared computation | rulepack supervisory factors, hedging sets, add-ons | supervisory haircuts (`engine/crm/haircut_tables.py`) |
| Output `risk_type` | `CCR_DERIVATIVE` | `CCR_SFT` |
| Output `ccr_method` | `sa_ccr` | `fccm_sft` |

> **Details:** the architectural rationale, alternatives weighed, and the
> phased migration are recorded in
> [`docs/plans/sft-fccm-separation.md`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/docs/plans/sft-fccm-separation.md).

"Where do SFTs diverge from derivatives?" is answered by *reading the
registry* — two adjacent `StageSpec` entries, `ccr_sa_ccr` then `sft_fccm`
([`engine/registry.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/engine/registry.py)).

---

## The FCCM E\* formula (Art. 223(5))

For an SFT netting set, the fully-adjusted exposure value `E*` is:

```
E* = max( 0,  E·(1 + HE)  −  CVA·(1 − HC − HFX) )
```

where:

| Term | Meaning | Source |
|------|---------|--------|
| `E` | Exposure amount lent / sold under the SFT (the trade `notional`) | Art. 223(5) |
| `HE` | Volatility (supervisory) haircut **appropriate to the exposure** | Art. 223(5), Art. 224 Table 1 |
| `CVA` | Volatility-adjusted value of the collateral received (market value) | Art. 223(5) |
| `HC` | Volatility haircut appropriate to the **collateral** | Art. 224 Table 1 |
| `HFX` | Haircut for any **currency mismatch** between collateral and exposure | Art. 224 Table 4 (8%; 0 when currencies match) |

The supervisory haircuts `H_10` (10-business-day daily-revaluation holding
period) come from the CRR Art. 224 Table 1 lookup by collateral type / issuer
CQS / residual maturity. The **applied** haircut is the full three-factor
expression:

```
H = H_10 · sqrt( T_M / 10 ) · sqrt( (N_R + T_M − 1) / T_M )
```

with:

- `sqrt( T_M / 10 )` — the **Art. 224(2)** liquidation-period rescale (the
  published 5/10/20-day columns are `H_10 · sqrt(T_M/10)`). `T_M` is the
  holding/liquidation period in business days appropriate to the branch
  (5 for unmargined repo/SFT, Art. 224(2)(b); the MPOR for margined sets).
- `sqrt( (N_R + T_M − 1) / T_M )` — the **Art. 226** non-daily revaluation
  scale-up, driven by `N_R = remargining_frequency_days`. It **collapses to
  1.0 at daily revaluation** (`N_R = 1`), so a daily-revalued unmargined SFT
  sees only the period rescale (the regression anchor). Art. 226 has **no
  numbered paragraphs** — do not write "Art. 226(2)".

The same three-factor form applies independently to `HE` (exposure
security), `HC` (collateral security) and `HFX` (the 8% currency-mismatch
base, Art. 224 Table 4 / Art. 233(4)). Both the haircut table and the
business-day periods resolve from the rulepack — the FCCM engine declares no
regulatory scalars of its own (project data/engine separation rule).

### Two mutually-exclusive branches (margined vs unmargined)

The holding period `T_M` and whether the Art. 226 non-daily factor applies
are selected per netting set on the `is_margined` flag. The two branches are
**never combined** ([`engine/sft/fccm.py::_derive_margining_terms`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/engine/sft/fccm.py)):

- **Branch (a) — unmargined / simply-collateralised** (`is_margined` False or
  absent; today's behaviour). `T_M` is the transaction-type liquidation
  period — **5 business days** for the FCCM repo/SFT path (Art. 224(2)(b)).
  The Art. 226 non-daily term **is applied**, with `N_R =
  remargining_frequency_days`. At daily revaluation (`N_R = 1`) the term is
  exactly 1.0, so the unmargined-daily path is **bit-identical** to the prior
  behaviour (verified by IEEE-754 hex probe and the unchanged CCR-A11/A12
  goldens).
- **Branch (b) — margined** (qualifying Art. 285(2)–(4) collateral agreement;
  legal hook = the final subparagraph of Art. 224(2)). `T_M` is the
  **margin period of risk** `MPOR = F + N − 1` (Art. 285(5)), and the Art. 226
  non-daily term is **suppressed** (`N_R = 1`) because the MPOR already encodes
  the remargin period `N`. The floor `F` is `5` for repo / securities- or
  margin-lending-only sets (Art. 285(2)(a)), `10` for other sets
  (Art. 285(2)(b)) and `20` for sets with > 5000 trades **or** illiquid /
  hard-to-replace collateral (Art. 285(3) — two independent triggers). `F` is
  **doubled** for the two quarters following more than two margin disputes
  (Art. 285(4)). An explicit `mpor_days_override` supersedes the `F + N − 1`
  derivation. All `F` values and the dispute multiplier resolve from cited
  rulepack scalars — no regulatory numerics are hardcoded in the engine.

The five input columns that drive this selection (`is_margined`,
`remargining_frequency_days`, `mpor_floor_category`,
`has_margin_dispute_doubling`, `mpor_days_override`) are documented on the
[SFT input schema page](../../../data-model/input-schemas.md#sft-input-schemas-fccm);
all default so that the unmargined-daily path reproduces today's `E*` exactly.

Engine entry point:

```python
from rwa_calc.engine.sft.fccm import sft_bundle_to_exposures

# E* = max(0, E·(1+HE) − CVA·(1−HC−HFX))   (CRR Art. 223(5))
# Reads RawSFTBundle, writes one synthetic exposure row per netting set.
```

Source: [`src/rwa_calc/engine/sft/fccm.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/engine/sft/fccm.py)
— reuses `lookup_collateral_haircut`, `scale_haircut_for_liquidation_period`
and `FX_HAIRCUT` from `engine/crm/haircut_tables.py` (pack-bound), which is
its **only** cross-package engine dependency.

---

## Pipeline placement — the `sft_fccm` stage

FCCM runs as a dedicated stage immediately after the SA-CCR stage:

```
hierarchy_resolver → ccr_sa_ccr → sft_fccm → classifier → crm_processor → …
```

The `sft_fccm` stage ([`engine/stages/sft.py::run`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/engine/stages/sft.py)):

1. **No-ops when `data.sft is None`** — a firm with no SFT book is
   completely unaffected (`RawDataBundle.sft` defaults `None`).
2. **Fails loud on reserved methods.** `SFTConfig.method` selects the SFT
   EAD method per Art. 271(2). Only `"fccm"` (Art. 220–223) is implemented;
   `"var"` (Art. 221) and `"imm"` (Art. 283) are reserved literals that
   raise `NotImplementedError` rather than silently dropping SFT rows.
3. **Computes `E*`** at netting-set grain via `sft_bundle_to_exposures`.
4. **Enriches counterparty ratings** onto each synthetic row (shared with
   the SA-CCR stage via `engine/stages/_ccr_shared.py`) so the SA
   institution risk-weight lookup (CRR Art. 120(1) Table 3) and any IRB
   routing see the same rating as a traditional lending row.
5. **Appends** the SFT rows onto `resolved.exposures` via a
   `diagonal_relaxed` concat and **re-seals against the existing
   `ccr_exit` brand** — *not* a new `sft_exit` brand.

!!! danger "The SFT stage seals to the `ccr_exit` brand by design"
    Downstream stages select their CCR-variant edge by **exact
    brand-string equality** (the classifier expects `ccr_exit`). A fresh
    `sft_exit` brand would de-select SFT rows onto the non-CCR edge and
    strip their provenance columns (`source_netting_set_id`, `ccr_method`,
    `ead_ccr`), or the sealed-frame validator would reject the frame. SFT
    and derivative rows share the same `resolved.exposures` frame; the
    SFT-vs-derivative typing lives in the **input** bundle and schema, not
    in a new exit brand. SA-CCR provenance columns stay null on SFT rows
    naturally because the FCCM path never projects them.

From the seal onward an SFT row is treated like any other unsecured
institution / corporate-style exposure: the Classifier resolves the
counterparty class, the SA calculator looks up the risk weight
([Art. 120–122](../sa-risk-weights.md)), and the aggregator rolls the RWA
into firm totals.

---

## Downstream treatment (output floor + reporting)

FCCM SFTs are SA-risk-weighted, so under Basel 3.1 they participate in the
output floor and report under the Standardised credit-risk template:

- **Output floor.** FCCM SFT RWA enters the Basel 3.1 output-floor S-TREA /
  U-TREA numerators (PS1/26 Art. 92(3A) does **not** place SFTs on the
  S-TREA exclusion list). SFT rows receive the floor-eligible
  `standardised_ccr` tag. CRR runs have no output floor and are unaffected.
- **COREP.** FCCM SFT EAD is reported under **C 07.00 / OF 07.00 row 0090
  ("SFT netting sets")** — the Standardised credit-risk template — **not**
  the SA-CCR derivative templates (C 34.01/02/08). Template guidance:
  PS1/26 Appendix 17.
- **Pillar 3.** SFT EAD is excluded from the SA-CCR CCR1 / CCR8 disclosure
  tables (which carry derivatives only) by the same `risk_type != "CCR_SFT"`
  collector exclusion.

---

## The two meanings of "SFT"

The acronym "SFT" denotes **two unrelated concepts** in this codebase. They
never interact, despite sharing the name and the `schemas.py` module.

| | FCCM SFT (this page) | Lending `is_sft` |
|---|---|---|
| Carrier | `transaction_type == "sft"` on `SFT_TRADE_SCHEMA` | `is_sft` Boolean on `LOAN` / `CONTINGENT` / `FACILITY` schemas |
| Concept | Securities financing transaction routed to **FCCM CCR EAD** | A lending exposure that **is** a securities financing transaction for the F-IRB maturity carve-out |
| What it drives | The `sft_fccm` stage: `E* = max(0, E·(1+HE) − CVA·(1−HC−HFX))` | The F-IRB **0.4-year maturity (`M`) floor** in lieu of the 1-year floor |
| Regulatory basis | CRR Art. 220–223, Art. 271(2) | CRR Art. 162(3) |
| Engine site | `engine/sft/fccm.py` | `engine/irb/transforms.py` |

Promoting FCCM to `engine/sft/` already reduces the day-to-day grep
ambiguity: CCR-SFT hits land in `engine/sft/`; lending-SFT hits land in
`engine/irb/` and the lending schemas. The `is_sft` Boolean is deliberately
**not renamed** in this work — a rename would touch the sealed
`hierarchy_resolved` edge, the IRB transforms, the
`firb_sft_supervisory_maturity` pack feature and every fixture that sets
`is_sft`, so it is reserved for a standalone future codemod.

---

## Scope and reserved methods

The FCCM implementation is deliberately narrow (revisited as new SFT
scenarios land):

| In scope | Out of scope (reserved / deferred) |
|---|---|
| FCCM (Art. 220–223), the only implemented method | VaR method (Art. 221) — `SFTConfig.method = "var"`, fails loud |
| Single-trade, single-counterparty netting sets (Art. 220(1)(a)) | IMM method (Art. 283) — `SFTConfig.method = "imm"`, fails loud |
| Unmargined SFTs (Art. 224(2)(b) 5-BD liquidation period) | Own-estimate / VaR haircuts |
| Margined FCCM (Art. 285 MPOR; `F + N − 1`, dispute doubling) | Art. 227(2)(a)–(h) 0% core-market-participant carve-out |
| Standardised supervisory haircuts (Art. 220(3)(a)(i)) | |

---

## References

- **CRR Art. 220(1)(a)** — single-counterparty SFT / master-netting-set scope.
- **CRR Art. 220(3)(a)(i)** — standardised supervisory haircuts.
- **CRR Art. 223(5)** — `E* = max(0, E·(1+HE) − CVA·(1−HC−HFX))`.
- **CRR Art. 224 Table 1** — `H_10` supervisory haircuts by collateral type / CQS / residual maturity.
- **CRR Art. 224(2)(b)** — 5-business-day liquidation period for repo/SFT.
- **CRR Art. 224(2) final subparagraph** — legal hook for the margined branch.
- **CRR Art. 224 Table 4** — 8% currency-mismatch haircut (`HFX`).
- **CRR Art. 226** — the applied haircut `H = H_10 · sqrt(T_M/10) · sqrt((N_R+T_M−1)/T_M)` (Art. 224(2) period rescale + Art. 226 non-daily revaluation scale-up). Art. 226 has no numbered paragraphs.
- **CRR Art. 271(2)** — SFT EAD via FCCM, not SA-CCR Art. 274.
- **CRR Art. 285(2)–(5)** — margined MPOR floors (`F` = 5/10/20), the `F + N − 1` margin period of risk and the Art. 285(4) dispute-doubling multiplier.
- **PRA PS1/26 Art. 92(3A)** — output-floor inclusion of SA-CCR / FCCM EAD.
- **PRA PS1/26 Appendix 17** — COREP / OF 07.00 row 0090 ("SFT netting sets") template guidance.
- **`src/rwa_calc/engine/sft/fccm.py`** — FCCM engine implementation.
- **`src/rwa_calc/engine/stages/sft.py`** — `sft_fccm` stage adapter.

## Cross-references

- [SA-CCR — Counterparty Credit Risk](../ccr/index.md) — the SA-CCR
  derivative method (Art. 274) that FCCM sits beside.
- [Input schemas — SFT input contract](../../../data-model/input-schemas.md#sft-input-schemas-fccm)
  — `SFT_TRADE_SCHEMA` / `SFT_COLLATERAL_SCHEMA` columns and the
  `sft_trades` dataload.
- [SA risk weights (CRR)](../sa-risk-weights.md) — the risk-weight lookup
  the SFT EAD flows through downstream.
- [Credit risk mitigation](../credit-risk-mitigation.md) — the supervisory
  haircut framework FCCM reuses.
