# Implementation Plan — Integration Test Strategy

## Status: Not Started

Fill gaps in stage-to-stage integration testing. Currently 1 integration test file exists (`test_pre_post_crm_reporting.py`). Target: 7 new files, ~92 tests covering every pipeline handoff.

---

## Current State

### Existing Test Coverage
| Layer | Files | Tests | Coverage |
|---|---|---|---|
| Unit | ~35 files | ~1,509 | Individual functions/methods in isolation |
| Acceptance | ~15 files | ~275 | Full pipeline with golden-file comparison |
| Contract | ~5 files | ~123 | Schema conformance and protocol adherence |
| Integration | 1 file | ~30 | Pre/post-CRM reporting views only |
| Benchmark | ~1 file | ~27 | Performance regressions |

### Gap Analysis
Acceptance tests verify end-to-end correctness but cannot isolate which handoff broke when they fail. Unit tests mock adjacent stages. The missing layer is **stage-to-stage integration tests** that wire exactly two real components together and verify the data contract between them.

### Pipeline Architecture (for reference)
```
RawDataBundle
  → Loader
    → HierarchyResolver         ← test_loader_to_hierarchy
      → Classifier              ← test_hierarchy_to_classifier
        → CRMProcessor          ← test_classifier_to_crm
          → SA/IRB/Slotting     ← test_crm_to_calculators
            → OutputAggregator  ← test_output_floor_and_aggregation
```
Plus cross-cutting: `test_model_permissions_pipeline`, `test_equity_flow`.

---

## Shared Infrastructure

### File: `tests/integration/conftest.py`

Shared data builders, config factories, and component fixtures used by all integration test files.

#### Config Factories
```python
@pytest.fixture
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))

@pytest.fixture
def crr_firb_config() -> CalculationConfig:
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        irb_permissions=IRBPermissions.firb_only(),
    )

@pytest.fixture
def crr_full_irb_config() -> CalculationConfig:
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        irb_permissions=IRBPermissions.full_irb(),
    )

@pytest.fixture
def basel31_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(reporting_date=date(2028, 1, 15))

@pytest.fixture
def basel31_full_irb_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(
        reporting_date=date(2028, 1, 15),
        irb_permissions=IRBPermissions.full_irb(),
    )
```

#### Data Builders
Builder functions that create minimal valid data for each schema. Each builder returns a `pl.LazyFrame` with all required columns populated with sensible defaults, overridable via kwargs.

```python
def make_counterparty(**overrides) -> dict:
    """Single counterparty row with defaults."""

def make_loan(**overrides) -> dict:
    """Single loan row with defaults."""

def make_facility(**overrides) -> dict:
    """Single facility row with defaults."""

def make_contingent(**overrides) -> dict:
    """Single contingent row with defaults."""

def make_model_permission(**overrides) -> dict:
    """Single model permission row with defaults."""

def make_raw_data_bundle(
    counterparties: list[dict] | None = None,
    loans: list[dict] | None = None,
    facilities: list[dict] | None = None,
    contingents: list[dict] | None = None,
    model_permissions: list[dict] | None = None,
    ...
) -> RawDataBundle:
    """Build a RawDataBundle from row dicts, applying schema defaults."""
```

#### Component Fixtures
```python
@pytest.fixture
def hierarchy_resolver() -> HierarchyResolver:
    return HierarchyResolver()

@pytest.fixture
def classifier() -> Classifier:
    return Classifier()

@pytest.fixture
def crm_processor() -> CRMProcessor:
    return CRMProcessor()

@pytest.fixture
def sa_calculator() -> SACalculator:
    return SACalculator()

@pytest.fixture
def irb_calculator() -> IRBCalculator:
    return IRBCalculator()

@pytest.fixture
def slotting_calculator() -> SlottingCalculator:
    return SlottingCalculator()

@pytest.fixture
def aggregator() -> OutputAggregator:
    return OutputAggregator()
```

---

## Priority 1: Hierarchy → Classifier

### File: `tests/integration/test_hierarchy_to_classifier.py`

**Why P1**: This is where model_id propagation was just fixed. Validates that counterparty-level attributes (model_id, ratings, entity_type) flow correctly through hierarchy resolution into classification.

**Components wired**: `HierarchyResolver` → `Classifier`

#### Test Cases (~18 tests)

**model_id propagation (5 tests)**
1. `test_model_id_propagates_from_counterparty_to_loan` — counterparty has model_id, loan gets it after unification
2. `test_model_id_propagates_from_counterparty_to_contingent` — same for contingent exposures
3. `test_model_id_propagates_from_counterparty_to_facility_undrawn` — same for facility undrawn
4. `test_null_model_id_when_counterparty_has_none` — counterparty without model_id → exposure gets null model_id
5. `test_model_id_not_on_exposure_input` — model_id on loan schema is ignored (only counterparty model_id flows)

