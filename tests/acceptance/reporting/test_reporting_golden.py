"""
Reporting golden gate (migration Phase 7 S0).

Pipeline position:
    build_reporting_bundle -> PipelineOrchestrator -> result.results
        -> COREPGenerator / Pillar3Generator -> frozen golden frames

Key responsibilities:
- Freeze the full COREP + Pillar 3 template surface produced from the rich
  reporting portfolio (``tests/fixtures/reporting_portfolio.py``) as per-template
  golden files, captured once from real pipeline output.
- Gate every later declarative-reporting strangler slice (Phase 7 S4..N): a
  migrated template must reproduce its golden frame within tolerance, or the
  diff fails this test. This is the safety net the migration plan requires
  ("build the golden gate before the first strangler step").

Why tolerance, not byte-exact:
    Reporting templates are group-by/sum aggregates and Polars multi-threaded
    Float64 group-by sums are NOT process-deterministic (last 1-2 ulps differ
    run to run — the Phase 2 parity finding). So the gate is **structure-exact**
    (same frames present, same schema/column order, same row count + order, exact
    string cells, exact null positions) + **Float64 within rtol=1e-9, atol=1e-6**
    (the established Phase 2 parity convention).

Golden format:
    Per-template frames are stored as NDJSON (text, diffable, line-per-row) under
    ``tests/expected_outputs/reporting/{crr,b31}/`` — *.parquet is gitignored
    project-wide, and the engine goldens already use a committed-text source of
    truth. Each frame's exact schema (column order + dtypes) lives in
    ``manifest.json`` so an all-null column reloads as its true dtype rather than
    JSON-inferred Null.

Regenerating goldens:
    Set ``REGEN_REPORTING_GOLDENS=1`` and run this file. Each per-template frame
    is rewritten and ``manifest.json`` records per-frame schema plus which bundle
    fields are None / scalar (so a later non-None field FLAGS a regression rather
    than being silently captured). Each golden diff must get a recorded
    preserve-or-fix decision — never bulk-regen to make a red gate green.

References:
- tests/fixtures/reporting_portfolio.py: the oracle portfolio
- tests/acceptance/{crr,basel31}/test_p2_4{6,1}_*_corep.py: the run->generate pattern
- .claude/state/phase7-plan.md: S0 locked harness design
"""

from __future__ import annotations

import dataclasses
import json
import os
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

import polars as pl
import pytest
from tests.fixtures.reporting_portfolio import build_reporting_bundle

if TYPE_CHECKING:
    from polars._typing import PolarsDataType

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator
from rwa_calc.reporting.pillar3.generator import Pillar3Generator

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_GOLDEN_ROOT = Path(__file__).parent.parent.parent / "expected_outputs" / "reporting"
_REGEN = os.environ.get("REGEN_REPORTING_GOLDENS") == "1"

# Float comparison tolerance — Phase 2 parity convention (group-by float noise).
_RTOL = 1e-9
_ATOL = 1e-6

# Golden frames are Float64 / String only; the wider map future-proofs the
# schema-aware reload if a template later emits integer / boolean / date cells.
_DTYPE_BY_NAME: dict[str, PolarsDataType] = {
    str(dt): dt
    for dt in (
        pl.Float64,
        pl.Float32,
        pl.String,
        pl.Boolean,
        pl.Int8,
        pl.Int16,
        pl.Int32,
        pl.Int64,
        pl.UInt8,
        pl.UInt16,
        pl.UInt32,
        pl.UInt64,
        pl.Date,
    )
}


def _crr_config() -> CalculationConfig:
    return CalculationConfig.crr(
        reporting_date=date(2025, 12, 31), permission_mode=PermissionMode.IRB
    )


def _b31_config() -> CalculationConfig:
    # enforce_retail_granularity=False: the 0.2%-of-portfolio retail granularity
    # limb (Art. 123A(1)(b)(ii)) is unsatisfiable for a compact oracle portfolio;
    # CRE20.66 national discretion permits suppressing it. Without this, every
    # natural-person retail exposure reclassifies to corporate under B31 and the
    # retail template rows would be unreachable.
    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 1),
        permission_mode=PermissionMode.IRB,
        enforce_retail_granularity=False,
    )


# regime key -> (golden subdir, framework string, config factory)
_REGIMES: dict[str, tuple[str, str, Callable[[], CalculationConfig]]] = {
    "crr": ("crr", "CRR", _crr_config),
    "b31": ("b31", "BASEL_3_1", _b31_config),
}


# ---------------------------------------------------------------------------
# Bundle -> flat frame map
# ---------------------------------------------------------------------------


