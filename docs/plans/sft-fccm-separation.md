# SFT / FCCM Separation of Concerns

**Status:** ✅ DONE — all phases 1–8 complete (2026-06-20). FCCM SFTs are now a peer subsystem (`engine/sft/`, `sft_fccm` stage, `RawDataBundle.sft`); `engine/ccr/` is SA-CCR-derivatives-only. See the per-phase checkmarks in §5 below.
**Author:** Investigation 2026-06-19
**Scope:** Separate Securities Financing Transaction (SFT) FCCM EAD from OTC-derivative SA-CCR EAD across the CCR input + engine surface.
**Related:** [target-architecture-migration.md](target-architecture-migration.md) (Phase 4 fold / literal registry / edge contracts).

---

## 1. Problem

Two regulatory EAD methods are physically co-mingled across the entire CCR input surface:

- **SA-CCR** — OTC derivatives, CRR Art. 274, `EAD = α·(RC + PFE)`. Implemented in `src/rwa_calc/engine/ccr/pipeline_adapter.py` and the `engine/ccr/*` submodules.
- **FCCM** — SFTs, CRR Art. 220–223, `E* = max(0, E·(1+HE) − CVA·(1−HC−HFX))`. Implemented in `src/rwa_calc/engine/ccr/sft_fccm.py`.

The confusion is structural, not incidental. Four concrete coupling points (all verified against source):

### (a) One schema, ~90% derivative-shaped, discriminated by a free-text string
`TRADE_SCHEMA` (`src/rwa_calc/data/schemas.py:890-983`) declares 30 columns. 22+ are SA-CCR-only (`delta`, `mtm_value`, `option_*`, `cdo_*`, `notional_leg2`, `market_price`, `number_of_units`, `reference_entity`, `commodity_type`, `is_index`, `credit_quality`, `is_legacy_cva_exempt`). The only thing that flags an SFT is the inline comment on line 897 (`# "derivative" | "sft"`). The `golden_ccr_a11_a12` fixture proves the cost: each SFT row carries ~25 `None`-valued derivative columns and a meaningless `asset_class="credit"`.

### (b) The three FCCM input columns are schema-orphaned (tunnelled, undeclared)
`sft_fccm.py:153-161` reads `exposure_collateral_type`, `exposure_security_cqs`, `exposure_security_residual_maturity_years` off the trade row — each behind an `if "<col>" in trade_schema` guard, **because none is declared in `TRADE_SCHEMA`**. They survive loading only because the CCR bundle is loaded via `enforce_schema(lf, schema, strict=False)` (`loader.py:483`), which casts/adds declared columns but does **not** `.select()` away undeclared ones — unlike every other input table, which seals against `RAW_TABLE_EDGES` and strips. The same three names *are* declared on `LOAN_SCHEMA` (`schemas.py:266-268`) and `CONTINGENTS_SCHEMA` (`353-355`) for an unrelated lending purpose, so grepping the name actively misleads.

### (c) The split happens deep in the engine, not at the data boundary
`ccr_rows_to_exposures` (`pipeline_adapter.py:87-190`) calls `_split_ccr_bundle_by_transaction_type` (`193-254`), which partitions one `RawCCRBundle` on `transaction_type == "sft"`, runs the two chains separately, and re-stitches via `pl.concat([...], how="diagonal_relaxed")` (line 189). Nobody inspecting `config/data_sources.py`, the loader, `RawCCRBundle`, or even the stage adapter `engine/stages/ccr.py` can discover that two regulatory methods diverge. The split key `transaction_type` has **no** value-constraint set and **no** `COLUMN_VALUE_CONSTRAINTS` entry, so a typo (`"SFT"`, `"repo"`) silently routes to SA-CCR and produces ≈£0 EAD with no DQ error.

### (d) "SFT" means two unrelated things
`transaction_type == "sft"` (FCCM EAD, Art. 220–223) is unrelated to the `is_sft` Boolean on `LOAN`/`CONTINGENT`/`FACILITY` schemas (`schemas.py:188/227/337`), which drives F-IRB `M = 0.5y` and the 1-day maturity floor (Art. 162) — `engine/irb/transforms.py:895-963`. Same acronym, same `schemas.py`, zero interaction.

