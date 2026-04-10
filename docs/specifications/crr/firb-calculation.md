# Foundation IRB Specification

Foundation IRB calculation with supervisory LGD, PD floors, and correlation formulas.

**Regulatory Reference:** CRR Articles 153-154, 161-163

**Test Group:** CRR-B

---

## Requirements Status

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-1.3 | F-IRB capital requirement (K): PD, supervisory LGD, maturity adjustment | P0 | Done |
| FR-1.8 | Defaulted exposure treatment: F-IRB (K=0) | P0 | Done |

---

## Supervisory LGD Values (CRR Art. 161)

Under F-IRB, LGD is prescribed by the regulator based on collateral type:

### Art. 161(1) LGD Values

| Category | Supervisory LGD | Reference |
|----------|-----------------|-----------|
| Senior unsecured | 45% | Art. 161(1)(a) |
| Subordinated unsecured | 75% | Art. 161(1)(b) |
| Covered bonds (Art. 129(4)/(5) eligible) | 11.25% | Art. 161(1)(d) |
| Senior purchased corporate receivables | 45% | Art. 161(1)(e) |
| Subordinated purchased corporate receivables | 100% | Art. 161(1)(f) |
| Dilution risk of purchased corporate receivables | 75% | Art. 161(1)(g) |

Art. 161(1)(c) provides that institutions may recognise funded and unfunded credit protection
in the LGD in accordance with Chapter 4.

!!! info "Purchased Receivables (Art. 161(1)(e)–(g))"
    Art. 161(1)(e) and (f) apply where the institution **cannot estimate PD** for the purchased
    receivables pool (or estimates do not meet Section 6 requirements). When PD is estimable,
    the standard senior (45%) or subordinated (75%) LGD from (a)/(b) applies instead.
    Art. 161(1)(g) covers dilution risk — the risk that receivables amounts are reduced through
    credits or allowances to the obligor. It always applies to the dilution component regardless
    of PD estimation capability.

!!! warning "Not Yet Implemented — Purchased Receivables LGD"
    The code does not implement separate LGD paths for Art. 161(1)(e)/(f)/(g). Purchased
    receivables exposures currently receive the standard unsecured LGD (45% senior / 75%
    subordinated). The 100% subordinated purchased receivables LGD and the 75% dilution
    risk LGD are not applied. See D3.10.

### Art. 230 Table 5 LGDS Values (Foundation Collateral Method)

When exposures are secured by eligible collateral, the LGD* formula (Art. 230) uses the
following supervisory LGDS values for the secured portion:

| Collateral Type | LGDS (Senior) | LGDS (Subordinated) | C* | C** | Reference |
|----------------|---------------|---------------------|----|-----|-----------|
| Financial collateral | 0% | 0% | 0% | — | Art. 230 Table 5 |
| Receivables | 35% | 65% | 0% | 125% | Art. 230 Table 5 |
| Residential / commercial RE | 35% | 65% | 30% | 140% | Art. 230 Table 5 |
| Other physical collateral | 40% | 70% | 30% | 140% | Art. 230 Table 5 |

Where C\* is the minimum collateralisation threshold (below which the collateral is not
recognised) and C\*\* is the overcollateralisation level at which the full LGDS applies
to the entire exposure.

!!! info "Covered Bond LGD (Art. 161(1)(d))"
    CRR Art. 161(1)(d) provides a permissive ("may be assigned") 11.25% LGD for covered
    bonds eligible under Art. 129(4) or (5). Basel 3.1 restructures this into a separate paragraph
    Art. 161(1B) with the same 11.25% value. Covered bonds use the Art. 161 mechanism, not the
    Art. 230 Table 5 LGDS/overcollateralisation framework.

!!! warning "Art. 161 vs Art. 230 Distinction"
    Art. 161(1)(a)–(g) covers unsecured LGD, subordinated LGD, covered bonds, purchased
    receivables, and dilution risk. The per-collateral-type LGDS values (0%/35%/40%) for the
    **secured portion** of the LGD\* formula come from Art. 230 Table 5 (Foundation Collateral
    Method), not Art. 161. The Art. 230 LGDS subordinated column (65%/70%) applies when the
    underlying exposure is a subordinated claim — these are distinct from the Art. 161(1)(b)
    subordinated unsecured LGD of 75%.