def _flatten_bundle(prefix: str, bundle: Any) -> tuple[dict[str, pl.DataFrame], dict]:
    """Split a template bundle into a flat ``key -> DataFrame`` map + a metadata dict.

    - ``pl.DataFrame`` field        -> one frame ``f"{prefix}__{field}"``
    - ``dict[str, pl.DataFrame]``   -> one frame per key ``f"{prefix}__{field}__{key}"``
    - ``None`` field                -> recorded in ``meta`` as null (so a later
                                       non-None value is detected as a new frame)
    - scalar (str / list) field     -> recorded in ``meta`` for exact assertion
    """
    frames: dict[str, pl.DataFrame] = {}
    meta: dict = {}
    for f in dataclasses.fields(bundle):
        value = getattr(bundle, f.name)
        key_base = f"{prefix}__{f.name}"
        if isinstance(value, pl.DataFrame):
            frames[key_base] = value
        elif isinstance(value, dict):
            meta[f.name] = {"kind": "dict", "keys": sorted(value.keys())}
            for sub_key, sub_df in value.items():
                frames[f"{key_base}__{sub_key}"] = sub_df
        elif value is None:
            meta[f.name] = None
        else:
            meta[f.name] = value
    return frames, meta


def _generate_frames(regime_key: str) -> tuple[dict[str, pl.DataFrame], dict]:
    """Run the portfolio through one regime and flatten both generator bundles."""
    _subdir, framework, config_factory = _REGIMES[regime_key]
    config = config_factory()
    result = PipelineOrchestrator().run_with_data(build_reporting_bundle(), config)

    corep = COREPGenerator().generate_from_lazyframe(result.results, framework=framework)
    pillar3 = Pillar3Generator().generate_from_lazyframe(result.results, framework=framework)

    corep_frames, corep_meta = _flatten_bundle("corep", corep)
    p3_frames, p3_meta = _flatten_bundle("pillar3", pillar3)

    frames = {**corep_frames, **p3_frames}
    meta = {"corep": corep_meta, "pillar3": p3_meta}
    return frames, meta


# ---------------------------------------------------------------------------
# Golden (NDJSON + schema) round-trip
# ---------------------------------------------------------------------------


def _schema_of(df: pl.DataFrame) -> dict[str, str]:
    """Ordered ``{column: dtype_name}`` map for schema-faithful reload."""
    return {col: str(dt) for col, dt in df.schema.items()}


def _read_golden(path: Path, schema: dict[str, str]) -> pl.DataFrame:
    """Reload a golden NDJSON frame, restoring exact column order + dtypes.

    JSON cannot type an all-null column, so we reload then cast to the stored
    schema; an empty file rebuilds the typed-but-rowless frame from schema alone.
    """
    typed = {col: _DTYPE_BY_NAME[name] for col, name in schema.items()}
    if not path.exists() or path.stat().st_size == 0:
        return pl.DataFrame(schema=typed)
    df = pl.read_ndjson(path)
    # Add any column JSON dropped because every value was null, then cast + order.
    missing = [pl.lit(None).alias(c) for c in schema if c not in df.columns]
    if missing:
        df = df.with_columns(missing)
    return df.select(list(schema)).cast(typed)  # ty: ignore[invalid-argument-type]


# ---------------------------------------------------------------------------
# Tolerance-based frame comparison
# ---------------------------------------------------------------------------

_FLOAT_DTYPES = (pl.Float32, pl.Float64)


def _frame_diffs(expected: pl.DataFrame, actual: pl.DataFrame, label: str) -> list[str]:
    """Return human-readable structural/numeric diffs (empty list == match)."""
    diffs: list[str] = []

    if expected.columns != actual.columns:
        diffs.append(
            f"{label}: column set/order differs\n"
            f"  expected: {expected.columns}\n  actual:   {actual.columns}"
        )
        return diffs  # column mismatch makes per-column comparison meaningless

    if expected.height != actual.height:
        diffs.append(
            f"{label}: row count differs (expected {expected.height}, actual {actual.height})"
        )
        return diffs

    if expected.schema != actual.schema:
        diffs.append(
            f"{label}: dtypes differ\n"
            f"  expected: {dict(expected.schema)}\n  actual:   {dict(actual.schema)}"
        )

    for col in expected.columns:
        exp_s = expected[col]
        act_s = actual[col]

        # Null positions must match exactly in every column.
        if not exp_s.is_null().equals(act_s.is_null()):
            mismatched = (exp_s.is_null() != act_s.is_null()).sum()
            diffs.append(f"{label}.{col}: null positions differ in {mismatched} row(s)")
            continue

        if exp_s.dtype in _FLOAT_DTYPES and act_s.dtype in _FLOAT_DTYPES:
            mask = exp_s.is_not_null()
            e = exp_s.filter(mask)
            a = act_s.filter(mask)
            if e.len() == 0:
                continue
            abs_err = (a - e).abs()
            tol = e.abs() * _RTOL + _ATOL
            over = abs_err > tol
            n_over = int(over.sum())
            if n_over:
                idx = over.arg_max()
                assert idx is not None  # n_over > 0 guarantees a max position
                diffs.append(
                    f"{label}.{col}: {n_over} float cell(s) exceed rtol={_RTOL}/atol={_ATOL}; "
                    f"worst expected={e[idx]!r} actual={a[idx]!r} (|err|={abs_err[idx]!r})"
                )
        else:
            # Exact equality for non-float (already null-aligned above).
            if not exp_s.equals(act_s):
                neq = (exp_s != act_s).fill_null(False).sum()
                diffs.append(f"{label}.{col}: {neq} non-float cell(s) differ")

    return diffs


