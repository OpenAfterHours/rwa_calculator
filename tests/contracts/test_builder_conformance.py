"""
Test-lint: pipeline bundles are constructed via the contract-derived builders.

Direct ``RawDataBundle(...)`` / ``ResolvedHierarchyBundle(...)`` /
``ClassifiedExposuresBundle(...)`` / ``CRMAdjustedBundle(...)`` /
``AggregatedResultBundle(...)`` / ``CounterpartyLookup(...)`` construction
in test files bypasses the edge seals and historically made the engine's
effective input domain the union of fixture shapes (the root cause behind
the Phase 3 guard debt). The sanctioned construction paths are the
builders in ``tests/fixtures/raw_bundle.py`` and
``tests/fixtures/resolved_bundle.py``, which seal every frame exactly as
the producing stage does.

The post-migration census is ZERO, so this is a hard invariant rather
than a ratchet (the Phase 8 hard ban, achieved at the end of Phase 3).
A test that genuinely needs raw construction (bundle/registry mechanics)
belongs in one of the exempt files below, with the registry monkeypatch
pattern from ``test_edge_contracts.py::TestBundleBrandValidation``.

References:
- docs/plans/target-architecture-migration.md (Phase 3)
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

_CONSTRUCTOR_TOKENS = (
    "RawDataBundle(",
    "ResolvedHierarchyBundle(",
    "ClassifiedExposuresBundle(",
    "CRMAdjustedBundle(",
    "AggregatedResultBundle(",
    "CounterpartyLookup(",
    # Phase 4: stage-fold contexts are built via tests/fixtures/context.py
    # so the orchestration artifact channels (errors, components,
    # securitisation lookup) always carry their canonical defaults.
    "PipelineContext(",
)

# The builders themselves, and files whose PURPOSE is pinning bundle /
# registry mechanics on raw construction.
_EXEMPT_PREFIXES = ("tests/fixtures/",)
_EXEMPT_FILES = {
    "tests/contracts/test_edge_contracts.py",
    "tests/contracts/test_aggregated_bundle_validation.py",
    # Pins PipelineContext construction mechanics themselves.
    "tests/unit/contracts/test_pipeline_context.py",
    # This file: the token tuple below would count itself.
    "tests/contracts/test_builder_conformance.py",
}


def _tracked_test_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "tests/"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=True,
    ).stdout.splitlines()
    return [
        f
        for f in out
        if f.endswith(".py") and not f.startswith(_EXEMPT_PREFIXES) and f not in _EXEMPT_FILES
    ]


def test_no_direct_bundle_construction_in_tests() -> None:
    violations: list[str] = []
    for rel in _tracked_test_files():
        text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="ignore")
        for token in _CONSTRUCTOR_TOKENS:
            count = text.count(token)
            if count:
                violations.append(
                    f"  {rel}: {count}x {token}...) — use the contract-derived "
                    "builder (tests/fixtures/raw_bundle.py / resolved_bundle.py) "
                    "or add a justified exemption here"
                )
    assert not violations, "direct bundle construction in tests:\n" + "\n".join(violations)
