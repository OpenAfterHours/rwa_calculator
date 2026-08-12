"""
Input-domain and output-bound validation for the RWA calculator.

Pipeline position:
    Both pipeline entries and the pipeline exit. ``scrub_non_finite_values``
    and ``validate_bundle_values`` gate the raw input bundle (the file loader
    calls the latter at load; ``engine/pipeline.py::run_with_data`` calls both
    so the in-memory entry path is covered identically);
    ``validate_aggregated_bundle`` gates the aggregated results frame at the
    pipeline exit.

Key responsibilities:
- Categorical input domains — ``validate_bundle_values`` /
  ``validate_column_values`` against ``COLUMN_VALUE_CONSTRAINTS``
- Numeric input domains — PD, LGD, own-estimate CCF and the non-negative
  amount columns, via the four range validators below
- Non-finite (NaN / +-inf) input scrubbing
- Collateral-link referential integrity
- Regulatory output bounds on the aggregated results frame

Schema shape is NOT validated here. Every ``RawDataBundle`` frame carries a
loader edge brand (``contracts/edges.py``, ``contracts.bundles``
``SEALED_FRAME_FIELDS``), and the seal that grants the brand already injects
missing required columns (reported as DQ001 by the loader) and casts declared
columns to their declared dtype. A schema-shape check downstream of that seal
is structurally incapable of firing.

References:
- CRR Art. 160/163: PD; Art. 161/164: LGD; Art. 166(8)/(10): own-estimate CCF
- CRR Art. 111 (SA) / Art. 166 (IRB): exposure value
- CRR Art. 92(3); CRE31.5: the 1250% risk-weight cap
- docs/plans/test-space-correctness-proposal.md (Phase 0)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.errors import (
    ERROR_CCF_OUT_OF_RANGE,
    ERROR_COLLATERAL_LINK_DUPLICATE,
    ERROR_COLLATERAL_LINK_UNKNOWN_BENEFICIARY,
    ERROR_COLLATERAL_LINK_UNKNOWN_COLLATERAL,
    ERROR_EAD_NULL,
    ERROR_INVALID_COLUMN_VALUE,
    ERROR_INVALID_VALUE,
    ERROR_LGD_OUT_OF_RANGE,
    ERROR_MATURITY_INVALID,
    ERROR_NEGATIVE_AMOUNT,
    ERROR_PD_OUT_OF_RANGE,
    ERROR_RW_ABOVE_CAP,
    ERROR_RW_NEGATIVE,
    ERROR_RWA_NEGATIVE,
    CalculationError,
    ErrorCategory,
    ErrorSeverity,
    negative_amount_without_netting_warning,
    non_finite_raw_input_error,
)

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import AggregatedResultBundle, RawDataBundle

# Regulatory reference for collateral link validation (CRM)
COLLATERAL_LINK_CRM_REFERENCE = "CRR Art. 193/194"


# =============================================================================
# BUSINESS RULE VALIDATORS
# =============================================================================


def validate_non_negative_amounts(
    lf: pl.LazyFrame,
    amount_columns: list[str],
    context: str = "",
) -> pl.LazyFrame:
    """
    Add validation expressions for non-negative amount columns.

    Returns a LazyFrame with validation flag columns added.
    Does NOT collect/materialize.

    Args:
        lf: LazyFrame to validate
        amount_columns: List of columns that should be non-negative
        context: Context for naming validation columns

    Returns:
        LazyFrame with _valid_{col} columns added
    """
    exprs = []
    schema_names = lf.collect_schema().names()
    for col in amount_columns:
        if col in schema_names:
            valid_col = f"_valid_{col}"
            exprs.append((pl.col(col) >= 0).alias(valid_col))

    if exprs:
        return lf.with_columns(exprs)
    return lf


def validate_pd_range(
    lf: pl.LazyFrame,
    pd_column: str = "pd",
    min_pd: float = 0.0,
    max_pd: float = 1.0,
) -> pl.LazyFrame:
    """
    Add validation expression for PD range [0, 1].

    Args:
        lf: LazyFrame to validate
        pd_column: Name of PD column
        min_pd: Minimum valid PD (default 0)
        max_pd: Maximum valid PD (default 1)

    Returns:
        LazyFrame with _valid_pd column added
    """
    if pd_column in lf.collect_schema().names():
        return lf.with_columns(
            ((pl.col(pd_column) >= min_pd) & (pl.col(pd_column) <= max_pd)).alias("_valid_pd")
        )
    return lf


def validate_lgd_range(
    lf: pl.LazyFrame,
    lgd_column: str = "lgd",
    min_lgd: float = 0.0,
    max_lgd: float = 1.25,  # Can exceed 1.0 in some cases
) -> pl.LazyFrame:
    """
    Add validation expression for LGD range.

    Args:
        lf: LazyFrame to validate
        lgd_column: Name of LGD column
        min_lgd: Minimum valid LGD (default 0)
        max_lgd: Maximum valid LGD (default 1.25)

    Returns:
        LazyFrame with _valid_lgd column added
    """
    if lgd_column in lf.collect_schema().names():
        return lf.with_columns(
            ((pl.col(lgd_column) >= min_lgd) & (pl.col(lgd_column) <= max_lgd)).alias("_valid_lgd")
        )
    return lf


# =============================================================================
# CCF VALIDATORS
# =============================================================================


def validate_ccf_modelled(
    lf: pl.LazyFrame,
    column: str = "ccf_modelled",
    min_ccf: float = 0.0,
    max_ccf: float = 1.5,
) -> pl.LazyFrame:
    """
    Add validation expression for ccf_modelled range.

    Validates that ccf_modelled is in range [0.0, 1.5] when present.
    Null values are considered valid (the field is optional).

    Note: Retail IRB CCFs can exceed 100% due to additional drawdown
    behaviour (borrowers may draw more than committed amounts during
    stress). A cap of 150% is applied as a reasonable upper bound.

    Args:
        lf: LazyFrame to validate
        column: Name of ccf_modelled column
        min_ccf: Minimum valid CCF (default 0.0)
        max_ccf: Maximum valid CCF (default 1.5, allowing for Retail IRB)

    Returns:
        LazyFrame with _valid_ccf_modelled column added
    """
    if column not in lf.collect_schema().names():
        return lf

    return lf.with_columns(
        pl.when(pl.col(column).is_null())
        .then(pl.lit(True))  # Null is valid (optional field)
        .otherwise((pl.col(column) >= min_ccf) & (pl.col(column) <= max_ccf))
        .alias("_valid_ccf_modelled")
    )


# =============================================================================
# NUMERIC INPUT-DOMAIN GATE
# =============================================================================

# Scratch prefix for the per-column flag each range validator contributes. The
# four validators name their own flag (``_valid_pd``, ``_valid_lgd``, ...), and
# ``validate_lgd_range`` names it ``_valid_lgd`` whichever LGD column it was
# pointed at — so each flag is renamed to a per-column name immediately after
# the validator adds it, and no two can collide on one frame.
_RANGE_FLAG_PREFIX = "_valid_range_"

# Natural key per raw input table: the column whose value names the offending
# row. Populated onto ``CalculationError.exposure_reference`` so a domain
# violation can always be traced to one row (the Phase 2 triage invariant).
_TABLE_KEY_COLUMNS: dict[str, str] = {
    "facilities": "facility_reference",
    "loans": "loan_reference",
    "contingents": "contingent_reference",
    "collateral": "collateral_reference",
    "collateral_links": "collateral_reference",
    "guarantees": "guarantee_reference",
    "provisions": "provision_reference",
    "ratings": "rating_reference",
    "equity_exposures": "exposure_reference",
}

# Amount columns whose regulatory domain excludes negatives, per table.
#
# Deliberately EXCLUDED, each for a stated reason — a false positive here would
# flag legitimate data:
# - ``loans.drawn_amount`` / ``loans.interest``: negative IS the on-balance-sheet
#   netting convention (CRR Art. 195/219). The unreferenced case is already the
#   DQ010 warning from ``_validate_negative_amounts_without_netting``.
# - ``equity_exposures.position_value``: declared SIGNED (+long / -short) for the
#   Art. 133 net-long calculation (``data/schemas.py``).
# - ``counterparties.annual_revenue`` / ``total_assets``: size measures, not
#   exposure amounts; a negative is an accounting fact, not a domain violation.
_NON_NEGATIVE_AMOUNT_COLUMNS: dict[str, tuple[str, ...]] = {
    "facilities": ("limit",),
    "contingents": ("nominal_amount",),
    "collateral": ("market_value", "nominal_value"),
    "collateral_links": ("max_pledge_amount",),
    "guarantees": ("amount_covered",),
    "provisions": ("amount",),
    "equity_exposures": ("carrying_value", "fair_value"),
}

_PD_REFERENCE = "CRR Art. 160/163; PS1/26 Art. 160(1)/163(1)"
_LGD_REFERENCE = "CRR Art. 161/164; PS1/26 Art. 161(5)/164(4)"
_CCF_REFERENCE = "CRR Art. 166(8)/(10)"
_AMOUNT_REFERENCE = "CRR Art. 111 (SA); Art. 166 (IRB)"


@dataclass(frozen=True)
class _DomainSpec:
    """One (column, domain) pair to report on, and how to report it."""

    column: str
    flag: str
    code: str
    expected: str
    regulatory_reference: str


def _validate_numeric_ranges(
    lf: pl.LazyFrame,
    table_name: str,
    sample_cap: int = 5,
) -> list[CalculationError]:
    """Flag numeric input values outside their regulatory domain.

    The error-emitting collector over the four range validators
    (:func:`validate_pd_range`, :func:`validate_lgd_range`,
    :func:`validate_ccf_modelled`, :func:`validate_non_negative_amounts`).
    Each adds a boolean flag column; this pipes the table through every
    validator whose column is present, then turns the flags into row-named
    ``CalculationError``s in ONE ``.collect()`` per table.

    Severity is ERROR, not WARNING: an out-of-domain PD/LGD/CCF/amount does
    not degrade — it produces a plausible, wrong capital number in silence.
    A feed expressing PD in percent rather than as a fraction (``1.5`` for
    1.5%) understates a GBP 1m senior corporate F-IRB exposure's RWA by
    99.95% with no other signal.

    Domains, and why each bound is where it is:

    - **PD in [0, 1]** — closed at zero. The upper bound is the definition of
      a probability and catches the percent-vs-fraction feed error. The lower
      bound is CLOSED because PD = 0 is an admissible regulatory input: CRR
      Art. 160(1) floors the PD of "an exposure to a corporate or an
      institution" at 0.03% and has no central-government / central-bank limb,
      which is why the CRR rulepack carries ``pd_floors["sovereign"] = 0``. A
      half-open (0, 1] domain would reject every sovereign IRB exposure priced
      at zero. Basel 3.1 does floor sovereigns (0.05%), but a floor applied
      downstream is not the same statement as an invalid input, and this gate
      is regime-invariant — the loader validates before any regime pack is
      resolved.
    - **LGD in [0, 1.25]** — ``validate_lgd_range``'s own documented domain.
      Own-estimate downturn LGD can exceed 100% where workout costs exceed the
      exposure, so 1.0 is not a hard ceiling; 1.25 bounds it.
    - **CCF in [0, 1.5]** — ``validate_ccf_modelled``'s documented domain
      (retail A-IRB additional drawdown can exceed 100%). Null is valid.
    - **Amounts >= 0** — per ``_NON_NEGATIVE_AMOUNT_COLUMNS``, which names the
      columns where a negative cannot be a netting convention.

    Null is never a domain violation on any of these — a missing PD/LGD is
    IRB004/IRB005's business, and a missing amount is the loader's.

    Args:
        lf: The table's LazyFrame.
        table_name: RawDataBundle field name, used for the natural key,
            the amount-column set, and the message prefix.
        sample_cap: Maximum per-row errors emitted per column (default 5);
            a single summary error carries the omitted count.

    Returns:
        List of CalculationError objects (empty when every value is in domain).
    """
    schema_names = set(lf.collect_schema().names())
    key_column = _TABLE_KEY_COLUMNS.get(table_name)
    if key_column is None or key_column not in schema_names:
        return []

    flagged = lf
    specs: list[_DomainSpec] = []

    if "pd" in schema_names:
        flagged = _rename_flag(validate_pd_range(flagged), "_valid_pd", "pd")
        specs.append(_domain_spec("pd", ERROR_PD_OUT_OF_RANGE, "[0, 1]", _PD_REFERENCE))

    for lgd_column in ("lgd", "lgd_unsecured"):
        if lgd_column in schema_names:
            flagged = _rename_flag(
                validate_lgd_range(flagged, lgd_column=lgd_column), "_valid_lgd", lgd_column
            )
            specs.append(
                _domain_spec(lgd_column, ERROR_LGD_OUT_OF_RANGE, "[0, 1.25]", _LGD_REFERENCE)
            )

    if "ccf_modelled" in schema_names:
        flagged = _rename_flag(
            validate_ccf_modelled(flagged), "_valid_ccf_modelled", "ccf_modelled"
        )
        specs.append(
            _domain_spec("ccf_modelled", ERROR_CCF_OUT_OF_RANGE, "[0, 1.5]", _CCF_REFERENCE)
        )

    amount_columns = [
        column
        for column in _NON_NEGATIVE_AMOUNT_COLUMNS.get(table_name, ())
        if column in schema_names
    ]
    if amount_columns:
        flagged = validate_non_negative_amounts(flagged, amount_columns, context=table_name)
        for column in amount_columns:
            flagged = _rename_flag(flagged, f"_valid_{column}", column)
            specs.append(_domain_spec(column, ERROR_NEGATIVE_AMOUNT, ">= 0", _AMOUNT_REFERENCE))

    if not specs:
        return []
    return _collect_domain_violations(flagged, key_column, specs, table_name, sample_cap)


def _domain_spec(column: str, code: str, expected: str, reference: str) -> _DomainSpec:
    """Build the reporting spec for one validated column."""
    return _DomainSpec(
        column=column,
        flag=f"{_RANGE_FLAG_PREFIX}{column}",
        code=code,
        expected=expected,
        regulatory_reference=reference,
    )


def _rename_flag(lf: pl.LazyFrame, produced: str, column: str) -> pl.LazyFrame:
    """Give a range validator's freshly-added flag its per-column scratch name."""
    return lf.rename({produced: f"{_RANGE_FLAG_PREFIX}{column}"})


