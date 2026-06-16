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

Non-qualifying CCP (non-QCCP) trade exposures fall back to the standard
SA-CCR EAD and the ordinary SA institution risk-weight (Art. 121, or
the corresponding Basel 3.1 ECRA / SCRA bucket) per Art. 107(2)(a).

This page documents:

- the Art. 306 trade-exposure risk-weight ladder (2% / 4% / non-QCCP
  fallback) and the Art. 305(2)(a)–(c) condition list for the
  client-clearing 2% leg;
- the Art. 307 default-fund-contribution stack and its current
  engine status (placeholder pending);
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
| Art. 307               | Own funds requirements for **default-fund contributions** to a CCP — engine-pending (see below) | CRE54.21 |
| Art. 308(3)            | RWA = own-funds requirement × 12.5 for **pre-funded** default-fund contributions to a QCCP    | CRE54.22 |
| Art. 309(2)            | RWA = own-funds requirement × 12.5 for default-fund contributions / unfunded contributions to a non-QCCP | CRE54.27 |
| Art. 107(2)(a)         | Non-QCCP fallback — exposures classified as institution exposures and weighted per the SA institution ladder | CRE20.14 |

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

### Pending engine wiring — `apply_ccp_risk_weight` not yet orchestrated

!!! warning "Engine gap — orchestrator hook missing"
    `apply_ccp_risk_weight` is implemented and unit-tested
    (`tests/unit/ccr/test_ccp.py`) but is **not yet called from
    `engine/ccr/pipeline_adapter.py::ccr_rows_to_exposures`**. The
    `is_qccp` and `is_client_cleared` flags exist on the CCR
    counterparty and trade schemas (`data/schemas.py`), and the
    regulatory scalars are cited pack params in the rulebook common
    pack, but the synthetic
    exposure row currently flows from SA-CCR EAD straight to the
    Classifier without the QCCP gate. Wiring this through is the
    follow-up batch P8.30; until then, every QCCP trade is
    risk-weighted by the standard SA institution ladder instead of
    the regulatory 2% / 4% pin. This is a **conservative**
    mis-pricing — the SA institution weight (20% CQS-1, 50% CQS-2,
    etc., per [`../sa-risk-weights.md`](../sa-risk-weights.md)) is
    higher than the QCCP 2% / 4%, so firms are over-stating
    capital, not under-stating it.

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

### Engine status — default fund contributions not yet implemented

!!! warning "Engine gap — Art. 307 not implemented"
    The Art. 307 own-funds-requirement formula (the "K_CM" stack
    that allocates a portion of the CCP's hypothetical capital
    requirement `K_CCP` to each clearing member by pre-funded
    contribution share) is **not** implemented in
    `src/rwa_calc/engine/ccr/ccp.py`. The module covers only the
    Art. 306 trade-exposure RW. Articles 307 / 308(3) / 309(2) are
    deferred to a follow-up batch; until then, a clearing member
    must compute its default-fund-contribution RWA off-system and
    fold the result into the aggregator's `manual_addon` channel
    (or report-only adjustment).

The default-fund-contribution stack is not on the SA-CCR EAD chain — it
sits on a separate input (the firm's pre-funded contribution amount and
the CCP-published `K_CCP` / `DF_CM` figures) and produces an own-funds
requirement directly. The 12.5× RWA conversion in Art. 308(3) is the
standard inverse of the 8% capital ratio — no SA-CCR EAD is involved.

---

## Non-QCCP fallback to standard SA-CCR

When the counterparty's `is_qccp` flag is `False`, the SA-CCR EAD
(`α · (RC + PFE)`, Art. 274(2)) is preserved unchanged, the
`apply_ccp_risk_weight` annotator returns `risk_weight = NULL`, and
the synthetic exposure row falls back to the standard SA / IRB
risk-weight ladder via the Classifier:

| Framework            | Counterparty class                     | Risk weight ladder                                                   | Reference                                                   |
|----------------------|----------------------------------------|----------------------------------------------------------------------|-------------------------------------------------------------|
| CRR                  | Institutions (Art. 107(2)(a))          | CQS-1 → 20%, CQS-2 → 50%, CQS-3 → 50%, CQS-4/5 → 100%, CQS-6 → 150% (Art. 121) | [`../sa-risk-weights.md`](../sa-risk-weights.md)           |
| Basel 3.1 (PS1/26)   | Institutions (Art. 121 Bucket A/B/C)   | ECRA-rated: A → 20%, B → 30%/40% by short/long-term; SCRA: A → 40%, B → 75%, C → 150% | [`../sa-risk-weights.md`](../sa-risk-weights.md) |

The non-QCCP fallback **does not amend** the SA-CCR EAD — `α = 1.4`
still applies, the multiplier and add-on aggregation are unchanged.
What changes is only the downstream risk-weight lookup: instead of the
2% / 4% Art. 306 pin, the row is weighted as an ordinary institution
exposure. Under Basel 3.1, the same row also enters both legs of the
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

### Example 4 — Non-QCCP fallback (standard SA institution RW)

The same trade, but the CCP is not on the PRA / FSMA-recognised QCCP
list (e.g. a non-EMIR-equivalent overseas CCP). `is_qccp = False`,
`is_client_cleared` is irrelevant on this branch.

```
Inputs:
  ead_ccr           = 5,480,017.52
  is_qccp           = False                       (Art. 272 Def (88) not satisfied)
  is_client_cleared = (any)                       (ignored on the non-QCCP branch)

apply_ccp_risk_weight branch:
  ¬is_qccp → Art. 107(2)(a) (institution SA path)
  risk_weight       = NULL                        (deferred to Classifier + SA Calculator)

Downstream Classifier (P8.30):
  exposure_class    = "INSTITUTION"               (CRR Art. 121 / B31 Art. 121 Bucket A/B)
  CQS               = 2 (illustrative)
  risk_weight       = 0.50                        (CRR Art. 121 Table 3; or B31 ECRA Bucket B → 0.40)

RWA (under CRR):
  RWA = 5,480,017.52 × 0.50 = 2,740,008.76
```

Compare with the 2% QCCP proprietary leg: the non-QCCP fallback
multiplies the CCP-leg RWA by **25× under CRR** (50% / 2%) and
**20× under Basel 3.1** (40% / 2%). This is the structural
incentive that drives clearing through QCCPs.

---

## Pending — items documented here for forward visibility

| # | Gap                                                                                                                                          | Article             | Status                                  |
|---|----------------------------------------------------------------------------------------------------------------------------------------------|---------------------|-----------------------------------------|
| 1 | `apply_ccp_risk_weight` not wired into `pipeline_adapter.py::ccr_rows_to_exposures`. The function exists with unit-test coverage but is unreachable from the orchestrator. | Art. 306(1)(a)–(c) | P8.30 follow-up                         |
| 2 | Art. 307 own-funds-requirement formula for **pre-funded** default-fund contributions to a QCCP — `K_CCP` / `K_CM` allocation stack — not implemented. | Art. 307            | Engine batch deferred                   |
| 3 | Art. 308(3) and Art. 309(2) RWA conversion (`× 12.5`) — gated on (2). | Art. 308(3), 309(2) | Engine batch deferred                   |
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
- **PRA Rulebook — Counterparty Credit Risk (CRR) Part, Article 107(2)(a)** —
  non-QCCP exposures classified as institution exposures and weighted
  per the SA institution ladder.
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
  used on the non-QCCP fallback branch (Art. 107(2)(a) institution
  ladder).
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