### Basel 3.1 F-IRB LGD Changes (PRA PS1/26 Art. 161(1))

Under Basel 3.1, senior unsecured LGD is differentiated by whether the counterparty is a **financial sector entity (FSE)**:

#### Art. 161 LGD Comparison

| Category | CRR | Basel 3.1 | Reference |
|----------|-----|-----------|-----------|
| Senior unsecured (non-FSE) | 45% | **40%** | Art. 161(1)(a) → Art. 161(1)(aa) |
| Senior unsecured (FSE) | 45% | **45%** | Art. 161(1)(a) |
| Subordinated unsecured | 75% | 75% | Art. 161(1)(b) |
| Covered bonds | 11.25% | **11.25%** | Art. 161(1)(d) → Art. 161(1B) |
| Senior purchased receivables | 45% | **40%** | Art. 161(1)(e) |
| Subordinated purchased receivables | 100% | **100%** | Art. 161(1)(f) |
| Dilution risk | 75% | **100%** | Art. 161(1)(g) |

#### Art. 230 LGDS Comparison (Secured Portions)

| Collateral Type | CRR LGDS | Basel 3.1 LGDS | Reference |
|----------------|----------|----------------|-----------|
| Financial collateral | 0% | 0% | Art. 230 Table 5 / Art. 230(2) |
| Receivables | 35% | **20%** | Art. 230 Table 5 / CRE32.9 |
| Residential RE | 35% | **20%** | Art. 230 Table 5 / CRE32.10 |
| Commercial RE | 35% | **20%** | Art. 230 Table 5 / CRE32.11 |
| Other physical | 40% | **25%** | Art. 230 Table 5 / CRE32.12 |

!!! note "FSE Definition"
    Financial sector entity includes banks, building societies, investment firms, insurance
    companies, and any entity primarily engaged in financial intermediation. Under CRR this is
    Art. 4(1)(27); under Basel 3.1 Art. 4(1)(146) uses a total assets > EUR 70bn threshold for
    the "large FSE" correlation multiplier.

!!! info "Key B31 Changes to Purchased Receivables / Dilution"
    Basel 3.1 aligns the senior purchased receivables LGD with the new non-FSE rate (45% → 40%,
    Art. 161(1)(e)). The dilution risk LGD increases from 75% to **100%** (Art. 161(1)(g)),
    reflecting the PRA's view that dilution losses are not mitigated by collateral recovery.
    The subordinated purchased receivables LGD remains at 100% (Art. 161(1)(f)).

!!! info "B31 Art. 230 — Subordinated LGDS Distinction Removed"
    CRR Art. 230 Table 5 has separate "senior" and "subordinated" LGDS columns (e.g.,
    receivables 35%/65%). PRA PS1/26 Art. 230(2) replaces this with a single LGDS per
    collateral type (20%/20%/25%) with no subordinated distinction. The subordination effect
    is captured solely through the LGDU term (75% per Art. 161(1)(b)).

## PD Floor

**CRR:** Single floor of **0.03%** (3 basis points) for all non-defaulted exposure classes
(Art. 160(1) for corporate/sovereign/institution; Art. 163(1) for retail).

### Basel 3.1 PD Floors by Exposure Class (PRA PS1/26 Art. 160/163)

Under Basel 3.1, PD floors are differentiated by exposure class:

| Exposure Class | CRR PD Floor | Basel 3.1 PD Floor | Reference |
|---------------|-------------|--------------------|-----------| 
| Corporate / SME | 0.03% | **0.05%** | Art. 160(1) |
| Sovereign | 0.03% | 0.05% | Art. 160(1) |
| Institution | 0.03% | 0.05% | Art. 160(1) |
| Retail — mortgage | 0.03% | **0.10%** | Art. 163(1)(b) |
| Retail — QRRE (transactor) | 0.03% | **0.05%** | Art. 163(1)(c) |
| Retail — QRRE (revolver) | 0.03% | **0.10%** | Art. 163(1)(a) |
| Retail — other | 0.03% | **0.05%** | Art. 163(1)(c) |