def _collect_domain_violations(
    flagged: pl.LazyFrame,
    key_column: str,
    specs: list[_DomainSpec],
    table_name: str,
    sample_cap: int,
) -> list[CalculationError]:
    """Turn the flag columns into row-named errors in one ``.collect()``.

    Per spec the aggregation carries three length-1 outputs — the violation
    count, up to ``sample_cap`` offending keys, and their values — so the
    whole table (however many columns were validated) costs one collect.
    A null flag means the underlying value was null, which is never a domain
    violation, so it is filled True before negation (``~`` on an all-null
    column also raises).
    """
    exprs: list[pl.Expr] = []
    for spec in specs:
        invalid = ~pl.col(spec.flag).fill_null(value=True)
        exprs.append(invalid.sum().alias(f"n_{spec.flag}"))
        exprs.append(
            pl.col(key_column)
            .cast(pl.String)
            .filter(invalid)
            .head(sample_cap)
            .implode()
            .alias(f"k_{spec.flag}")
        )
        exprs.append(
            pl.col(spec.column).filter(invalid).head(sample_cap).implode().alias(f"v_{spec.flag}")
        )

    row = flagged.select(exprs).collect().row(0, named=True)

    errors: list[CalculationError] = []
    for spec in specs:
        total = int(row[f"n_{spec.flag}"] or 0)
        if total == 0:
            continue
        keys = list(row[f"k_{spec.flag}"] or [])
        values = list(row[f"v_{spec.flag}"] or [])
        message = (
            f"[{table_name}] '{spec.column}' outside its regulatory domain "
            f"{spec.expected} — {total} row(s)"
        )
        for reference, value in zip(keys, values, strict=False):
            errors.append(
                CalculationError(
                    code=spec.code,
                    message=f"{message} (value={value})",
                    severity=ErrorSeverity.ERROR,
                    category=ErrorCategory.DATA_QUALITY,
                    exposure_reference=reference,
                    regulatory_reference=spec.regulatory_reference,
                    field_name=spec.column,
                    expected_value=spec.expected,
                    actual_value=str(value),
                )
            )
        if total > len(keys):
            errors.append(
                CalculationError(
                    code=spec.code,
                    message=(
                        f"{message}: {total - len(keys)} additional row(s) omitted "
                        f"beyond sample_cap={sample_cap}"
                    ),
                    severity=ErrorSeverity.ERROR,
                    category=ErrorCategory.DATA_QUALITY,
                    regulatory_reference=spec.regulatory_reference,
                    field_name=spec.column,
                    expected_value=spec.expected,
                )
            )
    return errors


