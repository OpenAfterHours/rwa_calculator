# Oracle Derivations

This document is the **independent source of truth** for the oracle test suite.
Every expected RWA value in `expected_values.json` corresponds to one section
below, derived directly from the regulation with full intermediate arithmetic.

The companion script `derive.py` re-computes these values using only Python
stdlib (`math`, `statistics`). It does not import any `rwa_calc` code. The
test suite asserts the engine's output matches these independently-derived
numbers within a tight tolerance (relative error ≤ 1e-6).

**Update protocol** — see `README.md`. The short version: this document and
`expected_values.json` are locked together by a SHA-256 hash. They may only
change in lockstep, with both the doc and the script updated and re-derived.

---

## ORC-001 — SA Corporate, unrated

**Framework:** UK CRR (current, until 31 Dec 2026)
**Approach:** Standardised Approach
**Exposure class:** Corporate (CRR Art. 122)

### Inputs

| Parameter | Value | Source |
|---|---|---|
| EAD | £1,000,000 | given |
| External rating | none (unrated) | given |
| CQS | n/a | unrated |

### Regulation

CRR Art. 122(2): exposures to corporates without an eligible ECAI credit
assessment receive a risk weight of 100%.

### Arithmetic

```
RW  = 100%                        (Art. 122(2))
RWA = EAD × RW
    = 1,000,000 × 1.00
    = 1,000,000
```

### Expected outputs

| Field | Value |
|---|---|
| `risk_weight` | 1.00 |
| `rwa` | 1,000,000.00 |

---

## ORC-002 — SA Sovereign, CQS 2 (foreign currency)

**Framework:** UK CRR (current)
**Approach:** Standardised Approach
**Exposure class:** Central government / central bank (CRR Art. 114)

### Inputs

| Parameter | Value | Source |
|---|---|---|
| EAD | £5,000,000 | given |
| Exposure class | CENTRAL_GOVT_CENTRAL_BANK | engine enum |
| ECAI rating mapped to | CQS 2 | given |
| Counterparty country | US | given (non-UK sovereign) |
| Exposure currency | USD | given (foreign currency) |

The country and currency are **load-bearing inputs**: CRR Art. 114(3)/(4)
grants UK sovereign exposures denominated in GBP a 0% RW regardless of
their CQS rating. To exercise the Art. 114(2) Table 1 path cleanly, this
oracle uses a non-UK sovereign in foreign currency.

### Regulation

CRR Art. 114(2), Table 1: exposures to central governments or central banks
that have a CQS 2 ECAI assessment carry a 20% risk weight. Art. 114(3) is
disapplied because country ≠ UK and currency ≠ local currency.

### Arithmetic

```
RW  = 20%                         (Art. 114(2) Table 1, CQS 2)
RWA = EAD × RW
    = 5,000,000 × 0.20
    = 1,000,000
```

### Expected outputs

| Field | Value |
|---|---|
| `risk_weight` | 0.20 |
| `rwa` | 1,000,000.00 |

---

## ORC-003 — F-IRB Corporate, senior unsecured

**Framework:** UK CRR (current)
**Approach:** Foundation IRB
**Exposure class:** Corporate (CRR Art. 153)

This oracle exercises the full Basel/CRR IRB risk-weight formula, the most
analytically complex calculation in the engine.

### Inputs

| Parameter | Value | Source |
|---|---|---|
| EAD | £10,000,000 | given |
| PD | 1.00% (0.01) | given (above PD floor of 0.03%) |
| LGD | 45% (0.45) | F-IRB supervisory LGD, senior unsecured (Art. 161(1)(a)) |
| M (effective maturity) | 2.5 years | given (so maturity adjustment = 1) |

### Regulation

CRR Art. 153(1) — risk-weight formula for non-defaulted corporate exposures
under the IRB approach. The formula is:

```
RW  = 12.5 × 1.06 × K × MA
K   = LGD × [N( (G(PD) + √R · G(0.999)) / √(1−R) ) − PD]
```

The **1.06 scaling factor** is part of Art. 153(1) under CRR. It is removed
in Basel 3.1 (PRA PS1/26) — that change is a separate oracle (not yet
scaffolded). An oracle that omits 1.06 under CRR will under-state RWA by
exactly that ratio, which is precisely how this oracle was first written
(and immediately caught by the engine comparison).

with correlation `R` (Art. 153(1)(iii)):

```
R = 0.12 · (1 − e^(−50·PD)) / (1 − e^(−50))
  + 0.24 · (1 − (1 − e^(−50·PD)) / (1 − e^(−50)))
```

and maturity adjustment `MA` (Art. 153(1)(iv)):

