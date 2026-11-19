# SA-CCR — Central counterparty (CCP) trade exposures (Art. 306–307)

The Counterparty Credit Risk (CRR) Part Section 9 sits **outside** the
SA-CCR EAD chain (Art. 274 et seq.) — it does not change how exposure
value is computed, it changes what risk weight that exposure attracts.
Once SA-CCR has produced a netting-set EAD (`α · (RC + PFE)`, Art.
274(2)), the QCCP route bypasses the standard SA / IRB risk-weight
ladder and applies one of two regulatorily-pinned weights:

- **2%** for a clearing member's own (proprietary) trade exposures to a
  qualifying CCP, and for trades a clearing member intermediates on
  behalf of a client when the Art. 305(2) conditions are met (the
  client itself also enjoys the 2% RW on its leg) — PRA PS1/26 Art.
  306(1)(a)–(b);
- **4%** for trades a clearing member intermediates on behalf of a
  client when the Art. 305(2) conditions are *not* met — PRA PS1/26
  Art. 306(1)(c).

Non-qualifying CCP (non-QCCP) trade exposures keep the standard SA-CCR
EAD and take the ordinary SA **corporate** risk weight (Art. 122 in
both regimes) per Art. 107(2)(b) and Art. 306(1)(b). Exposures to a
QCCP that are neither trade exposures nor default-fund contributions —
a term loan, a deposit, held CCP debt — are **not** pinned: Art.
107(2)(a) treats them as exposures to an institution. See
[Which rows the pin covers](#which-rows-the-pin-covers-art-1072).

This page documents:

- the Art. 306 trade-exposure risk-weight ladder (2% / 4% / non-QCCP
  fallback) and the Art. 305(2)(a)–(c) condition list for the
  client-clearing 2% leg;
- the Art. 307–310 default-fund-contribution stack (Art. 308(2)
  QCCP pre-funded formula and floor, Art. 309(1) non-QCCP, Art. 310
  QCCP unfunded);
- the engine entry point (`apply_ccp_risk_weight`) and its position
  immediately downstream of the SA-CCR EAD producer;
- the non-QCCP fallback to standard SA-CCR with SA risk-weighting;
- three worked examples — direct-cleared QCCP, client-cleared QCCP
  with and without Art. 305(2) compliance, and a non-QCCP fallback.

## Regulatory citation

**Primary source:** PRA Rulebook — Counterparty Credit Risk (CRR) Part,
Section 9 "Own funds requirements for exposures to a central
counterparty" (Articles 301–311). PS1/26 Appendix 1 (effective 1
January 2027) restates Section 9 with only Art. 306(4) /
Art. 308(3) / Art. 309(2) explicitly re-stated — paragraphs 1–3 of
Art. 306 (and Articles 301–305, 307) carry forward from the
pre-revocation CRR text via the standard "[Note: This rule
corresponds to Article X of CRR as it applied immediately before
revocation by the Treasury]" provenance footer.

| Sub-article            | Coverage                                                                            | BCBS cross-reference |
|------------------------|-------------------------------------------------------------------------------------|----------------------|
| Art. 272 Def (88)      | Definition of *qualifying central counterparty* (QCCP)                              | CRE50.6              |
| Art. 305(2)(a)–(c)     | Conditions a client must satisfy to attract the 2% RW (rather than 4%) on its client-cleared leg: segregation, portability, no transmission of losses | CRE54.18 |
| Art. 306(1)(a)         | 2% RW on a clearing member's own trade exposures to a QCCP                          | CRE54.14             |
| Art. 306(1)(b)         | 2% RW on a clearing member's trade exposure to a client when intermediating on behalf of that client (Art. 305(2) satisfied) | CRE54.14 |
| Art. 306(1)(c)         | 4% RW on a clearing member's trade exposure to a client when Art. 305(2) is *not* satisfied | CRE54.15 |
| Art. 306(4)            | `RWA = Σ EAD_trade × RW` — PS1/26 verbatim restated to point at the Required Level of Own Funds (CRR) Part Art. 92(3) | CRE54.16 |
| Art. 307               | Own funds requirements for **default-fund contributions** to a CCP — implemented (see below) | CRE54.21 |
| Art. 308(2)            | QCCP pre-funded: `K_i = max{K_CCP · DF_i / (DF_CCP + DF_CM), 8% · 2% · DF_i}` | CRE54.31–32 |
| Art. 308(3)            | RWA = own-funds requirement × 12.5 for **pre-funded** default-fund contributions to a QCCP    | CRE54.22 |
| Art. 309(1)            | Non-QCCP: `K = DF + UC` — the contribution itself is the own-funds requirement | CRE54.40 |
| Art. 309(2)            | RWA = own-funds requirement × 12.5 for default-fund contributions / unfunded contributions to a non-QCCP | CRE54.27 |
| Art. 310               | 0% risk weight on **unfunded** contributions to the default fund of a QCCP | CRE54.38 |
| Art. 107(2)(a)         | Other (non-trade) exposures to a **QCCP** treated as exposures to an institution | CRE20.14 |
| Art. 107(2)(b)         | Other exposures to a **non-QCCP** treated as exposures to a corporate; Art. 306(1)(b) applies the same weight to non-QCCP trade exposures | CRE54.11 |