**Rating inheritance → classification (5 tests)**
6. `test_internal_pd_from_rating_inheritance_enables_irb` — counterparty with internal_pd → classifier assigns IRB
7. `test_external_cqs_only_falls_to_sa` — counterparty with external rating but no internal PD → SA
8. `test_parent_rating_inherited_when_own_missing` — child counterparty inherits parent's rating → classifier uses inherited rating
9. `test_dual_rating_resolution_independent_chains` — internal and external ratings resolve independently through hierarchy
10. `test_unrated_counterparty_gets_unrated_sa_weight` — no rating at all → SA with unrated weight

**Entity type → exposure class (4 tests)**
11. `test_corporate_entity_type_classifies_as_corporate` — entity_type="corporate" → ExposureClass.CORPORATE
12. `test_institution_entity_type_classifies_as_institution` — entity_type="institution" → ExposureClass.INSTITUTION
13. `test_sme_flag_from_annual_revenue` — counterparty annual_revenue < EUR 50m → CORPORATE_SME
14. `test_retail_reclassification_from_managed_as_retail` — is_managed_as_retail + aggregated exposure < threshold → retail class

**Column completeness (4 tests)**
15. `test_hierarchy_output_has_all_columns_classifier_expects` — schema contract check
16. `test_default_status_propagates_to_classifier` — defaulted counterparty → classifier marks as defaulted
17. `test_apply_fi_scalar_propagates` — apply_fi_scalar flag flows through hierarchy to classifier
18. `test_multiple_exposures_same_counterparty_get_same_classification` — consistency check

---

## Priority 2: Classifier → CRM

### File: `tests/integration/test_classifier_to_crm.py`

**Why P2**: Classification determines approach, which controls CRM behaviour (different CCFs, LGD treatment for SA vs IRB).

**Components wired**: `Classifier` → `CRMProcessor`

#### Test Cases (~14 tests)

**Approach-specific CRM (5 tests)**
1. `test_sa_classified_exposure_gets_sa_ccf` — SA exposure → regulatory CCF applied
2. `test_firb_classified_exposure_gets_supervisory_lgd` — FIRB → LGD set by seniority (45%/75%)
3. `test_airb_classified_exposure_keeps_modelled_lgd` — AIRB → modelled LGD preserved
4. `test_slotting_classified_exposure_passes_through_crm` — slotting → CRM preserves fields
5. `test_mixed_approaches_in_single_portfolio` — portfolio with SA + IRB + slotting → each gets correct treatment

**Provision handling (3 tests)**
6. `test_sa_provisions_deducted_from_ead` — SA: provision_on_drawn subtracted before CCF
7. `test_irb_provisions_not_deducted` — IRB: provision_deducted=0 (feeds EL shortfall instead)
8. `test_provision_amounts_match_approach` — verify correct provision columns per approach

**CCF conversion (3 tests)**
9. `test_contingent_gets_ccf_from_risk_type` — off-balance sheet contingent → CCF by risk_type
10. `test_facility_undrawn_gets_ccf` — facility undrawn amount → CCF applied
11. `test_drawn_loan_has_no_ccf` — on-balance sheet drawn loan → no CCF conversion

**Cross-approach guarantee (3 tests)**
12. `test_irb_exposure_with_sa_guarantor_gets_sa_ccf_on_guaranteed_portion` — cross-approach CCF substitution
13. `test_guaranteed_portion_uses_guarantor_risk_weight` — guarantee substitution effect
14. `test_unguaranteed_portion_keeps_original_treatment` — remaining portion unaffected

---

## Priority 2: CRM → Calculators

### File: `tests/integration/test_crm_to_calculators.py`

**Why P2**: CRM output drives all three calculator branches. Verifies the split-once architecture works correctly.

**Components wired**: `CRMProcessor` → `SACalculator` / `IRBCalculator` / `SlottingCalculator`

#### Test Cases (~15 tests)

**SA branch (4 tests)**
1. `test_sa_exposure_gets_risk_weight_from_cqs` — CQS-based risk weight lookup
2. `test_sa_rwa_equals_ead_times_rw` — RWA = EAD × RW
3. `test_sa_supporting_factor_applied_crr` — CRR: SME factor reduces RWA
4. `test_sa_no_supporting_factor_basel31` — Basel 3.1: no supporting factor