# =============================================================================
# COLUMN VALUE VALIDATORS
# =============================================================================


def validate_column_values(
    lf: pl.LazyFrame,
    column: str,
    valid_values: set[str],
    context: str = "",
) -> list[CalculationError]:
    """
    Validate that all non-null values in a column are in the valid set.

    Case-insensitive comparison. Null values are skipped (treated as
    missing data, not invalid values).

    Args:
        lf: LazyFrame to validate
        column: Column name to check
        valid_values: Set of allowed lowercase string values
        context: Context string for error messages (e.g. table name)

    Returns:
        List of CalculationError objects for invalid values found
    """
    schema = lf.collect_schema()
    if column not in schema.names():
        return []

    # Find distinct invalid values with counts
    valid_lower = {v.lower() for v in valid_values}
    invalid_df = (
        lf.filter(pl.col(column).is_not_null())
        .filter(~pl.col(column).str.to_lowercase().is_in(valid_lower))
        .group_by(column)
        .len()
        .collect()
    )

    if invalid_df.height == 0:
        return []

    errors: list[CalculationError] = []
    for row in invalid_df.iter_rows(named=True):
        bad_value = row[column]
        count = row["len"]
        sorted_valid = sorted(valid_values)
        errors.append(
            CalculationError(
                code=ERROR_INVALID_COLUMN_VALUE,
                message=(
                    f"[{context}] Invalid value '{bad_value}' for column '{column}' "
                    f"({count} row(s)). "
                    f"Valid values: {sorted_valid}"
                ),
                severity=ErrorSeverity.WARNING,
                category=ErrorCategory.DATA_QUALITY,
                field_name=column,
                expected_value=", ".join(sorted_valid),
                actual_value=str(bad_value),
            )
        )

    return errors


