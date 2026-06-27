"""
Last-run persistence for the calculator form.

Pipeline position:
    POST /calculate (success) -> save_calculator_state(...)
    GET  /calculator          -> load_calculator_state() -> form pre-fill

Key responsibilities:
- Remember the inputs of the last *completed* calculation so the form opens
  pre-filled and the user never re-types the data path, framework, mode, format,
  reporting date or the chosen output folder/formats.
- Store the form fields verbatim as JSON in a per-user state file. The
  multi-select ``output_formats`` is kept as a comma-joined string so every field
  is a plain string (mirrors the reconciliation last-run invariant).

The state file lives at ``$RWA_STATE_DIR/calculator_last_run.json`` when that env
var is set (the test seam and the packaged-app override), else
``~/.rwa_calc/calculator_last_run.json``. Saving never raises and loading never
raises — a save failure must not break a run, and a missing or corrupt file
simply falls back to the form defaults.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

STATE_DIR_ENV_VAR = "RWA_STATE_DIR"
_STATE_FILENAME = "calculator_last_run.json"


@dataclass(frozen=True, slots=True)
class CalculatorFormState:
    """The calculator form fields, captured verbatim as strings."""

    data_path: str
    reporting_date: str
    framework: str
    permission_mode: str
    data_format: str
    output_folder: str
    output_formats: str

    @property
    def formats(self) -> list[str]:
        """The comma-encoded ``output_formats`` as a list (empty -> [])."""
        return [fmt for fmt in self.output_formats.split(",") if fmt]


def save_calculator_state(state: CalculatorFormState) -> None:
    """Persist *state* to the per-user JSON file; swallow any IO error.

    A failure here must never break a calculation run, so the whole body is
    guarded — the worst case is that the next form is not pre-filled.
    """
    try:
        path = _state_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dataclasses.asdict(state), indent=2), encoding="utf-8")
    except (OSError, TypeError):
        logger.warning("could not save calculator last-run state", exc_info=True)


def load_calculator_state() -> CalculatorFormState | None:
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
        field_names = [f.name for f in dataclasses.fields(CalculatorFormState)]
        values = {name: raw[name] for name in field_names}
        if not all(isinstance(v, str) for v in values.values()):
            raise TypeError("calculator state fields must be strings")
        return CalculatorFormState(**values)
    except (OSError, ValueError, TypeError, KeyError):
        logger.warning("ignoring unreadable calculator last-run state", exc_info=True)
        return None


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
    """Absolute path to the calculator last-run JSON file."""
    return _state_dir() / _STATE_FILENAME
