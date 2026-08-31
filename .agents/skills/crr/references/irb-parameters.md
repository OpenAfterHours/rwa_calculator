# CRR IRB Parameters

**Regulatory Reference:** CRR Articles 153-154, 161-163

> Regulatory **parameters** (LGDs, floors, thresholds) are generated from the rulepack —
> see the tables below. Regenerate with
> `uv run python scripts/generate_regulatory_tables.py`.
>
> The **formulas** on this page are a different thing: their coefficients are invariant
> mathematical constants of the Basel risk-weight function, not regime parameters, so
> they live in `src/rwa_calc/engine/irb/` rather than in the pack. They are reproduced
> here because a hand-calc needs them.

---

## Supervisory LGD and collateral parameters

`firb_supervisory_lgd` is the Art. 161 decision table keyed by seniority and collateral
type. Under the Foundation Collateral Method the secured portion's LGD is replaced by the
collateral-specific value (Art. 230 Table 5), subject to `overcollateralisation_ratios`
and `min_collateralisation_thresholds`.

Under CRR, A-IRB has **no LGD floors at all** — Basel 3.1 introduces them. The retail
portfolio-level RE floors (`retail_*_re_portfolio_lgd_floor`) are a separate, CRR-era
constraint applied at portfolio rather than exposure level, gated by
`crr_retail_re_portfolio_lgd_floor`.

<!-- BEGIN GENERATED: crr-irb-parameters -->
### `pd_floors`

**CRR** — CRR Art. 160(1)
 *(0.03% IRB PD floor for corporates and institutions only (retail floored separately by Art. 163(1); no CGCB floor))*

| Parameter | Value |
|---|---|
| `corporate` | `0.0003` |
| `corporate_sme` | `0.0003` |
| `sovereign` | `0` |
| `institution` | `0.0003` |
| `retail_mortgage` | `0.0003` |
| `retail_other` | `0.0003` |
| `retail_qrre_transactor` | `0.0003` |
| `retail_qrre_revolver` | `0.0003` |

**Basel 3.1** — PS1/26, paragraph 160
 *((1) differentiated IRB PD floors (Art. 160(1) wholesale / 163(1) retail))*

| Parameter | Value |
|---|---|
| `corporate` | `0.0005` |
| `corporate_sme` | `0.0005` |
| `sovereign` | `0.0005` |
| `institution` | `0.0005` |
| `retail_mortgage` | `0.0010` |
| `retail_other` | `0.0005` |
| `retail_qrre_transactor` | `0.0005` |
| `retail_qrre_revolver` | `0.0010` |

### `lgd_floors`

**CRR** — CRR Art. 164
 *(no A-IRB own-estimate LGD floor under CRR (all zero))*

| Parameter | Value |
|---|---|
| `unsecured` | `0.0` |
| `subordinated_unsecured` | `0.0` |
| `financial_collateral` | `0.0` |
| `receivables` | `0.0` |
| `commercial_real_estate` | `0.0` |
| `residential_real_estate` | `0.0` |
| `other_physical` | `0.0` |
| `retail_rre` | `0.0` |
| `retail_qrre_unsecured` | `0.0` |
| `retail_other_unsecured` | `0.0` |
| `retail_lgdu` | `0.0` |

**Basel 3.1** — PS1/26, paragraph 161
 *((5) A-IRB LGD floors (Art. 161(5) corporate / 164(4) retail))*

| Parameter | Value |
|---|---|
| `unsecured` | `0.25` |
| `subordinated_unsecured` | `0.50` |
| `financial_collateral` | `0.0` |
| `receivables` | `0.10` |
| `commercial_real_estate` | `0.10` |
| `residential_real_estate` | `0.10` |
| `other_physical` | `0.15` |
| `retail_rre` | `0.05` |
| `retail_qrre_unsecured` | `0.50` |
| `retail_other_unsecured` | `0.30` |
| `retail_lgdu` | `0.30` |

### `firb_supervisory_lgd`

**CRR** — CRR Art. 161
 *(F-IRB supervisory LGD (Art. 161 / Art. 230 Table 5))*

Keys: `collateral_type` , `seniority` , `is_fse`

