"""
API-layer glue for parallel-run reconciliation.

Provides the analyst-facing entry points that surround the pure
``analysis.reconciliation.ReconciliationRunner``:

- ``ReconciliationSettings``: legacy file + format + column mapping + top-N.
- ``load_reconciliation_config`` / ``dump_reconciliation_config``: TOML <-> settings
  using the stdlib ``tomllib`` (read) and a small hand-rolled writer (no new
  dependency; consistent with the project's existing ``.toml`` config).
- ``LegacyOutputLoader``: scans a legacy parquet/CSV and maps its columns onto our
  canonical ``legacy_<component>`` columns (applying scale / unit conversion),
  keyed by the declared legacy key columns.

The loader maps only the columns present in the file; any mapped component whose
column is absent is left out and surfaced as a non-fatal REC001 warning by the
runner (single authority), so reconciliation degrades gracefully.
"""

from __future__ import annotations

import logging
import math
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import polars as pl

from rwa_calc.analysis.recon_registry import (
    RECONCILABLE_COMPONENTS_BY_NAME,
    ComponentMapping,
    LegacyColumnMapping,
)

logger = logging.getLogger(__name__)

_DEFAULT_TOP_N = 50


@dataclass(frozen=True)
class ReconciliationSettings:
    """Everything needed to run a reconciliation from a config file.

    Attributes:
        legacy_file: Path to the legacy calculator's output file.
        mapping: Column/key mapping and per-component tolerances.
        legacy_format: ``"csv"`` or ``"parquet"``.
        top_n: Number of largest breaks to surface (reserved for report views).
    """

    legacy_file: Path
    mapping: LegacyColumnMapping
    legacy_format: Literal["parquet", "csv"] = "csv"
    top_n: int = _DEFAULT_TOP_N


# =============================================================================
# Config file IO (TOML)
# =============================================================================


def load_reconciliation_config(path: str | Path) -> ReconciliationSettings:
    """Load reconciliation settings from a TOML config file.

    Relative ``legacy_file`` paths are resolved against the config file's
    directory so a config + data bundle is portable.

    Raises:
        ValueError: If a required key is missing or a value is invalid.
        FileNotFoundError: If the config file does not exist.
    """
    path = Path(path)
    with path.open("rb") as fh:
        raw: dict[str, Any] = tomllib.load(fh)
    return _settings_from_raw(raw, base_dir=path.parent)


def loads_reconciliation_config(text: str, base_dir: str | Path = ".") -> ReconciliationSettings:
    """Parse reconciliation settings from a TOML string (e.g. a UI editor).

    Relative ``legacy_file`` paths are resolved against ``base_dir``.

    Raises:
        ValueError: If a required key is missing or a value is invalid.
    """
    raw = tomllib.loads(text)
    return _settings_from_raw(raw, base_dir=Path(base_dir))


def dump_reconciliation_config(settings: ReconciliationSettings) -> str:
    """Serialise settings back to TOML text (round-trips with ``load_*``).

    Used by the UI's "export mapping" action — a tiny hand-rolled writer so we
    keep reads on stdlib ``tomllib`` without adding a TOML-writer dependency.
    """
    lines = [
        f"legacy_file = {_toml_str(str(settings.legacy_file))}",
        f"legacy_format = {_toml_str(settings.legacy_format)}",
        f"legacy_keys = {_toml_list(settings.mapping.legacy_keys)}",
        f"our_keys = {_toml_list(settings.mapping.our_keys)}",
        f"top_n = {settings.top_n}",
    ]
    for name, cm in settings.mapping.components.items():
        lines.append("")
        lines.append(f"[components.{name}]")
        lines.append(f"legacy_column = {_toml_str(cm.legacy_column)}")
        if not math.isclose(cm.scale, 1.0):
            lines.append(f"scale = {cm.scale!r}")
        if cm.unit != "raw":
            lines.append(f"unit = {_toml_str(cm.unit)}")
        if cm.value_map:
            lines.append(f"value_map = {_toml_inline_table(cm.value_map)}")
        if cm.tol_kind is not None:
            lines.append(f"tol_kind = {_toml_str(cm.tol_kind)}")
        if cm.tol is not None:
            lines.append(f"tol = {cm.tol!r}")
    return "\n".join(lines) + "\n"


# =============================================================================
# Legacy output loader
# =============================================================================


