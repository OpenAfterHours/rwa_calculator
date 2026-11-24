# Advanced IRB Specification

Basel 3.1 Advanced IRB changes: LGD floors, post-model adjustments (PMA),
CCF floor at 50% of SA, double default removal, and EL monotonicity.

**Regulatory Reference:** PRA PS1/26 Art. 153–154, 158(5), 161(5), 164(4), 166D, 178, CRE31–32
**Test Group:** B31-C

!!! info "Default Definition — Art. 178"
    A-IRB defaulted exposures consume a `beel` companion input (Art. 158(5) best
    estimate of expected loss) in addition to the `is_defaulted` flag. The Art. 178
    two-limb default trigger, UTP indicators, PS1/26 hardcoded materiality thresholds
    (retail GBP 0 / 0%; non-retail GBP 440 / 1%), DPD-counter suspensions, and the
    3-month cure / 1-year distressed-restructuring probation are documented in the
    shared [Default Definition (Art. 178) specification](../common/default-definition.md).

---

## Requirements Status

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-4.1 | Corporate A-IRB LGD floors (Art. 161(5)) | P0 | Done |
| FR-4.2 | Retail A-IRB LGD floors (Art. 164(4)) | P0 | Done |
| FR-4.3 | Post-model adjustments — RWA and EL scalars | P0 | Done |
| FR-4.4 | Mortgage risk weight floor (Art. 154(4A)(b)) | P0 | Done |
| FR-4.5 | PMA sequencing: three additive limbs on one base; floor tested after limb (a) (P1.325) | P0 | Done |
| FR-4.6 | A-IRB CCF floor at 50% of SA CCF (Art. 166D, CRE32.27) | P0 | Done |
| FR-4.7 | Double default treatment removal | P0 | Done |
| FR-4.8 | EL monotonicity under PMA (Art. 158(6A)) | P0 | Done |
| FR-4.9 | FI scalar (1.25× correlation) retained | P0 | Done |
| FR-4.10 | Full-facility EAD approach with floors (Art. 166D(3)–(5)) | P0 | Done |
| FR-4.11 | Expected drawdown incorporation in CCF (Art. 166D(2)) | P0 | Done |
| FR-4.12 | Unrecognised exposure adjustment scalar, Advanced IRB legs only (Art. 166D(6), P1.399) | P1 | Done |

---

## Overview

