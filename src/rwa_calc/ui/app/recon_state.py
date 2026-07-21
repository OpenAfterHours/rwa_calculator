"""
Last-run persistence for the reconciliation form.

Pipeline position:
    POST /reconciliation (success) -> save_last_run(...)
    GET  /reconciliation           -> load_last_run() -> form pre-fill

Key responsibilities:
- Remember the inputs of the last *completed* reconciliation so the form opens
  pre-filled and the analyst never re-types the data path, framework, mode,
  format, reporting date or the (commented) legacy-mapping TOML.
- Store the six form fields verbatim as JSON in a per-user state file. The raw
  ``mapping_toml`` string is kept as-typed (comments and the embedded
  ``legacy_file`` / keys survive) rather than round-tripped through
  ``ReconciliationSettings``.

The state file lives at ``$RWA_STATE_DIR/reconciliation_last_run.json`` when that
env var is set (the test seam and the packaged-app override), else
``~/.rwa_calc/reconciliation_last_run.json``. Saving never raises and loading
never raises — a save failure must not break a run, and a missing or corrupt
file simply falls back to the form defaults.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

STATE_DIR_ENV_VAR = "RWA_STATE_DIR"
_STATE_FILENAME = "reconciliation_last_run.json"


@dataclass(frozen=True, slots=True)
class ReconciliationFormState:
    """The reconciliation form fields, captured verbatim as strings.

    ``reporting_entity`` / ``reporting_basis`` are the optional multi-entity
    reporting scope (blank when unscoped); they carry defaults so a state file
    written before these fields existed still loads (the scope opens blank).
    """

    data_path: str
    reporting_date: str
    framework: str
    permission_mode: str
    data_format: str
    mapping_toml: str
    reporting_entity: str = ""
    reporting_basis: str = ""


def save_last_run(state: ReconciliationFormState) -> None:
    """Persist *state* to the per-user JSON file; swallow any IO error.

    A failure here must never break a reconciliation run, so the whole body is
    guarded — the worst case is that the next form is not pre-filled.
    """
    try:
        path = _state_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dataclasses.asdict(state), indent=2), encoding="utf-8")
    except (OSError, TypeError):
        logger.warning("could not save reconciliation last-run state", exc_info=True)


def load_last_run() -> ReconciliationFormState | None:
    """Return the saved form state, or ``None`` if absent, corrupt or partial.

    A missing file is the normal first-run case (no warning). A corrupt or
    partial file is logged at WARNING and treated as absent so the form falls
    back to its defaults rather than failing.
    """
    path = _state_file()
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        values = _read_fields(raw)
        if not all(isinstance(v, str) for v in values.values()):
            raise TypeError("reconciliation state fields must be strings")
        return ReconciliationFormState(**values)
    except (OSError, ValueError, TypeError, KeyError):
        logger.warning("ignoring unreadable reconciliation last-run state", exc_info=True)
        return None


def _read_fields(raw: dict) -> dict[str, Any]:
    """Pull each dataclass field from *raw*, tolerating absent defaulted fields.

    A field with a default (the multi-entity scope fields, added later) is read
    with ``.get`` and falls back to that default, so an older state file loads
    without the new keys. A field with no default stays strict (a ``KeyError``
    bubbles up and the file is treated as unreadable), preserving the original
    all-or-nothing contract for the core form fields.
    """
    values: dict[str, Any] = {}
    for field in dataclasses.fields(ReconciliationFormState):
        if field.default is not dataclasses.MISSING:
            values[field.name] = raw.get(field.name, field.default)
        else:
            values[field.name] = raw[field.name]
    return values


def clear_last_run() -> None:
    """Forget the saved run so the form returns to its built-in defaults.

    A missing file is fine (nothing to forget) and any IO error is swallowed —
    "reset to defaults" must never surface an error to the page.
    """
    try:
        _state_file().unlink(missing_ok=True)
    except OSError:
        logger.warning("could not clear reconciliation last-run state", exc_info=True)


# =============================================================================
# Private helpers
# =============================================================================


def _state_dir() -> Path:
    """The directory holding the state file (env override, else ``~/.rwa_calc``)."""
    override = os.environ.get(STATE_DIR_ENV_VAR)
    if override:
        return Path(override)
    return Path.home() / ".rwa_calc"


def _state_file() -> Path:
    """Absolute path to the reconciliation last-run JSON file."""
    return _state_dir() / _STATE_FILENAME