**IRB branch (5 tests)**
5. `test_irb_firb_uses_supervisory_lgd` — FIRB: 45% LGD for senior unsecured
6. `test_irb_airb_uses_modelled_lgd` — AIRB: LGD from input data
7. `test_irb_pd_floor_applied` — PD floored at regulatory minimum
8. `test_irb_expected_loss_calculated` — EL = PD × LGD × EAD
9. `test_irb_scaling_factor_crr_only` — CRR: 1.06× scaling; Basel 3.1: 1.0×

**Slotting branch (3 tests)**
10. `test_slotting_category_determines_risk_weight` — Strong/Good/Satisfactory/Weak/Default → RW
11. `test_slotting_hvcre_gets_higher_weights` — HVCRE flag → higher risk weights
12. `test_slotting_maturity_adjustment_crr` — CRR: <2.5yr vs >=2.5yr weight difference

**Split correctness (3 tests)**
13. `test_all_exposures_assigned_to_exactly_one_branch` — no duplicates, no gaps
14. `test_collect_all_parallel_results_match_sequential` — parallel vs sequential produce identical results
15. `test_branch_results_combine_to_total_exposure_count` — SA + IRB + slotting = total

---

## Priority 3: Loader → Hierarchy

### File: `tests/integration/test_loader_to_hierarchy.py`

**Why P3**: Validates that loaded data (parquet/CSV) produces correct hierarchy resolution. Lower priority because acceptance tests cover this path end-to-end.

**Components wired**: `Loader` → `HierarchyResolver`

#### Test Cases (~8 tests)

**Schema conformance (3 tests)**
1. `test_loaded_counterparties_have_all_hierarchy_columns` — loader output matches hierarchy input contract
2. `test_loaded_facilities_have_mapping_columns` — facility_reference, counterparty_reference present
3. `test_loaded_loans_have_counterparty_reference` — loan → counterparty linkage

**Data integrity (3 tests)**
4. `test_parent_child_mappings_resolve_hierarchy` — org_mappings → correct parent_reference
5. `test_lending_group_totals_aggregated` — lending group EAD sums correctly
6. `test_fx_conversion_applied_before_hierarchy` — multi-currency → base_currency conversion

**Edge cases (2 tests)**
7. `test_empty_optional_tables_produce_valid_bundle` — no contingents/collateral/guarantees → still valid
8. `test_minimal_dataset_loads_and_resolves` — just counterparties + loans → valid hierarchy

---

## Priority 4: Model Permissions Pipeline

### File: `tests/integration/test_model_permissions_pipeline.py`

**Why P4**: Cross-cutting feature spanning hierarchy → classifier → CRM → calculators. Validates end-to-end model permission resolution without full acceptance test overhead.

**Components wired**: `HierarchyResolver` → `Classifier` → `CRMProcessor` (3 stages)

#### Test Cases (~12 tests)

**Basic model resolution (4 tests)**
1. `test_model_airb_permission_routes_to_airb` — model with airb_permitted=True → AIRB approach
2. `test_model_firb_permission_routes_to_firb` — model with firb_permitted=True, airb_permitted=False → FIRB
3. `test_no_model_permission_falls_to_sa` — counterparty without model_id → SA fallback
4. `test_model_permission_overrides_org_wide_irb` — org has FIRB, model has AIRB → exposure gets AIRB

**Filtering (4 tests)**
5. `test_model_permission_filters_by_exposure_class` — permission for corporate only → institution falls to SA
6. `test_model_permission_filters_by_geography` — UK-only permission → non-UK falls to SA
7. `test_model_permission_excludes_book_code` — excluded book_code → SA treatment
8. `test_model_airb_requires_internal_pd` — AIRB permission but no internal_pd → falls to SA

**End-to-end with CRM (4 tests)**
9. `test_model_firb_exposure_gets_supervisory_lgd` — model permission → FIRB → CRM sets supervisory LGD
10. `test_model_airb_exposure_keeps_modelled_lgd` — model permission → AIRB → CRM preserves LGD
11. `test_mixed_model_and_org_permissions_in_portfolio` — some exposures model-permissioned, others org-permissioned
12. `test_model_id_in_output_for_audit` — model_id present in CRM output for traceability

---

## Priority 4: Output Floor & Aggregation

### File: `tests/integration/test_output_floor_and_aggregation.py`

**Why P4**: Output floor is Basel 3.1 only and involves SA-equivalent RWA calculation on all rows. Existing integration test covers CRM reporting but not floor mechanics.

**Components wired**: `SACalculator` + `IRBCalculator` + `SlottingCalculator` → `OutputAggregator`

#### Test Cases (~15 tests)

**Output floor (5 tests)**
1. `test_floor_not_applied_crr` — CRR: no output floor
2. `test_floor_binding_when_irb_rwa_below_threshold` — IRB RWA < 72.5% × SA RWA → floor binds
3. `test_floor_not_binding_when_irb_rwa_above_threshold` — IRB RWA ≥ 72.5% × SA RWA → no floor
4. `test_transitional_floor_percentage_by_date` — 2027: 50%, 2028: 55%, ... 2032: 72.5%
5. `test_floor_impact_tracked_in_result` — floor_impact field shows additional RWA from floor