### The tell
FCCM's *only* cross-package engine dependency is `engine/crm/haircut_tables.py` (`sft_fccm.py:52-56`), and it shares **zero** computational code with SA-CCR (which uses rulepack supervisory factors). FCCM is architecturally a CRM treatment parked inside a package billed as SA-CCR.

---

## 2. Recommendation: promote FCCM to a peer subsystem (`engine/sft/`)

Move FCCM out of `engine/ccr/` into a sibling `engine/sft/` subpackage with:
- its own lean input schemas (`SFT_TRADE_SCHEMA`, optional `SFT_COLLATERAL_SCHEMA`),
- its own `RawSFTBundle` on `RawDataBundle.sft`,
- its own `sft_fccm` `StageSpec` in the literal registry (adjacent to `ccr_sa_ccr`),
- its own `SFTConfig`,
- a dedicated `sft_trades` dataload.

`engine/ccr/` becomes SA-CCR-derivatives-only.

### Why this over the alternatives

| Criterion | A: in-place clarify | B: split at loader | **C: peer subsystem (chosen)** |
|---|---|---|---|
| Separation of concerns | 3/10 (symptom only) | 7/10 | **9/10** |
| Developer clarity | 7 | 8 | **9** |
| Migration safety | 9 | 7 | 6 |
| Convention fit | 7 | 8 | **9** |

Only C makes the divergence visible at the seams a developer naturally inspects: `config/data_sources.py`, the loader, `RawDataBundle`, and the literal `PIPELINE_STAGES` list (`registry.py:44-54`). "Where do SFTs diverge from derivatives?" becomes *read the registry* (two adjacent stages) instead of *read the adapter internals*. C also places FCCM next to the subsystem it actually reuses (`engine/crm`) and lets the dead coupling be deleted outright: `_split_ccr_bundle_by_transaction_type`, the intra-adapter `diagonal_relaxed` SFT concat, and the inert `transaction_type == 'sft'` branch in `engine/ccr/maturity_factor.py`.

Convention fit is highest: a new `engine/<domain>/` package of plain typed transforms, a frozen `RawSFTBundle`, a literal `StageSpec` entry (gets `stage_timer` for free), an edge sealed at stage exit, rulepack-resolved values (`liquidation_period_repo` stays in the common pack), CRM-table reuse — all idiomatic. `arch_check` passes unchanged (no module-scope regulatory scalars, no `rwa_calc.data.tables` import, no `config.is_crr` branch). Crucially, `RawDataBundle.ccr` is a single optional field and **`RawDataBundle`'s field count is not contract-pinned** — adding `sft: RawSFTBundle | None = None` is purely additive, unlike touching the hard-pinned 7-field `RawCCRBundle`.

### Grafts from A/B (done regardless)
1. Declare the three FCCM columns first-class and delete the tunnel guards (`sft_fccm.py:153-161`).
2. Add `VALID_TRANSACTION_TYPES` + a `COLUMN_VALUE_CONSTRAINTS` entry, and wire the SFT trade frame into `validate_bundle_values` (`contracts/validation.py`) so a bad discriminator raises DQ006 instead of mis-routing.
3. Load the new SFT tables through the standard `seal_lenient` + `RAW_TABLE_EDGES` path, not `enforce_schema` — ending CCR's status as the lone seal-bypassing input family.
4. Fail loud on the reserved `var`/`imm` methods rather than silently dropping all SFT rows (current `pipeline_adapter.py:187-190` returns derivative rows only).

---

## 3. ⚠️ Critical constraint: the SFT stage must seal to the existing `ccr_exit` brand

A naive design would give the SFT stage a fresh `SFT_EXIT_EDGE` (brand `"sft_exit"`). **That breaks the pipeline.** Downstream stages select their CCR-variant edge by *exact brand-string equality*, and the sealed-frame validator pins the allowed brand set:

- `engine/stages/classify/classifier.py:183` — `sealed_edge_of(...) == "ccr_exit"`
- `engine/crm/processor.py:622` — `== "classifier_exit_ccr"`
- `engine/stages/re_split/splitter.py:209` — `== "crm_exit_ccr"`
- `engine/stages/re_split/stage.py:71` — `== "re_split_exit_ccr"`
- `contracts/bundles.py:50-51` — `SEALED_FRAME_FIELDS["ResolvedHierarchyBundle.exposures"] = ("hierarchy_resolved", "hierarchy_exit", "ccr_exit")`; any other brand fails `__post_init__`.

