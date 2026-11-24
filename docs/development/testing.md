# Testing Guide

This guide covers the testing approach, test organisation, and how to write effective tests. The test suite currently contains **5,034 tests** across unit, acceptance, contract, integration, and benchmark categories.

| Category | Tests | Description |
|----------|------:|-------------|
| Unit | 4,232 | Component tests in isolation |
| Acceptance | 501 | End-to-end regulatory scenarios (CRR + Basel 3.1 + comparison + stress) |
| Contract | 145 | Protocol/interface compliance |
| Integration | 122 | Cross-component integration |
| Benchmark | 34 | Performance at various scales (7 slow tests deselected by default) |
| **Total** | **5,034** | |

## Test Organisation

```
tests/
├── unit/                    # Component unit tests (4,232 tests)
│   ├── crr/                 # CRR-specific tests
│   ├── crm/                 # Credit risk mitigation tests
│   ├── irb/                 # IRB-specific tests
│   ├── basel31/             # Basel 3.1-specific tests
│   └── api/                 # API tests
├── acceptance/              # End-to-end scenario tests (501 tests)
│   ├── crr/                 # CRR framework scenarios (169 tests)
│   ├── basel31/             # Basel 3.1 framework scenarios (212 tests)
│   └── comparison/          # Cross-framework comparison tests (60 tests)
├── contracts/               # Interface compliance tests (145 tests)
├── integration/             # Cross-component integration tests (122 tests)
├── benchmarks/              # Performance tests (34 tests)
│   ├── data_generators.py   # Dataset generation for various scales
│   └── data/                # Cached benchmark datasets (parquet)
├── bdd/                     # BDD-style tests (step definitions)
├── fixtures/                # Test data generators (parquet fixtures)
│   ├── counterparty/        # Counterparty fixtures (5 types)
│   ├── exposures/           # Facility, loan, contingent, mapping fixtures
│   ├── collateral/          # Collateral fixtures
│   ├── guarantee/           # Guarantee fixtures
│   ├── provision/           # Provision fixtures
│   ├── ratings/             # Rating fixtures
│   ├── mapping/             # Hierarchy mapping fixtures
│   ├── fx_rates/            # FX rates fixtures
│   └── generate_all.py      # Master fixture generation script
└── expected_outputs/        # Golden files for acceptance tests
    ├── crr/                 # CRR expected RWA outputs
    └── basel31/             # Basel 3.1 expected RWA outputs
```

## Running Tests

### All Tests

```bash
# Run entire test suite (benchmarks and slow tests excluded by default)
uv run pytest

# With verbose output
uv run pytest -v

# With coverage
uv run pytest --cov=src/rwa_calc --cov-report=html
```

### By Category

```bash
# Unit tests only
uv run pytest tests/unit

# Acceptance tests
uv run pytest tests/acceptance
uv run pytest tests/acceptance/crr
uv run pytest tests/acceptance/basel31
uv run pytest tests/acceptance/comparison

# Contract tests
uv run pytest tests/contracts

# Benchmarks (requires --benchmark-only or --benchmark-enable)
uv run pytest tests/benchmarks --benchmark-only

# Include slow tests (10M+ scale)
uv run pytest -m slow
```

### Specific Tests

```bash
# Run specific file
uv run pytest tests/unit/test_pipeline.py

# Run specific test
uv run pytest tests/unit/test_pipeline.py::test_crr_basic_calculation

# Run by pattern
uv run pytest -k "test_sa_"

# Stop on first failure
uv run pytest -x

# Show local variables in tracebacks
uv run pytest -l

# Run last failed tests
uv run pytest --lf
```

## Test Categories

### Unit Tests

Test individual components in isolation:

```python
# tests/unit/test_ccf.py

import polars as pl
from rwa_calc.engine.ccf import sa_ccf_expression

class TestCCF:
    """Tests for credit conversion factor calculation."""

    def test_unconditionally_cancellable_crr_returns_zero(self):
        """Unconditionally cancellable commitments have 0% CCF under CRR."""
        lf = pl.LazyFrame(
            {"item_type": ["UNDRAWN_COMMITMENT"], "is_unconditionally_cancellable": [True]}
        )
        result = lf.with_columns(
            sa_ccf_expression(is_basel_3_1=False).alias("ccf")
        ).collect()
        assert result["ccf"][0] == 0.0

    def test_unconditionally_cancellable_basel31_returns_ten_percent(self):
        """Unconditionally cancellable has 10% CCF under Basel 3.1."""
        lf = pl.LazyFrame(
            {"item_type": ["UNDRAWN_COMMITMENT"], "is_unconditionally_cancellable": [True]}
        )
        result = lf.with_columns(
            sa_ccf_expression(is_basel_3_1=True).alias("ccf")
        ).collect()
        assert result["ccf"][0] == 0.10
```

### Contract Tests

Test interface compliance:

```python
# tests/contracts/test_calculator_protocol.py

import pytest
from rwa_calc.contracts.protocols import SACalculatorProtocol
from rwa_calc.engine.sa.calculator import SACalculator

class TestSACalculatorProtocol:
    """Verify SACalculator implements protocol correctly."""

    def test_implements_protocol(self):
        """SACalculator should implement SACalculatorProtocol."""
        calculator = SACalculator()
        assert isinstance(calculator, SACalculatorProtocol)

    def test_calculate_returns_result_bundle(self, sample_exposures, config):
        """Calculate should return SAResultBundle."""
        calculator = SACalculator()
        result = calculator.calculate(sample_exposures, config)
        assert hasattr(result, "data")
        assert hasattr(result, "errors")
```

### Acceptance Tests

End-to-end tests that run fixture data through the full production pipeline and compare results against pre-calculated expected outputs (golden files). There are three suites:

**CRR scenarios** (97 tests across 9 files):

| File | Tests | Covers |
|------|------:|--------|
| `test_scenario_crr_a_sa.py` | 14 | Standardised Approach risk weights |
| `test_scenario_crr_b_firb.py` | 13 | Foundation IRB |
| `test_scenario_crr_c_airb.py` | 7 | Advanced IRB |
| `test_scenario_crr_d_crm.py` | 9 | Credit Risk Mitigation |
| `test_scenario_crr_e_slotting.py` | 9 | Specialised Lending Slotting |
| `test_scenario_crr_f_supporting_factors.py` | 15 | SME/Infrastructure factors |
| `test_scenario_crr_g_provisions.py` | 17 | Provision resolution |
| `test_scenario_crr_h_complex.py` | 4 | Complex/combined scenarios |
| `test_scenario_crr_i_defaulted.py` | 9 | Defaulted exposures |

**Basel 3.1 scenarios** (116 tests across 9 files):

| File | Tests | Covers |
|------|------:|--------|
| `test_scenario_b31_a_sa.py` | 14 | SA risk weights (PRA PS1/26) |
| `test_scenario_b31_b_firb.py` | 16 | Foundation IRB |
| `test_scenario_b31_c_airb.py` | 13 | Advanced IRB |
| `test_scenario_b31_d_crm.py` | 15 | Credit Risk Mitigation |
| `test_scenario_b31_d7_parameter_substitution.py` | 5 | IRB parameter substitution |
| `test_scenario_b31_e_slotting.py` | 13 | Specialised Lending Slotting |
| `test_scenario_b31_f_output_floor.py` | 6 | Output floor (72.5%) |
| `test_scenario_b31_g_provisions.py` | 24 | Provision resolution |
| `test_scenario_b31_h_complex.py` | 10 | Complex/combined scenarios |

**Comparison tests** (62 tests) validate that CRR and Basel 3.1 results relate to each other correctly (e.g. output floor binds when SA RWA exceeds IRB).

Each acceptance test looks up a specific exposure in the pipeline results and asserts against the expected output:

```python
# tests/acceptance/crr/test_scenario_crr_a_sa.py

class TestCRRGroupA_StandardisedApproach:

    def test_crr_a1_uk_sovereign_zero_rw(
        self,
        sa_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        CRR-A1: UK Sovereign with CQS 1 should have 0% risk weight.

        Input: £1,000,000 loan to UK Government (CQS 1)
        Expected: RWA = £0 (0% RW per CRR Art. 114)
        """
        expected = expected_outputs_dict["CRR-A1"]
        result = get_sa_result_for_exposure(sa_results_df, "LOAN_SOV_UK_001")

        assert result is not None, "Exposure LOAN_SOV_UK_001 not found in SA results"
        assert_risk_weight_match(
            result["risk_weight"], expected["risk_weight"], scenario_id="CRR-A1"
        )
        assert_rwa_within_tolerance(
            result["rwa_post_factor"], expected["rwa_after_sf"], scenario_id="CRR-A1"
        )
```

The session-scoped fixtures (`sa_results_df`, `expected_outputs_dict`, `pipeline_results`, etc.) are defined in each suite's `conftest.py`. The pipeline runs once per session and results are shared across all tests.

### Benchmark Tests

Performance tests at various scales. See [Benchmark Tests](benchmarks.md) for full details.

```bash
# Run benchmarks (uses cached datasets)
uv run pytest tests/benchmarks --benchmark-only

# Force regenerate all benchmark datasets
uv run pytest tests/benchmarks --benchmark-only --benchmark-regenerate

# Force regenerate a specific scale
uv run pytest tests/benchmarks --benchmark-only --benchmark-regenerate-scale=100k
```

Scales: 10K (quick, ~1s), 100K (standard, ~5s), 1M (large, ~60s), 10M (production, slow marker).

## Acceptance Test Datasets

Acceptance tests depend on two things: **input fixture data** (parquet files in `tests/fixtures/`) and **expected outputs** (golden files in `tests/expected_outputs/`). Understanding how to generate and maintain these is essential for working with acceptance tests.

### Data flow

```
tests/fixtures/               tests/expected_outputs/
    ├── counterparty/*.py             ├── crr/expected_rwa_crr.json
    ├── exposures/*.py                └── basel31/expected_rwa_b31.json
    ├── collateral/*.py
    ├── ...                                     │
    │                                           │
    ▼  generate_all.py                          │
    │                                           │
tests/fixtures/                                 │
    ├── counterparty/*.parquet                  │
    ├── exposures/*.parquet                     │
    ├── ...                                     │
    │                                           │
    ▼  conftest.py: load_fixtures()             │
    │                                           │
    RawDataBundle (LazyFrames)                  │
    │                                           │
    ▼  conftest.py: PipelineOrchestrator.run()  │
    │                                           │
    AggregatedResultBundle                      │
    │                                           │
    ▼  test assertions ◄────────────────────────┘
```

### Generating fixture data

Each subdirectory in `tests/fixtures/` contains Python modules with `create_*()` and `save_*()` functions that produce parquet files. The master script generates everything in the correct order:

```bash
# Generate all fixture parquet files
uv run python tests/fixtures/generate_all.py
```

This produces parquet files across 8 fixture groups:

| Group | Directory | Files | Description |
|-------|-----------|-------|-------------|
| Counterparties | `counterparty/` | sovereign, institution, corporate, retail, specialised_lending | All counterparty types with various CQS bands |
| Mappings | `mapping/` | org_mapping, lending_mapping | Organisational and lending group hierarchies |
| Ratings | `ratings/` | ratings | External and internal ratings |
| Exposures | `exposures/` | facilities, loans, contingents, facility_mapping | All exposure types with facility-to-loan mappings |
| Collateral | `collateral/` | collateral | Financial and non-financial collateral |
| Guarantees | `guarantee/` | guarantee | Guarantee and credit protection |
| Provisions | `provision/` | provision | Specific and general provisions |
| FX Rates | `fx_rates/` | fx_rates | Currency conversion rates |

The script also runs data integrity checks (referential integrity between counterparties, exposures, collateral, etc.).

**When to regenerate**: after modifying any `create_*()` function in `tests/fixtures/`, or when adding new test scenarios that require new input data.

### Expected outputs (golden files)

Expected outputs live in `tests/expected_outputs/` and define the correct RWA results for each test scenario. Three formats are supported (checked in priority order):

1. **Parquet** (fastest) — `expected_rwa_crr.parquet` / `expected_rwa_b31.parquet`
2. **CSV** (fallback) — `expected_rwa_crr.csv` / `expected_rwa_b31.csv`
3. **JSON** (source of truth) — `expected_rwa_crr.json` / `expected_rwa_b31.json`

Each record has at minimum:

- `scenario_id` — unique test identifier (e.g. `"CRR-A1"`, `"B31-B03"`)
- `scenario_group` — grouping for fixture filtering (e.g. `"CRR-A"`, `"B31-D"`)
- `risk_weight`, `rwa_after_sf`, `ead` — expected calculation outputs

The JSON file is the canonical source of truth. Parquet/CSV are derived for faster loading. When updating expected values, edit the JSON and regenerate the other formats.

### Reporting goldens

`tests/expected_outputs/reporting/` freezes the full COREP + Pillar 3 output of every reporting run registered in `RUNS` (`tests/acceptance/reporting/test_supervisory_validations.py`), one directory per run: per-template NDJSON frames plus a `manifest.json` holding each frame's schema and the bundle metadata. The comparison is structure-exact with Float64 cells within `rtol=1e-9`, never byte-exact.

- Six portfolios have their own golden module (`test_reporting_golden.py` for `rich`, and the `ccr`, `irb_classes`, `netting`, `offbs` and `sa_classes` modules).
- Every other registered run is frozen by `test_reporting_registered_goldens.py` in `<portfolio>_<regime>/`, generated from the run's own builder, config and prior-period config. Both generators get the side inputs the REST layer passes (`api/rest.py::get_template_bundles`): the prior-period frame and the run's output-floor summary. The register withholds both from Pillar 3, so these goldens freeze more than the register evaluates: CR8's flow rows and Basel 3.1 OV1 row 27 ("Output floor adjustment").
- The Python API's Pillar 3 paths do not pass the run's summary. `ResultExporter.export_to_pillar3`, `export_pillar3_facts` and `validate_submission`'s Pillar 3 bundle use only a caller-supplied one, and `CalculationResponse.to_pillar3()` supplies none. So on those paths OV1 row 27 is null, where the goldens freeze a figure.
- `test_every_registered_run_has_a_golden` fails while any run in `RUNS` has no golden, so registering a portfolio also means banking its golden.

The register's vacuity legs and the coverage ratchets are unions over runs, so a cell emptied on one portfolio while another keeps it live can leave every one of them green; only a published rule over that exact cell would object. A golden catches that, and any change in a value, but only in cells it froze with a figure. A cell the golden froze as null is still a blind spot. That is true of some legacy goldens, which were captured without a side input:

- C 08.04 rows 0010-0080 and CR8 rows 1-8 on `rich` and `irb-classes` (both regimes), listed in `_PRIOR_FRAME_OWED`.
- OV1 row 27 on all six legacy Basel 3.1 goldens, listed in `_FLOOR_SUMMARY_OWED`.

Two parity limbs hold each list two-way. Every other run in scope must freeze a figure in those cells. An owed golden that starts freezing one must come off its list.

Regenerate one run at a time with `REGEN_REGISTERED_GOLDENS=<regime>/<portfolio>` (comma-separated), or `REGEN_REGISTERED_GOLDENS=missing` for runs with no golden yet. There is no "all". Every moved cell needs a recorded preserve-or-fix decision; never regenerate to turn a red gate green.

### How conftest.py wires it together

Each acceptance suite's `conftest.py` (e.g. `tests/acceptance/crr/conftest.py`) provides session-scoped fixtures:

1. **`load_test_fixtures`** — calls `load_fixtures()` from `workbooks/shared/fixture_loader.py`, which reads all parquet files into a `FixtureData` container of LazyFrames
2. **`raw_data_bundle`** — assembles the `FixtureData` into a `RawDataBundle` (the pipeline's input type)
3. **`pipeline_results`** — runs `PipelineOrchestrator().run_with_data(bundle, config)` once per session
4. **`sa_results_df` / `irb_results_df` / `slotting_results_df`** — collected DataFrames for each approach
5. **`expected_outputs_df` / `expected_outputs_dict`** — loaded golden file data for assertions

Different configs are used for different scenario groups (SA-only, full IRB, slotting permissions, etc.).

### Adding a new acceptance test scenario

1. Add input data in the appropriate `tests/fixtures/` module (e.g. a new counterparty in `corporate.py`, a new loan in `loans.py`)
2. Regenerate fixtures: `uv run python tests/fixtures/generate_all.py`
3. Add expected outputs to the relevant JSON golden file in `tests/expected_outputs/`
4. Write the test in the appropriate `test_scenario_*.py` file, using conftest fixtures
5. Run and verify: `uv run pytest tests/acceptance/crr/test_scenario_crr_a_sa.py -v`

## Test Fixtures

### Unit test fixtures

Unit tests use inline Polars DataFrames or `@pytest.fixture` functions:

```python
@pytest.fixture
def sample_counterparty():
    """Single corporate counterparty."""
    return pl.DataFrame({
        "counterparty_id": ["C001"],
        "counterparty_name": ["Acme Corp"],
        "counterparty_type": ["CORPORATE"],
        "country_code": ["GB"],
        "annual_turnover": [30_000_000.0],
    }).lazy()
```

### Parametrized fixtures

```python
@pytest.fixture(params=[
    ("CQS_1", 0.20),
    ("CQS_2", 0.50),
    ("CQS_3", 0.75),
    ("CQS_4", 1.00),
    ("UNRATED", 1.00),
])
def corporate_risk_weight_case(request):
    """Parametrized corporate risk weight test cases."""
    cqs, expected_rw = request.param
    return {"cqs": cqs, "expected_risk_weight": expected_rw}
```

### Configuration fixtures

```python
import pytest
from datetime import date
from rwa_calc.contracts.config import CalculationConfig

@pytest.fixture
def crr_config():
    """Standard CRR configuration."""
    return CalculationConfig.crr(reporting_date=date(2026, 12, 31))

@pytest.fixture
def basel31_config():
    """Standard Basel 3.1 configuration."""
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 1, 1))

@pytest.fixture(params=["crr", "basel31"])
def both_frameworks(request, crr_config, basel31_config):
    """Run test under both frameworks."""
    if request.param == "crr":
        return crr_config
    return basel31_config
```

### Hand-built frames: `exposure_class` takes only `ExposureClass` values

`exposure_class` is engine-derived: no exposure input file carries it, and the
classifier writes `ExposureClass.<X>.value` on every row — lowercase, never
null. A hand-built calculator frame writes it itself, so it can hand the engine
a class the classifier never writes (`"CORPORATE"`, an invented `"RETAIL"`, a
typed null, or no column at all), take the wrong branch of an exact-match gate,
and still pass. The harness therefore refuses each shape where it enters:

| Shape | Where it is stopped |
|---|---|
| Any of the three in a single-exposure builder's frame | `tests/fixtures/single_exposure.py` — `calculate_single_sa_exposure`, `calculate_single_irb_exposure` and `calculate_single_slotting_exposure` run `contract_columns.require_exposure_class_values` on the frame they hand to `calculate_branch`, and raise `ValueError` if any row's class is absent, null or not an enum value. `calculate_single_equity_exposure` writes no class, because production's equity calculator input (the raw `equity_exposures` table) carries none — the aggregator stamps `equity` / `ciu` afterwards when the calculator wrote no class (the CRR PD/LGD branch writes `"CORPORATE"`, a known defect — below) |
| A typed null, or no column | `pad_crm_exit_defaults`, `pad_sa_branch`, `pad_irb_branch` and `pad_slotting_branch` (`tests/fixtures/contract_columns.py`), and the stage-output seals behind `make_classified_bundle`, `make_crm_bundle` and `make_aggregated_bundle` (`tests/fixtures/resolved_bundle.py`, including its summary-frame seal) all raise `ValueError` on a non-empty frame with no `exposure_class`, or a null on any row, via `contract_columns.require_class_on_every_row` (`pad_slotting_branch_defaults` names `specialised_lending` first, so slotting frames pass). They do not check that a supplied string is an enum value |
| A non-member string literal in a builder keyword, a parameter default or a frame dict | `tests/contracts/test_harness_exposure_class_domain.py` — see below |

The contract module also reads the frame each builder actually hands its
calculator, through a recording stand-in calculator, so a builder that drops
or nulls the column fails there even if its own guard is deleted with it (the
builder's callers do not notice: deleting `exposure_class` and the guard from
the slotting builder leaves all 46 tests in `test_slotting_supporting_factors.py`
and `crr/test_crr_slotting.py` green). An AST anchor fails on any function
under `tests/fixtures/` that calls `calculate_branch` without a probe.

A frame a test builds itself and passes **straight** to `calculate_branch` goes
through none of these choke points: 180 such calls in 41 test files (measured
2026-11-24 on `ab0c8c8f`) are checked only where the frame went through a pad or a seal
first. That is a known gap, not a pass, filed as a residual of P5.69: some of
those frames hand a calculator a class the classifier never writes today
(`tests/unit/sa/test_payroll_transactor_precedence.py`, for one, feeds
`"RETAIL_QRRE"` / `"RETAIL_OTHER"` through a module constant no check reads).

Neither a null nor an absent class is safe to leave to the engine. A typed null
takes the null branch of every exact-match gate. An absent column is worse than
it looks: at least six engine readers guard on the column's presence and fall
back *silently* when it is missing (measured 2026-11-24) —
`engine/supporting_factors.py` (the Art. 501a(1)(a) class limb becomes
`pl.lit(True)`, so an unclassed CRR infrastructure row collects the 0.75 factor
that a null or an `institution` class is denied), `engine/crm/processor.py` (the
guarantor ranking drops its SA risk-weight density),
`engine/aggregator/_securitisation.py` (the pool breakdown drops the parent
class), `engine/aggregator/_equity_prep.py` (stamps a class of its own), and
`engine/aggregator/_floor.py` / `engine/aggregator/_supporting_factors.py`
(`col_or_default`, a typed null). So the pads refuse both. A test that deliberately pins the
engine's defensive null fallback pads (or seals) a classed row and nulls the
class afterwards, so the intent is in code.

**No lenient seal may skip the guard.** `seal_lenient` (and
`EdgeContract.conform_lenient`) turns every missing required column into a
typed null, so any helper that lenient-seals a classed edge reintroduces the
null class unless it runs `require_class_on_every_row` first. Two anchors in
the contract module read every such call under `tests/`, function by
function:

- in `tests/fixtures/resolved_bundle.py` and `tests/fixtures/contract_columns.py`
  (the stage-output helpers), every lenient seal must call the guard on the
  same frame earlier in the same function, or be named in `UNGUARDED_SEALS`
  with a reason (today `seal_hierarchy_exit` and `make_counterparty_lookup`,
  whose edges carry no class). An exempt seal's edge is resolved statically:
  one that cannot be resolved, or that declares `exposure_class`, fails;
- everywhere else under `tests/`, an unguarded lenient seal must resolve to
  edges with no engine-derived `exposure_class` — the SFT tables, or the raw
  input tables, whose `exposure_class` (CIU holdings, model permissions) is
  user input the production loader seals the same way. An edge that cannot
  be resolved fails unless `UNRESOLVED_SEALS` names it (the synthetic edges
  `tests/contracts/test_edge_contracts.py` builds to test the primitive).

So a new `make_*` helper that seals `crm_exit` inline, or a fixture elsewhere
that does, fails the contract module before it can hand a calculator a null
class. The anchors read syntax, not control flow: a guard call earlier in the
function counts even inside a branch that never runs (`if False: ...`), and a
seal reached through another callable — `functools.partial(seal_lenient,
edge=CRM_EXIT_EDGE)(lf)`, or `seal_lenient` passed as a value — is not seen at
all. Neither shape exists under `tests/` today; the anchors are a tripwire for
the ordinary shape, not a proof. They read `exposure_class` only; the aggregator-exit seal still
null-completes the sibling class carriers (`reporting_class`,
`reporting_class_origin`, `exposure_class_applied`) that a hand results frame
omits — a known gap, filed as a residual of P5.69.

**What the contract scan reads, and what it does not.** It parses every module
under `tests/` and reads three places a class literal can enter a harness
frame:

- a keyword argument named for any class-family column (`exposure_class=`,
  `post_crm_exposure_class_guaranteed=`, `reporting_class_origin=`, …) — must
  be in the column's harness domain, zero tolerance outside a two-entry
  allowlist for `CIU_HOLDINGS_SCHEMA` rows. That is an enum value, or one of
  the column's `PRODUCTION_EXTRA_VALUES` — the strings production writes there
  **by design**: today only `guarantor_exposure_class = ""`, which the CRM
  stage writes on every row with no eligible guarantor. The family
  (`CLASS_COLUMNS`) is every
  edge-contract column that holds an `ExposureClass` value; a test reads every
  `EdgeContract` in `rwa_calc.contracts.edges` and fails on a column named for
  a class that is neither in it nor in `CLASS_COLUMN_EXCLUSIONS` (which says
  why each excluded column — `exposure_subclass`, `reporting_subclass`,
  `addon_by_asset_class`, `reclassified_to_retail` — is not a class);
- a parameter default on a class-family parameter — the same per-column domain;
- a dict entry keyed on a class-family column whose value spells out string
  constants (a string, a list or tuple, `[...] * n`, or `pl.Series([...])`) —
  the literals outside the column's domain are a per-file, two-way
  `FRAME_LITERAL_BASELINE` (441 across 65 files when it was banked: a
  shrink-only ratchet, not a refusal).

**The domain is not everything production writes.** Under CRR with IRB
permission and `equity_pd_lgd=True`, the Art. 155(3) PD/LGD equity branch
(`engine/equity/calculator.py`) borrows the corporate formula by setting the
class to `"CORPORATE"` and restores `equity` only for significant investments,
and `engine/aggregator/_equity_prep.py` restamps the class only when the column
is absent. So every non-significant PD/LGD leg leaves the aggregator with
`"CORPORATE"` on six class columns — `exposure_class`, `exposure_class_applied`,
`exposure_class_post_crm`, `reporting_class`, `reporting_class_origin` and
`reporting_class_pre_default` (measured 2026-11-24 on `ab0c8c8f`: all three of
the `rich` book's equity-file legs, the listed holding and both CIU legs). That
is a known production defect, owned by P1.480 (filed from P5.69): CRR
Art. 147(2)(e) and (6) put an equity exposure in the equity class whatever the
approach, and Art. 155(3) borrows only the Art. 153(1) formula. It is declared
in `KNOWN_PRODUCTION_CLASS_DEFECTS` and kept **out** of every column's domain,
so the builders, the keyword scan and the frame ratchet refuse `"CORPORATE"` on
purpose: no test may lean on the defect. The entry carries:

- an `owner` in the parked-register grammar — an `OWNER: P<n>.<n>` token
  (`scripts/tolerated_findings.py`) naming a bullet `IMPLEMENTATION_PLAN.md`
  holds open, checked by `test_every_known_production_defect_names_an_open_owner`
  against `scripts/check_parked_registers.py::read_open_bullets`, so closing the
  bullet without removing the entry fails, as it does for every other parked
  register;
- the writer, and the class a **fixed** writer must leave (`fixed_classes`,
  split on `equity_type`): `equity` on the listed holding, and `equity` or `ciu`
  on the CIU legs, whose class on the IRB path is not decided here (Art. 147(2)
  lists no CIU class). `corporate` is admitted on none, in any case — the
  obvious wrong fix, dropping the writer's `.upper()`, makes `"CORPORATE"`
  vanish and leaves an enum value no other check objects to.

Both declarations are measured, not assumed, by one anchor
(`test_production_extra_values_are_what_a_real_run_writes`). It runs the `rich`
reporting portfolio through `PipelineOrchestrator` under exactly three configs
(`ANCHOR_LEGS`): the CRR and Basel 3.1 factory defaults, and CRR IRB with
`equity_pd_lgd=True`. Each leg fails if a by-design extra stops appearing, or if
a class column carries a non-enum string declared in neither place; the PD/LGD
leg also fails if it reaches no `pd_lgd` equity row (so a lost population is not
mistaken for a fix); if any of those rows holds, on a declared column, neither
`"CORPORATE"` nor a class `fixed_classes` admits for it — a **wrong fix**, never
read as a fix; if `"CORPORATE"` appears outside those rows; and **stale** only
once a declared column holds an admitted class on every one of them, until the
column (and, once none remain, the entry) is removed. Once the entry is gone the
anchor no longer reads that population, so the fix that closes P1.480 must pin
the class at the aggregator exit in a test of its own. A writer reached only by
some other config is invisible to the anchor. The wider measurement — every config the 39 `RUNS` entries of
`tests/acceptance/reporting/test_supervisory_validations.py` execute, 59 with
the prior-period ones, both regimes (2026-11-24) — found `""` on
`guarantor_exposure_class` in all 59 and no other non-enum string; but no
`RUNS` config enables `equity_pd_lgd`, so it cannot see the defect, and it is a
recorded measurement, not a test.

The scan does **not** read a class that reaches a frame through a variable: a
`@pytest.mark.parametrize` value list (`test_b31_sa_risk_weights.py` feeds
`"RETAIL_SME"`, not an enum member at all, this way; `test_lgd_floor_blended.py`
feeds `"CORPORATE"`), a helper argument, or a comprehension — 135 class-column
dict entries in 102 files and 32 class-column keywords in 16 files take their
value from an expression that references a name other than `pl` /
`ExposureClass` and spells out neither a string literal nor an `ExposureClass`
member, measured 2026-11-24 on `ab0c8c8f`. Nor does it
read comparisons, which is deliberate: an upper-case comparison is how a test
legitimately queries the SA risk-weight join table. Nor does it read a literal
wrapped in an expression the frame-value reader does not unpack:
`pl.lit("X").alias(<class col>)`, `with_columns(<class col>=pl.lit("X"))`,
`pl.repeat("X", n)`, `dict(<class col>=[...])` (a keyword whose value is a
list) and a conditional element (`["X" if c else "Y"]`) each score 0 (probed
2026-11-24; the eight `pl.lit` class sites under `tests/` hold an enum member
today, apart from one null set deliberately after a pad in
`tests/unit/irb/test_irb_formulas.py`, but nothing holds them there). The builder refusals cover variable-fed
strings that go through the builders; the pad and seal refusals cover only a
missing or null class, so a variable-fed or expression-wrapped non-member
string anywhere else is a known gap.

Two kinds of dict are outside the frame scan. A row of `CIU_HOLDINGS_SCHEMA`
(user input the look-through upper-cases) or `MODEL_PERMISSIONS_SCHEMA` is
exempt only when **every** key is a column of that schema — `model_id` is also a
column of every calculator-branch edge, so a marker key alone would exempt an
IRB results frame. And a dict that maps column names rather than holding rows —
a `.rename({...})` argument, or an assignment named in `NON_FRAME_DICTS` — is not
a frame.

Write `ExposureClass.CORPORATE.value` (or `"corporate"`), never `"CORPORATE"`.
The SA risk-weight join tables are keyed on the upper-cased spelling of real
enum members and are queried by comparison, which the scan does not read. A
test that means to exercise the engine's case tolerance builds its own frame
with `member.value.upper()`, so the intent is in code rather than in a literal.

When you convert a file's frame literals, lower its entry in
`FRAME_LITERAL_BASELINE` in the same change — the ratchet fails in both
directions, so freed slack cannot absorb a later addition.

## Writing Effective Tests

### Test Naming

Use descriptive names that explain what is being tested, under what conditions, and the expected outcome:

```python
# Good
def test_sme_factor_tiered_calculation_exposure_above_threshold_returns_blended_factor():
    ...

# Bad
def test_sme():
    ...
```

### Test Structure (AAA Pattern)

```python
def test_irb_capital_requirement_calculation():
    """Test IRB K formula calculation."""
    # Arrange
    pd = 0.01
    lgd = 0.45
    correlation = 0.20

    # Act
    k = calculate_k(pd, lgd, correlation)

    # Assert
    assert k == pytest.approx(0.0445, rel=0.01)
```

### Assertions

```python
# Exact equality
assert result == expected

# Approximate equality
assert result == pytest.approx(expected, rel=0.01)  # 1% tolerance
assert result == pytest.approx(expected, abs=0.001)  # Absolute tolerance

# Collections
assert set(result) == set(expected)
assert result in expected_values

# DataFrame assertions
assert len(df) == expected_count
assert df["column"].sum() == expected_sum
```

### Testing Errors

```python
def test_invalid_pd_raises_error():
    """Negative PD should raise ValueError."""
    with pytest.raises(ValueError, match="PD must be positive"):
        calculate_k(pd=-0.01, lgd=0.45, correlation=0.20)

def test_calculation_accumulates_errors():
    """Invalid exposures should accumulate errors."""
    result = pipeline.run_with_data(invalid_data, config)
    assert result.has_errors
    assert any("Invalid PD" in e.message for e in result.errors)
```

### Testing UI routes that start background jobs

`POST /calculate` and `POST /reconciliation` do not run the pipeline in the request. Each
hands a job to the UI's module-level `ThreadPoolExecutor` (`rwa_calc.ui.app.progress`) and
answers with a 303 straight away. A test that posts one of these forms must wait for the job
before it returns: post with `follow_redirects=False`, take the job id from the `Location`
header, and poll `/jobs/{id}` until its `status` is no longer `"running"`. The `_wait_for_job`
helpers in `tests/integration/test_ui_app.py` and `tests/unit/ui/test_ui_scope.py` do this.

A job nobody waits for is a full pipeline run that carries on into the tests after it, on the
same xdist worker. Three things go wrong:

- Polars spies patched on the class (such as the collect budget in
  `tests/contracts/test_pipeline_collect_budget.py`) count its work. Before P5.74 this made the
  budget read 2-3.5x its banked counts, but only when the two files ran in one process, close
  together, which under xdist depends on which worker each file lands on.
- It takes CPU from timing tests.
- It writes the real `~/.rwa_calc` once the test's `RWA_STATE_DIR` monkeypatch has been undone.

The autouse guard `_no_leaked_ui_job` in `tests/conftest.py` fails any test that returns while
a job it started is still running, and names the job ids. Sometimes a test needs only the
synchronous part of a route and stubs `submit_job`. The stub must then close the job it is
given, for example with `job.finish(success=True)`. The route registers the job with
`create_job()` before it calls `submit_job`, and the registry is never pruned, so a job left
open stays `"running"` for the rest of the process.

### Testing the batch driver over real worker processes

`tests/unit/api/test_batch.py` is the one file that starts real worker processes (the batch
driver's `ProcessPoolExecutor`). The driver contains a worker that **dies**: the pool breaks,
the lost scopes are re-run one at a time, and the scope that killed its worker is reported as
`BATCH005`. It does not contain a worker that **deadlocks**. That worker stays alive and
silent, so an unbounded test waits for it for ever. Under xdist `--dist=loadfile` the run then
stalls at ~99%, which looks like a slow machine, not a red test. The 2026-11-13 escape-log
entry (a forked worker hanging on its first Polars query) presented exactly so.

So every test in that file runs under the autouse fixture `bounded_pool_wait`. If a test still
has worker processes alive after `POOL_WAIT_BOUND_SECONDS` (180 s), a watchdog thread
terminates them. It then sweeps again every 0.5 s until the test returns, because ending a
broken pool starts one recovery pool per lost scope, and those deadlock too. The fixture's
teardown then fails the test with a message naming it, the bound and the pids it ended. A test
the watchdog had to rescue can never pass. `TestDeadlockedWorkerBound` proves the bound against
a probe worker that never returns (`_batch_probe.blocking_run`).

The bound has to **end the worker**, not just raise in the test process.
`ProcessPoolExecutor`'s `with` exit is `shutdown(wait=True)`, which waits on that same worker.
So these do not work:

- pytest-timeout's default `signal` method;
- a bare `as_completed(timeout=)` or `.result(timeout=)`.

Each raises, then hangs again on the way out (measured on CPython 3.13). Abandoning the
executor does not work either, because `concurrent.futures` joins every live pool thread at
interpreter exit. The watchdog finds the workers with the process-global
`multiprocessing.active_children()`. That is safe only because the file runs serially on one
xdist worker. Product code would need the pool's own processes.

To check the bound by hand, set `rwa_calc.api.batch.WORKER_START_METHOD = "fork"` on Linux from
a throwaway pytest plugin, and run `TestSerialParallelEquivalence`. The test fails with the
watchdog's message about 180 s in, rather than hanging.

## The robustness suite (`tests/robustness/`)

Every other suite in this estate is organised on one axis — **by regulatory
rule**: *does Art. 123 work?* Every generator in them starts from a valid
portfolio. `tests/robustness/` is the second axis — **by input pathology**:
*what happens when the customer's data is wrong?*

### Running it

One command, and it is the same one the nightly runs:

```bash
# The whole suite, dev budget (~10 Hypothesis examples per property, ~3 minutes)
uv run pytest tests/robustness/ -m 'robustness and not slow' -o addopts= -n 6

# The real sweep — 250 examples per property, which is what the nightly runs
RWA_ROBUSTNESS_PROFILE=thorough \
  uv run pytest tests/robustness/ -m 'robustness and not slow' -o addopts= -n auto

# Under Basel 3.1 instead of CRR (the nightly runs both as separate matrix legs)
RWA_ROBUSTNESS_REGIME=B31 \
  uv run pytest tests/robustness/ -m 'robustness and not slow' -o addopts= -n 6

# The 1M-row case, on its own — ~333k obligors x 3 loans, minutes and gigabytes
uv run pytest tests/robustness/ -m 'robustness and slow' -o addopts=
```

Two things about that command line are load-bearing:

- `-o addopts=` is required. The dev-loop default in `pyproject.toml` carries
  `-m '... and not robustness'`, so without clearing it pytest deselects the whole
  suite and reports a cheerful zero.
- `and not slow` must then be written back explicitly, because clearing `addopts`
  also cleared its `not slow`. A bare `-m robustness` pulls in the 1M-row case.

### Why it is not in the dev loop

It is a **search**, not a regression check. Its output is a list of input shapes
that broke, which is something to read and triage — not a merge gate. Both
`pyproject.toml`'s `addopts` and the `test` job in `.github/workflows/ci.yml`
exclude the `robustness` marker; the marker filter in both is an *exclusion*
list, so deleting either line silently puts a tens-of-minutes search back into
every developer's `pytest tests/`.

`.github/workflows/nightly-robustness.yml` owns it: 03:41 UTC daily, CRR and
Basel 3.1 as separate matrix legs, plus a `workflow_dispatch` with a profile
choice. Note that GitHub fires `schedule` **only on the default branch**, so the
workflow does nothing until it reaches `master` — use the manual dispatch or the
local command until then.

### The invariant it asserts

There is no hand-derived expected value anywhere in the suite, which is what
lets it scale to as many generated shapes as you care to pay for. Instead every
test asserts that **every input exposure row is accounted for**, which holds
when at least one of these does:

| | Outcome | Meaning |
|---|---|---|
| (a) | Sound result | An output row joins back to it via `source_exposure_reference`, carrying a non-null, finite, in-bounds `ead_final` / `risk_weight` / `rwa_final`. |
| (b) | Named error | A `CalculationError` names the row — by its input reference, by an output reference derived from it, or by its counterparty. |
| (c) | Aggregate error | An error with `exposure_reference=None` whose (table, column) matches an injected field. The input gate samples at most five row-named errors per column and summarises the rest, and `DQ001` / `DQ010` name no row at all — without this clause the suite reports false failures on correct behaviour. |
| (d) | **Nothing** | The failure. The row produced no output and no error mentions it: filtered out, lost in a join, or collapsed by a `group_by`, with its capital missing from the portfolio total and no signal. |

A fifth outcome, `collapsed`, is reported separately: duplicate input rows
sharing one reference are invisible to a per-reference identity, so the harness
counts input **rows** as well as references.

The join is on `source_exposure_reference`, never `exposure_reference` — the
real-estate splitter, guarantee substitution and facility-undrawn legs all make
the latter non-unique per input row, and joining on it would report every
correct split as a vanished row.

### The generators

| # | Generator | Module |
|---|---|---|
| 1 | Unit-scale errors (×100 and ÷100 on every ratio column) | `test_unit_scale.py` |
| 2 | Out-of-domain numerics, driven off the `ColumnSpec.domain` declarations | `test_out_of_domain.py` |
| 3 | Null each optional field in turn | `test_null_and_enum.py` |
| 4 | Unknown enum strings, including case and whitespace variants | `test_null_and_enum.py` |
| 5 | Sign flips, duplicate keys, orphan foreign keys | `test_referential_integrity.py` |
| 6 | Structural extremes — empty tables, one row, absent tables, 1M rows | `test_structural_extremes.py` |
| — | The seal's silent cast failure | `test_cast_failures.py` |

Generator 2 reads `NumericDomain` off the column declarations rather than
restating any bound, so a newly-declared column is fuzzed by being declared. The
declaration readers **raise** when a canary column loses its domain: a generator
that quietly fuzzes fewer columns than it did yesterday reports "no defects
found" for the wrong reason.

### A red run is the deliverable

The suite found three silent-wrong-number defects while it was being written.
All three are now closed, and every one of them closed by turning its
already-written test green rather than by editing the test:

| Finding | State |
|---|---|
| `DQ005 ERROR_ORPHAN_REFERENCE` is declared and emitted nowhere — an orphan or null `counterparty_reference` classifies to `other` at 100%, a **33.3% understatement** on a CQS 6 corporate, silently | **closed** by `validation.py::validate_referential_integrity`, reading the `TABLE_FOREIGN_KEYS` declarations. Orphan → `DQ005`; a null reference → `DQ001`, deliberately a different code because the two are repaired in different files |
| Duplicate input rows collapse on the model-permission dedupe with no error — a file delivered twice loses every duplicate | **closed** by `validation.py::validate_duplicate_keys` reading `TABLE_UNIQUE_KEYS`, one uncapped `DQ004` per duplicated key. The engine still collapses them; what changed is that the run now names every reference it collapsed |
| `conform_lenient` cast with `strict=False`, so an unreadable numeric became null and a £1m exposure reported £0.00 of capital, silently | **closed** by `DQ014 ERROR_UNREADABLE_INPUT_DTYPE`; the eight tests in `test_cast_failures.py` were written red and went green under the fix with no edit |

A green run means the findings were fixed — not that the search found nothing.
Do not narrow the suite to make it pass, and do not `xfail` a finding without a
plan bullet that owns it (`.claude/LESSONS.md` B7). All three are recorded in
[the escape log](escape-log.md) under 2026-08-12.

## Test Markers

Markers are configured in `pyproject.toml`. The `-m` filter in `addopts` is an
**exclusion list**, so a newly registered marker runs in the dev loop unless it
is named there:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "--tb=short --strict-markers --benchmark-disable -m 'not slow and not stress and not scale_1m and not benchmark and not robustness' -n 8 --dist=loadfile"
markers = [
    "benchmark: mark test as a benchmark (excluded from the default dev loop; run via -m benchmark)",
    "robustness: input-pathology fuzzing over the full pipeline (nightly, not the dev loop)",
    "slow: mark test as slow (1M scale, may take several minutes)",
    "stress: mark test as a correctness-at-scale validation (10K+ rows, opt-in)",
    "scale_10k: benchmark at 10K counterparty scale",
    "scale_100k: benchmark at 100K counterparty scale",
    "scale_1m: benchmark at 1M counterparty scale (opt-in via -m scale_1m)",
]
```

`--strict-markers` is on, so an unregistered marker is a hard collection error
rather than a silently ignored one.

Usage:
```python
@pytest.mark.slow
def test_large_portfolio_calculation():
    ...
```

Run by marker:
```bash
uv run pytest -m "not slow"    # Default — excludes slow tests
uv run pytest -m slow           # Only slow tests
```

## Coverage

### Generate Coverage Report

```bash
# Terminal report
uv run pytest --cov=src/rwa_calc

# HTML report
uv run pytest --cov=src/rwa_calc --cov-report=html
open htmlcov/index.html
```

### Coverage Configuration

```toml
# pyproject.toml
[tool.coverage.run]
source = ["src/rwa_calc"]
branch = true

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "if TYPE_CHECKING:",
    "raise NotImplementedError",
]
```

## Next Steps

- [Specifications](../specifications/index.md) - Regulatory specifications and scenarios
- [Adding Features](extending.md) - Extending the calculator
- [Code Style](code-style.md) - Coding conventions
- [Architecture](../architecture/index.md) - System design