def validate_bundle_values(
    bundle: RawDataBundle,
    constraints: dict[str, dict[str, set[str]]] | None = None,
) -> list[CalculationError]:
    """
    Validate the input domain of every column in a RawDataBundle.

    The whole-bundle input gate. Iterates over all tables in the bundle and,
    per table, checks:

    - **Categorical domains** against the constraints registry (DQ006), all
      columns batched into a single ``.collect()``.
    - **Numeric domains** — PD, LGD, own-estimate CCF and the non-negative
      amount columns (:func:`_validate_numeric_ranges`), likewise one
      ``.collect()`` per table, with the offending row named.
    - **Exposure-table rules** — effective-maturity range (IRB003) and
      unreferenced negative on-balance amounts (DQ010).
    - **Ratings** — the short-term rating scope contract (DQ002).

    Then, cross-table, the collateral-link referential integrity checks.

    Called from both pipeline entries: ``engine/loader.py::_build_bundle``
    for the file path (so the returned bundle carries its own errors) and
    ``engine/pipeline.py::run_with_data`` for the in-memory path, which
    de-duplicates against the errors already on the bundle so the file path
    never double-reports.

    Args:
        bundle: RawDataBundle to validate
        constraints: Override constraints dict; defaults to COLUMN_VALUE_CONSTRAINTS

    Returns:
        List of CalculationError objects for any invalid values found
    """
    if constraints is None:
        from rwa_calc.data.schemas import COLUMN_VALUE_CONSTRAINTS

        constraints = COLUMN_VALUE_CONSTRAINTS

    frame_mapping: dict[str, pl.LazyFrame | None] = {
        "facilities": bundle.facilities,
        "loans": bundle.loans,
        "contingents": bundle.contingents,
        "counterparties": bundle.counterparties,
        "collateral": bundle.collateral,
        "collateral_links": bundle.collateral_links,
        "guarantees": bundle.guarantees,
        "provisions": bundle.provisions,
        "ratings": bundle.ratings,
        "specialised_lending": bundle.specialised_lending,
        "equity_exposures": bundle.equity_exposures,
        "facility_mappings": bundle.facility_mappings,
        "model_permissions": bundle.model_permissions,
    }

    all_errors: list[CalculationError] = []

    for table_name, lf in frame_mapping.items():
        if lf is None:
            continue
        table_constraints = constraints.get(table_name, {})
        if table_constraints:
            errors = _validate_table_columns_batched(lf, table_constraints, table_name)
            all_errors.extend(errors)

        # Numeric input domains (PD / LGD / own-estimate CCF / amounts). One
        # collect per table; a no-op for tables carrying none of those columns.
        all_errors.extend(_validate_numeric_ranges(lf, table_name))

        # Art. 162(3) override is restricted to exposure tables — the 1-day to
        # 5-year range mirrors the regulatory cap; out-of-range values are clipped
        # downstream but flagged here so firms see the mismatch.
        if table_name in {"facilities", "loans", "contingents"}:
            all_errors.extend(_validate_effective_maturity_range(lf, table_name))
            all_errors.extend(_validate_negative_amounts_without_netting(lf, table_name))

        # PRA PS1/26 Art. 120(2B) / Art. 122(3): short-term rating rows must
        # carry a scope (which exposure they attach to). Flag rows that violate
        # the is_short_term ↔ scope_type/scope_id contract.
        if table_name == "ratings":
            all_errors.extend(_validate_short_term_rating_scope(lf))

    # Cross-table referential integrity for the M:N collateral-links table.
    all_errors.extend(validate_collateral_links(bundle))

    return all_errors


