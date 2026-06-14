"""
Unit tests for ``rwa_calc.rulebook.audit`` — pack manifest serialise + diff.

Covers:
- ``serialize_pack`` is the single serialiser (== ``ResolvedRulepack.as_manifest``).
- ``diff_packs`` buckets every change kind (added / removed / changed_value /
  changed_citation / changed_kind) and reports empty for identical packs.
- two distinct regimes produce a non-empty diff (the real CRR-vs-B31 case).
- ``main`` writes the diff JSON and returns a non-zero exit only on a non-empty
  diff (the CI drift-gate contract), including unwrapping a pipeline
  ``manifest.json`` that carries the pack under its ``rulepack`` key.
"""

from __future__ import annotations

import json
from datetime import date
from typing import TYPE_CHECKING

from rwa_calc.rulebook.audit import diff_is_empty, diff_packs, main, serialize_pack
from rwa_calc.rulebook.resolve import resolve

if TYPE_CHECKING:
    from pathlib import Path

_REPORTING_DATE = date(2026, 1, 1)


def _manifest(*entries: dict) -> dict:
    """A minimal pack-manifest shell wrapping the given entry dicts."""
    return {
        "id": "test@2026-01-01",
        "regime_id": "test",
        "reporting_date": "2026-01-01",
        "content_hash": "deadbeef",
        "entries": list(entries),
    }


def _entry(
    name: str, *, kind: str = "ScalarParam", citation: str = "CRR Art. 1", value="1"
) -> dict:
    return {"name": name, "kind": kind, "citation": citation, "value": value}


# --- serialize_pack ---------------------------------------------------------


def test_serialize_pack_delegates_to_as_manifest() -> None:
    """serialize_pack is a thin delegate, not a second serialiser."""
    pack = resolve("crr", _REPORTING_DATE)

    assert serialize_pack(pack) == pack.as_manifest()


# --- diff_packs -------------------------------------------------------------


def test_diff_identical_manifests_is_empty() -> None:
    """A pack diffed against itself reports no changes in any bucket."""
    pack = resolve("crr", _REPORTING_DATE)
    snapshot = serialize_pack(pack)

    diff = diff_packs(snapshot, snapshot)

    assert diff_is_empty(diff)
    assert diff == {
        "added": [],
        "removed": [],
        "changed_value": [],
        "changed_citation": [],
        "changed_kind": [],
    }


def test_diff_buckets_each_change_kind() -> None:
    """Each change kind lands in exactly its own bucket."""
    before = _manifest(
        _entry("stays"),
        _entry("gone"),
        _entry("v", value="1"),
        _entry("c", citation="CRR Art. 1"),
        _entry("k", kind="ScalarParam"),
    )
    after = _manifest(
        _entry("stays"),
        _entry("new"),
        _entry("v", value="2"),
        _entry("c", citation="CRR Art. 2"),
        _entry("k", kind="Feature"),
    )

    diff = diff_packs(before, after)

    assert [e["name"] for e in diff["added"]] == ["new"]
    assert [e["name"] for e in diff["removed"]] == ["gone"]
    assert diff["changed_value"] == [{"name": "v", "before": "1", "after": "2"}]
    assert diff["changed_citation"] == [
        {"name": "c", "before": "CRR Art. 1", "after": "CRR Art. 2"}
    ]
    assert diff["changed_kind"] == [{"name": "k", "before": "ScalarParam", "after": "Feature"}]


def test_diff_crr_vs_b31_is_non_empty() -> None:
    """Two genuinely different regimes produce a non-empty diff."""
    crr = serialize_pack(resolve("crr", _REPORTING_DATE))
    b31 = serialize_pack(resolve("b31", _REPORTING_DATE))

    diff = diff_packs(crr, b31)

    assert not diff_is_empty(diff)
    # irb_scaling_factor is 1.06 (CRR) vs 1.0 (B31) — a value change both packs carry.
    changed_names = {e["name"] for e in diff["changed_value"]}
    assert "irb_scaling_factor" in changed_names


# --- main / CLI -------------------------------------------------------------


def test_main_returns_zero_for_identical_snapshots(tmp_path: Path) -> None:
    """Identical manifests → empty diff → exit 0 (no drift)."""
    snapshot = serialize_pack(resolve("crr", _REPORTING_DATE))
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text(json.dumps(snapshot), encoding="utf-8")
    b.write_text(json.dumps(snapshot), encoding="utf-8")

    assert main([str(a), str(b)]) == 0


def test_main_returns_nonzero_for_differing_snapshots(tmp_path: Path) -> None:
    """Different manifests → non-empty diff → non-zero exit (CI drift gate)."""
    a = tmp_path / "crr.json"
    b = tmp_path / "b31.json"
    a.write_text(json.dumps(serialize_pack(resolve("crr", _REPORTING_DATE))), encoding="utf-8")
    b.write_text(json.dumps(serialize_pack(resolve("b31", _REPORTING_DATE))), encoding="utf-8")

    assert main([str(a), str(b)]) == 1


def test_main_unwraps_pipeline_manifest_rulepack_key(tmp_path: Path) -> None:
    """The CLI diffs a full pipeline manifest.json by unwrapping its rulepack key."""
    snapshot = serialize_pack(resolve("crr", _REPORTING_DATE))
    bare = tmp_path / "bare.json"
    wrapped = tmp_path / "manifest.json"
    bare.write_text(json.dumps(snapshot), encoding="utf-8")
    wrapped.write_text(json.dumps({"run_id": "x", "rulepack": snapshot}), encoding="utf-8")

    # Bare pack manifest vs the same pack wrapped in a pipeline manifest → identical.
    assert main([str(bare), str(wrapped)]) == 0
