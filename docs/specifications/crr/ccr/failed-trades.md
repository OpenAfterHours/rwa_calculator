# Settlement risk — Failed trades (Art. 378–380)

CRR Part Three Title V ("Own funds requirements for settlement risk")
sits **outside** the SA-CCR exposure-at-default chain (Art. 274 et
seq.) — failed-settlement capital is a separate Pillar 1 charge that
runs on its own input frame (`RawCCRBundle.failed_trades`) and emits
RWA directly per row rather than producing an EAD that downstream
risk-weight stages consume. The charge applies to two distinct
settlement-failure shapes:

- **Delivery-versus-Payment (DvP) transactions** unsettled **after**
  their due delivery date — Art. 378. The charge is a price-difference
  ladder that scales with the number of working days past due: at
  t+5–15 working days the institution holds 8% of the price
  difference as own funds; at t+46 or more the multiplier reaches
  100% of the price difference (the regulatory equivalent of a
  1,250% risk weight on that price difference once the standard
  `RWA = own-funds × 12.5` conversion is applied).
- **Free deliveries (non-DvP transactions)** — Art. 379. Where the
  institution has paid for securities, FX or commodities before
  receiving them (or delivered before receiving payment), the
  three-column Table 2 routing applies: no charge in Column 2 (up to
  the first contractual leg), the value-transferred treated as a
  credit exposure in Column 3 (from the first leg up to four days
  after the second leg), and a **1,250% risk weight** on
  `value_transferred + current_positive_exposure` in Column 4 (five
  business days after the second leg onwards).

Art. 380 layers a **system-wide failure waiver** on top: where a
clearing system, settlement system or CCP suffers a system-wide
failure, the competent authority may waive both the Art. 378 and
Art. 379 own-funds requirements until the situation is rectified.

This page documents:

- the Art. 378 Table 1 DvP multiplier ladder
  (8%, 50%, 75%, 100% by working-days-past-due band) and the
  price-difference base on which it operates;
- the Art. 379 free-delivery three-column treatment and the
  Column-4 1,250% RW that produces the `RWA = exposure × 12.5`
  conversion;