### Verbatim text — PRA PS1/26 Art. 306(4)

> "An institution shall calculate the risk-weighted exposure amounts
> for its trade exposures with CCPs for the purposes of Article 92(3)
> [of] Required Level of Own Funds (CRR) Part Article 92 as the sum of
> the exposure values of its trade exposures with CCPs, calculated in
> accordance with paragraphs 2 and 3, multiplied by the risk weight
> determined in accordance with paragraph 1."
>
> — PS1/26 Appendix 1, Counterparty Credit Risk (CRR) Part, Article
> 306(4), p. 457 (source PDF: `docs/assets/ps126app1.pdf`).

### Carried-forward paragraphs (Art. 306(1)–(3) and Art. 305(2))

PS1/26 elides paragraphs 1–3 of Art. 306 (and Article 305 in its
entirety) with the standard "…" continuation marker and the
provenance footer ("[Note: This rule corresponds to Article 306 of
CRR as it applied immediately before revocation by the Treasury]").
The substantive content carries forward from the pre-revocation CRR
text:

- **Art. 306(1)(a)** — 2% on a clearing member's own trade
  exposures to a QCCP (the proprietary leg).
- **Art. 306(1)(b)** — 2% on the clearing member's trade exposure
  to a client where the clearing member acts as a financial
  intermediary between the client and the QCCP, **provided the
  conditions in Art. 305(2) are met**.
- **Art. 306(1)(c)** — 4% on the clearing member's trade exposure
  to a client where the clearing member acts as a financial
  intermediary between the client and the QCCP and the conditions
  in Art. 305(2) are **not** met.

### Art. 305(2) — client-clearing condition list

A client of a clearing member receives the 2% RW (rather than 4%) on
its client-cleared QCCP trade legs only when **all** of the following
conditions are satisfied:

| Condition           | Substance                                                                                                                                                |
|---------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------|
| Art. 305(2)(a)      | **Default portability:** if the clearing member defaults or becomes insolvent, the trades and any associated collateral are transferable to another clearing member within the margin period of risk — the client does not lose its hedge. |
| Art. 305(2)(b)      | **Segregation:** the client's positions and collateral with the CCP are identified and segregated, both at the clearing member's books and at the CCP, from those of the clearing member and from those of other clients. |
| Art. 305(2)(c)      | **Operational, legal and bankruptcy-remote arrangements:** the arrangements between the client, the clearing member, the CCP and any insolvency administrator are operationally and legally robust, so that the segregation and portability protections in (a) and (b) actually take effect under all foreseeable scenarios (a legal opinion is normally required). |

Failing **any** one of the three conditions demotes the client-cleared
leg from 2% (Art. 306(1)(b)) to 4% (Art. 306(1)(c)). The engine
expresses this as a single Boolean (`is_client_cleared`); the
firm-level legal review that produces that Boolean must verify all of
(a)–(c) before flagging the trade with the 2% leg. See the worked
example below for a comparison of the two outcomes on the same
notional.

---

## Which rows the pin covers (Art. 107(2))

CRR Art. 107(2) = PS1/26 Art. 107(2):

