# SA-CCR — Replacement cost (Art. 275)

The replacement cost (RC) is the netting-set-grain measure of *current*
counterparty exposure — the loss the institution would suffer today if
the counterparty defaulted and every trade in the netting set had to be
closed out at prevailing market prices, net of any collateral already
held. RC is the first of the two components of the SA-CCR exposure
formula (Art. 274(2)):

```
EAD = α × (RC + PFE)         α = 1.4
```

SA-CCR carries **two** RC branches:

- **Unmargined netting sets** — Art. 275(1) — `RC = max(V − C, 0)`. No
  CSA, so the bank carries the full mark-to-market shortfall whenever
  collateral does not cover the positive netting-set value.
- **Margined netting sets** — Art. 275(2) —
  `RC = max(V − C, TH + MTA − NICA, 0)`. A CSA caps the counterparty's
  uncollateralised exposure at the threshold (`TH`) plus the
  minimum-transfer-amount buffer (`MTA`), net of any independent
  collateral already pledged (`NICA`). Even a fully-collateralised
  netting set retains a residual RC because the bank can only call for
  variation margin once losses breach `TH + MTA`.

The two formulas share inputs `V` (per-netting-set MTM aggregate) and
`C` (haircut-adjusted net collateral held) and differ only in the
right-hand floor that the margined branch adds. This page documents the
two formulas, the `NICA` / `TH` / `MTA` definitions, the engine entry
points, and the worked examples pinned by the unit test suite. The
upstream `MPOR_eff` cascade that feeds the *margined* maturity factor
sits one level up the chain on
[maturity-factor.md](maturity-factor.md#mpor-cascade--art-2852-5) — RC
itself is independent of `MPOR_eff`, but the margined branch only
engages on netting sets that also satisfy the Art. 285 margined-NS
gate.

## Regulatory citation

**Primary source:** PRA PS1/26 Counterparty Credit Risk (CRR) Part —
Article 275 (replacement cost) and Article 272 (definitions of margin
agreement, NICA, threshold, MTA). The UK regime is a verbatim
re-export of the onshored CRR text with the Basel 3.1 calibration
retained. References below follow the PRA-priority convention: PRA
Art. numbers first, BCBS CRE52 cross-reference second.

| Sub-article | Coverage | BCBS cross-reference |
|-------------|----------|----------------------|
| Art. 275(1)        | Unmargined RC = `max(V − C, 0)` | CRE52.10 |
| Art. 275(2)        | Margined RC = `max(V − C, TH + MTA − NICA, 0)` | CRE52.11 |
| Art. 272(7)        | Definition of *margin agreement* | CRE50.11 |
| Art. 272(9)        | Definition of *margin period of risk* — feeds `MPOR_eff` on the upstream MF stage | CRE50.13 |
| Art. 271(7)        | Definition of *Net Independent Collateral Amount* (NICA) | CRE50.16 |
| Art. 274(2)        | EAD = `α · (RC + PFE)` — the consumer of RC | CRE52.1 |
| Art. 285(2)–(5)    | Margined-NS gate and MPOR cascade ([maturity-factor.md](maturity-factor.md#mpor-cascade--art-2852-5)) | CRE52.48–52 |

---

## (a) Unmargined formula — Art. 275(1)

For a netting set without a legally enforceable margin agreement, the
replacement cost is the larger of (i) the current market exposure net
of collateral, and (ii) zero:

```
RC_unmargined = max( V − C, 0 )
```

where:

- `V` = `v_net` — the **signed** sum of mark-to-market values over
  every trade in the netting set. Positive `V` means the netting set is
  in-the-money to the bank (counterparty owes); negative `V` means
  out-of-the-money (bank owes).
- `C` = `c_net` — the **net collateral** held against the netting set,
  haircut-adjusted per the Title II CRM rules and signed positive when
  held by the bank. Collateral pledged *by* the bank (negative `c_net`)
  enlarges `V − C` and therefore RC.

The `max(·, 0)` floor reflects the asymmetric default payoff: a bank
cannot owe the counterparty a positive replacement cost — if the
counterparty defaults while owing money to the bank (`V − C > 0`) the
bank loses; if the bank is the one out-of-the-money (`V − C < 0`) the
bank simply walks away from the obligation, RC = 0.

### Worked example — positive V

```
V        = +2,000,000        (in-the-money to the bank)
C        = +1,850,000        (collateral held, haircut-adjusted)
V − C    = +150,000
RC       = max(150,000, 0) = 150,000
```

### Worked example — negative V

```
V        = −500,000          (out-of-the-money to the bank)
C        = 0                 (no collateral)
V − C    = −500,000
RC       = max(−500,000, 0) = 0
```

The negative-`V` case demonstrates the asymmetry: even though the bank
has an economic loss embedded in the trades today, the replacement
cost — the loss *given counterparty default* — is zero. The bank's
liability survives the counterparty's default and is unaffected by
SA-CCR.

### Engine entry point

```python
from rwa_calc.engine.ccr.rc import compute_rc_unmargined

def compute_rc_unmargined(netting_sets: pl.LazyFrame) -> pl.LazyFrame:
    """RC_unmargined = max(v_net − c_net, 0). Reads ``v_net`` and
    ``c_net`` on the netting-set-grain LazyFrame; writes a
    ``rc_unmargined: Float64`` column."""
```

Source: [`src/rwa_calc/engine/ccr/rc.py::compute_rc_unmargined`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/engine/ccr/rc.py#L33-L48).

```python
--8<-- "src/rwa_calc/engine/ccr/rc.py:33:48"
```

---

## (b) Margined formula — Art. 275(2)

For a netting set covered by a legally enforceable margin agreement
(typically an ISDA Master Agreement with a CSA requiring at least daily
exchange of variation margin), the replacement cost is the maximum of
three terms:

```
RC_margined = max( V − C,   TH + MTA − NICA,   0 )
```

The middle term, `TH + MTA − NICA`, is the **largest exposure the bank
can hold without triggering a margin call** — and therefore the
smallest RC the bank can guarantee on demand. Even a CSA with zero
threshold and zero MTA cannot drive RC below `−NICA`, because
independent collateral is posted up-front and not reclaimable on a
single-day default. The three-way `max` enforces three distinct
economic floors:

| Arm | Economic meaning | When it dominates |
|-----|------------------|-------------------|
| `V − C`           | Current uncollateralised market exposure                  | The CSA is operating as designed and the netting set is materially in-the-money relative to the CSA thresholds. |
| `TH + MTA − NICA` | The CSA's permitted uncollateralised buffer               | The CSA is operating as designed but the netting set is only marginally in-the-money — RC is pinned to the buffer the bank tolerates before calling. |
| `0`               | The same default-asymmetry floor as Art. 275(1)            | Both arms are negative (e.g. the netting set is out-of-the-money *and* `NICA > TH + MTA`). |

### NICA — Net Independent Collateral Amount (Art. 271(7))

NICA is **independent collateral** — collateral posted up-front that
secures the netting set regardless of mark-to-market — measured net of
the directional flow:

```
NICA = (independent collateral held by the bank from the counterparty)
     + (segregated initial margin held by the bank from the counterparty)
     − (independent collateral pledged by the bank to the counterparty,
        non-segregated)
```

The asymmetry between "segregated IM held" (included) and
"non-segregated IM pledged" (subtracted) is deliberate: segregated IM
posted *by* the bank is bankruptcy-remote and would be returned on the
counterparty's default, so it does not reduce NICA on the bank's
balance sheet. Non-segregated IM the bank pledges is at risk and so
shows up negatively.

NICA enters Art. 275(2) **subtractively** because it reduces the
buffer above which a margin call would be triggered: a counterparty
that has posted £200,000 of segregated IM and a CSA with TH = £50,000,
MTA = £10,000 has effectively a negative buffer
(`50,000 + 10,000 − 200,000 = −140,000`), so the IM contributes
directly to RC reduction up to (but not below) the zero floor.

### TH — Threshold (Art. 272(7))

The **threshold** is the unsecured-exposure amount specified in the
CSA that the bank tolerates without calling for variation margin.
`TH ≥ 0`. A "zero-threshold" CSA (`TH = 0`) collateralises every
basis point of exposure; a high-threshold CSA (`TH = £25m`) lets the
counterparty run up to £25m of net positive MTM before any VM call.

### MTA — Minimum Transfer Amount (Art. 272 definitions)

The **minimum transfer amount** is the operational floor for any
single margin call. `MTA ≥ 0`. CSAs use MTA to avoid the operational
overhead of calling for £100 of margin when the daily MTM moves by a
trivial amount — the CSA only calls when the cumulative
uncollateralised exposure exceeds `TH + MTA`. The bank therefore
carries both `TH` and `MTA` worth of exposure as a structural part of
the CSA, which is why both add into the RC floor.

### Interaction with the Art. 285 MPOR cascade

The Art. 275(2) formula governs the **current** replacement cost on
the reporting date — it does not include any uplift for the
margin-period-of-risk close-out window. The MPOR enters SA-CCR one
level up the chain via the *margined maturity factor*
`MF_margined = 1.5 × sqrt(MPOR_eff / 250)`, which scales the PFE
add-on rather than RC. See
[maturity-factor.md § MPOR cascade — Art. 285(2)–(5)](maturity-factor.md#mpor-cascade--art-2852-5)
for the full five-step cascade that derives `MPOR_eff`. RC and PFE
combine into EAD per Art. 274(2):

```
EAD = α × (RC_margined + PFE_margined)        α = 1.4
                          ↑
                          PFE_margined inherits MPOR_eff via MF_margined
```

So even when the CSA pins RC to `TH + MTA − NICA`, an MPOR upgrade
(e.g. >5,000-trade netting set forcing `MPOR_eff = 20 BD` per
Art. 285(3)(a)) lifts the PFE branch and therefore the EAD without
touching RC itself.

### Engine entry point

```python
from rwa_calc.engine.ccr.rc import compute_rc_margined

def compute_rc_margined(netting_sets: pl.LazyFrame) -> pl.LazyFrame:
    """RC_margined = max(v_net − c_net, margin_threshold + minimum_transfer_amount
    − nica, 0) for is_margined=True rows; null otherwise. Reads
    ``v_net``, ``c_net``, ``is_margined``, ``margin_threshold``,
    ``minimum_transfer_amount``, ``nica``; writes ``rc_margined:
    Float64``."""
```

Source: [`src/rwa_calc/engine/ccr/rc.py::compute_rc_margined`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/engine/ccr/rc.py#L53-L79).

```python
--8<-- "src/rwa_calc/engine/ccr/rc.py:53:79"
```

The function deliberately returns **null** on unmargined rows
(`is_margined = False`) rather than zero, so a downstream
coalesce-style join can pick the correct branch without an explicit
filter:

```python
rc_effective = pl.coalesce(pl.col("rc_margined"), pl.col("rc_unmargined"))
```

### Worked examples — `tests/unit/ccr/test_rc_margined.py`

All four examples below are pinned by the unit-test suite in
[`tests/unit/ccr/test_rc_margined.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/tests/unit/ccr/test_rc_margined.py)
via the fixture builder
[`tests/fixtures/ccr/rc_margined_builder.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/tests/fixtures/ccr/rc_margined_builder.py).

#### Example 1 — TH + MTA − NICA floor dominates (NS_A)

A marginally in-the-money netting set under a CSA with material
threshold and MTA, partially offset by independent collateral:

```
V                  = +2,000,000      (in-the-money)
C                  = +1,850,000      (haircut-adjusted VM held)
V − C              = +150,000

TH                 = 250,000
MTA                = 100,000
NICA               = 50,000
TH + MTA − NICA    = 300,000

RC_margined        = max(150,000, 300,000, 0) = 300,000
```

The CSA's `TH + MTA = 350,000` permits the counterparty to run up to
£350,000 of uncollateralised exposure before a margin call would
trigger; the £50,000 of NICA offsets some of that, leaving the bank
exposed to £300,000 even though current MTM net of VM is only
£150,000. This is the central regulatory point of Art. 275(2): the
CSA's *structural* buffer dominates current MTM whenever the netting
set is operating inside the buffer.

#### Example 2 — V − C arm dominates (NS_B)

A deeply in-the-money netting set whose current MTM exceeds the CSA
buffer:

```
V                  = +1,500,000
C                  = +400,000
V − C              = +1,100,000

TH                 = 100,000
MTA                = 50,000
NICA               = 25,000
TH + MTA − NICA    = 125,000

RC_margined        = max(1,100,000, 125,000, 0) = 1,100,000
```

When the netting set has moved through the CSA buffer, the bank
should already have called for additional VM — but until that VM is
received and reflected in `C`, the bank still carries the full
`V − C` shortfall as RC.

#### Example 3 — zero floor dominates (NS_C)

A deeply out-of-the-money netting set with NICA exceeding the CSA
buffer:

```
V                  = −500,000        (out-of-the-money to the bank)
C                  = 0
V − C              = −500,000

TH                 = 50,000
MTA                = 10,000
NICA               = 200,000
TH + MTA − NICA    = −140,000

RC_margined        = max(−500,000, −140,000, 0) = 0
```

Both the current-exposure arm and the CSA-buffer arm are negative —
NICA is so large that the structural buffer goes net negative. The
zero floor of Art. 275(2) prevents the bank from booking *negative*
RC against the counterparty.

#### Example 4 — unmargined pass-through (NS_D)

When `is_margined = False`, the function emits null rather than
applying the margined formula. This lets the orchestrator coalesce
the margined and unmargined branches in a single pipeline pass
without a per-row filter — `compute_rc_unmargined` handles the same
row.

```
is_margined        = False
margin_threshold   = null
minimum_transfer_amount = null
nica               = null
RC_margined        = null      (pass-through; Art. 275(1) applies)
```

---

## Pipeline ordering

```
trades → years_to_maturity
       → adjusted_notional         (Art. 279b)
       → supervisory_delta         (Art. 279a)
       → maturity_factor           (Art. 279c — unmargined OR margined per Art. 285)
       → assign_hedging_set        (Art. 277)
       → compute_addon_per_asset_class  (Art. 277a)
       → ↓ per-NS aggregation
netting_sets joined with per-NS v_net, c_net, addon_aggregate
       → compute_rc_unmargined     (Art. 275(1))         ← this page
       → compute_rc_margined       (Art. 275(2))         ← this page
       → compute_pfe               (Art. 278)
       → ead = α × (RC + PFE)      (Art. 274(2))
```

The orchestrator at
[`engine/ccr/pipeline_adapter.py::ccr_rows_to_exposures`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/engine/ccr/pipeline_adapter.py)
currently routes only the **unmargined** branch — every netting set is
treated as unmargined for the CCR-A1 / CCR-A2 acceptance scenarios.
The margined function is implemented end-to-end and pinned by the
unit-test suite, but is not yet routed through the orchestrator
pending the margined-netting-set acceptance batch (CCR-A3, pending
engine batch P8.35–P8.38).

### Inputs

| Column | Source | Schema | Notes |
|--------|--------|--------|-------|
| `v_net`             | `pipeline_adapter` per-NS aggregation of `trade.mtm_value` | `Float64`         | Signed; `fill_null(0.0)` on empty NS. |
| `c_net`             | `pipeline_adapter` per-NS aggregation of `ccr_collateral.collateral_value` | `Float64` | Signed; haircut adjustment applied upstream of the aggregation per Title II. |
| `is_margined`       | `NETTING_SET_SCHEMA.is_margined`                               | `Boolean` (default `False`) | Margined-branch gate. |
| `margin_threshold`  | `NETTING_SET_SCHEMA.margin_threshold`                          | `Float64` (nullable)        | `TH`; null when `is_margined = False`. |
| `minimum_transfer_amount` | `NETTING_SET_SCHEMA.minimum_transfer_amount`             | `Float64` (nullable)        | `MTA`; null when `is_margined = False`. |
| `nica`              | `NETTING_SET_SCHEMA.nica`                                      | `Float64` (nullable)        | Per Art. 271(7); null when `is_margined = False`. |

### Outputs

| Column | Source | Schema | Notes |
|--------|--------|--------|-------|
| `rc_unmargined` | `compute_rc_unmargined` | `Float64`               | Always populated. Floored at 0. |
| `rc_margined`   | `compute_rc_margined`   | `Float64` (nullable)    | Null when `is_margined = False`; floored at 0 otherwise. |

The two columns coexist on the NS-grain frame so the orchestrator can
coalesce them into a single effective RC without re-running either
stage. The synthetic exposure row emitted by `pipeline_adapter` carries
`rc_unmargined` on every row today (margined branch not yet wired);
once margined routing lands, both columns travel through to the
COREP-reconciliation surface.

---

## References

- **PRA PS1/26 Counterparty Credit Risk (CRR) Part — Article 275** —
  unmargined and margined replacement cost.
- **PRA PS1/26 Counterparty Credit Risk (CRR) Part — Article 274(2)** —
  consumes RC into the EAD formula `α · (RC + PFE)`.
- **PRA PS1/26 Counterparty Credit Risk (CRR) Part — Article 271(7)** —
  definition of Net Independent Collateral Amount (NICA).
- **PRA PS1/26 Counterparty Credit Risk (CRR) Part — Article 272(7)–(9)** —
  definitions of margin agreement, margin period of risk, threshold,
  and minimum transfer amount.
- **PRA PS1/26 Counterparty Credit Risk (CRR) Part — Article 285(2)–(5)** —
  margined-NS gate and MPOR cascade; consumed by the *margined
  maturity factor* one stage upstream, not by RC itself
  ([maturity-factor.md](maturity-factor.md#mpor-cascade--art-2852-5)).
- **BCBS CRE52.10–11** — Basel-level RC formulas (unmargined and
  margined).
- **BCBS CRE50.11, CRE50.13, CRE50.16** — Basel-level definitions of
  margin agreement, MPOR, and NICA.
- **`src/rwa_calc/engine/ccr/rc.py`** — engine implementation of
  `compute_rc_unmargined` and `compute_rc_margined`.
- **`src/rwa_calc/data/schemas.py::NETTING_SET_SCHEMA`** — netting-set
  input columns (`is_margined`, `margin_threshold`,
  `minimum_transfer_amount`, `nica`).
- **`tests/unit/ccr/test_rc_margined.py`** — pinned numeric examples
  for the three margined arms plus the unmargined pass-through case.
- **`tests/fixtures/ccr/rc_margined_builder.py`** — fixture builder
  for NS_A / NS_B / NS_C / NS_D used by the worked examples above.
- **[Maturity factor](maturity-factor.md)** — companion page for the
  Art. 285 MPOR cascade that feeds the margined `MF`.
- **[Adjusted notional](adjusted-notional.md)** — companion page for
  the per-asset-class `d` formulas that feed `addon_aggregate` →
  `PFE`.
- **[CCR index](index.md)** — full SA-CCR specification index and the
  per-stage status table.
