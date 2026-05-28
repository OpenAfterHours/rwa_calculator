# SA-CCR — Wrong-way risk (Art. 291)

**Wrong-way risk (WWR)** is the regulatory recognition that the SA-CCR
exposure formula `EAD = α · (RC + PFE)` understates the loss-given-default
whenever the future exposure to a counterparty and that counterparty's
probability of default move together. Article 291 splits the phenomenon
into two qualitatively different cases and prescribes a distinct
treatment for each:

- **General wrong-way risk** (Art. 291(1)(a)) — a *portfolio-level*
  correlation between counterparty creditworthiness and broad market
  risk factors. Identification is qualitative (stress-testing,
  monitoring, senior-management reporting under Art. 291(3) and (6));
  the SA-CCR engine flags affected netting sets but does not numerically
  adjust the EAD because the regulatory uplift for general WWR lives
  inside the IMM `α` re-estimation per Art. 284(9). For SA-CCR the
  general-WWR branch is therefore **diagnostic only** — the netting set
  continues through the standard `α = 1.4` chain.
- **Specific wrong-way risk** (Art. 291(1)(b)) — a *transaction-level*
  legal connection between the counterparty and the issuer of the
  derivative's underlying (canonically, a single-name CDS where the
  reference entity is the counterparty itself). Identification is
  operational and the treatment is mechanical: the affected trade is
  carved out into its own single-trade synthetic netting set
  (Art. 291(5)(a)) and downstream LGD is overridden to 100%
  (Art. 291(5)(c)).

This page documents:

- the Art. 291(1)(a)/(b) definitions and the Art. 291(2)–(4)
  identification process;
- the Art. 291(5)(a)/(c) specific-WWR carve-out and LGD = 100% override
  the engine implements;
- the Art. 291(4) general-WWR demarcation (out of scope for SA-CCR
  numerical impact — handled in IMM via the modified `α`);
- the engine entry point and the pipeline position of `apply_wwr_gate`
  relative to the legal-enforceability gate and the SA-CCR calculator
  chain;
- a worked example for a single-name CDS sold against the counterparty
  itself.

## Regulatory citation

**Primary source:** PRA Rulebook — Counterparty Credit Risk (CRR) Part,
Article 291 (Wrong-Way Risk). The UK regime is a verbatim re-export of
the onshored CRR text; PRA PS1/26 does not amend Article 291, so the
specific-WWR LGD = 100% override and the general-WWR identification
duties carry forward unchanged into the Basel 3.1 regime effective
1 January 2027.

| Sub-article | Coverage | BCBS cross-reference |
|-------------|----------|----------------------|
| Art. 291(1)(a) | Definition of *general WWR* — positive correlation between counterparty PD and general market risk factors | CRE53.2 |
| Art. 291(1)(b) | Definition of *specific WWR* — positive correlation between future exposure and counterparty PD due to the *nature of the transactions* | CRE53.3 |
| Art. 291(2)    | Institutions shall give due consideration to exposures that give rise to a significant degree of WWR (general or specific) | CRE53.4 |
| Art. 291(3)    | Identification of general WWR via stress-testing and scenario analysis monitoring by product, region, industry | CRE53.5 |
| Art. 291(4)    | Procedures to identify, monitor and control specific WWR for each legal entity from inception through life of transaction | CRE53.6 |
| Art. 291(5)(a) | Specific-WWR trades **shall not be included in the same netting set as other transactions with the counterparty, and shall each be treated as a separate netting set** | CRE53.7 |
| Art. 291(5)(b) | Single-name CDS exposure value equals the full expected loss on the underlying assuming liquidation of the issuer | CRE53.7 |
| Art. 291(5)(c) | **LGD shall be 100% for such swap transactions** (for institutions using the IRB approach of Chapter 3) | CRE53.7 |
| Art. 291(5)(d) | For institutions using the SA, the applicable risk weight shall be that of an unsecured transaction | CRE53.7 |
| Art. 291(5)(e) | For all other transactions referencing a single name, exposure value shall be consistent with jump-to-default of the legally connected obligation | CRE53.7 |
| Art. 291(5)(f) | Where market-risk IDR calculations already contain an LGD assumption, the LGD shall be 100% | CRE53.7 |
| Art. 291(6)    | Regular reports to senior management and the management body on both specific and general WWR | CRE53.8 |