A `"sft_exit"` brand matches none of these, so SFT rows would be de-selected onto the non-CCR edge and have their provenance columns (`source_netting_set_id`, `ccr_method`, `ead_ccr`) **stripped** — or the seal would reject the frame.

**Design rule:** the SFT stage appends onto `resolved.exposures` (which `ccr_sa_ccr` may already have sealed to `ccr_exit`) and **re-seals against the existing `CCR_EXIT_EDGE` / `ccr_exit` brand**. SFT and derivative rows share the same `resolved.exposures` frame anyway. The SFT-vs-derivative typing lives in the *input* bundle and schema, not in a new exit brand. SA-CCR provenance columns stay null on SFT rows naturally because the FCCM path never projects them (`CCR_EXIT_EDGE` declares them; the SFT rows arrive null via the `diagonal_relaxed` append, exactly as today).

---

## 4. Input model (operator decisions Q3 + Q4)

**Q3 — give SFT its own lean schemas (do not reuse `NETTING_SET_SCHEMA` / `CCR_COLLATERAL_SCHEMA`).**
**Q4 — one file is acceptable.**

FCCM's current regulatory scope is single-trade, single-counterparty netting sets (Art. 220(1)(a); `sft_fccm.py:26-31`). That collapses the netting set onto the trade, so the lean model needs **no separate SFT netting-set table** — the netting-set `counterparty_reference` is denormalised onto the trade row.

- **`SFT_TRADE_SCHEMA`** (trade grain — the single primary dataload, `sft_trades`):
  - `trade_id`, `netting_set_id` (kept for the `ccr__<netting_set_id>` output reference + collateral join), `counterparty_reference` (denormalised from the netting set),
  - `notional` (E), `currency`, `maturity_date`, `start_date`,
  - `exposure_collateral_type`, `exposure_security_cqs`, `exposure_security_residual_maturity_years` (the three Art. 223(5) HE inputs, now first-class + `@cites`).
- **`SFT_COLLATERAL_SCHEMA`** (collateral grain — *optional* second dataload, `sft_collateral`):
  - `ccr_collateral_reference`, `netting_set_id`, `collateral_type`, `market_value`, `currency`, `issuer_cqs`, `residual_maturity_years`.

Collateral is genuinely a different grain (0..n securities per netting set), so it stays a separate optional file. For the common uncollateralised SFT (e.g. CCR-A11) this is literally **one file**; the collateral file appears only when collateral is posted (CCR-A12). Net file-count win: today's four CCR-style files (`ccr_trades`, `ccr_netting_sets`, `ccr_margin_agreements`, `ccr_collateral`) reduce to **one + one optional** for the SFT book.

The new files live under the existing `ccr/` data directory by default (matching `data_sources.py:172-192`) unless a dedicated `sft/` directory is preferred; this is a cosmetic choice settled at Phase 4.

---

## 5. Phased migration plan

Each phase is independently committable and leaves the suite green. Gate after every phase:

```
uv run python scripts/arch_check.py && uv run ruff check && uv run ruff format --check && uv run ty check && uv run pytest tests/
```

### Phase 1 — Pure extraction (no behaviour change) ✅ DONE
Create `src/rwa_calc/engine/sft/`. Move `engine/ccr/sft_fccm.py` → `engine/sft/fccm.py` **verbatim** (it already imports only `engine/crm/haircut_tables`, the rulepack, and `contracts/bundles`). Re-point the import at `pipeline_adapter.py:62` and update test/fixture import paths.
- **Files:** `engine/sft/__init__.py` (new), `engine/sft/fccm.py` (moved), `engine/ccr/pipeline_adapter.py`, `engine/ccr/__init__.py`, test imports.
- **Note:** `engine/sft/` is a plain engine domain package (transforms), **not** a stage package — it must not be added to any `STAGE_PACKAGES_WITHOUT_RUN` list in `arch_check.py`.
- **arch_check:** unchanged — `liquidation_period_repo` stays pack-resolved; `SFT_TRANSACTION_TYPE = "sft"` is a literal token (allowed).

