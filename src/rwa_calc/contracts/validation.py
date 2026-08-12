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
- Declared input domains — ``_validate_declared_domains`` reads every
  ``ColumnSpec.domain`` in ``data/schemas.py`` (numeric intervals AND
  categorical value sets) and emits one row-named error per offending value
- Categorical input domains — ``validate_bundle_values`` /
  ``validate_column_values`` against ``COLUMN_VALUE_CONSTRAINTS``, which is
  itself derived from the same declarations
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
- docs/plans/test-space-correctness-proposal.md (Phases 0 and 1)
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
    ERROR_INPUT_OUT_OF_DOMAIN,
    ERROR_INVALID_COLUMN_VALUE,
    ERROR_INVALID_VALUE,
    ERROR_LGD_OUT_OF_RANGE,
    ERROR_MATURITY_INVALID,
    ERROR_MISSING_FIELD,
    ERROR_NEGATIVE_AMOUNT,
    ERROR_ORPHAN_REFERENCE,
    ERROR_PD_OUT_OF_RANGE,
    ERROR_RW_ABOVE_CAP,
    ERROR_RW_NEGATIVE,
    ERROR_RWA_NEGATIVE,
    ERROR_UNKNOWN_BRANCH_FALLBACK,
    CalculationError,
    ErrorCategory,
    ErrorSeverity,
    absent_reference_error,
    duplicate_input_key_error,
    negative_amount_without_netting_warning,
    non_finite_raw_input_error,
    orphan_reference_error,
)
from rwa_calc.domain.branch_reasons import BRANCH_REASON_VOCABULARIES, UNKNOWN_FALLBACK

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import AggregatedResultBundle, RawDataBundle
    from rwa_calc.data.column_spec import ColumnDomain, ForeignKey

# Regulatory reference for collateral link validation (CRM)
COLLATERAL_LINK_CRM_REFERENCE = "CRR Art. 193/194"


# =============================================================================
# DECLARED INPUT-DOMAIN GATE
# =============================================================================
#
# Phase 1 of docs/plans/test-space-correctness-proposal.md. Phase 0 shipped
# this gate as a collector over FOUR hand-written range validators
# (``validate_pd_range``, ``validate_lgd_range``, ``validate_ccf_modelled``,
# ``validate_non_negative_amounts``), so a column got validation only when
# somebody remembered to add a branch for it. Those four are gone: the domain
# now lives on the column declaration (``data/schemas.py``
# ``ColumnSpec.domain``) and this reads every declaration generically. Their
# pins were removed from ``CONTRACTS_GUARD_SURFACE`` in the same change, which
# is the documented path for deliberately retiring a guard.
#
# What the declaration does NOT carry is the error TAXONOMY. Which code and
# severity an out-of-domain value publishes is a contracts-layer concern (and
# ``data/`` may not import ``contracts/`` — arch_check check 12), so the
# legacy pins live here.

#: Columns whose out-of-domain error code the estate already publishes, and
#: which therefore may not change. A NEW declared domain needs no entry — it
#: reports as ``DQ013`` / ERROR. This is an error-taxonomy compatibility table,
#: NOT a second home for the domains themselves.
_DOMAIN_REPORTING: dict[str, tuple[str, ErrorSeverity]] = {
    "pd": (ERROR_PD_OUT_OF_RANGE, ErrorSeverity.ERROR),
    "lgd": (ERROR_LGD_OUT_OF_RANGE, ErrorSeverity.ERROR),
    "lgd_unsecured": (ERROR_LGD_OUT_OF_RANGE, ErrorSeverity.ERROR),
    "ccr_modelled_lgd": (ERROR_LGD_OUT_OF_RANGE, ErrorSeverity.ERROR),
    "wwr_lgd_override": (ERROR_LGD_OUT_OF_RANGE, ErrorSeverity.ERROR),
    "ccf_modelled": (ERROR_CCF_OUT_OF_RANGE, ErrorSeverity.ERROR),
    # WARNING, not ERROR, and deliberately so: the engine CLIPS effective
    # maturity to [1/365, 5.0] downstream, so an out-of-range value still
    # produces a calculable row. Severity is the estate's existing IRB003
    # contract (tests/unit/test_effective_maturity.py) and changing it is a
    # separate decision from declaring the domain.
    "effective_maturity": (ERROR_MATURITY_INVALID, ErrorSeverity.WARNING),
}