def scrub_non_finite_values(bundle: RawDataBundle) -> RawDataBundle:
    """Null out non-finite (NaN / ±inf) float values in every raw input table.

    The pipeline-entry gate for the DQ011 error family: a NaN in any float
    input column (a guarantee ``amount_covered``, a loan ``drawn_amount`` /
    ``effective_maturity``, a rating ``pd``, ...) survives every downstream
    arithmetic step — Polars ``.sum()`` propagates NaN — poisoning the
    affected exposure's ``rwa_final`` (surfacing only later as an aggregator
    AGG001 error) and, through the Basel 3.1 portfolio output floor, every
    other row's post-floor RWA. Null is the documented degradation value
    (see ``missing_required_column_error``): downstream null semantics
    exclude the value instead of blanking totals.

    Iterates the ``RAW_TABLE_EDGES`` frames (the ``RawDataBundle`` LazyFrame
    fields; the nested CCR/SFT composite bundles are out of scope here — the
    aggregator AGG001 scan still nets any non-finite they produce). Per
    table: one aggregate pass counts non-finite values per float column;
    clean tables pass through untouched (a fully clean bundle is returned
    identically). Dirty columns are nulled, the frame is re-branded for its
    loader edge, and one :func:`non_finite_raw_input_error` per (table,
    column) — carrying up to five affected row references — is appended to
    the bundle's error list.

    Called by ``PipelineOrchestrator.run_with_data`` so both entry paths
    (file loader and in-memory bundles) are covered.
    """
    from rwa_calc.contracts.edges import RAW_TABLE_EDGES, brand

    replacements: dict[str, pl.LazyFrame] = {}
    new_errors: list[CalculationError] = []

    for field_name, edge in RAW_TABLE_EDGES.items():
        frame = getattr(bundle, field_name, None)
        if frame is None:
            continue
        scrubbed = _scrub_table_non_finite(frame, field_name, new_errors)
        if scrubbed is not None:
            replacements[field_name] = brand(scrubbed, edge.name)

    if not replacements:
        return bundle

    from dataclasses import replace

    return replace(bundle, errors=list(bundle.errors) + new_errors, **replacements)


def _scrub_table_non_finite(
    lf: pl.LazyFrame,
    table_name: str,
    errors: list[CalculationError],
) -> pl.LazyFrame | None:
    """Null non-finite values in ``lf``'s float columns; ``None`` when clean.

    One aggregate ``.collect()`` counts non-finite values per float column
    (``is_finite()`` is null on null, so nulls are never counted); a second,
    dirty-tables-only collect samples up to five row references per affected
    column for the DQ011 message. The reference column is the first String
    column named ``*_reference`` in table order (``loan_reference``,
    ``guarantee_reference``, ...); tables without one emit no samples.
    """
    schema = lf.collect_schema()
    float_cols = [c for c, dt in schema.items() if dt in (pl.Float32, pl.Float64)]
    if not float_cols:
        return None

    counts = (
        lf.select(
            [(~pl.col(c).is_finite()).fill_null(value=False).sum().alias(c) for c in float_cols]
        )
        .collect()
        .row(0, named=True)
    )
    dirty = [c for c in float_cols if counts[c]]
    if not dirty:
        return None

    ref_col = next(
        (c for c in schema.names() if c.endswith("_reference") and schema[c] == pl.String),
        None,
    )
    samples: dict[str, list[str]] = {}
    if ref_col is not None:
        non_finite = [(~pl.col(c).is_finite()).fill_null(value=False) for c in dirty]
        sample_df = (
            lf.filter(pl.any_horizontal(non_finite))
            .select([pl.col(ref_col), *(pl.col(c) for c in dirty)])
            .head(100)
            .collect()
        )
        for c in dirty:
            mask = (~sample_df.get_column(c).is_finite()).fill_null(value=False)
            refs = sample_df.filter(mask).get_column(ref_col).cast(pl.String).to_list()
            samples[c] = list(dict.fromkeys(refs))[:5]

    errors.extend(
        non_finite_raw_input_error(
            table=table_name,
            column=c,
            count=int(counts[c]),
            references=samples.get(c),
        )
        for c in dirty
    )
    return lf.with_columns(
        [pl.when(pl.col(c).is_finite()).then(pl.col(c)).otherwise(None).alias(c) for c in dirty]
    )