# ---------------------------------------------------------------------------
# Capture (REGEN) helper
# ---------------------------------------------------------------------------


def _capture_frames(out: Path, frames: dict[str, pl.DataFrame], meta: dict) -> None:
    """Write goldens + manifest for one already-generated frame map.

    Shared with the CCR golden gate (``test_reporting_ccr_golden.py``), which
    runs a different portfolio through the same comparison machinery.
    """
    out.mkdir(parents=True, exist_ok=True)

    # Clear stale frames so a removed template does not linger as a golden.
    for stale in out.glob("*.ndjson"):
        stale.unlink()

    schemas: dict[str, dict[str, str]] = {}
    for key, df in sorted(frames.items()):
        df.write_ndjson(out / f"{key}.ndjson")
        schemas[key] = _schema_of(df)

    # NB: no sort_keys — the per-frame schema dict order IS the column order the
    # reload restores via .select(list(schema)); sorting it would scramble it.
    manifest = {"frames": schemas, "meta": meta}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))


def _capture(regime_key: str) -> None:
    """Write goldens + manifest for one regime of the rich portfolio."""
    frames, meta = _generate_frames(regime_key)
    _capture_frames(_GOLDEN_ROOT / _REGIMES[regime_key][0], frames, meta)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("regime_key", list(_REGIMES))
def test_reporting_templates_match_golden(regime_key: str) -> None:
    """Generated COREP + Pillar 3 templates match the frozen goldens within tolerance.

    Arrange: rich reporting portfolio + regime config.
    Act:     run pipeline -> generate both bundles -> flatten to per-template frames.
    Assert:  every golden frame is reproduced (structure-exact + float-rtol), the
             frame set matches exactly, and the None/scalar metadata matches.
    """
    if _REGEN:
        _capture(regime_key)
        pytest.skip(f"REGEN_REPORTING_GOLDENS=1 — captured goldens for {regime_key!r}")

    subdir = _REGIMES[regime_key][0]
    golden_dir = _GOLDEN_ROOT / subdir
    manifest_path = golden_dir / "manifest.json"
    assert manifest_path.exists(), (
        f"No reporting goldens for {regime_key!r} at {golden_dir}. "
        "Capture them first: REGEN_REPORTING_GOLDENS=1 uv run pytest "
        "tests/acceptance/reporting/test_reporting_golden.py"
    )

    manifest = json.loads(manifest_path.read_text())
    frames, meta = _generate_frames(regime_key)

    errors: list[str] = []

    # 1. Frame set must match exactly (no added/dropped templates).
    expected_keys = set(manifest["frames"])
    actual_keys = set(frames)
    if expected_keys != actual_keys:
        added = sorted(actual_keys - expected_keys)
        dropped = sorted(expected_keys - actual_keys)
        if added:
            errors.append(f"NEW template frames not in golden: {added}")
        if dropped:
            errors.append(f"MISSING template frames present in golden: {dropped}")

    # 2. None/scalar metadata must match (catches a None field becoming populated).
    if manifest["meta"] != meta:
        errors.append(
            f"bundle metadata changed:\n  expected: {manifest['meta']}\n  actual:   {meta}"
        )

    # 3. Per-frame structure + float-tolerance comparison.
    for key in sorted(expected_keys & actual_keys):
        expected_df = _read_golden(golden_dir / f"{key}.ndjson", manifest["frames"][key])
        errors.extend(_frame_diffs(expected_df, frames[key], key))

    assert not errors, "Reporting golden mismatch ({}):\n{}".format(regime_key, "\n".join(errors))
