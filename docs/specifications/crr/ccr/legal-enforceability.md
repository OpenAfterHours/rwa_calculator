# SA-CCR — Legal-enforceability gate (Art. 272(4), Art. 295–297)

The legal-enforceability gate is the first stage of the SA-CCR pipeline:
**before** any per-trade adjusted-notional, supervisory-delta or
maturity-factor work runs, the orchestrator inspects every netting set
and asks a single binary question — *is this netting agreement legally
enforceable against the counterparty under Section 7
(Art. 295–297)?* The answer determines whether the trades inside that
agreement see each other through the rest of the SA-CCR chain or are
fanned out into single-trade synthetic netting sets that recognise no
netting benefit at all.

The gate is asset-class-agnostic — it sits **above** the IR / FX /
credit / equity / commodity branches and is the only stage that runs
on every CCR pipeline regardless of the trade book composition. It
also runs ahead of the WWR gate (`apply_wwr_gate`), which performs an
identical "break each affected trade into its own NS" rewrite for a
different reason (Art. 291(5)(a) specific-WWR LGD override). The two
gates are deliberately structured the same way so the downstream
SA-CCR chain only ever sees one consistent partition.

This page documents:

- the Art. 272(4) "netting set" definition and the second-subparagraph
  fallback for non-enforceable agreements;
- the Art. 295 framework for recognising contractual netting (the
  agreement *types* that may be recognised at all);
- the Art. 296(2)(a)–(d) conditions every contractual netting
  agreement must satisfy — in particular the written legal-opinion
  obligation and the four jurisdictions it must address;
- the Art. 296(2) last-subparagraph supervisory power to disregard a
  contractual netting agreement on enforceability grounds (the same
  power Art. 297 backs by ongoing-monitoring obligations);
- the engine's gate implementation in `sa_ccr.py:83–210` and the
  `CCR001` warning it emits per affected original netting set;
- a worked example showing two ITM and three OTM trades in a
  non-enforceable netting set producing a higher EAD than the
  enforceable equivalent — the direct mechanical cost of failing the
  gate.

## Regulatory citation

**Primary source:** PRA Rulebook — Counterparty Credit Risk (CRR) Part,
Articles 272(4), 295, 296, 297. PS1/26 Appendix 1 carries these
articles forward into the Basel 3.1 regime **by reference**: the PS1/26
glossary entry for "netting set" on p. 396 reads in full *"has the
meaning in Article 272(4) of CRR"*, and the contractual-netting Part
applies the CRR Section 7 articles unchanged. The Basel 3.1 legal-
enforceability gate is therefore identical to the CRR gate — the same
verbatim text governs both frameworks.

| Sub-article         | Coverage                                                                                                                | BCBS cross-reference |
|---------------------|-------------------------------------------------------------------------------------------------------------------------|----------------------|
| Art. 272(4) ¶1     | Netting set = group of transactions between a firm and a **single counterparty** subject to a legally enforceable bilateral netting arrangement recognised under Section 7 and Chapter 4 | CRE50.05–50.10       |
| Art. 272(4) ¶2     | Each transaction that is **not** subject to a recognised legally enforceable bilateral netting arrangement is treated as its own netting set | CRE52.05             |
| Art. 295(a)–(c)    | Three types of contractual netting agreement eligible for recognition (novation, other bilateral, contractual cross-product) | CRE55.05             |
| Art. 295 (final ¶) | Cross-entity-group netting is **not** recognised for own-funds purposes                                                | CRE55.05             |
| Art. 296(1)        | Competent-authority recognition is required for every contractual netting agreement                                    | CRE55.10             |
| Art. 296(2)(a)     | Single-legal-obligation requirement — net sum, not gross                                                               | CRE55.11             |
| Art. 296(2)(b)     | Written and reasoned legal opinions — four jurisdictions covered                                                        | CRE55.12             |
| Art. 296(2)(c)     | Credit-risk aggregation into internal credit-limit and capital processes                                                | CRE55.13             |
| Art. 296(2)(d)     | No walk-away clause — the contract may not let a non-defaulting party withhold payment to the defaulting party         | CRE55.14             |
| Art. 296(2) last ¶ | Supervisory power to disregard the netting agreement when not satisfied of legal validity in every relevant jurisdiction | CRE55.15             |
| Art. 297(1)–(4)    | Ongoing obligations: review under changes of law, documentation, integration into CCR measurement, cross-product procedures | CRE55.20–55.23       |
| Art. 274(2)        | EAD = α · (RC + PFE) — the consumer downstream of the gate (see [ead-composition.md](ead-composition.md)) | CRE52.1              |