!!! note "Sovereign/Institution PD Floors"
    Under Basel 3.1, sovereign and institution exposures retain a PD floor but are restricted under Art. 147A (sovereign = SA only, institution = FIRB only). PD floors are still relevant for any grandfathered or transitional IRB treatment.

See [Framework Differences](../../framework-comparison/technical-reference.md) for Basel 3.1 differentiated PD floors.

## Asset Correlation Formula (CRR Art. 153)

### Corporate, Institution, Sovereign

PD-dependent correlation with exponential decay factor of 50:

```
f(PD) = (1 - exp(-50 x PD)) / (1 - exp(-50))
R = 0.12 x f(PD) + 0.24 x (1 - f(PD))
```

### SME Firm-Size Adjustment

For corporates with turnover < EUR 50m, correlation is reduced:

**CRR (Art. 153(4)):**
```
s = max(5, min(turnover_EUR, 50))
adjustment = 0.04 x (1 - (s - 5) / 45)
R_adjusted = R - adjustment
```

Turnover is stored in GBP and converted to EUR via the configured FX rate (default: 0.8732).

**Basel 3.1 (PRA PS1/26):** Thresholds converted to GBP:

| Parameter | CRR (EUR) | Basel 3.1 (GBP) |
|-----------|----------|-----------------|
| SME threshold | EUR 50m | GBP 44m |
| Floor turnover | EUR 5m | GBP 4.4m |
| Adjustment range | 45 | 39.6 |

```
s = max(4.4, min(turnover_GBP, 44))
adjustment = 0.04 x (1 - (s - 4.4) / 39.6)
R_adjusted = R - adjustment
```

### Retail Mortgage

Fixed correlation: **R = 0.15**

### Qualifying Revolving Retail (QRRE)

Fixed correlation: **R = 0.04**

### Other Retail

PD-dependent correlation with exponential decay factor of 35:

```
f(PD) = (1 - exp(-35 x PD)) / (1 - exp(-35))
R = 0.03 x f(PD) + 0.16 x (1 - f(PD))
```

## FI Scalar (CRR Art. 153(2))

A **1.25x** multiplier applied to the **asset correlation coefficient** (R) for **large financial sector entities** (total assets ≥ EUR 70bn per CRR Art. 4(1)(146)) **and unregulated financial sector entities** (per CRR Art. 153(2)).

!!! warning "Two distinct thresholds — do not conflate"
    - **EUR 70bn total assets** (≈ GBP 79bn) → 1.25x correlation multiplier (Art. 153(2)). Applies to large FSEs and all unregulated FSEs under both CRR and Basel 3.1.
    - **GBP 440m annual revenue** → F-IRB only approach restriction (Art. 147A(1)(d), Basel 3.1 only). Does not affect correlation.
    - The Art. 147A(1)(e) F-IRB restriction applies to **all** FSEs regardless of size — it is separate from the correlation uplift which only applies to *large* or *unregulated* FSEs.

## Capital Requirement Formula

```
K = LGD x N[(1-R)^(-0.5) x G(PD) + (R/(1-R))^(0.5) x G(0.999)] - PD x LGD
```

Where:

- `N(x)` = cumulative normal distribution function
- `G(x)` = inverse normal CDF
- `G(0.999)` = 3.0902323061678132
- `K` is floored at 0

## Effective Maturity (CRR Art. 162)

Applied to non-retail exposures only (retail exposures use MA = 1.0).

### Art. 162(1) — F-IRB Fixed Supervisory Maturities

Institutions that have **not** received permission to use own LGDs and own conversion factors
(i.e. F-IRB firms) shall assign:

| Exposure Type | Supervisory Maturity | Reference |
|---------------|---------------------|-----------|
| Repo-style transactions (repos, securities/commodities lending or borrowing) | **0.5 years** | Art. 162(1) |
| All other exposures | **2.5 years** | Art. 162(1) |