| Keys | Value |
|---|---|
| `unsecured`, `senior`, `False` | `0.45` |
| `unsecured`, `senior`, `True` | `0.45` |
| `unsecured`, `subordinated`, `False` | `0.75` |
| `covered_bond`, `senior`, `False` | `0.1125` |
| `financial_collateral`, `senior`, `False` | `0.00` |
| `financial_collateral`, `subordinated`, `False` | `0.00` |
| `receivables`, `senior`, `False` | `0.35` |
| `receivables`, `subordinated`, `False` | `0.65` |
| `residential_re`, `senior`, `False` | `0.35` |
| `residential_re`, `subordinated`, `False` | `0.65` |
| `commercial_re`, `senior`, `False` | `0.35` |
| `commercial_re`, `subordinated`, `False` | `0.65` |
| `other_physical`, `senior`, `False` | `0.40` |
| `other_physical`, `subordinated`, `False` | `0.70` |
| `purchased_receivables`, `senior`, `False` | `0.45` |
| `purchased_receivables`, `subordinated`, `False` | `1.00` |
| `purchased_receivables`, `dilution_risk`, `False` | `0.75` |
| `life_insurance`, `senior`, `False` | `0.40` |

**Basel 3.1** — PS1/26, paragraph 161
 *(Basel 3.1 F-IRB supervisory LGD (CRE32.9-12))*

Keys: `collateral_type` , `seniority` , `is_fse`

| Keys | Value |
|---|---|
| `unsecured`, `senior`, `False` | `0.40` |
| `unsecured`, `senior`, `True` | `0.45` |
| `unsecured`, `subordinated`, `False` | `0.75` |
| `covered_bond`, `senior`, `False` | `0.1125` |
| `financial_collateral`, `senior`, `False` | `0.00` |
| `receivables`, `senior`, `False` | `0.20` |
| `residential_re`, `senior`, `False` | `0.20` |
| `commercial_re`, `senior`, `False` | `0.20` |
| `other_physical`, `senior`, `False` | `0.25` |
| `purchased_receivables`, `senior`, `False` | `0.40` |
| `purchased_receivables`, `subordinated`, `False` | `1.00` |
| `purchased_receivables`, `dilution_risk`, `False` | `1.00` |
| `life_insurance`, `senior`, `False` | `0.40` |

| Name | CRR | Basel 3.1 | Citation |
|---|---|---|---|
| `irb_scaling_factor` | `1.06` | `1.0` | CRR Art. 153(1) / PS1/26, paragraph 153 |
| `irb_correlation_sme_gbp_native` | off | on | CRR Art. 153(4) / PS1/26, paragraph 153 |
| `crr_retail_re_portfolio_lgd_floor` | on | off | CRR Art. 164 / PS1/26, paragraph 164 |
| `retail_residential_re_portfolio_lgd_floor` | `0.10` | — | CRR Art. 164 |
| `retail_commercial_re_portfolio_lgd_floor` | `0.15` | — | CRR Art. 164 |
| `double_default_treatment` | on | off | CRR Art. 153(3) / PS1/26, paragraph 153 |
| `crr_non_named_mdb_institution_irb_class` | on | off | CRR Art. 147 / PS1/26, paragraph 147 |
<!-- END GENERATED: crr-irb-parameters -->

## PD Floor — scope matters more than the value (Art. 160(1), 163(1))

CRR applies a single uniform PD floor, but **only to the classes the two articles
reach**:

- **Art. 160(1)** — "The PD of an exposure to a **corporate or an institution** shall be
  at least 0,03 %."
- **Art. 163(1)** — retail: "The PD of an exposure shall be at least 0,03 %."
- **Central governments and central banks have NO floor.** Neither article has a CGCB
  limb, so a CRR sovereign IRB exposure keeps its modelled PD however low. Under
  Art. 161(3) a central-government *guarantor*'s substituted PD is likewise unfloored,
  because the benchmark is "a comparable, direct exposure to the guarantor".

Basel 3.1 introduces differentiated floors **and does floor sovereigns** — see the
`basel31` skill. The floor values themselves are in the `pd_floors` bundle above.

## Asset Correlation Formulas (Art. 153)