class LegacyOutputLoader:
    """Scan a legacy output file and map it onto our canonical columns."""

    def __init__(self, settings: ReconciliationSettings) -> None:
        self.settings = settings

    def load(self) -> pl.LazyFrame:
        """Return a LazyFrame with ``legacy_<component>`` columns + the legacy keys.

        Numeric components are scaled (``scale``) and unit-converted (``unit``);
        categorical components are kept as strings. Columns absent from the file
        are simply omitted (the runner surfaces them as REC001).

        Raises:
            FileNotFoundError: If the legacy file does not exist.
        """
        path = self.settings.legacy_file
        if not path.exists():
            raise FileNotFoundError(f"legacy output file not found: {path}")

        scan = (
            pl.scan_csv(path, try_parse_dates=True)
            if self.settings.legacy_format == "csv"
            else pl.scan_parquet(path)
        )
        norm_to_actual: dict[str, str] = {}
        for actual in scan.collect_schema().names():
            norm_to_actual.setdefault(_normalise_name(actual), actual)

        mapping = self.settings.mapping
        exprs: list[pl.Expr] = []
        for key in mapping.legacy_keys:
            actual = norm_to_actual.get(_normalise_name(key))
            if actual is not None:
                exprs.append(pl.col(actual).alias(key))
        for name, cm in mapping.components.items():
            actual = norm_to_actual.get(_normalise_name(cm.legacy_column))
            if actual is None:
                logger.debug("legacy column %r for component %r absent", cm.legacy_column, name)
                continue
            exprs.append(_component_expr(actual, name, cm))

        if not exprs:
            return pl.LazyFrame()
        return scan.select(exprs)


# =============================================================================
# Private helpers
# =============================================================================


def _settings_from_raw(raw: dict[str, Any], base_dir: Path) -> ReconciliationSettings:
    """Build ReconciliationSettings from a parsed TOML mapping."""
    legacy_file_raw = raw.get("legacy_file")
    if not legacy_file_raw:
        raise ValueError("reconciliation config must set 'legacy_file'")
    legacy_file = Path(legacy_file_raw)
    if not legacy_file.is_absolute():
        legacy_file = (base_dir / legacy_file).resolve()

    legacy_format = raw.get("legacy_format", "csv")
    if legacy_format not in ("parquet", "csv"):
        raise ValueError(f"legacy_format must be 'parquet' or 'csv', got {legacy_format!r}")

    mapping = LegacyColumnMapping(
        legacy_keys=tuple(raw.get("legacy_keys", ())),
        our_keys=tuple(raw.get("our_keys", ("exposure_reference",))),
        components=_parse_components(raw.get("components", {})),
    )
    return ReconciliationSettings(
        legacy_file=legacy_file,
        mapping=mapping,
        legacy_format=legacy_format,
        top_n=int(raw.get("top_n", _DEFAULT_TOP_N)),
    )


def _parse_components(raw: dict[str, Any]) -> dict[str, ComponentMapping]:
    """Build ComponentMapping objects from the TOML ``[components.*]`` tables."""
    components: dict[str, ComponentMapping] = {}
    for name, spec in raw.items():
        if not isinstance(spec, dict):
            raise ValueError(f"component '{name}' must be a table, got {type(spec).__name__}")
        legacy_column = spec.get("legacy_column")
        if not legacy_column:
            raise ValueError(f"component '{name}' must set 'legacy_column'")
        components[name] = ComponentMapping(
            legacy_column=legacy_column,
            scale=float(spec.get("scale", 1.0)),
            unit=spec.get("unit", "raw"),
            value_map=dict(spec.get("value_map", {})),
            tol_kind=spec.get("tol_kind"),
            tol=(float(spec["tol"]) if "tol" in spec else None),
        )
    return components


def _component_expr(actual: str, name: str, cm: ComponentMapping) -> pl.Expr:
    """Build the mapped ``legacy_<component>`` expression with scale/unit."""
    spec = RECONCILABLE_COMPONENTS_BY_NAME[name]
    alias = f"legacy_{name}"
    if spec.kind == "categorical":
        return pl.col(actual).cast(pl.String).alias(alias)
    expr = pl.col(actual).cast(pl.Float64) * cm.scale
    if cm.unit == "percent":
        expr = expr / 100.0
    return expr.alias(alias)


def _normalise_name(name: str) -> str:
    """Match engine.loader.normalize_columns: lowercase, spaces -> underscores."""
    return name.strip().lower().replace(" ", "_")


def _toml_str(value: str) -> str:
    """Quote a string as a basic TOML string."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _toml_list(values: tuple[str, ...]) -> str:
    return "[" + ", ".join(_toml_str(v) for v in values) + "]"


def _toml_inline_table(mapping: dict[str, str]) -> str:
    inner = ", ".join(f"{_toml_str(k)} = {_toml_str(v)}" for k, v in mapping.items())
    return "{ " + inner + " }"