### Phase 2 — Declare the SFT input contract (kills the tunnelling) ✅ DONE
Add `SFT_TRADE_SCHEMA` + `SFT_COLLATERAL_SCHEMA` (Section 4) to `data/schemas.py`, the three HE columns cited `@cites("CRR Art. 223")`. Add `VALID_TRANSACTION_TYPES = {"derivative", "sft"}` and a `COLUMN_VALUE_CONSTRAINTS` entry for the SFT trade frame's `transaction_type`. Schemas land but nothing wires them yet.
- **Files:** `data/schemas.py`, `tests/contracts/test_sft_schemas_contract.py` (new — pin the columns).
- **Untouched here:** the existing `TRADE_SCHEMA` 30-column pin and `RawCCRBundle` 7-field pin (`tests/contracts/test_ccr_schemas_contract.py`, `test_ccr_bundles_contract.py`).

### Phase 3 — Config peer ✅ DONE
Add frozen `SFTConfig(method: Literal["fccm","var","imm"] = "fccm")` to `contracts/config.py`, cited Art. 220–223; add `sft: SFTConfig` to `CalculationConfig`; expose `sft_method` as a factory arg on `.crr()` / `.basel_3_1()` (currently unreachable). Add the fail-loud guard for `var`/`imm`. Keep `CCRConfig.sft_method` as a **computed read-through property** (the dataclass is frozen — it cannot be a field default that shadows `SFTConfig.method`) for one release; rewire the read site at `pipeline_adapter.py:187` to `SFTConfig.method` in the same commit.
- **Files:** `contracts/config.py`, factory-method tests.

### Phase 4 — Peer bundle + loader dataload (additive, backward-compatible) ✅ DONE
Add `SftTradeBundle` + optional `SftCollateralBundle` and `RawSFTBundle(trades, collateral, errors)` to `contracts/bundles.py`, plus `sft: RawSFTBundle | None = None` on `RawDataBundle`. Add `raw_sft_trades` / `raw_sft_collateral` edges to `contracts/edges.py` and register the leaf frames in `SEALED_FRAME_FIELDS`. Add `sft_trades` (+ optional `sft_collateral`) `DataSourceFile` entries to `config/data_sources.py`, `DataSourceConfig.sft_*_file` fields + `from_registry` wiring, and `_build_raw_sft_bundle` in `loader.py` **loading via `seal_lenient` + `RAW_TABLE_EDGES`** (not `enforce_schema`).
- **Backward-compat:** `RawDataBundle.sft` defaults `None`; every existing construction is unaffected; no existing fixture populates it yet.
- **Files:** `contracts/bundles.py`, `contracts/edges.py`, `config/data_sources.py`, `engine/loader.py`, `tests/contracts/test_sft_bundles_contract.py` (new), a loader test (extend `tests/integration/test_ccr_loader.py` or add `test_sft_loader.py`).
- **Verify:** `tests/fixtures/raw_bundle.py::make_raw_bundle` and `tests/contracts/test_edge_contracts.py` iterate `dataclasses.fields(RawDataBundle)` — confirm neither asserts that *every* frame field is a bare loader-sealed frame (`RawSFTBundle` is a composite, like `ccr`, so it should be exempt exactly as `ccr` is).

### Phase 5 — Peer stage (sealing to the `ccr_exit` brand) ✅ DONE
Create `engine/stages/sft.py::run(ctx, rulepack, run_config)` that no-ops on `raw.sft is None`, calls `sft_rows_to_exposures`, enriches ratings (lift `_enrich_ccr_rows_with_ratings` out of `engine/stages/ccr.py` into a shared `engine/stages/_ccr_shared.py` consumed by both), appends via `diagonal_relaxed`, and **re-seals `resolved.exposures` against `CCR_EXIT_EDGE` / `ccr_exit`** (Section 3 — *not* a new edge). Insert `StageSpec("sft_fccm", sft.run, error_type="sft_error")` into `PIPELINE_STAGES` **immediately after `ccr_sa_ccr`** (`registry.py:47`).
- **Verify:** `engine/pipeline.py` error-merge accepts a new `error_type` token (`"sft_error"`); pin the new `sft_fccm` `stage_timer` label in the observability contract test (`tests/contracts/test_logging_contract.py` / integration).
- **Sequential re-seal:** `ccr_sa_ccr` then `sft_fccm` both `replace(resolved, exposures=materialise_sealed_edge(...))` on the same field — both seal to `ccr_exit`, so the last-writer brand is what the classifier expects.
- **Files:** `engine/stages/sft.py` (new), `engine/stages/_ccr_shared.py` (new), `engine/stages/ccr.py`, `engine/registry.py`, `engine/stages/__init__.py`, observability test.
- **Backward-compat:** existing single-file fixtures still flow SFT rows through `raw.ccr` and the legacy in-CCR SFT branch; the new stage only fires when `raw.sft` is populated.

