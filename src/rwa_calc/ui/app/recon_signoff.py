"""
Per-dataset sign-off store for reconciliation differences.

Pipeline position:
    POST /reconciliation/{recon_id}/signoff -> upsert_decision / clear_decision
    GET  /reconciliation/{recon_id}/rows|loan -> load_decisions -> annotate views

Key responsibilities:
- Persist an analyst's *accept* / *reject* decision (plus a free-text reason) for
  each reconciliation row, keyed by the deterministic ``_recon_key`` so a decision
  survives an app restart *and* a re-run of the same dataset (the key is stable).
- Scope decisions to a *workspace* — one dataset + mapping — via a stable hash, so
  several reconciled datasets coexist in one store file without colliding.

The store file lives at ``$RWA_STATE_DIR/reconciliation_signoff.json`` when that
env var is set (the test seam and the packaged-app override), else
``~/.rwa_calc/reconciliation_signoff.json``. Saving never raises and loading never
raises — a save failure must not break a sign-off click, and a missing or corrupt
file simply yields an empty decision set. Writes are atomic (temp file +
``os.replace``) because this is data the analyst is actively building.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

STATE_DIR_ENV_VAR = "RWA_STATE_DIR"
_STATE_FILENAME = "reconciliation_signoff.json"

# The disposition an analyst can record for one reconciliation row. ``open`` is
# the implicit, unstored default (no decision yet); only the two terminal
# dispositions below are ever persisted.
Status = Literal["accepted", "rejected"]
STATUS_OPEN = "open"
_VALID_STATUSES: frozenset[str] = frozenset({"accepted", "rejected"})


@dataclass(frozen=True, slots=True)
class Decision:
    """One analyst disposition of a reconciliation row.

    ``status`` is the terminal disposition (accepted / rejected); ``reason`` is the
    analyst's free-text justification (may be empty for a quick *accept*);
    ``decided_at`` is an ISO-8601 local timestamp, second precision; ``fingerprint``
    captures *what the difference looked like* when it was signed off, so a later
    re-run can detect that the difference has **moved** (and re-flag the decision as
    stale) rather than waving a changed difference through under an old approval. An
    empty fingerprint (a pre-fingerprint decision) is treated as "cannot tell" — it
    never goes stale.
    """

    status: Status
    reason: str
    decided_at: str
    fingerprint: str = ""


def workspace_id(
    data_path: str,
    our_keys: Sequence[str],
    legacy_keys: Sequence[str],
    legacy_file: str | Path,
    *,
    reporting_entity: str | None = None,
    reporting_basis: str | None = None,
) -> str:
    """A short, stable id for the dataset+mapping a reconciliation reconciles.

    Built from the *resolved* data path, the resolved legacy file path and the
    join-key tuples — the semantic identity of a reconciliation — so re-running the
    same data (even after a source fix, or an app restart) maps to the same stored
    decisions. Derived from the parsed mapping, never the raw TOML text, so a
    comment / whitespace edit in the mapping editor does not orphan decisions.

    A multi-entity reporting scope (``reporting_entity`` / ``reporting_basis``)
    is folded in so two scopes over one dataset get separate sign-off stores.
    An UN-scoped reconciliation (both None — the only shape before multi-entity
    reporting existed) appends nothing, so its id is byte-identical to the
    pre-feature hash and existing sign-off decisions are preserved.
    """
    parts = [
        _resolve(data_path),
        _resolve(legacy_file),
        "|".join(our_keys),
        "|".join(legacy_keys),
    ]
    if reporting_entity is not None or reporting_basis is not None:
        parts.append(reporting_entity or "")
        parts.append(reporting_basis or "")
    canonical = "\n".join(parts)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def load_decisions(workspace: str) -> dict[str, Decision]:
    """Return every stored decision for *workspace*, keyed by ``_recon_key``.

    A missing / corrupt store or an unknown workspace yields an empty dict; an
    individual decision that fails validation is skipped rather than failing the
    whole load, so one bad record never blanks the worklist.
    """
    entry = _load_store().get(workspace)
    if not isinstance(entry, dict):
        return {}
    raw_decisions = entry.get("decisions")
    if not isinstance(raw_decisions, dict):
        return {}
    out: dict[str, Decision] = {}
    for key, rec in raw_decisions.items():
        decision = _decision_from_raw(rec)
        if decision is not None:
            out[str(key)] = decision
    return out


def upsert_decision(
    workspace: str,
    data_path: str,
    recon_key: str,
    status: str,
    reason: str,
    fingerprint: str = "",
) -> None:
    """Record (or overwrite) the decision for one ``_recon_key`` in *workspace*.

    ``status`` must be ``"accepted"`` or ``"rejected"`` (a programming error
    otherwise — the route validates first). ``fingerprint`` snapshots the current
    shape of the difference so a later re-run can tell whether it has moved. The IO
    is best-effort: a write failure is logged and swallowed so a sign-off click can
    never surface a 500.
    """
    if status not in _VALID_STATUSES:
        raise ValueError(f"status must be one of {sorted(_VALID_STATUSES)}, got {status!r}")
    try:
        store = _load_store()
        entry = store.get(workspace)
        if not isinstance(entry, dict):
            entry = {}
        decisions = entry.get("decisions")
        if not isinstance(decisions, dict):
            decisions = {}
        decisions[recon_key] = {
            "status": status,
            "reason": reason,
            "fingerprint": fingerprint,
            "decided_at": datetime.now().isoformat(timespec="seconds"),  # noqa: DTZ005 - local wall-clock is intended for an analyst-facing stamp
        }
        entry["data_path"] = data_path
        entry["decisions"] = decisions
        store[workspace] = entry
        _save_store(store)
    except (OSError, TypeError):
        logger.warning("could not save reconciliation sign-off", exc_info=True)


def clear_decision(workspace: str, recon_key: str) -> None:
    """Forget the decision for one ``_recon_key`` (the *reopen* action).

    A missing workspace / key is a no-op; any IO error is logged and swallowed so
    "reopen" can never surface an error to the page.
    """
    try:
        store = _load_store()
        entry = store.get(workspace)
        if isinstance(entry, dict) and isinstance(entry.get("decisions"), dict):
            entry["decisions"].pop(recon_key, None)
            _save_store(store)
    except (OSError, TypeError):
        logger.warning("could not clear reconciliation sign-off", exc_info=True)


def clear_all_decisions(workspace: str) -> None:
    """Forget *every* decision for a workspace (the "clear all approvals" action).

    Drops the whole workspace entry; a missing workspace is a no-op and any IO error
    is logged and swallowed so the action can never surface an error to the page.
    """
    try:
        store = _load_store()
        if workspace in store:
            store.pop(workspace, None)
            _save_store(store)
    except (OSError, TypeError):
        logger.warning("could not clear all reconciliation sign-offs", exc_info=True)


# =============================================================================
# Private helpers
# =============================================================================


def _decision_from_raw(rec: object) -> Decision | None:
    """Validate one persisted record into a ``Decision`` (or ``None`` if invalid)."""
    if not isinstance(rec, dict):
        return None
    status = rec.get("status")
    reason = rec.get("reason", "")
    decided_at = rec.get("decided_at", "")
    fingerprint = rec.get("fingerprint", "")
    if (
        status not in _VALID_STATUSES
        or not isinstance(reason, str)
        or not isinstance(decided_at, str)
        or not isinstance(fingerprint, str)
    ):
        return None
    return Decision(
        status=cast("Status", status),
        reason=reason,
        decided_at=decided_at,
        fingerprint=fingerprint,
    )


def _load_store() -> dict:
    """Read the whole sign-off store; an absent / corrupt file yields ``{}``."""
    path = _state_file()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("ignoring unreadable reconciliation sign-off store", exc_info=True)
        return {}
    return raw if isinstance(raw, dict) else {}


def _save_store(store: dict) -> None:
    """Persist the whole store atomically (temp file + ``os.replace``)."""
    path = _state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(store, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _resolve(path: str | Path) -> str:
    """Normalise a path for stable hashing (absolute, ``~`` expanded)."""
    return str(Path(path).expanduser().resolve())


def _state_dir() -> Path:
    """The directory holding the store file (env override, else ``~/.rwa_calc``)."""
    override = os.environ.get(STATE_DIR_ENV_VAR)
    if override:
        return Path(override)
    return Path.home() / ".rwa_calc"


def _state_file() -> Path:
    """Absolute path to the reconciliation sign-off JSON store."""
    return _state_dir() / _STATE_FILENAME
