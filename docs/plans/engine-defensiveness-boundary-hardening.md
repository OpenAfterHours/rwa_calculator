# Engine Defensiveness — Boundary Hardening Plan

**Status:** Folded into [Target Architecture Migration](target-architecture-migration.md)
**Phase 3** (producer-sealed edge contracts). This document preserves the original
investigation (multi-agent audit, 2026-05-29) and its binding guardrails; committed to
the repo 2026-06-11 so the contract-debt baseline is tracked in-repo rather than in
agent session memory.

## Root cause

The dominant defect behind the engine's defensive column-presence / `fill_null` /
multi-name-fallback guards is **no producer-enforced inter-stage column contract**:

- `HIERARCHY/CLASSIFIER/CRM_OUTPUT_SCHEMA` (`data/schemas.py`) exist as ColumnSpec
  contracts but are applied **consumer-side only** (e.g. `SA_INPUT_CONTRACT` in
  `sa/namespace.py`).
- Producing stages never `ensure_columns` their own output.
- Inter-stage bundles have no `__post_init__` verification.
- The `contracts/validation.py` bundle validators were never wired into `pipeline.py`.
- Tests that bypass the pipeline are the documented driver: the engine's effective
  input domain became the union of historical fixture shapes (e.g. the
  `child_type`/`node_type`/neither three-way in `hierarchy.py`).

**Fix shape** (now Phase 3 of the migration, upgraded): per-stage
`ensure_columns(*_OUTPUT_CONTRACT)` at stage exit — evolved into `seal(df, EDGE)`
(assert + producer-owned defaults + strip undeclared scratch + branded frame) — plus a
non-mutating `__post_init__` presence/dtype verifier on the frozen bundles, and one
conformant test-fixture builder per edge (template:
`tests/integration/conftest.py::_rows_to_lazyframe`).

## Measured baseline

- 2026-05-29 audit: **189 guards** triaged; only ~16 of 39 proposal groups removable.
- 2026-06-11 review re-measure: ~1,050 defensive pattern sites / ~1,210 raw lines
  (~355 presence guards, ~474 `fill_null`s, ~196–221 `collect_schema` probes) — the
  debt roughly **doubled** in two weeks of feature work. This is why Phase 0 commits a
  ratchet (`scripts/arch_metrics.json` + `check_ratchet_metrics`) before any
  refactoring starts.

## Critical guardrail — do NOT naively delete guards

**~130 of the 189 audited guards are KEEP.** They are load-bearing, not noise:

- **Float/String `fill_null` is deliberately NOT broadened to `0.0`** — filling
  EAD/provision nulls with `0.0` is **anti-conservative** (understates RWA).
  Boolean-only fill is pinned by `tests/contracts/test_boolean_defaults_only.py`;
  rationale in `data/column_spec.py` (Risk-sign-off conservatism gate). Any contract
  added must use null defaults for Float/String.
- KEEP also covers: optional-input-*file* None guards (no securitisations/SFTs/CIUs is
  normal), required-True input guards (`beneficiary_type` — `ensure_columns` never
  adds required columns), config-gated columns (`sa_rwa`), by-design-null columns
  (`rwa_post_factor` null on IRB rows), and regulatory tri-state null semantics
  (`turnover_m` null ≠ 0 for SME support factor; `cp_is_managed_as_retail`
  `fill_null(True)` for Art. 123A).

Guard deletion is **per-sealed-edge**, triaged against the KEEP list, with the ratchet
enforcing monotone decrease — never a bulk sweep.

## Known anti-conservative divergences to resolve (recorded decisions required)

- `qualifies_as_retail`: defaults True / True / False across `data/schemas.py`,
  `sa/namespace.py` (`fill_null(True)`), and `b31_risk_weights.py` (coalesce-False).
- `has_default_definition_info`: absent → skip the equity 1.5× multiplier vs null →
  apply it (`equity/calculator.py`).

Each gets an explicit preserve-or-fix regulatory decision validated against
`tests/oracle/` before any golden regeneration (migration plan, Phase 0 hard ordering
rule).

## Regression guardrails

- `scripts/arch_check.py` `check_ratchet_metrics` (Phase 0): guard counts may not
  increase.
- Proposed `check_no_redundant_presence_guard` with a `PRESENCE_GUARD_ALLOWLIST` for
  the KEEP cases (lands with Phase 3 as edges seal).