- the 1,250% RW equivalent at the top of the DvP ladder
  (cross-link [output-floor.md](../../basel31/output-floor.md#of-adj-capital-adjustment)
  for the underlying 8% capital ratio inverse `1 / 0.08 = 12.5`);
- the Art. 380 system-wide failure waiver (schema-supported as a
  Boolean flag; engine currently treats waiver as off);
- the engine entry point (`compute_failed_trade_rwa`) and its
  pipeline status (function exists with full unit-test coverage,
  but is **not yet wired** into the orchestrator);
- one worked example per Art. 378 band plus the Art. 379 Column-4
  shape, replaying the five-row P8.24 fixture
  (`tests/fixtures/ccr/failed_trade_builder.py`) used by the unit-
  test suite.

## Regulatory citation

**Primary source:** PRA Rulebook — onshored CRR Part Three Title V
("Own funds requirements for settlement risk"), Articles 378–380. The
substantive ladder, the free-delivery three-column treatment and the
system-wide failure waiver all live in the carry-forward CRR text.
PRA PS1/26 does **not** restate Art. 378–380 in Appendix 1 — instead,
the PS1/26 calculation of `total_risk_exposure_amount` explicitly
points back at the CRR articles via Art. 92(3)(ca):

> "the own funds requirements for settlement risk calculated in
> accordance with Articles 378 and 380 of CRR"
>
> — PS1/26 Appendix 1, Required Level of Own Funds (CRR) Part,
> Article 92(3)(ca), p. 14 (source PDF: `docs/assets/ps126app1.pdf`).

and at Article 92(3)(a):

> "the risk-weighted exposure amounts for credit risk and dilution
> risk, calculated in accordance with Title II of Part Three of CRR,
> the credit risk rules, the Counterparty Credit Risk (CRR) Part and
> **Articles 379 and 380 of CRR** in respect of all the business
> activities of an institution […]"
>
> — PS1/26 Appendix 1, Required Level of Own Funds (CRR) Part,
> Article 92(3)(a), p. 14.

The split is deliberate. Art. 378 (DvP) and Art. 379 (free delivery)
produce different output shapes: Art. 378 produces an **own-funds
requirement** that PS1/26 routes through paragraph (ca) ("own funds
requirements for settlement risk"); Art. 379 Column 4 produces an
**RWA** at the 1,250% pin that PS1/26 routes through paragraph (a)
("risk-weighted exposure amounts"). The engine collapses both into
the same `failed_trade_rwa` column by applying the standard
`RWA = own_funds × 12.5` conversion on the DvP branch — but the
upstream regulatory categorisation differs.

| Sub-article             | Coverage                                                                                                                            | BCBS cross-reference |
|-------------------------|-------------------------------------------------------------------------------------------------------------------------------------|----------------------|
| Art. 378 ¶1             | Scope: unsettled-after-due-date transactions in debt instruments, equities, FX, commodities. Repos and securities lending / borrowing are **excluded**. | —                    |
| Art. 378 ¶2             | Price-difference base: `max(0, agreed_settlement_price − current_market_value)`, taken only where the difference could imply a loss for the institution. | —                    |
| Art. 378 ¶3 + Table 1   | Multiplier ladder by working-days-past-due band — 5–15 d → 8%; 16–30 d → 50%; 31–45 d → 75%; ≥ 46 d → 100%.                          | —                    |
| Art. 379(1) Table 2 Col 2 | Up to the first contractual payment / delivery leg: **no capital charge**.                                                          | —                    |
| Art. 379(1) Table 2 Col 3 | From the first leg up to four days after the second leg: **treat as an exposure** (IRB / SA risk-weight per ordinary credit-risk rules). | —                    |
| Art. 379(1) Table 2 Col 4 | From five business days after the second leg until extinction: **treat as an exposure risk-weighted at 1,250%**.                    | —                    |
| Art. 379(2)             | IRB PD inference + immateriality 100% RW alternative (engine-deferred — flag present in schema, default False).                      | —                    |
| Art. 379(3)             | CET1 deduction alternative to the Column-4 1,250% RW (engine-deferred — flag present in schema, default False).                      | —                    |
| Art. 380                | System-wide failure waiver (engine-deferred — flag present in schema, default False).                                                | —                    |
| PS1/26 Art. 92(3)(a)    | UK onshoring carry-forward for Art. 379 / 380 RWA contribution.                                                                       | —                    |
| PS1/26 Art. 92(3)(ca)   | UK onshoring carry-forward for Art. 378 / 380 own-funds-requirement contribution; standard `RWA = own_funds × 12.5` conversion (`= 1 / 0.08`). | —                    |

> **Citation note — watchfire CRR index gap.** The bundled watchfire
> CRR rulebook index (`rulebook_version 2026-05-15`) does not yet
> contain CRR Title V (Articles 378–380), so the engine module
> (`src/rwa_calc/engine/ccr/failed_trades.py`) deliberately omits the
> `@cites(...)` decorators that other CCR modules carry. The article
> attribution lives entirely in the docstring + this spec page until
> the watchfire index re-extension lands. See the leading comment on
> `failed_trades.py:71–77` for the same explanation in the source.

### Verbatim text — CRR Art. 378

> "In the case of transactions in which debt instruments, equities,
> foreign currencies and commodities excluding repurchase
> transactions and securities or commodities lending and securities
> or commodities borrowing are unsettled after their due delivery
> dates, an institution shall calculate the price difference to which
> it is exposed.
>
> The price difference is calculated as the difference between the
> agreed settlement price for the debt instrument, equity, foreign
> currency or commodity in question and its current market value,
> where the difference could involve a loss for the credit
> institution.
>
> The institution shall multiply that price difference by the
> appropriate factor in the right column of the following Table 1 in
> order to calculate the institution's own funds requirement for
> settlement risk."

— CRR (EU 575/2013 as onshored), Part Three Title V, p. 365 (source
PDF: `docs/assets/crr.pdf`).

#### CRR Art. 378 Table 1 — DvP multiplier ladder

| Number of working days after due settlement date | (%) own-funds factor |
|--------------------------------------------------|----------------------|
| 5 — 15                                           | 8                    |
| 16 — 30                                          | 50                   |
| 31 — 45                                          | 75                   |
| 46 or more                                       | 100                  |

The table operates on the **price difference**, *not* on the full
transaction notional. The price difference is the residual loss the
institution would incur if it closed out the failed leg at the
prevailing market price — `agreed_settlement_price` (what the
counterparty was contractually due to pay / deliver against) less
`current_market_value` (what the institution would now realise in the
market), floored at zero so the institution never books a negative
own-funds figure on an in-the-money failed trade.

The first 5 working days carry **no own-funds requirement** under
Art. 378 — the regulator's recognition that operational settlement
delays of up to one week are a routine market hygiene matter that
does not justify a Pillar 1 charge. The 5-band lower bound is the
post-settlement grace period built into the ladder itself; it is
**not** a separate Art. 379 mechanism (the plan-item summary on
this page conflated the two and is corrected here).

#### Conversion to RWA — Art. 92(3)(ca) `× 12.5`

CRR Art. 378 produces an **own-funds requirement**, not an RWA. The
standard 8%-capital-ratio inverse converts to an RWA-equivalent in
the firm-level aggregator:

```
RWA_dvp = own_funds_dvp × 12.5      (12.5 = 1 / 0.08)
```

At the top of the ladder (`≥ 46 working days past due`, multiplier
100%), the institution holds **the full price difference** as own
funds — equivalent to applying a **1,250% risk weight to the price
difference** (`100% own-funds factor × 12.5 = 1,250%`). This is the
same 1,250% pin that Art. 379 Column 4 applies directly to the
non-DvP exposure — see
[output-floor.md § OF-ADJ Capital Adjustment](../../basel31/output-floor.md#of-adj-capital-adjustment)
for the canonical discussion of the `12.5 = 1 / 0.08` conversion in
the framework-level aggregator.

### Verbatim text — CRR Art. 379(1)

> "An institution shall be required to hold own funds, as set out in
> Table 2, where the following occurs:
>
> (a) it has paid for securities, foreign currencies or commodities
> before receiving them or it has delivered securities, foreign
> currencies or commodities before receiving payment for them;
>
> (b) in the case of cross-border transactions, one day or more has
> elapsed since it made that payment or delivery."

— CRR, Part Three Title V, p. 365.

#### CRR Art. 379(1) Table 2 — Free-delivery capital treatment

| Transaction Type | Column 2 — Up to first contractual payment or delivery leg | Column 3 — From first contractual leg up to four days after second contractual leg | Column 4 — From 5 business days post second contractual leg until extinction |
|------------------|------------------------------------------------------------|------------------------------------------------------------------------------------|------------------------------------------------------------------------------|
| Free delivery    | No capital charge                                          | Treat as an exposure                                                               | Treat as an exposure risk weighted at **1,250%**                              |

The three-column structure scales the treatment with the temporal
distance between the institution's payment / delivery and the
counterparty's reciprocal performance. Column 2 reflects the
regulator's recognition that, until the institution itself has
performed, no asymmetric exposure exists. Column 3 treats the
transferred value as an ordinary credit-risk exposure to the
counterparty — risk-weighted via the standard SA / IRB ladder per
Title II — once the institution has performed but before five
business days have elapsed past the second leg. Column 4 caps the
escalation at the **1,250% RW pin** — the regulatory expression of
"this exposure should consume own funds at the rate of full
deduction" under the standard `RWA × 8% = own_funds` capital ratio.

The engine currently implements only the **Column 4** path (the
schema and bands cover all three columns; the engine's `regulatory_band`
falls through to `dvp_pre_t5` for the Column 2 path, and Column 3 is
not yet implemented — see "Engine status" below).

#### Art. 379(2) — IRB inference + immateriality 100% RW alternative

> "In applying a risk weight to free delivery exposures treated
> according to Column 3 of Table 2, an institution using the Internal
> Ratings Based approach set out in Part Three, Title II, Chapter 3
> may assign PDs to counterparties, for which it has no other non-
> trading book exposure, on the basis of the counterparty's external
> rating. […] Alternatively, an institution using the Internal
> Ratings Based approach […] may apply the risk weights of the
> Standardised Approach […] or may apply a 100% risk weight to all
> such exposures.
>
> If the amount of positive exposure resulting from free delivery
> transactions is not material, institutions may apply a risk weight
> of 100% to these exposures, except where a risk weight of 1,250% in
> accordance with Column 4 of Table 2 in paragraph 1 is required."

— CRR, Part Three Title V, p. 366.

The Art. 379(2) immateriality election is preserved on the schema
(`is_immaterial: Boolean, default=False`) but is **not** consumed by
the engine today. Materiality assessment is firm-judgement-driven; the
implementation path is to (i) introduce a fresh `regulatory_band` value
`"non_dvp_immaterial_100rw"`, (ii) branch on the flag in
`compute_failed_trade_rwa`, and (iii) skip the immateriality branch on
Column 4 rows per the carve-out in the last sentence of Art. 379(2).

#### Art. 379(3) — CET1 deduction alternative

> "As an alternative to applying a risk weight of 1,250% to free
> delivery exposures according to Column 4 of Table 2 in paragraph
> 1, institutions may deduct the value transferred plus the current
> positive exposure of those exposures from Common Equity Tier 1
> items in accordance with point (k) of Article 36(1)."

— CRR, Part Three Title V, p. 366.

The CET1 deduction route is the **economic dual** of the 1,250% RW
pin (`exposure × 1,250% × 8% = exposure × 100%`, i.e. full own-funds
consumption either way). The schema preserves the election as
`elect_cet1_deduction: Boolean, default=False` but the engine path is
deferred — the deduction would feed the CET1-deduction line of the
aggregator rather than the RWA line, requiring a coordinated change
across the failed-trades calculator and the aggregator's own-funds
surface.

### Verbatim text — CRR Art. 380 (system-wide failure waiver)

> "Where a system wide failure of a settlement system, a clearing
> system or a CCP occurs, competent authorities may waive the own
> funds requirements calculated as set out in Articles 378 and 379
> until the situation is rectified. In this case, the failure of a
> counterparty to settle a trade shall not be deemed a default for
> purposes of credit risk."

— CRR, Part Three Title V, p. 366.

Art. 380 is the **regulatory escape hatch**: when the failed
settlement is the consequence of a system-wide infrastructure failure
(not counterparty distress), the competent authority may suspend the
Art. 378 / 379 charges entirely, and — separately — the counterparty's
failure to settle is explicitly carved out of the credit-risk default
definition (Art. 178). The schema preserves the election as
`system_wide_failure_waiver: Boolean, default=False` so a firm can
flag rows under an active PRA waiver; the engine path is deferred —
when the flag is True the calculator would short-circuit to
`own_funds_requirement = 0` and `failed_trade_rwa = 0` regardless of
the band, and the row would also need to be excluded from any
upstream Art. 178 default flagging on the counterparty.

---

## Engine entry point

The failed-trade calculation is a free function on
`engine/ccr/failed_trades.py` that consumes the
`FailedTradesBundle.failed_trades` LazyFrame and emits a per-row
LazyFrame with the own-funds requirement, RWA, and a stable
`regulatory_band` audit string for downstream attribution:

```python
from rwa_calc.engine.ccr.failed_trades import compute_failed_trade_rwa

def compute_failed_trade_rwa(
    failed_trades: pl.LazyFrame,
    config: CalculationConfig,
) -> pl.LazyFrame:
    """Compute own-funds and RWA for failed trades per CRR Art. 378 / 379.

    For DvP rows (``settlement_type == "dvp"``): compute
    ``price_difference = max(0, agreed_settlement_price - current_market_value)``
    and look up the Art. 378 Table 1 multiplier by ``working_days_past_due``
    band (5-15, 16-30, 31-45, 46+). Own-funds = price_difference x multiplier;
    RWA = own_funds x 12.5.

    For non-DvP free-delivery rows (``settlement_type ==
    "non_dvp_free_delivery"``) past t+5: compute
    ``exposure_amount = value_transferred + current_positive_exposure``,
    treat as a credit-risk exposure at 1250% RW, so RWA = exposure x 12.5
    and own_funds = exposure (Art. 379(1) Table 2 Column 4)."""
```

Source: [`src/rwa_calc/engine/ccr/failed_trades.py::compute_failed_trade_rwa`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/engine/ccr/failed_trades.py#L78-L217)
(lines 78–217).

```python
--8<-- "src/rwa_calc/engine/ccr/failed_trades.py:78:217"
```

### Inputs (`FailedTradesBundle.failed_trades`)

The calculator consumes a LazyFrame matching
`FAILED_TRADE_SCHEMA` (defined on
[`src/rwa_calc/data/schemas.py:926`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/data/schemas.py#L926)).
Settlement-type discriminates the two branches: DvP rows must supply
`agreed_settlement_price` + `current_market_value`; non-DvP rows must
supply `value_transferred` + `current_positive_exposure`.

| Column                          | Source                                        | Dtype       | Notes                                                                                                  |
|---------------------------------|-----------------------------------------------|-------------|--------------------------------------------------------------------------------------------------------|
| `failed_trade_id`               | `FAILED_TRADE_SCHEMA.failed_trade_id`         | `String`    | Primary key — passes through unchanged.                                                                |
| `counterparty_reference`        | `FAILED_TRADE_SCHEMA.counterparty_reference`  | `String`    | Joins the row back to the firm's CP master.                                                            |
| `settlement_type`               | `FAILED_TRADE_SCHEMA.settlement_type`         | `String`    | `"dvp"` or `"non_dvp_free_delivery"` — branch discriminator.                                           |
| `working_days_past_due`         | `FAILED_TRADE_SCHEMA.working_days_past_due`   | `Int32`     | Number of working days elapsed since due settlement date — drives the Art. 378 / 379 band lookup.       |
| `instrument_class`              | `FAILED_TRADE_SCHEMA.instrument_class`        | `String`    | `"debt" \| "equity" \| "fx" \| "commodity"` — audit attribution only; not consumed by the formula.     |
| `agreed_settlement_price`       | `FAILED_TRADE_SCHEMA.agreed_settlement_price` | `Float64`   | DvP-only required. Null on non-DvP rows. Art. 378 ¶2 price-difference numerator.                       |
| `current_market_value`          | `FAILED_TRADE_SCHEMA.current_market_value`    | `Float64`   | DvP-only required. Null on non-DvP rows. Art. 378 ¶2 price-difference subtrahend.                      |
| `value_transferred`             | `FAILED_TRADE_SCHEMA.value_transferred`       | `Float64`   | Non-DvP-only required. Null on DvP rows. Art. 379(1) exposure numerator (the "value transferred" leg). |
| `current_positive_exposure`     | `FAILED_TRADE_SCHEMA.current_positive_exposure` | `Float64` | Non-DvP-only required. Null on DvP rows. Art. 379(1) exposure addend.                                  |
| `is_repo_or_sec_lending`        | `FAILED_TRADE_SCHEMA.is_repo_or_sec_lending`  | `Boolean` (default `False`) | Art. 378 ¶1 scope exclusion — not currently consumed (engine treats every row as in scope). |
| `is_immaterial`                 | `FAILED_TRADE_SCHEMA.is_immaterial`           | `Boolean` (default `False`) | Art. 379(2) immateriality election — not currently consumed.                                           |
| `elect_cet1_deduction`          | `FAILED_TRADE_SCHEMA.elect_cet1_deduction`    | `Boolean` (default `False`) | Art. 379(3) CET1 deduction election — not currently consumed.                                          |
| `system_wide_failure_waiver`    | `FAILED_TRADE_SCHEMA.system_wide_failure_waiver` | `Boolean` (default `False`) | Art. 380 waiver — not currently consumed.                                                              |

### Outputs

The calculator returns a LazyFrame with one row per input row and the
following derived columns. The two branch-specific value columns
(`price_difference` and `exposure_amount`) are emitted on both
branches as nullable Floats so the resulting frame has a stable shape;
non-applicable cells are `null`.

| Column                    | Dtype     | Formula                                                                                                | Article             |
|---------------------------|-----------|--------------------------------------------------------------------------------------------------------|---------------------|
| `price_difference`        | `Float64` (nullable) | `max(0, agreed_settlement_price − current_market_value)` on DvP rows; null on non-DvP rows.            | Art. 378 ¶2         |
| `exposure_amount`         | `Float64` (nullable) | `value_transferred + current_positive_exposure` on non-DvP rows; null on DvP rows.                     | Art. 379(1) Col 4   |
| `multiplier_or_rw`        | `Float64` | DvP rows: Table 1 multiplier (`0.08 / 0.50 / 0.75 / 1.00 / 0.0`); non-DvP Col 4 rows: `12.5`; `0.0` otherwise. | Art. 378 Table 1; Art. 379(1) Table 2 |
| `own_funds_requirement`   | `Float64` | DvP: `price_difference × multiplier`; non-DvP Col 4: `exposure_amount`; `0.0` otherwise.                | Art. 378 ¶3; Art. 379(1) |
| `failed_trade_rwa`        | `Float64` | `own_funds_requirement × 12.5` (= `1 / 0.08`).                                                          | Art. 92(3)(ca)      |
| `regulatory_band`         | `String`  | One of `dvp_5_15`, `dvp_16_30`, `dvp_31_45`, `dvp_46_plus`, `non_dvp_col4_t5_plus`, `dvp_pre_t5`.       | Audit / attribution |

### Pending — engine wiring gaps

!!! warning "Engine gap — orchestrator hook missing (P8.24 follow-up)"
    `compute_failed_trade_rwa` is implemented end-to-end and pinned by
    a 6-test unit suite
    ([`tests/unit/ccr/test_failed_trades.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/tests/unit/ccr/test_failed_trades.py))
    but is **not yet called** from
    [`src/rwa_calc/engine/pipeline.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/engine/pipeline.py)
    or
    [`src/rwa_calc/engine/ccr/pipeline_adapter.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/engine/ccr/pipeline_adapter.py).
    The `FAILED_TRADE_SCHEMA` and the regulatory scalars in
    [`src/rwa_calc/data/tables/failed_trades_multipliers.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/data/tables/failed_trades_multipliers.py)
    are in place, but the orchestrator does not yet read a
    `failed_trades` leaf off the `RawCCRBundle` or aggregate the
    resulting `failed_trade_rwa` into the firm-level totals. Until the
    wiring lands, firms with failed settlements must compute the
    Art. 378 / 379 RWA off-system and fold it into the aggregator's
    `manual_addon` channel (or report-only adjustment).

The following Art. 378–380 sub-articles are **not** consumed by the
engine today (all schema-supported with default-False Boolean flags):

| Gap                                                                                              | Article             | Engine state                                                                                                     |
|--------------------------------------------------------------------------------------------------|---------------------|------------------------------------------------------------------------------------------------------------------|
| Art. 378 ¶1 repo / securities-lending / securities-borrowing exclusion gate                       | Art. 378 ¶1         | `is_repo_or_sec_lending` flag on `FAILED_TRADE_SCHEMA`, not branched on.                                          |
| Pre-t+5 DvP rows                                                                                  | Art. 378 Table 1    | Produce `regulatory_band = "dvp_pre_t5"`, `multiplier_or_rw = 0.0`, `own_funds = 0.0` — the correct outcome by construction. |
| Art. 379(1) Table 2 Column 2 (pre-first-leg) / Column 3 (post-first-leg up to t+4 after second leg) | Art. 379(1)         | Schema present; engine's `regulatory_band` falls through to `dvp_pre_t5` for the Column 2 path, and Column 3 is not yet implemented (the Column-3 path requires routing to the SA / IRB risk-weight ladder rather than a fixed pin). |
| Art. 379(2) immateriality 100% RW alternative                                                     | Art. 379(2)         | `is_immaterial` flag present; not branched on.                                                                    |
| Art. 379(3) CET1 deduction election                                                               | Art. 379(3)         | `elect_cet1_deduction` flag present; not branched on. Would require a CET1-deduction emission to the aggregator. |
| Art. 380 system-wide failure waiver                                                               | Art. 380            | `system_wide_failure_waiver` flag present; not branched on. Would short-circuit the row to zero capital.          |

The implementation notes are preserved in the engine module docstring
on
[`failed_trades.py:23–40`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/engine/ccr/failed_trades.py#L23-L40)
for the engine-implementer follow-up.

---

## Pipeline ordering

```
PipelineOrchestrator.run_with_data
  → Loader
  → CCRCalculator stage (engine/pipeline.py)
      ├─ apply_legal_enforceability_gate    (Art. 272(4))
      ├─ apply_wwr_gate                     (Art. 291(5)(a))
      ├─ ccr_rows_to_exposures              (SA-CCR EAD chain → CCR_DERIVATIVE rows)
      └─ compute_failed_trade_rwa           (Art. 378-380; this page)     ← PENDING ORCHESTRATOR WIRING
            └─ per-row failed_trade_rwa  → aggregator (manual_addon today)
  → Classifier / CRM / SA / IRB
  → OutputAggregator                        (firm-level totals + output floor)
```

The failed-trade calculator is **strictly orthogonal** to the SA-CCR
EAD chain — it does not consume any SA-CCR output and is not consumed
by any SA-CCR downstream stage. Architecturally it lives in the same
`engine/ccr/` package because settlement-failure rows arrive on the
same `RawCCRBundle` input as SA-CCR derivatives data; mechanically it
is a self-contained Pillar 1 stage that produces RWA directly.

### Interaction with the output floor

The 1,250% RW pin at the top of both the DvP ladder (`46+` band)
and the non-DvP Column 4 is **invariant under the output floor**: the
Basel 3.1 output floor compares IRB-driven RWA against an SA-equivalent
RWA at 72.5% (see [output-floor.md](../../basel31/output-floor.md#floor-calculation)),
but the failed-trade RWA has no IRB / SA divergence to floor — both
branches of the floor calculation see the same `own_funds × 12.5`
contribution. The failed-trade row therefore enters both the U-TREA
(unfloored) and S-TREA (standardised) legs of the floor comparison
identically and does not contribute to any floor binding / non-binding
state.

The `12.5 = 1 / 0.08` conversion factor used to translate the
Art. 378 own-funds requirement into RWA is the same multiplier that
[output-floor.md § OF-ADJ Capital Adjustment](../../basel31/output-floor.md#of-adj-capital-adjustment)
discusses for the OF-ADJ own-funds-to-RWA translation — both arise
from the inverse of the 8% Pillar 1 minimum capital ratio.

---

## Worked numeric examples

All five examples below are pinned by the P8.24 unit-test suite at
[`tests/unit/ccr/test_failed_trades.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/tests/unit/ccr/test_failed_trades.py)
via the fixture builder
[`tests/fixtures/ccr/failed_trade_builder.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/tests/fixtures/ccr/failed_trade_builder.py).
The five rows are designed to exercise every published Art. 378 band
plus the Art. 379 Column 4 path, with the portfolio aggregate adding
to `29,737,500`.

### Example 1 — DvP band `5–15` (multiplier 8%) — FT001

A debt-instrument settlement that has failed five working days past
its due settlement date. The price difference is `1,000,000 − 950,000
= 50,000`; the Art. 378 Table 1 multiplier for the `5–15` band is
`0.08`:

```
Inputs:
  settlement_type            = "dvp"
  working_days_past_due      = 5                        (within the 5-15 band)
  agreed_settlement_price    = 1,000,000
  current_market_value       =   950,000

Art. 378 ¶2 price difference:
  price_difference           = max(0, 1,000,000 - 950,000)   = 50,000

Art. 378 Table 1 band lookup:
  regulatory_band            = "dvp_5_15"                    (5 ≥ 5; 5 < 16)
  multiplier_or_rw           = 0.08                          (Table 1: 5-15 → 8%)

Art. 378 ¶3 own-funds requirement:
  own_funds_requirement      = 50,000 × 0.08                = 4,000

Art. 92(3)(ca) RWA conversion:
  failed_trade_rwa           = 4,000 × 12.5                 = 50,000
```

### Example 2 — DvP band `16–30` (multiplier 50%) — FT002

The same shape with a larger price difference (`200,000`) sitting
20 working days past due — comfortably inside the `16–30` band:

```
Inputs:
  working_days_past_due      = 20
  agreed_settlement_price    = 2,000,000
  current_market_value       = 1,800,000
  price_difference           = max(0, 2,000,000 - 1,800,000) = 200,000

Band lookup:
  regulatory_band            = "dvp_16_30"                   (20 ≥ 16; 20 < 31)
  multiplier_or_rw           = 0.50

own-funds + RWA:
  own_funds_requirement      = 200,000 × 0.50              = 100,000
  failed_trade_rwa           = 100,000 × 12.5              = 1,250,000
```

The 6.25× RWA uplift between Example 1 and Example 2 (50,000 →
1,250,000) is driven by both the larger price difference (4×) and the
6.25× multiplier step (0.08 → 0.50) — the regulator's quantitative
expression that 16+ working days past due is materially worse than
the 5-15 grace tier.

### Example 3 — DvP band `31–45` (multiplier 75%) — FT003

```
Inputs:
  working_days_past_due      = 35                          (within the 31-45 band)
  price_difference           = max(0, 500,000 - 400,000)   = 100,000

Band lookup:
  regulatory_band            = "dvp_31_45"
  multiplier_or_rw           = 0.75

own-funds + RWA:
  own_funds_requirement      = 100,000 × 0.75              = 75,000
  failed_trade_rwa           = 75,000 × 12.5               = 937,500
```

### Example 4 — DvP band `46+` (multiplier 100% — the 1,250% RW equivalent) — FT004

The top of the Art. 378 ladder. At 46+ working days past due the
institution holds **the entire price difference** as own funds —
mechanically equivalent to applying a 1,250% risk weight to the price
difference once the standard `× 12.5` conversion lands:

```
Inputs:
  working_days_past_due      = 50                          (≥ 46)
  price_difference           = max(0, 750,000 - 600,000)   = 150,000

Band lookup:
  regulatory_band            = "dvp_46_plus"
  multiplier_or_rw           = 1.00                        (the regulatory cap)

own-funds + RWA:
  own_funds_requirement      = 150,000 × 1.00              = 150,000
  failed_trade_rwa           = 150,000 × 12.5              = 1,875,000

Cross-check — equivalent risk weight:
  effective_rw = failed_trade_rwa / price_difference        = 1,875,000 / 150,000
                                                            = 12.5
                                                            = 1,250%        ← Art. 379 Col 4 equivalent
```

The `1,875,000 / 150,000 = 12.5 = 1,250%` cross-check is the load-
bearing equivalence between the top of the Art. 378 ladder and the
Art. 379 Column 4 pin — both routes produce identical capital
consumption on the affected exposure base (the price difference under
Art. 378; the full transferred value plus current positive exposure
under Art. 379 Col 4). The `12.5` conversion factor is the inverse
of the 8% minimum capital ratio — see
[output-floor.md § OF-ADJ Capital Adjustment](../../basel31/output-floor.md#of-adj-capital-adjustment)
for the canonical discussion in the framework-level aggregator.

### Example 5 — Non-DvP free delivery, Column 4 (1,250% RW direct) — FT005

A free-delivery transaction six working days past the second
contractual leg — into the Art. 379(1) Table 2 Column 4 band. The
exposure base is the **sum** of the value the institution transferred
to the counterparty (`1,000,000`) and the current positive
mark-to-market on the open second leg (`1,050,000`):

```
Inputs:
  settlement_type              = "non_dvp_free_delivery"
  working_days_past_due        = 6                          (≥ 5; into Col 4)
  value_transferred            = 1,000,000
  current_positive_exposure    = 1,050,000

Art. 379(1) Col 4 exposure base:
  exposure_amount              = 1,000,000 + 1,050,000     = 2,050,000

Col 4 risk-weight pin:
  regulatory_band              = "non_dvp_col4_t5_plus"
  multiplier_or_rw             = 12.5                       (1,250% RW direct)
  own_funds_requirement        = 2,050,000 × 1.00          = 2,050,000   (RW = 1,250% ⇒ own-funds factor = 1.0)
  failed_trade_rwa             = 2,050,000 × 12.5          = 25,625,000
```

Note that on the non-DvP Column 4 branch the engine sets
`multiplier_or_rw = 12.5` directly (rather than the `0.08 / 0.50 /
0.75 / 1.00` DvP multipliers). This is the column's regulatory
pin expressed as the RWA multiplier — `own_funds = exposure × 1.0`
(because the 1,250% RW implies an own-funds factor of exactly 1.0
against the full exposure), and `RWA = own_funds × 12.5 = exposure ×
12.5` directly. The implementation's
[`multiplier_or_rw`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/engine/ccr/failed_trades.py#L158-L165)
expression preserves this asymmetry deliberately so the column carries
audit-trail value (DvP rows show the 8% / 50% / 75% / 100% multiplier;
non-DvP Col 4 rows show the `12.5` RW multiplier).

### Portfolio aggregate

```
FT001 (DvP   t+5  band dvp_5_15)            RWA       50,000
FT002 (DvP   t+20 band dvp_16_30)           RWA    1,250,000
FT003 (DvP   t+35 band dvp_31_45)           RWA      937,500
FT004 (DvP   t+50 band dvp_46_plus)         RWA    1,875,000
FT005 (non-DvP t+6 band non_dvp_col4_t5+)   RWA   25,625,000
                                            ----------------
Total failed-trade RWA                            29,737,500
```

The non-DvP Column 4 row dominates the portfolio total (86%) — a
direct consequence of the 1,250% RW pin applying to the **full**
transferred value plus current positive exposure, not to a residual
price difference. The four DvP rows together (8.5% of the portfolio)
demonstrate the laddered nature of Art. 378: the 100%-multiplier band
at the top is **10× higher RWA** than the 8% band at the bottom on
comparable price differences — see Example 1 vs Example 4 for the
direct illustration (50,000 vs 1,875,000 RWA on price differences of
50,000 vs 150,000 respectively).

---

## References

- **PRA Rulebook — onshored CRR Part Three Title V, Article 378** —
  DvP settlement-risk own-funds-requirement ladder; price-difference
  base; Table 1 multipliers by working-days-past-due band (5-15 → 8%;
  16-30 → 50%; 31-45 → 75%; 46+ → 100%).
- **PRA Rulebook — onshored CRR Part Three Title V, Article 379(1)** —
  free-delivery three-column treatment; Column 4 1,250% RW from t+5
  business days after the second contractual leg.
- **PRA Rulebook — onshored CRR Part Three Title V, Article 379(2)** —
  IRB PD inference + immateriality 100% RW alternative (engine-
  deferred; flag on schema).
- **PRA Rulebook — onshored CRR Part Three Title V, Article 379(3)** —
  CET1 deduction alternative to the Column 4 1,250% RW (engine-
  deferred; flag on schema).
- **PRA Rulebook — onshored CRR Part Three Title V, Article 380** —
  system-wide failure waiver (engine-deferred; flag on schema).
- **PRA PS1/26 Appendix 1, Required Level of Own Funds (CRR) Part,
  Article 92(3)(a)** — UK onshoring carry-forward routing Art. 379 /
  380 RWA into `total_risk_exposure_amount`.
- **PRA PS1/26 Appendix 1, Required Level of Own Funds (CRR) Part,
  Article 92(3)(ca)** — UK onshoring carry-forward routing Art. 378 /
  380 own-funds-requirement into `total_risk_exposure_amount` via the
  standard `× 12.5 = 1 / 0.08` conversion.
- [`src/rwa_calc/engine/ccr/failed_trades.py::compute_failed_trade_rwa`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/engine/ccr/failed_trades.py#L78-L217) —
  engine implementation (lines 78–217) of the Art. 378 / 379 calculator.
- [`src/rwa_calc/data/tables/failed_trades_multipliers.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/data/tables/failed_trades_multipliers.py) —
  canonical regulatory scalars: DvP multipliers (`0.08 / 0.50 / 0.75
  / 1.00`), band lower-bound thresholds (5 / 16 / 31 / 46 days),
  non-DvP Col-4 RW multiplier (`12.5`), `OWN_FUNDS_TO_RWA_FACTOR` (`12.5`).
- [`src/rwa_calc/data/schemas.py::FAILED_TRADE_SCHEMA`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/data/schemas.py#L926) —
  failed-trade input schema; the four electives (`is_repo_or_sec_lending`,
  `is_immaterial`, `elect_cet1_deduction`, `system_wide_failure_waiver`)
  default to False per the Art. 378-380 scope rules.
- [`tests/unit/ccr/test_failed_trades.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/tests/unit/ccr/test_failed_trades.py) —
  unit-test suite pinning the five-row P8.24 portfolio and the
  portfolio-aggregate RWA of `29,737,500`.
- [`tests/fixtures/ccr/failed_trade_builder.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/tests/fixtures/ccr/failed_trade_builder.py) —
  P8.24 fixture builder; single source of truth for the five-row
  scenario consumed by the worked examples on this page.
- [Output floor (Basel 3.1) — OF-ADJ](../../basel31/output-floor.md#of-adj-capital-adjustment) —
  the canonical discussion of the `12.5 = 1 / 0.08` own-funds-to-RWA
  conversion factor that the failed-trade calculator uses to translate
  the Art. 378 own-funds requirement into RWA.
- [Legal enforceability](legal-enforceability.md) — sibling CCR
  spec page; the failed-trade calculator is **independent** of the
  SA-CCR legal-enforceability gate (failed trades operate on their own
  input frame).
- [CCP exposures](ccp-exposures.md) — sibling CCR spec page; the
  Art. 380 waiver carve-out specifically covers system-wide failures
  of CCPs alongside settlement / clearing systems.
- [CCR index](index.md) — full SA-CCR specification index with the
  failed-trades row at line 90.