```
b  = (0.11852 − 0.05478 · ln(PD))²
MA = (1 + (M − 2.5) · b) / (1 − 1.5 · b)
```

`N(·)` is the standard normal CDF; `G(·)` its inverse.

### Step 1 — correlation R

```
A   = (1 − exp(−50 × 0.01)) / (1 − exp(−50))
    = (1 − exp(−0.5)) / (1 − exp(−50))
    = (1 − 0.6065306597126334) / (1 − 1.928749847963918e−22)
    = 0.3934693402873666

R   = 0.12 · A + 0.24 · (1 − A)
    = 0.12 × 0.3934693402873666 + 0.24 × 0.6065306597126334
    = 0.04721632083448399 + 0.14556735833103203
    = 0.192783679165516
```

### Step 2 — maturity adjustment b and MA

```
ln(PD) = ln(0.01) = −4.605170185988091

inner_b = 0.11852 − 0.05478 × ln(PD)
        = 0.11852 − 0.05478 × (−4.605170185988091)
        = 0.11852 + 0.25227122278842763
        = 0.37079122278842763

b       = inner_b²
        = 0.37079122278842763²
        = 0.13748613089693737
```

Note: even though M = 2.5 makes the numerator `(M − 2.5) · b` term vanish,
**MA does not equal 1**. The denominator `(1 − 1.5 · b)` still contributes:

```
MA = (1 + (M − 2.5) · b) / (1 − 1.5 · b)
   = 1 / (1 − 1.5 × 0.13748613089693737)
   = 1 / (1 − 0.20622919634540606)
   = 1 / 0.7937708036545939
   = 1.2598095009238282
```

(The denominator is well clear of zero, so this is numerically stable.)

### Step 3 — capital K

```
G(PD)   = G(0.01)   = −2.3263478740408408
G(0.999)            =  3.090232306167813
√R                  =  0.43907138043835
√(1−R)              =  0.8984522387635823

inner   = (G(PD) + √R · G(0.999)) / √(1−R)

√R · G(0.999) = 0.43907138043835 × 3.090232306167813
              = 1.356928...

(Each intermediate is shown to 6 dp here; the script `derive.py` carries
full IEEE-754 double precision throughout.)

N(inner)        = 0.14027267845651598
cond_pd − PD    = 0.14027267845651598 − 0.01 = 0.13027267845651598

K = LGD × (cond_pd − PD) × MA
  = 0.45 × 0.13027267845651598 × 1.2598095009238282
  = 0.07385344111364117
```

### Step 4 — RW and RWA (with CRR 1.06 scaling)

```
RW  = 12.5 × 1.06 × K
    = 12.5 × 1.06 × 0.07385344111364117
    = 0.9785580947557455

RWA = EAD × RW
    = 10,000,000 × 0.9785580947557455
    = 9,785,580.947557455
```

### Expected outputs

| Field | Value |
|---|---|
| `correlation_R` | 0.192783679165516 |
| `maturity_adj_b` | 0.13748613089693737 |
| `maturity_adj_MA` | 1.2598095009238282 |
| `G_pd` | −2.3263478740408408 |
| `G_999` | 3.090232306167813 |
| `conditional_pd` | 0.14027267845651598 |
| `K` | 0.07385344111364117 |
| `crr_scaling_factor` | 1.06 |
| `risk_weight` | 0.9785580947557455 |
| `rwa` | 9,785,580.95 |

---

## How to add a new oracle exposure

1. Add a new section to this file with the same structure (inputs, regulation
   citation, full arithmetic, expected outputs).
2. Add a corresponding function to `derive.py` that computes the same values
   using stdlib only.
3. Add a corresponding test method to `test_oracle.py`.
4. Run `uv run python tests/oracle/derive.py` to regenerate
   `expected_values.json` (which embeds a fresh hash of this document).
5. Run `uv run pytest tests/oracle/` and confirm both the hash test and the
   value tests pass.
6. Commit all four files (this doc, `derive.py`, `expected_values.json`,
   `test_oracle.py`) in a single commit.

## Why this layout

The engine cannot validate itself. `tests/expected_outputs/{crr,basel31}/*`
are recorded engine outputs — they catch regressions but are structurally
incapable of detecting a wrong implementation. The oracle suite breaks that
loop by deriving the expected numbers from the regulation independently,
with the arithmetic shown in plain text so a regulator or auditor can
verify each step by eye.

The hash lock prevents the most likely failure mode of an oracle suite:
silently re-pinning the JSON to whatever the engine currently produces.
A drift in this document **must** be matched by a corresponding regeneration,
making the regeneration a deliberate, auditable act.