> "For trade exposures and for default fund contributions to a central
> counterparty, institutions shall apply the treatment set out in
> Section 9 ... For all other types of exposures to a central
> counterparty, institutions shall treat those exposures as follows:
> (a) as exposures to an institution for other types of exposures to a
> qualifying CCP; (b) as exposures to a corporate for other types of
> exposures to a non-qualifying CCP."

The engine applies the 2% / 4% pin to a row only when **both** hold
(one shared predicate, `engine/sa/ccp_exposures.py::qccp_trade_exposure_expr`,
used by the SA risk-weight chain and by the Art. 121(6) sovereign-floor
carve-out so the two cannot drift apart):

- the row is a **trade exposure** — an SA-CCR netting-set row
  (`risk_type = "CCR_DERIVATIVE"`) or an FCCM SFT row (`"CCR_SFT"`);
- the counterparty is a **qualifying** CCP — `entity_type = "ccp"` and
  `is_qccp` is not `False` (an absent flag is read as qualifying).

| Row | Class | Risk weight |
|---|---|---|
| Trade exposure to a QCCP | institution (base map) | 2% / 4% pin (Art. 306(1)) |
| Loan, deposit or other non-trade row to a QCCP | institution | Art. 120 / 121 institution ladder (Art. 107(2)(a)) |
| Any row to a non-QCCP (`is_qccp = False`) | **corporate** | Art. 122 corporate ladder (Art. 107(2)(b), 306(1)(b)) |
| Default-fund contribution | own-funds line | 12.5 × K (Art. 308(3) / 309(2)) |

Before the 2026-11 review (item CC-11) the pin keyed on the
counterparty alone, so a term loan to a QCCP took 2%, and a non-QCCP
was classified as an institution on a citation of Art. 107(2)(a) — the
qualifying-CCP limb.

!!! note "Initial margin posted to a QCCP"
    Posted initial margin is a trade exposure (Art. 306(1)), but the
    input contract has no posted-collateral row and no flag that marks
    a loan-table row as one. A loan row booked against a QCCP to carry
    posted margin is therefore weighted as an institution exposure —
    a conservative treatment, never a relief.

## Engine entry point

The trade-exposure RW assignment is implemented as a one-shot annotation
step that runs **after** the SA-CCR EAD producer and **before** the
downstream SA / IRB risk-weight lookup:

```python
--8<-- "src/rwa_calc/engine/ccr/ccp.py:46:111"
```

Source: [`src/rwa_calc/engine/ccr/ccp.py::apply_ccp_risk_weight`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/engine/ccr/ccp.py).

### Inputs (netting-set / counterparty / trade grain)

| Column                | Frame            | Dtype     | Source                          | Article                  |
|-----------------------|------------------|-----------|---------------------------------|--------------------------|
| `ead_ccr`             | `exposures`      | `Float64` | `compute_ead` (Art. 274(2))     | Art. 274(2)              |
| `is_qccp`             | `counterparties` | `Boolean` | CCR counterparty schema         | Art. 272 Def (88)        |
| `is_client_cleared`   | `trades`         | `Boolean` | CCR trade schema                | Art. 305(2) outcome flag |

### Outputs (exposure grain)

| Column         | Dtype     | Formula                                                                                          | Article             |
|----------------|-----------|--------------------------------------------------------------------------------------------------|---------------------|
| `risk_weight`  | `Float64` | `0.02` if `is_qccp & ¬is_client_cleared`; `0.04` if `is_qccp & is_client_cleared`; `NULL` otherwise | Art. 306(1)(a)–(c)  |
| `ead_ccr`      | `Float64` | unchanged (load-bearing invariant — RW assignment never mutates EAD)                             | Art. 274(2)         |

### Regulatory scalars — rulebook common pack

The two pinned QCCP risk weights are cited pack params
(`qccp_proprietary_rw`, `qccp_client_cleared_rw`) in
`src/rwa_calc/rulebook/packs/common.py`, resolved in
`engine/ccr/ccp.py` via `_QCCP_PACK.scalar_param(...)` — the engine
never literalises them:

```python
qccp_proprietary_rw    = 0.02  # Art. 306(1)(a) / CRE54.14
qccp_client_cleared_rw = 0.04  # Art. 306(1)(c) / CRE54.15
```

The 2% client-cleared leg under Art. 306(1)(b) re-uses the
`qccp_proprietary_rw = 0.02` param — Art. 305(2) compliance does not
discount the regulatory weight, it just routes the trade to the same
weight as the proprietary leg.

### Non-QCCP signalling — why NULL, not 0.20

`apply_ccp_risk_weight` emits `risk_weight = NULL` for the non-QCCP
branch rather than literalising the SA institution weight. This is a
deliberate routing signal: the downstream Classifier (P8.30) recognises
a `NULL` `risk_weight` on a `risk_type = "CCR_DERIVATIVE"` row as
"no regulatory pin — apply standard SA / IRB lookup" and re-routes the
row through the ordinary SA institution ladder ([Art. 121 — see
`../sa-risk-weights.md`](../sa-risk-weights.md)) or the IRB chain when
the firm is IRB-permissioned for the counterparty.

### Pipeline ordering — where the CCP gate sits

```
RawCCRBundle
  → apply_legal_enforceability_gate     (Art. 272(4); see legal-enforceability.md)
  → ccr_rows_to_exposures               (chains the SA-CCR pipeline)
      ├─ compute_adjusted_notional      (Art. 279b)
      ├─ compute_supervisory_delta      (Art. 279a)
      ├─ compute_maturity_factor        (Art. 279c)
      ├─ assign_hedging_set             (Art. 277, 277a)
      ├─ compute_addon_per_asset_class  (Art. 277a(2)–(3))
      ├─ compute_pfe                    (Art. 278)
      └─ compute_ead                    (Art. 274(2))     → ead_ccr
  → synthetic exposure row (RAW_EXPOSURE_SCHEMA shape, drawn_amount = ead_ccr)
  → apply_ccp_risk_weight               (Art. 306(1)(a)–(c))   ← this page's entry point
      ├─ is_qccp=True,  is_client_cleared=False → risk_weight = 0.02
      ├─ is_qccp=True,  is_client_cleared=True  → risk_weight = 0.04
      └─ is_qccp=False                          → risk_weight = NULL  → SA fallback
  → Classifier                          (resolves counterparty class on the NULL branch)
  → SA / IRB Calculators                (risk-weight lookup; QCCP rows skip the lookup)
  → OutputAggregator                    (firm-level totals + output floor)
```

The QCCP path **skips** the standard SA / IRB risk-weight lookup — the
2% or 4% is the final, terminal regulatory weight. The output floor
(Basel 3.1 Art. 92(5)) still applies: both the U-TREA and S-TREA legs
treat the QCCP row identically because there is no IRB risk-weight
to differ from the SA pin (the QCCP risk weight is the same on both
legs, by construction).

### Where the pin is applied in the pipeline

The pin that reaches `rwa_final` is applied in the SA risk-weight chain
(`engine/sa/risk_weights.py`, both regime ladders), on the predicate in
`engine/sa/ccp_exposures.py` described in
[Which rows the pin covers](#which-rows-the-pin-covers-art-1072). The
CCR stage tags each SA-CCR netting-set row `risk_type =
"CCR_DERIVATIVE"`; the classifier carries the counterparty's `is_qccp`
and `is_ccp_client_cleared` onto it (`cp_is_qccp`,
`cp_is_ccp_client_cleared`) and routes every `entity_type = "ccp"` row
to SA.

`engine/ccr/ccp.py::apply_ccp_risk_weight`, the standalone annotator
shown above, is unit-tested but is not called from the pipeline; the
diagram above describes its contract, not the production path.

---

## Art. 307 — default-fund contributions

Default-fund contributions are a **separate** capital charge from the
trade-exposure RW documented above. A clearing member that maintains a
pre-funded contribution to a QCCP's default fund (the mutualised loss-
absorption pool that the CCP draws on after exhausting the defaulting
member's own margin and the CCP's "skin in the game") incurs an own-
funds requirement under Art. 307 (computation), scaled into RWA at
12.5× under Art. 308(3) (RWA conversion). Non-QCCP default-fund
contributions are weighted under Art. 309.

