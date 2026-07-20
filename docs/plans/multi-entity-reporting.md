# Multi-Entity Reporting — Group / Sub-Consolidated / Solo Submissions

Design brief for enabling multiple regulatory submissions (group consolidated, sub-consolidated,
solo/individual) from one institution. This file is the single source of truth for the
implementation wave; all implementation and review agents work from it.

## Regulatory context

- CRR Part One Title II: requirements apply at individual (Art. 6), sub-consolidated, and
  consolidated (Art. 11-18) levels. Same COREP/Pillar 3 template estate per level; different
  reporting entity (LEI), scope of consolidation, and population.
- Consolidation *eliminates* intragroup exposures; solo books *include* them (0% RW only with an
  Art. 113(6) core-UK-group permission — **deferred to a follow-up item**, not this wave).
- The output floor, EL aggregation, and prior-period flows are per-scope — hence the execution
  model below.

## Execution model: run-per-scope

Each submission is a **full pipeline run** over that scope's resolved input population. Never a
filter over another run's sealed ledger. The reporting layer (cellspec executor, template
modules, cell-fact export) needs **no changes** — it is a pure function of the sealed ledger.

**Invariant I1 (hard):** with no scope configured (`reporting_entity is None`), behaviour is
byte-identical to today. All existing tests pass untouched; goldens do not move; the new stage
no-ops.

**I1 carve-out (ruled at Wave-1 review):** the cell-fact export (`facts.py`) stamps
`entity_name` and `consolidation_basis` as always-present columns (null when unscoped), so the
unscoped corep/pillar3 facts parquet gains two null columns vs pre-feature output. Accepted
deliberately: a stable feed schema beats a scope-varying one, and it extends the existing
always-stamped `entity_identifier` pattern. The Excel metadata sheet (`as_sheet_fields`)
remains gated and byte-identical when unscoped.

## Data model (exact names — do not deviate)

### New input table: `config/reporting_entities` (OPTIONAL)
The reporting-hierarchy registry. Columns:

| column | dtype | required | notes |
|---|---|---|---|
| `entity_reference` | String | yes | unique key |
| `entity_name` | String | no | display name |
| `lei` | String | no | Legal Entity Identifier |
| `parent_entity_reference` | String | no (null = group apex) | parent link; tree, single root |
| `institution_type` | String | no | values mirror `InstitutionType` enum values |
| `core_uk_group` | Boolean | no, default False | Art. 113(6) permission perimeter (future use) |

### New input table: `mapping/book_entity_mapping` (OPTIONAL)
Maps booking books to reporting entities. Columns:

| column | dtype | required |
|---|---|---|
| `book_code` | String | yes |
| `reporting_entity_reference` | String | yes |

### New columns on existing schemas (all `required=False`, nullable, no default fill)
- `intragroup_entity_reference` (String) on: `FACILITY_SCHEMA`, `LOAN_SCHEMA`,
  `CONTINGENTS_SCHEMA`, `EQUITY_SCHEMA` (equity_exposures), CCR **netting_sets** schema,
  SFT **trades** schema. Non-null = "this exposure is to group entity X". Null = external.
- `guarantor_entity_reference` (String) on `GUARANTEE_SCHEMA`. Non-null = guarantor is group
  entity X.
- `book_code` (String, `required=False`, default `""`) added to: `EQUITY_SCHEMA`
  (equity_exposures), CCR netting_sets schema, SFT trades schema — mirroring the existing
  facility/loan/contingent column.

Deliberately NOT tagged this wave: collateral issued by group entities, CIU holdings
(follow the parent equity row). Reference frames (ratings, provisions, collateral,
mappings, specialised_lending) are never filtered — dropped exposures simply stop joining
to them.

### `RawDataBundle` (contracts/bundles.py)
Two new optional frames: `reporting_entities: pl.LazyFrame | None = None`,
`book_entity_mappings: pl.LazyFrame | None = None`. Loader loads them via two new
`DataSourceFile` entries (ids `reporting_entities`, `book_entity_mapping`), both OPTIONAL.

## Config / API plumbing

- `CalculationConfig` gains top-level fields: `reporting_entity: str | None = None`
  (an `entity_reference` into the registry) and `reporting_basis: ReportingBasis | None = None`.
  Both factories (`.crr()`, `.basel_3_1()`) accept and set them. Rules:
  - `reporting_entity` set without `reporting_basis` → `ValueError` (config error, exception is
    correct here).
  - `reporting_basis` alone remains valid (existing floor-applicability semantics).
  - On `.basel_3_1()`, when top-level `reporting_basis`/`institution_type` are given and the
    `OutputFloorConfig` does not explicitly set its own, propagate top-level into the floor
    config so Art. 92(2A) applicability keeps working (backward compatible: existing kwargs
    still accepted).
- `CreditRiskCalc` (api/service.py) accepts `reporting_entity` / `reporting_basis` and forwards
  via `_create_config`.
- `CalculationResponse` (api/models.py) carries `reporting_entity: str | None` and
  `reporting_basis: str | None` (string value of the enum).
- `CalculationFingerprint` (api/run_index.py) gains `reporting_entity: str | None = None` and
  `reporting_basis: str | None = None`; both feed `compute_fingerprint` and `_params_key`.
  Persisted-JSON backward compatibility via the None defaults.
