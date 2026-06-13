"""Contract tests for the architecture-migration gates.

Mirrors arch_check checks 11, 12, 13 and the Phase-4 checks 14-16 (see
docs/plans/target-architecture-migration.md):

- **Check 11 — architecture-debt ratchet**: the measured defensive surface of
  ``engine/**`` (``.fill_null(`` sites, string-literal column-presence guards,
  ``.collect_schema(`` probes, max module LOC) may not increase above the
  committed baseline in ``scripts/arch_metrics.json``, and the watchfire
  ``@cites(`` decorator count may never decrease below it. Improvements are
  banked with ``python scripts/arch_check.py --update-baseline``.
- **Check 12 — import direction**: contracts/ imports nothing above
  domain/data; engine/ never imports api/ui/reporting/analysis; reporting/
  never imports api/ui; data/ and domain/ import nothing above themselves.
  Known legacy inversions live in ``IMPORT_DIRECTION_ALLOWLIST`` with the
  migration phase that retires them.
- **Check 13 — no empty-LazyFrame sentinels in engine/**: optional frames
  are ``None`` (migration Phase 2); constructing a bare ``pl.LazyFrame()``
  to stand in for an absent input conflates "absent" with "zero rows" and
  regrows the presence-guard debt the ratchet is burning down.
- **Check 14 — no Polars namespace registrations**: the
  ``register_(lazyframe|dataframe|expr|series)_namespace`` pattern is
  extinct (migration Phase 4, Slice 7) anywhere under ``src/rwa_calc`` —
  calculator logic is plain typed functions composed via
  ``.pipe(fn, config)``. No allowlist.
- **Check 15 — the stage registry is literal**: ``engine/registry.py``'s
  module body is the docstring, imports, the module logger, and assignments
  whose value is a literal tuple of ``StageSpec(...)`` calls with
  literal/name/attribute arguments — no conditionals, loops,
  comprehensions, or function defs.
- **Check 16 — stage anatomy**: every ``StageSpec.fn`` in the registry is
  ``<stage module>.run`` resolved from ``rwa_calc.engine.stages``, the
  stage module binds a top-level ``run``, and every package directly under
  ``engine/stages/`` exposes ``run`` from its ``__init__`` unless pinned in
  the shrink-only ``STAGE_PACKAGES_WITHOUT_RUN`` set.

These tests re-use the check functions from ``scripts/arch_check.py`` so the
rules, metrics, and allowlists live in exactly one place (the same pattern as
``test_data_layer_boundary.py``).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src" / "rwa_calc"


def _load_arch_check():
    """Load scripts/arch_check.py as a module without polluting sys.path."""
    script_path = REPO_ROOT / "scripts" / "arch_check.py"
    spec = importlib.util.spec_from_file_location("_arch_check", script_path)
    assert spec is not None and spec.loader is not None, f"cannot load {script_path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules["_arch_check"] = module
    spec.loader.exec_module(module)
    return module


def test_ratchet_baseline_is_committed() -> None:
    """scripts/arch_metrics.json must exist — the debt baseline is repo state."""
    arch_check = _load_arch_check()
    assert arch_check.RATCHET_BASELINE_PATH.exists(), (
        "scripts/arch_metrics.json is missing. Generate and commit it with: "
        "python scripts/arch_check.py --update-baseline"
    )


def test_defensive_surface_does_not_regress() -> None:
    """Engine defensive-guard metrics may not grow; @cites may not shrink."""
    arch_check = _load_arch_check()
    violations = arch_check.check_ratchet_metrics(SRC_ROOT)
    assert not violations, (
        "Architecture-debt ratchet violated "
        "(see docs/plans/target-architecture-migration.md, Phase 0):\n" + "\n".join(violations)
    )


def test_imports_point_downward() -> None:
    """contracts/engine/reporting/data/domain must not import upward layers."""
    arch_check = _load_arch_check()
    violations = arch_check.check_import_direction(SRC_ROOT)
    assert not violations, (
        "Import-direction violation — layering points downward; an inversion "
        "needs an IMPORT_DIRECTION_ALLOWLIST entry in scripts/arch_check.py "
        "with a migration-phase justification:\n" + "\n".join(violations)
    )


def test_no_empty_frame_sentinels_in_engine() -> None:
    """engine/** never constructs an empty LazyFrame to stand in for None."""
    arch_check = _load_arch_check()
    violations = arch_check.check_no_empty_frame_sentinels(SRC_ROOT)
    assert not violations, (
        "Empty-LazyFrame sentinel in engine/ — optional frames are None "
        "(migration Phase 2):\n" + "\n".join(violations)
    )


def test_no_polars_namespace_registrations() -> None:
    """src/rwa_calc never registers a Polars namespace — the pattern is extinct."""
    arch_check = _load_arch_check()
    violations = arch_check.check_no_polars_namespace_registrations(SRC_ROOT)
    assert not violations, (
        "Polars namespace registration found — the pattern is extinct "
        "(migration Phase 4); write plain typed functions composed via "
        ".pipe(fn, config):\n" + "\n".join(violations)
    )


def test_stage_registry_is_literal() -> None:
    """engine/registry.py is a literal, diff-reviewable StageSpec tuple."""
    arch_check = _load_arch_check()
    violations = arch_check.check_registry_is_literal(SRC_ROOT)
    assert not violations, (
        "engine/registry.py must stay a literal stage list — docstring, "
        "imports, the module logger, and a literal tuple of StageSpec(...) "
        "calls only (migration Phase 4):\n" + "\n".join(violations)
    )


def test_stage_anatomy_is_uniform() -> None:
    """Every registry StageSpec.fn is engine/stages/<stage>.run, and stages expose run."""
    arch_check = _load_arch_check()
    violations = arch_check.check_stage_anatomy(SRC_ROOT)
    assert not violations, (
        "Stage-anatomy violation — registry fns must be "
        "`<engine/stages/ module>.run` and stage packages must expose `run` "
        "from their __init__ (migration Phase 4):\n" + "\n".join(violations)
    )