!!! warning "0.5-Year Repo Maturity — Not Yet Implemented"
    The code uses a blanket 2.5-year default for all F-IRB exposures when no `maturity_date`
    is provided (`namespace.py:259`, `formulas.py:366`). The 0.5-year supervisory maturity for
    repo-style transactions is not applied. This overstates maturity (and therefore RWA) for
    F-IRB repo/SFT exposures that lack an explicit maturity date.

Alternatively, the competent authority may require the institution to calculate M for each
exposure using the A-IRB methods in Art. 162(2).

### Art. 162(2) — A-IRB Effective Maturity Calculation

Institutions permitted to use own LGDs and CCFs (A-IRB) must calculate M per exposure.
M shall not exceed 5 years (except under Art. 384(1) for CVA). Key methods:

| Method | Applies To | Formula / Rule | Minimum M |
|--------|-----------|----------------|-----------|
| (a) Cash-flow schedule | Instruments with known cash flows | `M = max(1, min(Σ(t × CF_t) / Σ(CF_t), 5))` | 1 year |
| (b) Derivatives (MNA) | Derivatives under master netting agreement | Notional-weighted average remaining maturity | 1 year |
| (c) Fully collateralised derivatives + margin lending (MNA) | Daily remargined **and** revalued (Annex II) | Weighted average remaining maturity | **10 days** |
| (d) Repo-style transactions (MNA) | Daily remargined **and** revalued repos/SFTs | Notional-weighted average remaining maturity | **5 days** |
| (e) Purchased corporate receivables | Drawn amounts (own PD permitted) | Exposure-weighted average maturity | **90 days** |
| (f) Other instruments | When (a) cannot be calculated | Max remaining time to discharge obligations | 1 year |
| (g) IMM netting sets | Longest-dated contract > 1 year | IMM formula with effective EE | 1 year |
| (j) Double-default protection | Art. 153(3) credit protection | Effective maturity of protection | 1 year |

### Art. 162(3) — One-Day Maturity Floor Exceptions

Where documentation requires **daily re-margining and daily revaluation** with provisions for
prompt liquidation or set-off of collateral, M shall be at least **one day** (overriding the
longer minimums in paragraph 2) for:

- (a) Fully/nearly-fully collateralised derivatives (Annex II)
- (b) Fully/nearly-fully collateralised margin lending
- (c) Repurchase transactions, securities or commodities lending or borrowing

The same one-day floor applies to **qualifying short-term exposures** not part of ongoing
financing, including:

- (a) FX settlement exposures to institutions
- (b) Self-liquidating short-term trade finance (residual maturity ≤ 1 year, Art. 4(1)(80))
- (c) Securities settlement within usual delivery period or 2 business days
- (d) Cash settlement/electronic payment exposures, including failed-transaction overdrafts

!!! info "Implementation Note — `has_one_day_maturity_floor` Flag"
    The code implements Art. 162(3) via a boolean flag `has_one_day_maturity_floor` on the
    input schema (`schemas.py:82,103,132`). However, this flag is currently used **only** for
    CRM maturity mismatch ineligibility (Art. 237(2) — any mismatch zeroes protection value
    for one-day-floor exposures). It does **not** currently override the IRB maturity column
    to 1/365. See `haircuts.py:482-485`.

### Art. 162(4) — SME Maturity Simplification

For exposures to **corporates situated in the UK** with consolidated sales and consolidated
assets < EUR 500 million, institutions may consistently apply the F-IRB fixed maturities
from Art. 162(1) instead of calculating per Art. 162(2). The EUR 500m threshold rises to
EUR 1,000m for corporates that primarily own and let non-speculative residential property.

!!! note "Not Yet Implemented"
    The code does not implement the Art. 162(4) SME maturity simplification. All A-IRB
    exposures calculate maturity from `maturity_date` or default to 2.5 years.

### Maturity Adjustment Formula

```
b = (0.11852 - 0.05478 x ln(PD))^2
MA = (1 + (M - 2.5) x b) / (1 - 1.5 x b)
```