def validate_collateral_links(bundle: RawDataBundle) -> list[CalculationError]:
    """Referential-integrity checks for the M:N collateral-links table.

    The collateral_links table lets one finite collateral item be pledged
    against multiple beneficiaries. Before the CRM stage splits the value, this
    validates that:

    - Every ``collateral_reference`` resolves to a real collateral item
      (``CRM009``).
    - Every ``(beneficiary_type, beneficiary_reference)`` resolves to a real
      exposure / facility / counterparty / guarantee (``CRM010``). Types are
      resolved exactly as the CRM cascade resolves them: direct types
      (exposure/loan/contingent) against loan/contingent references, ``facility``
      against facility references, ``counterparty`` against counterparty
      references.
    - No ``(collateral_reference, beneficiary_type, beneficiary_reference)``
      triple is duplicated (``CRM011``).

    Returns an empty list when no collateral_links table is supplied (the
    single-beneficiary path is unaffected). Never raises — all issues are
    accumulated as CalculationError.

    References:
    - CRR Art. 193/194/207: CRM eligibility and recognition conditions
    """
    links = bundle.collateral_links
    if links is None:
        return []

    link_cols = set(links.collect_schema().names())
    required = {"collateral_reference", "beneficiary_type", "beneficiary_reference"}
    if not required.issubset(link_cols):
        # Missing required columns are reported by schema validation.
        return []

    errors: list[CalculationError] = []

    norm = links.select(
        pl.col("collateral_reference").cast(pl.String),
        pl.col("beneficiary_type").cast(pl.String).str.to_lowercase().alias("_bt"),
        pl.col("beneficiary_reference").cast(pl.String),
    )

    # --- CRM009: unknown collateral reference ---------------------------------
    # An absent collateral table yields an empty valid set, so the anti-join
    # flags every linked collateral_reference (a single linear code path).
    if bundle.collateral is not None and (
        "collateral_reference" in bundle.collateral.collect_schema().names()
    ):
        valid_coll = (
            bundle.collateral.select(pl.col("collateral_reference").cast(pl.String))
            .unique()
            .drop_nulls()
        )
    else:
        valid_coll = pl.LazyFrame(schema={"collateral_reference": pl.String})
    unknown_coll = (
        norm.select("collateral_reference")
        .unique()
        .join(valid_coll, on="collateral_reference", how="anti")
        .collect()["collateral_reference"]
        .to_list()
    )
    if unknown_coll:
        errors.append(
            CalculationError(
                code=ERROR_COLLATERAL_LINK_UNKNOWN_COLLATERAL,
                message=(
                    f"[collateral_links] {len(unknown_coll)} collateral_reference value(s) "
                    f"do not resolve to a collateral item: {sorted(unknown_coll)[:5]}. "
                    "Each link must reference a row in the collateral table."
                ),
                severity=ErrorSeverity.ERROR,
                category=ErrorCategory.CRM,
                field_name="collateral_reference",
                regulatory_reference=COLLATERAL_LINK_CRM_REFERENCE,
            )
        )

    # --- CRM010: unknown beneficiary (type, reference) ------------------------
    valid_refs = _collateral_link_valid_beneficiaries(bundle)
    unknown_benef = (
        norm.select("_bt", "beneficiary_reference")
        .unique()
        .join(valid_refs, on=["_bt", "beneficiary_reference"], how="anti")
        .collect()
    )
    if unknown_benef.height > 0:
        sample = (
            unknown_benef.head(5)
            .select(pl.concat_str(["_bt", "beneficiary_reference"], separator=":").alias("s"))["s"]
            .to_list()
        )
        errors.append(
            CalculationError(
                code=ERROR_COLLATERAL_LINK_UNKNOWN_BENEFICIARY,
                message=(
                    f"[collateral_links] {unknown_benef.height} beneficiary link(s) do not "
                    f"resolve to a real exposure/facility/counterparty: {sample}. The "
                    "beneficiary_type must match the reference's source table."
                ),
                severity=ErrorSeverity.ERROR,
                category=ErrorCategory.CRM,
                field_name="beneficiary_reference",
                regulatory_reference=COLLATERAL_LINK_CRM_REFERENCE,
            )
        )

    # --- CRM011: duplicate links ---------------------------------------------
    dups = (
        norm.group_by(["collateral_reference", "_bt", "beneficiary_reference"])
        .len()
        .filter(pl.col("len") > 1)
        .collect()
    )
    if dups.height > 0:
        sample = (
            dups.head(5)
            .select(
                pl.concat_str(
                    ["collateral_reference", "_bt", "beneficiary_reference"], separator=":"
                ).alias("s")
            )["s"]
            .to_list()
        )
        errors.append(
            CalculationError(
                code=ERROR_COLLATERAL_LINK_DUPLICATE,
                message=(
                    f"[collateral_links] {dups.height} duplicated "
                    f"(collateral_reference, beneficiary_type, beneficiary_reference) "
                    f"triple(s): {sample}. Each link must be unique."
                ),
                severity=ErrorSeverity.ERROR,
                category=ErrorCategory.CRM,
                field_name="beneficiary_reference",
                regulatory_reference=COLLATERAL_LINK_CRM_REFERENCE,
            )
        )

    return errors


def _collateral_link_valid_beneficiaries(bundle: RawDataBundle) -> pl.LazyFrame:
    """Build the valid (lower-cased beneficiary_type, reference) universe.

    Mirrors the CRM cascade's resolution: exposure/loan/contingent resolve
    against loan and contingent references; facility against facility
    references; counterparty against counterparty references; guarantee against
    guarantee references.
    """
    frames: list[pl.LazyFrame] = []

    def _add(lf: pl.LazyFrame | None, ref_col: str, bt_values: list[str]) -> None:
        if lf is None:
            return
        if ref_col not in lf.collect_schema().names():
            return
        refs = lf.select(
            pl.col(ref_col).cast(pl.String).alias("beneficiary_reference")
        ).drop_nulls()
        for bt in bt_values:
            frames.append(refs.with_columns(pl.lit(bt).alias("_bt")))

    # Direct types share the unified exposure_reference (= loan / contingent ref).
    _add(bundle.loans, "loan_reference", ["loan", "exposure"])
    _add(bundle.contingents, "contingent_reference", ["contingent", "exposure"])
    _add(bundle.facilities, "facility_reference", ["facility"])
    _add(bundle.counterparties, "counterparty_reference", ["counterparty"])
    _add(bundle.guarantees, "guarantee_reference", ["guarantee"])

    if not frames:
        return pl.LazyFrame(
            {"beneficiary_reference": [], "_bt": []},
            schema={"beneficiary_reference": pl.String, "_bt": pl.String},
        )
    return pl.concat(frames, how="vertical_relaxed").unique()


def _validate_effective_maturity_range(
    lf: pl.LazyFrame,
    context: str,
) -> list[CalculationError]:
    """Flag effective_maturity values outside (0, 5.0] for an exposure table."""
    schema_names = lf.collect_schema().names()
    if "effective_maturity" not in schema_names:
        return []

    bad = (
        lf.filter(pl.col("effective_maturity").is_not_null())
        .filter((pl.col("effective_maturity") <= 0.0) | (pl.col("effective_maturity") > 5.0))
        .select(
            pl.len().alias("n"),
            pl.col("effective_maturity").min().alias("min_val"),
            pl.col("effective_maturity").max().alias("max_val"),
        )
        .collect()
    )
    if bad.height == 0 or bad["n"][0] == 0:
        return []

    row = bad.row(0, named=True)
    return [
        CalculationError(
            code=ERROR_MATURITY_INVALID,
            message=(
                f"[{context}] effective_maturity has {row['n']} value(s) outside the "
                f"regulatory range (0, 5.0] years (observed min={row['min_val']}, "
                f"max={row['max_val']}). Values will be clipped to [1/365, 5.0]."
            ),
            severity=ErrorSeverity.WARNING,
            category=ErrorCategory.DATA_QUALITY,
            field_name="effective_maturity",
            expected_value="(0, 5.0]",
        )
    ]