### Corporate, Institution, Sovereign

```
f(PD) = (1 - exp(-50 x PD)) / (1 - exp(-50))
R     = 0.12 x f(PD) + 0.24 x (1 - f(PD))
```

R ranges from 0.12 at high PD to 0.24 at low PD.

### SME Firm-Size Adjustment

```
s          = max(5, min(turnover_millions, 50))
adjustment = 0.04 x (1 - (s - 5) / 45)
R_adjusted = R - adjustment
```

Maximum reduction of 0.04, reached at the lower turnover bound.
`irb_correlation_sme_gbp_native` records whether the turnover test is applied in GBP
natively or converted — a UK-specific detail that changes which exposures qualify.

### Retail

```
Retail mortgage:  R = 0.15                    (fixed)
QRRE:             R = 0.04                    (fixed)
Other retail:     f(PD) = (1 - exp(-35 x PD)) / (1 - exp(-35))
                  R = 0.03 x f(PD) + 0.16 x (1 - f(PD))
```

### FI Scalar (Art. 153(2))

A 1.25x multiplier on R for large or unregulated financial sector entities, applied
before K. Unchanged under Basel 3.1.

## Capital Requirement and RWA (Art. 153)

```
K   = LGD x N[(1-R)^-0.5 x G(PD) + (R/(1-R))^0.5 x G(0.999)] - PD x LGD
RWA = K x 12.5 x EAD x MA x irb_scaling_factor
EL  = PD x LGD x EAD
```

N is the normal CDF and G the inverse normal CDF, with G(0.999) = 3.0902323. K is floored
at zero. `irb_scaling_factor` is a **pack entry** — it is the CRR-era 1.06 uplift and
moves to unity under Basel 3.1, so write the name rather than the number.

## Maturity Adjustment (Art. 162)

Non-retail only; retail takes MA = 1.0.

```
b  = (0.11852 - 0.05478 x ln(PD))^2
MA = (1 + (M - 2.5) x b) / (1 - 1.5 x b)
```

M is clamped to the Art. 162 floor and cap. Note the **separate, shorter floors** for
repo/SFT and collateralised-derivative exposures, and the one-day floor — these are pack
entries and override the general floor.

<!-- BEGIN GENERATED: crr-irb-maturity -->
| Name | CRR | Basel 3.1 | Citation |
|---|---|---|---|
| `firb_fixed_supervisory_maturity` | on | off | CRR Art. 162(1) / PS1/26, paragraph 162 |
| `firb_fixed_supervisory_maturity_years` | `2.5` | `2.5` | CRR Art. 162(1) |
| `firb_sft_supervisory_maturity` | on | off | CRR Art. 162(1) / PS1/26, paragraph 162 |
| `firb_sft_supervisory_maturity_years` | `0.5` | `0.5` | CRR Art. 162(1) |
| `irb_maturity_floor_collateralised_deriv_years` | `0.02739726027397260273972602740` | `0.02739726027397260273972602740` | CRR Art. 162(2) |
| `irb_maturity_floor_repo_sft_years` | `0.01369863013698630136986301370` | `0.01369863013698630136986301370` | CRR Art. 162(2) |
| `one_day_maturity_floor` | on | off | CRR Art. 162(3) / PS1/26, paragraph 162 |
| `one_day_maturity_floor_years` | `0.002739726027397260273972602740` | `0.002739726027397260273972602740` | CRR Art. 162(3) |
| `revolving_uses_termination_maturity` | off | on | CRR Art. 162 / PS1/26, paragraph 162 |
<!-- END GENERATED: crr-irb-maturity -->

## A-IRB differences from F-IRB

| Parameter | F-IRB | A-IRB (CRR) |
|-----------|-------|-------------|
| LGD | Supervisory decision table | Own estimate, **no floor under CRR** |
| CCF | Supervisory | Own estimate |
| Maturity | Fixed supervisory value | Own estimate, clamped to the Art. 162 range |

---

> **Full detail:** `docs/specifications/crr/firb-calculation.md` and `docs/specifications/crr/airb-calculation.md`
> **All pack entries:** `docs/data-model/regulatory-tables.md`
