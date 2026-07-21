"""
Unit tests: reconciliation sign-off workspace id under a reporting scope.

The workspace id keys the per-dataset sign-off store. Multi-entity reporting
folds the reporting scope into it so two scopes over one dataset get separate
stores — while an UN-scoped reconciliation keeps the exact pre-feature id, so
existing sign-off decisions survive the upgrade untouched.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from rwa_calc.ui.app.recon_signoff import workspace_id

_DATA = "/data/q1"
_LEGACY = "/data/legacy.csv"
_OUR_KEYS = ("loan_reference",)
_LEGACY_KEYS = ("LoanId",)


def _prechange_workspace_id(
    data_path: str, our_keys: tuple[str, ...], legacy_keys: tuple[str, ...], legacy_file: str
) -> str:
    """The exact hash the pre-multi-entity algorithm produced (the frozen contract).

    Reproduced here independently so the test pins the byte-for-byte identity an
    existing sign-off store depends on, rather than trusting the implementation
    it is meant to guard.
    """

    def _resolve(path: str) -> str:
        return str(Path(path).expanduser().resolve())

    canonical = "\n".join(
        [
            _resolve(data_path),
            _resolve(legacy_file),
            "|".join(our_keys),
            "|".join(legacy_keys),
        ]
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def test_unscoped_id_matches_prechange_algorithm() -> None:
    # Arrange / Act
    got = workspace_id(_DATA, _OUR_KEYS, _LEGACY_KEYS, _LEGACY)

    # Assert — an un-scoped reconciliation must hash exactly as it did before
    # multi-entity reporting existed, so existing decisions are not orphaned.
    assert got == _prechange_workspace_id(_DATA, _OUR_KEYS, _LEGACY_KEYS, _LEGACY)


def test_scope_changes_the_id() -> None:
    unscoped = workspace_id(_DATA, _OUR_KEYS, _LEGACY_KEYS, _LEGACY)
    scoped = workspace_id(
        _DATA,
        _OUR_KEYS,
        _LEGACY_KEYS,
        _LEGACY,
        reporting_entity="ACME",
        reporting_basis="consolidated",
    )
    assert scoped != unscoped


def test_different_scopes_are_distinct() -> None:
    a = workspace_id(
        _DATA,
        _OUR_KEYS,
        _LEGACY_KEYS,
        _LEGACY,
        reporting_entity="ACME",
        reporting_basis="consolidated",
    )
    b = workspace_id(
        _DATA,
        _OUR_KEYS,
        _LEGACY_KEYS,
        _LEGACY,
        reporting_entity="ACME",
        reporting_basis="individual",
    )
    c = workspace_id(
        _DATA,
        _OUR_KEYS,
        _LEGACY_KEYS,
        _LEGACY,
        reporting_entity="BETA",
        reporting_basis="consolidated",
    )
    assert len({a, b, c}) == 3


def test_basis_only_scope_is_distinct_from_unscoped() -> None:
    # A basis with no entity is still a scope, so it must not collide with the
    # unscoped store (the append branch fires on either field being set).
    unscoped = workspace_id(_DATA, _OUR_KEYS, _LEGACY_KEYS, _LEGACY)
    basis_only = workspace_id(
        _DATA, _OUR_KEYS, _LEGACY_KEYS, _LEGACY, reporting_basis="consolidated"
    )
    assert basis_only != unscoped
