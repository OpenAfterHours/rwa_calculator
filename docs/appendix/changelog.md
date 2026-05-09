# Changelog

All notable changes to the RWA Calculator are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **B31 equity SA-only hard guard in classifier (P2.39, batch 20260509-1642)**: `engine/classifier.py::_apply_b31_approach_restrictions` now adds `b31_equity_sa_only = (exposure_class_irb == ExposureClass.EQUITY.value)` to the existing sovereign-like SA-only mask so neither `new_airb` nor `new_firb` can fire for Basel 3.1 equity exposures, regardless of caller-supplied `IRBPermissions`. Pre-fix a misconfigured `IRBPermissions` granting AIRB to `ExposureClass.EQUITY` would route equity exposures through `approach="advanced_irb"` ahead of the equity branch in `_build_approach_expr`'s decision ladder, contradicting PRA PS1/26 Art. 147A(1)(h) (Art. 155 left blank under PS1/26). Post-fix the row falls through to `.when(exposure_class == EQUITY).then(EQUITY)` and `approach="equity"`. CRR is untouched (`_apply_b31_approach_restrictions` returns early for non-B3.1 configs; legacy CRR Art. 155 IRB equity approach retained). `firb_clear_expr` is intentionally not widened — equity is SA-only, not F-IRB-only. Pinned by `tests/unit/classifier/test_p2_39_b31_equity_sa_only_guard.py` (7 tests across `TestB31EquitySaOnlyGuard` and `TestCrrEquityControlNoB31Guard`); 48 B31-L equity acceptance tests continue to pass. Ref: PRA PS1/26 Art. 147A(1)(h) read with Art. 147(2)(e); BCBS CRE60.
- **`ValidationRequest` requires `model_permissions` under IRB permission mode (P1.147, batch 20260509-1642)**: new `permission_mode: Literal["standardised", "irb"]` field on `ValidationRequest` (`api/models.py`, default `"standardised"`); `CreditRiskCalc.validate()` and `.calculate()` now propagate `permission_mode` into the request (previously silently dropped at `api/service.py:113-118` and `:165-170`). New `_check_irb_required(...)` step in `DataPathValidator.validate()` (`api/validation.py`) appends `Path("config/model_permissions.parquet")` to `files_missing` and emits a new `VAL003` `APIError` (`api/errors.py::create_irb_required_file_error`) when `permission_mode == "irb"` and the model_permissions file is absent on disk; sets `valid=False`. The existing short-circuit in `CreditRiskCalc.calculate()` then returns `success=False` with `summary.total_rwa = Decimal("0")` and `exposure_count = 0`. Pre-fix `calculate()` returned `success=True` with `total_rwa = Decimal("1000000.0")` (silent SA fallback for all exposures despite IRB request) — direct capital overstatement risk. The B31-M11 acceptance test (`TestB31M11_NoModelPermissionsFallback`) remains green because it exercises `PipelineOrchestrator.run_with_data` with an in-memory `RawDataBundle`, bypassing `DataPathValidator` — the engine-layer silent-SA fallback is intentionally retained for in-memory callers. Pinned by `tests/integration/test_p1_147_irb_requires_model_permissions.py` (8 tests, 7 failing pre-fix). Ref: PRA PS1/26 Art. 147A; CRR Art. 143 / 150; internal model-permissions gating contract.
- **Null-safe `is_guaranteed` filter in CRM reporting / CR7 / CR7-A disclosures (P1.146, batch 20260509-1642)**: sink-side fix at `engine/aggregator/_crm_reporting.py:138,166,212` — the three `pl.col("is_guaranteed")` / `~pl.col("is_guaranteed")` filters now wrap with `.fill_null(False)` so Polars 3VL no longer drops rows where `is_guaranteed` is null. Source-side defence-in-depth at `engine/crm/guarantees.py:293` — the alias is now `(pl.col("guaranteed_portion").fill_null(0.0) > 0).alias("is_guaranteed")`, so a null `guaranteed_portion` from upstream cannot leak a null `is_guaranteed` into the aggregator. Pre-fix any guaranteed exposure whose `is_guaranteed` arrived null (e.g. an SA row that had not flowed through `apply_guarantees`, or an equity-results path that did not propagate the column) was silently dropped from `post_crm_detailed`, `post_crm_summary`, and downstream CR7 / CR7-A Pillar III disclosures — a regulatory completeness defect. The plan-bullet line reference `:260` was stale; the actual alias is at `:293`. Pinned by `tests/unit/test_p1_146_is_guaranteed_null_filter.py` (4 tests; aggregator-level scenario with a hand-built 3-row `sa_results` LazyFrame `is_guaranteed=[True, False, None]` → `post_crm_detailed.height = 4` post-fix vs `3` pre-fix; CORPORATE `total_ead = 2_150_000`). 5 pre-existing CRM-reporting integration tests continue to pass. Ref: CRR Art. 213-217 (CRM eligibility, origin of `is_guaranteed`); CRR Art. 444 / 453(g),(j); PRA PS1/26 Annex XX / XXII (CR7 / CR7-A).
- **CRR receivables Art. 224 haircut removed (P1.165, batch 20260509-1530)**: `data/tables/haircuts.py` `COLLATERAL_HAIRCUTS["receivables"]` now `Decimal("0")` (was `0.20`, an "ad-hoc approximation" with no Art. 224 basis). Receivables are non-financial collateral per CRR Art. 199(5); the entire CRR treatment lives in Art. 230 LGD\* / 1.25× OC mechanism (LGDS=35% senior per Art. 230 Table 5, no minimum threshold) — already implemented in `firb_lgd.py`. The pre-fix engine double-counted capital by applying both an ad-hoc 20% volatility haircut AND the Art. 230 mechanism. Comment block in `data/tables/haircuts.py` now points to Art. 230 / Art. 199(5). `BASEL31_COLLATERAL_HAIRCUTS["receivables"]` preserved at `0.40` per PRA PS1/26 Art. 230(2). Capital impact: F-IRB single-loan with 800k receivables collateral / EAD=1m / LGDU=0.45 / LGDS=0.35 — blended LGD\* drops from pre-fix 0.4041 (which double-counted) to the regulatorily correct 0.386 = (0.35 × 640k + 0.45 × 360k) / 1m. Pinned by `tests/acceptance/crr/test_p1_165_art_230_receivables_no_volatility_haircut.py` (8 tests). Bug-encoded assertions in `tests/unit/crr/test_crr_tables.py` and `tests/unit/crm/test_crm_basel31.py` flipped accordingly. Ref: CRR Art. 224, Art. 199(5), Art. 230(1)–(2), Art. 230 Table 5.
- **`COVERED_BOND_UNRATED_DERIVATION` split CRR vs B31 + nested Art. 129(5)(b) bug fixed (P1.180, batch 20260509-1530)**: `data/tables/crr_risk_weights.py` now exports `COVERED_BOND_UNRATED_DERIVATION_CRR` (4 keys per CRR Art. 129(5)(a)–(d): 0.20→0.10, 0.50→0.20, 1.00→0.50, 1.50→1.00) and `COVERED_BOND_UNRATED_DERIVATION_B31` (7 keys per PRA PS1/26: adds the ECRA / SCRA-only 0.30→0.15, 0.40→0.20, 0.75→0.35; B31 0.50→0.25). The old shared 7-key dict had used the B31 (b) value `0.50→0.25` even under CRR config — a nested numeric bug now corrected: under CRR, an unrated covered bond whose CQS3 institution issuer carries RW 0.50 derives RW = 0.20 (Art. 129(5)(b)) instead of the pre-fix 0.25. `_crr_unrated_cb_rw_expr` (`engine/sa/namespace.py`) consumes the new `_CRR` table; `_b31_unrated_cb_rw_expr` continues to consume `COVERED_BOND_UNRATED_DERIVATION` which now aliases `_B31` (back-compat preserved). Pinned by `tests/unit/data_tables/test_p1_180_covered_bond_unrated_derivation_split.py` (7 tests). The CRR parametrize in `tests/unit/test_covered_bonds.py::test_unrated_covered_bond_crr_by_institution_cqs` (CQS2 / CQS3 rows) flipped 0.25→0.20 to match. Ref: CRR Art. 129(5)(a)–(d); PRA PS1/26 Art. 129(5)(a)/(aa)/(ab)/(b)/(ba)/(c)/(d).
- **Classifier deterministic dedup with SA precedence on conflicting model_permissions (P1.145, batch 20260509-1530)**: `engine/classifier.py::_resolve_model_permissions` now applies the conservative-precedence rule when conflicting `(model_id, exposure_class)` AIRB+SA permission rows exist — SA wins. CRR Art. 150(1) PPU is a carve-out from IRB scope; AIRB-wins would silently expand IRB scope beyond firm permission. Implementation: row-level `_sa_block_match = permission_valid & (mp_approach == ApproachType.SA.value)` aggregated as `.max().over("exposure_reference")` and AND-NOT'd against the AIRB / FIRB / slotting `.max().over()` flags. Order-stability also pinned: a deterministic sort on `(exposure_reference, _diagnostic_priority, mp_approach, mp_country_codes, mp_excluded_book_codes)` precedes `unique(subset=["exposure_reference"], keep="first", maintain_order=True)`, so the surviving `_model_permission_diagnostic` is the most-informative one (null > filter_rejected > unmatched_model_id > null_model_id) regardless of input ordering. Existing CLS006 ladder fires `"filter_rejected"` when SA blocks IRB. Behaviour change: operators with conflicting AIRB+SA rows in production will now see a CLS006 warning where pre-fix the engine silently routed to AIRB. Pinned by `tests/unit/classifier/test_p1_145_model_permissions_dedup_determinism.py` (9 tests across two physical orderings of the same 9-row fixture; both produce identical post-classifier frames). 188 related classifier / permission / model_id tests pass with no regressions. Ref: CRR Art. 143 (IRB permission scope), Art. 150(1) PPU; PRA PS1/26 Art. 150(1A).
- **CRR Art. 237/238/239(3) maturity mismatch on unfunded credit protection (P1.109, batch 20260509-1359)**: `engine/crm/guarantees.py` now scales `amount_covered` and `percentage_covered` by `(t − 0.25) / (T − 0.25)` when the guarantor's residual maturity is shorter than the secured exposure's residual maturity (gated on `config.is_crr`). Art. 237(2) ineligibility (residual < 3 months / original < 1 year) flows through the existing eligibility chain. Pre-fix the engine applied FX haircut but no maturity-mismatch reduction, understating capital on long exposures with short-dated guarantees: a £1m / 5y CRR corporate exposure fully covered by a 2.5y guarantee now produces `GA = 1m × (2.5 − 0.25) / (5.0 − 0.25) = 473,684.21` and blended RWA = 621,052.63 (vs the pre-fix 100% substitution). Pinned by `tests/acceptance/crr/test_p1_109_art_237_maturity_mismatch_guarantees.py` (11 tests). Ref: CRR Art. 237, Art. 238, Art. 239(3); BCBS CRE22.74.
- **B31 SA RWSM corporate-CQS3 guarantor RW = 75% via Art. 122(2) Table 6 (P1.110, batch 20260509-1359)**: `engine/sa/namespace.py` imports `B31_CORPORATE_RISK_WEIGHTS` and gates the corporate-guarantor SA risk-weight lookup on `is_basel_3_1` so a CQS3-rated corporate guarantor on a B31 exposure now picks up Table 6's 75% instead of the CRR Art. 122 100%. CRR path untouched. Capital impact: a £1m B31 corporate exposure guaranteed by a CQS3 corporate guarantor drops post-RWSM RW 100% → 75% (RWA 1m → 750k). Pinned by `tests/acceptance/basel31/test_p1_110_art_122_corporate_cqs3_guarantee_substitution.py` (7 tests). Distinct from P1.95 (SCRA unrated institutions) and P1.122 (full B31 framework branching). Ref: PRA PS1/26 Art. 122(2) Table 6, Art. 235.
- **PSM F-IRB LGD substitution routes by guarantor seniority (P1.160, batch 20260509-1359)**: `engine/crm/guarantees.py::_apply_guarantee_splits` now threads `guarantor_seniority` from the guarantee table through the per-guarantor pre-aggregation, the join select-list, the borrower-frame drop-list, and the no-guarantee / remainder null-fill paths — so the IRB stage receives the actual seniority value instead of `None`. The downstream IRB routing in `engine/irb/guarantee.py` already had the seniority dispatch wired (Art. 161(1)(aa) senior 0.40 / Art. 161(1)(b) subordinated 0.75 / Art. 161(1)(d) covered-bond 0.1125) but received `None` from upstream and silently defaulted to the senior LGD. The same patch tightens `_add_guarantee_status_columns`: when the parameter-substitution path was taken (`_is_pd_substitution=True` and `guaranteed_portion>0`), `guarantee_method_used` now resolves to `"PD_PARAMETER_SUBSTITUTION"` regardless of whether the beneficial gate retained the borrower RWA — the `GUARANTEE_NOT_APPLIED_NON_BENEFICIAL` signal continues to live on `guarantee_status`. Discriminating row: B31 corporate borrower (PD=0.015, M=2.5y, EAD=1m) with subordinated corporate guarantor (PD=0.005) — `guarantor_rw_irb` 0.61877 → 1.16037 (LGD 0.40 → 0.75), guarantee correctly judged not beneficial, RWA retained at borrower 938,690 instead of incorrectly applied 618,870. Pinned by `tests/acceptance/basel31/test_p1_160_art_161_psm_lgd_seniority_routing.py` (11 tests); `tests/unit/test_irb_double_default.py::TestDoubleDefaultRWA::test_dd_floor_at_guarantor_rw` widened to accept `PD_PARAMETER_SUBSTITUTION` as a method label for non-beneficial PSM scenarios. Ref: PRA PS1/26 Art. 161(1)(aa)/(b)/(d), Art. 236(1)(a); BCBS CRE32.
- **FCSM Art. 222(4) SFT 0%/10% carve-out + Art. 222(6) non-SFT gating (P1.93, batch 20260509-1252)**: `engine/crm/simple_method.py::compute_fcsm_columns` now splits the previously-merged Art. 222(4)/(6) zero-RW exception into two distinct paths — SFTs with Art. 227-qualifying collateral get 0% (counterparty is a core market participant) or 10% (otherwise) per PRA PS1/26 Art. 222(4); non-SFTs keep the existing same-currency cash / 0%-RW sovereign 0% via the renamed `_is_art_222_6_carveout_expr` (gated on `~exposure_is_sft`); other rows fall back to the 20% Art. 222(3) floor. Step 5's Art. 222(6)(b) 20% sovereign-bond market-value discount is now suppressed when `qualifies_for_zero_haircut=True` (the Art. 227 SFT carve-out is a flat RW substitution, not a value haircut). New Boolean column `is_core_market_participant` on COUNTERPARTY_SCHEMA (default False; mirrored as `cp_is_core_market_participant` on HIERARCHY_OUTPUT_SCHEMA); new constants `ART_222_4_CMP_RW = Decimal("0.00")` and `ART_222_4_NON_CMP_RW = Decimal("0.10")` in `data/tables/crr_simple_method.py`. Headline regression: an SFT non-CMP gilt repo (Run B) now produces blended RW 0.10 / RWA £100k vs the pre-fix RW 0.00 / RWA 0 (the buggy merged branch mis-fired the same-currency 0% on every SFT). Pinned by `tests/acceptance/basel31/test_p1_93_art_222_4_fcsm_sft_carveout.py` (11 tests across 3 runs). Ref: PRA PS1/26 Art. 222(4)/(6), Art. 227(2)/(3); BCBS CRE22.18.
- **IRB PSM correlation re-derivation reads guarantor row (P1.159, batch 20260509-1252)**: `engine/irb/guarantee.py` now lifts the `guarantor_rw_irb` materialisation out of `_apply_parameter_substitution` Step 3 and into `_apply_no_better_than_direct_floor`'s existing borrower-to-guarantor column-swap window, so the primary PSM RW and the Art. 160(4) `rw_direct` floor both compute their correlation with `exposure_class` / `turnover_m` / `requires_fi_scalar` sourced from the guarantor's row — per PRA PS1/26 Art. 236(1)(a)(i) "the correlation coefficient that would be assigned to a comparable direct exposure to the protection provider". Pre-fix the engine read those columns from the borrower row, so a corporate-borrower-with-FI-scalar (Art. 153(2)) routed through a regulated bank guarantor inflated correlation by the spurious 1.25× FI multiplier and over-stated `guarantor_rw_irb`. For a £1m / PD=0.0150 / M=2.5y corporate exposure with 60% bank guarantee, `guarantor_rw_irb` drops 0.4007 → 0.2969, blended RW 0.7716 → 0.7093, RWA £771,594 → £709,324. Core math (`_parametric_irb_risk_weight_expr`, `_correlation_expr_from_pd`) untouched. The pre-existing `test_p1_157_psm_no_better_than_direct.py` was updated — its `EXPECTED_GUARANTOR_RW_IRB` flipped 0.01346 → 0.17489 (now coincides with `rw_direct` since both inputs operate in the guarantor's class), and its strict `post_nbd > rw_irb` weakened to `>=` (the max-of-two NBD floor remains asserted). Pinned by `tests/acceptance/basel31/test_p1_159_art_236_psm_correlation_guarantor_class.py` (15 tests). Ref: PRA PS1/26 Art. 236(1)(a)(i), Art. 153(2)/(4), Art. 160(4); BCBS CRE22.74.
- **UK CRR Art. 128 high-risk 150% RW gated off (P2.14, batch 20260509-1252)**: Art. 128 was omitted from UK onshored CRR by SI 2021/1078 reg. 6(3)(a) effective 1 Jan 2022 — there is no legal basis for the 150% HIGH_RISK risk weight under UK CRR until Basel 3.1 reintroduces Art. 128 from 1 Jan 2027. `engine/sa/namespace.py::_apply_crr_risk_weight_overrides` no longer carries the `.when(uc == "HIGH_RISK")` branch, so HIGH_RISK rows fall through to the chain-tail residual 100% under UK CRR. `engine/classifier.py` adds a CRR-only post-Batch-1 `_sa_class` remap rewriting `"high_risk"` → `"other"` so `exposure_class_for_sa` reflects the absence of the class under UK CRR and matches the namespace's RW behaviour; the Art. 112 priority carve-out at lines 607-618 is preserved (becomes inert under CRR after the remap, remains active under B3.1). Basel 3.1 is unchanged: `_apply_b31_risk_weight_overrides` keeps the 150% branch (Art. 128 reintroduced under PS1/26). Capital impact: a £1m unrated VC/PE high-risk corporate exposure drops from RWA £1.5m to £1.0m under UK CRR (B3.1 unchanged at £1.5m). The `HIGH_RISK_RW = Decimal("1.50")` table value in `data/tables/crr_risk_weights.py` is retained as an unused-but-correct entry; `B31_HIGH_RISK_RW` is unchanged and still consumed by the B31 path. Pre-existing tests `tests/unit/test_high_risk_items.py::TestCRRHighRiskItems` and `tests/unit/test_defaulted_secured_split.py::TestDefaultedEdgeCases::test_high_risk_unaffected` were flipped to expect the corrected 100% under CRR; B3.1 sibling assertions and the `HIGH_RISK_RW` constant tests are left untouched. Pinned by `tests/acceptance/crr/test_p2_14_art_128_high_risk_uk_omitted.py` (13 tests). Ref: SI 2021/1078 reg. 6(3)(a); UK CRR Art. 112(1) waterfall, Art. 122, Art. 133(2); PRA PS1/26 Art. 128 (B3.1 reintroduction).
- **CRR Art. 117(1) non-named MDB institution routing (P1.184, batch 20260509-1300)**: under CRR, non-named multilateral development bank exposures now risk-weight off the institution tables (Art. 120 Table 3 for own-CQS rated, Art. 121 Table 5 sovereign-derived for unrated) instead of the Basel-3.1 Table 2B that the engine previously consulted under both frameworks. Two-layer fix in `engine/sa/namespace.py`: (1) `_prepare_risk_weight_lookup` coalesces `cp_institution_cqs` into `cqs` for MDB rows so the rated CQS join target is populated (closes a separate latent bug where every MDB row arrived at the SA branch with `cqs=null`); (2) `_apply_crr_risk_weight_overrides` replaces the prior single MDB-unrated 50% branch with two branches — rated MDB → `build_institution_guarantor_rw_expr` (Art. 120 Table 3) and unrated MDB → new `INSTITUTION_RISK_WEIGHTS_SOVEREIGN_DERIVED` table (Art. 121 Table 5) with `INSTITUTION_RISK_WEIGHTS_CRR[CQS.UNRATED]` 100% fallback. `MDB_RISK_WEIGHTS_TABLE_2B` and `MDB_UNRATED_RW` remain in `data/tables/crr_risk_weights.py` (still used by the B31 path) with an updated docstring marking them Basel-3.1-only. Named MDBs (`entity_type="mdb_named"`) keep the unconditional 0% under both frameworks. Capital impact: CRR rated CQS-2 MDB jumps 30%→50% (+20pp); CRR unrated MDB with sovereign CQS-1 drops 50%→20%; CRR unrated MDB with no sovereign data jumps 50%→100%. B31 unaffected. Pinned by `tests/acceptance/crr/test_p1_184_art_117_mdb_institution_routing.py` (14 tests). Ref: CRR Art. 117(1), Art. 120 Table 3, Art. 121 Table 5.
- **F-IRB purchased receivables / dilution-risk supervisory LGD (P1.151, batch 20260509-1300)**: CRR Art. 161(1)(e)/(f)/(g) and PRA PS1/26 Art. 161(1)(e)/(f)/(g) supervisory LGDs for purchased receivables and dilution risk now wired into the F-IRB engine. New optional nullable column `purchased_receivables_subtype` on `FACILITY_SCHEMA` / `LOAN_SCHEMA` / `CONTINGENTS_SCHEMA` (values `null` / `"senior"` / `"subordinated"` / `"dilution_risk"`, validated via `COLUMN_VALUE_CONSTRAINTS`). New keys on `FIRB_SUPERVISORY_LGD` and `BASEL31_FIRB_SUPERVISORY_LGD` in `data/tables/firb_lgd.py`: `purchased_receivables_senior` (CRR 0.45 / B3.1 0.40 — the new B3.1 senior-unsecured rate), `purchased_receivables_subordinated` (1.00 both frameworks), `dilution_risk` (CRR 0.75 / B3.1 1.00 — PS1/26 recasts the dilution-risk LGD upward). `apply_firb_lgd` (`engine/irb/namespace.py`) gains a `pl.when().then()` dispatch that takes precedence over the seniority-based selector when `purchased_receivables_subtype` is non-null — so `seniority="senior", subtype="dilution_risk"` correctly resolves to dilution LGD, not the senior 0.40. `engine/hierarchy.py::_coerce_loans_to_unified` extended to pass the new column through to the IRB stage. Capital impact under B3.1: a 1m senior PR exposure at PD=1% on a 1y residual moves from default-LGD 0.40 to subtype-LGD 0.40 (no change) but a subordinated PR at 500k jumps 0.75→1.00 (RWA 814k vs. 611k pre-fix); a 200k dilution-risk row jumps 0.40→1.00 (RWA 326k vs. 130k pre-fix). Pinned by `tests/acceptance/basel31/test_p1_151_art_161_purchased_receivables_lgd.py` (5 tests). Ref: CRR Art. 161(1)(e)/(f)/(g); PRA PS1/26 Art. 161(1)(e)/(f)/(g); BCBS CRE32.
- **UKB OV1 output-floor disclosure rows 4a / 5a–7b (P1.162, batch 20260509-1300)**: PRA PS1/26 Annex XX UKB OV1 mandates seven output-floor disclosure rows that the calculator was emitting as a 13-row template (jumping 4 → 5 and 24 → 26). `B31_OV1_ROWS` in `reporting/pillar3/templates.py` now carries 20 entries with refs `4a` (Total RWEAs pre-floor), `5a` / `5b` (CET1 ratio pre-floor / pre-floor transitional), `6a` / `6b` (Tier 1 ratio), `7a` / `7b` (Total capital ratio). New frozen dataclass `Pillar3CapitalRatioOverrides` (`contracts/config.py`, exported via `contracts/__init__.py`) carries six optional `Decimal` fields letting firms supply the pre-floor and pre-floor-transitional ratios that cannot be derived from credit-risk pipeline data alone. `Pillar3Generator.generate_from_lazyframe` now accepts an optional `capital_ratios` kwarg and `_generate_ov1` now: (a) emits row 4a as `sum(rwa_pre_floor)` over the full results LazyFrame with `c = a × 0.08` (None when the column is absent — same fallback posture as existing rows 26/27); (b) emits rows 5a–7b from the override (× 100 to col `a`, with `b` and `c` left None to bypass the existing own-funds shim). When no override is supplied each ratio row stays mandatory in shape but value-blank. CRR `CRR_OV1_ROWS` is unchanged. Pinned by `tests/unit/reporting/pillar3/test_p1_162_ukb_ov1_floor_rows.py` (6 tests, including a CRR regression guard). Ref: PRA PS1/26 Annex XX UKB OV1, Art. 92(2A), Art. 92(5), Art. 438(d).
- **CRR Art. 197 / 207(2) covered-bond collateral eligibility gating (P1.96, batch 20260509-1100)**: `engine/crm/haircuts.py::_apply_collateral_haircuts` now treats `collateral_type=="covered_bond"` rows as ineligible financial collateral on non-SFT exposures (Art. 197(1) closed list governs; covered bonds are NOT in (a)–(h)). The Art. 207(2) carve-out for repo / SFT / capital-markets-driven / secured-lending transactions keeps the existing `covered_bond → corp_bond` Art. 224 supervisory-haircut routing — only the gating expression changed. The plan-bullet wording was stale ("falls through to other_physical 40%"); pre-fix the engine unconditionally applied corp-bond CQS-banded haircuts to all covered-bond collateral regardless of SFT status, understating capital on non-repo term loans secured by covered bonds. Ineligibility flows through the existing `_bond_ineligible` chain (`value_after_haircut=0`, `is_eligible_financial_collateral=False`); no schema or new data tables. Pinned by `tests/acceptance/crr/test_p1_96_art_197_covered_bond_eligibility.py` (9 tests, paired Run A non-SFT term-loan ineligibility / Run B repo Art. 207(2) carve-out). The pre-existing `test_p1_96_covered_bond_haircut_routing.py` was reframed to set `is_sft=True` on its repo fixture so the 416,970.56 expectation now genuinely tests the carve-out instead of relying on the buggy unconditional routing. Ref: CRR / PRA PS1/26 Art. 197(1), Art. 207(2), Art. 224 Table 1.
- **CRR Art. 162(3)(b) F-IRB short-term trade-finance M derivation (P1.118, batch 20260509-1100)**: `engine/irb/namespace.py::IRBLazyFrame.prepare_columns` now derives `has_one_day_maturity_floor=True` from `is_short_term_trade_lc=True AND maturity_date is not null AND residual_years <= 1.0` (gated on `config.is_crr`; B31 wording differs and is deferred). The flag was previously caller-supplied only — qualifying short-term self-liquidating trade-finance F-IRB exposures defaulted to M=2.5y or floored at 1y unless the caller pre-set the flag. With derivation in place, an unrated MLR documentary credit on a 9-month residual now picks up M=1/365 (the existing `irb/formulas.py:705-707` branch sets `maturity = 1/365` literally when the flag is True; this is the documented engine semantic, not a "floor at 1/365" interpretation). For a £2m EAD / PD=0.5% F-IRB corporate, RWA drops 1,106,216 → 860,310 (≈22% capital relief). Reuses the existing `is_short_term_trade_lc` schema column added by P1.128; no schema change. Pinned by `tests/acceptance/crr/test_p1_118_art_162_3_short_term_trade_finance_m_derivation.py` (5 tests). FX-settlement / securities-settlement Art. 162(3) 2nd-sub (a)/(c)/(d) carve-outs and the B31 wording variant deferred. Ref: CRR Art. 162(3) second sub-paragraph point (b), Art. 4(1)(80).
- **B31 SA Art. 127(1) defaulted provision-ratio gross denominator (P1.120, batch 20260509-1100)**: `engine/sa/namespace.py::_apply_defaulted_risk_weight` B31 branch now uses `gross_outstanding = ead_gross + provision_deducted` (with a fallback to `ead + provision_deducted` for unit-test entry points where `ead_gross` is absent) as the Art. 127(1) provision-coverage 100%/150% threshold denominator, instead of `ead_final` (post-CRM, post-provision). PRA PS1/26 Art. 127(1) wording is "the outstanding amount of the item or facility" (gross outstanding before specific credit risk adjustments and before CRM); the CRR branch's different wording — "unsecured part of the exposure value if those credit risk adjustments and deductions were not applied" — remains correctly modelled by the existing `ead_final + provision_deducted` expression and is left untouched. The plan-bullet direction was inverted: the bug was UNDER-stating RW (assigning 100% when 150% was correct on partially collateralised B31 defaults), so the fix INCREASES capital. For a B31 corporate defaulted exposure with outstanding=100k / provisions=8k / FCCM cash 60k, the pre-fix ratio was 8k/32k=25% (RW 100%, RWA 32,000); post-fix ratio is 8k/100k=8% (RW 150%, RWA 48,000). Pinned by `tests/acceptance/basel31/test_p1_120_art_127_1_provision_ratio_denominator.py` (B31-K13, 7 tests). Existing `test_scenario_b31_k_defaulted.py::TestB31K8_ProvisionDenominatorDifference` updated: B31 RW 100%→150%, RWA 80,000→120,000; CRR contrast unchanged. Ref: PRA PS1/26 Art. 127(1); BCBS CRE20.87–90.
- **PRA PS1/26 Art. 122(3) Table 6A short-term corporate ECAI risk weights (P1.103, batch 20260509-1025)**: corporate exposures with an issue-specific short-term ECAI rating now route through the new Table 6A (CQS1=20% / CQS2=50% / CQS3=100% / Others=150%) instead of the long-term Table 6 fallback (where CQS3 = 75% under Basel 3.1). On a £1m CQS-3 short-term-rated corporate the RW jumps 75% → 100% (RWA 750k → 1m, K 60k → 80k) — closes a documented capital understatement. New constant `B31_CORPORATE_SHORT_TERM_ECAI_RISK_WEIGHTS` in `data/tables/b31_risk_weights.py`; new helper `_b31_append_corporate_maturity_branches` in `engine/sa/namespace.py` invoked alongside the existing institution Table 4A branch (P1.105). Reuses the `has_short_term_ecai` `FACILITY_SCHEMA` flag and OR-aggregation infrastructure added by P1.105 — no new schema or hierarchy fields. Corporate short-term gate is `original_maturity_years ≤ 0.25` only (Art. 121(4)/(5) trade-LC ≤ 6m extension is institution-only). SME corporates are excluded so the dedicated 85% SME path remains authoritative even when an SME has a short-term ECAI rating. CRR corporate branch unchanged (CRR Art. 122 has no Table 6A analogue). Pinned by `tests/acceptance/basel31/test_p1_103_art_122_3_short_term_corporate_ecai.py` (5 tests). Ref: PRA PS1/26 Art. 122(3) Table 6A; BCBS CRE20.42–49.
- **PRA PS1/26 Art. 121(4) SCRA short-term trade-finance extension wired into B31 institution chain (P1.128, batch 20260509-1025)**: an unrated Grade A institution exposure that is a documentary credit financing the movement of goods with original maturity ≤ 6 months now picks up the Table 5A short-term SCRA RW (Grade A = 20%) via the same Art. 121(4) carve-out the ECRA branch (Art. 120(2A)) already honoured. Pre-fix the SCRA short-term gate in `_b31_append_institution_maturity_branches` was hard-coded to `original_mty ≤ 0.25`, missing the `is_short_term_trade_lc & original_mty ≤ 0.5` OR-clause that the ECRA branch already had via the shared `in_st_window` expression — a 5-month documentary credit fell through to the long-term SCRA Grade A 40%, doubling RWA (£1m drawn → 400k vs 200k). Fix replaces the SCRA gate with `is_institution & is_unrated & in_st_window`, reusing the helper expression already in place. Required follow-on edit in `engine/hierarchy.py::_propagate_facility_qrre_columns` to add a counterparty-level OR-broadcast of `is_short_term_trade_lc` (mirroring the `has_short_term_ecai` precedent added by P1.105) so the flag propagates from facilities to drawn-loan exposure rows when `facility_mappings` is empty. CRR helper `_crr_append_institution_maturity_branches` unchanged (CRR has no Art. 121(4) trade-finance extension to its short-term unrated-institution treatment). Pinned by `tests/acceptance/basel31/test_p1_128_art_121_4_scra_short_term_trade_finance.py` (5 tests). Ref: PRA PS1/26 Art. 121(4); BCBS CRE20.16–21.
- **CRR Art. 224(2)(a) FX H_fx 20-day secured-lending default pinned by acceptance test (P1.186, batch 20260509-1025)**: the engine fix shipped silently in commit `44006da` on 2026-05-03 — `engine/crm/haircuts.py` now derives the liquidation period from `exposure_is_sft` (5 / 10 / 20 days per Art. 224(2)(a)–(c)) instead of defaulting everything to 10 days — but the acceptance test pinning the regulatory behaviour was never written, leaving the plan item at `[~]`. This batch adds the missing fixtures and a 10-test acceptance scenario covering: 20-day default for `is_sft=False` secured lending → ead_final ≈ 484,852.81 (H_fx,20 = 8% × √2 ≈ 11.314%, H_c,20 ≈ 2.828%); 5-day default for `is_sft=True` → ead_final ≈ 442,426.41; an explicit regression guard against the pre-fix 10-day result of 460,000.00 (a strict inequality that can only be satisfied when H_fx is scaled to the 20-day period); and a directional sanity SL > SFT (20-day haircuts > 5-day → larger E* on secured-lending loan than on the SFT). Closes the residual `liquidation_period as config` sub-item of P6.15. Pinned by `tests/acceptance/crr/test_p1_186_art_224_2_fx_haircut_secured_lending_default.py` (10 tests). Ref: CRR Art. 224(2)(a), Art. 226(2), Art. 233.
- **PRA PS1/26 Art. 120(2B) Table 4A short-term institution ECAI risk weights (P1.105, batch 20260508-0254)**: institutions with an issue-specific short-term ECAI assessment now route through the new Table 4A (CQS1=20% / CQS2=50% / CQS3=100% / CQS4–5=150%) instead of the more permissive Table 4 fallback, closing a CQS-2/3 capital understatement (CQS3 jumps 20% → 100% on a £1m short-term-rated institution exposure). New optional Boolean `has_short_term_ecai` on `FACILITY_SCHEMA` (default False); new constant `B31_ECRA_SHORT_TERM_ECAI_RISK_WEIGHTS` in `data/tables/b31_risk_weights.py`; `_b31_append_institution_maturity_branches` in `engine/sa/namespace.py` gates Table 4A ahead of the Table 4 fallback when `is_institution & is_rated & has_short_term_ecai & in_st_window`. Because the ECAI rating is a counterparty/rating-level property, `engine/hierarchy.py::_propagate_facility_qrre_columns` was extended to OR-aggregate `has_short_term_ecai` across a counterparty's facilities and broadcast to every exposure — loans without `parent_facility_reference` therefore inherit the flag from a sibling facility row. CRR institution path is unchanged (Art. 120 has no Table 4A analogue). Pinned by `tests/acceptance/basel31/test_p1_105_art_120_2b_short_term_institution_ecai.py` (5 tests). Ref: PRA PS1/26 Art. 120(2B), Art. 120(3); BCBS CRE20.20.
- **CRR Art. 155(2)(c) IRB Simple GOVERNMENT_SUPPORTED equity now 370% (P1.164, batch 20260508-0254)**: Art. 155(2) is a closed three-bucket enumeration (290% exchange-traded / 190% PE-diversified / 370% all-other) with no government-supported carve-out. The previous 190% mapping for `GOVERNMENT_SUPPORTED` had no regulatory basis and *understated* capital (190% < 370%). `data/tables/crr_equity_rw.py` `IRB_SIMPLE_EQUITY_RISK_WEIGHTS[GOVERNMENT_SUPPORTED]` updated 1.90 → 3.70 with an Art. 155(2)(c) citation comment; the redundant `is_government_supported` and `equity_type=="government_supported"` branches in `engine/equity/calculator.py::_apply_equity_weights_irb_simple` were removed (the `.otherwise(_IRB_RW[OTHER])` fall-through now produces the correct 370%). For a £300k AIRB government-supported equity exposure, RWA increases 570,000 → 1,110,000. Basel 3.1 unaffected (Art. 155 is left blank under PS1/26; B31 routes through Art. 133(3) 250%). Pinned by `tests/acceptance/crr/test_p1_164_art_155_2c_government_supported_irb_simple.py` (5 tests) plus updated CRR-J14 acceptance and `TestIRBSimpleEquityRiskWeights::test_government_supported_370_percent` unit-table assertions. Ref: CRR Art. 155(2)(c).
- **CRR Art. 239(1) FCSM maturity-mismatch eligibility gate (P1.104, batch 20260508-0210)**: `engine/crm/simple_method.py::compute_fcsm_columns()` now treats financial collateral whose `residual_maturity_years` is strictly less than the secured exposure's residual maturity as ineligible — the FCSM benefit is fully suppressed (binary gate, no Art. 239(2) `(t-0.25)/(T-0.25)` partial adjustment, which is FCCM/IRB only). Direct-/facility-/counterparty-level exposure residual maturity is coalesced before the comparison so the gate is conservative for pool-level pledges. Pre-fix the engine recognised collateral with shorter maturity than the exposure, understating capital. Pinned by `tests/acceptance/crr/test_p1_104_art_239_1_fcsm_maturity_eligibility.py` (8 tests; the discriminating MISMATCH row asserts `fcsm_collateral_value=0`, `risk_weight=1.00`, `rwa=1,000,000`). Plan-bullet citation was Art. 222(7); architect verified the actual FCSM maturity-mismatch exclusion lives at Art. 239(1) — Art. 222(7) is a definition-extension paragraph for sovereign-debt-securities scope. Ref: CRR Art. 239(1).
- **PSM PD floor uses guarantor exposure-class context (P1.157, batch 20260508-0210)**: `engine/irb/formulas.py::_pd_floor_expression` extended with optional `exposure_class_col` / `transactor_col` kwargs (additive, backward-compatible — defaults preserve all existing call-site behaviour). Three PSM call sites in `engine/irb/guarantee.py` (`_apply_parameter_substitution`, `_adjust_expected_loss`, `_apply_double_default`) now pass `guarantor_exposure_class` so the substituted (guarantor's) PD is floored at the floor that would apply to a direct exposure to the guarantor — Art. 160(4) "no better than direct" — and not at the borrower's class-floor. In the pinned scenario a corporate guarantor's PD is floored at corporate 0.05% (Art. 163(1)(a)) instead of the borrower's QRRE-revolver 0.10% (Art. 163(1)(c)), correctly lowering `guarantor_rw_irb` from 0.02408 to 0.01346. The NBD floor function `_apply_no_better_than_direct_floor` was already in place; the prior fixture/test were degenerate (`guarantor_rw_irb == RW_direct` ⇒ floor non-binding) and have been replaced with a binding configuration where `RW_direct` (0.17489) ≫ `guarantor_rw_irb` (0.01346) and the NBD floor lifts blended RWA from 136,636 to 233,494 (+71%). Pinned by `tests/acceptance/basel31/test_p1_157_psm_no_better_than_direct.py` (13 tests). Ref: CRR / PRA PS1/26 Art. 160(4), Art. 163(1)(a), Art. 161(1)(aa), Art. 236(1)(a)(i).
- **CRR Art. 126(2)(d) commercial-RE proportion split (P1.181, batch 20260508-0210)**: `engine/sa/namespace.py::_crr_append_real_estate_branches` residual leg now blends the 50% Art. 126(2) secured RW with the counterparty's Art. 122 corporate-CQS RW per Art. 124(1) "the part of the exposure that exceeds the mortgage value", instead of stamping a flat 100% residual. The split mechanism mirrors Art. 125 RRE: `secured_share = min(1, 0.50 / LTV)`, `residual_share = 1 − secured_share`, blended RW = `0.50 × secured_share + counterparty_RW × residual_share`. The residual lookup uses `_cqs_table_lookup_expr` against `CORPORATE_RISK_WEIGHTS` (already imported), so the unrated default (1.00) is sourced from the data layer rather than inlined. `engine/hierarchy.py::_coerce_loans_to_unified` defensively passes through the CLASSIFIER_OUTPUT_SCHEMA RE columns (`ltv`, `property_type`, `has_income_cover`, `is_qualifying_re`, `prior_charge_ltv`, `is_defaulted`, `qualifies_as_retail`); `_add_collateral_ltv` only stamps null defaults for columns not already present so the loan-frame values survive unification. Pre-fix, CRR CRE LTV > 50% was a binary 100% (overstatement); for an LTV-0.80 unrated-corporate CRE the new RW is 0.6875 (RWA 687,500) instead of 1.00 (RWA 1,000,000). The discriminating fixture row uses an LTV-0.80 corporate-CQS1 exposure, where a naïve "residual = constant 100%" fix would still emit RW=1.00 but the correct counterparty-RW lookup emits 0.3875 (RW=0.50×0.625 + 0.20×0.375). Basel 3.1 Art. 124H/124I path unchanged. Pinned by `tests/acceptance/crr/test_p1_181_art_126_cre_proportion_split.py` (7 tests). Ref: UK CRR Art. 126(2)(d), Art. 124(1), Art. 122 Table 6.
- **CRR Art. 137(1)–(2) Table 9 ECA / MEIP score-to-RW direct mapping (P1.100, batch 20260508-0020)**: unrated sovereigns with an Art. 137(1) Export Credit Agency / OECD MEIP score now route through Table 9 (0/0/20/50/100/100/100/150 % for scores 0–7) instead of falling through to the Art. 114(2) Table 1 unrated 100% bucket — closes a 5× capital overstatement for unrated sovereigns with low MEIP scores. New `eca_score: ColumnSpec(pl.Int8, required=False)` on COUNTERPARTY_SCHEMA; new `ECA_MEIP_RISK_WEIGHTS` table in `data/tables/crr_risk_weights.py`; new `_eca_meip_rw_expr()` in `engine/sa/namespace.py` injected after the Art. 114(3)/(4) domestic-currency override and before the unrated fallback. Basel 3.1 path unchanged. Pinned by `tests/acceptance/crr/test_p1_100_art_137_eca_meip_sovereign.py` (5 tests, scenario CRR-A14-ECA). Ref: CRR Art. 137(1)–(2), Art. 114(2) Table 1.
- **CRR Art. 226(1) non-daily revaluation haircut scaling (P1.101, batch 20260508-0020)**: collateral revalued less frequently than daily now sees its supervisory haircut scaled by `sqrt((N_R + T_m − 1) / T_m)` where N_R is the revaluation frequency in business days and T_m is the liquidation period (5 / 10 / 20 per Art. 224(2)) — closes a haircut understatement for SFTs and other less-than-daily-revalued collateral. New `revaluation_frequency_days: ColumnSpec(pl.Int32, required=False)` on COLLATERAL_SCHEMA (null/1 ⇒ daily, no scaling; >1 fires Art. 226(1)); `engine/crm/haircuts.py` multiplies post-Art-226(2) `collateral_haircut` AND `fx_haircut` by `reval_factor` after the Art. 226(2) liquidation-period scaling. Art. 227 zero-haircut short-circuit preserved. The fix applies identically under CRR and PRA PS1/26 (PS1/26 carries Art. 226(1) forward unchanged). Pinned by `tests/acceptance/crr/test_p1_101_art_226_1_non_daily_revaluation.py` (6 tests, scenario CRR-D-REVAL). Ref: CRR Art. 226(1), Art. 226(2), Art. 224(2)(a)–(c).
- **UK CRR slotting Art. 153(5) Table 1 — `is_hvcre` ignored under CRR (P1.177, batch 20260508-0020)**: UK-onshored CRR Art. 153(5) contains only Table 1; the EU CRR Table 2 HVCRE table was not retained on onshoring (SI 2021/1078). The previous engine routed `is_hvcre=True` CRR exposures through `SLOTTING_RISK_WEIGHTS_HVCRE` weights (e.g. 95% Strong ≥2.5y) — a capital overstatement for UK firms. `engine/slotting/namespace.py::SlottingExpr.lookup_rw` and `lookup_el_rate` now ignore `is_hvcre` under CRR (`config.is_crr=True`); all SL exposures use Table 1 weights and Table B EL rates regardless of the HVCRE flag. Basel 3.1 HVCRE handling under PS1/26 Art. 153(5) Table A is unchanged. The `is_hvcre` flag is preserved on the audit trail. Existing CRR-E4/E7/E8 expected outputs patched to post-fix values (RW 0.95→0.70 / 0.70→0.50 / 0.95→0.70); 20 pre-existing unit tests that codified the buggy EU Table 2 behaviour were deleted or updated to assert HVCRE-equals-non-HVCRE under CRR. Pinned by `tests/acceptance/crr/test_p1_177_art_153_5_uk_crr_no_hvcre.py` (5 tests, scenario CRR-E9). Ref: UK CRR Art. 153(5) Table 1, Art. 147(8) (no HVCRE sub-type), Art. 158(6) Table B; SI 2021/1078.
- **Mixed RRE+CRE collateral now split across both classes per regime (`engine/re_splitter.py`, `engine/classifier.py`)**: a single SA exposure secured by both residential and commercial property collateral now produces three child rows (`secured_rre` + `secured_cre` + `residual`) sharing one `split_parent_id`, instead of the prior dominance-rule single-class split that silently dropped the non-dominant collateral value. The new behaviour follows **PRA PS1/26 Art. 124(4) pro-rata by collateral value** under Basel 3.1 (closes documented gap **D3.59** in `docs/specifications/basel31/sa-risk-weights.md:1314-1321`) and **CRR Art. 124(1) "any part of an exposure" RRE-first sequential allocation** under CRR (RRE consumes EAD up to its 80% LTV cap, then CRE picks up the remainder up to its 50% LTV cap when rental coverage is met). Per-component classifier columns added (`re_split_residential_value`, `re_split_commercial_value`, `re_split_residential_eligible`, `re_split_commercial_eligible`); per-component audit columns added to `re_split_audit` (`rre_secured_ead`, `cre_secured_ead`, `is_mixed`); new informational warning **RE003** counts mixed-collateral splits per batch with the regime-specific allocation rule named in the message. Single-component splits (pure RRE or pure CRE) keep the legacy `secured` role and `_sec` reference suffix for backward compatibility — only mixed splits use `secured_rre` / `secured_cre` and `_rre` / `_cre` suffixes. Single `prior_charge_ltv` column is applied to both component caps as a v1 conservatism (documented limitation). Surfaced and fixed a pre-existing latent SA dispatch bug in `engine/sa/namespace.py`: `COMMERCIAL_MORTGAGE` exposure-class rows were mis-routed through the residential RW branch because both classes contain the `MORTGAGE` substring; commercial branch now dispatches first under both CRR and Basel 3.1 paths and the Art. 127(3) defaulted RESI flat-100% rule excludes commercial RE. Ref: PRA PS1/26 Art. 124(4), Art. 124F, Art. 124H(1)-(3); CRR Art. 124(1), Art. 125, Art. 126.
- **`crm_collateral_method` / `airb_collateral_method` config knobs documented (`docs/api/configuration.md`)**: the `CRMCollateralMethod` (`COMPREHENSIVE` / `SIMPLE`) and `AIRBCollateralMethod` (`LGD_MODELLING` / `FOUNDATION`) enums on `CalculationConfig` were exposed in source but absent from the API docs — practitioners had to read `domain/enums.py` to discover the toggles. Both knobs are now on the configuration page with field-summary tables, member-by-member regulatory citations (CRR Art. 222 FCSM / Art. 223–224 FCCM; PRA PS1/26 Art. 191A firm-wide election; PS1/26 Art. 169A/169B and CRR Art. 229–231 for the A-IRB collateral switch), factory defaults, framework-applicability admonitions, and worked `dataclasses.replace` snippets. Closes DOCS_IMPLEMENTATION_PLAN.md D3.52.
- **IRB guarantee parameter-substitution path (PSM, CRE22.70–85) documented (`docs/specifications/basel31/credit-risk-mitigation.md`)**: the four-step PSM path implemented at `engine/irb/guarantee.py` was an opaque code surface — the B31 CRM spec covered guarantee haircuts and eligibility but never showed how PD substitution, F-IRB LGD substitution by guarantor seniority, correlation re-derivation, and Art. 236A maturity adjustment compose into the final risk weight. The restructured `## IRB Parameter Substitution` section now walks each step against PRA PS1/26 Art. 161 / Art. 162 / Art. 202 / Art. 235 / Art. 236(1)(a)(i) (with BCBS CRE22.72–80 in parentheses), adds the composing IRB risk-weight and EL formulas, the CRR-only Art. 153(3) double-default overlay, and an audit-trail table mapping every output column emitted by `_add_guarantee_status_columns`. Three Art. 236 code defects surfaced during the doc walk (Step-3 borrower-vs-guarantor correlation, Step-2 senior-unsecured LGD scalar, missing option-(i) borrower-unprotected LGD source) routed to IMPLEMENTATION_PLAN.md as P1.159 / P1.160 / P2.43. Closes DOCS_IMPLEMENTATION_PLAN.md D3.56.
- **`life_ins_collateral_value` / `life_ins_secured_rw` output columns documented (`docs/data-model/output-schemas.md`)**: new "CRM — life insurance collateral (Art. 232)" subsection describes the two exposure-frame columns produced by `engine/crm/life_insurance.py::compute_life_insurance_columns` and consumed by `lf.sa.apply_life_insurance_rw_mapping()` during SA risk-weight blending. Includes the Art. 232(3) insurer-RW mapping table (PS1/26 7-tier 20% / 30% / 50% / 65% / 100% / 135% / 150% vs CRR 4-tier 20% / 50% / 100% / 150%), defaults when no life-insurance collateral is present, IRB-side LGD_S = 40% cross-reference, and a single-source-of-truth pointer to the Basel 3.1 CRM spec. Ref: PRA PS1/26 Art. 232, Art. 200(b), Art. 212(2); CRR Art. 232. Closes DOCS_IMPLEMENTATION_PLAN.md D3.53.
- **IRB Risk Parameter Estimation Standards (PS1/26 Art. 179–184) documented (`docs/specifications/basel31/irb-approach.md`)**: previously the spec stub-cited Art. 179–184 with no content, leaving implementers without a documented contract for what the calculator's PD / LGD / EAD inputs must represent. New "Risk Parameter Estimation Standards" section now covers Art. 179 (general estimation, MoC, pooled data), Art. 180(1)(a)–(h) corporate / institution PD plus Art. 180(2)(a)–(f) retail PD with the 5-year minimum data history, Art. 181 LGD (downturn LGD, LGD-in-default, 5y → 7y data ramp), Art. 181A–C downturn nature/severity/duration (incl. ≥ 20-year time-span at Art. 181C(1)), Art. 182 EAD/CCF, Art. 183 LGD-AM under A-IRB, and Art. 184 purchased receivables — all with verbatim PS1/26 Appendix 1 page citations (pp. 131–141). Closes DOCS_IMPLEMENTATION_PLAN.md D3.49.
- **`enable_double_default` config knob documented (`docs/api/configuration.md`)**: the CRR Art. 153(3) double-default RW formula is now a discoverable knob from the API docs alone — field name, type, default (`False`), formula reference, Art. 202 / 217 eligibility, the PS1/26 B31-removal note, and a worked `CalculationConfig.crr(enable_double_default=True)` snippet are all in place. Practitioners no longer have to read source to find the toggle. Closes DOCS_IMPLEMENTATION_PLAN.md D3.50.
- **Five missing error codes documented in the contracts API reference (`docs/api/contracts.md`)**: `CLS004` (`ERROR_QRRE_COLUMNS_MISSING`), `CLS005` (`ERROR_RETAIL_POOL_MGMT_MISSING`), `IRB006` (`ERROR_MISSING_EXPECTED_LOSS`), `SA005` (`ERROR_EQUITY_IN_MAIN_TABLE`), and `SF001` (`ERROR_SME_MISSING_COUNTERPARTY_REF`) were defined in `src/rwa_calc/contracts/errors.py` but absent from the published Error Code Constants table. `SF001` introduces a new "Supporting Factors" prefix. Closes DOCS_IMPLEMENTATION_PLAN.md D3.55.
- **`use_investment_grade_assessment` config knob documented (`docs/api/configuration.md`)**: the PRA PS1/26 Art. 122(6)/(8) IG=65% / non-IG=135% election for unrated non-SME corporates is now a discoverable knob from the API docs — field name, type, default (`False`), the Basel-3.1-only scope (CRR factory does not expose it), the Art. 122(7) sound-processes obligation and Art. 122(8)(b) PRA notification requirement on adoption *and* cessation, the Art. 92(2A) S-TREA interaction, and a worked `CalculationConfig.basel_3_1(use_investment_grade_assessment=True)` snippet are all in place. The `basel_3_1()` factory signature in the same page is updated to surface the argument. Closes DOCS_IMPLEMENTATION_PLAN.md D3.51 (plan-item article citation corrected — the field is Art. 122(6)/(8), not Art. 153(3) as the plan text said).

### Changed
- **`supporting_factor_applied` column documented in canonical name (`docs/data-model/output-schemas.md`)**: the SA supporting-factor stage at `engine/sa/supporting_factors.py` and the aggregator at `engine/aggregator/_supporting_factors.py` emit a generic `supporting_factor_applied` Boolean covering both Art. 501 (SME, blended at the EUR 2.5m / GBP 2.2m threshold) and Art. 501a (infrastructure, flat 0.75) supporting factors, but the schema docs still showed the legacy `sme_supporting_factor_applied` name from before the infrastructure factor existed. The "Supporting factors (CRR only)" sub-table now lists all four pipeline-emitted columns (`supporting_factor`, `supporting_factor_applied`, `rwa_pre_factor`, `rwa_post_factor`) with broadened prose covering both factors, and a rename callout explains that `sme_supporting_factor_applied` survives in `CRR_OUTPUT_SCHEMA_ADDITIONS` only as a legacy COREP alias. Closes DOCS_IMPLEMENTATION_PLAN.md D3.54.

### Cross-references
- **Art. 179–184 estimation standards cross-link added (`docs/appendix/regulatory-references.md`)**: the bare Art. 178–180 / Art. 181 rows in the IRB Approach articles table are replaced with cross-link rows pointing at the existing verbatim Art. 179–184 spec section in `basel31/irb-approach.md` and the Art. 181A–C economic-downturn anchor — implementers can now navigate the appendix index straight into the PD/LGD/EAD estimation rules without scanning the IRB spec page. Companion to D3.49 (above).
- **Art. 159(3) two-branch rule and Art. 62(d) T2 cap formula documented (`docs/specifications/crr/provisions.md`, `docs/specifications/basel31/provisions.md`)**: both provisions specs previously described the EL-vs-provisions comparison at high level only — the formal A/B/C/D pseudocode block, the explicit `T2_credit_cap = 0.006 × IRB_credit_risk_RWA` formula, and the per-branch CET1-deduction-vs-T2-credit treatment were absent from both pages. Both specs now carry verbatim Art. 159(3) and Art. 62(d) quotes (CRR + PS1/26 App 1 p. 109), a dedicated `### Art. 62(d) — T2 Cap on EL Excess` subsection, and three worked numeric examples (combined-shortfall, combined-excess-cap-binds, split-branch). The B31 spec adds a CRR↔B31 framework-delta callout cross-linking the OF-ADJ T2 component caps in `output-floor.md` (single source of truth, no duplication). Plan-item misattribution corrected inline: D4.87(b) cited "0.6% IRB RWA (CRR) / 1.25% S-TREA (B31)" — the verbatim Art. 62(d) cap base is **0.6% of IRB credit-risk RWA under both CRR and Basel 3.1**; the 1.25% S-TREA figure is the **GCRA cap** under Art. 92(2A), not an EL-excess T2 cap. Closes DOCS_IMPLEMENTATION_PLAN.md D4.87. Ref: CRR Art. 159(3), Art. 62(d); PRA PS1/26 Art. 159(3), Art. 62(d), Art. 92(2A).
- **Factory-override worked examples added for `CalculationConfig.crr()` / `.basel_3_1()` (`docs/api/configuration.md`)**: the page previously showed only the factory defaults, leaving practitioners to read source to discover which keyword overrides exist. The factory signatures now match `src/rwa_calc/contracts/config.py:894-1041`; a new "Factory Overrides — Worked Examples" subsection adds a keyword-coverage table cross-linking each override to its per-knob anchor, plus one CRR worked example (overriding `enable_double_default`, `crm_collateral_method`, `eur_gbp_rate`, `log_format`) and one Basel 3.1 worked example (overriding `use_investment_grade_assessment`, `airb_collateral_method`, `crm_collateral_method`, `institution_type`, `reporting_basis`, `skip_transitional_floor`). Two stale prose blocks corrected: both factories DO expose `crm_collateral_method` as a keyword, and `.basel_3_1()` exposes `airb_collateral_method` (default `AIRBCollateralMethod.LGD_MODELLING`). Plan-item enum correction: D4.89 cited `AIRBCollateralMethod.EFFECTIVE_LGD` — actual enum members are `FOUNDATION` and `LGD_MODELLING`. Closes DOCS_IMPLEMENTATION_PLAN.md D4.89.
- **`SlottingCategory` enum and subgrade A/B/C/D relationship surfaced at glossary and user-guide level (`docs/specifications/glossary.md`, `docs/user-guide/methodology/specialised-lending.md`)**: previously the relationship between the coarse 5-bucket `SlottingCategory` enum (STRONG / GOOD / SATISFACTORY / WEAK / DEFAULT) and the four subgrade columns A/B/C/D in PS1/26 Art. 153(5) Table A / Art. 158(6) Table B was documented only inside the slotting spec — practitioners reading the glossary or user guide had no entry point. The glossary now carries a new `SlottingCategory` row in the top-of-page table and a `### SlottingCategory and subgrades A/B/C/D` subsection that names the five enum members verbatim and explains that subgrades arise only on the STRONG and GOOD buckets per Art. 153(5)(c)–(f). The specialised-lending user guide gains a new `## From Category to Risk Weight: the Subgrade Step` section walking through "I have a Strong CRE exposure → RW" in four steps using the actual loader fields (`slotting_category`, `is_hvcre`, `residual_maturity_years`, `is_short_maturity`, `sl_type`); no risk-weight numbers are duplicated — all values cross-link to the canonical slotting spec. Plan-item correction: D4.90 cited a `slotting_subgrade` loader field that does **not** exist in `data/schemas.py` — the subgrade is derived from `is_short_maturity` / `residual_maturity_years` per Art. 153(5)(c)–(f); only `slotting_category` and `is_hvcre` are direct inputs. Closes DOCS_IMPLEMENTATION_PLAN.md D4.90. Ref: PRA PS1/26 Art. 153(5)(c)–(f), Art. 158(6) Table B; CRR Art. 153(5) Table 1; `domain/enums.py`.
- **Art. 129(6) pre-2007 covered bond grandfathering documented (`docs/specifications/crr/sa-risk-weights.md`)**: the CRR Art. 129(6) carve-out exempting covered bonds issued before 31 Dec 2007 from the Art. 129(1)/(3) eligibility requirements (grandfathered to maturity) was absent from the spec — practitioners had no documented basis for why pre-2007 issues retain the preferential covered-bond RW table without satisfying the modern collateral-pool / disclosure tests. New "Pre-2007 Grandfathering (Art. 129(6))" subsection now sits between the existing Art. 129 eligibility block and the B31 covered-bond changes, with verbatim CRR Art. 129(6) and PS1/26 Art. 129(6) quotes, an operational note that Art. 129(7) disclosure obligations still apply, and a B31 delta callout flagging the PS1/26 tightening (PS1/26 explicitly conditions grandfathering on Art. 129(7) compliance). Closes DOCS_IMPLEMENTATION_PLAN.md D4.47. Ref: CRR Art. 129(6), PRA PS1/26 Art. 129(6).
- **Art. 227(2)(d) 4-business-day close-out window for FCSM SFTs documented (`docs/specifications/crr/credit-risk-mitigation.md`)**: the Financial Collateral Simple Method gates the 0% / 10% repo-style transaction floor on a set of preconditions in Art. 227(2)(a)–(h), one of which (the 4-business-day close-out period at Art. 227(2)(d)) was completely absent from the CRM spec — implementers had no documented eligibility test for when an SFT qualifies for the FCSM carve-out vs. falls back to the Art. 222(3) 20% RW floor. New "Art. 227(2)(a)–(h) — Preconditions for the FCSM SFT Carve-Out" subsection lists all eight gating conditions with a dedicated "Art. 227(2)(d) — 4-business-day close-out window" sub-subsection (verbatim CRR quote, framed as eligibility precondition, fall-back behaviour explained, Art. 227(1) FCCM-routing note). B31 delta callout flags PS1/26 Art. 227(2)(i) (new unfettered-seizure condition) and PS1/26 Art. 227(4) (new master-netting-agreement rule) as B31 additions. Plan-item misattribution corrected: D4.49 cited "Art. 227(4)" but the 4-business-day window actually sits at Art. 227(2)(d) in the consolidated UK CRR. Closes DOCS_IMPLEMENTATION_PLAN.md D4.49. Ref: CRR Art. 227(2)(d), Art. 227(1), Art. 222(4); PRA PS1/26 Art. 227(2)(d), Art. 227(2)(i), Art. 227(4).
- **OF-ADJ T2 component caps (Art. 62(c) / Art. 62(d) / Art. 92(2A) GCRA) documented (`docs/specifications/basel31/output-floor.md`)**: the OF-ADJ formula `OF-ADJ = max(0, SA-RWA × OF% − IRB-RWA)` was published without context for the three Tier-2 caps that interact with the floor reconciliation, leaving a gap between the formula in the spec and the upstream-caps-vs-engine-cap split that `engine/aggregator/_floor.py::compute_of_adj` actually implements. New "T2 Component Caps — Art. 62(c) and Art. 62(d)" subsection (framed as a clarification, not a new mechanic) covers IRB T2 (Art. 62(d), 0.6% of IRB credit-risk RWA, applied upstream), SA T2 (Art. 62(c), 1.25% of SA credit-risk RWA, applied upstream), and the engine-applied GCRA cap (Art. 92(2A), 1.25% of S-TREA), with verbatim Art. 92(2A) quote, GCRA-vs-SA-T2 sign/base distinction, worked numeric illustration, and a CRR delta note (Art. 62 caps exist under both frameworks but the OF-ADJ linkage is B31-only). Plan-item misattribution corrected: D4.50 cited "Art. 92(3)(c)" but the cap locations are Art. 62(c) / Art. 62(d) of the Own Funds (CRR) Part — Art. 92(3) is the U-TREA composition list with no point (c) cap. Closes DOCS_IMPLEMENTATION_PLAN.md D4.50. Ref: PRA PS1/26 Art. 62(c), Art. 62(d), Art. 92(2A).
- **Art. 40 EL-shortfall DTA grossing-up rule explained in OF-ADJ context (`docs/specifications/basel31/output-floor.md`)**: the previous gloss "plus any supervisory deductions under Art. 40" in the IRB_CET1 component row mischaracterised CRR Art. 40 as a separate prudential filter / supervisory deduction. New "Art. 40 — no deferred-tax grossing-up of the EL-shortfall deduction" subsection adds verbatim CRR Art. 40 text and a plain-English explanation that Art. 40 is a *clarifier on Art. 36(1)(d)* — it forbids reducing the EL-shortfall deduction by a rise in deferred-tax assets reliant on future profitability. The component-table row now points at the new subsection rather than restating the misattribution. Engine-inputs note covers both the engine-derived `ELPortfolioSummary.cet1_deduction` path and the institution-supplied `OutputFloorConfig.art_40_deductions` scalar. Closes DOCS_IMPLEMENTATION_PLAN.md D4.51. Ref: CRR Art. 40, PRA PS1/26 Art. 92(2A).
- **Equity transitional 3-year window (Rules 4.4–4.10) distinguished from output-floor 4-year transitional (`docs/specifications/basel31/equity-approach.md`)**: the spec previously implied the SA equity transitional ran four years through 31 Dec 2030; PRA PS1/26 Annex C Chapter 4 Rule 4.2 chapeau is unambiguous that **both** the SA equity transitional (Rules 4.1–4.3) and the IRB equity/CIU opt-out transitional (Rules 4.4–4.10) run only **3 years** (1 Jan 2027 – 31 Dec 2029), with steady-state from 1 Jan 2030. Side-by-side comparative table now shows scope/dates/mechanism/opt-out for the two regimes, plus an info admonition warning against conflating equity transitional (3 years) with output-floor transitional (4 years, Art. 92(5)). Rules 4.4, 4.7, 4.9, 4.10 quoted verbatim from PS1/26 Appendix 1. Plan-item correction: D4.52 itself stated "SA equity transitional runs 4 years (2027-2030)" — the 4-year window is the output-floor transitional, not equity. Closes DOCS_IMPLEMENTATION_PLAN.md D4.52. Ref: PRA PS1/26 Annex C Chapter 4 Rules 4.1–4.11, Art. 92(5).
- **HVCRE Table B EL subgrade columns A/B/C/D surfaced (`docs/specifications/basel31/slotting-approach.md`)**: the B31 HVCRE expected-loss row was previously rendered as a single "Strong = 0.4%" entry without exposing the four subgrade columns that PS1/26 Appendix 1 Art. 158(6) Table B uses for both HVCRE and non-HVCRE rows. The HVCRE EL table is now expanded to four explicit columns (A/B/C/D) parallel to the existing Table A risk-weight subgrade structure (which DOES split: 70%/95%/95%/120%); Art. 158(6) Table B is quoted verbatim. Plan-item correction: D4.53 plan wording "Strong A = 0.4%, Strong = 0.8%" conflated HVCRE Table B (flat 0.4% across all four columns) with the non-HVCRE EL row (where Good C = 0.4% and Good D = 0.8%). Closes DOCS_IMPLEMENTATION_PLAN.md D4.53. Ref: PRA PS1/26 Appendix 1 Art. 153(5) Table A, Art. 158(6) Table B.
- **CRR Art. 121(4) trade-finance preferential 50%/20% for unrated institutions documented (`docs/specifications/crr/sa-risk-weights.md`)**: the institution section gains a dedicated Art. 121(4) subsection — verbatim Art. 121(4) (CRR p. 120), Art. 162(3) second subparagraph point (b) (p. 160), and Art. 4(1)(80) (p. 39) quotes; per-case RW table; cumulative eligibility checklist; B31 framework-delta callout flagging the SCRA restructuring and the absence of a flat-50% successor; implementation-status callout flagging the CRR calculator gap. Plan-item terminology correction: D4.55 wording said "50% (sovereign CQS 4-5) or 20% (sovereign CQS 1-3) under sovereign-derived approach" — Art. 121(4) is **not** CQS-keyed; the 50% is flat for all eligible trade-finance exposures (residual ≤ 1y), and 20% applies where residual ≤ 3 months. Closes DOCS_IMPLEMENTATION_PLAN.md D4.55. Ref: CRR Art. 121(4), Art. 162(3) second subpara point (b), Art. 4(1)(80).
- **PS1/26 Art. 132(8) "relevant CIU" PRA notification regime documented (`docs/specifications/basel31/equity-approach.md`)**: a new section covers the third-country-fund-manager notification trigger that previously had no doc surface — verbatim Art. 132(8)(a)–(d) (PS1/26 App 1 pp. 64–65) and Glossary "relevant CIU" definition (p. 27), plain-English summary, distinction from other CIU notification regimes, and a CRR comparison (Art. 132 omitted from UK CRR by SI 2021/1078; the regime is B31-only). Three plan-item misattributions recorded: (a) the cited articles **132(3A) / 132(3B) do not exist** — the actual provision is Art. 132(8); (b) **no AML/CFT trigger exists** anywhere in PS1/26 — the genuine trigger is the fund manager's third-country domicile, not establishment country, not AML/CFT assessment; (c) the threshold is **0.5% of credit-risk + dilution-risk RWA OR GBP 500m exposure value**, not "≥2% of own funds". The same new spec section also fully covers D4.66's misattributed Art. 132(4A) / GBP 2bn RWA / GBP 500m references — D4.66 should be closed in the next plan refresh. Closes DOCS_IMPLEMENTATION_PLAN.md D4.58. Ref: PRA PS1/26 Art. 132(8), Glossary p. 27.
- **CRR Art. 118(f) UK-exit deletion noted (`docs/specifications/crr/sa-risk-weights.md`)**: the Art. 118 0% list for international organisations was previously documented as the EU-onshored Art. 118 in full, with no flag that **item (f)** — the residual "two-or-more-Member-States international financial institution" catch-all — was omitted by **SI 2018/1401 reg. 116** with effect from 31 December 2020. New warning admonition under the existing International Organisations subsection sets out the pre-deletion EU text, the SI reference, and the practical effect (Art. 118 closes to items (a)–(e) only — IMF, BIS, EU, ESM, EFSF, EIB; cross-Member-State financial institutions no longer qualify under UK CRR). Plan-item misattribution corrected: D4.56 framed Art. 118 as "exposures to recognised exchanges" — Art. 118 is the international-organisations 0% list; recognised exchanges sit in Art. 107 / Art. 197–198. Closes DOCS_IMPLEMENTATION_PLAN.md D4.56. Ref: UK CRR Art. 118 (consolidated, footnote F266); The Capital Requirements (Amendment) (EU Exit) Regulations 2018, SI 2018/1401 reg. 116.
- **PS1/26 Art. 122B / Art. 139(2B) SA Specialised Lending in S-TREA documented (`docs/specifications/basel31/output-floor.md`)**: the SA SL framework introduced by PS1/26 Art. 122A–122B was previously absent from the output-floor spec — practitioners had no documented basis for how an IRB firm using SA for specialised lending under Art. 122A contributes to S-TREA. New section covers the Art. 122A sub-classification (Project Finance / Object Finance / Commodities Finance / IPRE / HVCRE) and Art. 122B routing (Art. 122B(1) rated → Table 5A short-term ECRA; Art. 122B(2)/(4) unrated ladder; Art. 122B(3) operational-phase definition; Art. 122B(5) high-quality criteria). The Art. 139(2B) ECAI rating-attribution rule is documented as a suppression of Art. 139(2)/(2A) inferred fallbacks when the rated SL pathway is invoked — **not** as a S-TREA exclusion. Plan-item factual correction: D4.59 wording — "IRB firms using SA for specialised lending do not include those exposures in the output floor SA-RWA calculation" — is **factually wrong**; SA SL exposures contribute to S-TREA in full (just routed through Art. 122B), and Art. 139(2B) is an ECAI rule, not a carve-out. Misattribution recorded inline via a warning admonition. Closes DOCS_IMPLEMENTATION_PLAN.md D4.59. Ref: PRA PS1/26 Art. 122A, Art. 122B(1)–(5), Art. 139(2)–(2B), Art. 92(2A).
- **PS1/26 Art. 143(6)–(8) Overseas Model Approach documented (`docs/specifications/basel31/model-permissions.md`)**: the new PS1/26 Overseas Model Approach (OMA) — a permission for UK-parent groups to apply a foreign supervisor-approved IRB approach to retail and SME corporate exposures of equivalent-jurisdiction overseas subsidiaries, capped at 7.5% of group RWA and 7.5% of group exposure value pre-output-floor — was completely absent from the docs. New top-level section covers Art. 143(6) substantive permission with the (a)–(k) conditions and the aggregate cap, Art. 143(7) grandfathering as a deeming provision for pre-2027 CRR Art. 143 PRA permissions, and Art. 143(8) ongoing-compliance obligation, with verbatim PS1/26 App 1 quotes (pp. 79, 83–84) and a CRR-vs-B31 delta (CRR has no structured OMA). Plan-item paraphrase corrected in three respects: (a) Art. 143(7) grandfathers an existing **PRA permission**, not a standalone overseas-regulator approval; (b) the mechanism is a **deeming provision**, not a notification; (c) the substantive OMA in Art. 143(6) is far narrower than the plan suggested — restricted to retail / SME corporate, equivalent-jurisdiction, with the 7.5% group caps. Closes DOCS_IMPLEMENTATION_PLAN.md D4.60. Ref: PRA PS1/26 Art. 143(6)(a)–(k), Art. 143(7), Art. 143(8), Glossary p. 79.
- **PS1/26 Art. 191A(2)(e),(f) two-layer protection look-through documented (`docs/specifications/basel31/credit-risk-mitigation.md`)**: the CRM spec previously had no description of the PS1/26 election allowing an institution to recognise funded collateral posted by an unfunded protection provider directly through the guarantee chain. New "Look-Through for Unfunded Protection Backed by Funded Protection (Art. 191A(2)(e), (f))" sub-section, slotted inside the existing CRM Method Taxonomy (Art. 191A) block, gives verbatim Art. 191A(2)(e) and (2)(f) (PS1/26 App 1 p. 168), a three-option election table (funded only / unfunded + funded jointly / Part-3-only fallback), the Art. 191A(2)(f) borrower-deeming flexibility, a CRR↔PS1/26 comparison flagging this as wholly new under PS1/26, cross-references to FCSM/FCCM/Foundation Collateral Method/PSM/RWSM and Art. 237–239, and an implementation-status admonition flagging the engine gap. Plan-item misattribution corrected: D4.61 cited "Art. 191A(4)" — the actual provision is Art. 191A(2)(e)/(f); Art. 191A(4) is an unrelated cross-reference scoping rule for Articles 192–239 absent an explicit cross-reference. Closes DOCS_IMPLEMENTATION_PLAN.md D4.61. Ref: PRA PS1/26 Art. 191A(2)(e)–(f), Part 4 of Appendix 1.
- **CRR Art. 132 paragraph references corrected in CRR equity spec (`docs/specifications/crr/equity-approach.md`)**: the CRR equity spec previously labelled CIU look-through and mandate-based approaches with PRA PS1/26 article numbers (132A / 132B). Under the historical UK CRR — before SI 2021/1078 omitted Art. 132 effective 1 Jan 2022 — these were paragraphs within Art. 132 itself: para 4 = look-through, para 5 = mandate-based. Article numbers throughout the CRR-context tables, section headings (CIU Treatment, Look-Through Approach, Mandate-Based Approach, Fallback Approach), the FR-1.7b requirements row, the CRR-J15 acceptance scenario, and the CRR-J16 third-party multiplier note are now retitled with pre-omission paragraph citations (Art. 132(4) / Art. 132(5) / Art. 132(2)). New top-of-page warning callout summarises the regulatory history: SI 2021/1078 omission, PRA Rulebook (CRR Part) housing through 31 Dec 2026, and PRA PS1/26 reintroduction as Art. 132A / 132B / 132C from 1 Jan 2027. Cross-links to `basel31/equity-approach.md` for the Art. 132A treatment. Closes DOCS_IMPLEMENTATION_PLAN.md D4.65. Ref: CRR Art. 132(2), (4), (5) (pre-omission); SI 2021/1078; PRA PS1/26 Art. 132A, 132B, 132C.
- **CRR Art. 150(1)(a)–(j) permanent partial use spec mirroring B31 (`docs/specifications/crr/model-permissions.md`)**: previously no spec file documented the CRR Art. 150 PPU framework — practitioners had to reverse-engineer the conditions for SA-within-IRB from `IRBPermissions` / `permission_mode` config code. The new spec is a CRR-side mirror of `basel31/model-permissions.md` so the two pages diff cleanly. Contents: a sunset warning that CRR Art. 150 expires 31 Dec 2026 with cross-link to PS1/26 Art. 150(1A); verbatim Art. 150(1) opening and conditions (a)–(j) (`crr.pdf` pp. 145–146); plain-English summary table covering each condition, plus admonitions on the (a)/(b) "limited material counterparties" two-limb test, the qualitative immateriality test in (c) (vs B31's numeric thresholds), the SI 2018/1401 UK-Exit re-targeting of (d), and the standalone 10% own-funds cap in (h); verbatim Art. 150(2) text plus a tier table (10% threshold for ≥10 holdings, 5% for <10 holdings) with a worked example; a 10-row CRR↔B31 comparison table; and an Engine Inputs section showing how each Art. 150(1)(a)–(j) condition is (or is not) encoded. Plan-item correction: there is no `apply_partial_ppu` flag on `CalculationConfig` — PPU under the engine is implicit in `IRBPermissions` (a class with `permitted={SA}` is effectively PPU for that class). Closes DOCS_IMPLEMENTATION_PLAN.md D4.64. Ref: CRR Art. 150(1)(a)–(j), Art. 150(2); PRA PS1/26 Art. 150(1A).
- **OF 08.01 col 0260 (post-adjustment RWEA) documented (`docs/specifications/output-reporting.md`)**: the OF 08.01 column list jumped from col 0254 to col 0265 with no entry for the intermediate col 0260. Per PS1/26 Annex II §3.3.1 p. 112, col 0260 = "Risk-Weighted Exposure Amount After Adjustments" = `0251 + 0252 + 0253 + 0254` and is the post-adjustment RWEA feeding OF 02.00 row 0010. Now inserted in the correct PDF order between cols 0254 and 0265. Closes DOCS_IMPLEMENTATION_PLAN.md D4.69. Ref: PRA PS1/26 Annex II §3.3.1 p. 112.
- **OF 08.07 row 0270 / col 0180 PPU formulas documented (`docs/framework-comparison/reporting-differences.md`)**: rows 0260/0270 were previously listed as "Added" without their formulas, leaving COREP implementers to reverse-engineer the Art. 150(1A) PPU materiality calculations from the Annex II PDF. Now expanded with verbatim PS1/26 Annex II formulas: col 0160 = `col 0100 / CA2 row 0040` (Art. 150(1A)(c)), col 0170 = `sum(0110+0120) / (col_0060 - col_0070)` (Art. 150(1) last subparagraph), and col 0180 / row 0270 = `row_0260_col_0120 / sum(col_0060 for rows 0180-0250 where col_0150 > 0)` (Art. 150(1A)(e)). Cross-link to `basel31/model-permissions.md` instead of duplicating the Art. 150(1A) materiality regime. Plan-item factual correction: D4.71 stated row 0270 / col 0180 uses `sum(0110+0120)/(col_0060-col_0070)` — that formula actually defines col 0170; col 0180 / row 0270 uses the Art. 150(1A)(e) formula (row 0260 col 0120 / Σ col 0060 for material rows). Closes DOCS_IMPLEMENTATION_PLAN.md D4.71. Ref: PRA PS1/26 Annex II §3.3 OF 08.07 pp. 134–136.
- **UKB CR7-A PDF col labelling typo flagged (`docs/framework-comparison/disclosure-differences.md`)**: PRA PS1/26 Annex XXII p. 14 reuses col (n) for unfunded credit protection on slotting exposures (intended label is col (p)). Existing UKB CR7-A column-changes table already showed the corrected o/p sequence; new warning admonition documents the PDF typo so implementors do not follow the PDF literally. Closes DOCS_IMPLEMENTATION_PLAN.md D4.73. Ref: PRA PS1/26 Annex XXII p. 14.
- **CRR double-default eligibility, RW floor, and A-IRB precondition corrected in user-guide CRM (`docs/user-guide/methodology/crm.md`)**: the user-guide double-default subsection previously cited "Art. 153(3) paragraph 2" for the RW floor (Art. 153(3) para 2 is blanked under PS1/26 — the CRR floor lives elsewhere), gave an ambiguous "CQS 2 or better (CQS 3 maintained threshold)" guarantor eligibility wording inconsistent with CRR Art. 202, and omitted the A-IRB own-LGD precondition entirely. The RW floor citation is now CRR Art. 161(3) (the comparable-direct-exposure-to-guarantor floor); the CQS threshold is rebuilt from verbatim Art. 202(b)/(c)/(d) (ECAI ≥ CQS 3 at provision; historical PD ≤ CQS 2; current PD ≤ CQS 3); the A-IRB own-LGD chain (Art. 153(3) → Art. 161(4) → Art. 161(3)) is set out explicitly with the F-IRB fall-back to Art. 235/236 substitution. Underlying-exposure scope re-stated to match Art. 153(3) (corporate, institution, central government/CB, retail SME via Art. 154(2)) — replacing the prior incorrect "RGLA/PSE" claim. Closes DOCS_IMPLEMENTATION_PLAN.md D4.76. Ref: CRR Art. 153(3), Art. 154(2), Art. 161(3)–(4), Art. 202; PRA PS1/26 (Art. 153(3) para 2 blanked).
- **Art. 155(2) short-position netting and Art. 155(4) IMA floor added to user-guide equity (`docs/user-guide/methodology/equity.md`)**: the user-guide page documented the IRB Simple RW table (190%/290%/370%) but two material Art. 155 sub-rules — already present in the CRR equity spec — were missing from the practitioner reference. Added subsections on (a) Art. 155(2) short-position netting (short cash positions and non-trading-book derivatives may offset long positions in the same individual stock only if the hedge is explicit and covers ≥ 1 year; otherwise treated as long with the RW applied to the absolute value) and (b) Art. 155(4) IMA approach (12.5 × VaR-derived potential loss; portfolio RWEA must not be lower than `PD/LGD RWEA + EL × 12.5` using Art. 165(1)/(2) PD floors and LGDs). Cross-link to `crr/equity-approach.md` for the canonical Art. 155 RW table; B31 framework-delta callout flags PS1/26 Art. 147A removal of IRB Equity Approach with the Rules 4.4–4.10 transitional path. Art. 155(3) per-exposure cap deliberately not pre-empted (owned by D4.79). Closes DOCS_IMPLEMENTATION_PLAN.md D4.77. Ref: CRR Art. 155(2), Art. 155(4), Art. 165(1)–(2); PRA PS1/26 Art. 147A, Annex C Chapter 4 Rules 4.4–4.10.
- **Art. 155(3) PD/LGD per-exposure cap added to user-guide equity (`docs/user-guide/methodology/equity.md`)**: CRR Art. 155(3) caps the PD/LGD-approach capital for any individual equity exposure at a 100% loss assumption (`EL × 12.5 + RWEA ≤ EAD × 12.5`), but the user-guide page only mentioned the cap inline as a contrast within the Art. 155(4) IMA-floor warning callout — easily overlooked by practitioners scanning for PD/LGD mechanics. New dedicated "PD/LGD Approach Per-Exposure Cap (Art. 155(3))" subsection sits between Short-Position Netting and the IMA section, with verbatim cap formula, a non-binding worked example (EAD=£100, PD=0.40%, LGD=90% → LHS ≈ £374.50 ≪ RHS = £1,250) and a binding example showing the cap reducing PD/LGD RWEA from £1,500 to £350 for a near-default exposure with the Art. 155(3) 1.5× scaling factor applied. Cross-references the canonical PD/LGD parameter table in `crr/equity-approach.md` rather than duplicating it. PRA PS1/26 Art. 147A removal callout flags that the cap has no Basel 3.1 successor. Implementation-status note records that the calculator currently implements only Art. 155(2) Simple Risk Weight Approach (PD/LGD approach is `IMPLEMENTATION_PLAN.md` P1.153 follow-up), so the per-exposure cap does not bite in any current calculation path. Closes DOCS_IMPLEMENTATION_PLAN.md D4.79. Ref: CRR Art. 155(3), Art. 153(1), Art. 165(1)–(3); PRA PS1/26 Art. 147A.
- **UKB OV1 pre-floor capital ratio rows documented (`docs/features/pillar3-disclosures.md`)**: Pillar 3 OV1 row table previously listed only rows 1–5, 11–14, 24, 26, 27, 29 — missing the seven UKB-specific pre-floor rows (4a Total RWEAs (pre-floor); 5a/5b CET1; 6a/6b Tier 1; 7a/7b Total capital pre-floor capital ratios). These rows are mandatory under PRA PS1/26 Annex XX for output-floor-active institutions so market participants can see the pre-floor capital position separately from the post-floor figures driven by Art. 92(5). Cross-references to `framework-comparison/disclosure-differences.md` (lines 31, 63–64) carry the canonical CRR-vs-Basel 3.1 row delta. The corresponding `B31_OV1_ROWS` gap in `src/rwa_calc/reporting/pillar3/templates.py` is routed to IMPLEMENTATION_PLAN.md as a separate code-side P-coded item. Closes DOCS_IMPLEMENTATION_PLAN.md D4.81. Ref: PRA PS1/26 Annex XX (Disclosure (CRR) Part Art. 438(d)), Art. 92(5).
- **CRR Art. 137 ECA score open-gap surfaced in CRR SA spec (`docs/specifications/crr/sa-risk-weights.md`)**: the previous "Implementation Status" note at the end of the Art. 137 ECA section understated the gap as a "future enhancement" with no mention of which inputs the engine actually accepts today. Replaced with a new `### Art. 136 vs Art. 137 — two distinct mappings` subsection (clarifying that Art. 136 routes ECAI grades through the CQS pipeline and Art. 137 routes OECD MEIP integers 0–7 directly through Table 9 to risk weights) followed by an explicit "Open Gap" warning admonition. The admonition records that the engine accepts only a raw `credit_quality_step` integer (no ECAI grade strings, no MEIP integers), enumerates what a complete implementation would need (input-schema field for either an ECAI grade or an Art. 137 MEIP integer 0–7, static lookup table in `data/tables/`, Art. 114/121 sovereign-derived wiring, Art. 138 multi-assessment selection logic), and surfaces the engine work for `IMPLEMENTATION_PLAN.md` tracking. Verbatim Art. 137 Table 9 (0%/0%/20%/50%/100%/100%/100%/150%) PDF-verified against `docs/assets/crr.pdf` p. 135. Closes DOCS_IMPLEMENTATION_PLAN.md D4.74. Ref: CRR Art. 136(1)–(2), Art. 137(1)–(2) Table 9.
- **UKB CR8 signed-flow convention documented (`docs/features/pillar3-disclosures.md`)**: the Pillar 3 disclosures page CR8 section previously showed only the row structure with no sign convention, leaving template consumers to infer the direction of flow rows 2–8 from the spec page or the PRA Annex XXII text. New `!!! warning` admonition under the row-structure table records that flow rows 2–8 use signed values (increases positive, decreases negative; example: a £15m RWEA decrease emits as `-15`) and cross-references the canonical sign-convention list at `docs/specifications/output-reporting.md` lines 349 / 356–366 instead of duplicating spec text. The corresponding `_generate_cr8` gap in `src/rwa_calc/reporting/pillar3/generator.py` (rows 2–8 currently emitted as `None` because multi-period comparison data is not wired through the pipeline) is surfaced for IMPLEMENTATION_PLAN.md routing — the implementation must honour the signed convention when prior-period inputs are added. Closes DOCS_IMPLEMENTATION_PLAN.md D4.82. Ref: PRA PS1/26 Annex XXII §11 (UKB CR8 instructions).
- **UKB CMS1 / CMS2 col d ↔ OF-ADJ / GCRA reconciliation surfaced (`docs/features/pillar3-disclosures.md`)**: the Pillar 3 page documented CMS1 col d as "RWA calculated using full standardised approach" without flagging that this is the **pre-OF-ADJ** S-TREA input matching OF 02.01 col 0040 — i.e. the S-TREA leg of `TREA = max{U-TREA; x · S-TREA + OF-ADJ}` before the floor multiplier and OF-ADJ are applied. New "Col d — pre-OF-ADJ S-TREA input" subsection on UKB CMS1 carries verbatim Art. 92(2A) (PS1/26 App 1 p. 13), an info admonition explaining how CMS1 col d gates GCRA T2 capacity through the 1.25%-of-S-TREA cap (Art. 62(c)), and cross-links to `specifications/basel31/output-floor.md` (formula derivation + GCRA/SCRA boundary) and `specifications/output-reporting.md` (COREP mapping). The UKB CMS2 section gains a parallel "Col d — pre-OF-ADJ S-TREA at asset-class granularity" subsection confirming CMS2 col d carries the same pre-OF-ADJ semantics as CMS1 col d (asset-class breakdown of the same population) and pointing back to the CMS1 admonition rather than duplicating the formula. Closes DOCS_IMPLEMENTATION_PLAN.md D4.83. Ref: PRA PS1/26 App 1 Art. 92(2A), Art. 62(c).
- **QCCP guarantor RW override (Art. 306) surfaced in user-guide CRM (`docs/user-guide/methodology/crm.md`)**: `engine/irb/guarantee.py::_compute_guarantor_rw_sa` overrides the substituted guarantor risk weight to 2% (proprietary) or 4% (client-cleared) when the guarantor is a qualifying central counterparty (gated by `guarantor_entity_type == "ccp"` and `guarantor_is_ccp_client_cleared`), but the user-guide CRM page never referenced Art. 306 — practitioners had to read the engine source to discover the override. New "Qualifying CCP (QCCP) Guarantor Override (CRR Art. 306)" subsection inside the existing Guarantees section sets out the trigger flags, the 2% / 4% RW table with CRE54.14 / CRE54.15 cross-references, the ordering versus the institution CQS lookup, a scope warning (trade-exposure RW only — default-fund contributions go through Art. 308 / CRE54.16 separately), a worked example, and cross-links to the Institution exposure-class page (CCP anchor) and `specifications/output-reporting.md` (COREP rows 0150 / 0160). Closes DOCS_IMPLEMENTATION_PLAN.md D4.85. Ref: CRR Art. 306(1)(a)–(b), Art. 308; PRA PS1/26 Art. 306; BCBS CRE54.14, CRE54.15, CRE54.16.
- **Art. 232 life-insurance spec ↔ output-column cross-reference + worked example (`docs/specifications/basel31/credit-risk-mitigation.md`)**: the B31 CRM spec described the Art. 232 7-tier insurer-RW → secured-portion-RW mapping (20% / 35% / 70% / 150%) and the F-IRB LGD<sub>S</sub>=40% rule but did not link these mechanics to the engine output columns `life_ins_collateral_value` / `life_ins_secured_rw` produced by `engine/crm/life_insurance.py::compute_life_insurance_columns` and consumed during SA blending by `lf.sa.apply_life_insurance_rw_mapping()`. The previous stale `!!! warning "Output-column naming documented separately"` admonition (referencing the now-closed D3.53 / D2.48) is replaced with (a) a new `#### Spec ↔ Output-Column Cross-Reference` subsection — a 5-row table mapping each Art. 232 mechanic to the engine column, default-value behaviour, and `engine/crm/life_insurance.py` / `engine/sa/namespace.py` line numbers — and (b) a new `#### Worked Example` subsection — a fully traced 6-step calculation using a 30% insurer SA RW (SCRA Grade A enhanced, Art. 121(5)) → 35% secured-portion RW (Art. 232(3)(b)) → blended 0.61 RW = GBP 610,000 RWA versus GBP 1,000,000 unmitigated. Closes DOCS_IMPLEMENTATION_PLAN.md D4.86. Ref: PRA PS1/26 App 1 Art. 232(A1), (2)(a), (2)(b), (3)(a)–(d); Art. 121(5); Art. 200(b), Art. 212(2); Art. 233(3)–(4).
- **CRR Art. 129(5) covered bond unrated-derivation framework boundary clarified (`docs/specifications/crr/sa-risk-weights.md`)**: the CRR covered bond unrated-derivation section previously documented the four sub-paragraphs (a)–(d) without flagging that the shared `COVERED_BOND_UNRATED_DERIVATION` dict in `crr_risk_weights.py` carries 7 entries (3 of which — 30%, 40%, 75% institution RWs — derive from PS1/26 SCRA Grade A/B and CQS 2 ECRA paths that do not exist in CRR). Practitioners reading the dict comment "CRR Art. 129(5), PRA PS1/26 Art. 129" risked treating the larger entry set as authoritative under both frameworks. New verbatim CRR Art. 129(5)(a)–(d) quote (`crr.pdf` p. 129) plus warning admonition explaining only four CRR institution RWs (20/50/100/150 from Art. 120 Table 3 and Art. 121 Table 5) drive Art. 129(5), producing 10/20/50/100 covered bond RWs; the 30%/40%/75% institution inputs driving PS1/26 sub-paragraphs (aa)/(ab)/(ba) (`ps126app1.pdf` pp. 61–62) cannot arise under CRR. Implementation-note admonition records that the dict comment reflects shared storage, not framework equivalence. Cross-links to in-page B31 covered bond changes section and `basel31/sa-risk-weights.md` unrated-covered-bonds section. Code-side structural fix continues under DOCS_IMPLEMENTATION_PLAN.md D3.29. Closes DOCS_IMPLEMENTATION_PLAN.md D4.62. Ref: CRR Art. 129(5); PRA PS1/26 Art. 129(5).
- **UKB CR9 row breakdown rewritten to PS1/26 Annex XXII column-a verbatim sub-classes (`docs/features/pillar3-disclosures.md`)**: the Pillar 3 disclosures page CR9 section previously listed compact row labels (institutions / corporates with SL / "other general corporates SME/non-SME") that did not match the verbatim PRA PS1/26 Annex XXII column-`a` sub-classes for either approach. F-IRB CR9 was missing the "Financial corporates and large corporates" row (Art. 147(2)(c)(ii) / Art. 147A driver) that already appears in CR6, leaving the two templates inconsistent for the same population. Rewritten to use the full numbered hierarchy: A-IRB rows 1.1–1.3 (corporates) and 2.1–2.7 (RRE-SME, RRE-non-SME, CRE-SME, CRE-non-SME, QRRE, Other-SME, Other-non-SME); F-IRB rows 1, 2.1 SL, 2.2 financial corporates and large corporates, 2.3–2.4 other general corporates SME/non-SME, 3 total, per `ps1-26-annex-xxii-credit-risk-irb-disclosure-instructions.pdf` pp. 19–20. Cross-references the CR6 H2 anchor so the F-IRB sub-class 2.2 is recognisable as the same row in both templates; Reference Documents block expanded with verified PDF page numbers (Annex XXII p. 18 paras 12–15; pp. 19–20 column `a`; pp. 20–22 columns `b`–`h`; `ps126app1.pdf` Art. 147(2)(b)–(d) and Art. 147A). Plan-item observation: D4.84's "missing financial corporates and large corporates row" framing was stale relative to the current file state — that row was already present from commit `3d3b346`; the residual docs gap was the absence of a CR6 cross-reference and the use of compact / non-verbatim row labels. The corresponding `CR9_FIRB_CLASSES` and `CR9_AIRB_CLASSES` gaps in `src/rwa_calc/reporting/pillar3/templates.py` (missing F-IRB sub-classes 2.2 and 2.4, missing A-IRB sub-class 1.3, and the seven retail sub-classes 2.1–2.7) are routed to IMPLEMENTATION_PLAN.md as a separate code-side P-coded item. Closes DOCS_IMPLEMENTATION_PLAN.md D4.84. Ref: PRA PS1/26 Annex XXII paras 12–15; column `a` row definitions on pp. 19–20.

### Changed
- (Next release changes will go here)

### Fixed
- **IRB maturity-adjustment formula now honours the CRR Art. 162(3) carve-out from the 1-year M floor (`engine/irb/formulas.py::_maturity_adjustment_expr_from_pd`)**: under CRR Art. 162(3) (mirrored by PRA PS1/26 / BCBS CRE32.50), four transaction types are exempt from the 1-year M floor in the IRB maturity-adjustment formula and may use M down to 1 day — daily-margined SFTs (repo / securities lending), daily-margined derivatives, margin-lending transactions, and short-term self-liquidating trade transactions (e.g. import/export LCs). The repo already had the *upstream* plumbing to set `maturity = 1/365` for these rows (priority chain in `engine/irb/namespace.py::IRBLazyFrame.prepare_columns` lines 243-318, gated on the `has_one_day_maturity_floor` boolean column) but the *formula itself* re-applied a hardcoded `clip(1.0, 5.0)` to `maturity` inside `_maturity_adjustment_expr_from_pd`, silently undoing the carve-out: a contingent with `is_short_term_trade_lc=True` and `effective_maturity=0.1` showed `maturity = 0.1` in the output but `maturity_adjustment = 1.0` and `rwa` identical to a 1-year exposure — zero capital relief despite the regulatory carve-out being in scope. The fix gates the 1-year floor on the `has_one_day_maturity_floor` column: when True, the floor is suppressed and the actual maturity flows through; when False/null/missing, the existing `[1.0, 5.0]` clip applies (so ordinary corporate IRB exposures see no behaviour change). The 5-year cap from Art. 162(2) remains unconditional (no carve-out). Worked numbers at PD=0.5%, M=0.1, LGD=45%, EAD=£1m: old behaviour MA=1.0 → RWA=£521,650; new behaviour MA=0.799 → RWA=£416,969 — a 20% relief. Magnitude of relief scales with PD via the b coefficient (≈15-25% across the realistic PD range for non-defaulted exposures). The wrong behaviour was previously pinned by `tests/unit/irb/test_irb_formulas.py::test_ma_below_floor_clipped` and `tests/unit/crr/test_crr_irb.py::test_maturity_floor` which asserted that M=0.5 produced the same MA as M=1.0 — both replaced with two-case tests covering with-flag and without-flag behaviour. Scalar `calculate_maturity_adjustment` gains a `has_one_day_maturity_floor: bool = False` parameter (kwarg-only by signature ordering); positional callers (which all use `(pd, maturity)`) are unaffected. Column visibility threaded through every vectorised call site — `apply_irb_formulas`, `_parametric_irb_risk_weight_expr`, `IRBLazyFrame.prepare_columns`, `IRBLazyFrame.calculate_maturity_adjustment`, `IRBLazyFrame.apply_all_formulas`, `engine/irb/guarantee.py::apply_guarantee_substitution` — each default-adds `has_one_day_maturity_floor=False` when missing, so existing fixtures and inputs that do not set the flag continue to work. New regression coverage in `tests/contracts/test_one_day_maturity_floor_propagation.py` pins (a) schema declaration on FACILITY_SCHEMA / LOAN_SCHEMA / CONTINGENTS_SCHEMA, (b) `prepare_columns` flag preservation and default-add, (c) end-to-end MA<1.0 with carve-out under both CRR and B31, (d) MA=1.0 without carve-out, and (e) bounded RWA relief at 10%-50%. Follow-up tracked: full agent-driven `B31-IRB-MAT-CARVEOUT` / `CRR-IRB-MAT-CARVEOUT` acceptance scenarios with golden outputs covering all four trigger types (currently the contract suite covers the formula behaviour and end-to-end pipeline through `apply_all_formulas`, but not the loader → hierarchy → classifier → CRM → IRB → aggregator full pipeline with pre-baked fixtures). Auto-derivation of `has_one_day_maturity_floor` from `is_short_term_trade_lc` deliberately deferred — firms must currently set the carve-out flag explicitly, and the engine treats it as the single regulatory switch into Art. 162(3). Full suite: 5,566 passed; arch_check clean. Ref: CRR Art. 153(1)(iii), Art. 162(2), Art. 162(3); PRA PS1/26 (mirrored); BCBS CRE32.46, CRE32.50.
- **FX collateral haircut now uses 20-day secured-lending default per CRR Art. 224(2)(a) / PS1/26 Art. 224(2)(a) (`engine/crm/processor.py::_build_exposure_lookups` + `_join_collateral_to_lookups`, `engine/crm/haircuts.py::apply_haircuts`)**: the FX collateral haircut Hfx previously defaulted to a 10-day liquidation period (8%) for *all* exposures regardless of transaction type, when the regulatory baseline for secured lending (a vanilla loan facility plus collateral) is **20 business days** under CRR Art. 224(2)(a) — giving Hfx = 8% × √(20/10) = **11.314%** after the Art. 226(2) square-root-of-time scaling. The constants `LIQUIDATION_PERIOD_REPO=5 / _CAPITAL_MARKET=10 / _SECURED_LENDING=20` already lived in `data/tables/haircuts.py:146-148` but were unused — `is_sft` from the exposure schemas was not propagated onto collateral. Worked example for the FX-mismatch scenario that motivated the fix: £1m GBP loan facility secured by €500k EUR cash collateral. Old behaviour: adjusted collateral = 500k × (1 - 0.08) = **£460,000**, EAD = £540,000, RWA = £540,000 (8% Hfx — wrong period). New behaviour: adjusted collateral = 500k × (1 - 0.11314) = **£443,431.46**, EAD = £556,568.54, RWA = £556,568.54 — a **3.07% RWA understatement** corrected on every FX-mismatched secured-lending exposure. The fix has two layers: (1) `_build_exposure_lookups()` now captures `is_sft` from each exposure level (direct/facility/cp), and `_join_collateral_to_lookups()` resolves them into a single `exposure_is_sft` Boolean column on collateral; (2) the unconditional `fill_null(10)` in `apply_haircuts` is replaced with: explicit per-collateral `liquidation_period_days` override → `LIQUIDATION_PERIOD_REPO` (5) when `exposure_is_sft=True` → `LIQUIDATION_PERIOD_SECURED_LENDING` (20) otherwise. **Guarantees deliberately untouched** — Art. 233(4) fixes guarantee Hfx at the 10-day liquidation period regardless of the underlying transaction type, so the flat 8% in `engine/crm/guarantees.py` remains correct. Acceptance impact: CRR-D2 / CRR-D3 / CRR-D6 and B31-D2 / B31-D3 / B31-D6 expected RWAs re-baselined upward to reflect the 20-day default (the collateral asset haircut Hc also scales by the same factor — gilt 0.5% → 0.707%, FTSE-100 equity 15% → 21.213%); golden JSON updated under `tests/expected_outputs/{crr,basel31}/`. 32 unit tests pinned the buggy 10-day default by omission — all updated either with explicit `liquidation_period_days=10` overrides (when the test was probing haircut-lookup behaviour, not period scaling) or with re-baselined expectations citing P1.186 (when the test was specifically about the default contract). New regression tests in `tests/unit/crm/test_collateral_fx_mismatch.py::TestP1186DefaultLiquidationPeriod` pin both the 20-day secured-lending default (`fx_haircut == 0.113137`) and the 5-day SFT default (`fx_haircut == 0.056569`) end-to-end through the processor join. Closes the `liquidation_period as config` outstanding item from P6.15 / D2.39. Full suite: 5,566 passed (23 skipped, 11 deselected); arch_check, ruff, ty all clean. Ref: CRR Art. 224(2)(a)–(c), Art. 226(2); PRA PS1/26 Art. 224(2)(a)–(c), Art. 226(2); Art. 233(4) (guarantee carve-out preserved). (P1.186.)
- **Facility undrawn now nets netting-flagged negative drawn balances per CRR Art. 195/219 / PS1/26 Art. 195/219 (`engine/hierarchy.py::_aggregate_loan_drawn_per_facility`, `_per_sub_drawn` inner helper of MOF undrawn waterfall)**: the per-facility drawn aggregation previously applied `.clip(lower_bound=0.0)` per row before summing, so a deposit booked as a negative-drawn loan under an on-balance-sheet netting agreement contributed 0 to facility utilisation instead of offsetting positive siblings. Worked example for the user request that motivated the fix: Fac_01 limit £100m with Loan_01 £60m, Loan_02 £60m, and Loan_03 -£40m carrying `has_netting_agreement=True`. Old behaviour: total_drawn = 120m → undrawn = max(0, 100-120) = 0m (the facility undrawn row was entirely suppressed by the existing `undrawn_amount > 0` filter). New behaviour: total_drawn = 80m → undrawn = 20m, matching the regulatorily-correct net headroom. The aggregation now uses a netting-aware expression — positives always sum normally; negatives contribute only when the loan carries `has_netting_agreement=True`. Negatives without the flag remain clipped to 0 (data-quality guard, preserving the historical contract verified by the existing `test_negative_drawn_amount_treated_as_zero`, `test_mixed_positive_negative_drawn_amounts`, and `test_all_negative_drawn_amounts` tests). The same netting-aware logic is applied to the `_per_sub_drawn` helper used by the MOF sub-facility undrawn waterfall so a netting-flagged deposit mapped to a sub-facility offsets that sub's utilisation rather than the parent's. The downstream CRM `generate_netting_collateral` stage (`engine/crm/collateral.py`) was already correct — it generates synthetic cash collateral pro-rata across positive siblings under the netting facility — and is unchanged; this fix is strictly upstream at facility utilisation. Defensive fallback: when the loans frame lacks `has_netting_agreement` (direct unit-test callers), the original clip-at-0 behaviour is used. Schema column `has_netting_agreement` (default `False`) was already present on `LOAN_SCHEMA`. New unit tests in `tests/unit/test_hierarchy.py`: `test_netting_negative_drawn_offsets_facility_utilisation` (the user's exact 60+60-40 scenario asserting `undrawn_amount=20m`) and `test_negative_drawn_without_netting_flag_still_clipped` (regression — negative without flag still suppresses the undrawn row). Out of scope (tracked as follow-ups, agreed with user): pro-rata vs first-positive netting-collateral allocation policy (current pro-rata is defensible per CRR Art. 219 silence on allocation order); contingent-side parallel clip in `_aggregate_contingent_per_facility` (negative ONB contingents under a netting agreement is unusual). Full suite: 5,554 passed (2 skipped, 4 deselected); arch_check, ruff, ty all clean. Ref: CRR Art. 195 (recognition), Art. 219 (treatment as cash collateral), Art. 228(1) SA / Art. 228(2) FIRB; PRA PS1/26 Art. 195, Art. 219(1) (new unified EAD-reduction formula), Art. 228(1) — verified by direct extraction from `docs/assets/crr.pdf` p.191/211 and `docs/assets/ps126app1.pdf` p.170/190.

---





## [0.2.9] - 2026-05-04

### Changed
- Version bump for PyPI release

---

## [0.2.8] - 2026-05-04

### Changed
- Version bump for PyPI release

---

## [0.2.7] - 2026-05-04

### Changed
- Version bump for PyPI release

---

## [0.2.6] - 2026-05-03

### Changed
- Version bump for PyPI release

---

## [0.2.5] - 2026-05-02

### Fixed
- **Collateral CRM now nets against CCF=100% E per CRR Art. 223(4) / PS1/26 Art. 223(4) (`engine/crm/processor.py::_initialize_ead`, `engine/crm/collateral.py::_apply_collateral_unified`, `engine/ccf.py::_compute_ead`)**: the CRM stage previously netted collateral against `ead_gross = on_bal + nominal × CCF` (post-CCF) for off-balance-sheet exposures, both in the FIRB LGD\* formula and in the SA `ead_after_collateral` reduction. Both **CRR Art. 223(4)** and **PRA PS1/26 Art. 223(4)** explicitly require the **opposite**: when computing the exposure value `E` used for CRM (financial collateral via FCCM, other eligible collateral via the Foundation Collateral Method, and the C\*/C\*\* threshold tests in Art. 230), off-balance-sheet items shall be valued at **100% of nominal**, overriding the regulatory CCF. The actual CCF re-couples afterwards: under SA per Art. 228(1) the CCF is applied to `E*`, while under FIRB the actual CCF stays in EAD but is absent from the LGD\* ratio. Phil's worked example (100m off-BS FIRB, 75% CCF, 50m cash, senior unsecured): pre-fix code produced LGD\* = 15%, regulation requires LGD\* = 22.5% — code under-stated FIRB LGD by 7.5pp on this exposure. Under SA the same shape under-stated EAD: 100m off-BS, 50% CCF, 30m cash gave EAD = 20m; regulation requires `(100−30) × 0.5 = 35m`. Fix introduces two new columns on the exposures frame computed in `_initialize_ead`: `ead_for_crm = on_bs_for_ead + nominal_after_provision` (CCF=100% basis, used by all CRM-ratio sites) and `effective_ccf = ead_pre_crm / ead_for_crm` (used to recouple the actual CCF in SA's post-collateral EAD). `ead_gross` (post-CCF) is **kept** unchanged in the schema — multiple downstream sites legitimately need the actual EAD that flows through to RWA. Migrated sites: collateral pro-rata weights for facility / counterparty pools (`_build_exposure_lookups` in `processor.py` and `_apply_collateral_unified` in `collateral.py`), `_generate_netting_collateral` allocation, Art. 230 RE 30% threshold cap, the Art. 231 sequential-fill waterfall denominator, the FIRB LGD\* formula numerator and denominator, `collateral_coverage_pct`, and the SA `ead_after_collateral` formula (rewritten from `(ead_gross − collateral_adjusted_value)+` to `(ead_for_crm − collateral_adjusted_value)+ × effective_ccf` per Art. 228(1)). Pure on-BS rows are unaffected (`ead_for_crm == ead_gross` by construction). FIRB / Slotting `ead_after_collateral` continues to equal `ead_gross` (collateral modifies LGD, not EAD, under those approaches). AIRB is unaffected (uses own LGD estimate). The CCF stage in `engine/ccf.py` now persists the on-BS portion of EAD as a column `on_bs_for_ead` (previously a local variable), enabling `_initialize_ead` to compose `ead_for_crm` without recomputing the drawn / interest / provision adjustments. Defensive fallbacks added to `apply_collateral`, `_apply_collateral_unified`, `_build_exposure_lookups`, and `_generate_netting_collateral` so direct unit-test callers that hand-build exposures frames with `ead_gross` only continue to work (default `ead_for_crm = ead_gross`, `effective_ccf = 1.0` — semantically correct for pure on-BS rows). New unit tests in `tests/unit/crm/test_ead_for_crm.py` (8 tests): pure on-BS, pure off-BS independent of CCF (SA + FIRB), mixed on-BS+off-BS row blended `effective_ccf`, provision-on-nominal reduces `ead_for_crm`, zero-nominal divide-by-zero guard, and two end-to-end pins through the full CRM processor — Phil's worked FIRB cash example asserting `lgd_post_crm == 22.5%`, and the SA off-BS analogue asserting `ead_after_collateral == 35m`. **Out of scope for this fix (tracked as follow-ups)**: guarantees Art. 235 / 236 (same regulatory shape — `E` with CCF=100% override — but a separate code surface in `engine/crm/guarantees.py`); life insurance under Art. 232 (routes via Art. 235 / 236, not FCCM/FCM, so falls under the guarantees follow-up); AIRB CRM under Art. 191A LGD Adjustment Method (uses own-estimate LGDs, not the FCCM/FCM pipeline). Full suite: 4717 unit + 336 contracts/integration + 497 acceptance pass — no existing acceptance fixture combined an off-BS exposure with collateral so no expected-outputs JSON shifted; the new behaviour is only triggered when both conditions are met. Spec updated in `docs/specifications/crr/credit-risk-mitigation.md` (new "Exposure value for CRM purposes (Art. 223(4))" section with worked cash and SA off-BS examples) and `docs/architecture/pipeline.md` (processing-order section now describes the two-EAD-bases pattern). Ref: CRR Art. 111(3), Art. 223(3)–(5), Art. 228(1)–(2), Art. 230, Art. 231 (extracted from `docs/assets/crr.pdf` p.110, 219, 226–228); PRA PS1/26 Art. 166A–166C, Art. 223(4), Art. 228(1), Art. 230 (extracted from `docs/assets/ps126app1.pdf` p.117–120, 200–202, 208–210); BCBS CRE22.55. (`a6e15b6`.)

### Changed
- Version bump for PyPI release.

---

## [0.2.4] - 2026-04-30

### Added
- **Blog section + main-navigation link**: new `docs/blog/` series live on the Zensical site, with a `Blog` link added to the primary site navigation. First two posts published — including "Post 2 — The Pipeline" walking through the immutable bundle pipeline architecture. (`874a510` add nav link; PRs #289 / #290, commits `cceaee4` / `7fe91fb`.)

### Changed
- **MOF undrawn now emits per-sub waterfall rows by descending CCF (`engine/hierarchy.py::_calculate_facility_undrawn`, new `_expand_mof_facility_undrawn`)**: replaces the prior worst-case single-CCF emission, where the MOF parent's full undrawn headroom flowed at the highest descendant CCF. Each MOF parent now emits one `facility_undrawn` row per committed descendant sub-facility with positive headroom, allocated by waterfall: subs are sorted by descending SA CCF (deterministic tie-break: `risk_type` then `facility_reference`) and filled in order, capped per-sub at `max(0, sub_limit - sub_drawn)` and globally at `parent_headroom`. When sub-limits sum below the parent's limit, a residual row is emitted at the parent's own `risk_type` and `counterparty_reference`. Each split row carries the **sub's** `risk_type` and `counterparty_reference` natively, so the prior `_derive_facility_share_counterparty` riskiest-CP override is now skipped on MOF parents (it still applies to non-MOF facilities). Per-sub drawn netting (loans + contingents directly mapped to a sub net only that sub's headroom — not the parent's) makes the waterfall reflect actual sub-level utilisation rather than rolling everything up to root before allocating. **Uncommitted (`committed=False`) sub-facilities are skipped entirely** from the waterfall — they consume no parent headroom, mirroring the existing parent-level rule that an unconditionally cancellable line carries no commitment EAD. Worked example for the user request that motivated the fix: parent £100m, sub_01 £60m @ MR (50% CCF), sub_02 £60m @ MLR (20% CCF). Old behaviour: 1 row £100m @ 50% → £50m EAD. New behaviour: 2 rows £60m @ 50% + £40m @ 20% (capped) → £38m EAD. Output schema: `exposure_reference = "{parent}_UNDRAWN_{sub}"` for waterfall rows, `"{parent}_UNDRAWN_RESIDUAL"` for the residual; `source_facility_reference = parent` on every row so facility-level collateral allocation and downstream rollups still group by the MOF parent; `mof_risk_type_source` records the sub each row came from (null on the residual). The retired private method `_derive_mof_risk_type` is replaced by `_expand_mof_facility_undrawn`. Tests: 8 new unit tests in `TestMOFAndFacilityShare` (waterfall caps at parent limit, B31 CCF table, per-sub drawn netting, fully-drawn sub drops out, sub-limits-under-parent residual, three-subs mixed CCF, per-sub counterparty, all-undrawn per-sub counterparties, **uncommitted sub skipped**); 5 existing MOF tests updated to assert per-sub split rows; 4 multi-level facility undrawn tests updated to assert sum-across-rows equals parent headroom. Full unit suite: 4,692 passed; acceptance: 497 passed (1 skipped); contracts + integration: 317 passed. No acceptance goldens shifted because no existing fixture combined a MOF with sub-facilities of differing risk_types. Spec updated in `docs/specifications/common/hierarchy-classification.md` (new "Multi-Option Facility (MOF) Waterfall Allocation" subsection with two worked examples and edge-case enumeration). Ref: CRR Art. 111 (SA CCFs), Art. 166 (off-balance EAD); PRA PS1/26 Art. 111 Table A1, Art. 166C. (PRs #292 / #293.)
- Version bump for PyPI release.

### Fixed
- **CRR F-IRB CCF over-statement for issued OBS items — implement Art. 166(10) fallback (`engine/ccf.py::_firb_ccf_for_col`)**: the CRR F-IRB CCF helper previously blanket-applied 75% to every `MR` / `MLR` / `OC` row except the Art. 166(8)(b) short-term trade-LC carve-out, treating Art. 166(8)(d) as the catch-all. CRR Article 166 in fact has two F-IRB CCF clauses: Art. 166(8) prescribes bespoke CCFs for the named commitment types (UCC credit lines, short-term trade LCs, revolving purchased-receivables UCC, "other credit lines / NIFs / RUFs"), and **Art. 166(10) is a self-contained residual fallback** for off-balance sheet items not in scope of paragraphs 1–8 (100% FR / 50% MR / 20% MLR / 0% LR by Annex I category). The engine now distinguishes the two via a new boolean schema flag `is_obs_commitment`: `True` (Art. 166(8)(d) commitment-style — credit lines, NIFs, RUFs) routes to 75%; `False` (Art. 166(10) issued OBS item — performance bonds, warranties, tender bonds, non-credit-substitute documentary credits / standby LCs, shipping guarantees, customs/tax bonds, self-liquidating documentary credits) routes to the Annex I fallback (50% MR / 20% MLR). The Art. 166(8)(b) `is_short_term_trade_lc` carve-out continues to win over both buckets (it is a more specific Art. 166(8)(b) rule). Schema additions (`data/schemas.py`): `is_obs_commitment` defaults to `True` on `FACILITY_SCHEMA` (a facility row is, by construction, a commitment / credit line) and `False` on `CONTINGENTS_SCHEMA` (a contingent is, by construction, an issued OBS item); callers may override per row (e.g., a contingent that genuinely represents a NIF/RUF can be tagged `True`). The hierarchy stage (`engine/hierarchy.py::_unify_exposures` and `_calculate_facility_undrawn`) projects the column with the per-source-table default. The CCF calculator's `_ensure_columns` defaults `is_obs_commitment=True` as a final fallback for unit-test callers that bypass hierarchy, preserving all existing direct-API behaviour. Items affected (over-stated CCF before the fix): MR issued items — performance bonds, tender bonds, advance-payment guarantees, warranties, non-self-liquidating documentary credits, non-credit-substitute irrevocable standby LCs (75% → **50%**, Art. 166(10)(b)); MLR issued items — self-liquidating documentary credits, shipping guarantees, customs and tax bonds (75% → **20%**, Art. 166(10)(c)). Items unchanged: FR (100% under both Art. 166(8) general and Art. 166(10)(a)); LR UCC (0% under both Art. 166(8)(a) and Art. 166(10)(d)); OC commitments (75% via Art. 166(8)(d)); MLR with `is_short_term_trade_lc=True` (20% via Art. 166(8)(b)). Fix is **CRR-only** — Basel 3.1 Art. 166C already aligns F-IRB CCFs to SA Table A1 (50% MR, 20% MLR) so the over-statement only existed in the `is_basel_3_1=False` branch. Test coverage: 7 new unit tests in `tests/unit/test_ccf.py` (`TestFIRBArt16610Fallback`) covering MR-issued@50%, MR-commitment@75%, MLR-issued@20%, MLR-commitment@75%, MLR-issued+trade-LC@20% (carve-out priority), OC-issued@50%, and the missing-flag default; 3 new end-to-end integration tests in `tests/integration/test_classifier_to_crm.py` (`test_crr_d_ccf7_firb_mr_contingent_falls_to_50_via_art_166_10`, `test_crr_d_ccf8_firb_mlr_contingent_falls_to_20_via_art_166_10`, `test_firb_mr_facility_undrawn_keeps_75_via_art_166_8d`) that drive data through `HierarchyResolver` → `ExposureClassifier` → `CRMProcessor` and confirm the per-source-table default routing. Stress / benchmark fixture data updated (`tests/acceptance/stress/conftest.py`, `tests/benchmarks/data_generators.py`) and the test fixture builders (`tests/fixtures/exposures/facilities.py`, `tests/fixtures/exposures/contingents.py`) gain an optional `is_obs_commitment` field. Module docstring and `CCFCalculator` class docstring updated to cite Art. 166(8)(a)/(b)/(d) and Art. 166(10), and to correct the prior Art. 166(9) misattribution for short-term trade LCs (Art. 166(9) is in fact the lower-of-two-CCFs rule for overlapping commitments, already handled via `underlying_risk_type`). Spec updated in `docs/specifications/crr/credit-conversion-factors.md` (new "F-IRB CCFs by source" tables splitting Art. 166(8)(d) credit lines from Art. 166(10) issued items; new CRR-D.CCF7 / CRR-D.CCF8 scenarios). Full suite: 5,531 passed (1 skipped, 11 deselected) — no acceptance goldens shifted because no existing CRR FIRB acceptance fixture combined an FIRB-classified counterparty with an MR or MLR contingent that previously expected 75%. Ref: CRR Art. 166(8)(a)–(d), Art. 166(10) (extracted verbatim from `docs/assets/crr.pdf`). (PR #291.)

---

## [0.2.3] - 2026-04-28

### Added
- **Oracle test suite scaffold (PR #286, `301f77f`)**: new `tests/oracle/` directory containing a small set of hash-locked, hand-derived expected values for SA / IRB scenarios that act as a third-party-friendly oracle independent of the existing acceptance goldens. Each fixture row carries a SHA-256 hash so any drift in inputs or expected outputs is detected as a hash mismatch rather than a silent recomputation. Initial scaffolding only; no production-engine changes.

### Changed
- **Facility undrawn generation now respects the `committed` flag (`engine/hierarchy.py::_calculate_facility_undrawn`)**: the dormant `committed` Boolean on `FACILITY_SCHEMA` is now consulted by the hierarchy resolver. Facilities with `committed=False` no longer generate a synthetic `facility_undrawn` exposure row — an unconditionally cancellable line carries no irrevocable lending commitment, so the bank holds no commitment EAD / RWA against the unused headroom (consistent with the regulatory intuition under CRR Art. 166 and PRA PS1/26 Art. 166C). Loans and contingents already mapped to such facilities are completely unaffected: they remain independent exposure rows with normal counterparty / parent rollup, collateral allocation, and CCF treatment, because they are already on-balance-sheet (loans) or carry their own off-balance EAD (contingents). The schema default for `committed` was flipped from `False` to `True` (`data/schemas.py:69`) so legacy callers and fixtures that omit the field continue to generate undrawn rows as before — uncommitted is now the explicit, opted-in case. Null `committed` values are also defensively treated as committed. New unit tests in `tests/unit/test_hierarchy.py`: `test_uncommitted_facility_suppresses_undrawn_row` (no row generated for `committed=False`), `test_committed_null_treated_as_committed` (null defaults to committed), `test_uncommitted_facility_loans_still_flow` and `test_uncommitted_facility_contingents_still_flow` (mapped loans/contingents flow through `_unify_exposures` unchanged, no `facility_undrawn` synthetic row in the unified output). The mislabeled `test_facility_uncommitted_lr_risk_type` (which actually used `committed=True`) was renamed to `test_facility_lr_risk_type`. No CCF or downstream calculator changes — the `committed` gate simply stops feeding suppressed rows into the existing CCF pipeline. Full suite: 5,521 passed (1 skipped, 11 deselected) — no acceptance goldens shifted because the only fixture that previously held `committed=False` (`FAC_CORP_UNCOMMIT_001` in `tests/fixtures/exposures/facilities.py`) was already declared with the comment "0% CCF for unconditionally cancellable" and not asserted against in any expected-output JSON. Docs updated in `docs/data-model/input-schemas.md` (facility `committed` row) and `docs/architecture/components.md` (HierarchyResolver method table). Ref: CRR Art. 166 (off-balance-sheet item EAD); PRA PS1/26 Art. 166C (Basel 3.1 CCF treatment for unconditionally cancellable commitments). (PR #288.)
- Version bump for PyPI release.

### Docs
- **README accuracy refresh (PR #287, `fce582e`)**: refreshed the project README to match the current state of the codebase — updated test counts, the supported exposure classes table, and the Basel 3.1 implementation status section.

---

## [0.2.2] - 2026-04-27

### Added
- **Multiple Option Facility (MOF) and Facility Share support in the undrawn allocation pipeline (`engine/hierarchy.py::_calculate_facility_undrawn`)**: two product patterns that the facility/undrawn pipeline previously did not honour are now applied as overrides on the parent facility's undrawn exposure row, without requiring schema changes. **MOFs**: any facility with at least one `child_type='facility'` row in `facility_mappings` is now treated as a Multiple Option Facility — the parent's undrawn `risk_type` is overridden to the descendant sub-facility `risk_type` whose SA CCF (via `engine/ccf.py::sa_ccf_expression`, frame-aware for CRR / PRA PS1/26 Table A1) is highest, so the parent's undrawn EAD reflects the worst-case off-balance commitment among its components rather than the parent's own (often LR / 0%) `risk_type`. Tie-break on alphabetical lowercase risk_type then alphabetical descendant `facility_reference` for full reproducibility. The new private method `_derive_mof_risk_type()` walks the existing `_build_facility_root_lookup()` output to collect descendants at any depth. **Facility Shares**: when the descendant loans / contingents under a facility reference more than one distinct `counterparty_reference`, the undrawn is now allocated to the riskiest member by SA-equivalent risk weight rather than to the facility's own `counterparty_reference`. The new private method `_derive_facility_share_counterparty()` collects the union of distinct counterparties from the descendant loan/contingent set (using the existing `_resolve_to_root_facility()` helper) and joins each candidate to the resolved counterparty lookup to read `entity_type` and `cqs`. A new module-level helper `_preview_sa_rw_expr()` maps `entity_type` to the matching SA risk weight table (`CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS`, frame-aware `INSTITUTION_RISK_WEIGHTS_*`, `CORPORATE_RISK_WEIGHTS`, `RETAIL_RISK_WEIGHT`, `MDB_RISK_WEIGHTS_TABLE_2B`, `HIGH_RISK_RW`) and returns the RW for the candidate's CQS — deliberately SA-only so the preview avoids the circular dependency with the classifier's IRB approach gating; the chosen counterparty still flows through the full classifier and SA/IRB pipeline downstream so the preview is non-binding. Per facility, max RW wins; tie-break on higher CQS then alphabetical `counterparty_reference`. Both overrides are skipped no-ops when their inputs are trivial: a facility with no `child_type='facility'` rows is not a MOF (parent risk_type unchanged); a facility with ≤1 distinct member counterparty is not a share (counterparty unchanged). Two new audit columns flow on the `facility_undrawn` exposure rows for traceability — `original_counterparty_reference` (the facility's own `counterparty_reference` before the share override) and `mof_risk_type_source` (the descendant facility reference whose `risk_type` won the max-CCF tie). The `_calculate_facility_undrawn()` signature gains optional `counterparty_lookup` and `config` parameters; `_unify_exposures()` plumbs the same `config` through from `resolve()` so the framework switch reaches both helpers. `FACILITY_MAPPING_SCHEMA` (`data/schemas.py`) is unchanged. New unit-test class `TestMOFAndFacilityShare` in `tests/unit/test_hierarchy.py` covers six scenarios: MOF parent inherits max-CCF child `risk_type` under CRR; MOF picks OC over LR under Basel 3.1 (40% beats 10%); plain hierarchies with only `child_type='loan'` rows are not MOFs (parent `risk_type` preserved); facility share with three distinct corporate counterparties at CQS 1/3/5 allocates undrawn to CQS 5 (RW 150%); single-member facility is unchanged; combined MOF + share scenario applies both overrides independently. Full suite: 5,484 passed (1 skipped, 4 deselected) — no acceptance goldens shifted because no existing fixture combines a multi-CP facility share or a MOF with mixed-CCF children. `scripts/arch_check.py`, `ruff check`, and `ty check` all clean. Docs updated in `docs/architecture/components.md` (new key-features bullets and method rows in the HierarchyResolver section). Ref: CRR Art. 111 (SA CCFs); PRA PS1/26 Art. 111 Table A1; CRR Art. 112-122 (SA risk weights for the preview lookup). (PR #285.)

### Changed
- Version bump for PyPI release.

### Docs
- **Doc batch (D2.* items, two `/next-docs` waves, batches `b39d7e1` and `bdd0f31`)**: eight regulatory-doc items landed in this window without code changes — Art. 143(2A)/(2B) A-IRB permission conditions (`05660d0`); Art. 154/157/158/160-166A/184 purchased-receivables pool & dilution risk (`2ae4bf1`); Art. 234 tranched coverage with P1.30(e) cross-ref (`dd488c7`); CRE loan-split threshold corrected from "60% LTV" to "55% of property value" (`0d5a58d`); Art. 119(2)/(3) CRR national-currency short-term institution coverage (`1c4a339`); OF 09.01 missing rows 0075/0085/0095/0141-0143/0160/0170 (`fb0a5d2`); plus two `IMPLEMENTATION_PLAN.md` ticks (`f83bc84`, `dd0f317`). All edits are docs-only.

---

## [0.2.1] - 2026-04-27

### Added
- **`is_airb_model_collateral` flag on the collateral table to prevent AIRB collateral double-counting (CRR Art. 181 / Basel 3.1 Art. 169A)**: under A-IRB, the firm's own modelled LGD already reflects the credit-risk-mitigating effect of any collateral incorporated in the model, so allocating that same collateral to non-AIRB exposures of the counterparty supervisorily double-counts it. New optional Boolean column on `COLLATERAL_SCHEMA` (default `False`) that asserts the row's collateral has been used to construct the firm's internal LGD model. The CRM allocator (`engine/crm/collateral.py::_apply_collateral_unified`) is now pool-aware: (1) exposures are partitioned at the start of `apply_collateral` into an **AIRB pool** (rows where the modelled LGD is preserved by CRM — `approach == AIRB` AND not falling back to the supervisory formula under Foundation election or Art. 169B insufficient-data) and a **non-AIRB pool** (FIRB / SA / Slotting and AIRB rows that use the formula); (2) `_build_exposure_lookups` in `engine/crm/processor.py` now emits pool-specific facility / counterparty EAD aggregates (`_ead_facility_airb` / `_ead_facility_non_airb`, `_ead_cp_airb` / `_ead_cp_non_airb`); (3) the group-by aggregation splits each metric into `_n` (unflagged collateral) and `_a` (flagged) variants via filter on `is_airb_model_collateral`; (4) pro-rata weights `_fw_n` / `_fw_a` / `_cw_n` / `_cw_a` bake in the pool-match gate so non-matching pools contribute zero. Behaviour: flagged collateral routes only to AIRB-pool rows (facility / counterparty pro-rata over AIRB pool only); unflagged facility / counterparty collateral routes only to non-AIRB rows (AIRB pool excluded from the pro-rata base — non-AIRB rows now absorb 100% of unflagged counterparty / facility collateral that previously was wasted on AIRB rows whose modelled LGD ignores it); direct unflagged collateral is unchanged (1:1 to the named exposure). Direct flagged collateral pledged onto a non-AIRB exposure emits new `CRM006` (`ERROR_AIRB_MODEL_COLLATERAL_MISDIRECTED`) data-quality warning via `find_misdirected_airb_model_collateral` and is given zero allocation. The inline `_airb_uses_formula` expression in `_apply_collateral_unified` was lifted into a top-level helper `airb_lgd_preserved_expr(config, is_basel_3_1, schema_names)` reused by both the LGD branch and the new pool-membership tagging. `_apply_collateral_unified` is defensive about missing pool-aware columns (test helpers that supply only `_fac_ead_total` / `_cp_ead_total` are backfilled to legacy behaviour: AIRB total = 0, non-AIRB total = full total). Schema, processor lookups, and pro-rata logic are all backward-compatible with fixtures that don't set the column — `ensure_columns(COLLATERAL_SCHEMA)` in the loader (`engine/loader.py:88`) fills the default. Test coverage: new `tests/unit/crm/test_airb_model_collateral_flag.py` (7 tests across schema, unflagged-counterparty AIRB-exclusion, flagged-counterparty user scenario `loan_1`/`loan_2`/`loan_3`, CRM006 misdirection emission and silence, homogeneous-FIRB backward-compat); benchmark data generator (`tests/benchmarks/data_generators.py`) updated to include the new column. Full suite: 5,505 passed, 1 skipped — no acceptance goldens shifted because no existing scenario combined mixed AIRB / non-AIRB exposures with counterparty / facility-level collateral. Docs updated in `docs/specifications/crr/credit-risk-mitigation.md` (new "Pool-Aware Pro-Rata for AIRB Mixes" subsection under Multi-Level Collateral Allocation) and `docs/specifications/basel31/credit-risk-mitigation.md` ("AIRB own-LGD anti-double-counting" bullet under Art. 191A(2)(d) anti-double-counting rules). Ref: CRR Art. 181; Basel 3.1 Art. 169A, Art. 191A(2)(d); CRE36.34-36. (PR #280.)

### Changed
- Version bump for PyPI release.

### Internal
- **Experimental Claude agent-teams configuration for `loop.sh`** (PRs #282 / #283, commits `0dcd821` / `94311fb` / `09a4b97` / `fbf784a`): adds `/next-docs` and `/next-items` parallel batch orchestrators, a Phase 1 docs-implementation team, and full coverage of all four `loop.sh` modes. Tooling-only; no engine or test changes.

---

## [0.2.0] - 2026-04-26

### Changed
- **Promote `RESIDENTIAL_MORTGAGE` / `COMMERCIAL_MORTGAGE` from uppercase magic strings to first-class `ExposureClass` enum members**: the SA real-estate loan-splitter (`engine/re_splitter.py`) labels its secured child row's `exposure_class` with one of two values that, until now, lived only as uppercase string literals (`_SECURED_TARGET_RESIDENTIAL = "RESIDENTIAL_MORTGAGE"` and `_SECURED_TARGET_COMMERCIAL = "COMMERCIAL_MORTGAGE"` in `engine/classifier.py:158-159`), with an explicit code comment noting they "are not in the ExposureClass enum (only `RETAIL_MORTGAGE` is)". The exposure-class enum convention is lowercase string values (e.g. `"retail_mortgage"`, `"corporate"`); the loan-splitter therefore broke that convention every time it materialised a non-retail residential or commercial mortgage row. Behavioural impact: none (the SA RW expressions in `engine/sa/namespace.py` uppercase `exposure_class` via `_uc = pl.col("exposure_class").str.to_uppercase()` before any substring match, so both cases route identically). Hygiene impact: the loan-splitter outputs are now indistinguishable from any other classifier output. Changes: (1) add `ExposureClass.RESIDENTIAL_MORTGAGE = "residential_mortgage"` and `ExposureClass.COMMERCIAL_MORTGAGE = "commercial_mortgage"` in `domain/enums.py` with docstrings citing CRR Art. 125 / Art. 126 and PRA PS1/26 Art. 124F / Art. 124H; (2) replace the `_SECURED_TARGET_*` magic-string assignments in `engine/classifier.py:158-159` with `ExposureClass.<X>.value` references and rewrite the surrounding comment to point at the new enum members; (3) update `engine/re_splitter.py` to import `ExposureClass` and replace the literal `"COMMERCIAL_MORTGAGE"` filter at line 503 with `ExposureClass.COMMERCIAL_MORTGAGE.value`; (4) update all four `target_class=` initialisers in `data/tables/re_split_parameters.py` (`RE_SPLIT_PARAMS_CRR_RESIDENTIAL`, `RE_SPLIT_PARAMS_CRR_COMMERCIAL`, `RE_SPLIT_PARAMS_B31_RESIDENTIAL`, `RE_SPLIT_PARAMS_B31_COMMERCIAL`) to use enum-value references via a new `from rwa_calc.domain.enums import ExposureClass` (the existing arch-check allowlist permits `data/tables/` to import from `domain/enums`, mirroring the pre-existing `CQS` import in `crr_risk_weights.py`); (5) update test fixtures and assertions in `tests/unit/test_real_estate_splitter.py`, `tests/unit/test_b31_re_junior_charges.py`, `tests/integration/test_re_split_pipeline.py`, `tests/unit/test_b31_sa_risk_weights.py`, and `tests/unit/crr/test_crr_sa.py` to use the lowercase enum values, matching what the production classifier now emits. **Intentionally not changed**: (a) the uppercase `"RESIDENTIAL_MORTGAGE"` join key in the `crr_risk_weights.py:458` LTV-split lookup table — it is joined against `_lookup_class` which is uppercased via `.str.to_uppercase()`, so it stays uppercase to preserve the case-insensitive routing behaviour; (b) the `uc.str.contains("MORTGAGE", literal=True) | uc.str.contains("RESIDENTIAL", literal=True) | uc.str.contains("COMMERCIAL", literal=True) | uc.str.contains("CRE", literal=True)` substring matches in `engine/sa/namespace.py:_b31_append_real_estate_branches` and `_crr_append_real_estate_branches` — they cover both the canonical enum values *and* a real non-enum user-input path (`"CRE"` appears as a direct `exposure_class` value in `tests/expected_outputs/crr/expected_rwa_crr.json:213` for the `LOAN_CRE_001` acceptance fixture). Switching to `is_in([ExposureClass.X.value.upper(), …])` would lose that fallback unless the list reintroduced `"CRE"` as a magic string, defeating the refactor's purpose. Verification: 70 splitter-focused unit + integration tests pass (`tests/unit/test_real_estate_splitter.py`, `tests/unit/test_b31_re_junior_charges.py`, `tests/integration/test_re_split_pipeline.py`); 330 SA / classifier / data-boundary tests pass (`tests/unit/test_b31_sa_risk_weights.py`, `tests/unit/crr/test_crr_sa.py`, `tests/unit/test_classifier.py`, `tests/contracts/test_data_layer_boundary.py`); `scripts/arch_check.py` clean; the broader acceptance + contracts + integration sweep was also run, and the failure count is identical to the parent commit baseline (106 acceptance failures, all pre-existing — `hierarchy_resolver` errors in FIRB/AIRB/Slotting/Provisions scenarios that don't touch the SA real-estate path). Ref: CRR Art. 125, Art. 126; PRA PS1/26 Art. 124F, Art. 124H.

### Fixed
- **SME supporting factor `E*` aggregated across group of connected clients (CRR Art. 501)**: the SA SME supporting factor previously evaluated the EUR 1.5m / GBP-equivalent `E*` exposure threshold on a per-counterparty basis, ignoring Art. 4(1)(39) connected-client aggregation. The check now aggregates across the full group of connected clients, matching the regulatory definition of the obligor used elsewhere in the pipeline. Acceptance scenarios CRR-F* updated; new test class in `tests/unit/test_supporting_factors.py`. (PR #279)

### Docs
- **Clarify counterparty scope of the CRR Art. 125 35% / 75% residential mortgage RW**: three doc updates document that CRR Art. 125 is **not** restricted to retail individuals — any exposure secured by qualifying residential property may receive the 35% secured / residual-counterparty-RW split, contingent on the Art. 125(2) qualifying conditions (value/repayment not materially dependent on borrower credit quality or property cash flows; Art. 208 / Art. 229(1) valuation). The calculator routes individuals via `RETAIL_MORTGAGE` (in `engine/classifier.py` when `is_mortgage=True` and `cp_entity_type=="individual"`) and non-retail counterparties via `RESIDENTIAL_MORTGAGE` (through the SA real-estate loan-splitter `engine/re_splitter.py`); both paths apply the same Art. 125 split. (1) `docs/user-guide/exposure-classes/retail.md` — replaced the misleading "CRR uses a flat 35% (LTV ≤ 80%) or 75% (LTV > 80%)" sentence with the correct split treatment and added a pointer to the loan-splitter for non-retail RRE; (2) `docs/framework-comparison/key-differences.md` — added a "Counterparty scope of the CRR 35%/75% column" callout under the Residential RE General loan-splitting comparison table noting that the CRR column is regime treatment, not a retail-only label; (3) `docs/specifications/crr/sa-risk-weights.md` — extended the "Residential Mortgage Exposures (CRR Art. 125)" section with the Art. 125(2)(a)–(d) qualifying-conditions list (mirroring the existing Art. 126(2) list) and a "Counterparty scope" info admonition mapping the two routing buckets and noting that the calculator infers the qualifying-condition gate from the `is_mortgage` flag rather than independently verifying (a)–(c). No code changes.

---

## [0.1.67] - 2026-04-25

### Fixed
- **Guarantor rating routing now beneficiary-aware (CRR Art. 161(3) / Basel 3.1 CRE22.70-85)**: guarantor substitution previously chose between the guarantor's internal PD and external CQS based purely on the guarantor's own properties — an SA exposure could end up routed through IRB parameter substitution, and an IRB exposure under CRR was always forced through SA RW substitution because parameter substitution was gated on `config.is_basel_3_1`. Now the routing is keyed on the beneficiary's approach: IRB beneficiaries use the guarantor's internal PD when available; SA beneficiaries always use external CQS. The F-IRB supervisory LGD used in PD substitution and EL blending now tracks the active framework (0.45 CRR / 0.40 Basel 3.1) instead of being hard-coded. (PR #277)

### Docs
- **Refresh `docs/data-model/input-schemas.md` to match `src/rwa_calc/data/schemas.py`**: the input schema reference had drifted ~30 columns behind the source of truth. Added documentation for `effective_maturity` (CRR Art. 162(3) / PS1/26 numeric `M` override that bypasses the 1-year floor) on Facility / Loan / Contingent; the Art. 110A due-diligence override fields (`due_diligence_performed`, `due_diligence_override_rw`); A-IRB modelled-EAD and unsecured-LGD fields (`ead_modelled`, `lgd_unsecured`, `has_sufficient_collateral_data`); maturity-floor and SFT flags (`has_one_day_maturity_floor`, `is_sft`); the `is_payroll_loan` 35% retail RW flag; counterparty classification flags (`is_natural_person`, `is_social_housing`, `is_financial_sector_entity`, `is_ccp_client_cleared`, `borrower_income_currency`, `local_currency`, `sovereign_cqs`, `institution_cqs`); the Basel 3.1 real-estate collateral fields (`is_qualifying_re`, `original_maturity_years`, `rental_to_interest_ratio`, `liquidation_period_days`, `qualifies_for_zero_haircut`, `is_main_index`, `insurer_risk_weight`, `credit_event_reduction`); guarantee credit-derivative fields (`protection_type`, `includes_restructuring`); specialised-lending `project_phase`; equity / CIU look-through fields (`ciu_approach`, `ciu_mandate_rw`, `ciu_third_party_calc`, `fund_reference`, `fund_nav`); and an entirely new **CIU Holdings schema** section documenting the look-through input (Art. 132(3)). Also corrected several `Required: Yes` cells that were stale relative to the `ColumnSpec(required=...)` source of truth (Counterparty, Facility, Loan, Contingent — only the reference IDs and `entity_type` are loader-required). No code changes.

- **Comprehensive regulatory documentation refresh (D2.34–D2.73)**: ~30 documentation commits land verbatim citations and clarifications across A-IRB, CRM, slotting, real-estate, SCRA, covered bonds, and SL specs. Highlights: Art. 124B underwriting-standards obligation (D2.60); Art. 124D valuation requirements (D2.43, D2.62); Art. 124E(5)/(7) RE reassessment obligations (D2.56); Art. 122(7)-(8) output-floor election for unrated corporates (D2.46); Art. 129(4A) covered-bond due-diligence CQS step-up (D2.34); Art. 138(1)(g) + Art. 139(6) implicit-support higher-of rule (D2.49); Art. 153(5)(c)-(f) slotting column-assignment rules (D2.68); Art. 161(1)(e)/(f)/(g) purchased-receivables trigger recast (D2.51); Art. 162(2A)(k) revolving maturity precedence (D2.52); Art. 232(3) life insurance derivation (D2.48); Art. 237/239 CRM maturity-mismatch wording aligned to PS1/26 (D2.55); Art. 121(1)(a)/(1)(b) SCRA disclosure barring ladder (D2.54); BEEL substitution for A-IRB defaulted exposures (D2.67); retail A-IRB LGD floor reconciliation (D2.50); removal of Art. 119(2)/(3) national-currency preferential in B3.1 (D2.73). Misc fixes: USD 100bn LFSE threshold (D2.53); CRR FCSM Art. 222 paragraph attributions (D1.47, D2.63); LFSE citation to Art. 142(1)(4) (D1.49); MDBs/IOs in Art. 147A(1)(a) SA-only scope (D2.38). No code changes. (PR #275)

---

## [0.1.66] - 2026-04-24

### Added
- **`effective_maturity` override (CRR Art. 162(3) / PRA PS1/26)**: new optional column on Facility / Loan / Contingent that lets firms supply a numeric maturity `M` directly, bypassing the 1-year maturity floor and the date-derived calculation for IRB exposures. When populated, it takes precedence over derived maturity in correlation, K, and maturity-adjustment formulas. Documented in `docs/data-model/input-schemas.md`. (PR #274)

### Fixed
- **IRB / Slotting exposures secured by real estate no longer receive the 0.15 retail-mortgage correlation (CRR Art. 153 / CRE31.11)**: `RealEstateSplitter._split_unified_frame` in `engine/re_splitter.py` previously split every row flagged by the classifier as `re_split_mode='split'` (or `'whole'`) regardless of the row's `approach`, emitting a secured child row with `exposure_class = RESIDENTIAL_MORTGAGE` / `COMMERCIAL_MORTGAGE`. For FIRB / AIRB / Slotting rows, the IRB correlation expression in `engine/irb/formulas.py::_correlation_expr_from_pd` reads `pl.col("exposure_class")` and hits the `str.contains("MORTGAGE")` branch → `pl.lit(0.15)`, i.e. the retail-mortgage correlation under CRR Art. 154(3). A FIRB corporate-SME exposure collateralised by residential property was therefore splitting into (a) a `corporate_sme` residual row with the correct supervisory-formula-with-SME-adjustment correlation and (b) a `RESIDENTIAL_MORTGAGE` secured row stuck at 0.15 — a regime that doesn't exist under IRB. Loan-splitting is an SA-only regulatory mechanism (CRR Art. 125/126 and PRA PS1/26 Art. 124F/H all sit in the Credit Risk: Standardised Approach Part); IRB recognises real-estate collateral via LGD (Art. 161(5) FIRB supervisory RRE floor / AIRB own-estimate LGD / Art. 230-231 funded credit protection), already handled upstream by the CRM processor's `crm_alloc_real_estate` allocation. Fix: gate `is_split_mode` and `is_whole_mode` on `approach ∈ {standardised, equity}` (a new `_SA_BOUND_APPROACHES` module constant backed by `ApproachType` enum values). Rows with `approach ∈ {foundation_irb, advanced_irb, slotting}` and the classifier's split flag set now fall into the pass-through bucket and retain their original `exposure_class` — the downstream IRB correlation formula then correctly lands on the corporate / corporate-SME / retail branches. `_accumulate_split_errors` is similarly gated so IRB rows do not emit SA-specific `RE002` zero-cap or `RE004` CRR rental-coverage warnings. When the `approach` column is absent (pure SA-only bundles, older test fixtures) the predicate defaults to `True` — existing SA-only tests continue to pass. 5 new regression tests in `tests/unit/test_real_estate_splitter.py::TestSplitterApproachGate` (parametrised over FIRB/AIRB/Slotting pass-through, whole-loan pass-through, SA-with-explicit-approach still splits, no spurious RE002 on IRB zero-cap rows, mixed SA+IRB batch). Full suite: 4,640 unit passed, 810 acceptance+contracts+integration passed. Ref: CRR Art. 125, Art. 126, Art. 153(1)-(4), Art. 154(3), Art. 161(5), Art. 230-231; PRA PS1/26 Art. 124F, Art. 124H.
- **Defaulted SA exposures no longer return the base class RW when non-financial collateral columns are populated (PS1/26 Art. 127)**: `_apply_defaulted_risk_weight` in `engine/sa/namespace.py` previously computed `secured_pct = (collateral_re_value + collateral_receivables_value + collateral_other_physical_value) / ead` and blended `unsecured_pct × provision_rw + secured_pct × pl.col("risk_weight")`. `pl.col("risk_weight")` at that point is the exposure's base class RW (75% for retail, 100% for unrated corporate, 35% for mortgage), so whenever non-financial collateral reached or exceeded EAD, the blended RW collapsed back to the class base — for defaulted regulatory retail with RE collateral the SA path returned 75% instead of the Art. 127(1) 100%/150%. Art. 127(2) defers to the CRM method the institution applies (Art. 191A(2)); under FCCM (the default for SA) eligible financial collateral has already reduced `ead_final` upstream and eligible RE is routed through class reclassification, so the post-CRM value IS the unsecured portion and no secondary split is required inside the defaulted override. Fix: drop the non-financial collateral split entirely; apply the provision-based 100%/150% to `ead_final` directly (CRR denominator keeps the `+ provision_deducted` pre-provision reconstruction; B31 uses `ead_final` per "outstanding amount of the item or facility"). The Basel 3.1 RESI RE non-income-dependent flat-100% branch (Art. 127(3) / CRE20.88) and the HIGH_RISK precedence guard (Art. 128) are unchanged. `tests/unit/test_defaulted_secured_split.py` rewritten to assert the new behaviour (regulatorily-incorrect "fully secured returns base RW" cases deleted; new regression tests pin down the retail scenario). New unit tests in `tests/unit/crr/test_crr_sa.py::TestDefaultedRWApplication` for defaulted non-mortgage retail under both CRR and Basel 3.1. Acceptance scenario B31-K7 re-baselined (collateral columns no longer produce a blend). Spec `docs/specifications/basel31/defaulted-exposures.md` updated: FR-10.3 reworded to "unsecured portion determined by the CRM method"; D3.19 code-divergence warning on the B31 denominator removed (resolved); secured-portion section rewritten. Ref: PS1/26 Art. 127(1)-(3); Art. 191A(2); CRR Art. 127(1)-(2); CRE20.88-90.

---

## [0.1.65] - 2026-04-21

### Added
- **Auto-sync of `config.eur_gbp_rate` from the loaded `fx_rates` table**: the pipeline now keeps the scalar EUR/GBP rate used by the IRB SME correlation formula (CRR Art. 153(4)) and the GBP equivalents of EUR regulatory thresholds (`RegulatoryThresholds.crr`) in step with the `(EUR, GBP)` row of the loaded `fx_rates` input. Previously these two FX mechanisms were independent: a user could load an up-to-date `fx_rates.parquet` and get all exposure/collateral/guarantee/provision amounts converted at e.g. 0.90 while the IRB SME correlation and the derived GBP thresholds continued to run at the default 0.8732, silently. Implementation: (1) new module `src/rwa_calc/engine/fx_rate_sync.py` exposes `extract_eur_gbp_rate(fx_rates: pl.LazyFrame | None) -> Decimal | None` — returns the rate when the table contains exactly one `(EUR, GBP)` row, returns `None` and logs WARNING `"fx_rates table has N (EUR, GBP) rows; skipping eur_gbp_rate auto-sync"` when multiple rows match; (2) new method `CalculationConfig.with_fx_rate(eur_gbp_rate)` in `src/rwa_calc/contracts/config.py` uses `dataclasses.replace` to produce a new config with both `eur_gbp_rate` and `thresholds=RegulatoryThresholds.crr(eur_gbp_rate=...)` rebuilt, so the SME turnover threshold, SME exposure threshold, retail max exposure, QRRE limit, and LFSE threshold are all re-derived at the new rate; the method is a no-op on Basel 3.1 (GBP-native per PRA PS1/26 Art. 153(4)) and a no-op when the rate is unchanged; (3) `PipelineOrchestrator.run_with_data` in `src/rwa_calc/engine/pipeline.py` calls `extract_eur_gbp_rate(data.fx_rates)` immediately before `_ensure_components_initialized(config)` and, when the derived rate differs from the caller-supplied rate, logs WARNING `"eur_gbp_rate auto-sync: replacing <old> with <new> from fx_rates table"` on `rwa_calc.engine.pipeline` and swaps the local `config` via `with_fx_rate`. New opt-out field `CalculationConfig.sync_eur_gbp_rate_from_fx_table: bool = True` lets callers force their passed-in rate to win regardless of the data; when False, no WARNING is emitted and the supplied rate stands. Tests: 5 contract tests (`tests/contracts/test_config.py::TestCalculationConfig` — `test_sync_eur_gbp_rate_flag_defaults_true`, `test_with_fx_rate_rebuilds_thresholds`, `test_with_fx_rate_noop_when_rate_unchanged`, `test_with_fx_rate_noop_for_basel_3_1`, `test_with_fx_rate_preserves_post_init_derivations`); 6 unit tests (`tests/unit/test_fx_rate_sync.py` — single/missing/None/multiple rows, reverse-direction row, Decimal precision); 4 integration tests (`tests/integration/test_fx_rate_autosync.py` — divergence-warns-and-replaces, same-rate no-warn, opt-out suppresses, B3.1 no-op). Documented in `docs/user-guide/methodology/fx-conversion.md` under a new "Auto-sync of `eur_gbp_rate` from the FX table" section covering the match rules, divergence warning, multiple-row skip, opt-out flag, and Basel 3.1 behaviour. Ref: CRR Art. 153(4); `RegulatoryThresholds.crr` at `contracts/config.py:619`.

### Changed
- Refactor: `stage_timer` logging format enhanced for clearer pipeline traces.
- Refactor: inline sidebar theme CSS for improved styling.

### Fixed
- **Retail Art. 123(c) threshold now aggregates across the full counterparty when no lending group is defined**: `HierarchyResolver._enrich_with_lending_group` in `engine/hierarchy.py` previously set `lending_group_total_exposure` and `lending_group_adjusted_exposure` to `0.0` whenever `lending_group_reference` was null, and the classifier's fallback in `_build_qualifies_as_retail_expr` then compared the **per-row** `exposure_for_retail_threshold` against the EUR 1m / GBP 880k limit. A counterparty with, say, three GBP 400k loans and no lending group was therefore classified as retail even though the aggregate GBP 1.2m exposure exceeded the threshold. CRR Art. 123(c) read with Art. 4(1)(39) ("group of connected clients") and PRA PS1/26 Art. 123A require aggregation across every exposure to a single obligor — a standalone counterparty is a group-of-one. Fix: the `.otherwise(0.0)` branches now aggregate via `.sum().over("counterparty_reference")` so both totals are always populated with the connected-client figure. The now-redundant `zero_lending_group_fail` branch in `engine/classifier.py` is removed. New regression tests: `tests/unit/test_hierarchy.py::TestLendingGroupAggregation::test_standalone_counterparty_aggregates_own_exposures` (three-loan counterparty, 1.2m aggregate) and `tests/unit/test_art123a_retail_criteria.py::TestCounterpartyAggregationWithoutLendingGroup` (three cases covering above-threshold B3.1, below-threshold B3.1, and above-threshold CRR). Existing `test_standalone_not_in_lending_group` updated to expect the counterparty aggregate (50k) rather than 0.0. Ref: CRR Art. 123(c), Art. 4(1)(39); PRA PS1/26 Art. 123A.

---

## [0.1.64] - 2026-04-19

### Added
- **stdlib `logging` observability layer (`rwa_calc.observability`)**: a new cross-cutting package (`src/rwa_calc/observability/`) configures stdlib `logging` idempotently on the `rwa_calc` namespace logger (never root), installs a `contextvars`-backed correlation `run_id` injected onto every LogRecord, and provides `stage_timer` — a context manager that emits INFO `"stage entered"` / `"stage completed"` records with an `elapsed_ms` extra (WARNING `"stage failed"` on exception). Every `_run_*` helper in `PipelineOrchestrator` is wrapped with `stage_timer`, so each pipeline run now emits matching entry/exit records for loader, hierarchy_resolver, classifier, crm_processor, re_splitter, calculators, aggregator, and equity_calculator, all sharing one freshly-generated 12-hex-char `run_id` bound at `run_with_data` entry and cleared in the existing `finally`. Two output formats — `"text"` (human-readable) and `"json"` (single-line, audit-friendly with a whitelisted extras set) — are selectable via two new fields on `CalculationConfig` (`log_level` default `"INFO"`, `log_format` default `"text"`) that also flow through `CreditRiskCalc(log_level=..., log_format=...)` and both `.crr()` / `.basel_3_1()` factories. `CreditRiskCalc.calculate()` now calls `configure_logging(config.log_level, config.log_format)` before constructing the pipeline; the orchestrator itself does NOT call `configure_logging` so it remains usable in embedded contexts. Noisy third-party loggers (`polars`, `uvicorn.access`, `fastapi`, `asyncio`) are pinned to WARNING. Contract: logging is operational-only — data-quality issues remain in `CalculationError`, and the integration test asserts no log record's `message` equals any `CalculationError.message` in the same run. Enforcement: ruff rules `G` / `LOG` / `T20` (f-string lazy-formatting, deprecated API detection, `print()` ban with `tests/**` + marimo apps exempted); `scripts/arch_check.py` gains check 8 (engine modules must declare `logger = logging.getLogger(__name__)`, no `print(` or `logging.basicConfig(` — helper modules listed in `LOGGER_REQUIRED_EXEMPT`); `tests/contracts/test_logging_contract.py` asserts every stage module exports a correctly-named `Logger` and that `observability.__all__` is stable; `tests/integration/test_logging_pipeline.py` runs the pipeline end-to-end and asserts entry/exit record pairs, shared `run_id`, distinct ids on back-to-back runs, no handler stacking, and no regulatory-error duplication. The ~19 `print()` calls in `src/rwa_calc/ui/marimo/server.py:main()` are converted to `logger.info` with `configure_logging("INFO", "text")` called at startup. New spec `docs/specifications/observability.md` documents the public API, record schema, levels, correlation-ID lifecycle, reference stage skeleton, enforcement layers, and anti-patterns. CLAUDE.md gains a **Logging** section mirroring the **Error Handling** section. `CalculationConfig` fields are listed in `docs/specifications/configuration.md` (FR-5.7, CONFIG-7).

### Changed
- Refactor: hoist SA risk-weight scalars and scaffold `lf.sa` namespace (no behavioural change).

---

## [0.1.63] - 2026-04-19

### Added
- **Real estate loan-splitter for SA exposures collateralised by property (CRR Art. 125/126, PRA PS1/26 Art. 124F/H)**: A new pipeline stage (`engine/re_splitter.py`) inserted between `CRMProcessor` and the calculators physically partitions a property-collateralised non-RE SA exposure into two rows — a secured row reclassified to `RESIDENTIAL_MORTGAGE` / `COMMERCIAL_MORTGAGE` capped at the regulatory secured-LTV cap, and an uncollateralised residual row that retains the original counterparty exposure class so the standard corporate / retail risk weight applies on the remainder. Both rows share a `split_parent_id` lineage key so downstream aggregations reconcile back to the parent exposure. Previously, a corporate / retail loan secured by eligible property collateral that was not already classified as a mortgage received the full counterparty risk weight on the entire EAD, materially overstating capital. Mechanics are identical across regimes; parameters (secured LTV cap / secured RW / prior-charge reduction / counterparty carve-outs) live in `data/tables/re_split_parameters.py` (`re_split_parameters(is_basel_3_1=...)`):
  - **CRR Art. 125 (RRE):** secured cap = 80% LTV, secured RW = 35%, residual at counterparty CQS RW.
  - **CRR Art. 126 (CRE):** secured cap = 50% LTV, secured RW = 50% — applied only when the rental coverage test (≥ 1.5× interest costs) is met (new optional input `rental_to_interest_ratio` on collateral). When not met, no split is applied (`RE004` informational warning) and the exposure stays in its original class. Default conservative (no split) when the column is absent.
  - **B3.1 Art. 124F (RRE):** secured cap = 55% × property value (less prior charges per Art. 124F(2)), secured RW = 20%, residual at counterparty RW.
  - **B3.1 Art. 124H(1)-(2) (CRE NP/SME):** secured cap = 55% × property value, secured RW = 60%, residual at counterparty RW. Restricted to natural persons / SMEs.
  - **B3.1 Art. 124H(3) (CRE other):** no physical split; the whole exposure becomes a single `COMMERCIAL_MORTGAGE` row so the existing `b31_commercial_rw_expr` Art. 124H(3) branch (`max(60%, min(cp_rw, Art. 124I RW))`) handles it.

  The split is gated by a new classifier Phase 4c (`_flag_property_reclassification_candidates`) that emits `re_split_target_class`, `re_split_mode` (`"split"` / `"whole"` / null), `re_split_property_type`, `re_split_property_value`, and `re_split_cre_rental_coverage_met` candidate columns. Income-producing real estate continues to use the existing whole-loan path (Art. 124G / Art. 124I bands); already-classified `RESIDENTIAL_MORTGAGE` / `RETAIL_MORTGAGE` / `COMMERCIAL_MORTGAGE` / defaulted / equity / CIU / subordinated / high-risk / covered-bond rows are excluded from the split. The downstream SA RW expressions are reused unchanged — the secured row's LTV is capped by construction at the secured-LTV threshold, so the existing `b31_residential_rw_expr` / `b31_commercial_rw_expr` / CRR `_apply_residential_mortgage_rw` paths produce 35% / 50% / 20% / 60% naturally, and the residual row keeps its original `exposure_class` and gets the corporate / retail RW. Provisions allocate pro-rata by the EAD share. New audit LazyFrame `CRMAdjustedBundle.re_split_audit` captures one row per parent (parent EAD, secured/residual EAD, effective cap, target class, regime). New error codes: `RE001` (non-eligible RE), `RE002` (zero effective cap), `RE003` (mixed property types), `RE004` (CRR CRE rental coverage failed). New `RealEstateSplitterProtocol` in `contracts/protocols.py`. 14 new unit tests (`tests/unit/test_real_estate_splitter.py`), 3 end-to-end pipeline integration tests (`tests/integration/test_re_split_pipeline.py`), 2 protocol contract tests. Output floor / aggregator semantics unchanged: each child row contributes its own `sa_rwa` so portfolio-level totals are mathematically equivalent to the pre-split blended-RW row. Ref: CRR Art. 125, Art. 126(2)(d); PRA PS1/26 Art. 124A, Art. 124F, Art. 124F(2), Art. 124H(1)-(3), Art. 124L; SS10/13.

- **Regression coverage: IRB-denied exposures must still use the counterparty's external ECAI rating on SA**: `tests/integration/test_model_permissions_pipeline.py::TestIRBDeniedUsesExternalRatingOnSA` adds three end-to-end tests that wire a counterparty with **both** an internal rating (PD + `model_id`) and an external rating (CQS) through the full pipeline, then assert that when `model_permissions` deny IRB (via `filter_rejected` on exposure-class mismatch, via `unmatched_model_id`, and via PRA PS1/26 Art. 147A(1)(a) sovereign SA-only routing) the resulting SA row carries `approach="SA"`, the counterparty's external `cqs`, and a CQS-based `risk_weight` rather than the unrated fallback — the scenario the CLS006 diagnostic warning already signals. A new `_make_external_rating` helper mirrors the existing `_make_internal_rating` shape. These tests pin down the expected behaviour end-to-end; previously, `tests/integration/test_model_permissions_pipeline.py` and `tests/acceptance/basel31/test_scenario_b31_m_model_permissions.py` always built internal-only ratings with `cqs=None`, so the external-rating path through SA after IRB denial was never exercised from rating inheritance through `SACalculator._apply_risk_weights`.

### Changed
- **Institution guarantor RW expression unified**: SA (`engine/sa/calculator.py::_apply_guarantee_substitution`) and IRB (`engine/irb/guarantee.py::_compute_guarantor_rw_sa`) guarantee substitution paths had near-identical hard-coded `pl.when().then()` ladders for institution CQS → RW with `pl.lit(0.30) if config.is_basel_3_1 else pl.lit(0.50)` branches. Extracted shared helper `build_institution_guarantor_rw_expr(cqs_col, is_basel_3_1)` in `data/tables/crr_risk_weights.py` that drives values from `INSTITUTION_RISK_WEIGHTS_CRR` / `INSTITUTION_RISK_WEIGHTS_B31_ECRA` so the dicts remain the single source of truth and the two sites cannot drift on future edits. Also removed the dead `extra_cols={"is_basel_3_1": ...}` column previously emitted by `_create_institution_df` (never consumed by any downstream join).

### Fixed
- **RGLA / PSE institution-treated exposures now correctly route to IRB (CRR Art. 147(3)/(4)(b), PRA PS1/26 Art. 147A(1)(b))**: `rgla_institution` and `pse_institution` counterparties carrying an internal rating were silently forced to SA regardless of IRB permissions. Under CRR the org-wide `IRBPermissions.full_irb()` map keys IRB eligibility off `exposure_class`, but the classifier set `exposure_class` from the SA map (RGLA / PSE) while `full_irb()` only listed CGCB / INSTITUTION / corporate / retail / SL — so every `rgla_*` / `pse_*` row's `firb_permitted_expr` evaluated to `False` and fell through to the SA default. Under Basel 3.1 the `_b31_sa_only` filter additionally swept `ExposureClass.RGLA` / `ExposureClass.PSE` into the Art. 147A(1)(a) sovereign-only set, but Art. 147(3) scopes that restriction to quasi-sovereigns with 0% SA RW (i.e. `rgla_sovereign` / `pse_sovereign` / `mdb` / `international_org`) — institution-treated variants should follow the Art. 147A(1)(b) INSTITUTION F-IRB-only path. Fix in `engine/classifier.py`: (1) `_build_orgwide_permission_exprs` and `_resolve_model_permissions` now key their permission-match expressions on `exposure_class_irb`; (2) `_b31_sa_only` now keys on `cp_entity_type` with the explicit Art. 147(3) list; (3) `_b31_institution_no_airb` now keys on `exposure_class_irb == INSTITUTION`; (4) new Step 4a re-syncs `exposure_class_irb` with the reclassified `exposure_class` after Phases 3-4 (SME / QRRE / retail) so retail-reclassified corporates still match retail model permissions; (5) after approach assignment, `exposure_class` is rewritten to `exposure_class_irb` for IRB-routed `rgla_*` / `pse_*` rows so the IRB calculator reads INSTITUTION / CGCB for correlation & LGD selection. SA-routed RGLA / PSE rows keep `exposure_class = RGLA` / `PSE` and continue to use Art. 115 / Art. 116 SA risk weight tables. Net effect under CRR: a `rgla_institution` with internal PD + modelled LGD now correctly lands on A-IRB via the INSTITUTION class; under B3.1 it lands on F-IRB with supervisory LGD per Art. 147A(1)(b). 11 new regression tests in `tests/unit/test_b31_approach_restrictions.py` (`TestCRRRGLAPSEIRBRouting` plus additional `TestB31QuasiSovereignSAOnly` cases) cover CRR AIRB/FIRB routing, B3.1 FIRB routing, A-IRB blocking under B3.1, LGD clearing, and SA-fallback behaviour for unrated rgla/pse rows. Full suite: 4,711 unit passed, 627 acceptance + integration passed. `IRBPermissions.full_irb_b31()` permissions map unchanged (RGLA / PSE / MDB entries remain as defensive defaults); docstring updated to clarify the quasi-sovereign scope is tied to the 0%-RW entity treatment, not the SA exposure class label. Ref: CRR Art. 147(3), Art. 147(4)(b); PRA PS1/26 Art. 147A(1)(a), Art. 147A(1)(b) read with Art. 147(3).
- **CRR Art. 138 multi-rating resolution now applied**: `HierarchyResolver._build_rating_inheritance_lazy` in `engine/hierarchy.py` previously collapsed multiple external ratings per counterparty to the single most recent one, silently ignoring assessments from additional nominated ECAIs. Replaced the "most recent wins" logic for external ratings with Art. 138: per-agency dedup (most recent per agency) followed by the 1-rating / 2-rating (higher RW) / ≥ 3-rating (second-best) selection rule. Resolution is performed on CQS rather than RW because within every SA exposure class the CQS → RW mapping is monotone non-decreasing. Internal-rating resolution, inheritance, and the external-rating non-inheritance rule are unchanged. New `TestArt138ExternalRatingResolution` class in `tests/unit/test_hierarchy.py` covers single/two/three/four-rating cases, ties at the two lowest CQS, same-agency repeats, and null-CQS rows. Existing fixture counterparties have ≤ 1 external agency each, so no acceptance-golden changes. Ref: CRR Art. 138.

- **CRR Art. 120(2) Table 4 short-term rated institution risk weights now applied [P1.99]**: The CRR SA branch fell through to Art. 120 Table 3 (long-term) for every rated institution regardless of maturity, so a CQS 2 institution with 1-month residual maturity received the 50% long-term weight instead of the 20% Table 4 short-term weight. Added `INSTITUTION_SHORT_TERM_RISK_WEIGHTS_CRR` in `data/tables/crr_risk_weights.py` (CQS 1-3 = 20%, CQS 4-5 = 50%, CQS 6 = 150%) and a new `.when()` branch in `engine/sa/calculator.py` keyed on `residual_maturity_years <= 0.25` with `INSTITUTION` exposure class and non-null CQS. CRR Art. 120(2) keys on *residual* maturity and imposes no domestic-currency restriction (distinct from Art. 119(2)). Diverges from B31 Table 4 which applies 20% uniformly across CQS 1-5.
- **CRR Art. 121(3) unrated institution short-term 20% RW now applied [P1.121]**: The CRR SA branch provided no short-term override for unrated institutions, so a 1-month-original-maturity unrated institution fell through to the Table 5 sovereign-derived fallback (typically 100%). Added `INSTITUTION_SHORT_TERM_UNRATED_RW_CRR = 0.20` and a `.when()` branch in `engine/sa/calculator.py` keyed on `original_maturity_years <= 0.25` with `INSTITUTION` exposure class and null-or-zero CQS. Art. 121(3) uses *original* effective maturity (consistent with the P1.133 B31 PSE/SCRA fix), so a seasoned 5-year bond with 1 month remaining does NOT qualify. Art. 121(6) sovereign floor (applied later via `_apply_sovereign_floor_for_institutions`) still lifts this to the sovereign weight for FX exposures. Capital previously overstated by up to 80 percentage points for short-term unrated interbank exposures.
- Both fixes: 13 new regression tests in `tests/unit/crr/test_crr_institution_standard.py` (`TestCRRShortTermInstitutionTables`, `TestCRRShortTermInstitutionSACalculator`) cover parametrized CQS 1-6 short-term rated, >3m fall-through, unrated short-term, original vs residual maturity keying, sovereign-floor interaction, and B31 isolation. 2 existing tests in `tests/unit/test_b31_sa_risk_weights.py` that previously asserted CRR does NOT apply short-term treatment renamed to assert the new correct behaviour. Full suite: 5,329 passed, 21 skipped. Ref: CRR Art. 120(1)-(2), Art. 121(3)/(6).
- **Short-term PSE/institution treatment now keys on original maturity [P1.133]**: `SACalculator._SA_INPUT_CONTRACT` extended with `original_maturity_years`, `value_date`, `maturity_date`; `calculate_branch` derives `original_maturity_years` inline from `(maturity_date - value_date)/365.0` when the column is null, so hierarchy-supplied facility data flows through without a new schema column. Five SA call-sites updated to use `original_maturity_years`: B31 PSE short-term (Art. 116(3)), B31 ECRA rated institution short-term (Art. 120(2)/(2A) incl. 6m trade-goods carve-out), B31 SCRA unrated institution short-term (Art. 121(3)), CRR PSE short-term (Art. 116(3)), and Art. 121(6) trade-goods sovereign-floor exception. Previously a 5-year bond with 1 month residual incorrectly attracted short-term 20% RW; it now correctly receives the long-term CQS/SCRA weight. 8 new regression tests cover seasoned-vs-fresh scenarios across both CRR and B31 branches in `tests/unit/test_pse_risk_weights.py` and `tests/unit/test_b31_sa_risk_weights.py`. Understates-capital bug; fix tightens RWs on seasoned short-residual exposures. Ref: CRR Art. 116(3), PRA PS1/26 Art. 120(2)/(2A), Art. 121(3)/(6).
- **PRA PS1/26 Art. 224 Table 1 B31 haircut corrections [P1.155]**: `BASEL31_COLLATERAL_HAIRCUTS` in `data/tables/haircuts.py` had 9 stale values (P1.155 originally cited 4; PDF verification found 5 more in the same table). Corrections verified against ps126app1.pdf p.203: sovereign CQS 2-3 3_5y 4%→3% and 10y+ 12%→6%; corp/institution CQS 1 1_3y/3_5y/5_10y 4/6/10%→3/4/6%; corp/institution CQS 2-3 1_3y/3_5y/5_10y/10y+ 6/8/15/15%→4/6/12/20%. The 10y+ CQS 2-3 correction (15%→20%) widens FCCM haircut on long-dated lower-rated corporate bonds (capital increase); the other 8 corrections were conservative over-haircuts whose correction reduces collateral haircut in FCCM, increases collateral value recognised, and lowers post-CRM EAD. Test class `TestBasel31BondHaircuts` in `tests/unit/crm/test_crm_basel31.py` parametrized into a single `test_b31_bond_haircuts_match_pra_table_1` with 13 cases; `test_b31_corp_bond_long_dated_higher_haircut` in `TestHaircutCalculatorFrameworkBranching` updated accordingly. All 5,307 tests pass.
- **CRR Institution CQS 2 risk weight corrected to 50% (CRR Art. 120 Table 3) [P1.149]**: The CRR table (misnamed `INSTITUTION_RISK_WEIGHTS_UK`) conflated the PRA PS1/26 Basel 3.1 ECRA values (CQS 2 = 30%, unrated = 40%) with a non-existent "UK deviation" to CRR Art. 120, and the SA calculator keyed framework selection off `base_currency == "GBP"` via `use_uk_deviation`. Under CRR Art. 120 Table 3, CQS 2 institutions are 50% and unrated institutions are 100% — no deviation exists in the UK-onshored CRR. Renamed data tables to `INSTITUTION_RISK_WEIGHTS_CRR` and `INSTITUTION_RISK_WEIGHTS_B31_ECRA`; replaced `use_uk_deviation` boolean (keyed on base currency) with `config.is_basel_3_1` (keyed on framework) throughout `engine/sa/calculator.py`, `engine/irb/guarantee.py`, and `engine/equity/calculator.py`. Also caught an additional instance of the same root-cause bug in `irb/guarantee.py:269` where unrated institution guarantors were hard-coded to 40% regardless of framework — now returns 100% under CRR and 40% under B31. CRR-A4 acceptance scenario updated (RW 0.30 → 0.50, RWA £300k → £500k); CRR-D4 updated (blended RW 0.58 → 0.70). Unit tests in `tests/unit/test_sovereign_floor_institutions.py`, `test_b31_sa_risk_weights.py`, `test_covered_bonds.py`, `test_guarantor_exposure_class_rw.py`, `crr/test_crr_sa.py`, `crr/test_crr_tables.py`, `crr/test_crr_institution_standard.py`, and `crr/test_irb_namespace.py` updated to reflect the correct CRR values.
- **HVCRE Good slotting EL rate corrected to 0.4% (PRA PS1/26 Art. 158(6) Table B) [P1.150]**: Both `B31_SLOTTING_EL_RATES_HVCRE[GOOD]` (`data/tables/b31_slotting.py`) and `SLOTTING_EL_RATES_HVCRE[GOOD]` (`data/tables/crr_slotting.py`) returned 0.8% — mirroring non-HVCRE long-maturity Good — but PRA PS1/26 Table B (Appendix 1 p.108) shows the HVCRE row flat at 0.4% across both Strong (cols A/B) and Good (cols C/D), i.e. HVCRE collapses the subgrade differentiation that non-HVCRE retains. **Halves the EL shortfall for HVCRE Good exposures** (capital overstatement when EL > provisions). Under UK CRR the substantive Article 158 was omitted by SI 2021/1078 in 2022, so PRA PS1/26 Table B is the only extant UK source — applied symmetrically to both framework data tables. Updated unit tests in `tests/unit/test_slotting_el_rates.py` (renamed `test_hvcre_good_zero_point_eight` → `test_hvcre_good_zero_point_four` for both CRR and B31, replaced `test_hvcre_matches_long_maturity_non_hvcre` with `test_hvcre_good_diverges_from_non_hvcre_long_maturity` regression guard, parametrized cases `("good", True, False, ...)` and `("good", True, True, ...)` now expect 0.004). Updated B31 slotting spec admonition. Acceptance scenarios CRR-E4/E7/E8 unchanged (they assert HVCRE risk weights, not EL rates).
- **FX haircut on collateral silently zero after FX conversion (CRR Art. 224, PRA PS1/26 Art. 224) [P1.135/P1.136]**: `FXConverter.convert_exposures()` and `convert_collateral()` both rewrite the `currency` column to the reporting currency, so by the time `HaircutCalculator.apply_haircuts` compared `currency != exposure_currency` both sides were equal and the 8% Art. 224 FX volatility haircut was silently never applied to any FX-mismatched secured exposure (HIGH capital understatement). Root cause: only `convert_exposures` and `convert_guarantees` preserved `original_currency`; `convert_collateral`, `convert_provisions`, and `convert_equity_exposures` did not — and `_build_exposure_lookups` sourced the collateral-side `exposure_currency` from the post-conversion `currency`. Fix: (1) `engine/fx_converter.py` — all four sibling converters now alias `currency` into `original_currency` on both the conversion and no-conversion paths; (2) `engine/hierarchy.py` — removed the `apply_fx_conversion`/`fx_rates is not None` branching block (converters now handle the no-op path consistently); (3) `engine/crm/processor.py::_build_exposure_lookups` — prefers `original_currency` with fallback to `currency`; (4) `engine/crm/haircuts.py::apply_haircuts` — compares the collateral's `original_currency` with fallback. Regression coverage: 5 tests in `tests/unit/crm/test_collateral_fx_mismatch.py` (including the post-conversion pipeline path that the existing scalar-based `calculate_single_haircut` tests did not exercise) + 2 tests in `tests/unit/test_fx_converter.py` covering the new collateral audit column.
- **Domestic sovereign guarantor 0% RW uses guarantee currency (CRR Art. 114(4)/(7))**: The Art. 114(4)/(7) domestic-currency test on a guaranteed portion was being evaluated against the underlying exposure's currency rather than the guarantee's currency, which meant a GBP loan guaranteed by an EU sovereign in that sovereign's domestic currency (e.g. DE in EUR) did not receive 0% RW even though, under the substitution approach (Art. 215-217), the substituted claim against the sovereign is denominated in EUR. The Art. 233(3) 8% FX haircut already handles the cross-currency layer between guarantee and underlying loan; layering Art. 114(4)/(7) on top of the exposure currency effectively nullified Art. 233(3) for sovereign guarantees. Switched the three call sites that implement the check (`engine/crm/guarantees.py` routing, `engine/irb/guarantee.py::_compute_guarantor_rw_sa`, `engine/sa/calculator.py::_apply_guarantee_substitution`) to read `guarantee_currency` (already populated on guaranteed rows by `_apply_guarantee_splits`) with a null-safe fallback to the exposure's `denomination_currency_expr`. Added shared helper `build_domestic_cgcb_guarantor_expr` in `data/tables/eu_sovereign.py` combining the UK and EU-member branches into a single expression so the three sites cannot drift. New regression coverage: `tests/integration/test_domestic_sovereign_guarantor_end_to_end.py` (4 end-to-end cases through the full pipeline), a new `TestGuarantorSubstitutionReadsGuaranteeCurrency` class in `tests/unit/test_guarantor_exposure_class_rw.py` (5 cases covering the cross-currency SA+IRB substitution), and an extended `TestDomesticSovereignGuarantorForcedToSA` in `tests/unit/crm/test_guarantor_rating_type.py` adding the reported GBP-loan/EUR-guarantee/DE-sovereign case plus a guard against reading exposure currency (EUR loan + GBP guarantee + DE sovereign must stay IRB). Applies under both CRR and Basel 3.1 / PRA PS1/26.
- **Domestic sovereign guarantor 0% RW vs internal rating (CRR Art. 114(4)/(7))**: When a guarantee from an EU/UK central government/central bank in its domestic currency was provided by a counterparty that the firm rates internally (i.e. carries an `internal_pd`) and the firm holds IRB permission for the CGCB exposure class, the guarantor was being routed to the IRB substitution path. The downstream `_apply_parameter_substitution` step in `engine/irb/guarantee.py` then overwrote the SA branch's correct 0% RW with the parametric F-IRB risk weight derived from the PD, so e.g. a DE sovereign + EUR guarantor with `internal_pd = 0.001` produced ~2.6% instead of the regulatory 0%. The previous EU/UK domestic 0% fix (PR #253) handled the FX-conversion edge case but only inside the SA branch — it did not change routing, so internal-PD guarantors bypassed it. Promoted the Art. 114(4)/(7) check into the guarantor-approach routing step in `engine/crm/guarantees.py`: domestic-currency CGCB guarantors are now forced to `guarantor_approach = "sa"` ahead of the internal-PD branch, so the existing SA 0% short-circuit fires regardless of whether the guarantor has an internal rating. The `guarantor_rating_type` audit field is unchanged — still reports `"internal"` when an internal PD exists, since the override is an approach decision, not a rating-source decision. Reuses `build_eu_domestic_currency_expr` and `denomination_currency_expr` (post-FX safe). Applies under both CRR (Art. 114(4) UK/GBP, Art. 114(7) EU member states) and Basel 3.1 (PRA PS1/26 preserves Art. 114(7) by cross-reference via third-country reciprocity). Added `TestDomesticSovereignGuarantorForcedToSA` regression class in `tests/unit/crm/test_guarantor_rating_type.py` covering UK/GBP, DE/EUR (post-FX), PL/PLN (non-euro EU) and a non-domestic DE/USD counter-case under both frameworks.

---

## [0.1.62] - 2026-04-17

### Changed
- Version bump for PyPI release

---

## [0.1.61] - 2026-04-15

### Fixed
- **EU sovereign guarantee 0% RW (CRR Art. 114(4))**: Exposures guaranteed by an EU member state central government/central bank in that state's domestic currency (e.g. a German sovereign guaranteeing a EUR-denominated exposure) were failing to receive the mandated 0% risk weight when the pipeline's FX converter was active. Root cause: `engine/fx_converter.py` overwrites the exposure's `currency` column with the reporting currency and stores the pre-conversion denomination in `original_currency`, but every downstream "denominated in domestic currency" check read the now-overwritten `currency` column. After FX conversion a DE sovereign + EUR exposure appeared as DE + GBP (or whatever the reporting currency was), so the Art. 114(4) short-circuit never fired; unrated EU sovereign guarantors then fell through to `.otherwise(1.0)` = 100% instead of 0%. Added `denomination_currency_expr()` helper in `data/tables/eu_sovereign.py` that returns `pl.col("original_currency")` when present, else `pl.col("currency")`. Extended `build_eu_domestic_currency_expr` to accept a `pl.Expr` for the currency side. Updated all seven affected call sites in `engine/sa/calculator.py` (borrower + guarantor), `engine/irb/guarantee.py` (guarantor, IRB path), and `engine/classifier.py` (forced-SA check for EU domestic sovereigns). Existing `TestSAEUDomesticSovereignTreatment` unit tests were bypassing the bug because they fabricated LazyFrames with `currency` set to the denomination directly; added `TestSAEUDomesticSovereignPostFX` / `TestIRBEUDomesticSovereignPostFX` regression classes covering the post-FX pipeline state.

---

## [0.1.60] - 2026-04-14

### Changed
- **Data tables**: Eliminated duplicated regulatory values in `data/tables/`. Previously most `_create_*_df` builders hardcoded numeric literals that were already defined in the module's constant dicts (`CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS`, `CORPORATE_RISK_WEIGHTS`, `COLLATERAL_HAIRCUTS`, `BASEL31_FIRB_SUPERVISORY_LGD`, etc.), meaning a regulatory update required changes in 2+ places. Builders now derive their values by iterating the authoritative dict: new helpers `_build_cqs_rw_df` (crr), `_build_int_cqs_rw_df` (b31), `_build_haircut_df` (haircuts), and `_build_firb_lgd_df` / `_build_b31_firb_lgd_df` (firb_lgd) read values from the dicts via small row-spec tuples that define column ordering. `B31_FIRB_LGD_*` scalar aliases now derive from `BASEL31_FIRB_SUPERVISORY_LGD`. Matches the gold-standard pattern already used in `b31_equity_rw.py`. New test `tests/unit/test_tables_dict_dataframe_parity.py` (18 cases) locks in the invariant so regressions cannot reintroduce duplication. DataFrame schemas, column/row ordering, and public API are unchanged — no regulatory values changed.
- **Data tables**: Renamed `data/tables/crr_haircuts.py` -> `data/tables/haircuts.py` and `data/tables/crr_firb_lgd.py` -> `data/tables/firb_lgd.py`; both files already held dual-framework content (CRR Art. 224/161 and PRA PS1/26 equivalents), so the `crr_` prefix was misleading. Merged `data/tables/b31_firb_lgd.py` into `firb_lgd.py` — it was a thin re-export of the Basel 3.1 LGD dict that physically lived in the CRR-prefixed file. All `BASEL31_*` / `B31_*` constants, lookup helpers (`lookup_b31_firb_lgd`, `get_b31_firb_lgd_table`, `get_b31_vs_crr_lgd_comparison`), and framework-shared helpers (`FIRB_OVERCOLLATERALISATION_RATIOS`, `FIRB_MIN_COLLATERALISATION_THRESHOLDS`, `CRR_K_SCALING_FACTOR`) are now in `firb_lgd.py`. Module docstrings updated to reflect dual-framework scope; `crm_supervisory.py` docstring updated to match. Import sites updated across `engine/`, tests, and docs; public `data/tables/__init__.py` re-exports preserved. No regulatory values changed.

---

## [0.1.59] - 2026-04-14

### Changed
- Version bump for PyPI release

---

## [0.1.58] - 2026-04-11

### Fixed
- **Guarantees (#239)**: Fixed two bugs in multi-guarantor handling:
  1. **Non-beneficial guarantors consuming EAD**: When an exposure has multiple guarantors and some are non-beneficial, the pro-rata scaling no longer wastes EAD on non-beneficial guarantors. After the SA/IRB beneficial check, a new `redistribute_non_beneficial()` function reallocates freed portions to beneficial guarantors using a greedy strategy ordered by ascending risk weight (lowest RW fills first), minimising total RWA.
  2. **FX/restructuring haircuts applied after capping**: The 8% FX mismatch haircut (Art. 233(3-4)) and 40% CDS restructuring exclusion haircut (Art. 233(2)) are now applied to the nominal credit protection value (G) *before* capping at EAD, per CRR Art. 233/235. Previously, a large cross-currency guarantee that vastly exceeded EAD would incorrectly have coverage reduced (e.g. £200m guarantee on €1m loan → was 920k, now correctly 1m).
- **CCF (P1.166)**: CRR OC (Other Commitments) CCF corrected from **0%** to maturity-dependent values. Under CRR, the OC category did not exist — commitments were classified by maturity: >1yr → MR (50% SA / 75% F-IRB), ≤1yr → MLR (20% SA / 75% F-IRB). The only 0% category was LR (unconditionally cancellable). Previously **understated capital** for all OC-tagged exposures under CRR. SA CRR: OC now receives 50% (>1yr) or 20% (≤1yr, based on maturity_date vs reporting_date); 50% conservative default when maturity_date absent. F-IRB CRR: OC moved from 0% to 75% (both MR and MLR are 75% under F-IRB). Basel 3.1 OC (40%) unchanged. Updated `sa_ccf_expression()`, `_firb_ccf_for_col()`, and `_compute_ccf()` with maturity-aware override. Spec F-IRB table corrected. 7 unit tests updated, 6 new tests added.
- **Equity (P1.132)**: B31 government-supported equity risk weight corrected from 100% to **250%** per Art. 133(3). Art. 133(6) is an exclusion clause (own funds deductions, Art. 89(3), Art. 48(4)), not a 100% risk weight — CRR Art. 133(3)(c) legislative equity carve-out has no equivalent in B31. Previously **understated capital** by 2.5x for government-supported equity under B31. Government-supported equity also removed from transitional floor exclusion (now subject to floor as standard equity, though 250% already exceeds all transitional floors). Updated risk weight table, calculator, transitional floor logic, 8 unit tests, 4 acceptance tests, and spec documentation. Art. 133 paragraph references corrected across codebase (subordinated debt = Art. 133(5) not 133(1); PE/VC = Art. 133(4) not 133(5)).
- **Covered Bonds (P1.113)**: B31 rated covered bond risk weights corrected from BCBS CRE20.28 values to PRA PS1/26 Art. 129(4) Table 7 values. CQS 2: 15%→20%, CQS 6: 50%→100%. PRA retained CRR Table 6A unchanged — did NOT adopt BCBS reductions. Previously **understated capital** for CQS 2 and CQS 6 covered bonds. Both `B31_COVERED_BOND_RISK_WEIGHTS` dict and `_create_b31_covered_bond_df()` DataFrame corrected. All 77 covered bond tests updated. 3 stale doc divergence warnings converted to "Fixed" admonitions.
- **Equity (P1.119)**: CIU fallback risk weight corrected from 150% (CRR) / 250%-400% (B31) to **1,250%** per Art. 132(2). Was the highest-severity capital understatement bug (3-8x). Root cause: original implementation used Art. 133 equity risk weights instead of Art. 132(2) punitive CIU fallback. Extracted shared `CIU_FALLBACK_RW` constant and `_append_ciu_branches()` helper to eliminate CRR/B31 code duplication. Updated risk weight tables, calculator, 27 unit tests, 7 acceptance tests, and both equity spec documents.

---

## [0.1.57] - 2026-04-11

### Changed
- **Naming**: Renamed functions with "and" in their names to better reflect single responsibility:
  - `_classify_sme_and_retail` -> `_classify_exposure_subtypes` (classifier)
  - `_determine_approach_and_finalize` -> `_assign_approach` (classifier)
  - `_sink_and_scan` -> `_spill_to_disk` (materialise)
  - `_combine_irb_and_slotting` -> `_merge_el_sources` (EL summary aggregator)
  - `commit_and_push` -> `publish_changes` (git ops)
- **Classifier**: Moved `B31_LARGE_CORPORATE_REVENUE_THRESHOLD_GBP` (PRA PS1/26 Art. 147A(1)(e)) and `B31_SME_TURNOVER_THRESHOLD_GBP` (PRA PS1/26 Art. 153(4)) from `engine/classifier.py` to `data/tables/b31_risk_weights.py` for consistency with other B31 regulatory thresholds. Converted from `float` to `Decimal`.
- **Pipeline**: Renamed private methods in `PipelineOrchestrator` to remove stale fan-out/single-pass terminology: `_run_crm_processor_unified` -> `_run_crm_processor`, `_run_single_pass` -> `_run_calculators`, `_aggregate_single_pass` -> `_aggregate_results`. Section header renamed from "Single-Pass Pipeline" to "Calculation".
- **Pipeline**: Removed dead code `_run_sa_calculator` and `_run_irb_calculator` (never called from production; superseded by `calculate_branch()` in the single-pass path). Associated tests removed.

---

## [0.1.56] - 2026-04-11

### Changed
- Version bump for PyPI release

---

## [0.1.55] - 2026-04-09

### Fixed
- **Classifier**: Exposures with internal ratings no longer silently route to Standardised Approach when `permission_mode="irb"` is set on `CreditRiskCalc`. Two independent bugs are addressed:
  - **Pipeline downgrade (Bug #1)**: `PipelineOrchestrator.run_with_data` used `dataclasses.replace(config, permission_mode=STANDARDISED)` when `model_permissions` was absent, which re-ran `CalculationConfig.__post_init__` and wiped `irb_permissions` to `sa_only()`. The pipeline now preserves the user's org-wide IRB permissions and emits a `missing_model_permissions` pipeline error explaining that per-model gating is disabled.
  - **Silent classifier join failure (Bug #2)**: `ExposureClassifier._resolve_model_permissions` joined `exposure.model_id` LEFT against `model_permissions.model_id`. Null or unmatched `model_id` values produced no match and silently routed to SA with no diagnostic. The classifier now tags each IRB-eligible miss with one of three causes (`null_model_id`, `unmatched_model_id`, `filter_rejected`) and emits a rolled-up `CLS006` (`ERROR_MODEL_PERMISSION_UNMATCHED`) classification warning per cause with targeted remediation guidance.
- **Tests**: Added `TestModelPermissionsDiagnostics` (4 integration tests) and `TestPipelineIRBWithoutModelPermissions` (1 integration test) in `tests/integration/test_model_permissions_pipeline.py`, plus a regression guard `test_irb_mode_preserves_full_irb_after_pipeline_init` in `tests/unit/test_irb_approach_selection.py`.
- **Docs**: Replaced fabricated double-default formula in `crm.md` with correct CRR Art. 153(3) formula `K_dd = K_obligor × (0.15 + 160 × PD_guarantor)` (D3.7). Added eligibility requirements (Art. 202/217), guarantor RW floor, and Basel 3.1 removal warning with cross-link to A-IRB spec.
- **Docs**: SA specialised lending waterfall position documented in `key-differences.md` (D2.20). Waterfall item 15 annotated with Art. 122–122B SA SL sub-classification cross-reference. New admonition added explaining SA SL sits within corporates (row 15, Art. 112(1)(g)), with IPRE excluded per Art. 122A(1) ("not a real estate exposure") — IPRE is caught at row 7 (real estate, Art. 124–124L) instead. SA SL section expanded with:
  - Art. 122A(1) 4-part definition criteria (SPV structure, asset dependency, lender control, asset income repayment)
  - Art. 122A(2) sub-type classification (OF, CF, PF)
  - IPRE exclusion warning admonition with cross-reference to real estate section
  - Art. 122B(1) rated SL fallthrough to corporate CQS table
  - Art. 122B(2) unrated risk weight table with article references per row
  - Art. 122B(3) operational phase definition (positive net cash-flow + declining LT debt)
  - Art. 122B(4)–(5) high-quality PF criteria (8 structural conditions)

---

## [0.1.54] - 2026-04-08

### Added
- **COREP**: Reporting basis conditionality for output floor (P1.38(c)). `COREPGenerator` now accepts `output_floor_config: OutputFloorConfig` to gate floor-related COREP template content on entity-type applicability per Art. 92 para 2A:
  - **OF 02.00 rows 0034-0036** (floor activated/multiplier/OF-ADJ) show 0.0 for exempt entities (international subsidiaries, ring-fenced bodies on individual basis, etc.)
  - **OF 02.01** (output floor comparison) returns None for exempt entities — only applicable entities report the floor comparison
  - **C 08.07 materiality columns 0160-0180** documented as consolidated-basis-only (Art. 150(1A)), threaded with `is_consolidated` flag for future population
  - **COREPTemplateBundle** extended with `reporting_basis` and `institution_type` metadata fields
  - **ResultExporterProtocol** and **ResultExporter** accept `output_floor_config` keyword parameter
- **Tests**: 38 new tests in `tests/unit/test_corep_reporting_basis.py` across 7 test classes: COREPTemplateBundleMetadata (7), OF0201FloorApplicability (6), OF0200FloorIndicatorRows (7), C0807MaterialityColumns (4), BackwardCompatibility (3), EntityTypeCombinations (9 parametrized), ExporterProtocolCompliance (2). Total: 5,125 (was 5,087). Contract tests: 145.
- **Tests**: 26 new tests in `tests/unit/crm/test_equity_main_index.py` across 7 test classes: schema validation, CRR/B31 haircut verification for main-index and other-listed, backward compatibility, precedence over eligibility flag, mixed collateral, and full pipeline end-to-end (other-listed EAD = 625k vs main-index EAD = 575k on 1M exposure with 500k equity collateral). Total: 5,087 (was 5,061).
- **Tests**: 36 new CRM acceptance tests in `tests/acceptance/crr/test_scenario_crr_d2_crm_advanced.py` across 13 test classes covering advanced CRM scenarios not tested by the basic D1-D6/G1-G3 groups: non-beneficial guarantee (guarantor RW = borrower RW), sovereign guarantee 0% substitution, CDS restructuring exclusion (40% haircut, Art. 216(1)/233(2)), CDS with restructuring (no haircut contrast), gold collateral (15% CRR haircut), equity collateral (main-index 15%), overcollateralisation (EAD=0), full CRM chain (provision+collateral+guarantee), mixed collateral types (cash+bond), SA provision EAD deduction, multiple provisions summed, provision+collateral combined, and structural baseline validation. CRR acceptance: 169 (was 133). Total: 5,061 (was 5,025). (P5.3)
- **COREP**: C 09.01 / OF 09.01 — CR GB 1 geographical breakdown SA. One DataFrame per country code + TOTAL. CRR: 13 columns (0010-0090 incl. supporting factors), 23 rows. Basel 3.1: 10 columns (removes supporting factors), 29 rows (adds SL sub-rows 0071-0073, RE sub-rows 0091-0094, removes short-term row). Uses `cp_country_code` from counterparty schema. Template definitions, generator methods, class maps, framework selectors.
- **COREP**: C 09.02 / OF 09.02 — CR GB 2 geographical breakdown IRB. One DataFrame per country code + TOTAL. CRR: 17 columns (incl. PD, LGD, EL, supporting factors), 16 rows (incl. equity). Basel 3.1: 15 columns (adds 0107 defaulted EV, removes supporting factors), 19 rows (adds corporate sub-rows, restructures retail RE, removes equity).
- **Tests**: 80 new COREP tests for C 09.01/09.02 across 10 test classes. COREP tests: 635 (was 555). Total: 4,953 (was 4,873). (P2.3)
- **COREP**: C 08.04 / OF 08.04 — CR IRB RWEA flow statements. 1 column (RWEA) × 9 rows (opening, 7 movement drivers, closing) per IRB exposure class. Closing RWEA (row 0090) populated from pipeline; opening and drivers null (require prior-period data). Slotting excluded. CRR column names "after supporting factors"; Basel 3.1 removes supporting factors reference. Template definitions: `CRR_C08_04_COLUMNS`, `B31_C08_04_COLUMNS`, `C08_04_ROWS`, `C08_04_COLUMN_REFS`, `get_c08_04_columns()`. Generator: `_generate_all_c08_04()`, `_generate_c08_04_for_class()`. `COREPTemplateBundle.c08_04` field (dict[str, pl.DataFrame]). Excel export with C 08.04 / OF 08.04 prefix.
- **Tests**: 41 new COREP tests for C 08.04 across 6 test classes (TestC0804TemplateDefinitions: 13, TestC0804Generation: 5, TestC0804ClosingRWEA: 4, TestC0804NullDriverRows: 9, TestC0804B31Features: 3, TestC0804EdgeCases: 7). COREP tests: 555 (was 514). (P2.2)
- **Pillar III**: UKB CR9 — IRB PD backtesting per exposure class (Art. 452(h)). 8 columns × 17 PD buckets + total row. Basel 3.1 only. Separate F-IRB and A-IRB template sets. Uses `irb_pd_original` for bucket allocation (beginning-of-period proxy). Includes obligor count, default count, observed default rate, EAD-weighted average PD, arithmetic mean PD, historical annual default rate.
- **Pillar III**: UKB CR9.1 — ECAI mapping PD backtesting (Art. 180(1)(f)). Template definitions only; generation deferred until pipeline provides firm-specific ECAI mapping data.
- **Pillar III**: `Pillar3TemplateBundle.cr9` field added (dict of approach–class keyed DataFrames)
- **Pillar III**: CR9 Excel export via `export_to_excel()` with human-readable sheet names (e.g., "UKB CR9 F-IRB Corp")
- **Tests**: 44 new tests for CR9/CR9.1 across 7 test classes (definitions, generation, column values, PD allocation, edge cases, bundle integration, Excel export). Total: 4,832 (was 4,788). (P3.2)

### Fixed
- **Docs**: Art. 128 (high-risk items, 150%) UK CRR omission clarified across 6 files (D1.28, D4.9). Art. 128 was omitted from UK onshored CRR by SI 2021/1078, reg. 6(3)(a), effective 1 January 2022 — the high-risk exposure class is a dead letter under current UK CRR. Re-introduced under PRA PS1/26 (Basel 3.1, from 1 January 2027) with paragraphs 1 and 3 retained (paragraph 2 left blank). Files updated:
  - `specifications/crr/sa-risk-weights.md`: Added omission admonition, B31 re-introduction note, code bug cross-reference (D3.12), and exposure class waterfall clarification (equity priority 3 > high-risk priority 4)
  - `user-guide/exposure-classes/other.md`: Restructured "Items Associated with High Risk" section — added framework applicability warning, corrected table to Art. 128 items only (speculative RE, PRA-designated), added waterfall note explaining PE/VC are equity (Art. 133), not high-risk
  - `framework-comparison/key-differences.md`: Corrected equity table row (removed "(or 150% if Art. 128 high-risk)" — PE/VC is equity per waterfall), added Art. 128 re-introduction admonition to priority waterfall section
  - `user-guide/regulatory/crr.md`: Added "Omitted Provisions" section documenting Art. 128 and Art. 132 omissions by SI 2021/1078
  - `specifications/crr/equity-approach.md`: Corrected Art. 128 note to explain waterfall precedence (equity > high-risk) and UK CRR omission
  - `specifications/common/hierarchy-classification.md`: Updated calculator coverage note with Art. 128 framework status and CRR legal basis issue
- **Docs**: Documentation accuracy sweep correcting wrong regulatory values across 13 files (P4.5, P4.6, P4.22):
  - **PD floors (P4.5)**: Retail mortgage Basel 3.1 PD floor corrected from 0.05% to **0.10%** (Art. 163(1)(b)) in 5 files. QRRE transactor Basel 3.1 PD floor corrected from 0.03% to **0.05%** (Art. 163(1)(c)) in 5 files. Affected: `api/configuration.md`, `user-guide/configuration.md`, `user-guide/exposure-classes/retail.md`, `data-model/regulatory-tables.md`.
  - **LGD floors (P4.6)**: Corporate LGD floor code example corrected (RECEIVABLES 15%→10%, CRE 15%→10%, OTHER_PHYSICAL 20%→15%) in `user-guide/configuration.md`. Corporate `residential_real_estate` field corrected from 0.05 to **0.10** (Art. 161(5)) in `api/configuration.md` — was showing retail floor instead of corporate floor.
  - **Output floor schedule (P4.22)**: BCBS 6-year schedule (50%/55%/60%/65%/70%/72.5%, 2027–2032) replaced with PRA 4-year schedule (**60%/65%/70%/72.5%**, 2027–2030) across 12 files. Affected: `plans/implementation-plan.md`, `api/engine.md`, `api/contracts.md`, `framework-comparison/reporting-differences.md`, `plans/prd.md`, `specifications/index.md`, `features/index.md`, `specifications/regulatory-compliance.md`, `framework-comparison/index.md`, `appendix/index.md`, `framework-comparison/impact-analysis.md`, `user-guide/configuration.md`.
- **CRM**: Decoupled `is_main_index` from `is_eligible_financial_collateral` for equity collateral haircuts (P6.21). Added `is_main_index` Boolean field to `COLLATERAL_SCHEMA`. When present, drives haircut lookup directly: `True` = main-index (CRR 15%, B31 20%), `False` = other-listed (CRR 25%, B31 30%). When absent, falls back to `is_eligible_financial_collateral` for backward compatibility. Previously all eligible equity was forced to the main-index haircut tier.
- **COREP**: OF 02.00 IRB sub-row splits — rows 0295-0297 (FSE/large, SME, non-SME corporates), 0355-0356 (retail RE SME/non-SME), 0382-0385 (corporate RE sub-splits), 0400/0410 (other retail SME/non-SME) now populated from pipeline data instead of hardcoded 0.0. Uses finer-grained aggregation keyed by (approach, exposure_class, is_sme, apply_fi_scalar, property_type).
- **COREP**: OF 02.00 floor indicator rows 0035/0036 — floor_pct and of_adj now populated from `OutputFloorSummary` when provided, instead of hardcoded 0.0.
- **COREP**: `_filter_re()` fallback chain — gracefully degrades from `materially_dependent_on_property` → `has_income_cover` → `is_income_producing` when pipeline columns vary. Null handling corrected: only fallback columns use `fill_null(False)`, preserving null-as-unclassified semantics for the primary column.
- **Equity**: `_apply_transitional_floor()` now emits `equity_transitional_approach` and `equity_higher_risk` annotation columns for COREP OF 07.00 rows 0371-0374.
- **Tests**: 24 new COREP tests across 4 classes (IRB sub-row splits, floor indicators, RE fallback, equity transitional columns). COREP tests: 687 (was 663). Total: 5,025 (was 5,001). (P2.5)

---

## [0.1.53] - 2026-04-07

### Changed
- Version bump for PyPI release

---

## [0.1.52] - 2026-04-06

### Changed
- Version bump for PyPI release

---

## [0.1.51] - 2026-04-05

### Changed
- Version bump for PyPI release

---

## [0.1.50] - 2026-04-01

### Changed
- Version bump for PyPI release

---

## [0.1.49] - 2026-03-30

### Changed
- Version bump for PyPI release

---

## [0.1.48] - 2026-03-29

### Changed
- Version bump for PyPI release

---

## [0.1.47] - 2026-03-28

### Changed
- Version bump for PyPI release

---

## [0.1.46] - 2026-03-28

### Changed
- Version bump for PyPI release

---

## [0.1.45] - 2026-03-27

### Added

#### CCP Guarantor Risk Weight Support (CRR Art. 306 / CRE54.14-15)
CCP guarantors now receive the prescribed QCCP risk weight (2% proprietary / 4% client-cleared) instead of being treated as generic unrated institutions (40% RW). The guarantee substitution when/then chain in both the SA calculator and IRB namespace checks `guarantor_entity_type == "ccp"` before the institution/MDB branch, applying `QCCP_PROPRIETARY_RW` (2%) or `QCCP_CLIENT_CLEARED_RW` (4%) based on `guarantor_is_ccp_client_cleared`.

- CRM processor and namespace propagate `is_ccp_client_cleared` from guarantor counterparty data
- Entity type normalization (`.str.to_lowercase()`) applied to guarantor entity type joins

---

## [0.1.44] - 2026-03-25

### Added

#### ~~Article 114(4)~~ Article 114(7) EU domestic currency 0% risk weight for EU sovereigns

!!! warning "Correction (D4.35)"
    The original entry cited Art. 114(4). In the UK-onshored CRR, Art. 114(4)
    covers only the UK central government and Bank of England in sterling.
    EU member state domestic-currency treatment is provided by **Art. 114(7)**
    (third-country reciprocity).

EU member state central government and central bank exposures denominated in that member state's domestic currency now receive 0% risk weight regardless of CQS, per CRR Art. 114(7). Covers all 27 EU member states: eurozone members (EUR) and non-euro members in their national currencies (PLN, SEK, CZK, DKK, HUF, BGN, RON). EU domestic sovereign exposures are also forced to the Standardised Approach, preventing internal models from overriding the regulatory 0% treatment. Applies to both direct exposures and guarantor risk weight substitution (SA and IRB).

- `is_ccp_client_cleared` field added to data generators

### Fixed
- CCP exposures now forced to SA approach with correct risk weights (was falling through to generic corporate treatment)

---

## [0.1.43] - 2026-03-24

### Fixed

#### Guarantee application expanded to facility and counterparty levels
Guarantee application previously only matched at direct (loan/exposure/contingent) level. Guarantees linked at facility or counterparty level were silently ignored. Now supports multi-level beneficiary matching: direct, facility (pro-rata across facility's exposures), and counterparty (pro-rata across all counterparty exposures).

---

## [0.1.42] - 2026-03-22

### Fixed

#### Slotting maturity not derived from `maturity_date`
The `is_short_maturity` flag for CRR Art. 153(5) specialised lending was never calculated from exposure `maturity_date`. It defaulted to `False`, causing all exposures to receive the >= 2.5yr risk weights regardless of actual remaining maturity. Strong category exposures with <2.5yr maturity now correctly receive 50% RW (was 70%), Good receives 70% (was 90%), HVCRE Strong receives 70% (was 95%), and HVCRE Good receives 95% (was 120%).

- `prepare_columns()` now accepts `CalculationConfig` and derives `is_short_maturity` from `maturity_date` and `reporting_date`
- Extracted `exact_fractional_years_expr` to shared `engine/utils.py` (reused by IRB and slotting)
- Added `remaining_maturity_years` column to slotting audit trail
- Added CRR-E5 through CRR-E8 acceptance scenarios for short-maturity slotting

#### UK govt guarantee exposure marked "not beneficial" for non-sovereign entity types
Guarantor risk weight lookup used regex matching on `guarantor_entity_type` (e.g., `contains("SOVEREIGN")`), which only matched `sovereign` but not `central_bank`, `bank`, `company`, or `mdb`. These entity types produced `null` guarantor RW, causing beneficial guarantees to be incorrectly skipped. The lookup now uses `guarantor_exposure_class` (derived from the existing `ENTITY_TYPE_TO_SA_CLASS` mapping), ensuring all valid entity types resolve to the correct SA risk weight. Also adds Art. 114(4) domestic sovereign treatment: UK CGCB guarantors in GBP receive 0% RW regardless of CQS. *(Correction (D4.35): original entry cited Art. 114(3); Art. 114(3) is the ECB provision, Art. 114(4) is UK domestic currency.)* Both SA calculator and IRB namespace are fixed. CRM processor and namespace now propagate `guarantor_country_code` from counterparty data.

---

## [0.1.41] - 2026-03-22

### Added

#### ~~Article 114(3)~~ Article 114(4) domestic currency 0% risk weight for UK sovereign

!!! warning "Correction (D4.35)"
    The original entry cited Art. 114(3). CRR Art. 114(3) is the **ECB** 0%
    provision. The UK domestic currency provision is **Art. 114(4)**.

UK central government and central bank exposures denominated in GBP now receive 0% risk weight regardless of CQS, per CRR Art. 114(4). Previously, 0% was only assigned via CQS 1 external rating lookup. The override applies in both CRR and Basel 3.1 SA risk weight chains. Foreign-currency UK sovereign exposures continue to use the standard CQS-based risk weight table.

---

## [0.1.40] - 2026-03-22

### Changed

#### Specialised lending now input-driven via `counterparty_reference`
Specialised lending metadata (`sl_type`, `slotting_category`, `is_hvcre`) is now supplied as an input file (`exposures/specialised_lending.parquet`) keyed by `counterparty_reference`, rather than being derived from counterparty reference naming conventions. This allows a corporate counterparty to have both SL and non-SL exposures, aligning with CRR Art. 147(8) and BCBS CRE30.6.

- **New input file**: `ratings/specialised_lending.parquet`
- **Schema change**: `exposure_reference` replaced with `counterparty_reference`; `remaining_maturity_years` removed (sourced from loan/facility data)
- **Removed dead code**: `_build_slotting_category_expr()`, `_build_sl_type_expr()`, and counterparty reference naming convention logic in the classifier

### Fixed

#### FI scalar (`apply_fi_scalar`) not applied to IRB correlation
The `apply_fi_scalar` counterparty flag was gated on `is_financial_sector_entity`, which required the `entity_type` to be an institution-like value. Counterparties with `entity_type="corporate"` and `apply_fi_scalar=True` silently received no 1.25x correlation multiplier. The classifier now derives `requires_fi_scalar` directly from the user-supplied `apply_fi_scalar` flag.

**Removed dead code**: `FINANCIAL_SECTOR_ENTITY_TYPES`, `is_financial_sector_entity`, and `is_large_financial_sector_entity` — set in the classifier but never consumed by any calculation engine.

---

## [0.1.39] - 2026-03-21

### Fixed
- SME managed-as-retail 75% RW now correctly gated on EUR 1m turnover threshold check (was applying 75% RW without verifying threshold)

### Changed
- Documentation aligned with current codebase state

---

## [0.1.38] - 2026-03-20

### Fixed
- Null `slotting_category` and `sl_type` for non-slotting exposures (was leaving stale values from classification)
- Defaulted exposure treatment for SA risk weights now correctly implemented
- Case-insensitive column value validation (lowercase valid values set before comparison)
- `country_codes` and `excluded_book_codes` columns in `model_permissions` input are now truly optional — when absent, treated as null (all geographies permitted, no book code exclusions). Previously caused `ColumnNotFoundError`
- Documentation aligned with code schemas across 13 files

---

## [0.1.37] - 2026-03-17

### Fixed
- Validation error messages now correctly convert file paths to string (was raising `TypeError` for `Path` objects)

---

## [0.1.36] - 2026-03-15

### Changed

#### Model ID moved from counterparty to ratings level (Breaking)
`model_id` has been moved from `COUNTERPARTY_SCHEMA` to `RATINGS_SCHEMA`. The rating inheritance pipeline now carries `model_id` alongside `internal_pd` through parent-child inheritance, eliminating the redundant counterparty-to-exposure propagation path.

- **Removed**: `model_id` from `COUNTERPARTY_SCHEMA`
- **Added**: `model_id` to `RATINGS_SCHEMA`
- **Updated**: Rating inheritance pipeline carries `internal_model_id` through coalesce (own → parent)
- **Updated**: `_unify_exposures()` sources `model_id` from rating inheritance instead of counterparty join
- **Updated**: Fixture generators, integration tests, benchmark data generators, and documentation
- Counterparty data handling consolidated

---

## [0.1.35] - 2026-03-11

### Added

#### Integration Test Infrastructure
Comprehensive integration test suite covering the full pipeline from loader to output:

- **Phase 1**: Hierarchy → Classifier flow tests
- **Phase 2**: Classifier → CRM and CRM → Calculators flow tests
- **Phase 3**: Loader → Hierarchy, model permissions, and output floor tests
- **Phase 4**: Equity flow integration tests
- Integration test strategy document and shared infrastructure

### Changed
- `model_id` added to counterparty-level schema (subsequently moved to ratings in 0.1.36)

---

## [0.1.34] - 2026-03-10

### Added

#### Model-Level IRB Permissions
Per-model IRB approach gating replaces the org-wide `IRBPermissions` config when a `model_permissions` input file is provided:

- **New schema**: `MODEL_PERMISSIONS_SCHEMA` with `model_id`, `exposure_class`, `approach`, `country_codes`, `excluded_book_codes`
- **New column**: `model_id` on `FACILITY_SCHEMA`, `LOAN_SCHEMA`, `CONTINGENTS_SCHEMA` — links exposures to their IRB model
- **Classifier**: `_resolve_model_permissions()` joins exposures with model permissions, filters by geography and book code, gates approach on both permission and data availability (AIRB requires `internal_pd` + `lgd`; FIRB requires only `internal_pd`)
- **Backward compatible**: When no `model_permissions` file is present, org-wide `IRBPermissions` fallback applies
- **Validation**: `model_permissions` included in `validate_raw_data_bundle()` and `validate_bundle_values()` for schema and value validation
- `model_permissions` fixtures and `model_id` added to exposure generators
- API documentation updated
- 10 unit tests covering AIRB/FIRB gating, geography filters, book code exclusions, and backward compatibility

#### Rename `is_regulated` → `apply_fi_scalar`
Simplified FI scalar control on `COUNTERPARTY_SCHEMA`:

- **Schema**: `is_regulated` renamed to `apply_fi_scalar` — direct user-controlled flag replacing the intermediate boolean
- **Classifier**: `requires_fi_scalar` now derives from `is_financial_sector_entity AND cp_apply_fi_scalar` (simpler than the previous two-condition inference from `is_regulated`)
- **Documentation**: All references updated across input schemas, architecture, and classification docs

---

## [0.1.33] - 2026-03-09

### Added

#### Dual Per-Type Rating Resolution
Rating inheritance now resolves best internal and best external rating per counterparty independently. CQS is an external-only concept; internal ratings carry PD values without internal CQS.

- Per-type columns: `internal_pd`, `internal_rating_value`, `external_cqs`, `external_rating_value`
- Per-type inheritance: own internal → parent internal, own external → parent external (independent chains)
- Removed internal CQS references throughout the codebase

### Changed
- Enhanced netting facility handling in loan data

---

## [0.1.32] - 2026-03-08

### Added
- `netting_facility_reference` field added to `LOAN_SCHEMA` and loan data for explicit netting group assignment

---

## [0.1.31] - 2026-03-07

### Added
- Enhanced netting logic for facility siblings (pro-rata allocation within netting groups)
- `interest_for_ead` function in CCF module to handle negative interest values

---

## [0.1.30] - 2026-03-06

### Added

#### Basel 3.1 Engine
Full Basel 3.1 framework implementation alongside existing CRR support:

- **Revised SA risk weight tables** (CRE20.7-26) with LTV-band risk weights for residential and commercial real estate
- **Basel 3.1 supervisory haircuts** and F-IRB LGD framework dispatch
- **Output floor**: SA-equivalent RWA calculation on all IRB rows with phase-in schedule
- **Basel 3.1 acceptance tests**: B31-B (F-IRB), B31-C (A-IRB), B31-D (CRM), B31-E (slotting), B31-G (provisions), B31-H (complex scenarios) — 116 tests total
- **IRB**: A-IRB LGD floors gated on `is_airb` column (CRE30.41)
- **IRB**: QRRE transactor/revolver PD floor distinction (CRR Art. 147(5), CRE30.55)

#### Dual-Framework Comparison and Analysis
- **M3.1**: CRR vs Basel 3.1 side-by-side comparison with per-exposure RWA delta
- **M3.2**: Capital impact analysis with driver attribution
- **M3.3**: Transitional floor schedule modelling with year-by-year phase-in
- **M3.4**: Enhanced Marimo workbook for interactive impact analysis

#### EL Shortfall/Excess (CRR Art. 158-159)
Expected loss shortfall/excess computation for IRB portfolios, with portfolio-level Tier 2 credit cap per CRR Art. 62(d).

#### COREP Template Generation (FR-4.6 / M4.1)
Regulatory reporting templates for CRR firms following EBA/PRA COREP structure (Regulation (EU) 2021/451):

- **C 07.00** — SA credit risk: original exposure, SA EAD, RWA by exposure class, plus risk weight band breakdown
- **C 08.01** — IRB totals: original exposure, IRB EAD, RWA, expected loss, weighted-average PD/LGD/maturity by exposure class
- **C 08.02** — IRB PD grade breakdown: obligor-grade-level detail with standard PD bands and exposure-weighted averages
- `COREPGenerator` class with `generate()` and `export_to_excel()` methods
- `ResultExporter.export_to_corep()` for multi-sheet Excel export
- `CalculationResponse.to_corep()` convenience method

#### Programmatic Export API (FR-4.7)
Export calculation results to Parquet, CSV, and Excel formats programmatically.

#### On-Balance Sheet Netting (CRR Article 195)
Support for on-balance sheet netting of mutual claims when a legally enforceable netting agreement exists:

- **New fields**: `has_netting_agreement` and `netting_facility_reference` on `LOAN_SCHEMA` and `Loan` fixture
- **Synthetic cash collateral**: Negative-drawn netting-eligible loans generate cash collateral that reduces all positive-drawn sibling exposures pro-rata within the same netting facility
- **Netting facility resolution**: Priority chain — explicit `netting_facility_reference` → `root_facility_reference` → `parent_facility_reference`
- **SA**: EAD reduced by netting pool (cash = 0% haircut)
- **F-IRB**: LGD reduced via cash collateral path (0% LGD)
- **FX mismatch**: 8% haircut applied when currencies differ

#### Service API Documentation
Restructured user-facing documentation to promote the high-level Service API (`quick_calculate`, `RWAService`) as the primary entry point:

- **Quick Start** rewritten with 3-tier progression: `quick_calculate` one-liner, `RWAService` with more control, full example with validation/export
- **New page: `docs/api/service.md`** — complete Service API reference
- **API Reference index** features Service API as first module

#### Basel 3.1 Parameter Substitution for IRB Guarantors (CRE22.70-85)
IRB guarantee substitution parameters updated for Basel 3.1 framework.

#### CI/CD Pipeline
GitHub Actions workflow with lint, typecheck, and test jobs.

### Changed
- Replaced `Enum` with `StrEnum` and `IntEnum` throughout the codebase
- Centralised data source configuration with `DataSourceRegistry` replacing `RequiredFiles`
- Introduced `BaseRequest` class to reduce duplication in request models
- Error factory functions updated to support `Path` types alongside `str`
- Tests migrated to use `Path` for file paths

### Fixed
- Corporate bond haircut CQS grouping corrected per CRR Art. 224
- PD floors and transitional schedule corrected to PRA PS1/26
- Output floor `sa_rwa` computation fixed for acceptance tests
- Benchmark data generators now include all schema columns (`is_buy_to_let`, `interest`, `bs_type`, `pledge_percentage`, `is_qrre_transactor`)
- Benchmark tests updated for current API: `_unify_exposures` signature (added `facilities` arg), `CRMProcessor.get_crm_adjusted_bundle`
- Protocol test stubs updated to include `calculate_branch` method

---

## [0.1.29] - 2026-02-28

### Added
- F-IRB acceptance tests and expected outputs (CRR-B1 through B7)

### Changed
- Pipeline refactored to single-pass calculation for unified frame (filter-process-merge pattern)
- Classifier exposure classification logic optimized
- Hierarchy collateral allocation logic simplified
- RWA calculations simplified with filter-process-merge approach

### Performance
- Pipeline optimizations: pre-computed classifier intermediates, deferred audit string, slimmed counterparty join, eliminated unnecessary `collect_schema()` calls
- Full CRR pipeline at 100K: ~1.7s mean (SA-only ~1.7s, CRR ~1.9s)

---

## [0.1.28] - 2026-02-24

### Added
- Benchmarking module for RWA Calculator performance testing

### Performance
- Optimized aggregation data collection and processing
- Optimized hierarchy graph traversal methods
- Optimized exposure enrichment methods
- Optimized pledge resolution and validation in pipeline

---

## [0.1.27] - 2026-02-22

### Added
- Results caching with lazy loading for improved pipeline performance

### Changed
- Replaced custom validation methods with shared utility functions across hierarchy, loader, pipeline, and processor
- Replaced `enable_irb` boolean config with `irb_approach` enum for clearer IRB permission modelling
- Optimized data materialization to reduce redundant `.collect()` calls
- Multiple speed optimization PRs merged (aggregator, formatters, validation)

---

## [0.1.26] - 2026-02-21

### Performance
- Optimized aggregator processing for large result sets
- Optimized formatter output generation
- Streamlined validation data processing to reduce overhead
- UI speed improvements for interactive calculator

---

## [0.1.25] - 2026-02-20

### Added

#### IRB Defaulted Exposure Treatment (CRR Art. 153(1)(ii), 154(1)(i))
- Defaulted exposures (PD=1.0) receive K=0 under F-IRB and K=max(0, LGD-BEEL) under A-IRB
- Expected loss = LGD × EAD for defaulted exposures
- CRR 1.06 scaling factor correctly applied to defaulted corporate exposures
- New CRR-I acceptance test group with 9 tests (I1 F-IRB corporate, I2 A-IRB retail, I3 A-IRB corporate with CRR scaling)

### Fixed
- SME supporting factor now correctly uses drawn amount (not EAD) for tier threshold calculation

---

## [0.1.24] - 2026-02-19

### Added

#### Multi-Level SA Collateral Allocation
- Multi-level collateral allocation for SA EAD reduction with overcollateralisation compliance
- Haircut calculator enhancements for multi-level processing

---

## [0.1.23] - 2026-02-17

### Added

#### SA Provision Handling — Art. 111(1)(a)-(b) Compliance
Provisions are now resolved **before** CCF application using a drawn-first deduction approach, compliant with CRR Art. 111(1)(a)-(b):

**Pipeline reorder:**
```
resolve_provisions → CCF → initialize_ead → collateral → guarantees → finalize_ead
```

**New method:** `resolve_provisions()` with multi-level beneficiary resolution:
- **Direct** (loan/exposure/contingent): provision matched to specific exposure
- **Facility**: distributed pro-rata across facility's exposures
- **Counterparty**: distributed pro-rata across all counterparty exposures

**SA drawn-first deduction:**
- `provision_on_drawn = min(provision, max(0, drawn))` — absorbs provision against drawn first
- Remainder → `provision_on_nominal` — reduces nominal before CCF
- `nominal_after_provision = nominal_amount - provision_on_nominal` feeds into CCF

**IRB/Slotting:** Provisions tracked (`provision_allocated`) but NOT deducted from EAD (feeds EL shortfall/excess comparison)

**New columns:**
| Column | Type | Description |
|--------|------|-------------|
| `provision_on_drawn` | Float64 | Provision absorbed by drawn (SA only) |
| `provision_on_nominal` | Float64 | Provision reducing nominal before CCF (SA only) |
| `nominal_after_provision` | Float64 | `nominal_amount - provision_on_nominal` |
| `provision_deducted` | Float64 | Total = `provision_on_drawn + provision_on_nominal` |
| `provision_allocated` | Float64 | Total provision matched to this exposure |

**Other changes:**
- `finalize_ead()` no longer subtracts provisions (already baked into `ead_pre_crm`)
- `_initialize_ead()` preserves existing provision columns if set by `resolve_provisions`
- 14 unit tests in `tests/unit/crm/test_provisions.py`
- CCF test suite expanded to 57 tests

---

## [0.1.22] - 2026-02-16

### Changed
- Slotting risk weights updated for remaining maturity splits (CRR Art. 153(5))
- Config enhancements for slotting maturity bands

## [0.1.21] - 2026-02-16

### Added

#### Pledge Percentage for Collateral Valuation
- Introduced `pledge_percentage` field to allow collateral to be specified as a percentage of the beneficiary's EAD
- Collateral processing resolves `pledge_percentage` to absolute market values based on beneficiary type (loan, facility, or counterparty level)
- Updated input schemas and CRM methodology documentation to reflect the new field
- 403 lines of new tests covering pledge percentage resolution across different beneficiary levels

## [0.1.20] - 2026-02-14

### Added

#### Equity Exposure FX Conversion
- New `convert_equity_exposures()` method in FX converter for converting equity exposure values to reporting currency
- Updated classifier and hierarchy to support equity exposures in FX conversion pipeline
- Enhanced FX rate configuration with equity-specific handling
- Comprehensive tests for equity exposure conversion and currency handling

## [0.1.19] - 2026-02-11

### Added

#### Buy-to-Let Flag
- New `is_buy_to_let` boolean flag in hierarchy and schemas for identifying BTL exposures
- BTL exposures excluded from SME supporting factor discount
- Unit tests verifying BTL flag behaviour in supporting factor calculations

#### On-Balance EAD Helper
- New `on_balance_ead()` helper function in CCF module calculating EAD as `max(0, drawn) + interest`
- Updated CRM processor and namespace to use the new helper
- Comprehensive tests covering various on-balance EAD scenarios

### Changed
- Updated implementation plan and roadmap documentation with current test results and fixture completion status

## [0.1.18] - 2026-02-10

### Added

#### Facility Hierarchy Enhancements
- Facility root lookup and undrawn calculations for full facility hierarchy resolution
- Include contingent liabilities in facility undrawn calculations
- Enhanced facility hierarchy resolution logic

## [0.1.17] - 2026-02-10

### Added
- CCF: handle negative drawn amounts in EAD calculations

### Fixed
- Hierarchy: resolve duplicate mapping issues in facility calculations

## [0.1.16] - 2026-02-09

### Added

#### Cross-Approach CCF Substitution
- SA CCF expression and cross-approach substitution for guaranteed IRB exposures
- When an IRB exposure is guaranteed by an SA counterparty, the guaranteed portion uses SA CCFs
- New columns: `ccf_original`, `ccf_guaranteed`, `ccf_unguaranteed`, `guarantee_ratio`, `guarantor_approach`, `guarantor_rating_type`

#### Aggregator Enhancements
- Updated summaries for post-CRM reporting
- Enhanced approach handling for IRB results

## [0.1.15] - 2026-02-08

### Added
- Correlation: rename sovereign exposure class to central govt/central bank
- CI: add GitHub Actions workflow for documentation deployment

## [0.1.14] - 2026-02-07

### Added

#### Overcollateralisation Requirements (CRR Art. 230 / CRE32.9-12)
Non-financial collateral now requires overcollateralisation to receive CRM benefit:

| Collateral Type | Overcollateralisation Ratio | Minimum Threshold |
|----------------|---------------------------|-------------------|
| Financial | 1.0x | No minimum |
| Receivables | 1.25x | No minimum |
| Real estate | 1.4x | 30% of EAD |
| Other physical | 1.4x | 30% of EAD |

- `effectively_secured = adjusted_value / overcollateralisation_ratio`
- Financial vs non-financial collateral tracked separately for threshold checks
- Multi-level allocation respects overcollateralisation at each level

### Changed
- Standardized `collateral_type` casing and descriptions across codebase

## [0.1.13] - 2026-02-07

### Added

#### Input Value Validation
- `validate_bundle_values()` validates all categorical columns against `COLUMN_VALUE_CONSTRAINTS`
- Error code `DQ006` for invalid column values
- Pipeline calls `_validate_input_data()` as non-blocking step (errors collected, not raised)

### Fixed
- Prevented row duplication in exposure joins when `facility_reference = loan_reference` (#71)

## [0.1.12] - 2026-02-02

### Added

#### Equity Exposure Calculator
Complete equity exposure RWA calculation supporting two regulatory approaches:

**Article 133 - Standardised Approach (SA):**
| Equity Type | Risk Weight |
|-------------|-------------|
| Central bank | 0% |
| Listed/Exchange-traded/Government-supported | 100% |
| Unlisted/Private equity | 250% |
| Speculative | 400% |

**Article 155 - IRB Simple Risk Weight Method:**
| Equity Type | Risk Weight |
|-------------|-------------|
| Central bank | 0% |
| Private equity (diversified portfolio) | 190% |
| ~~Government-supported~~ | ~~190%~~ |
| Exchange-traded/Listed | 290% |
| Other equity | 370% |

!!! warning "Correction (D1.27)"
    "Government-supported: 190%" was incorrectly listed as an Art. 155 category. Art. 155(2) has only three categories: (a) exchange-traded 290%, (b) PE diversified 190%, (c) all other 370%. No "government-supported" category exists in Art. 155.

**New Components:**
- `EquityCalculator` class (`src/rwa_calc/engine/equity/calculator.py`)
- `EquityLazyFrame` namespace (`lf.equity`) for fluent calculations
- `EquityExpr` namespace (`expr.equity`) for column-level operations
- `EquityResultBundle` for equity calculation results
- `crr_equity_rw.py` lookup tables

**Features:**
- Automatic approach determination based on IRB permissions
- Diversified portfolio treatment for private equity (190% vs 370%)
- Full audit trail generation
- Single exposure calculation convenience method

#### Pre/Post CRM Tracking for Guarantees
Enhanced guarantee processing with full tracking of exposure amounts before and after CRM application:
- `rwa_pre_crm`: RWA calculated on original exposure before guarantee
- `rwa_post_crm`: RWA calculated after guarantee substitution
- `guarantee_rwa_benefit`: Reduction in RWA from guarantee protection
- Supports both covered and uncovered portion tracking

### Changed
- Pipeline now includes equity calculator between CRM and aggregator
- `CRMAdjustedBundle` extended with `equity_exposures` field

## [0.1.11] - 2026-01-28

### Added
- Namespace: add exact fractional years calculation
- Config: add MCP server configuration

## [0.1.10] - 2026-01-28

### Added
- CCF: include interest in EAD calculations

## [0.1.8] - 2026-01-28

### Added
- Data: add script to generate sample data in parquet format
- Correlation: add SME adjustment with EUR/GBP conversion
- Orgs: make org_mappings optional in data loaders

### Fixed
- Config: update EUR to GBP exchange rate

## [0.1.7] - 2026-01-27

### Added
- Tests: add unit tests for API error handling and validation
- Protocols: update aggregation method with new bundles
- Loader: enhance data loading with validation checks
- BDD: add specifications for CRR provisions, risk weights, and supporting factors

### Changed
- Loans: update loan schema and documentation

## [0.1.6] - 2026-01-25

### Added
- Stats: implement backend detection for statistical functions
- Documentation: add detailed implementation plan and project roadmap

### Changed
- Stats: remove dual stats backend implementation
- Documentation: update optional dependencies and installation instructions

## [0.1.5] - 2026-01-25

### Added
- Counterparties: enhance counterparty schema and classification
- Documentation: add logo to documentation theme

### Changed
- CCF: remove unused CCF module and tests
- Contingents: remove ccf_category and update risk_type

### Performance
- Benchmark: update results with improved metrics

## [0.1.4] - 2026-01-25

### Added
- Deploy: add automated deployment script

### Performance
- Benchmark: transition to pure Polars expressions

## [0.1.3] - 2025-01-24

### Added

#### Documentation Code Linking
- Updated documentation to link code examples to actual source implementations
- Added `pymdownx.snippets` for embedding real code from source files
- Added `mkdocstrings` auto-generated API documentation
- New `docs/development/documentation-conventions.md` guide for contributors
- Source code references with GitHub line number links throughout docs

#### Mandatory `risk_type` Column for CCF Determination

The `risk_type` column is now the authoritative source for CCF (Credit Conversion Factor) determination across all facility inputs:

**New Columns:**
- `risk_type` (mandatory) - Off-balance sheet risk category: FR, MR, MLR, LR
- `ccf_modelled` (optional) - A-IRB modelled CCF estimate (0.0-1.5, Retail IRB can exceed 100%)
- `is_short_term_trade_lc` (optional) - CRR Art. 166(9) exception flag

**Risk Type Values (CRR Art. 111):**

| Code | SA CCF | F-IRB CCF | Description |
|------|--------|-----------|-------------|
| FR | 100% | 100% | Full risk - guarantees, credit substitutes |
| MR | 50% | 75% | Medium risk - NIFs, RUFs, committed undrawn |
| MLR | 20% | 75% | Medium-low risk - documentary credits, trade |
| LR | 0% | 0% | Low risk - unconditionally cancellable |

**F-IRB Rules:**
- CRR Art. 166(8): MR and MLR both become 75% CCF under F-IRB
- CRR Art. 166(9): Short-term trade LCs for goods movement retain 20% (set `is_short_term_trade_lc=True`)

**A-IRB Support:**
- When `ccf_modelled` is provided and approach is A-IRB, this value takes precedence

### Removed

#### `commitment_type` Column and Legacy CCF Functions

The following have been removed as `risk_type` is now the authoritative CCF source:

**Removed from schemas:**
- `commitment_type` column from FACILITY_SCHEMA and all intermediate schemas

**Removed from `crr_ccf.py`:**
- `lookup_ccf()` function
- `lookup_firb_ccf()` function
- `calculate_ead_off_balance_sheet()` function
- `create_ccf_type_mapping_df()` function

**Removed from `ccf.py`:**
- `calculate_single_ccf()` method
- `CCFResult` dataclass

**Migration:** Replace `commitment_type` with `risk_type`:
- `unconditionally_cancellable` → `LR` (low_risk)
- `committed_other` → `MR` (medium_risk) or `MLR` (medium_low_risk)

#### FX Conversion Support (14 new tests)

Multi-currency portfolio support with configurable FX conversion:

**FXConverter Module** (`src/rwa_calc/engine/fx_converter.py`)
- `convert_exposures()` - Converts drawn, undrawn, and nominal amounts
- `convert_collateral()` - Converts market and nominal values
- `convert_guarantees()` - Converts covered amounts
- `convert_provisions()` - Converts provision amounts
- Factory function `create_fx_converter()`

**Features:**
- Configurable target currency via `CalculationConfig.base_currency`
- Enable/disable via `CalculationConfig.apply_fx_conversion`
- Full audit trail: `original_currency`, `original_amount`, `fx_rate_applied`
- Graceful handling of missing FX rates (values unchanged, rate = null)
- Early pipeline integration (HierarchyResolver) for consistent threshold calculations

**Data Support:**
- New `FX_RATES_SCHEMA` in `src/rwa_calc/data/schemas.py`
- `fx_rates` field added to `RawDataBundle`
- `fx_rates_file` config in `DataSourceConfig`
- Test fixtures in `tests/fixtures/fx_rates/`

**Tests:**
- 14 unit tests covering all conversion scenarios
- Tests for exposure, collateral, guarantee, and provision conversion
- Multi-currency batch conversion tests
- Alternative base currency tests (EUR, USD)

#### Polars Namespace Extensions (8 namespaces, 139 new tests)

The calculator now provides comprehensive Polars namespace extensions for fluent, chainable calculations across all approaches:

**SA Namespace** (`lf.sa`, `expr.sa`)
- `SALazyFrame` namespace for Standardised Approach calculations
- Methods: `prepare_columns`, `apply_risk_weights`, `apply_residential_mortgage_rw`, `apply_cqs_based_rw`, `calculate_rwa`, `apply_supporting_factors`, `apply_all`
- UK deviation handling for institution CQS 2 (30% vs 50%)
- 29 unit tests

**IRB Namespace** (`lf.irb`, `expr.irb`)
- `IRBLazyFrame` namespace for IRB calculations
- Methods: `classify_approach`, `apply_firb_lgd`, `prepare_columns`, `apply_pd_floor`, `apply_lgd_floor`, `calculate_correlation`, `calculate_k`, `calculate_maturity_adjustment`, `calculate_rwa`, `calculate_expected_loss`, `apply_all_formulas`
- Expression methods: `floor_pd`, `floor_lgd`, `clip_maturity`
- 33 unit tests

**CRM Namespace** (`lf.crm`)
- `CRMLazyFrame` namespace for EAD waterfall processing
- Methods: `initialize_ead_waterfall`, `apply_collateral`, `apply_guarantees`, `apply_provisions`, `finalize_ead`, `apply_all_crm`
- SA vs IRB treatment differences handled automatically
- 20 unit tests

**Haircuts Namespace** (`lf.haircuts`)
- `HaircutsLazyFrame` namespace for collateral haircut calculations
- Methods: `classify_maturity_band`, `apply_collateral_haircuts`, `apply_fx_haircut`, `apply_maturity_mismatch`, `calculate_adjusted_value`, `apply_all_haircuts`
- CRR Article 224 supervisory haircuts
- 24 unit tests

**Slotting Namespace** (`lf.slotting`, `expr.slotting`)
- `SlottingLazyFrame` namespace for specialised lending
- Methods: `prepare_columns`, `apply_slotting_weights`, `calculate_rwa`, `apply_all`
- CRR vs Basel 3.1 risk weight differences
- HVCRE treatment
- 26 unit tests

**Hierarchy Namespace** (`lf.hierarchy`)
- `HierarchyLazyFrame` namespace for hierarchy resolution
- Methods: `resolve_ultimate_parent`, `calculate_hierarchy_depth`, `inherit_ratings`, `coalesce_ratings`, `calculate_lending_group_totals`, `add_lending_group_reference`, `add_collateral_ltv`
- Pure LazyFrame join-based traversal (no Python recursion)
- 13 unit tests

**Aggregator Namespace** (`lf.aggregator`)
- `AggregatorLazyFrame` namespace for result combination
- Methods: `combine_approach_results`, `apply_output_floor`, `calculate_floor_impact`, `generate_summary_by_class`, `generate_summary_by_approach`, `generate_supporting_factor_impact`
- Basel 3.1 output floor support
- 12 unit tests

**Audit Namespace** (`lf.audit`, `expr.audit`)
- `AuditLazyFrame` namespace for audit trail generation
- Methods: `build_sa_calculation`, `build_irb_calculation`, `build_slotting_calculation`, `build_crm_calculation`, `build_haircut_calculation`, `build_floor_calculation`
- `AuditExpr` namespace for column formatting: `format_currency`, `format_percent`, `format_ratio`, `format_bps`
- 15 unit tests

### Changed
- **All calculators** can now use namespace-based fluent APIs
- Improved code readability with chainable method calls
- Test count increased from 635 to 826 (139 namespace tests + 14 FX converter tests + 38 other tests)

## [0.1.2] - 2025-01-24

### Added

#### Interactive UI Console Command
- New `rwa-calc-ui` console script for starting the UI server when installed from PyPI
- `main()` function added to `server.py` for entry point

#### Documentation Improvements
- New `docs/user-guide/interactive-ui.md` - comprehensive UI guide with prerequisites, all three apps, troubleshooting
- Updated quickstart with "Choose Your Approach" section (UI vs Python API)
- Added Interactive UI to user guide navigation and recommendations
- Updated all server startup commands to show both PyPI and source installation methods

### Changed
- Installation instructions clarified for PyPI vs source installations
- UI documentation moved from Development section to User Guide for better discoverability

---

## [0.1.1] - 2025-01-22

### Added
- FX conversion support for multi-currency portfolios
- Polars namespace extensions (8 namespaces)
- Retail classification flag (`cp_is_managed_as_retail`)

---

## [0.1.0] - 2025-01-18

### Added

#### Core Framework
- Dual-framework support (CRR and Basel 3.1 configuration)
- Pipeline architecture with discrete processing stages
- Protocol-based component interfaces
- Immutable data contracts (bundles)

#### Data Loading
- Parquet file loader
- Schema validation
- Optional file handling
- Metadata tracking

#### Hierarchy Resolution
- Counterparty hierarchy resolution (up to 10 levels)
- Rating inheritance from parent
- Lending group aggregation
- LazyFrame-based join optimization

#### Classification
- All exposure classes supported
- Approach determination (SA/F-IRB/A-IRB/Slotting)
- SME identification
- Retail eligibility checking
- EAD calculation with CCFs

#### Standardised Approach
- Complete risk weight tables
- Sovereign, Institution, Corporate, Retail classes
- Real estate treatments
- Defaulted exposure handling

#### IRB Approach
- K formula implementation
- Asset correlation with SME adjustment
- Maturity adjustment
- PD and LGD floors
- Expected loss calculation
- 1.06 scaling factor (CRR)

#### Slotting Approach
- All specialised lending types
- Category-based risk weights
- HVCRE treatment
- Pre-operational project finance

#### Credit Risk Mitigation
- Financial collateral (comprehensive method)
- Supervisory haircuts
- Currency mismatch handling
- Guarantees (substitution approach)
- Maturity mismatch adjustment
- Provision allocation

#### Supporting Factors (CRR)
- SME supporting factor (tiered calculation)
- Infrastructure factor

#### Output
- Aggregated results
- Breakdown by approach/class/counterparty
- Export to Parquet/CSV/JSON
- Error accumulation and reporting

#### Configuration
- Factory methods (crr/basel_3_1)
- EUR/GBP rate configuration
- Configurable supporting factors
- PD floor configuration

#### Testing
- 468+ test cases
- Unit tests for all components
- Contract tests for interfaces
- Acceptance test framework
- Test fixtures generation

#### Documentation
- MkDocs with Material theme
- User guide for all audiences
- API reference
- Architecture documentation
- Development guide

### Technical
- Python 3.13+ support
- Polars LazyFrame optimization
- Pydantic validation
- Type hints throughout
- Ruff formatting/linting

## Version History

| Version | Date | Status |
|---------|------|--------|
| 0.2.5  | 2026-05-02 | Current |
| 0.2.4  | 2026-04-30 | Previous |
| 0.2.3  | 2026-04-28 | - |
| 0.2.2  | 2026-04-27 | - |
| 0.2.1  | 2026-04-27 | - |
| 0.2.0  | 2026-04-26 | - |
| 0.1.67 | 2026-04-25 | - |
| 0.1.66 | 2026-04-24 | - |
| 0.1.65 | 2026-04-21 | - |
| 0.1.64 | 2026-04-19 | - |
| 0.1.63 | 2026-04-19 | - |
| 0.1.62 | 2026-04-17 | - |
| 0.1.61 | 2026-04-15 | - |
| 0.1.60 | 2026-04-14 | - |
| 0.1.59 | 2026-04-14 | - |
| 0.1.58 | 2026-04-11 | - |
| 0.1.57 | 2026-04-11 | - |
| 0.1.56 | 2026-04-11 | - |
| 0.1.55 | 2026-04-09 | - |
| 0.1.54 | 2026-04-08 | - |
| 0.1.53 | 2026-04-07 | - |
| 0.1.52 | 2026-04-06 | - |
| 0.1.51 | 2026-04-05 | - |
| 0.1.50 | 2026-04-01 | - |
| 0.1.49 | 2026-03-30 | - |
| 0.1.48 | 2026-03-29 | - |
| 0.1.47 | 2026-03-28 | - |
| 0.1.46 | 2026-03-28 | - |
| 0.1.45 | 2026-03-27 | - |
| 0.1.44 | 2026-03-25 | - |
| 0.1.43 | 2026-03-24 | - |
| 0.1.42 | 2026-03-22 | - |
| 0.1.41 | 2026-03-22 | - |
| 0.1.40 | 2026-03-22 | - |
| 0.1.39 | 2026-03-21 | - |
| 0.1.38 | 2026-03-20 | - |
| 0.1.37 | 2026-03-17 | - |
| 0.1.36 | 2026-03-15 | - |
| 0.1.35 | 2026-03-11 | - |
| 0.1.34 | 2026-03-10 | - |
| 0.1.33 | 2026-03-09 | - |
| 0.1.32 | 2026-03-08 | - |
| 0.1.31 | 2026-03-07 | - |
| 0.1.30 | 2026-03-06 | - |
| 0.1.29 | 2026-02-28 | - |
| 0.1.28 | 2026-02-24 | - |
| 0.1.27 | 2026-02-22 | - |
| 0.1.26 | 2026-02-21 | - |
| 0.1.25 | 2026-02-20 | - |
| 0.1.24 | 2026-02-19 | - |
| 0.1.23 | 2026-02-17 | - |
| 0.1.22 | 2026-02-16 | - |
| 0.1.21 | 2026-02-16 | - |
| 0.1.20 | 2026-02-14 | - |
| 0.1.19 | 2026-02-11 | - |
| 0.1.18 | 2026-02-10 | - |
| 0.1.17 | 2026-02-10 | - |
| 0.1.16 | 2026-02-09 | - |
| 0.1.15 | 2026-02-08 | - |
| 0.1.14 | 2026-02-07 | - |
| 0.1.13 | 2026-02-07 | - |
| 0.1.12 | 2026-02-02 | - |
| 0.1.11 | 2026-01-28 | - |
| 0.1.10 | 2026-01-28 | - |
| 0.1.8  | 2026-01-28 | - |
| 0.1.7  | 2026-01-27 | - |
| 0.1.6  | 2026-01-25 | - |
| 0.1.5  | 2026-01-25 | - |
| 0.1.4  | 2026-01-25 | - |
| 0.1.3  | 2025-01-24 | - |
| 0.1.2  | 2025-01-24 | - |
| 0.1.1  | 2025-01-22 | - |
| 0.1.0  | 2025-01-18 | Initial |

## Migration Notes

### From Previous Versions

This is the initial release. No migration required.

### CRR to Basel 3.1

When transitioning calculations from CRR to Basel 3.1:

1. **Update configuration:**
   ```python
   # Before (CRR)
   config = CalculationConfig.crr(date(2026, 12, 31))

   # After (Basel 3.1)
   config = CalculationConfig.basel_3_1(date(2027, 1, 1))
   ```

2. **Review impacted exposures:**
   - SME exposures (factor removal)
   - Infrastructure exposures (factor removal)
   - Low-risk IRB portfolios (output floor)

3. **Update data requirements:**
   - LTV data for Basel 3.1 real estate weights
   - Transactor/revolver flags for QRRE

## Deprecation Notices

### CRR-Specific Features (End of 2026)

The following CRR-specific features will be removed from active use after December 2026:

- SME supporting factor
- Infrastructure supporting factor
- 1.06 scaling factor

These will remain available for historical calculations and comparison.

## Contributing

See [Development Guide](../development/index.md) for contribution guidelines.

## Support

For issues and feature requests, please use the project's issue tracker.
