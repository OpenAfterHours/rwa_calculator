"""
Rulebook audit — pack manifest serialisation and diff.

Pipeline position:
    A read-only sibling of ``rulebook/resolve.py``. ``resolve`` produces a
    content-hashed ``ResolvedRulepack``; this module serialises it to a stable
    audit manifest and diffs two such manifests. The per-run pipeline manifest
    (``engine/pipeline.py::_persist_audit_artifacts``) embeds
    :func:`serialize_pack` output under its ``rulepack`` key, so every run
    records exactly which regime data produced it; the ``rulepack-diff``
    console script diffs two snapshots for change review.

Key responsibilities:
- ``serialize_pack`` — the single audit serialiser (delegates to
  ``ResolvedRulepack.as_manifest``; values stay Decimal-as-string, never
  floated — the Decimal->float boundary is ``rulebook/compile.py`` only).
- ``diff_packs`` — a pure dict-in/dict-out diff bucketing entries into
  added / removed / changed_value / changed_citation / changed_kind.
- ``main`` — the ``rulepack-diff a.json b.json`` CLI (non-zero exit on a
  non-empty diff, so CI can gate on unexpected regime-data drift).

References:
- docs/plans/target-architecture-migration.md (Phase 5 S12 — manifest +
  ``rulepack diff``; versioned, citation-carrying, content-hashed regime data)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, cast

from rwa_calc.rulebook.resolve import resolve

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from rwa_calc.rulebook.resolve import ResolvedRulepack


# =============================================================================
# SERIALISER — the single audit entry point onto a resolved pack
# =============================================================================


def serialize_pack(pack: ResolvedRulepack) -> dict[str, object]:
    """Return the stable audit manifest for a resolved pack.

    The single audit serialiser — delegates to
    :meth:`ResolvedRulepack.as_manifest` so the entry walk lives in one place
    (``id`` / ``content_hash`` / per-entry ``name`` + ``kind`` + ``citation`` +
    ``value``). Values stay Decimal-as-string; there is no ``float(...)`` here
    (that boundary belongs to ``rulebook/compile.py``).
    """
    return pack.as_manifest()


# =============================================================================
# DIFF — compare two serialised pack manifests
# =============================================================================


def diff_packs(before: dict[str, object], after: dict[str, object]) -> dict[str, list]:
    """Diff two pack manifests (as produced by :func:`serialize_pack`).

    Buckets entry-level changes by name: ``added`` (in ``after`` only),
    ``removed`` (in ``before`` only), and ``changed_value`` /
    ``changed_citation`` / ``changed_kind`` (present in both, that field
    differs). The diff is order-insensitive (manifests sort entries by name)
    and pure — dict in, dict out, no I/O.
    """
    before_by_name = {entry["name"]: entry for entry in _entries(before)}
    after_by_name = {entry["name"]: entry for entry in _entries(after)}

    added = [after_by_name[name] for name in sorted(after_by_name.keys() - before_by_name.keys())]
    removed = [
        before_by_name[name] for name in sorted(before_by_name.keys() - after_by_name.keys())
    ]
    changed_value: list[dict] = []
    changed_citation: list[dict] = []
    changed_kind: list[dict] = []
    for name in sorted(before_by_name.keys() & after_by_name.keys()):
        b = before_by_name[name]
        a = after_by_name[name]
        if b["kind"] != a["kind"]:
            changed_kind.append({"name": name, "before": b["kind"], "after": a["kind"]})
        if b["citation"] != a["citation"]:
            changed_citation.append({"name": name, "before": b["citation"], "after": a["citation"]})
        if b["value"] != a["value"]:
            changed_value.append({"name": name, "before": b["value"], "after": a["value"]})
    return {
        "added": added,
        "removed": removed,
        "changed_value": changed_value,
        "changed_citation": changed_citation,
        "changed_kind": changed_kind,
    }


def diff_is_empty(diff: dict[str, list]) -> bool:
    """True when a :func:`diff_packs` result reports no changes."""
    return not any(diff.values())


# =============================================================================
# PACK CITATION INDEX — citation -> entries (the watchfire-matrix analogue)
# =============================================================================


def pack_citation_index(
    reporting_date: date, regimes: Sequence[str] = ("crr", "b31")
) -> dict[str, list[str]]:
    """Map each distinct pack citation string to the sorted entry names citing it.

    The pack-data analogue of watchfire's article->function matrix: resolves
    each regime's pack and groups entry names by ``str(entry.citation)``. The
    entry set is date-invariant — resolution merges all pack entries regardless
    of date; only ``Schedule`` *values* depend on the date — so any valid
    ``reporting_date`` yields the same index. Consumed by the arch_check pack-
    citation gate and the citation-coverage contract test.
    """
    index: dict[str, set[str]] = {}
    for regime in regimes:
        for name, entry in resolve(regime, reporting_date).entries.items():
            index.setdefault(str(entry.citation), set()).add(name)
    return {citation: sorted(names) for citation, names in sorted(index.items())}


# =============================================================================
# CLI — ``rulepack-diff a.json b.json``
# =============================================================================


def main(argv: Sequence[str] | None = None) -> int:
    """``rulepack-diff a.json b.json`` — diff two persisted pack manifests.

    Reads two manifest JSON files (each a :func:`serialize_pack` snapshot, or a
    full pipeline ``manifest.json`` carrying the pack under its ``rulepack``
    key), writes the bucketed diff as JSON to stdout, and returns a non-zero
    exit code when the diff is non-empty — so CI can gate on unexpected
    regime-data drift.
    """
    parser = argparse.ArgumentParser(
        prog="rulepack-diff",
        description="Diff two resolved-rulepack audit manifests.",
    )
    parser.add_argument("before", help="path to the baseline manifest JSON")
    parser.add_argument("after", help="path to the candidate manifest JSON")
    args = parser.parse_args(argv)

    diff = diff_packs(_load_manifest(args.before), _load_manifest(args.after))
    sys.stdout.write(json.dumps(diff, indent=2, sort_keys=True) + "\n")
    return 0 if diff_is_empty(diff) else 1


# =============================================================================
# PRIVATE HELPERS
# =============================================================================


def _entries(manifest: dict[str, object]) -> list[dict]:
    """Return the entry list of a pack manifest (empty list if absent)."""
    entries = manifest.get("entries", [])
    if not isinstance(entries, list):
        raise TypeError("pack manifest 'entries' must be a list")
    # JSON / as_manifest boundary: entries are entry dicts. The isinstance check
    # guards the list shape; the element type is asserted by the manifest contract.
    return cast("list[dict]", entries)


def _load_manifest(path: str) -> dict[str, object]:
    """Load a manifest JSON file, unwrapping a pipeline ``manifest.json``.

    Accepts either a bare pack manifest (:func:`serialize_pack` output, with an
    ``entries`` key) or a full pipeline ``manifest.json`` (with the pack under
    its ``rulepack`` key) so the CLI diffs persisted run manifests directly.

    The operator-supplied ``path`` is validated by :func:`_safe_manifest_path`
    before any filesystem access; the canonicalised :class:`~pathlib.Path` it
    returns — never the raw argument — is what reaches the ``open`` sink.
    """
    safe_path = _safe_manifest_path(path)
    with open(safe_path, encoding="utf-8") as handle:
        data = json.load(handle)
    if "entries" not in data and isinstance(data.get("rulepack"), dict):
        return data["rulepack"]
    return data


def _safe_manifest_path(path: str) -> Path:
    """Canonicalise and validate an operator-supplied manifest path before I/O.

    Resolves ``path`` to an absolute, canonical form (collapsing ``..`` and
    symlinks) and requires it to name an existing regular ``.json`` file, so a
    malformed or hostile CLI argument is rejected with a clear ``error: ...``
    message *before* :func:`_load_manifest` opens it. The validated value flows
    to the filesystem sink in place of the raw argument — the path-injection
    analogue of the ``error: ...`` fast-fail sanitiser convention used at the
    project's other CLI boundaries (e.g. ``scripts/_validate.py``).

    Containment to a fixed base directory is intentionally *not* enforced:
    ``rulepack-diff`` legitimately diffs manifests written to operator-chosen
    run-output / CI-artifact directories (the per-run ``manifest.json`` under
    ``config.audit_cache_dir``), which may sit anywhere on disk.
    """
    resolved = Path(path).resolve()
    if resolved.suffix.lower() != ".json":
        raise SystemExit(f"error: manifest path must be a .json file: {path!r}")
    if not resolved.is_file():
        raise SystemExit(f"error: manifest file not found: {path!r}")
    return resolved


if __name__ == "__main__":
    raise SystemExit(main())