### Verbatim text — CRR Art. 272(4)

> "*‘netting set’ means a group of transactions between an institution
> and a single counterparty that is subject to a legally enforceable
> bilateral netting arrangement that is recognised under Section 7 and
> Chapter 4.*
>
> *Each transaction that is not subject to a legally enforceable
> bilateral netting arrangement which is recognised under Section 7
> shall be treated as its own netting set for the purposes of this
> Chapter.*"

— CRR (EU 575/2013 as onshored), Part Three Title II Chapter 6 Section 1
(source PDF: `docs/assets/crr.pdf`, p. 273). PS1/26 incorporates this
definition by reference (`ps126app1.pdf`, p. 396).

The **second subparagraph** is the operative regulatory mandate
underlying this gate: it is not optional — every trade that fails the
Section 7 recognition test **must** be treated as its own one-trade
netting set, regardless of any economic netting the counterparty would
honour in practice. The mechanical effect downstream is that
intra-set offsets disappear: signed mark-to-market values that would
cancel within an enforceable netting set instead sit on their own
single-trade NSes where the `max(V − C, 0)` floor in Art. 275(1)
discards every negative `V` while keeping every positive `V` (see the
worked example below).

### Verbatim text — CRR Art. 295

> "*Institutions may treat as risk reducing in accordance with
> Article 298 only the following types of contractual netting
> agreements where the netting agreement has been recognised by
> competent authorities in accordance with Article 296 and where the
> institution meets the requirements set out in Article 297:*
>
> *(a) bilateral contracts for novation between an institution and its
> counterparty under which mutual claims and obligations are
> automatically amalgamated in such a way that the novation fixes one
> single net amount each time it applies so as to create a single new
> contract that replaces all former contracts and all obligations
> between parties pursuant to those contracts and is binding on the
> parties;*
>
> *(b) other bilateral agreements between an institution and its
> counterparty;*
>
> *(c) contractual cross-product netting agreements for institutions
> that have received the approval to use the method set out in
> Section 6 for transactions falling under the scope of that
> method.*
>
> *Netting across transactions entered into by different legal
> entities of a group shall not be recognised for the purposes of
> calculating the own funds requirements.*"

— CRR, p. 295.

Art. 295 is a **type whitelist**: only the three named agreement
shapes are eligible for recognition at all. Anything else — for
example a netting set assembled informally across multiple unrelated
master agreements, or netting purportedly straddling two separate
legal entities of the counterparty's group — is excluded *before*
Art. 296 even applies. The final-subparagraph carve-out on cross-
entity-group netting is the regulatory expression of the principle
that own-funds relief follows the legal counterparty, not the economic
group.

### Verbatim text — CRR Art. 296(2)(a)–(d)

The legal-opinion obligation in Art. 296(2)(b) is the most
operationally load-bearing condition of the four, because it
quantifies *how many* jurisdictions the firm must obtain a written
and reasoned legal opinion for before competent-authority recognition
can be granted:

> "*The following conditions shall be fulfilled by all contractual
> netting agreements used by an institution for the purposes of
> determining exposure value in this Part:*
>
> *(a) the institution has concluded a contractual netting agreement
> with its counterparty which creates a single legal obligation,
> covering all included transactions, such that, in the event of
> default by the counterparty it would be entitled to receive or
> obliged to pay only the net sum of the positive and negative
> mark-to-market values of included individual transactions;*
>
> *(b) the institution has made available to the competent authorities
> written and reasoned legal opinions to the effect that, in the
> event of a legal challenge of the netting agreement, the
> institution's claims and obligations would not exceed those referred
> to in point (a). The legal opinion shall refer to the applicable
> law:*
>
> >  *(i) the jurisdiction in which the counterparty is incorporated;*
> >
> >  *(ii) if a branch of an undertaking is involved, which is located
> >  in a country other than that where the undertaking is
> >  incorporated, the jurisdiction in which the branch is located;*
> >
> >  *(iii) the jurisdiction whose law governs the individual
> >  transactions included in the netting agreement;*
> >
> >  *(iv) the jurisdiction whose law governs any contract or
> >  agreement necessary to effect the contractual netting;*
>
> *(c) credit risk to each counterparty is aggregated to arrive at a
> single legal exposure across transactions with each counterparty.
> This aggregation shall be factored into credit limit purposes and
> internal capital purposes;*
>
> *(d) the contract shall not contain any clause which, in the event
> of default of a counterparty, permits a non-defaulting counterparty
> to make limited payments only, or no payments at all, to the estate
> of the defaulting party, even if the defaulting party is a net
> creditor (i.e. walk-away clause).*"