**Summaries (5 tests)**
6. `test_summary_by_class_sums_correctly` — EAD/RWA by exposure class sum to totals
7. `test_summary_by_approach_splits_sa_irb_slotting` — approach-level summary correct
8. `test_combined_results_include_all_approaches` — concat of SA + IRB + slotting = total count
9. `test_el_summary_computed_for_irb` — EL shortfall/excess and T2 credit cap
10. `test_supporting_factor_impact_crr_only` — CRR: SME/infra factor impact reported

**Error accumulation (5 tests)**
11. `test_errors_from_all_stages_accumulated` — errors from SA + IRB collected in final result
12. `test_warnings_do_not_prevent_success` — warnings present but success=True
13. `test_critical_errors_mark_failure` — critical error → success=False
14. `test_error_codes_preserved_through_aggregation` — DQ/CL/SA/IRB codes intact
15. `test_empty_irb_bundle_produces_valid_result` — SA-only portfolio → no IRB bundle → valid aggregation

---

## Priority 5: Equity Flow

### File: `tests/integration/test_equity_flow.py`

**Why P5**: Equity is a separate path outside the main unified frame. Lower priority because it's simpler and less interconnected.

**Components wired**: `Classifier` → `EquityCalculator` → `OutputAggregator`

#### Test Cases (~10 tests)

**Approach selection (3 tests)**
1. `test_equity_sa_approach_when_sa_only` — SA config → Article 133 weights
2. `test_equity_irb_simple_when_irb_permitted` — IRB config → Article 155 weights
3. `test_equity_approach_in_output` — approach field correctly set in result

**Risk weights (4 tests)**
4. `test_listed_equity_100_percent` — listed equity → 100% RW (Art. 133)
5. `test_venture_capital_400_percent` — VC equity → 400% RW (Art. 133)
6. `test_irb_simple_listed_190_percent` — listed equity IRB → 190% (Art. 155)
7. `test_irb_simple_private_290_percent` — private equity IRB → 290% (Art. 155)

**Aggregation (3 tests)**
8. `test_equity_results_in_aggregated_output` — equity bundle merged into final result
9. `test_equity_separate_from_unified_frame` — equity not in SA/IRB/slotting branches
10. `test_equity_summary_by_approach` — equity has own row in approach summary

---

## Implementation Sequence

### Phase 1 — Infrastructure + P1 (Week 1)
1. `tests/integration/conftest.py` — shared builders, fixtures, config factories
2. `tests/integration/test_hierarchy_to_classifier.py` — 18 tests

### Phase 2 — P2 (Week 2)
3. `tests/integration/test_classifier_to_crm.py` — 14 tests
4. `tests/integration/test_crm_to_calculators.py` — 15 tests

### Phase 3 — P3+P4 (Week 3)
5. `tests/integration/test_loader_to_hierarchy.py` — 8 tests
6. `tests/integration/test_model_permissions_pipeline.py` — 12 tests
7. `tests/integration/test_output_floor_and_aggregation.py` — 15 tests

### Phase 4 — P5 (Week 4)
8. `tests/integration/test_equity_flow.py` — 10 tests

---

## Guiding Principles

1. **No mocking adjacent stages** — Wire real components. The whole point is verifying the handoff.
2. **Minimal data** — Each test creates the smallest dataset that exercises the behaviour. Use `make_*` builders.
3. **One handoff per file** — Each file tests exactly one stage boundary (except model_permissions which is cross-cutting).
4. **Don't duplicate acceptance tests** — Integration tests verify column contracts and data flow, not regulatory correctness. Leave golden-file assertions to acceptance tests.
5. **LazyFrame boundaries** — Pass LazyFrames between stages (as the real pipeline does). Only `.collect()` in assertions.
6. **AAA pattern** — Every test has clear Arrange / Act / Assert sections.
7. **Descriptive test names** — `test_<what_happens>` format.

---

## Known Risks

- **Data builder complexity**: Building minimal valid `RawDataBundle` requires many columns with correct types. The `make_raw_data_bundle()` builder must handle schema defaults carefully.
- **Hierarchy resolver test data**: Facility mappings need `child_type`/`node_type` handling (3-case pattern). Builders must support all variants.
- **CRM processor state**: CRM has an internal collect barrier. Integration tests must account for materialisation points.
- **Test runtime**: Wiring real components is slower than unit tests. Keep datasets small (~5-10 rows per test) to stay under 1s per test.