#: Monetary columns Phase 0 already published under DQ012. Grouped rather than
#: listed one-per-entry above because they share one domain
#: (``_NON_NEGATIVE_AMOUNT_DOMAIN``) and one code.
_NEGATIVE_AMOUNT_COLUMNS: frozenset[str] = frozenset(
    {
        "limit",
        "nominal_amount",
        "market_value",
        "nominal_value",
        "max_pledge_amount",
        "amount_covered",
        "amount",
        "carrying_value",
        "fair_value",
    }
)


@dataclass(frozen=True)
class _DomainSpec:
    """One declared (column, domain) pair to report on, and how to report it."""

    column: str
    domain: ColumnDomain
    code: str
    severity: ErrorSeverity


def _validate_declared_domains(
    lf: pl.LazyFrame,
    table_name: str,
    sample_cap: int = 5,
) -> list[CalculationError]:
    """Flag input values outside the domain their column DECLARES.

    The generic reader of ``ColumnSpec.domain``. For every column the table's
    schema declares a domain for and the frame actually carries, this builds
    the domain's own violation predicate and turns the results into row-named
    ``CalculationError``s in ONE ``.collect()`` per table — whatever the
    number of validated columns.

    Severity is ERROR unless ``_DOMAIN_REPORTING`` pins otherwise: an
    out-of-domain PD, LGD, CQS or amount does not degrade, it produces a
    plausible and wrong capital number in silence. A feed expressing PD in
    percent rather than as a fraction (``1.5`` for 1.5%) understates a
    GBP 1m senior corporate F-IRB exposure's RWA by 99.95% with no other
    signal; a CQS of 0, 7 or 99 silently takes the unrated 100% branch.

    The bounds themselves, and the justification for each, live on the
    declarations in ``data/schemas.py`` — deliberately not restated here,
    because a bound with two homes is a bound that drifts.

    Null is never a domain violation: a MISSING PD/LGD is IRB004/IRB005's
    business and a missing amount is the loader's.

    Args:
        lf: The table's LazyFrame.
        table_name: ``TABLE_SCHEMAS`` key — resolves the declaring schema,
            the natural key, and the message prefix.
        sample_cap: Maximum per-row errors emitted per column (default 5);
            a single summary error carries the truthful omitted count.

    Returns:
        List of CalculationError objects (empty when every value is in domain).
    """
    from rwa_calc.data.schemas import TABLE_KEY_COLUMNS, TABLE_SCHEMAS

    schema = TABLE_SCHEMAS.get(table_name)
    if schema is None:
        return []

    present = set(lf.collect_schema().names())
    specs: list[_DomainSpec] = []
    for column, spec in schema.items():
        if spec.domain is None or column not in present:
            continue
        code, severity = _reporting_for(column)
        specs.append(_DomainSpec(column=column, domain=spec.domain, code=code, severity=severity))
    if not specs:
        return []

    key_column = TABLE_KEY_COLUMNS.get(table_name)
    if key_column not in present:
        key_column = None
    return _collect_domain_violations(lf, key_column, specs, table_name, sample_cap)


def _reporting_for(column: str) -> tuple[str, ErrorSeverity]:
    """The error code and severity a domain violation on ``column`` publishes."""
    if column in _NEGATIVE_AMOUNT_COLUMNS:
        return ERROR_NEGATIVE_AMOUNT, ErrorSeverity.ERROR
    return _DOMAIN_REPORTING.get(column, (ERROR_INPUT_OUT_OF_DOMAIN, ErrorSeverity.ERROR))