— CRR, p. 296.

The four obligations decompose into:

| Condition         | Operational meaning                                                                                                                                                                                              |
|-------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **(a) Single legal obligation** | The contract must collapse all included transactions into one net claim/obligation at default — *not* a stack of gross claims that the firm asserts an offset against. Standard ISDA Master Agreement + Schedule satisfies this for in-scope products. |
| **(b) Written and reasoned legal opinions** | Up to **four** separate opinions per agreement (counterparty's incorporation jurisdiction, branch jurisdiction if any, transaction-governing law, agreement-governing law) — all must conclude that the netting would survive a legal challenge in default. The opinion may be drawn up by reference to *types* of contractual netting per Art. 296(3), so industry-standard ISDA opinions for standardised master agreements meet the requirement without per-counterparty re-issuance. |
| **(c) Credit aggregation** | The netted exposure must be the figure used by internal credit-limit and capital systems — not just a regulatory artefact. This forces operational consistency between the regulatory and internal risk views. |
| **(d) No walk-away clause** | The contract may not include any clause permitting a non-defaulting party to withhold payment to the defaulting party's estate when the defaulting party is a net creditor. This eliminates the asymmetric-payoff variant of close-out netting historically common in cross-border agreements. |

### Verbatim text — Art. 296(2) last subparagraph (supervisory power)

> "*If […] the competent authorities are not satisfied that the
> contractual netting is legally valid and enforceable under the law
> of each of the jurisdictions referred to in point (b) the
> contractual netting agreement shall not be recognised as risk-
> reducing for either of the counterparties.*"

— CRR, p. 296.

This is the **enforceability over-ride**: even when an agreement
nominally satisfies Art. 296(2)(a), (c) and (d) and the firm has
filed legal opinions per (b), the competent authority retains the
unilateral power to disregard the netting on enforceability grounds.
In engine terms this means a firm cannot self-certify
`is_legally_enforceable = True` on the netting set frame — the value
must reflect the supervisor's current acceptance of the agreement.

### Verbatim text — CRR Art. 297

> "*1. An institution shall establish and maintain procedures to
> ensure that the legal validity and enforceability of its contractual
> netting is reviewed in the light of changes in the law of relevant
> jurisdictions referred to in Article 296(2)(b).*
>
> *2. The institution shall maintain all required documentation
> relating to its contractual netting in its files.*
>
> *3. The institution shall factor the effects of netting into its
> measurement of each counterparty's aggregate credit risk exposure
> and the institution shall manage its CCR on the basis of those
> effects of that measurement.*
>
> *4. In the case of contractual cross-product netting agreements
> referred to in Article 295, the institution shall maintain
> procedures under Article 296(2)(c) to verify that any transaction
> which is to be included in a netting set is covered by a legal
> opinion referred to in Article 296(2)(b). […]*"

— CRR, p. 297.

Art. 297(1) is the **ongoing-monitoring obligation**: the netting
opinion is not a one-off document — it must be reviewed whenever the
law of any of the four Art. 296(2)(b) jurisdictions changes. In
practice this is the legal-and-compliance hook that flips
`is_legally_enforceable` from `True` to `False` on a netting-set row
mid-life when (for example) a new insolvency regime emerges in the
counterparty's incorporation jurisdiction that defeats close-out
netting. Art. 297(4) extends the same monitoring obligation to
cross-product netting agreements, where each individual bilateral
master agreement nested inside the cross-product wrapper must
independently satisfy the Art. 296(2)(b) opinion requirement.

---

## Engine entry point

The gate is implemented as a free function on `sa_ccr.py` that
consumes the raw CCR bundle, partitions netting sets by enforceability,
and emits a new bundle with non-enforceable agreements broken out into
single-trade synthetic netting sets:

```python
from rwa_calc.engine.ccr.sa_ccr import apply_legal_enforceability_gate

def apply_legal_enforceability_gate(raw_ccr: RawCCRBundle) -> RawCCRBundle:
    """Expand non-enforceable netting sets into single-trade synthetic NSes.

    CRR Art. 272(4) second subparagraph requires that when a netting
    agreement fails the recognition conditions of Art. 295-297
    (``is_legally_enforceable == False``), each trade in that netting
    set must be treated as its own single-trade netting set — i.e. no
    netting benefit is recognised."""
```

Source: [`src/rwa_calc/engine/ccr/sa_ccr.py::apply_legal_enforceability_gate`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/engine/ccr/sa_ccr.py#L83-L210)
(lines 83–210).

```python
--8<-- "src/rwa_calc/engine/ccr/sa_ccr.py:83:210"
```

### Inputs (`RawCCRBundle`)

The gate operates on the aggregate CCR input bundle assembled by the
loader. The single load-bearing column is the boolean
`is_legally_enforceable` flag on the netting-set frame; all other
inputs are pass-through.

| Column                                  | Source                                | Schema                              | Notes                                                                                                                                                          |
|-----------------------------------------|----------------------------------------|-------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `netting_sets.is_legally_enforceable`   | `NETTING_SET_SCHEMA.is_legally_enforceable` | `Boolean` (default `False`)        | **Conservative default — no netting benefit until legality confirmed.** The schema's `default=False` (`src/rwa_calc/data/schemas.py:826`) means an unset flag triggers the gate. |
| `netting_sets.netting_set_id`           | `NETTING_SET_SCHEMA.netting_set_id`    | `String`                            | Used as the prefix of the synthetic split id `"<ns_id>__split__<trade_id>"`.                                                                                   |
| `netting_sets.counterparty_reference`   | `NETTING_SET_SCHEMA.counterparty_reference` | `String`                            | Carried onto the `CCR001` warning's `counterparty_reference` field for downstream reconciliation.                                                              |
| `trades.netting_set_id`                 | `TRADE_SCHEMA.netting_set_id`          | `String`                            | Remapped on affected rows to the synthetic split id.                                                                                                            |
| `trades.trade_id`                       | `TRADE_SCHEMA.trade_id`                | `String`                            | Used as the suffix of the synthetic split id.                                                                                                                  |

### Outputs (`RawCCRBundle`)

The gate produces a new frozen `RawCCRBundle` with three coupled
mutations:

| Output                          | Mutation                                                                                                                                                                | Notes                                                                                            |
|---------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------|
| `trades`                        | Affected rows: `netting_set_id ← "<original>__split__<trade_id>"`. Unaffected rows pass through unchanged.                                                              | Trade row count is **preserved** — only the `netting_set_id` column is rewritten.                |
| `netting_sets`                  | Affected NS rows are deleted and replaced by `N` synthetic rows (one per trade in the affected NS), with the original NS row's columns broadcast onto each synthetic row. | NS row count **expands** from `1 → N` for each affected NS.                                       |
| `errors`                        | One `CalculationError(code="CCR001", severity=WARNING, category=ErrorCategory.CCR_LEGAL)` appended per **affected original NS** (not per split trade).                  | The aggregation key is the original `netting_set_id` — an NS with 100 trades emits **one** `CCR001` warning, not 100. |

The `CCR001` warning is the canonical observability hook for the gate
firing. Its fields are:

| Field                      | Value                                                                                              |
|----------------------------|----------------------------------------------------------------------------------------------------|
| `code`                     | `"CCR001"` (constant `CCR_LEGAL_ENFORCEABILITY_ERROR_CODE` on `sa_ccr.py:42`)                      |
| `severity`                 | `ErrorSeverity.WARNING`                                                                            |
| `category`                 | `ErrorCategory.CCR_LEGAL`                                                                          |
| `field_name`               | `"is_legally_enforceable"`                                                                         |
| `expected_value`           | `"True (Art. 295 conditions met)"`                                                                 |
| `actual_value`             | `"False"`                                                                                          |
| `regulatory_reference`     | `"CRR Art. 272(4); Art. 295-297"` (constant `CCR_LEGAL_ENFORCEABILITY_REG_REF` on `sa_ccr.py:45`)  |
| `counterparty_reference`   | The affected NS's `counterparty_reference` (joins the warning back to the firm's CP master)        |
| `message`                  | `"Netting set <ns_id> is not legally enforceable per Art. 295-297; trades expanded to single-trade netting sets per Art. 272(4)."` |

The gate also logs a single INFO line at the end of execution
(`sa_ccr.py:197`):
`"legal-enforceability gate expanded %d netting set(s) into single-trade NSes"`,
which the orchestrator wraps in the standard `stage_timer` envelope.

---

## Pipeline ordering

The legal-enforceability gate is the **first SA-CCR stage to run** —
ahead of both the per-trade SA-CCR chain and the WWR gate:

```
PipelineOrchestrator.run_with_data
  → Loader
  → ccr_sa_ccr registry stage (engine/stages/ccr.py::run, wired in
    engine/registry.py and folded by orchestrator.run_stages)
      → apply_legal_enforceability_gate    (Art. 272(4); this page)   ← FIRST
      → apply_wwr_gate                     (Art. 291(5)(a))
      → ccr_rows_to_exposures              (engine/ccr/pipeline_adapter.py)
          ├─ 1. Adjusted notional           (Art. 279b)
          ├─ 2. Supervisory delta           (Art. 279a)
          ├─ 3. Maturity factor             (Art. 279c, 285)
          ├─ 4. Hedging-set partition       (Art. 277, 277a)
          ├─ 5. Asset-class add-on          (Art. 277a)
          ├─ 6. RC                          (Art. 275, see rc-calculation.md)
          ├─ 7. PFE multiplier + add-on     (Art. 278, see pfe-multiplier.md)
          └─ 8. EAD                         (Art. 274(2), see ead-composition.md)
      → synthetic exposure rows
  → Classifier / CRM / SA / IRB / OutputAggregator
```

Source: [`src/rwa_calc/engine/stages/ccr.py::run`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/engine/stages/ccr.py). The
`ccr_sa_ccr` stage is declared in `engine/registry.py`
(`StageSpec('ccr_sa_ccr', ccr.run, error_type='ccr_error')`) and folded
through `orchestrator.run_stages`, which wraps it in the standard
`stage_timer` envelope. The stage applies the WWR gate after the
legal-enforceability gate, then runs the EAD chain and seals its exit
edge (`CCR_EXIT_EDGE`):

```python
def run(ctx: PipelineContext, rulepack: RulepackV0, run_config: RunConfig) -> PipelineContext:
    ...
    # Apply the Art. 272(4) legal-enforceability gate first so
    # non-enforceable netting sets are split into single-trade synthetic
    # NSes, then the Art. 291(5)(a) WWR gate, before the EAD chain runs.
    raw_ccr_gated = apply_wwr_gate(apply_legal_enforceability_gate(data.ccr))
    ccr_exposure_rows = ccr_rows_to_exposures(
        raw_ccr_gated,
        run_config.ccr,
        run_config.reporting_date,
        ...,
    )
    ...  # seal the producer edge contract via CCR_EXIT_EDGE
```

The "gate first, chain second" ordering is the **only** ordering
consistent with Art. 272(4) ¶2: the SA-CCR chain consumes
`netting_set_id` as a partition key in every per-NS aggregation step
(steps 5–8 above). If the gate ran *after* the chain, the per-NS
`v_net`, `c_net`, `addon_aggregate` would already have been computed
against the original (enforceable-presumed) NS partition, and the
break-out would only affect downstream reporting — not the regulatory
EAD. By running the gate first, every per-NS aggregation downstream
already sees the synthetic single-trade partition for non-enforceable
agreements.

### Interaction with the WWR gate

The WWR gate (`apply_wwr_gate`, see
[`src/rwa_calc/engine/ccr/wwr.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/engine/ccr/wwr.py))
uses an **identical break-out mechanism** for a different regulatory
trigger — Art. 291(5)(a) specific WWR requires each `is_specific_wwr =
True` trade to live in its own synthetic NS so the LGD = 100% override
of Art. 291(5)(c) applies to the WWR trade in isolation. The two
gates are designed to compose: if a trade is **both** in a non-
enforceable netting set **and** flagged specific-WWR, the legal-
enforceability gate fires first (producing `<original_ns>__split__<trade_id>`),
then the WWR gate observes the already-split frame and applies its own
`__wwr__<trade_id>` suffix on top if needed. The
[`wwr.py:138`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/engine/ccr/wwr.py#L138)
comment explicitly references this gate as the precedent for its
break-out logic.

### CRM-passthrough — the gate does not touch collateral

The gate rewrites `netting_set_id` on the trade and netting-set frames
only — it does **not** rewrite the CCR collateral frame
(`ccr_collateral`). This is deliberate: collateral pledged against a
non-enforceable netting agreement is itself non-enforceable as netting
collateral, so the downstream per-NS aggregation in
`pipeline_adapter.py` will simply fail to find collateral matching
the synthetic split `netting_set_id`s and emit `c_net = 0.0` for each
split row. The RC calculation
([rc-calculation.md](rc-calculation.md#a-unmargined-formula--art-2751))
then reduces to `RC_split = max(V_trade, 0)`, which is the exact
regulatory outcome — collateral provides no offset when the netting
agreement underlying it is not recognised.

---

## Worked numeric example — five-trade non-enforceable netting set

The example below is constructed to highlight the central mechanical
effect of the gate: signed mark-to-market values that would cancel
within an enforceable netting set instead survive on their own single-
trade NSes because the `max(V − C, 0)` floor in Art. 275(1) discards
every negative `V` while keeping every positive `V`. The example uses
the same fixture shape as the P8.18 acceptance scenario
(`tests/fixtures/ccr/p8_18_non_enforceable.py`) extended to five
trades.

### Scenario setup

A single netting set `NS_NE_5` against counterparty `CP_NE` contains
five at-par unmargined IR derivative trades — two in-the-money, three
out-of-the-money:

| Trade | `mtm_value` | `addon` (illustrative) | Direction      |
|-------|-------------|------------------------|----------------|
| T1    | `+200`      | `1,000`                | ITM            |
| T2    | `+150`      | `800`                  | ITM            |
| T3    | `−80`       | `600`                  | OTM            |
| T4    | `−120`      | `500`                  | OTM            |
| T5    | `−50`       | `400`                  | OTM            |

No collateral is posted, so `C = 0` everywhere.

### Case A — enforceable netting set (`is_legally_enforceable = True`)

The gate does **not** fire — the netting set passes through unchanged
and the SA-CCR chain sees one NS with five trades:

```
v_net (NS_NE_5)        = +200 + 150 − 80 − 120 − 50          = +100        (net ITM)
c_net (NS_NE_5)        = 0
RC_unmargined          = max(100 − 0, 0)                     = 100         (Art. 275(1))
addon_aggregate        = 1,000 + 800 + 600 + 500 + 400       = 3,300       (plain sum, Art. 278(2))
pfe_multiplier         = min(1, 0.05 + 0.95·exp(100/(2·0.95·3,300)))
                       ≈ min(1, 0.05 + 0.95·exp(0.01595))
                       ≈ min(1, 0.05 + 0.95·1.01608)
                       ≈ min(1, 1.01528) = 1.0               (cap binds, Art. 278(3))
pfe_addon              = 1.0 × 3,300                         = 3,300       (Art. 278(1))
EAD_enforceable        = 1.4 × (100 + 3,300)                 = 4,760       (Art. 274(2))
```

The negative-MTM trades **net off** the positive-MTM trades inside
`v_net`, leaving a net positive position of only `+100`. The PFE
component sits at the cap because `V − C = +100 ≥ 0`.

### Case B — non-enforceable netting set (`is_legally_enforceable = False`)

The gate fires. The bundle returned from
`apply_legal_enforceability_gate` carries five synthetic single-trade
netting sets:

| Synthetic NS              | Trade | `v_net` | `c_net` | `addon_aggregate` |
|---------------------------|-------|---------|---------|--------------------|
| `NS_NE_5__split__T1`      | T1    | `+200`  | `0`     | `1,000`            |
| `NS_NE_5__split__T2`      | T2    | `+150`  | `0`     | `800`              |
| `NS_NE_5__split__T3`      | T3    | `−80`   | `0`     | `600`              |
| `NS_NE_5__split__T4`      | T4    | `−120`  | `0`     | `500`              |
| `NS_NE_5__split__T5`      | T5    | `−50`   | `0`     | `400`              |

The SA-CCR chain then runs independently on each synthetic NS:

```
T1 (V = +200):  RC = max(+200, 0) = 200;  mult = min(1, 0.05 + 0.95·exp(200/(2·0.95·1,000)))
                                                ≈ min(1, 0.05 + 0.95·exp(0.10526))
                                                ≈ min(1, 0.05 + 0.95·1.11100)
                                                ≈ min(1, 1.10545) = 1.0
                pfe_addon = 1,000;  EAD_T1 = 1.4 × (200 + 1,000) = 1,680

T2 (V = +150):  RC = max(+150, 0) = 150;  mult ≈ 1.0 (V > 0, cap binds)
                pfe_addon = 800;    EAD_T2 = 1.4 × (150 + 800) = 1,330

T3 (V = −80):   RC = max(−80, 0)  = 0;    mult = min(1, 0.05 + 0.95·exp(−80/(2·0.95·600)))
                                                = min(1, 0.05 + 0.95·exp(−0.07018))
                                                = min(1, 0.05 + 0.95·0.93223)
                                                = min(1, 0.93562) = 0.93562
                pfe_addon ≈ 561.37; EAD_T3 = 1.4 × (0 + 561.37) ≈ 785.92

T4 (V = −120):  RC = max(−120, 0) = 0;    mult = min(1, 0.05 + 0.95·exp(−120/(2·0.95·500)))
                                                = min(1, 0.05 + 0.95·exp(−0.12632))
                                                = min(1, 0.05 + 0.95·0.88134)
                                                = min(1, 0.88727) = 0.88727
                pfe_addon ≈ 443.63; EAD_T4 = 1.4 × (0 + 443.63) ≈ 621.09

T5 (V = −50):   RC = max(−50, 0)  = 0;    mult = min(1, 0.05 + 0.95·exp(−50/(2·0.95·400)))
                                                = min(1, 0.05 + 0.95·exp(−0.06579))
                                                = min(1, 0.05 + 0.95·0.93634)
                                                = min(1, 0.93951) = 0.93951
                pfe_addon ≈ 375.80; EAD_T5 = 1.4 × (0 + 375.80) ≈ 526.13
```

The counterparty-level CCR EAD is the **sum** of the five synthetic
EADs (each row is independent — there is no further netting recognised
by the rest of the pipeline):

```
EAD_non_enforceable = 1,680 + 1,330 + 785.92 + 621.09 + 526.13 ≈ 4,943.13
```

### Mechanical impact

| Quantity                       | Case A (enforceable) | Case B (non-enforceable) | Delta            |
|--------------------------------|----------------------|--------------------------|------------------|
| Net `v_net` exposure           | `+100`               | `+350` (sum of ITM `V`)  | `+250`           |
| Aggregate RC                   | `100`                | `350`                    | `+250` (+250%)   |
| Aggregate `addon_aggregate`    | `3,300`              | `3,300` (unchanged)       | `0`              |
| Aggregate PFE                  | `3,300`              | ≈ `3,180.81`              | `−119.19` (−3.6%) |
| **Aggregate EAD**              | **`4,760.00`**       | **≈ `4,943.13`**          | **`+183.13`** (**+3.85%**) |

The RC effect dominates: the non-enforceable case loses the OTM trades'
negative `V` contribution to `v_net` (because the per-trade `max(V −
C, 0)` floor discards each negative `V` independently), so the
aggregate RC rises from `100` to `350` (+250%). The PFE component
moves only slightly in the **opposite** direction — the gate
disaggregates the `V − C / 2(1−F)·AddOn` exponent into per-trade
shards, which on the OTM trades pushes their individual multipliers
fractionally below `1.0` and reduces the per-trade `pfe_addon` against
the original (capped) aggregate. The net effect on EAD is positive —
the RC inflation more than offsets the small PFE reduction — yielding
an aggregate EAD ≈ 3.85% higher than the enforceable equivalent.

The mechanical asymmetry — RC moves materially, PFE barely moves —
is the regulatory signature of Art. 272(4) ¶2: the second
subparagraph penalises non-enforceable agreements by eliminating
current-exposure netting in particular, while leaving the supervisory-
factor-driven add-on broadly intact.

### Pinned unit-test variant — P8.18 (two-trade case)

The shipped test scenario
[`tests/unit/ccr/test_legal_enforceability.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/tests/unit/ccr/test_legal_enforceability.py)
uses the smaller P8.18 fixture
([`tests/fixtures/ccr/p8_18_non_enforceable.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/tests/fixtures/ccr/p8_18_non_enforceable.py))
which exercises the gate's break-out and warning emission directly,
without driving the full SA-CCR chain to numerical EAD values:

| Fixture row | `netting_set_id` | `is_legally_enforceable` | Trades                                                        |
|-------------|------------------|--------------------------|----------------------------------------------------------------|
| `NS_Q1`     | `NS_Q1`          | `False`                  | `T_A` (mtm `+100`, notional `100m GBP`); `T_B` (mtm `−60`, notional `80m GBP`) |

After `apply_legal_enforceability_gate`:

- Trades' `netting_set_id` column: `{NS_Q1__split__T_A, NS_Q1__split__T_B}`.
- Netting-set frame: 2 rows (one synthetic NS per split trade).
- `bundle.errors`: 1 `CalculationError(code="CCR001", severity=WARNING,
  category=CCR_LEGAL, regulatory_reference="CRR Art. 272(4); Art. 295-297")`.
- Trade row count: preserved at 2 (gate only rewrites `netting_set_id`).

The acceptance scenario `CCR-A5` *(Non-enforceable netting fallback)*
is reserved on the [CCR index](index.md#scenario-coverage--ccr-a) for
the full end-to-end variant that drives the synthetic-split bundle
through the entire pipeline to a counterparty-level RWA.

---

## Pending — engine gaps documented here

The following items are **not** engine-wired today but are documented
for forward visibility:

1. **End-to-end acceptance scenario CCR-A5** — a full pipeline
   acceptance test driving the synthetic-split bundle through the
   SA-CCR chain to a counterparty-level RWA. The break-out mechanism
   is unit-tested via P8.18 today, but no shipped acceptance scenario
   pins the EAD-uplift consequence of the gate firing.
2. **Per-trade `is_legally_enforceable` flag** — the current schema
   carries `is_legally_enforceable` on the netting-set frame only. A
   future refinement might add a per-trade flag for the edge case
   where some trades inside a netting set were entered into before the
   legal opinion's effective date and therefore individually fail
   Art. 296(2)(b) even though the netting agreement as a whole is
   recognised.
3. **Counterparty-master integration** — the `CCR001` warning carries
   a `counterparty_reference` field, but the loader does not yet
   verify that the referenced counterparty exists in the firm's
   counterparty master. A dangling reference produces a `CCR001` with
   a `counterparty_reference` that no downstream system recognises —
   a data-quality validator for this is on the roadmap.

## References

- **PRA Rulebook — Counterparty Credit Risk (CRR) Part, Article 272(4)** —
  netting-set definition and the second-subparagraph fallback for
  trades not subject to a recognised legally enforceable bilateral
  netting arrangement. UK-onshored verbatim re-export of EU 575/2013.
- **PRA Rulebook — Counterparty Credit Risk (CRR) Part, Article 295** —
  three eligible types of contractual netting agreement (novation,
  other bilateral, contractual cross-product); cross-entity-group
  netting excluded.
- **PRA Rulebook — Counterparty Credit Risk (CRR) Part, Article 296(1)–(3)** —
  competent-authority recognition; single-legal-obligation requirement;
  written-and-reasoned legal-opinion obligation across four
  jurisdictions; credit-aggregation requirement; walk-away-clause
  prohibition; supervisory power to disregard agreements that are not
  legally valid in every relevant jurisdiction.
- **PRA Rulebook — Counterparty Credit Risk (CRR) Part, Article 297(1)–(4)** —
  ongoing obligations: review under changes of law; documentation;
  CCR-measurement integration; cross-product procedures.
- **PS1/26 Appendix 1, p. 396** — "netting set has the meaning in
  Article 272(4) of CRR" — Basel 3.1 incorporates the CRR
  legal-enforceability gate by reference; no textual amendments.
- **BCBS CRE50.05–50.10, CRE52.05, CRE55.05–55.23** — Basel-level
  methodology and the underlying Basel III calibration of the
  contractual-netting recognition framework.
- [`src/rwa_calc/engine/ccr/sa_ccr.py::apply_legal_enforceability_gate`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/engine/ccr/sa_ccr.py#L83-L210) —
  engine implementation (lines 83–210) of the Art. 272(4) gate.
- [`src/rwa_calc/engine/stages/ccr.py::run`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/engine/stages/ccr.py) —
  the `ccr_sa_ccr` registry stage (declared in `engine/registry.py`,
  folded by `orchestrator.run_stages` inside a `stage_timer`) that runs
  the gate and feeds its output into `ccr_rows_to_exposures`.
- [`src/rwa_calc/engine/ccr/pipeline_adapter.py::ccr_rows_to_exposures`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/engine/ccr/pipeline_adapter.py) —
  downstream orchestrator that drives the per-trade SA-CCR chain over
  the post-gate netting-set partition.
- [`src/rwa_calc/engine/ccr/wwr.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/engine/ccr/wwr.py) —
  WWR gate (Art. 291(5)(a)) that uses the same break-out mechanism for
  specific-WWR trades; cites this page's gate as its precedent.
- [`src/rwa_calc/data/schemas.py::NETTING_SET_SCHEMA`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/data/schemas.py#L817) —
  `is_legally_enforceable: ColumnSpec(pl.Boolean, default=False, required=False)`
  on line 826; conservative default keeps the gate firing whenever the
  flag is unset.
- [`tests/unit/ccr/test_legal_enforceability.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/tests/unit/ccr/test_legal_enforceability.py) —
  unit-test suite pinning the gate's break-out behaviour and the
  `CCR001` warning emission.
- [`tests/fixtures/ccr/p8_18_non_enforceable.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/tests/fixtures/ccr/p8_18_non_enforceable.py) —
  P8.18 fixture used by the unit-test suite.
- [Replacement cost (RC)](rc-calculation.md) — the next stage
  downstream; the `max(V − C, 0)` floor of Art. 275(1) is the mechanism
  through which the gate's break-out materialises into a higher EAD.
- [EAD composition](ead-composition.md) — terminal stage; the EAD
  emitted per synthetic single-trade netting set after the gate fires.
- [SA risk weights (CRR)](../sa-risk-weights.md) — downstream risk-
  weight lookup that ultimately consumes the post-gate EAD via
  `pipeline_adapter.ccr_rows_to_exposures`.
- [CCR index](index.md) — full SA-CCR specification index and per-stage
  status table.