Basel 3.1 constrains A-IRB flexibility by introducing **LGD floors** that prevent internal
estimates from falling below supervisory minimums, and **post-model adjustments** (PMA) that
allow PRA to impose conservative overlays. The double default treatment is removed, replaced
by parameter substitution for IRB guarantors (see [CRM Specification](credit-risk-mitigation.md)).
For funded credit protection (collateral), A-IRB firms may use **LGD modelling** under
Art. 169A/169B or fall back to the **Foundation Collateral Method** (FCM, Art. 230) — see
[CRM Specification § LGD Modelling Collateral Method](../crr/credit-risk-mitigation.md#lgd-modelling-collateral-method-basel-31-art-169a169b).

### Key Differences from F-IRB

| Parameter | F-IRB | A-IRB CRR | A-IRB Basel 3.1 |
|-----------|-------|-----------|-----------------|
| PD | Internal (floored) | Internal (floored) | Internal (floored, higher floors) |
| LGD | Supervisory | Internal | Internal **(with floors)** |
| CCF | Supervisory (CRR) / SA-aligned (B31) | Internal | **Revolving only** (floor: 50% of SA); others use SA |
| Maturity | Default 2.5y | Internal (retail: no MA) | Internal (retail: no MA) |
| Double default | Available | Available | **Removed** |
| PMA | N/A | N/A | **New: RWA/EL scalars + mortgage floor** |

---

## LGD Floors (Basel 3.1 Only)

### Corporate A-IRB LGD Floors (Art. 161(5))

A-IRB firms must ensure their internal LGD estimates do not fall below these floors:

| Collateral Type | LGD Floor |
|----------------|-----------|
| Unsecured | **25%** |
| Financial collateral | **0%** |
| Receivables | **10%** |
| Residential RE | **10%** |
| Commercial RE | **10%** |
| Other physical | **15%** |

!!! note "No Senior/Subordinated Distinction"
    Unlike F-IRB supervisory LGD (which distinguishes senior 40% from subordinated 75%),
    the A-IRB LGD floor is a flat **25%** for all unsecured corporate exposures regardless
    of seniority. There is no 50% subordinated floor — this was a previous documentation
    error corrected in D1.5.

For partially secured exposures, the blended LGD floor is:

```
LGD_floor = (E_unsecured / EAD) x LGDU_floor + sum_i((E_i / EAD) x LGDS_floor_i)
```

!!! info "Interaction with CRM Methods"
    These LGD floors apply **after** any CRM adjustment. Under A-IRB, the LGD input may be
    determined by the firm's own LGD model incorporating collateral effects (Art. 169A/169B) or
    by the Foundation Collateral Method (Art. 230). Either way, the resulting LGD is then floored
    per the tables above. Art. 169B requires that the LGD Modelling Collateral Method produce
    estimates at least as conservative as the FCM. See
    [CRM Specification](../crr/credit-risk-mitigation.md#lgd-modelling-collateral-method-basel-31-art-169a169b)
    for the full method taxonomy and requirements.

### Retail A-IRB LGD Floors (Art. 164(4))

| Retail Sub-Class | Collateral | LGD Floor |
|-----------------|------------|-----------|
| Residential RE mortgage | RE secured | **5%** |
| QRRE (transactor and revolver) | Unsecured | **50%** |
| Other retail | Unsecured | **30%** |
| Other retail | Receivables | **10%** |
| Other retail | Residential RE | **10%** |
| Other retail | Commercial RE | **10%** |
| Other retail | Other physical | **15%** |
| Other retail | Financial | **0%** |

### Retail Secured Only on Commercial Property (P1.324)

The engine's `retail_mortgage` class holds every retail exposure secured by immovable
property, commercial as well as residential. That is right for the treatments that read
*any* immovable property — R = 0.15 under Art. 154(3) ("retail exposures secured by
immovable property collateral"), the CRR Art. 164(4) 15% commercial LGD bucket, and the
OF 08.01 "Retail – Secured by commercial immovable property" sheets 0018 / 0019. But
Art. 147(5B) puts only "retail exposures secured by residential immovable property" in the
(d)(ii) subclass, and Art. 147(5C) sends every other retail exposure to (d)(iii) other
retail. Three Basel 3.1 treatments name residential security, so a `retail_mortgage` leg
secured **only on commercial property** takes the other-retail value of each:

| Treatment | Residential-secured `retail_mortgage` | Commercial-only `retail_mortgage` |
|-----------|---------------------------------------|-----------------------------------|
| PD floor, Art. 163(1) | (b) `retail_mortgage` floor | (c) `retail_other` floor |
| LGD floor, Art. 164(4) | (a) flat `retail_rre` floor | (c) LGD\* blend over every recognised collateral type (LGDU `retail_lgdu`; LGDS `financial_collateral`, `receivables`, `commercial_real_estate` for immovable property, `other_physical`); (b)(ii) `retail_other_unsecured` with no recognised collateral |
| RWEA floor, Art. 154(4A)(b) | `mortgage_rw_floor` add-on | none |

"Commercial-only" is `engine/irb/formulas.py::commercial_only_property_security_expr`:
positive commercial evidence (`property_type == "commercial"`) and **no residential
evidence on any of three carriers**:

- `re_collateral_may_be_residential` is False. The hierarchy stage
  (`engine/hierarchy/enrich.py::enrich_with_residential_security`) sets it wherever real
  estate that is, or may be, residential reaches the exposure on a route the CRM allocates
  collateral on: pledged directly, at the parent or **any ancestor** facility (the CRM's
  facility cascade), at the obligor, or through the M:N `collateral_links` table. A row is
  residential when `property_type` is `residential` or its `collateral_type` is a
  residential synonym (`RESIDENTIAL_REAL_ESTATE_COLLATERAL_TYPES`, e.g.
  `residential_property`); real estate of any recognised spelling not reported as
  `commercial` (an ADC or unreported type) counts as possibly residential. The flag records
  presence, not recognition, is never weighted and does not depend on row order;
- `residential_collateral_value_uncapped` is not positive;
- `is_uk_residential_mortgage_commitment` is not True (the firm's own attestation, which the
  CCF stage reads for Table A1 row 4(b)).

So a house behind a facility's undrawn row (drawn-basis residential value 0), behind a mixed
house-and-shop security whose keep-first `property_type` reads "commercial", behind a link,
behind a root-facility pledge, or typed with a synonym keeps the residential treatment. Any
null also leaves a row on it, so the predicate moves only a row it can show to be
commercial-only. CRR is unchanged: one flat Art. 163(1) PD floor, no A-IRB LGD input
floor and no post-model adjustments.

The first two limbs only release capital. The LGD limb moves it **either way**, because
the (c) blend is not bounded below by the (a) flat floor it replaces: Art. 164(4)(c)(iv)
gives financial collateral a 0% LGDS. Measured with `apply_lgd_floor`, EAD 100,000, own
LGD 3%: commercial cover of 40,000 alone gives 0.22 (was 0.05); 60,000 cash plus 40,000
property gives 0.04, and 80,000 cash plus 20,000 property or 95,000 cash gives the own
estimate 0.03 (each was 0.05). With own LGD 1% and 95,000 cash the floor is the blend
itself, 0.015.

The UK-location limb of Art. 154(4A)(b) and 163(1)(b) is still not implementable — no
property-country carrier reaches the IRB branch (P1.337).

!!! warning "Known residual — capital understatement, not fixed by P1.324"
    The positive commercial evidence is `property_type` alone, and the hierarchy leaves it
    null when the shop reaches the exposure only through `collateral_links`, through a
    non-parent ancestor facility, through a `contingent` beneficiary
    (`add_collateral_ltv` reads direct pledges to `exposure` / `loan` only), or under a
    commercial `collateral_type` synonym. Such a commercial-only `retail_mortgage` leg stays
    on the residential limbs. That is **not** conservative. With own LGD 3%, 40%
    commercial cover and R = 0.15, the risk weight the residential limbs give against the
    correct other-retail one is 10.00% vs 11.90% at PD 0.30%, 10.00% vs 27.57% at PD 1%,
    and 12.44% vs 54.75% at PD 3%. Only below a PD of about 0.24% do the residential limbs
    give the higher figure. Recorded for a follow-up item.

!!! note "Scope of Corporate vs Retail Floors"
    Corporate LGD floors (Art. 161(5)) and retail LGD floors (Art. 164(4)) are separate
    regulatory provisions. Institution exposures are restricted to **F-IRB only** under
    Art. 147A(1)(b), so A-IRB LGD floors do not apply to institutions. Sovereign exposures
    are restricted to **SA only** under Art. 147A(1)(a), so sovereign A-IRB LGD floors
    are moot. All financial sector entities (together with large corporates) are restricted
    to **F-IRB only** under Art. 147A(1)(e).

---

## Post-Model Adjustments (Art. 146(3), 154(4A), 158(6A))

Art. 153(5A) (corporates and institutions) and Art. 154(4A) (retail) require a firm to
increase the RWEA its models produce by post-model adjustments. The engine applies them in
`engine/irb/adjustments.py::apply_post_model_adjustments`, on formula-IRB legs only (the
slotting calculator applies none), and only under Basel 3.1 — the `post_model_adjustments`
pack Feature is off under CRR, which has no such framework.

### Adjustment Sequencing (Art. 153(5A) / Art. 154(4A))

The chapeau of Art. 154(4A) — "An institution shall increase the total risk-weighted
exposure amounts calculated under paragraphs 1, 3 and 4 ... to reflect: (a) ... (b) ...
(c) ..." — makes the limbs **three additive increases to one modelled base**, not a chain
(Art. 153(5A) has the same shape for corporates and institutions, with limbs (a) and (b)):

```
base = modelled RWEA (Art. 154(1)/(3)/(4) retail; Art. 153(1)/(2)/(4) others)
(a) general PMA              = base x pma_rwa_scalar
(b) mortgage floor shortfall = max(0, mortgage_rw_floor x EAD - (base + (a)))
(c) unrecognised exposure    = base x unrecognised_exposure_scalar   (A-IRB legs only)
RWEA = base + (a) + (b) + (c)
```

Each is sealed on the leg (`post_model_adjustment_rwa`, `mortgage_rw_floor_adjustment`,
`unrecognised_exposure_adjustment`, with `rwa_pre_adjustments` the base), so OF 08.01
column 0260 is columns 0251 + 0252 + 0253 + 0254 on every sheet.

### General PMA Scalar (Art. 146(3) / Art. 158(6A))

Limb (a), and its EL twin, are firm elections on `PostModelAdjustmentConfig`:

```
post_model_adjustment_rwa = base x pma_rwa_scalar
post_model_adjustment_el  = max(0, EL x pma_el_scalar)
```

Limb (a) reaches every formula-IRB leg, F-IRB included: it is an Art. 146(3) amount on the
firm's rating systems, which an F-IRB leg has (its PD).

### Mortgage Risk Weight Floor (Art. 154(4A)(b))

Limb (b) is a **test**, not a value in a chain: "any amount needed to ensure that
risk-weighted exposure amounts for non-defaulted exposures which are retail exposures
secured by UK residential immovable property are greater than or equal to 10% of the
exposure value ... (following application of any post model adjustments calculated under
point (b) of Article 146(3))". The parenthetical puts limb (a) inside the comparison and
nothing else. The floor is the pack scalar `mortgage_rw_floor`. It reaches non-defaulted
`retail_mortgage` legs except those secured only on commercial property (see
[Retail Secured Only on Commercial Property](#retail-secured-only-on-commercial-property-p1324)).

!!! note "Sequencing corrected (P1.325)"
    An earlier revision of this page said the floor is applied first and both scalars
    multiply the floored amount. The article says the reverse: (a) and (c) multiply the
    modelled base, and (c) sits outside the floor test because it is "calculated under
    Article 166D(6)", not under Article 146(3)(b). Correcting it released capital where the
    floor binds.

### Unrecognised Exposure Adjustment (Art. 153(5A)(b) / 154(4A)(c) / 166D(6))

Limb (c) is Art. 166D(6)'s adjustment. Art. 166D(6)(a) has a firm "assess EADs arising
from facilities or relationships that were not captured in exposure values prior to the
amount being drawn, in cases where: (i) they are not captured in exposure values because
the facilities or relationships were not intended to result in credit exposures; and (ii)
the institution would have applied the Advanced IRB Approach in accordance with Article
147A in respect of the facilities or relationships had they been captured in exposure
values." Where material, 166D(6)(b) has it "quantify an unrecognised exposure adjustment
that reflects the risk-weighted exposure amounts that would be required" and "allocate the
total value ... to exposure classes and exposure subclasses on a best-efforts basis".

The engine cannot identify uncaptured facilities, so it takes the firm's quantification as
an election — `PostModelAdjustmentConfig.unrecognised_exposure_scalar`, default 0.0 — and
allocates it pro rata to modelled RWEA, on **Advanced IRB legs only** (the sealed
`approach` column is `advanced_irb`). Limb (ii) confines the adjustment to facilities the
firm would have treated under the Advanced IRB Approach, and Annex II p.112 accordingly says
column 0254 "shall not be reported for sheets relating to the FIRB approach or the slotting
approach". An F-IRB leg's `unrecognised_exposure_adjustment` is 0.0 whatever the scalar.

!!! warning "Fixed 2026-11-17 (P1.399)"
    Until this date the scalar was multiplied into every formula-IRB leg's RWEA, F-IRB
    included — an overstatement of F-IRB RWEA wherever a non-zero scalar was configured.
    Since OF 08.01 / 08.02 report no column 0254 on F-IRB and slotting sheets, it also left
    an F-IRB sheet's column 0260 above columns 0251-0254 and failed the Bank's Error rule
    `boe_b0751`. At the default 0.0 nothing moved. Held by
    `tests/unit/irb/test_p1_399_unrecognised_exposure_airb_only.py` and, on a filed return,
    `tests/acceptance/reporting/test_of08_01_unrecognised_exposure_scalar.py`.

### EL Monotonicity (Art. 158(6A))

PMA application must satisfy:

```
EL_adjusted >= EL_unadjusted
```

EL must never decrease as a result of post-model adjustments. This prevents conservative
RWA overlays from inadvertently reducing expected loss estimates, which would distort the
EL shortfall/excess comparison (Art. 159).

---

## A-IRB CCF Restrictions (Art. 166D)

Under Basel 3.1, A-IRB own-estimate CCFs are **restricted to revolving facilities only**
(Art. 166D(1)(a)). All other off-balance sheet items must use SA CCFs from
[Table A1](../crr/credit-conversion-factors.md) (Art. 166D(1)(b)).

### Revolving Facility Eligibility (Art. 166D(1)(a))

Own-estimate CCFs are permitted only where **all** conditions are met:

1. The row arises from a **revolving** facility — `is_revolving = True`
2. The row is a **commitment**, not an issued item — `is_obs_commitment = True`
   (the facility default; a contingent defaults to `False`). The PS1/26 glossary
   defines a commitment as an arrangement "which is not itself an issued off-balance
   sheet item", so a letter of credit or guarantee booked under a revolving facility
   — which inherits the facility's `is_revolving` — is not a revolving loan
   commitment and takes the SA factor under Art. 166D(1)(b) whatever its
   `ccf_modelled` (CM-03). A null `is_obs_commitment` cannot evidence a commitment.
3. The row's SA CCF (per Art. 111 Table A1) is **less than 100%**

A revolving purchased-receivables commitment flagged
`is_purchased_receivable_commitment` takes the fixed PS1/26 Art. 166A(5) 40% (10% for
an unconditionally cancellable one) on every IRB approach — never an own estimate
(see the [CCF specification](../crr/credit-conversion-factors.md#purchased-receivables-art-166a5)).

!!! warning "Table A1 Row 2 Carve-Out"
    Revolving facilities classified at **100% SA CCF** under Table A1 Row 2
    (factoring facilities, repos, forward asset purchases, partly-paid shares)
    **cannot use own-estimate CCFs** even though they are revolving. These always
    receive the full 100% SA CCF. The 100% reflects certain-drawdown commitments
    where the full nominal is economically equivalent to on-balance sheet exposure —
    there is no estimation benefit.

Non-revolving A-IRB facilities (term loans, non-revolving commitments, guarantees, etc.)
must use SA CCFs from Table A1 regardless of the firm's A-IRB permission. The
`is_revolving` flag in the input data controls this routing in the calculator.

!!! info "Definition: Revolving Loan Commitment (PRA PS1/26 Art. 1.3)"
    A commitment arising from a revolving loan facility — including credit cards, charge
    cards, and overdrafts — that lets a borrower decide how often to draw and at what
    intervals. Facilities allowing prepayments and subsequent redraws are considered
    revolving.

### CCF Floor (Art. 166D(5)(a) / CRE32.27)

For eligible revolving facilities, the own-estimate CCF is subject to a floor:

```
CCF_applied = max(CCF_modelled, 0.50 × CCF_SA)
```

The A-IRB CCF must be at least **50% of the corresponding SA CCF** (Art. 166D(5)(a)).

### Expected Drawdown Incorporation (Art. 166D(2))

Where both an on-balance sheet item and a revolving loan commitment relate to the same
facility, the firm's own CCF estimate must incorporate any **expected increase in the
on-balance sheet value** at the point of default. This means the CCF applied to the
undrawn portion should already account for the likelihood that the drawn balance will
increase before default — the CCF is not applied to a static snapshot of the current
undrawn amount.

### Full-Facility EAD Approach (Art. 166D(3)/(4))

As an alternative to the standard CCF approach (drawn + undrawn × CCF), A-IRB firms
**may** estimate a single facility-level EAD that combines both on-balance sheet and
off-balance sheet components into one figure. This "full-facility EAD" replaces the
separate drawn/undrawn decomposition.

The approach has two variants depending on the facility's drawdown state:

#### Partially or Fully Undrawn Facilities (Art. 166D(3))

For revolving facilities that are partially drawn or fully undrawn, the firm assigns
a **single EAD estimate** to the entire facility. This replaces both:

- The exposure value of any related on-balance sheet item (Art. 166A(2))
- The exposure value of the revolving loan commitment (Art. 166D(1))

The single EAD must be the firm's own estimate provided in accordance with Section 6
(model validation requirements).

#### Fully Drawn Facilities (Art. 166D(4))

For revolving facilities that are currently **fully drawn** (no undrawn commitment
remains), the firm assigns an own EAD estimate that replaces the on-balance sheet
accounting value. This recognises that a revolving facility's exposure can exceed
its current drawn balance — the borrower may repay and redraw, and the facility
limit itself may fluctuate.

!!! info "Why Full-Facility EAD Matters"
    The standard CCF approach (drawn + undrawn × CCF) assumes a fixed split between
    drawn and undrawn amounts. For revolving facilities, this split is volatile — a
    borrower can repay and redraw repeatedly. The full-facility approach lets the model
    estimate total exposure at default directly, capturing drawdown dynamics that a
    static CCF may miss. This is particularly relevant for credit cards, overdrafts,
    and revolving credit lines where utilisation patterns drive EAD.

#### Input Field: `ead_modelled`

To use the full-facility approach, provide the `ead_modelled` field (type: `Float64`,
nullable) on the facility or contingent input record:

- **When present (non-null) on a revolving loan commitment:** The calculator uses
  this as the facility-level EAD, subject to the floors below. Art. 166D(3)/(4)
  reach "revolving loan facilities" only, so the row must be revolving
  (`is_revolving`) and a commitment (`is_obs_commitment` — an issued item is
  never one), and not a flagged revolving purchased-receivables commitment
  (Art. 166A(5) fixes its 40% / 10%). On any other row `ead_modelled` is ignored
  and the row keeps its Art. 166D(1)(b) SA factor (or its Art. 166A(5) factor)
- **When absent or null:** The calculator falls back to the standard CCF-based
  EAD calculation (drawn + undrawn × CCF)

The field is propagated through the pipeline via `FACILITY_SCHEMA` →
`RAW_EXPOSURE_SCHEMA` → `RESOLVED_HIERARCHY_SCHEMA` → `CLASSIFIED_EXPOSURE_SCHEMA`.
For drawn loans without a facility commitment, `ead_modelled` is set to null
(full-facility EAD is not applicable).

### EAD Floors (Art. 166D(5))

Art. 166D(5) specifies three separate floor tests ensuring A-IRB EAD estimates
do not fall below prudent minimums. Each floor maps to a specific EAD approach:

| Floor | Applies To | Formula | Reference |
|-------|-----------|---------|-----------|
| (a) CCF floor | Own-estimate CCFs (para 1(a)) | `CCF ≥ 50% × CCF_SA` | Art. 166D(5)(a) |
| (b) Facility EAD floor | Full-facility EAD for partially/fully undrawn (para 3) | `EAD ≥ EAD_on_BS + 50% × EAD_off_BS_FIRB` | Art. 166D(5)(b) |
| (c) Fully-drawn floor | Full-facility EAD for fully drawn (para 4) | `EAD ≥ EAD_on_BS` | Art. 166D(5)(c) |

#### Floor (a): CCF Floor

See [CCF Floor](#ccf-floor-art-166d5a--cre3227) above. The modelled CCF must be
at least 50% of the SA CCF for the same commitment type.

#### Floor (b): Facility-Level EAD Floor (Art. 166D(5)(b))

When using the full-facility approach for partially or fully undrawn facilities
(Art. 166D(3)), the modelled EAD must not be lower than:

```
EAD_floor_b = EAD_on_BS + 50% × EAD_off_BS_FIRB
```

Where:

- **`EAD_on_BS`** = exposure value of the on-balance sheet item calculated per
  Art. 166A(2), disregarding Art. 166D (i.e., the drawn balance as it would be
  calculated without the full-facility approach)
- **`EAD_off_BS_FIRB`** = exposure value of the off-balance sheet item under the
  **Foundation IRB Approach** per Art. 166C(1) (i.e., undrawn nominal × SA CCF,
  since F-IRB CCFs are aligned to SA under Basel 3.1)

The 50% factor on the off-balance sheet component mirrors the 50%-of-SA-CCF floor
in floor (a) — both enforce a minimum credit conversion of half the SA rate.

**Implementation:**

```
floor_b = on_balance_sheet_ead + nominal_after_provision × sa_ccf × 0.5
ead_pre_crm = max(ead_modelled, floor_b)
```

#### Floor (c): Fully-Drawn EAD Floor (Art. 166D(5)(c))

When using the full-facility approach for fully drawn facilities (Art. 166D(4)),
the modelled EAD must not be lower than the on-balance sheet exposure value:

```
EAD_floor_c = EAD_on_BS
```

Where **`EAD_on_BS`** is calculated per Art. 166A(2), disregarding Art. 166D.
This prevents the modelled EAD from falling below what the firm currently has
on its balance sheet — the model may estimate higher EAD (reflecting potential
redraw risk), but never lower.

**Implementation:**

```
ead_pre_crm = max(ead_modelled, on_balance_sheet_ead)
```

!!! note "Floor Interaction"
    When `ead_modelled` is provided, both floor (b) and floor (c) are evaluated
    and the binding floor is the higher of the two. In practice, floor (b) is
    typically binding for partially-drawn facilities (where there is material
    undrawn commitment), while floor (c) is binding for fully-drawn facilities
    (where the undrawn component is zero, making floor (b) collapse to just
    the on-balance sheet value).

### Unrecognised Exposure Adjustment (Art. 166D(6))

A-IRB firms must assess EADs arising from facilities or relationships that were
**not captured in exposure values** prior to drawdown — for example, where a
credit exposure materialises from a facility not originally intended to create
credit risk. Where such amounts are material, the firm must quantify an
**unrecognised exposure adjustment** reflecting the additional RWA required.
This adjustment is allocated to exposure classes on a best-efforts basis.

The calculator cannot identify the uncaptured facilities themselves — that is
institution-specific judgement — so it takes the firm's quantification as a scalar
election and adds it to Advanced IRB legs only — see "Unrecognised Exposure
Adjustment" under Post-Model Adjustments above.

See also the [CCF specification](../crr/credit-conversion-factors.md#basel-31-a-irb-changes-pra-ps126-art-166d--cre3227)
for context on how the A-IRB CCF regime fits within the broader CCF framework.

---

## Double Default Removal

Under CRR, the double default treatment (Art. 153(3) / Art. 202–203) allowed firms to
recognise the joint probability of both obligor and guarantor defaulting:

```
K_dd = K_obligor x (0.15 + 160 x PD_guarantor)  [CRR only]
```

Basel 3.1 **removes double default entirely** — Art. 153(3) is "[Provision left blank]" in
PRA PS1/26. For guaranteed exposures under IRB, firms must use **parameter substitution**
instead — see [CRM Specification](credit-risk-mitigation.md).

---

## Capital Formula

The A-IRB capital formula is identical to F-IRB (see [F-IRB Specification](firb-calculation.md)):

```
K = LGD x N[(1-R)^(-0.5) x G(PD) + (R/(1-R))^(0.5) x G(0.999)] - PD x LGD
RW = K x 12.5 x MA
```

The differences are:

- `LGD` = firm's own estimate, subject to LGD floors (above) and CRM adjustments ([Art. 169A/169B](../crr/credit-risk-mitigation.md#lgd-modelling-collateral-method-basel-31-art-169a169b) or FCM)
- `PD` = firm's own estimate, subject to the same PD floors as F-IRB
- `MA` = 1.0 for retail (no maturity adjustment); internal estimate for non-retail
- Scaling factor = 1.0 (removed under Basel 3.1)
- FI scalar = 1.25× correlation for large/unregulated FSEs (retained)

---

## Key Scenarios

| Scenario ID | Description | Key Feature |
|-------------|-------------|-------------|
| B31-C1 | Corporate A-IRB: LGD floor binding (internal LGD < 25%) | LGD floored to 25% |
| B31-C2 | Retail other: LGD floor 30% unsecured, own LGD preserved when above | Floor non-binding |
| B31-C3 | Specialised lending A-IRB routing over slotting | A-IRB takes priority when permitted |

## Acceptance Tests

| Group | Scenarios | Tests | Pass Rate |
|-------|-----------|-------|-----------|
| B31-C: Advanced IRB | C1–C3 | 13 | 100% (13/13) |