def _collect_domain_violations(
    lf: pl.LazyFrame,
    key_column: str | None,
    specs: list[_DomainSpec],
    table_name: str,
    sample_cap: int,
) -> list[CalculationError]:
    """Turn every declared domain's violation predicate into errors in one collect.

    Per spec the aggregation carries three length-1 outputs — the violation
    count, up to ``sample_cap`` offending keys, and their values — so the
    whole table costs one collect however many columns were validated.

    ``key_column`` may be None for a table with no single-column identity; the
    per-row errors then carry no ``exposure_reference`` rather than the table
    being skipped. Skipping was Phase 0's behaviour and it silently excluded
    every table absent from the key registry — including ``counterparties``,
    which owns the CQS columns.
    """
    exprs: list[pl.Expr] = []
    for spec in specs:
        invalid = spec.domain.violation_expr(spec.column)
        exprs.append(invalid.sum().alias(f"n_{spec.column}"))
        if key_column is not None:
            exprs.append(
                pl.col(key_column)
                .cast(pl.String)
                .filter(invalid)
                .head(sample_cap)
                .implode()
                .alias(f"k_{spec.column}")
            )
        exprs.append(
            pl.col(spec.column).filter(invalid).head(sample_cap).implode().alias(f"v_{spec.column}")
        )

    row = lf.select(exprs).collect().row(0, named=True)

    errors: list[CalculationError] = []
    for spec in specs:
        total = int(row[f"n_{spec.column}"] or 0)
        if total == 0:
            continue
        values = list(row[f"v_{spec.column}"] or [])
        keys: list[str | None] = (
            list(row[f"k_{spec.column}"] or []) if key_column is not None else [None] * len(values)
        )
        expected = spec.domain.describe()
        message = (
            f"[{table_name}] '{spec.column}' outside its declared domain "
            f"{expected} — {total} row(s)"
        )
        errors.extend(
            CalculationError(
                code=spec.code,
                message=f"{message} (value={value})",
                severity=spec.severity,
                category=ErrorCategory.DATA_QUALITY,
                exposure_reference=reference,
                regulatory_reference=spec.domain.reason,
                field_name=spec.column,
                expected_value=expected,
                actual_value=str(value),
            )
            for reference, value in zip(keys, values, strict=False)
        )
        if total > len(values):
            errors.append(
                CalculationError(
                    code=spec.code,
                    message=(
                        f"{message}: {total - len(values)} additional row(s) omitted "
                        f"beyond sample_cap={sample_cap}"
                    ),
                    severity=spec.severity,
                    category=ErrorCategory.DATA_QUALITY,
                    regulatory_reference=spec.domain.reason,
                    field_name=spec.column,
                    expected_value=expected,
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


def bundle_frames(bundle: RawDataBundle) -> dict[str, pl.LazyFrame | None]:
    """Every input frame the domain gate visits, keyed by ``TABLE_SCHEMAS`` name.

    Hoisted out of :func:`validate_bundle_values` so it is a fact a checker can
    read rather than a literal buried in a loop:
    ``scripts/check_input_domains.py`` asserts that every schema carrying a
    declared domain appears here. A domain nobody validates is guard-shaped
    code that reads as coverage — the same failure ``arch_check`` check 20
    stops on the function side, one level down at the declaration.

    The nested CCR / SFT leaves are reached through their composite bundles
    (``RawDataBundle.ccr`` / ``.sft``), which are None for firms with no
    derivative or SFT book.
    """
    frames: dict[str, pl.LazyFrame | None] = {
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
        "ciu_holdings": bundle.ciu_holdings,
        "fx_rates": bundle.fx_rates,
        "facility_mappings": bundle.facility_mappings,
        "model_permissions": bundle.model_permissions,
        "securitisation_allocations": bundle.securitisation_allocations,
        "cva_counterparties": bundle.cva_counterparties,
        "cva_hedges": bundle.cva_hedges,
    }
    if bundle.ccr is not None:
        frames["ccr.trades"] = bundle.ccr.trades.trades
        frames["ccr.netting_sets"] = bundle.ccr.netting_sets.netting_sets
        frames["ccr.margin_agreements"] = bundle.ccr.margin_agreements.margin_agreements
        frames["ccr.ccr_collateral"] = bundle.ccr.ccr_collateral.ccr_collateral
        if bundle.ccr.failed_trades is not None:
            frames["ccr.failed_trades"] = bundle.ccr.failed_trades.failed_trades
        frames["ccr.default_fund_contributions"] = bundle.ccr.default_fund_contributions
    if bundle.sft is not None:
        frames["sft.trades"] = bundle.sft.trades.sft_trades
        if bundle.sft.collateral is not None:
            frames["sft.collateral"] = bundle.sft.collateral.sft_collateral
    return frames


def validate_bundle_values(
    bundle: RawDataBundle,
    constraints: dict[str, dict[str, set[str]]] | None = None,
) -> list[CalculationError]:
    """
    Validate the input domain of every column in a RawDataBundle.

    The whole-bundle input gate. Iterates over every table in the bundle
    (:func:`bundle_frames`) and, per table, checks:

    - **Declared domains** — every ``ColumnSpec.domain`` the table's schema
      declares and the frame carries (:func:`_validate_declared_domains`),
      one ``.collect()`` per table, with the offending row named.
    - **Categorical domains** against the constraints registry (DQ006), all
      columns batched into a single ``.collect()``.
    - **Exposure-table rules** — unreferenced negative on-balance amounts
      (DQ010).
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

    all_errors: list[CalculationError] = []

    for table_name, lf in bundle_frames(bundle).items():
        if lf is None:
            continue
        table_constraints = constraints.get(table_name, {})
        if table_constraints:
            errors = _validate_table_columns_batched(lf, table_constraints, table_name)
            all_errors.extend(errors)

        # Declared input domains. One collect per table; a no-op for a table
        # whose schema declares none.
        all_errors.extend(_validate_declared_domains(lf, table_name))

        # A negative on-balance amount is the Art. 195/219 netting convention,
        # so it is NOT a declared-domain violation — only an UNREFERENCED one
        # is, and that needs a second column to decide.
        if table_name in {"facilities", "loans", "contingents"}:
            all_errors.extend(_validate_negative_amounts_without_netting(lf, table_name))

        # PRA PS1/26 Art. 120(2B) / Art. 122(3): short-term rating rows must
        # carry a scope (which exposure they attach to). Flag rows that violate
        # the is_short_term ↔ scope_type/scope_id contract.
        if table_name == "ratings":
            all_errors.extend(_validate_short_term_rating_scope(lf))

    # Cross-table referential integrity for the M:N collateral-links table.
    all_errors.extend(validate_collateral_links(bundle))

    # Declared foreign keys (DQ005 / DQ001) and natural-key uniqueness (DQ004).
    # Both are cross-row / cross-table facts, so they follow the per-table pass.
    all_errors.extend(validate_referential_integrity(bundle))
    all_errors.extend(validate_duplicate_keys(bundle))

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


# =============================================================================
# DECLARED REFERENTIAL INTEGRITY
# =============================================================================
#
# The cross-table half of the input gate. ``_validate_declared_domains`` above
# asks whether a value is admissible on its own; this asks whether it RESOLVES.
#
# Why reporting and not rejecting. Every counterparty-attribute join in the
# hierarchy stage is ``how="left"`` and has to stay that way: an inner join
# would drop the exposure, and an exposure that has left the portfolio is worse
# than one priced off a fallback — its capital is simply gone and no total says
# so. So the row survives, takes the fallback treatment its declaration names,
# and this gate is what makes the substitution visible. Nothing here changes a
# number; it changes what the run says about the number.
#
# Why the input gate and not the join. The information is richer here. At the
# join the miss is a null obligor attribute, indistinguishable from an obligor
# row that exists and simply has no rating — and the reference that was
# supplied, which is what an operator needs to repair the feed, has already
# been consumed. The gate also runs on BOTH pipeline entries (the file loader
# and ``run_with_data``), where a detector inside a stage would additionally
# have to survive every future re-ordering of the fold.

#: Kind labels for the two referential findings, carried through the single
#: collect below rather than evaluated as two separate queries.
_KIND_ORPHAN = "orphan"
_KIND_ABSENT = "absent"


def validate_referential_integrity(
    bundle: RawDataBundle,
    sample_cap: int = 5,
) -> list[CalculationError]:
    """Flag input rows whose DECLARED foreign key is broken or never supplied.

    The generic reader of ``data/schemas.py``'s ``TABLE_FOREIGN_KEYS``. For
    every declared link whose child column and parent key are both present, an
    anti-join finds the values that resolve to nothing (``DQ005``) and a null
    filter finds the rows that assert no link at all (``DQ001``). Both are
    expressed lazily and unioned, so the whole registry costs ONE ``.collect()``
    however many links are declared.

    The two findings are deliberately not merged. They reach the same engine
    fallback, but they are repaired in different files — an orphan needs the
    PARENT feed extended or corrected, an absent reference needs this row's
    column populated — and downstream they are indistinguishable, so the
    distinction has to be drawn here or not at all. See
    :func:`~rwa_calc.contracts.errors.absent_reference_error`.

    Follows the sampling contract of :func:`_collect_domain_violations` exactly:
    up to ``sample_cap`` row-named errors per (table, column, kind), then one
    summary carrying the truthful omitted count. A broken parent feed makes
    EVERY child row an orphan, and one error per row would bury the finding it
    is reporting.

    A link whose parent frame is absent from the bundle is skipped rather than
    reported as wholly orphaned: "no counterparties table was supplied" is a
    statement about the load, which the loader already makes, and re-reporting
    it once per exposure row would be the loudest possible way to say it.

    Args:
        bundle: RawDataBundle to validate.
        sample_cap: Maximum row-named errors per (table, column, kind).

    Returns:
        List of CalculationError objects (empty when every link resolves).
    """
    from rwa_calc.data.schemas import TABLE_FOREIGN_KEYS, TABLE_KEY_COLUMNS

    frames = bundle_frames(bundle)
    plans: list[pl.LazyFrame] = []
    declarations: dict[tuple[str, str], ForeignKey] = {}

    for table, foreign_keys in TABLE_FOREIGN_KEYS.items():
        child = frames.get(table)
        if child is None:
            continue
        child_columns = set(child.collect_schema().names())
        key_column = TABLE_KEY_COLUMNS.get(table)
        if key_column not in child_columns:
            key_column = None
        for foreign_key in foreign_keys:
            parent = _checkable_parent(frames, child_columns, foreign_key)
            if parent is None:
                continue
            declarations[table, foreign_key.column] = foreign_key
            plans.extend(_referential_plans(child, key_column, parent, table, foreign_key))

    if not plans:
        return []

    found = pl.concat(plans, how="vertical").collect()
    if found.height == 0:
        return []

    groups = found.sort(["_table", "_column", "_kind", "_reference"]).partition_by(
        ["_table", "_column", "_kind"], as_dict=True, maintain_order=True
    )
    errors: list[CalculationError] = []
    for (table, column, kind), rows in groups.items():
        errors.extend(
            _referential_errors(
                declaration=declarations[table, column],
                table=table,
                kind=kind,
                rows=rows,
                sample_cap=sample_cap,
            )
        )
    return errors


def validate_duplicate_keys(bundle: RawDataBundle) -> list[CalculationError]:
    """Flag input tables whose natural key names more than one row (``DQ004``).

    Reads ``data/schemas.py``'s ``TABLE_UNIQUE_KEYS`` — the tables where a
    repeated key is silent data loss rather than a visible fan-out. One
    ``.collect()`` for the whole registry.

    **Uncapped, one error per duplicated key**, breaking with the ``sample_cap``
    contract the rest of this module follows. The reason is that the two other
    gates sample a property of a COLUMN — "this column held 900 out-of-domain
    values" locates the repair whichever 5 rows are named — whereas a duplicate
    key is a property of a ROW, and a sampled duplicate leaves every un-sampled
    row exactly as unaccounted-for as it was before this gate existed. The
    population is bounded by the number of DISTINCT duplicated keys, which is
    zero on well-formed input and equals the corruption on broken input, so the
    cost scales with the fault rather than with the portfolio.

    Args:
        bundle: RawDataBundle to validate.

    Returns:
        List of CalculationError objects (empty when every key is unique).
    """
    from rwa_calc.data.schemas import TABLE_UNIQUE_KEYS

    frames = bundle_frames(bundle)
    plans: list[pl.LazyFrame] = []
    for table, key_column in TABLE_UNIQUE_KEYS.items():
        lf = frames.get(table)
        if lf is None or key_column not in set(lf.collect_schema().names()):
            continue
        plans.append(
            lf.select(pl.col(key_column).cast(pl.String).alias("_value"))
            .drop_nulls()
            .group_by("_value")
            .len("_count")
            .filter(pl.col("_count") > 1)
            .with_columns(
                pl.lit(table).alias("_table"),
                pl.lit(key_column).alias("_column"),
            )
        )

    if not plans:
        return []

    duplicated = pl.concat(plans, how="vertical").collect()
    return [
        duplicate_input_key_error(
            table=row["_table"],
            column=row["_column"],
            value=row["_value"],
            count=int(row["_count"]),
            names_a_counterparty=row["_table"] == "counterparties",
        )
        for row in duplicated.sort(["_table", "_value"]).iter_rows(named=True)
    ]


def _checkable_parent(
    frames: dict[str, pl.LazyFrame | None],
    child_columns: set[str],
    foreign_key: ForeignKey,
) -> pl.LazyFrame | None:
    """The parent frame a declared link can actually be checked against.

    None means "not checkable on this bundle", which is a SKIP rather than a
    finding, for the reason the public docstring gives: an absent parent table
    is a statement about the load that the loader already makes, and turning it
    into one orphan error per child row would be the loudest possible way to
    repeat it. The same holds for the columns — a link whose child or parent
    column was never supplied has nothing to resolve.
    """
    parent = frames.get(foreign_key.parent_table)
    if parent is None or foreign_key.column not in child_columns:
        return None
    if foreign_key.parent_column not in set(parent.collect_schema().names()):
        return None
    return parent


def _referential_plans(
    child: pl.LazyFrame,
    key_column: str | None,
    parent: pl.LazyFrame,
    table: str,
    foreign_key: ForeignKey,
) -> list[pl.LazyFrame]:
    """The orphan and absent-reference plans for one declared link.

    Both carry their own ``(_table, _column, _kind)`` labels so the caller can
    union every declared link into a single frame and pay for one collect.
    ``key_column`` may be None for a table with no single-column identity; the
    per-row errors then carry no ``exposure_reference`` rather than the link
    being skipped.
    """
    reference = (
        pl.col(key_column).cast(pl.String)
        if key_column is not None
        else pl.lit(None, dtype=pl.String)
    )
    pairs = child.select(
        reference.alias("_reference"),
        pl.col(foreign_key.column).cast(pl.String).alias("_value"),
    )
    parent_keys = (
        parent.select(pl.col(foreign_key.parent_column).cast(pl.String).alias("_value"))
        .drop_nulls()
        .unique()
    )
    labels = (pl.lit(table).alias("_table"), pl.lit(foreign_key.column).alias("_column"))
    orphans = (
        pairs.filter(pl.col("_value").is_not_null())
        .join(parent_keys, on="_value", how="anti")
        .with_columns(*labels, pl.lit(_KIND_ORPHAN).alias("_kind"))
    )
    absent = pairs.filter(pl.col("_value").is_null()).with_columns(
        *labels, pl.lit(_KIND_ABSENT).alias("_kind")
    )
    return [orphans, absent]


def _referential_errors(
    *,
    declaration: ForeignKey,
    table: str,
    kind: str,
    rows: pl.DataFrame,
    sample_cap: int,
) -> list[CalculationError]:
    """Turn one (table, column, kind) group of offending rows into errors."""
    names_counterparty = declaration.parent_table == "counterparties"
    sampled = rows.head(sample_cap)
    errors: list[CalculationError] = [
        orphan_reference_error(
            table=table,
            column=declaration.column,
            parent_table=declaration.parent_table,
            value=row["_value"],
            reference=row["_reference"],
            counterparty_reference=row["_value"] if names_counterparty else None,
            reason=declaration.reason,
        )
        if kind == _KIND_ORPHAN
        else absent_reference_error(
            table=table,
            column=declaration.column,
            parent_table=declaration.parent_table,
            reference=row["_reference"],
            reason=declaration.reason,
        )
        for row in sampled.iter_rows(named=True)
    ]

    omitted = rows.height - sampled.height
    if omitted:
        detail = (
            f"resolve to no row in '{declaration.parent_table}'"
            if kind == _KIND_ORPHAN
            else f"assert no link to '{declaration.parent_table}'"
        )
        errors.append(
            CalculationError(
                code=ERROR_ORPHAN_REFERENCE if kind == _KIND_ORPHAN else ERROR_MISSING_FIELD,
                message=(
                    f"[{table}] '{declaration.column}': {omitted} additional row(s) "
                    f"that {detail} omitted beyond sample_cap={sample_cap}"
                ),
                severity=ErrorSeverity.ERROR,
                category=ErrorCategory.DATA_QUALITY,
                regulatory_reference=declaration.reason,
                field_name=declaration.column,
                expected_value=f"a {declaration.parent_table} reference",
            )
        )
    return errors


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


def validate_branch_reasons(
    bundle: AggregatedResultBundle,
    sample_cap: int = 5,
) -> list[CalculationError]:
    """Raise BR001 for every row whose branch reason reads ``UNKNOWN_FALLBACK``.

    This is the enforcement half of
    ``docs/plans/test-space-correctness-proposal.md`` Phase 3. Emitting a
    ``*_branch_reason`` column beside the value only *records* that the engine
    could not justify a row's treatment; it takes an error to make the record
    reach anyone. The invariant — **no row lands on ``UNKNOWN_FALLBACK``
    without an accompanying error** — is therefore established here at the
    pipeline exit rather than asserted in a test, so it holds on customer data
    and not merely on ours.

    Runs at the exit rather than inside each producing stage on purpose: the
    exit already materialises the results frame for
    :func:`validate_aggregated_bundle`, so the scan is folded into a collect
    that is already paid for. Instrumenting inside a lazy stage would have cost
    one extra materialisation per instrumented path.

    Severity is WARNING, deliberately. An ``UNKNOWN_FALLBACK`` row is not
    provably wrong — the fallback value may well be the right answer — it is
    *unjustified*, which is a different claim. ERROR here would have made the
    two known-open defects this instrument was built to expose (P1.333, and
    the A-IRB rows carrying no LGD from any source) fail every run that touches
    them, and a gate that reddens on a pre-existing defect gets switched off
    rather than fixed. The census (``scripts/check_branch_census.py``) is what
    ratchets the population; this error is what names the rows.

    Follows :func:`validate_aggregated_bundle`'s sampling contract exactly: up
    to ``sample_cap`` row-named errors per column, then one summary carrying
    the omitted count. ``tests/robustness/harness.py`` clause (c) already
    depends on that shape, so a new code that named every row would change the
    triage arithmetic of a suite that has nothing to do with this one.

    Args:
        bundle: AggregatedResultBundle to inspect.
        sample_cap: Maximum per-row errors emitted per column (default 5).

    Returns:
        List of CalculationError objects (empty when no row is unjustified).
    """
    results_lf = bundle.results
    schema_names = set(results_lf.collect_schema().names())
    if "exposure_reference" not in schema_names:
        return []

    errors: list[CalculationError] = []
    for column in BRANCH_REASON_VOCABULARIES:
        if column not in schema_names:
            continue
        offending = (
            results_lf.filter(pl.col(column).cast(pl.String) == UNKNOWN_FALLBACK)
            .select("exposure_reference")
            .collect()
        )
        total = offending.height
        if total == 0:
            continue

        message = (
            f"{column} is {UNKNOWN_FALLBACK}: the deciding predicate could not be "
            "evaluated, or a value was substituted for absent input, so this row's "
            "treatment is unjustified rather than merely defaulted"
        )
        errors.extend(
            CalculationError(
                code=ERROR_UNKNOWN_BRANCH_FALLBACK,
                message=message,
                severity=ErrorSeverity.WARNING,
                category=ErrorCategory.DATA_QUALITY,
                exposure_reference=row["exposure_reference"],
                field_name=column,
                actual_value=UNKNOWN_FALLBACK,
            )
            for row in offending.head(sample_cap).iter_rows(named=True)
        )

        if total > sample_cap:
            errors.append(
                CalculationError(
                    code=ERROR_UNKNOWN_BRANCH_FALLBACK,
                    message=(
                        f"{message}: {total - sample_cap} additional row(s) omitted "
                        f"beyond sample_cap={sample_cap}"
                    ),
                    severity=ErrorSeverity.WARNING,
                    category=ErrorCategory.DATA_QUALITY,
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