### Phase 6 — Flip the source, delete the old path ✅ DONE
Re-point the SFT golden (`tests/fixtures/ccr/golden_ccr_a11_a12.py`) and any firm wiring at `raw.sft` via a dedicated SFT trade/collateral builder mirroring `SFT_TRADE_SCHEMA`. Add **guards**:
- error if any `transaction_type == "sft"` row survives in `raw.ccr` (the derivative chain would otherwise mis-price it via SA-CCR once the SFT branch is gone),
- error if both `raw.ccr` (with SFT rows) and `raw.sft` are populated (double-count).

Then delete: the `config_ccr.sft_method` gate + SFT `diagonal_relaxed` concat in `ccr_rows_to_exposures` (`pipeline_adapter.py:187-190`), `_split_ccr_bundle_by_transaction_type` (`193-254`), and the inert `transaction_type == 'sft'` `all_sft_in_ns` branch in `engine/ccr/maturity_factor.py`. `engine/ccr/` becomes derivatives-only.
- **`transaction_type` clarification:** it is a *required* column every derivative row still carries (value `"derivative"`); it cannot be removed and has no value-set to narrow. The only edit is the inline comment at `schemas.py:897`.
- **`diagonal_relaxed` clarification:** the *cross-stage append onto `resolved.exposures`* (`engine/stages/ccr.py:145-148` and the new `engine/stages/sft.py`) still uses `diagonal_relaxed` — correct, stays. What disappears is the *intra-adapter* SFT/derivative concat.
- **Hard-pinned contract tests (one deliberate commit):** revise `tests/contracts/test_ccr_schemas_contract.py` (`_P8_35_EXPECTED_COLUMN_COUNT` and the `VALID_RISK_TYPES_INPUT` pins as needed) and confirm `tests/contracts/test_ccr_bundles_contract.py`'s 7-field `RawCCRBundle` pin still holds (C does not change `RawCCRBundle`). Re-express the `test_ccr_a11_sa_ccr_columns_null` assertion (`tests/acceptance/ccr/test_ccr_a11_a12_sft_fccm_ead.py:270-287`): SFT rows now arrive via the typed `sft` stage; SA-CCR provenance is null because the FCCM path never projects it, not because of a shared intra-adapter concat.
- **Files:** `engine/ccr/pipeline_adapter.py`, `engine/ccr/maturity_factor.py`, `data/schemas.py`, `tests/fixtures/ccr/` (new SFT builder), `tests/fixtures/generate_all.py`, the two contract tests, the A11/A12 acceptance test, `tests/contracts/test_ccr_fixture_builders.py` (loader round-trip shape assertions).

### Phase 7 — Downstream behaviour (operator decisions Q1 + Q2) ✅ DONE (7a + 7b; 7c deferred)
These are deliberate regulatory changes (not behaviour-preserving), each independently reviewable, each needing golden-output updates.

**Phase 7a — Output floor: include FCCM SFTs (Q1). ✅ DONE**
Today FCCM SFTs are excluded from the Basel 3.1 floor numerator because the floor tag keys on `risk_type == CCR_DERIVATIVE` only (`engine/stages/calc.py:126`). Extend the predicate to include `CCR_SFT` so SFT rows receive the floor-eligible tag (`SA_CCR_APPROACH` routes rows into `FLOOR_ELIGIBLE_APPROACHES` and out of `SA_APPROACHES` — `engine/aggregator/_schemas.py`). The tag's name becomes a slight misnomer for SFTs; consider renaming the constant to a method-neutral "CCR-via-SA, floored" label, or leave it and document. Regulatory basis: PS1/26 Art. 92(3A) does not place SFTs on the S-TREA exclusion list.
- **Files:** `engine/stages/calc.py`, possibly `engine/aggregator/_schemas.py`; acceptance test asserting SFT RWA enters the floor numerator; update CCR-A11/A12 (and any floor-scenario) expected outputs.