- `FilingMetadata` (reporting/facts.py) gains `consolidation_basis: str | None = None` and
  `entity_name: str | None = None`; both appear in `as_sheet_fields()` and are stamped by
  `_stamp_metadata`; `stamped_filename()` appends `_<entity_identifier>_<basis>` tokens when
  present (filesystem-safe, lowercase).
- REST (api/rest.py): `CalculateRequest`, `ComparisonRequest`, `ReconcileRequest` gain optional
  `reporting_entity` / `reporting_basis` fields, threaded through to `CreditRiskCalc`.
  `get_template_bundles` passes the run's basis into the COREP generator path it already
  supports. New `GET /api/entities?data_path=...` returns the registry rows (empty list when the
  file is absent).
- Recon workspace: `workspace_id()` (ui/app/recon_signoff.py) folds `reporting_entity` +
  `reporting_basis` into the hash (None → stable sentinel so existing workspaces keep their ids).
- UI forms (ui/app/main.py + templates + form-state modules): calculator, comparison and
  reconciliation forms gain an optional `reporting_entity` text input and `reporting_basis`
  select (blank / individual / sub_consolidated / consolidated), persisted in the form-state
  dataclasses like existing fields, passed through the workers.

## Scope resolver stage

New registered stage `resolve_scope` (engine/stages/scope/), inserted in the literal
`engine/registry.py` list immediately after the load stage. It consumes the loaded
`RawDataBundle` artifact and republishes the SAME artifact key with a filtered bundle, so every
downstream stage is untouched. No-op (identity) when `config.reporting_entity is None`.

Logic (module-level typed functions; module logger per arch_check check 8; docstring cites
CRR Art. 6/11/18 — do NOT add `@cites` decorators this wave):

1. Collect the (tiny) registry + mapping frames eagerly (document why with a comment).
2. Validate registry: unique `entity_reference`; parent links form a tree (no cycles, unknown
   parents, at most one root). Failure → error code `SCP004` (severity ERROR) and the resolver
   filters all exposure-bearing frames to empty (loud, non-throwing).
3. Requested `reporting_entity` not in registry → `SCP006` (ERROR) + empty selection.
4. Membership set: `consolidated` / `sub_consolidated` → the entity's subtree (inclusive);
   `individual` → the entity alone.
5. Booking filter on exposure-bearing frames (facilities, loans, contingents,
   equity_exposures, ccr netting sets + their trades, sft trades): join `book_code` →
   `book_entity_mapping`; keep rows whose mapped entity ∈ membership. Rows with blank/unmapped
   `book_code` → `SCP001` (ERROR) and excluded (cannot be attributed). Mapping rows referencing
   unknown entities → `SCP002` (ERROR, mapping row ignored).
6. Intragroup handling: `intragroup_entity_reference` ∈ membership →
   - consolidated/sub_consolidated: DROP the row (elimination);
   - individual: KEEP the row (Art. 113(6) treatment is a follow-up; no RW change this wave).
   Tag referencing an entity not in the registry → `SCP003` (ERROR, row kept, treated external).
7. Guarantees: on consolidated/sub_consolidated runs, guarantee rows with
   `guarantor_entity_reference` ∈ membership are dropped (internal protection is not CRM at the
   consolidated level). On individual runs, kept.
8. Errors accumulate as `CalculationError`s on the bundle (never raise); pick an appropriate
   `ErrorCategory`; codes `SCP001`-`SCP006` (`SCP005` = WARNING when one counterparty has a mix
   of tagged and untagged exposures).

CCR note: filtering is at netting-set grain; trades are then semi-joined onto surviving netting
sets. Keep frames lazy except the tiny registry/mapping collects.

## UI hierarchy view (wave 3)

Page `GET /hierarchy?data_path=...` rendering the registry tree (server-side Jinja + inline SVG
or nested lists, matching the existing `--oah-*` theme), showing per-entity name/LEI/type and
which scopes it can head. Calculator form links to it. Uses `/api/entities`.

## Test expectations

- Unit: resolver membership/filtering/DQ codes; config validation + factory propagation;
  fingerprint distinguishes scopes; FilingMetadata stamping/filename.
- Contracts: loader loads the two new tables; bundle fields; schema presence.
- Integration: small multi-entity fixture group — consolidated run eliminates intragroup rows
  and sums subsidiaries; solo run keeps intragroup rows; totals reconcile by construction.
- Fixtures: new builders under tests/fixtures (parquets are generated artifacts; builders MUST
  be registered in tests/fixtures/generate_all.py).

## Wave plan / ownership (disjoint files — do not stray)

- **W1-A (plumbing):** contracts/config.py, api/service.py, api/models.py, api/run_index.py,
  reporting/facts.py (+ new unit-test files only).
- **W1-B (data model):** data/schemas.py, config/data_sources.py, contracts/bundles.py,
  engine/loader.py (+ new unit/contract-test files only).
- **W1-C (fixtures):** tests/fixtures/ only.
- **W2-D (resolver):** engine/stages/scope/ (new), engine/registry.py (+ new test files).
- **W2-E (REST/UI plumbing):** api/rest.py, ui/app/ (+ new test files).
- **W3-F (hierarchy page):** ui/app/, ui/views/ additions.
- **W3-G (integration tests):** tests/integration/ new files.
- Reviewer agents challenge each wave; orchestrator runs the validation gate and commits.