def _validate_short_term_rating_scope(lf: pl.LazyFrame) -> list[CalculationError]:
    """Flag short-term rating rows that violate the scope contract.

    Three violations are detected and reported via ``DQ002``:

    - **Missing scope**: ``is_short_term=True`` with null ``scope_type`` or
      null ``scope_id``. Short-term rating rows must identify the exposure they
      attach to.
    - **Stray scope**: ``is_short_term=False`` (or null) with a non-null
      ``scope_type``/``scope_id``. Scope columns are only meaningful for
      short-term rows; populated values on a long-term row indicate a
      data-entry error.

    ``scope_type`` value-set validation (must be one of
    ``VALID_RATING_SCOPE_TYPES``) is handled by the generic categorical-value
    pass via ``COLUMN_VALUE_CONSTRAINTS``.
    """
    schema_names = lf.collect_schema().names()
    if "is_short_term" not in schema_names:
        return []
    if "scope_type" not in schema_names or "scope_id" not in schema_names:
        return []

    is_st = pl.col("is_short_term").fill_null(False)
    scope_t = pl.col("scope_type")
    scope_id = pl.col("scope_id")

    bad = (
        lf.select(
            [
                (is_st & (scope_t.is_null() | scope_id.is_null())).sum().alias("missing"),
                (~is_st & (scope_t.is_not_null() | scope_id.is_not_null())).sum().alias("stray"),
            ]
        )
        .collect()
        .row(0, named=True)
    )

    errors: list[CalculationError] = []
    if bad["missing"]:
        errors.append(
            CalculationError(
                code=ERROR_INVALID_VALUE,
                message=(
                    f"[ratings] {bad['missing']} row(s) have is_short_term=True "
                    "but null scope_type or scope_id. Short-term rating rows must "
                    "identify the exposure they attach to (PRA PS1/26 Art. 120(2B))."
                ),
                severity=ErrorSeverity.ERROR,
                category=ErrorCategory.DATA_QUALITY,
                field_name="scope_type",
                regulatory_reference="PRA PS1/26 Art. 120(2B)",
            )
        )
    if bad["stray"]:
        errors.append(
            CalculationError(
                code=ERROR_INVALID_VALUE,
                message=(
                    f"[ratings] {bad['stray']} row(s) have is_short_term=False "
                    "but populated scope_type/scope_id. Scope columns apply only "
                    "to short-term rating rows."
                ),
                severity=ErrorSeverity.WARNING,
                category=ErrorCategory.DATA_QUALITY,
                field_name="scope_type",
            )
        )
    return errors


def _validate_negative_amounts_without_netting(
    lf: pl.LazyFrame,
    context: str,
) -> list[CalculationError]:
    """Flag negative ``drawn_amount`` / ``interest`` rows that carry no netting.

    A negative on-balance amount is the deliberate on-balance-sheet netting
    convention (CRR Art. 195/219): a deposit / credit balance offsets the loans
    that share its ``netting_agreement_reference``. A negative amount WITHOUT a
    reference cannot net against anything, so it is a data error — the value is
    floored at 0 downstream (for EAD and the gross-exposure reporting carriers),
    never consumed as negative. One aggregate DQ010 warning per offending
    column. When the table carries no ``netting_agreement_reference`` column,
    every negative is unreferenced by definition and flagged.

    References:
    - CRR Art. 111 (SA gross exposure value); Art. 166 (IRB exposure value)
    - CRR Art. 195/219 (on-balance-sheet netting)
    """
    schema_names = lf.collect_schema().names()
    amount_cols = [c for c in ("drawn_amount", "interest") if c in schema_names]
    if not amount_cols:
        return []

    if "netting_agreement_reference" in schema_names:
        unreferenced = pl.col("netting_agreement_reference").is_null()
    else:
        unreferenced = pl.lit(value=True)

    counts = (
        lf.select([((pl.col(c) < 0) & unreferenced).sum().alias(c) for c in amount_cols])
        .collect()
        .row(0, named=True)
    )

    return [
        negative_amount_without_netting_warning(context=context, column=c, n=counts[c])
        for c in amount_cols
        if counts[c]
    ]


def _validate_table_columns_batched(
    lf: pl.LazyFrame,
    table_constraints: dict[str, set[str]],
    context: str,
) -> list[CalculationError]:
    """
    Validate multiple columns in a single table with one .collect() call.

    Builds a single LazyFrame query that checks all constrained columns at once,
    reducing N separate .collect() calls to 1.

    Args:
        lf: LazyFrame for the table
        table_constraints: Mapping of column name -> valid values
        context: Table name for error messages

    Returns:
        List of CalculationError objects for invalid values found
    """
    schema = lf.collect_schema()
    columns_to_check = [col for col in table_constraints if col in schema.names()]

    if not columns_to_check:
        return []

    # Build a single query that finds invalid values for all columns at once.
    # For each column, select rows where the value is not in the valid set,
    # then union them into a single frame with (column_name, bad_value, count).
    invalid_queries: list[pl.LazyFrame] = []
    for col_name in columns_to_check:
        valid_values = table_constraints[col_name]
        valid_lower = {v.lower() for v in valid_values}
        q = (
            lf.filter(pl.col(col_name).is_not_null())
            .filter(~pl.col(col_name).str.to_lowercase().is_in(valid_lower))
            .group_by(pl.col(col_name).alias("bad_value"))
            .len()
            .with_columns(pl.lit(col_name).alias("column_name"))
        )
        invalid_queries.append(q)

    if not invalid_queries:
        return []

    # Single collect for all column checks in this table
    combined = pl.concat(invalid_queries, how="diagonal_relaxed")
    try:
        invalid_df = combined.collect()
    except Exception:
        # Fallback to per-column validation if batching fails
        errors: list[CalculationError] = []
        for col_name in columns_to_check:
            errors.extend(
                validate_column_values(lf, col_name, table_constraints[col_name], context=context)
            )
        return errors

    if invalid_df.height == 0:
        return []

    errors = []
    for row in invalid_df.iter_rows(named=True):
        col_name = row["column_name"]
        bad_value = row["bad_value"]
        count = row["len"]
        sorted_valid = sorted(table_constraints[col_name])
        errors.append(
            CalculationError(
                code=ERROR_INVALID_COLUMN_VALUE,
                message=(
                    f"[{context}] Invalid value '{bad_value}' for column '{col_name}' "
                    f"({count} row(s)). "
                    f"Valid values: {sorted_valid}"
                ),
                severity=ErrorSeverity.WARNING,
                category=ErrorCategory.DATA_QUALITY,
                field_name=col_name,
                expected_value=", ".join(sorted_valid),
                actual_value=str(bad_value),
            )
        )

    return errors


