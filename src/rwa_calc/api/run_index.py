"""
Calculation run index — "has this exact calculation already been run?"

Pipeline position:
    UI calculation worker -> compute_fingerprint + register_calculation
    UI reconciliation form/submit -> compute_fingerprint + find_reusable
        -> CreditRiskCalc.reconcile(settings, calculation=...)

Key responsibilities:
- Fingerprint a calculation request: the run parameters plus a stat-based
  signature (relative path, size, mtime_ns) of every input file the loader
  would read. The signature makes reuse conservative by construction — any
  input file change, addition or removal produces a different fingerprint.
- Index completed, *successful* runs by fingerprint (latest wins) so callers
  can hand the cached ``CalculationResponse`` to ``reconcile(calculation=...)``
  instead of re-running the pipeline.
- Optionally persist the index (and outlive the process): with
  ``configure_persistence(state_dir)`` every registration is written through to
  ``<state_dir>/run_index.json`` and reloaded at the next startup, and
  ``run_cache_dir`` hands callers a per-run parquet home under
  ``<state_dir>/runs/`` so the cached results survive too.

Design notes:
- Callers compute the fingerprint *before* running the calculation and
  register it after success: if an input file changes mid-run, the stored
  (pre-run) signature no longer matches the on-disk state at lookup time and
  the stale run is never reused.
- The index is capped at ``MAX_INDEXED_RUNS`` (oldest evicted). Eviction only
  drops the index entry — run directories are never deleted mid-session (a
  ``/results/{run_id}`` page may still be serving them); orphaned directories
  under the runs root are swept at the NEXT ``configure_persistence`` call,
  when nothing can reference them.
- Freshness verification stays here; ``CreditRiskCalc.reconcile`` deliberately
  trusts the response it is handed (see api/service.py).
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import shutil
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from rwa_calc.api.models import CalculationResponse, SummaryStatistics

logger = logging.getLogger(__name__)

# File extension the loader reads, per data format.
_FORMAT_EXTENSIONS: dict[str, str] = {"parquet": ".parquet", "csv": ".csv"}

# Most runs kept in the index (and on disk when persistence is on). Oldest
# entries are evicted first; their run directories are reclaimed by the orphan
# sweep at the next startup.
MAX_INDEXED_RUNS = 10

_PERSIST_FILENAME = "run_index.json"
_RUNS_SUBDIR = "runs"


# =============================================================================
# Fingerprint
# =============================================================================


@dataclass(frozen=True, slots=True)
class CalculationFingerprint:
    """Identity of one calculation request over one on-disk data state.

    Attributes:
        data_path: Resolved absolute data directory (string form).
        framework: ``"CRR"`` or ``"BASEL_3_1"``.
        reporting_date: ISO date string.
        permission_mode: ``"standardised"`` or ``"irb"``.
        data_format: ``"parquet"`` or ``"csv"``.
        base_currency: Reporting currency code.
        eur_gbp_rate: Exact string form of the Decimal FX rate.
        data_signature: Sorted ``(relative_path, size, mtime_ns)`` per input
            file — stat-based, never content-hashed (cheap on large books).
    """

    data_path: str
    framework: str
    reporting_date: str
    permission_mode: str
    data_format: str
    base_currency: str
    eur_gbp_rate: str
    data_signature: tuple[tuple[str, int, int], ...]


def compute_fingerprint(
    *,
    data_path: str | Path,
    framework: str,
    reporting_date: date,
    permission_mode: str,
    data_format: str,
    base_currency: str = "GBP",
    eur_gbp_rate: Decimal = Decimal("0.8732"),
) -> CalculationFingerprint:
    """Fingerprint a calculation request against the current on-disk data.

    Defaults for ``base_currency`` / ``eur_gbp_rate`` mirror ``CreditRiskCalc``
    so callers that never expose those knobs (the UI forms) fingerprint
    identically to the runs they dispatch.
    """
    root = Path(data_path).expanduser().resolve()
    return CalculationFingerprint(
        data_path=str(root),
        framework=framework,
        reporting_date=reporting_date.isoformat(),
        permission_mode=permission_mode,
        data_format=data_format,
        base_currency=base_currency,
        eur_gbp_rate=str(eur_gbp_rate),
        data_signature=_data_signature(root, data_format),
    )


# =============================================================================
# Index (in-process, latest run wins per fingerprint)
# =============================================================================


@dataclass(frozen=True, slots=True)
class ReusableRun:
    """A cached run that is safe to reuse for the fingerprint it was found by."""

    run_id: str
    response: CalculationResponse
    completed_at: datetime


_INDEX: dict[CalculationFingerprint, ReusableRun] = {}

# When set (configure_persistence), registrations write through to
# <_STATE_DIR>/run_index.json and run_cache_dir() hands out per-run parquet
# homes under <_STATE_DIR>/runs/.
_STATE_DIR: Path | None = None


def register_calculation(
    fingerprint: CalculationFingerprint,
    run_id: str,
    response: CalculationResponse,
) -> None:
    """Index a completed run under its (pre-run) fingerprint; latest wins.

    Failed runs are ignored — an unsuccessful response must never be offered
    for reuse, so callers can register unconditionally. The index is capped at
    ``MAX_INDEXED_RUNS`` (oldest evicted, index entry only — see the module
    docstring for why run directories are reclaimed at startup instead).
    """
    if not response.success:
        return
    completed_at = response.performance.completed_at if response.performance else datetime.now()
    _INDEX[fingerprint] = ReusableRun(run_id=run_id, response=response, completed_at=completed_at)
    while len(_INDEX) > MAX_INDEXED_RUNS:
        oldest = min(_INDEX, key=lambda fp: _INDEX[fp].completed_at)
        evicted = _INDEX.pop(oldest)
        logger.debug("run index cap reached; evicted run %s", evicted.run_id)
    _save()
    logger.debug("registered run %s in run index", run_id)


def find_reusable(fingerprint: CalculationFingerprint) -> ReusableRun | None:
    """Return the cached run matching *fingerprint*, or None.

    The caller computes *fingerprint* from the current request parameters and
    the current on-disk data, so a hit means: identical parameters AND no input
    file changed since the indexed run started. The cached results parquet must
    also still exist — cache cleanup outside our control must degrade to a
    recompute, never an error.
    """
    entry = _INDEX.get(fingerprint)
    if entry is None:
        return None
    if not Path(entry.response.results_path).exists():
        logger.debug("run %s results parquet vanished; not reusable", entry.run_id)
        return None
    return entry


def find_latest_for_params(fingerprint: CalculationFingerprint) -> ReusableRun | None:
    """Return the latest run matching *fingerprint* on every field EXCEPT the
    data signature, or None.

    A hit here when ``find_reusable`` misses means "you have run this exact
    calculation before, but the input data changed since" — the UI shows a
    passive will-recompute note instead of a reuse option. Never reuse a run
    returned by this lookup.
    """
    candidates = [
        entry for fp, entry in _INDEX.items() if _params_key(fp) == _params_key(fingerprint)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda entry: entry.completed_at)


def entries() -> list[ReusableRun]:
    """Every indexed run, newest first (e.g. to re-register reloaded runs)."""
    return sorted(_INDEX.values(), key=lambda entry: entry.completed_at, reverse=True)


def clear() -> None:
    """Empty the index and disable persistence (test seam)."""
    global _STATE_DIR
    _INDEX.clear()
    _STATE_DIR = None


# =============================================================================
# Persistence (optional; the UI app configures it at startup)
# =============================================================================


def configure_persistence(state_dir: Path) -> None:
    """Persist the index under *state_dir* and reload previously saved runs.

    Loading is tolerant: a missing, corrupt or partially-valid
    ``run_index.json`` degrades to whatever entries can be reconstructed, and
    entries whose results parquet no longer exists are dropped. After loading,
    run directories under ``<state_dir>/runs/`` referenced by no index entry
    are deleted — they are unreachable (the in-process run registry did not
    survive the restart), so this is where evicted/failed runs are reclaimed.
    """
    global _STATE_DIR
    _STATE_DIR = state_dir
    for fingerprint, entry in _load(state_dir / _PERSIST_FILENAME):
        if not Path(entry.response.results_path).exists():
            logger.debug("dropping persisted run %s (results parquet gone)", entry.run_id)
            continue
        # An entry registered this session is fresher than its persisted twin.
        _INDEX.setdefault(fingerprint, entry)
    _sweep_orphan_run_dirs()
    _save()


def run_cache_dir(run_id: str) -> Path | None:
    """The persistent parquet home for *run_id*, or None when unconfigured.

    Callers pass this as ``CreditRiskCalc(cache_dir=...)`` so the run's cached
    results live under the state home (and survive a restart) instead of a
    per-process temp dir. None means "no persistence" — the caller falls back
    to the temp-dir default.
    """
    if _STATE_DIR is None:
        return None
    return _STATE_DIR / _RUNS_SUBDIR / run_id


# =============================================================================
# Private helpers
# =============================================================================


def _params_key(fp: CalculationFingerprint) -> tuple[str, ...]:
    """Every fingerprint field except the data signature, for signature-blind matching."""
    return (
        fp.data_path,
        fp.framework,
        fp.reporting_date,
        fp.permission_mode,
        fp.data_format,
        fp.base_currency,
        fp.eur_gbp_rate,
    )


def _data_signature(root: Path, data_format: str) -> tuple[tuple[str, int, int], ...]:
    """Stat every loader-relevant file under *root*: (relpath, size, mtime_ns).

    Stat-only by design — content-hashing a multi-GB portfolio to save one
    pipeline run defeats the purpose. A touch without a content change merely
    forces a recompute (conservative in the right direction). Files that vanish
    between ``rglob`` and ``stat`` are skipped, matching their imminent absence.
    """
    extension = _FORMAT_EXTENSIONS.get(data_format, ".parquet")
    if not root.is_dir():
        return ()
    entries: list[tuple[str, int, int]] = []
    for path in root.rglob(f"*{extension}"):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        entries.append((path.relative_to(root).as_posix(), stat.st_size, stat.st_mtime_ns))
    return tuple(sorted(entries))


def _sweep_orphan_run_dirs() -> None:
    """Delete run directories under the runs root referenced by no index entry.

    Only called from ``configure_persistence`` (startup): the in-process run
    registry is empty then, so an unreferenced directory is unreachable by any
    page or endpoint and safe to reclaim.
    """
    if _STATE_DIR is None:
        return
    runs_root = _STATE_DIR / _RUNS_SUBDIR
    if not runs_root.is_dir():
        return
    referenced = {Path(entry.response.results_path).resolve().parent for entry in _INDEX.values()}
    for child in runs_root.iterdir():
        if child.is_dir() and child.resolve() not in referenced:
            logger.debug("sweeping orphan run dir %s", child)
            shutil.rmtree(child, ignore_errors=True)


def _save() -> None:
    """Write the index atomically to the persist file (no-op when unconfigured).

    Best-effort: persistence must never break the calculation flow it rides on,
    so an IO failure is logged and swallowed — the worst case is that the next
    restart starts from an older (or empty) index.
    """
    if _STATE_DIR is None:
        return
    path = _STATE_DIR / _PERSIST_FILENAME
    raw = {
        "entries": [_entry_to_raw(fp, entry) for fp, entry in _INDEX.items()],
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_text(json.dumps(raw, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        logger.warning("could not persist the run index", exc_info=True)


def _load(path: Path) -> list[tuple[CalculationFingerprint, ReusableRun]]:
    """Read persisted entries, skipping anything unreadable.

    A missing file is the normal first-run case; a corrupt file or a malformed
    entry is logged and treated as absent — a bad index must only ever cost a
    recompute.
    """
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("ignoring unreadable run index at %s", path, exc_info=True)
        return []
    loaded: list[tuple[CalculationFingerprint, ReusableRun]] = []
    for entry_raw in raw.get("entries", []) if isinstance(raw, dict) else []:
        try:
            loaded.append(_entry_from_raw(entry_raw))
        except (KeyError, TypeError, ValueError, ArithmeticError):
            logger.warning("skipping malformed run-index entry", exc_info=True)
    return loaded


def _entry_to_raw(fingerprint: CalculationFingerprint, entry: ReusableRun) -> dict:
    """One JSON-friendly persisted entry (fingerprint + run identity + response)."""
    response = entry.response
    return {
        "fingerprint": dataclasses.asdict(fingerprint),
        "run_id": entry.run_id,
        "completed_at": entry.completed_at.isoformat(),
        "response": {
            "framework": response.framework,
            "reporting_date": response.reporting_date.isoformat(),
            "results_path": str(response.results_path),
            "summary_by_class_path": _opt_str(response.summary_by_class_path),
            "summary_by_approach_path": _opt_str(response.summary_by_approach_path),
            "summary_by_class_method_path": _opt_str(response.summary_by_class_method_path),
            "summary": {
                key: (str(value) if isinstance(value, Decimal) else value)
                for key, value in dataclasses.asdict(response.summary).items()
            },
        },
    }


def _entry_from_raw(raw: dict) -> tuple[CalculationFingerprint, ReusableRun]:
    """Reconstruct one persisted entry; raises on any malformed field.

    The response comes back without errors/performance — only successful runs
    are ever persisted, and the completion time lives on the entry itself. All
    string values in the persisted summary are Decimals by construction
    (``SummaryStatistics`` has no string fields).
    """
    fp_raw = raw["fingerprint"]
    fingerprint = CalculationFingerprint(
        data_path=fp_raw["data_path"],
        framework=fp_raw["framework"],
        reporting_date=fp_raw["reporting_date"],
        permission_mode=fp_raw["permission_mode"],
        data_format=fp_raw["data_format"],
        base_currency=fp_raw["base_currency"],
        eur_gbp_rate=fp_raw["eur_gbp_rate"],
        data_signature=tuple(
            (str(rel), int(size), int(mtime_ns)) for rel, size, mtime_ns in fp_raw["data_signature"]
        ),
    )
    resp_raw = raw["response"]
    # Decimal fields persist as strings (SummaryStatistics has no string fields,
    # so every string value round-trips back to Decimal); int/bool pass through.
    summary_kwargs: dict[str, Any] = {
        key: (Decimal(value) if isinstance(value, str) else value)
        for key, value in resp_raw["summary"].items()
    }
    summary = SummaryStatistics(**summary_kwargs)
    response = CalculationResponse(
        success=True,
        framework=resp_raw["framework"],
        reporting_date=date.fromisoformat(resp_raw["reporting_date"]),
        summary=summary,
        results_path=Path(resp_raw["results_path"]),
        summary_by_class_path=_opt_path(resp_raw["summary_by_class_path"]),
        summary_by_approach_path=_opt_path(resp_raw["summary_by_approach_path"]),
        summary_by_class_method_path=_opt_path(resp_raw["summary_by_class_method_path"]),
    )
    entry = ReusableRun(
        run_id=raw["run_id"],
        response=response,
        completed_at=datetime.fromisoformat(raw["completed_at"]),
    )
    return fingerprint, entry


def _opt_str(path: Path | None) -> str | None:
    """str() for an optional Path."""
    return None if path is None else str(path)


def _opt_path(raw: str | None) -> Path | None:
    """Path() for an optional persisted string."""
    return None if raw is None else Path(raw)