### PS1/26 Art. 308(3) — verbatim

> "An institution shall calculate the risk-weighted exposure amounts
> for exposures arising from that institution's pre-funded
> contribution to the default fund of a QCCP for the purposes of
> Article 92(3) [of] Required Level of Own Funds (CRR) Part Article 92
> as the own funds requirement, calculated in accordance with
> paragraph 2 of this Article, multiplied by 12.5."
>
> — PS1/26 Appendix 1, Counterparty Credit Risk (CRR) Part, Article
> 308(3), p. 457 (source PDF: `docs/assets/ps126app1.pdf`).

### PS1/26 Art. 309(2) — verbatim (non-QCCP default fund)

> "An institution shall calculate the risk-weighted exposure amounts
> for exposures arising from that institution's contribution to the
> default fund of a non-qualifying CCP for the purposes of Article
> 92(3) [of] Required Level of Own Funds (CRR) Part Article 92 as the
> own funds requirement, calculated in accordance with paragraph 1 of
> this Article, multiplied by 12.5."
>
> — PS1/26 Appendix 1, Counterparty Credit Risk (CRR) Part, Article
> 309(2), p. 457 (source PDF: `docs/assets/ps126app1.pdf`).

### Engine implementation — `engine/ccr/default_fund.py`

The default-fund-contribution stack is not on the SA-CCR EAD chain. It
reads `RawCCRBundle.default_fund_contributions` (one row per
contribution) and produces an own-funds requirement `k_cm` per row, one
branch per limb:

| Branch (`regulatory_band`) | Condition | Own funds `K` | Article |
|---|---|---|---|
| `dfc_qccp_prefunded` | `is_qccp_ccp`, not unfunded | `max(K_CCP · DF_i / (DF_CCP + DF_CM), 8% · 2% · DF_i)` | Art. 308(2) |
| `dfc_qccp_unfunded` | `is_qccp_ccp`, unfunded | `0` | Art. 310 |
| `dfc_non_qccp_prefunded` | not QCCP, pre-funded | `DF_i` | Art. 309(1) |
| `dfc_non_qccp_unfunded` | not QCCP, unfunded | `UC_i` | Art. 309(1) |