# =============================================================================
# AGGREGATED OUTPUT BOUNDS VALIDATOR
# =============================================================================


# Per-bound configuration: (column, predicate-builder, error code, category, ref, message)
_AGG_BOUND_SPECS: tuple[
    tuple[str, str, ErrorCategory, str | None, str],
    ...,
] = (
    (
        "risk_weight",
        ERROR_RW_ABOVE_CAP,
        ErrorCategory.BUSINESS_RULE,
        "CRR Art. 92(3); CRE31.5 (RW <= 1250%)",
        "risk_weight exceeds 1250% cap (12.5)",
    ),
    (
        "risk_weight",
        ERROR_RW_NEGATIVE,
        ErrorCategory.BUSINESS_RULE,
        "CRR Art. 153; CRE31",
        "risk_weight is negative",
    ),
    (
        "rwa_final",
        ERROR_RWA_NEGATIVE,
        ErrorCategory.BUSINESS_RULE,
        "CRR Art. 92(3)",
        "rwa_final is negative beyond float64 round-off (< -1e-9)",
    ),
    (
        "ead_final",
        ERROR_EAD_NULL,
        ErrorCategory.DATA_QUALITY,
        None,
        "ead_final is null",
    ),
)


def validate_aggregated_bundle(
    bundle: AggregatedResultBundle,
    sample_cap: int = 5,
) -> list[CalculationError]:
    """
    Validate regulatory output bounds on AggregatedResultBundle.results.

    Checks four bound violations per the architect's spec:

    - OUT001: ``risk_weight > 12.5`` (1250% cap; CRR Art. 92(3); CRE31.5)
    - OUT002: ``risk_weight < 0``    (CRR Art. 153; CRE31)
    - OUT003: ``rwa_final < -1e-9``  (float64 round-off tolerance; CRR Art. 92(3))
    - OUT004: ``ead_final`` is null   (data quality)

    For each bound, up to ``sample_cap`` per-row errors are emitted with
    ``exposure_reference`` populated. If the violation count exceeds the
    cap, a single summary error is appended noting the omitted-row count.

    Missing target columns are silently skipped; an empty results frame
    returns ``[]``. Never raises — errors are accumulated, not thrown.

    Args:
        bundle: AggregatedResultBundle to inspect.
        sample_cap: Maximum per-row errors emitted per bound (default 5).

    Returns:
        List of CalculationError objects (empty if all bounds satisfied).
    """
    results_lf = bundle.results
    schema_names = set(results_lf.collect_schema().names())

    errors: list[CalculationError] = []
    for column, code, category, regulatory_reference, message in _AGG_BOUND_SPECS:
        if column not in schema_names:
            continue
        if "exposure_reference" not in schema_names:
            continue

        predicate = _bound_predicate(column, code)
        offending = (
            results_lf.filter(predicate)
            .select("exposure_reference", pl.col(column).alias("_bound_value"))
            .collect()
        )
        total = offending.height
        if total == 0:
            continue

        sampled = offending.head(sample_cap)
        for row in sampled.iter_rows(named=True):
            errors.append(
                CalculationError(
                    code=code,
                    message=f"{message} (value={row['_bound_value']})",
                    severity=ErrorSeverity.ERROR,
                    category=category,
                    exposure_reference=row["exposure_reference"],
                    regulatory_reference=regulatory_reference,
                    field_name=column,
                    actual_value=str(row["_bound_value"]),
                )
            )

        if total > sample_cap:
            omitted = total - sample_cap
            errors.append(
                CalculationError(
                    code=code,
                    message=(
                        f"{message}: {omitted} additional row(s) omitted beyond "
                        f"sample_cap={sample_cap}"
                    ),
                    severity=ErrorSeverity.ERROR,
                    category=category,
                    regulatory_reference=regulatory_reference,
                    field_name=column,
                )
            )

    return errors


def _bound_predicate(column: str, code: str) -> pl.Expr:
    """Build the Polars predicate that flags rows violating a given bound."""
    if code == ERROR_RW_ABOVE_CAP:
        return pl.col(column).is_not_null() & (pl.col(column) > 12.5)
    if code == ERROR_RW_NEGATIVE:
        return pl.col(column).is_not_null() & (pl.col(column) < 0.0)
    if code == ERROR_RWA_NEGATIVE:
        return pl.col(column).is_not_null() & (pl.col(column) < -1e-9)
    if code == ERROR_EAD_NULL:
        return pl.col(column).is_null()
    raise ValueError(f"Unknown bound code: {code}")