Where M is clamped to the range [1.0, 5.0] years (per Art. 162(1)/(2) floor and cap).

### Basel 3.1 Changes to Art. 162

PRA PS1/26 makes significant changes to Art. 162:

| Aspect | CRR | Basel 3.1 | Reference |
|--------|-----|-----------|-----------|
| F-IRB fixed maturities (§1) | 0.5yr repo / 2.5yr other | **Deleted** — all IRB firms must calculate M | Art. 162(1) |
| Scope | A-IRB only (Art. 143 permission) | **F-IRB and A-IRB** (Art. 147A) | Art. 162(2) |
| Revolving exposures | Repayment date of current drawing | **Max contractual termination date** | Art. 162(2A)(k) |
| Mixed MNA (derivatives + repos) | Not addressed | **10-day floor** | Art. 162(2A)(da) |
| Purchased receivables minimum M | 90 days | **1 year** | Art. 162(2A)(e) |
| Collateral daily condition | Re-margining **and** revaluation | Re-margining **or** revaluation | Art. 162(2A)(c)/(d) |
| SME simplification (§4) | Available (EUR 500m threshold) | **Deleted** | Art. 162(4) |

See the [Basel 3.1 F-IRB specification](../../specifications/basel31/firb-calculation.md#effective-maturity-art-162)
for full details.

!!! warning "Previous Description Was Wrong"
    This section previously stated "unconditionally cancellable revolving facilities are assigned a maturity of 1 year". Art. 162(2A)(k) actually requires the **maximum contractual termination date** — not a 1-year default. Using 1 year instead of the facility termination date would systematically understate maturity and therefore RWA for revolving corporate exposures.

## RWA Calculation

**CRR Corporate/Institution (Art. 153):** `RWA = K x 12.5 x 1.06 x EAD x MA`

The 1.06 is the CRR scaling factor from Art. 153(3) (not present in Basel 3.1 — Art. 153(3)
is "[Provision left blank]" in PS1/26).

!!! note "Retail — No 1.06 Scaling"
    CRR Art. 154(1) retail formula does **not** include the 1.06 scaling factor. The 1.06 applies
    only to corporate and institution exposures under Art. 153. Retail RWA = K x 12.5 x EAD
    (with MA = 1.0 for retail).

## Expected Loss

```
EL = PD x LGD x EAD
```

Used for comparison against provisions (see [Provisions](provisions.md)).

## Key Scenarios

| Scenario ID | Description | Key Parameters |
|-------------|-------------|----------------|
| CRR-B1 | Corporate F-IRB, senior unsecured, low PD | PD=0.10%, LGD=45%, M=2.5y |
| CRR-B2 | Corporate F-IRB, senior unsecured, high PD | PD=5.00%, LGD=45%, M=2.5y |
| CRR-B3 | Subordinated debt — supervisory LGD 75% | PD=0.50%, LGD=75% (Art. 161(1)(b)) |
| CRR-B4 | Financial collateral — blended LGD | Collateral reduces effective LGD (Art. 161(1)(d)) |
| CRR-B5 | SME corporate with firm-size adjustment + supporting factor | Turnover < EUR 50m, correlation reduced (Art. 153(4)) |
| CRR-B6 | PD floor binding — input PD below 0.03% floor | Input PD=0.01% → floored to 0.03% (Art. 160(1)) |
| CRR-B7 | Long maturity — contractual 7Y capped to 5Y | M clamped to [1, 5] range (Art. 162(2)) |

!!! note "FI Scalar Coverage"
    The 1.25x correlation multiplier for large/unregulated FSEs (Art. 153(2)) is validated within CRR-B5 and through the B31-B group (B31-B7 specifically tests FSE LGD differentiation). See [FI Scalar](#fi-scalar-crr-art-1532) for details.

## Acceptance Tests

| Group | Scenarios | Tests | Pass Rate |
|-------|-----------|-------|-----------|
| CRR-B: Foundation IRB | B1–B7 | 13 | 100% (13/13) |