RWEA = `K × 12.5` (Art. 308(3) / 309(2)). The ccr stage mints each
contribution as a synthetic `dfc__<contribution_id>` row with
`drawn_amount = k_cm` and `risk_type = "CCR_DEFAULT_FUND"`; the SA chain
pins its risk weight to 12.5. The row is an **own-funds line**, not a
credit exposure: it is always SA, takes no collateral, guarantee,
provision or supporting factor, and keeps the 12.5 pin even when the
CCP is in default (see [Failed trades — own-funds lines](failed-trades.md#own-funds-lines-are-not-credit-exposures)).

Inputs (`DF_CONTRIBUTION_SCHEMA`):

| Column | Meaning |
|---|---|
| `df_i_contribution_amount` | The row's own contribution: `DF_i` (pre-funded) or `UC` (unfunded) |
| `is_qccp_ccp` | Art. 272 Def (88) — selects Art. 308 / 310 (True) or Art. 309 (False) |
| `is_unfunded_commitment` | Unfunded contribution flag (Art. 309 UC / Art. 310) |
| `k_ccp_published` | `K_CCP`, as communicated by the CCP |
| `df_cm_total_contributions` | `DF_CM`, the clearing members' pre-funded contributions |
| `df_ccp_prefunded` | `DF_CCP`, the CCP's own pre-funded resources. Optional: absent is read as 0, which can only raise `K_i` |

The two floor scalars are cited pack entries
(`ccp_dfc_floor_capital_ratio` 8%, `ccp_dfc_floor_risk_weight` 2%, both
Art. 308(2)); the Art. 310 weight is `ccp_dfc_qccp_unfunded_rw`. Worked
values (pinned by `tests/acceptance/ccr/test_ccp_cva_review_cluster.py`):

- QCCP, `K_CCP` 20m, `DF_i` 10m, `DF_CCP` 100m, `DF_CM` 500m:
  `K = max(20m · 10m / 600m, 16,000) = 333,333.33`, RWEA 4,166,666.67.
- QCCP floor, `K_CCP` 0.5m: `K = max(8,333.33, 16,000) = 16,000`, RWEA 200,000.
- Non-QCCP pre-funded `DF_i` 10m: `K = 10m`, RWEA 125,000,000.
- QCCP unfunded: `K = 0`, RWEA 0.
- QCCP pre-funded with `K_CCP` or `DF_CM` missing: only the floor arm of
  the Art. 308(2) max can be evaluated, so `K = 8% · 2% · DF_i` (16,000 on
  `DF_i` 10m, RWEA 200,000) is charged as a **lower bound**, and the input
  gate raises **CCR032** (ERROR) naming the `dfc__` row, because the true
  requirement can be higher. Before this the null reached the SA chain as a
  null drawn amount and the row published RWEA 0 with no error.

Not implemented: the `K_CCP` hypothetical-capital simulation itself
(the firm supplies `k_ccp_published`) and the Art. 303(2) cap, which can
only lower the charge.

---

## Non-QCCP fallback to standard SA-CCR

When the counterparty's `is_qccp` flag is `False`, the SA-CCR EAD
(`α · (RC + PFE)`, Art. 274(2)) is preserved unchanged and the
classifier gives the row the **corporate** exposure class (Art.
107(2)(b); CCR (CRR) Part Art. 306(1)(b) applies "the risk weight used
for the Standardised Approach to credit risk as set out in Article
107(2)(b)" to non-QCCP trade exposures). The row is then weighted on
the Art. 122 corporate ladder — the generated `corporate_risk_weights`
(CRR) and `b31_corporate_risk_weights` (Basel 3.1) tables in
[Regulatory tables](../../../data-model/regulatory-tables.md). A rating
carried only as `institution_cqs` on the CCP counterparty is lifted into
`cqs` for the corporate lookup (`engine/sa/cqs_lift.py`).

The non-QCCP fallback **does not amend** the SA-CCR EAD — `α = 1.4`
still applies, the multiplier and add-on aggregation are unchanged.
What changes is only the downstream risk-weight lookup: instead of the
2% / 4% Art. 306 pin, the row is weighted as an ordinary corporate
exposure. Before the 2026-11 review (CC-11) it was weighted as an
institution, which differs from the corporate weight in both
directions (CRR CQS 3: 50% institution vs 100% corporate). Under Basel 3.1, the same row also enters both legs of the
output floor (`U-TREA` and `S-TREA`) per [`../basel31/output-floor.md`](../../basel31/output-floor.md#floor-calculation).

---

## Worked numeric examples

All three examples re-use a CCR-A1-style unmargined IR-swap netting
set that produces `ead_ccr = 5,480,017.52` (see
[`pfe-multiplier.md`](pfe-multiplier.md#cross-check-against-ccr-a1) for
the EAD derivation). The trade-exposure path then diverges based on
`is_qccp` and `is_client_cleared`.

### Example 1 — Direct-cleared QCCP trade (proprietary, 2%)

A clearing member trades for its own book against a UK-recognised QCCP
(e.g. LCH SwapClear). `is_qccp = True`, `is_client_cleared = False`.

```
Inputs:
  ead_ccr           = 5,480,017.52              (from SA-CCR per Art. 274(2))
  is_qccp           = True                       (Art. 272 Def (88))
  is_client_cleared = False                      (proprietary leg)

apply_ccp_risk_weight branch:
  is_qccp & ¬is_client_cleared → Art. 306(1)(a)
  risk_weight       = QCCP_PROPRIETARY_RW = 0.02

RWA (Art. 306(4)):
  RWA = ead_ccr × risk_weight = 5,480,017.52 × 0.02 = 109,600.35
```

### Example 2 — Client-cleared QCCP trade, Art. 305(2) met (2%)

The same clearing member intermediates the same trade on behalf of a
buy-side client. The client's collateral is segregated at the CCP,
positions are portable to a back-up clearing member on default, and a
clean Art. 305(2)(c) legal opinion is on file. `is_qccp = True`,
`is_client_cleared = True`, and the Art. 305(2) conditions are
**satisfied**.

```
Inputs:
  ead_ccr           = 5,480,017.52
  is_qccp           = True
  is_client_cleared = True
  Art. 305(2)(a)–(c) condition list: all three satisfied
                                     (segregation, portability, legal robustness)

Branch outcome (Art. 306(1)(b)):
  risk_weight       = QCCP_PROPRIETARY_RW = 0.02   (Art. 305(2) compliance routes back to 2%)

RWA:
  RWA = 5,480,017.52 × 0.02 = 109,600.35
```

!!! note "Engine flag granularity"
    The engine's `is_client_cleared` flag is a single Boolean — it
    does not separately encode "client-cleared AND Art. 305(2)
    satisfied". The firm-level legal review must collapse the
    three-part Art. 305(2)(a)–(c) test into the Boolean *before*
    the row hits SA-CCR. When the legal review says "yes — all
    three conditions hold", the engine routes the trade through
    `apply_ccp_risk_weight` as if it were the proprietary leg
    (re-using the `QCCP_PROPRIETARY_RW = 0.02` scalar). This is a
    deliberate simplification — the engine does not separately
    materialise the (a)/(b)/(c) booleans. The follow-up batch P8.30
    that wires `apply_ccp_risk_weight` into the orchestrator may
    revisit this if a firm requires per-condition audit trail.

### Example 3 — Client-cleared QCCP trade, Art. 305(2) NOT met (4%)

The same trade as Example 2, but the client's collateral arrangement
fails Art. 305(2)(b): the CCP segregates positions at the omnibus
client account level only, with no individual client identification.
Portability under Art. 305(2)(a) is therefore not legally robust
either. `is_qccp = True`, `is_client_cleared = True`, but
Art. 305(2) is **not** satisfied.

```
Inputs:
  ead_ccr           = 5,480,017.52
  is_qccp           = True
  is_client_cleared = True
  Art. 305(2) condition list: at least one of (a)–(c) NOT satisfied

Branch outcome (Art. 306(1)(c)):
  risk_weight       = QCCP_CLIENT_CLEARED_RW = 0.04   (the 305(2) penalty)

RWA:
  RWA = 5,480,017.52 × 0.04 = 219,200.70
```

The 2% → 4% step is exactly a **doubling** of CCP-leg RWA — the
regulator's quantitative signal that the Art. 305(2) protections
materially reduce client-leg counterparty risk.

### Example 4 — Non-QCCP fallback (standard SA corporate RW)

The same trade, but the CCP is not on the PRA / FSMA-recognised QCCP
list (e.g. a non-EMIR-equivalent overseas CCP). `is_qccp = False`,
`is_client_cleared` is irrelevant on this branch.

```
Inputs:
  ead_ccr           = 5,480,017.52
  is_qccp           = False                       (Art. 272 Def (88) not satisfied)
  is_client_cleared = (any)                       (ignored on the non-QCCP branch)

Classifier:
  ¬is_qccp → Art. 107(2)(b) / Art. 306(1)(b)
  exposure_class    = "corporate"
  CQS               = 2 (illustrative)
  risk_weight       = 0.50                        (Art. 122 Table 6, CQS 2 — both regimes)

RWA:
  RWA = 5,480,017.52 × 0.50 = 2,740,008.76
```

Compare with the 2% QCCP proprietary leg: the non-QCCP fallback
multiplies the CCP-leg RWA by **25×** (50% / 2%) at CQS 2. This is the
structural incentive that drives clearing through QCCPs.

---

## Pending — items documented here for forward visibility

| # | Gap                                                                                                                                          | Article             | Status                                  |
|---|----------------------------------------------------------------------------------------------------------------------------------------------|---------------------|-----------------------------------------|
| 1 | `apply_ccp_risk_weight` not wired into `pipeline_adapter.py::ccr_rows_to_exposures`. The function exists with unit-test coverage but is unreachable from the orchestrator. | Art. 306(1)(a)–(c) | P8.30 follow-up                         |
| 2 | Art. 308(2) / 309(1) / 310 default-fund own funds — **implemented** (`engine/ccr/default_fund.py`, see [above](#engine-implementation-engineccrdefault_fundpy)); only the `K_CCP` simulation and the Art. 303(2) cap remain out of scope. | Art. 307–310        | Done (2026-11 review, CC-10)            |
| 3 | Art. 308(3) and Art. 309(2) RWA conversion (`× 12.5`). | Art. 308(3), 309(2) | Done                                    |
| 4 | Per-condition Art. 305(2)(a)/(b)/(c) audit-trail booleans on the trade schema (the engine currently collapses the three-part test into a single `is_client_cleared` flag pre-engine). | Art. 305(2)         | Tracked alongside (1); operator-driven  |

The math itself is documented above for all four — the engine wiring
is the follow-up.

---

## References

- **PRA Rulebook — Counterparty Credit Risk (CRR) Part, Article 306** —
  trade-exposure risk weights (2% / 4%); UK-onshored re-export of the
  pre-revocation CRR text with PS1/26 Art. 306(4) restated verbatim.
- **PRA Rulebook — Counterparty Credit Risk (CRR) Part, Article 305(2)** —
  client-clearing condition list (segregation, portability, legal
  robustness) that gates the 2% vs 4% client-leg distinction.
- **PRA Rulebook — Counterparty Credit Risk (CRR) Part, Article 307** —
  own-funds requirement for default-fund contributions to a CCP
  (engine-pending — see "Pending" table above).
- **PRA Rulebook — Counterparty Credit Risk (CRR) Part, Article 308(3)** —
  RWA = own-funds-requirement × 12.5 for pre-funded default-fund
  contributions to a QCCP.
- **PRA Rulebook — Counterparty Credit Risk (CRR) Part, Article 309(2)** —
  RWA = own-funds-requirement × 12.5 for default-fund contributions to
  a non-QCCP.
- **PRA Rulebook — Counterparty Credit Risk (CRR) Part, Article 272 Def (88)** —
  definition of *qualifying central counterparty*.
- **CRR Art. 107(2) = PS1/26 Art. 107(2)** — (a) other exposures to a
  QCCP treated as institution exposures; (b) other exposures to a
  non-QCCP treated as corporate exposures (Art. 306(1)(b) applies the
  same weight to non-QCCP trade exposures).
- **BCBS CRE54.14, CRE54.15, CRE54.18, CRE54.21–22, CRE54.27** —
  Basel-level methodology for QCCP trade-exposure weights, the client-
  clearing condition list, and the default-fund-contribution stack.
- [`src/rwa_calc/engine/ccr/ccp.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/engine/ccr/ccp.py) —
  engine implementation of `apply_ccp_risk_weight` (Art. 306(1)(a)–(c)).
- [`src/rwa_calc/rulebook/packs/common.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/rulebook/packs/common.py) —
  cited pack params (`qccp_proprietary_rw = 0.02`,
  `qccp_client_cleared_rw = 0.04`), resolved in `engine/ccr/ccp.py` via
  `_QCCP_PACK.scalar_param(...)`.
- [`src/rwa_calc/data/schemas.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/data/schemas.py) —
  CCR schemas carrying the `is_qccp` (counterparty) and
  `is_client_cleared` (trade) Boolean flags.
- `tests/unit/ccr/test_ccp.py` — unit-test coverage of the 2% / 4% /
  NULL branching matrix.
- [SA risk weights (CRR)](../sa-risk-weights.md) — risk-weight lookup
  used on the non-QCCP fallback branch (Art. 107(2)(b) corporate
  ladder) and for non-trade exposures to a QCCP (Art. 107(2)(a)
  institution ladder).
- [EAD composition](ead-composition.md) — `α · (RC + PFE)` chain that
  produces `ead_ccr`; QCCP rows preserve this EAD and override only
  the risk weight.
- [PFE multiplier](pfe-multiplier.md) — upstream Art. 278 stage that
  contributes the PFE limb of EAD.
- [Replacement cost (RC)](rc-calculation.md) — upstream Art. 275 stage
  that contributes the RC limb of EAD.
- [SA-CCR — CCR landing page](index.md) — full SA-CCR pipeline shape
  with this page positioned at step 9 (post-EAD).
- [Output floor (Basel 3.1)](../../basel31/output-floor.md) — the
  QCCP row enters both `U-TREA` and `S-TREA` identically (the 2% /
  4% pin is framework-invariant).