### Verbatim text — PRA Rulebook Art. 291(1)

> "For the purposes of this Article:
>
> - (a) 'General Wrong-Way risk' arises when the likelihood of default
>   by counterparties is positively correlated with general market risk
>   factors;
> - (b) 'Specific Wrong-Way risk' arises when future exposure to a
>   specific counterparty is positively correlated with the
>   counterparty's PD due to the nature of the transactions with the
>   counterparty. An institution shall be considered to be exposed to
>   Specific Wrong-Way risk if the future exposure to a specific
>   counterparty is expected to be high when the counterparty's
>   probability of a default is also high."

— PRA Rulebook, Counterparty Credit Risk (CRR) Part, Art. 291(1)
(source PDF: `docs/assets/crr.pdf`, p. 289).

### Verbatim text — PRA Rulebook Art. 291(5)

> "Institutions shall calculate the own funds requirements for CCR in
> relation to transactions where Specific Wrong-Way risk has been
> identified and where there exists a legal connection between the
> counterparty and the issuer of the underlying of the OTC derivative
> or the underlying of the transactions referred to in points (b), (c)
> and (d) of Article 273(2)), in accordance with the following
> principles:
>
> - (a) the instruments where Specific Wrong-Way risk exists shall not
>   be included in the same netting set as other transactions with the
>   counterparty, and shall each be treated as a separate netting set;
> - (b) within any such separate netting set, for single-name credit
>   default swaps the exposure value equals the full expected loss in
>   the value of the remaining fair value of the underlying instruments
>   based on the assumption that the underlying issuer is in
>   liquidation;
> - (c) LGD for an institution using the approach set out in Chapter 3
>   shall be 100% for such swap transactions;
> - (d) for an institution using the approach set out in Chapter 2 of
>   this Regulation and Articles 132a to 132c of Chapter 3 of the
>   Standardised Approach and Internal Ratings Based Approach to Credit
>   Risk (CRR) Part of the PRA Rulebook, the applicable risk weight
>   shall be that of an unsecured transaction;
> - (e) for all other transactions referencing a single name in any
>   such separate netting set, the calculation of the exposure value
>   shall be consistent with the assumption of a jump-to-default of
>   those underlying obligations where the issuer is legally connected
>   with the counterparty…"

— PRA Rulebook, Counterparty Credit Risk (CRR) Part, Art. 291(5)
(source PDF: `docs/assets/crr.pdf`, p. 290).

---

## (a) Specific WWR — Art. 291(1)(b), 291(4), 291(5)

### Definition (Art. 291(1)(b))

Specific WWR arises when **the future exposure to a specific
counterparty is positively correlated with the counterparty's PD due to
the nature of the transactions with the counterparty** — i.e. the legal
connection between the *underlying* of the derivative (or SFT) and the
*counterparty* makes default of the counterparty mechanically destroy
the value of the bank's protection. The regulatory wording is
deliberately tight: it is not enough that exposure and PD are merely
correlated; the correlation must arise from a *legal* relationship
between the issuer of the underlying and the counterparty.

The archetypal case is a **single-name CDS where the reference entity
is (or is legally connected to) the counterparty**: the bank has
bought protection on Entity X from Entity X itself (or from a parent /
subsidiary of X). The protection is worthless precisely when it is
needed — at default of the reference entity, which is the
counterparty's own default.

Other patterns that satisfy Art. 291(1)(b) include:

- A put option sold on the counterparty's own equity (equity falls →
  option is in-the-money → counterparty owes more, exactly when it is
  least able to pay).
- A total return swap on the counterparty's own debt.
- A repo with the counterparty's own equity as the collateral asset
  *and* the counterparty's affiliate as the trade counterparty (the
  Art. 291(5)(b) jump-to-default treatment in particular applies to
  the SFT case via Art. 273(2)(b)–(d)).

### Identification process (Art. 291(2)–(4))

Article 291 imposes an **operational** identification gate, not a
statistical test. The institution must:

- (Art. 291(2)) give due consideration to exposures that give rise to
  a significant degree of WWR;
- (Art. 291(4)) **maintain procedures to identify, monitor and control
  cases of Specific Wrong-Way risk for each legal entity, beginning at
  the inception of a transaction and continuing through the life of
  the transaction**; and
- (Art. 291(6)) provide regular reports to senior management and the
  appropriate committee of the management body on both specific and
  general WWR and the steps being taken to manage those risks.

The engine treats the outcome of this process as an input: each trade
carries a Boolean `is_specific_wwr` flag (`TRADE_SCHEMA.is_specific_wwr`,
default `False`). Setting that flag is the firm's responsibility — the
WWR gate consumes it but does not derive it. This mirrors the
legal-enforceability flag on `NETTING_SET_SCHEMA.is_legally_enforceable`
and keeps the legal-determination work where it belongs (with the
firm's risk-and-legal functions).

### Carve-out + LGD override (Art. 291(5)(a)/(c))

When `is_specific_wwr = True` on a trade, the SA-CCR engine performs a
**two-step** transformation:

1. **Netting-set partition (Art. 291(5)(a)).** The trade is removed
   from its original netting set and placed into its own single-trade
   synthetic netting set whose id is
   `<original_ns_id>__wwr__<trade_id>`. Non-WWR trades in the original
   netting set continue in a residual netting set keyed by the
   original id. This is the regulatory expression of "shall not be
   included in the same netting set… and shall each be treated as a
   separate netting set" — the WWR trade cannot benefit from netting
   against any of the bank's other positions with the counterparty,
   because at the counterparty's default the WWR trade jumps to its
   full loss-given-default while the other positions remain in their
   pre-default mark.

2. **LGD = 100% override (Art. 291(5)(c)).** The synthetic netting set
   carries `wwr_lgd_override = 1.0` on the
   `NETTING_SET_SCHEMA.wwr_lgd_override` field. Downstream IRB
   consumption (Art. 153 K-formula) must use this override in place of
   the bank's own LGD estimate for the exposure carved out. The
   override scalar is the regulatory constant
   `CCR_WWR_SPECIFIC_LGD_OVERRIDE = Decimal("1.0")` in
   [`src/rwa_calc/data/tables/sa_ccr_factors.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/data/tables/sa_ccr_factors.py).

The SA-CCR EAD calculation itself is **unchanged** by the carve-out —
the synthetic single-trade netting set is processed through the same
`adjusted_notional → supervisory_delta → maturity_factor →
hedging_set → addon → multiplier → EAD` chain as any other netting set,
with `α = 1.4` and the same supervisory factor for the asset class.
What changes is the *downstream IRB LGD lookup*: the synthetic NS
carries `wwr_lgd_override = 1.0` which the IRB Calculator substitutes
for the bank's own LGD estimate when computing K (Art. 153). The
specific-WWR treatment is therefore purely **a partitioning step in
SA-CCR and a downstream LGD override**, not a multiplier on the
SA-CCR EAD formula.

#### Diagnostic warning (CCR010)

The gate emits one `CalculationError` per *original* netting set that
contained at least one WWR trade:

| Field | Value |
|-------|-------|
| `code`                 | `CCR010` |
| `severity`             | `WARNING` |
| `category`             | `ErrorCategory.CCR_WWR_SPECIFIC` |
| `regulatory_reference` | `"CRR Art. 291(4)-(5)"` |
| `field_name`           | `"is_specific_wwr"` |

The warning is a regulatory trace, not a blocking error — SA-CCR EAD
calculation continues with the partitioned frame.

---

## (b) General WWR — Art. 291(1)(a), 291(3), 291(6)

### Definition (Art. 291(1)(a))

General WWR arises when **the likelihood of default by counterparties
is positively correlated with general market risk factors** — i.e. a
broad-market correlation rather than a transaction-level legal
connection. The canonical example is a long-dated USD interest-rate
swap with a US-dollar-funded counterparty: an upward shock to USD
rates simultaneously lifts the swap's positive market value (so the
counterparty owes more) and tightens the counterparty's funding
position (so its PD rises).

General WWR is **portfolio-level**, not trade-level: it is identified
by stress-testing risk factors that are adversely related to
counterparty creditworthiness (Art. 291(3)) and by monitoring by
product, region, industry or other categories.

### Demarcation — SA-CCR vs IMM (Art. 291(4) / Art. 284(9))

The numerical adjustment for general WWR lives in the IMM `α` re-estimation
that Art. 284(9) permits — institutions with IMM permission may use
their own estimates of `α` (subject to a floor of `1.2`), and the
estimation methodology must internalise general WWR. **SA-CCR does
not have an `α` re-estimation hook**: `α` is fixed at `1.4` per
Art. 274(2), with the only carve-out being the non-financial / pension
`α = 1.0` reduction on [ead-composition.md](ead-composition.md). The
SA-CCR engine therefore handles general WWR **diagnostically only** —
the affected netting set is flagged but no numerical adjustment is
applied.

This is the regulatory demarcation that distinguishes SA-CCR from IMM
in the WWR context:

| Approach | Specific WWR | General WWR |
|----------|--------------|-------------|
| SA-CCR (this engine)        | Carve-out + LGD = 100% override (Art. 291(5)(a)/(c)) | **Diagnostic only** — flag the netting set; α stays at 1.4 (Art. 274(2)) |
| IMM (out of scope for this engine) | Carve-out + LGD = 100% override (Art. 291(5)(a)/(c)) — same as SA-CCR | Re-estimated `α ≥ 1.2` per Art. 284(9), with WWR risk factors internalised in the EPE simulation |

The "diagnostic only" SA-CCR treatment is not an engine shortcut — it
is the regulation: Art. 291(4) imposes monitoring, control and
senior-management reporting duties (Art. 291(6)) but does not impose
any numerical EAD uplift for general WWR outside the IMM `α`
re-estimation hook. The engine's CCR011 warning fulfils the
identification leg of those duties; the monitoring and reporting legs
sit outside the calculator and belong to the firm's risk-management
function.

### Diagnostic warning (CCR011)

The gate emits one `CalculationError` per netting set with
`has_general_wwr_flag = True`:

| Field | Value |
|-------|-------|
| `code`                 | `CCR011` |
| `severity`             | `WARNING` |
| `category`             | `ErrorCategory.CCR_WWR_GENERAL` |
| `regulatory_reference` | `"CRR Art. 291(1)(a), 291(6)"` |
| `field_name`           | `"has_general_wwr_flag"` |

Like CCR010, the warning is a regulatory trace, not a blocking error.
The flag is read from `NETTING_SET_SCHEMA.has_general_wwr_flag`
(default `False`).

---

## Engine entry point

The WWR identification gate is implemented by a single function
operating on the aggregate `RawCCRBundle`:

```python
from rwa_calc.engine.ccr.wwr import apply_wwr_gate

def apply_wwr_gate(raw_ccr: RawCCRBundle) -> RawCCRBundle:
    """Partition netting sets to isolate specific-WWR trades; tag general WWR.

    Specific WWR (Art. 291(1)(b) / 291(5)(a)/(c)): every trade with
    ``is_specific_wwr=True`` is broken out into its own single-trade
    synthetic netting set ``<original>__wwr__<trade_id>`` carrying
    ``wwr_lgd_override = 1.0`` for downstream IRB LGD substitution.

    General WWR (Art. 291(1)(a) / 291(6)): netting sets with
    ``has_general_wwr_flag=True`` emit a CCR011 WARNING but are not
    partitioned — α stays at 1.4."""
```

Source: [`src/rwa_calc/engine/ccr/wwr.py::apply_wwr_gate`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/engine/ccr/wwr.py).

```python
--8<-- "src/rwa_calc/engine/ccr/wwr.py:86:165"
```

### Inputs (`RawCCRBundle`)

| Frame | Column | Schema | Notes |
|-------|--------|--------|-------|
| `trades`        | `is_specific_wwr`     | `Boolean` (default `False`) — `TRADE_SCHEMA.is_specific_wwr`         | Trade-level Art. 291(1)(b) flag set by the firm's risk-and-legal function. |
| `netting_sets`  | `has_general_wwr_flag`| `Boolean` (default `False`) — `NETTING_SET_SCHEMA.has_general_wwr_flag` | NS-level Art. 291(1)(a) flag; emits CCR011 only. |
| `netting_sets`  | `wwr_lgd_override`    | `Float64` (default `None`) — `NETTING_SET_SCHEMA.wwr_lgd_override`     | Null on input; set to `1.0` by the gate on synthetic carve-out rows. |

`ensure_columns` backfills the WWR columns with their schema defaults
when the loader has not yet populated them — the gate stays independent
of upstream column-presence quirks.

### Outputs (`RawCCRBundle`)

| Frame / list | Mutation |
|--------------|----------|
| `trades`        | Each WWR trade's `netting_set_id` is rewritten from `<original>` to `<original>__wwr__<trade_id>`. Non-WWR trades pass through unchanged. |
| `netting_sets`  | Each affected original NS is replaced by (1) a residual row keyed by the original `netting_set_id` with `wwr_lgd_override = null` and (2) one synthetic row per WWR trade keyed by the synthetic id with `wwr_lgd_override = 1.0`. Unaffected NSes pass through unchanged. |
| `errors`        | Appended with one CCR010 WARNING per original NS containing ≥1 WWR trade, plus one CCR011 WARNING per NS with `has_general_wwr_flag = True`. |

The partition is **idempotent** on a frame that has already been
gated: re-running `apply_wwr_gate` on its own output is a no-op because
the synthetic rows carry `is_specific_wwr = False` after the
carve-out (the trades are kept tagged at the trade level, but the
synthetic netting-set id is already in place so a second invocation
re-emits CCR010 against the synthetic id rather than re-partitioning).
The engine treats `apply_wwr_gate` as a one-pass stage.

---

## Pipeline ordering

`apply_wwr_gate` sits between the legal-enforceability gate and the
SA-CCR calculator chain. The legal-enforceability gate runs first
because Art. 291(5)(a) requires the WWR carve-out to operate on
**netting sets** — the carve-out cannot be applied before the
legally-enforceable netting-set boundaries are settled:

```
RawCCRBundle (loader output)
  │
  ├─ apply_legal_enforceability_gate    (Art. 272(4), 295–297)
  │     ↓ resolves single-trade synthetic NSes for unenforceable agreements
  │
  ├─ apply_wwr_gate                     (Art. 291(1)(a)/(b), 291(4)–(5))   ← this page
  │     ├─ Art. 291(5)(a) — partition WWR trades into single-trade NSes
  │     ├─ Art. 291(5)(c) — wwr_lgd_override = 1.0 on synthetic rows
  │     ├─ Art. 291(1)(a) — CCR011 WARNING per has_general_wwr_flag=True NS
  │     └─ Art. 291(1)(b) — CCR010 WARNING per original NS w/ ≥1 WWR trade
  │
  └─ ccr_rows_to_exposures              (Art. 274–278)
        ↓ standard SA-CCR chain (adjusted notional → δ → MF → HS → add-on
        ↓                        → multiplier → RC → PFE → EAD)
        ↓ — α stays at 1.4 throughout; α adjustment is an IMM-only hook
        ↓
        synthetic exposure rows → Classifier → CRM → SA/IRB Calculator
                                                       │
                                                       └─ IRB consumes
                                                          wwr_lgd_override
                                                          on the synthetic
                                                          NS rows → LGD = 100%
                                                          per Art. 153 K-formula
```

> **Engine status note.** The orchestrator at
> `engine/ccr/pipeline_adapter.py::ccr_rows_to_exposures` does **not
> yet wire `apply_wwr_gate` into the SA-CCR chain end-to-end** —
> `apply_wwr_gate` is implemented and pinned by
> `tests/unit/ccr/test_wwr.py` but the IRB-LGD-override consumer leg
> remains pending engine batches P8.35–P8.38 alongside the credit /
> equity / commodity add-on engines. Until those batches land, the
> only acceptance scenario that exercises `apply_wwr_gate` end-to-end
> is the unit test; the placeholder `CCR-A10` acceptance scenario in
> `docs/specifications/crr/ccr/index.md` is reserved for the
> end-to-end worked example.

---

## Worked example — single-name CDS where the reference entity is the counterparty

The simplest concrete trigger of Art. 291(1)(b): the bank has bought
single-name CDS protection on Entity X **from Entity X itself**. The
protection's payoff at default of X is mechanically destroyed by X's
default — Art. 291(5) carves the trade out, overrides LGD to 100%, and
emits the CCR010 warning. The same arithmetic generalises to puts sold
on the counterparty's own equity and TRS on the counterparty's own
debt; the regulatory mechanic is identical (Art. 291(1)(b) ⇒ 291(5)(a)
⇒ 291(5)(c)).

### Input data

```
counterparty:
  CP_X                       — Entity X (the CDS reference entity)

netting set:
  netting_set_id           = "NS_X_01"
  counterparty_reference   = "CP_X"
  is_legally_enforceable   = True
  is_margined              = False
  has_general_wwr_flag     = False

trades (single-name CDS):
  trade_id                 = "T_CDS_X_01"
  netting_set_id           = "NS_X_01"
  asset_class              = "credit"
  reference_entity         = "CP_X"           ← legal connection to counterparty
  notional                 = 10,000,000 GBP
  protection_position      = "buyer"          ← bank bought protection
  is_specific_wwr          = True             ← firm-determined per Art. 291(4)

  trade_id                 = "T_IRS_X_01"
  netting_set_id           = "NS_X_01"
  asset_class              = "interest_rate"
  notional                 = 50,000,000 GBP
  is_specific_wwr          = False            ← normal IR swap, no Art. 291(1)(b) connection
```

### After `apply_wwr_gate`

```
trades:
  T_CDS_X_01    → netting_set_id = "NS_X_01__wwr__T_CDS_X_01"   (synthetic, single-trade)
  T_IRS_X_01    → netting_set_id = "NS_X_01"                    (residual, unchanged)

netting_sets:
  NS_X_01                        — wwr_lgd_override = null   (residual; carries IRS only)
  NS_X_01__wwr__T_CDS_X_01       — wwr_lgd_override = 1.0    (synthetic; carries CDS only)
                                   has_general_wwr_flag = False (inherited)
                                   is_legally_enforceable = True (inherited)
                                   counterparty_reference = "CP_X" (inherited)

errors:
  1 × CCR010 (WARNING, CCR_WWR_SPECIFIC, "CP_X",
              regulatory_reference = "CRR Art. 291(4)-(5)",
              message references NS_X_01)
  0 × CCR011 (has_general_wwr_flag = False on the original NS)
```

### Downstream consequences

- **SA-CCR EAD chain.** Both netting sets — the residual `NS_X_01`
  with the IRS and the synthetic `NS_X_01__wwr__T_CDS_X_01` with the
  CDS — run through `ccr_rows_to_exposures` with `α = 1.4`. The
  partition prevents the IRS from netting against the CDS even though
  both were originally legally enforceable under the same ISDA — the
  IRS and CDS were under the same Master, but Art. 291(5)(a) overrides
  the netting recognition for the WWR trade.
- **IRB LGD substitution.** The downstream IRB Calculator reads
  `wwr_lgd_override` on the synthetic NS row and substitutes `LGD = 1.0`
  for the bank's own LGD estimate (Art. 153 K-formula) — the
  Art. 291(5)(c) LGD = 100% override. The residual `NS_X_01` row
  carries `wwr_lgd_override = null` and the bank's own LGD estimate
  applies as normal.
- **SA branch (Art. 291(5)(d)).** Where the synthetic NS is routed to
  the SA calculator (rather than IRB), the applicable risk weight is
  **that of an unsecured transaction** (no collateral or guarantee
  recognition on the WWR carve-out). The SA branch implementation
  remains pending engine batches P8.35–P8.38.
- **Senior-management reporting.** The CCR010 warning surfaces in the
  pipeline error frame for the Art. 291(6) reporting leg. The bank's
  risk-management function is expected to consume the error frame and
  fold the CCR010 / CCR011 records into the WWR section of the
  Art. 291(6) management report.

### Asset-class scope of worked examples

| Asset class | Worked example status |
|-------------|------------------------|
| Interest rate | The IR swap leg of the example above demonstrates the residual-NS pass-through path. |
| FX            | Analogous to IR — an FX forward with the counterparty's home currency as the bought leg satisfies Art. 291(1)(b) when the counterparty is a sovereign and the trade is its sovereign currency. The carve-out arithmetic is identical to the CDS case above; only the asset-class add-on engine changes. |
| Credit        | Single-name CDS where the reference entity is (or is legally connected to) the counterparty — the canonical Art. 291(1)(b) case. The CDS leg of the worked example above is the structural shape; full numerical worked examples land with engine batches **P8.35–P8.38**, alongside the credit add-on engine. |
| Equity        | Put option sold on the counterparty's own equity — engine batches P8.35–P8.38. |
| Commodity     | A long-dated forward in the counterparty's primary commodity output (e.g. an oil-producing counterparty selling oil forwards) — engine batches P8.35–P8.38. |

The carve-out and LGD override mechanic is **asset-class-independent** —
it operates on the `is_specific_wwr` trade flag and the netting-set
partition only. The asset-class engine deferrals affect only the
worked-example arithmetic on the synthetic NS's EAD, not the partition
or the LGD override.

---

## Status

| Element | Status |
|---------|--------|
| Specific-WWR carve-out (Art. 291(5)(a))                              | **Live** — `apply_wwr_gate` implemented in `src/rwa_calc/engine/ccr/wwr.py`. |
| LGD = 100% override constant (Art. 291(5)(c))                        | **Live** — `CCR_WWR_SPECIFIC_LGD_OVERRIDE = Decimal("1.0")` in `src/rwa_calc/data/tables/sa_ccr_factors.py`. |
| CCR010 / CCR011 diagnostic warnings                                  | **Live** — pinned by `tests/unit/ccr/test_wwr.py`. |
| General-WWR diagnostic flag (Art. 291(1)(a), 291(6))                 | **Live** — `has_general_wwr_flag` consumed by `apply_wwr_gate`. |
| Wiring `apply_wwr_gate` into `pipeline_adapter.ccr_rows_to_exposures` end-to-end | **Pending** — `apply_wwr_gate` is currently exercised only via its unit test; the SA-CCR orchestrator does not yet call the gate before the calculator chain. |
| IRB downstream consumer of `wwr_lgd_override` (Art. 153 LGD substitution) | **Pending engine batches P8.35–P8.38** alongside the credit / equity / commodity asset-class add-ons. |
| Credit-derivative specific-WWR worked example (full numerics)        | **Pending engine batches P8.35–P8.38** — placeholder-flagged on the CCR-A10 acceptance scenario in [index.md](index.md). |
| SA branch — Art. 291(5)(d) "risk weight of an unsecured transaction" | **Pending engine batches P8.35–P8.38**. |

---

## References

- **PRA Rulebook — Counterparty Credit Risk (CRR) Part, Article 291** —
  wrong-way risk definitions, identification process, specific-WWR
  carve-out and LGD = 100% override.
- **PRA Rulebook — Counterparty Credit Risk (CRR) Part, Article 272(4)** —
  netting set definition; supplies the netting-set boundary on which
  the WWR carve-out operates.
- **PRA Rulebook — Counterparty Credit Risk (CRR) Part, Article 273(2)** —
  scope of "transactions" referenced by Art. 291(5) (OTC derivatives,
  long-settlement transactions, SFTs).
- **PRA Rulebook — Counterparty Credit Risk (CRR) Part, Article 274(2)** —
  the SA-CCR EAD formula consuming the carved-out netting sets; α
  stays at 1.4.
- **PRA Rulebook — Counterparty Credit Risk (CRR) Part, Article 284(9)** —
  IMM hook for α re-estimation that internalises general WWR
  (out of scope for SA-CCR).
- **PRA PS1/26** — does not amend Article 291; the WWR treatment
  carries forward unchanged into the Basel 3.1 regime from
  1 January 2027.
- **BCBS CRE53.2–53.8** — Basel-level methodology for specific and
  general WWR identification and treatment.
- [`src/rwa_calc/engine/ccr/wwr.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/engine/ccr/wwr.py) —
  engine implementation of `apply_wwr_gate`, including the synthetic
  netting-set id format `<original>__wwr__<trade_id>` and the CCR010 /
  CCR011 warning emission.
- [`src/rwa_calc/data/tables/sa_ccr_factors.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/data/tables/sa_ccr_factors.py) —
  `CCR_WWR_SPECIFIC_LGD_OVERRIDE = Decimal("1.0")` regulatory scalar
  (Art. 291(5)(c)).
- [`src/rwa_calc/data/schemas.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/data/schemas.py) —
  `TRADE_SCHEMA.is_specific_wwr`, `NETTING_SET_SCHEMA.has_general_wwr_flag`,
  `NETTING_SET_SCHEMA.wwr_lgd_override`.
- `tests/unit/ccr/test_wwr.py` — pinned partition behaviour and
  CCR010 / CCR011 warning emission for the P8.27 fixture.
- [`tests/fixtures/ccr/wwr_builder.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/tests/fixtures/ccr/wwr_builder.py) —
  fixture builder for the worked example structure.

## Cross-references

- [CCR index](index.md) — full SA-CCR specification index, the
  per-stage status table, and the CCR-A10 placeholder acceptance
  scenario for end-to-end specific-WWR.
- [RC calculation](rc-calculation.md) — replacement cost composition;
  the synthetic single-trade netting set runs through the same
  Art. 275(1) `RC = max(V − C, 0)` formula as any other unmargined
  netting set, but with the LGD = 100% override applied at the
  downstream IRB lookup.
- [EAD composition](ead-composition.md) — `α · (RC + PFE)` consumer of
  the carved-out netting sets; α stays at 1.4, the LGD override is a
  downstream IRB concern.
- [SA risk weights](../sa-risk-weights.md) — downstream lookup the
  carved-out netting set flows through when routed to the SA branch
  (Art. 291(5)(d) "risk weight of an unsecured transaction"; pending
  engine batches P8.35–P8.38).