**Phase 7b — COREP / Pillar 3: report SFTs under C07 row 0090, not the SA-CCR templates (Q2). ✅ DONE**
Today both `_collect_ccr_rows` (`reporting/corep/generator.py:2986-3008`) and `_ccr_rows` (`reporting/pillar3/generator.py:1270-1283`) sum **all** `ccr__`-prefixed rows with no `risk_type` filter, so FCCM SFT EAD is reported inside the SA-CCR templates (COREP C34, Pillar 3 CCR1). Two changes:
1. Add a `risk_type != "CCR_SFT"` (equivalently `ccr_method != "fccm_sft"`) exclusion to both collectors so FCCM SFT EAD leaves the SA-CCR templates.
2. Implement **C07 (SA) row 0090 — SFT-netting** to receive the FCCM SFT EAD; it is currently unimplemented (`reporting/corep/generator.py:4043` — `# CCR rows (0090-0130) not implemented`). Template guidance: PS1/26 App. 17 (`docs/assets/ps126app17`).
- **Files:** `reporting/corep/generator.py`, `reporting/pillar3/generator.py`; update `tests/expected_outputs/reporting/{crr,b31}/` goldens and the reporting reconciliation/golden tests.

**Phase 7c — Aggregator roll-up split (optional). ⏸ DEFERRED** (larger blast radius — sealed aggregator-exit contract; defer unless reconciliation needs it).
If the operator wants SFT vs derivative CCR EAD/RWA reconcilable at portfolio level, add `ead_ccr_sft` / `ead_ccr_derivative` fields to `AggregatedResultBundle`. This touches the **sealed aggregator-exit contract** and the aggregator goldens — larger blast radius; defer unless reconciliation needs it.

### Phase 8 — Docs + changelog ✅ DONE
Added a CCR-vs-SFT input-separation section to [`docs/data-model/input-schemas.md`](../data-model/input-schemas.md#sft-input-schemas-fccm) and a dedicated FCCM SFT spec page at [`docs/specifications/crr/sft/index.md`](../specifications/crr/sft/index.md) (peer to the SA-CCR [`crr/ccr/`](../specifications/crr/ccr/index.md) directory), both carrying the explicit callout disambiguating the two meanings of "SFT" (Section 6). Consolidated the phases 1–7 narrative in `docs/appendix/changelog.md`. Corrected the `_filter_sft` `@cites` in `reporting/corep/generator.py` (was `PS1/26, paragraph 1.3` — the COREP Annex II negation convention — now `PS1/26`, matching the C 07.00 row 0090 / App. 17 guidance the function implements) and regenerated the citation snapshot. `uv run zensical build` passes.

---

## 6. The `is_sft` naming collision — disambiguate, don't rename (in this work)

The lending `is_sft` Boolean (`LOAN`/`CONTINGENT`/`FACILITY` schemas, the `hierarchy_resolved` edge, `irb/transforms.py:895-963`) is a genuinely separate concept from the CCR `transaction_type == "sft"` token. Renaming it (`is_sft` → `is_sft_lending`) is the largest-blast-radius change in any approach — it touches schemas, the sealed `hierarchy_resolved` edge, IRB transforms, the `firb_sft_supervisory_maturity` pack feature, and **every fixture/test that sets `is_sft`**.

**Recommendation: leave `is_sft` named as-is; disambiguate via prominent docstrings at both definition sites and a docs callout (Phase 8).** Promoting FCCM to `engine/sft/` already reduces the day-to-day grep ambiguity (CCR-SFT hits land in `engine/sft/`; lending-SFT hits land in `engine/irb/` and the lending schemas). If a rename is later judged worthwhile, do it as a **standalone codemod commit** after this migration lands, never interleaved.

---

## 7. Risks

- **Hard-pinned contract tests (Phase 6).** `test_ccr_schemas_contract.py` pins `TRADE_SCHEMA` column count and `VALID_RISK_TYPES_INPUT` length; coordinated edits, isolated to one intentional commit. The `RawCCRBundle` 7-field pin should survive (C does not change `RawCCRBundle`) — verify.
- **Dual-path window (Phases 5–6).** Two SFT code paths coexist (legacy in-CCR via `raw.ccr`, new stage via `raw.sft`), gated by which bundle is populated. Keep the window to one PR; the Phase 6 guards enforce mutual exclusivity.
- **Brand propagation (Section 3).** The single biggest failure mode — mitigated by sealing the SFT stage to the existing `ccr_exit` brand. Do **not** introduce a new exit brand without also widening all four selectors and `SEALED_FRAME_FIELDS`.
- **Golden churn (Phase 7).** Output-floor inclusion (7a) and COREP/Pillar 3 reclassification (7b) both change numeric outputs by design; expected-output goldens for CCR-A11/A12 and reporting must be regenerated and reviewed.
- **Categorical validator activation (graft 2).** Wiring the SFT frame into `validate_bundle_values` could surface latent invalid values in existing fixtures; fix in the same commit if so.
- **Float non-determinism.** Per project memory, Polars group-by float sums are not process-deterministic. FCCM `E*` arithmetic moves verbatim (Phase 1), so values are byte-identical modulo this pre-existing effect; acceptance goldens tolerate it as today.
- **Eager FCCM loops.** `sft_fccm.py` uses `.collect()` + `iter_rows` (lines 145/188/202). The verbatim move preserves them — a known LazyFrame-first divergence, not fixed here. Optional later cleanup.

---

## 8. Out of scope

- **VaR (Art. 221) and IMM (Art. 283) SFT EAD methods** — reserved on `SFTConfig.method`, unimplemented; Phase 3 only makes them fail loud.
- **Margined FCCM (Art. 285)** — current FCCM is unmargined, single-trade, single-counterparty only (`sft_fccm.py:26-31`).
- **Settlement-risk failed trades (Art. 378–380) and CCP default-fund contributions (Art. 308–309)** — shaped in `engine/stages/ccr.py:118-143` directly from `data.ccr` (pre-split), ride `CCR_EXIT_EDGE`, and stay with the CCR stage.
- **The `is_sft` rename** — deferred to a standalone future codemod (Section 6).
- **Dead `CCRConfig` knob cleanup** (`mpor_floor_days`, `recognise_im`, `enable_ccp_exposures`) — orthogonal; not required.

---

## 9. Verified file reference

| Concern | Location |
|---|---|
| Split mechanism (to delete) | `engine/ccr/pipeline_adapter.py:87-254` |
| FCCM (to move → `engine/sft/fccm.py`) | `engine/ccr/sft_fccm.py` |
| Tunnelled FCCM columns read | `engine/ccr/sft_fccm.py:153-161` |
| `TRADE_SCHEMA` (derivative-shaped) | `data/schemas.py:890-983` |
| Lending `is_sft` (unrelated) | `data/schemas.py:188/227/337`; `engine/irb/transforms.py:895-963` |
| CCR load via `enforce_schema` (no edge seal) | `engine/loader.py:449-575` (`_build_raw_ccr_bundle`, `_load_ccr_file_optional:483`) |
| `RawDataBundle.ccr` (single optional field) | `contracts/bundles.py` |
| Stage adapter + registry | `engine/stages/ccr.py:56-156`; `engine/registry.py:47` (`ccr_sa_ccr`) |
| Brand selectors (must reuse `ccr_exit`) | `classify/classifier.py:183`; `crm/processor.py:622`; `re_split/splitter.py:209`; `re_split/stage.py:71` |
| Sealed-frame brand pin | `contracts/bundles.py:50-51` (`SEALED_FRAME_FIELDS`) |
| Output-floor tag (Q1) | `engine/stages/calc.py:126` |
| COREP CCR collector (Q2) | `reporting/corep/generator.py:2986-3008`; C07 row 0090 unimplemented `:4043` |
| Pillar 3 CCR collector (Q2) | `reporting/pillar3/generator.py:1270-1283` |
| Data sources (CCR files) | `config/data_sources.py:172-192` |
| SFT golden fixture | `tests/fixtures/ccr/golden_ccr_a11_a12.py` |
| SFT acceptance test | `tests/acceptance/ccr/test_ccr_a11_a12_sft_fccm_ead.py` |
