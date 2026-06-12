"""
Producer-sealed stage-edge contracts.

Pipeline position:
    Shared contracts-layer primitive — each pipeline stage seals its output
    frame against its edge contract at stage exit (via
    ``engine.materialise.materialise_sealed_edge``), and the frozen bundles
    validate the resulting brand in ``__post_init__``.

Key responsibilities:
- ``EdgeColumn`` / ``EdgeContract``: per-edge column declarations with
  null-semantics annotations and regulatory citations
- ``EdgeContract.conform``: assert required columns + dtypes (violations
  RAISE — a producer breaking its own output contract is a programming
  error, not a data-quality error), inject producer-owned defaults for
  absent optional columns, fill present-but-null Booleans (and only
  Booleans), strip undeclared scratch columns, emit canonical column order
- ``seal`` / ``sealed_edge_of``: brand a conformed frame with its edge name;
  the brand is an instance attribute and deliberately does NOT survive any
  frame transformation — a transformed frame is no longer the sealed frame

Conservatism gate:
    ``fill_null_default`` is legal on Boolean columns only, enforced when
    the contract is DECLARED. Float/String nulls are never filled — a silent
    ``0.0`` EAD/provision understates RWA (anti-conservative). Broadening
    this requires Risk sign-off; see ``data/column_spec.py`` and
    ``tests/contracts/test_boolean_defaults_only.py``.

References:
- docs/plans/target-architecture-migration.md (Phase 3)
- docs/plans/engine-defensiveness-boundary-hardening.md (root cause: no
  producer-enforced inter-stage column contract)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    from collections.abc import Mapping

    from rwa_calc.data.column_spec import ColumnSpec

_BRAND_ATTR = "_rwa_sealed_edge"


class EdgeContractViolation(Exception):
    """A frame failed its edge contract, or a bundle field lacks its brand.

    This is the programming-error channel: a producing stage emitting a
    frame that violates its own declared output contract is a code defect,
    never a data-quality condition — so it raises instead of accumulating
    a ``CalculationError``.
    """


@dataclass(frozen=True, slots=True)
class EdgeColumn:
    """Declarative contract for one column at a stage edge.

    Attributes:
        dtype: Exact Polars dtype the producer emits. A mismatch is a
            contract violation — ``conform`` never re-casts.
        required: When True the producer must emit the column; ``conform``
            raises if it is absent. When False an absent column is injected
            as ``default`` cast to ``dtype``.
        default: Producer-owned value injected when an optional column is
            absent. ``None`` injects a typed null column. Must be ``None``
            for required columns (the producer emits them; a default would
            be dead config).
        fill_null_default: Fill present-but-null values with ``default``.
            Boolean columns only — enforced at contract declaration
            (conservatism gate; Float/String nulls are never filled).
        null_meaning: Documented semantics of a null value (e.g. tri-state
            flags where null means "unknown", which must not collapse to a
            filled value).
        citation: Regulatory citation for derived columns (e.g.
            ``effectively_secured`` ← CRR Art. 230).
    """

    dtype: pl.DataType
    required: bool = True
    default: object = None
    fill_null_default: bool = False
    null_meaning: str | None = None
    citation: str | None = None


@dataclass(frozen=True)
class EdgeContract:
    """The full column contract for one stage edge.

    ``columns`` insertion order is the edge's canonical column order —
    ``conform`` re-orders its output to match.
    """

    name: str
    columns: dict[str, EdgeColumn] = field(default_factory=dict)

    def __post_init__(self) -> None:
        problems: list[str] = []
        for col_name, col in self.columns.items():
            if col.fill_null_default and col.dtype != pl.Boolean:
                problems.append(
                    f"{col_name}: fill_null_default is legal on Boolean columns only "
                    f"(got {col.dtype}); Float/String null fills are anti-conservative "
                    "and require Risk sign-off"
                )
            if col.fill_null_default and col.default is None:
                problems.append(f"{col_name}: fill_null_default=True requires a non-None default")
            if col.required and col.default is not None:
                problems.append(
                    f"{col_name}: a default on a required column is dead config — "
                    "drop the default or mark the column optional"
                )
        if problems:
            raise ValueError(f"invalid edge contract '{self.name}':\n  " + "\n  ".join(problems))

    def conform(self, lf: pl.LazyFrame) -> pl.LazyFrame:
        """Validate ``lf`` against this contract and normalise its shape.

        Raises ``EdgeContractViolation`` (listing every problem at once)
        when a required column is missing or a declared column's dtype
        does not match. Otherwise: injects absent optional columns with
        their producer-owned defaults, fills present-but-null Boolean
        columns declared ``fill_null_default``, strips undeclared scratch
        columns, and emits columns in contract order.
        """
        schema = lf.collect_schema()
        present = dict(schema)

        violations: list[str] = []
        for col_name, col in self.columns.items():
            actual = present.get(col_name)
            if actual is None:
                if col.required:
                    violations.append(f"missing required column '{col_name}'")
                continue
            if actual != col.dtype:
                violations.append(
                    f"column '{col_name}' has dtype {actual}, contract requires {col.dtype}"
                )
        if violations:
            raise EdgeContractViolation(
                f"edge '{self.name}' contract violated:\n  " + "\n  ".join(violations)
            )

        additions = [
            pl.lit(col.default).cast(col.dtype).alias(col_name)
            for col_name, col in self.columns.items()
            if col_name not in present
        ]
        if additions:
            lf = lf.with_columns(additions)

        fills = [
            pl.col(col_name).fill_null(pl.lit(col.default).cast(pl.Boolean))
            for col_name, col in self.columns.items()
            if col.fill_null_default and col_name in present
        ]
        if fills:
            lf = lf.with_columns(fills)

        return lf.select(list(self.columns))

    def conform_lenient(self, lf: pl.LazyFrame) -> tuple[pl.LazyFrame, list[str]]:
        """Input-boundary variant of ``conform`` — external data never raises.

        The loader boundary accumulates data-quality errors instead of
        raising (input validation is non-blocking), so this variant:
        injects missing REQUIRED columns as typed nulls and returns their
        names (the caller maps them to ``CalculationError``s), casts
        mismatched dtypes with ``strict=False`` (invalid values become
        null — never an exception), then applies the same default
        injection, Boolean-only null fill, scratch strip, and canonical
        order as ``conform``.
        """
        schema = lf.collect_schema()
        present = dict(schema)

        missing_required = [
            col_name
            for col_name, col in self.columns.items()
            if col.required and col_name not in present
        ]

        additions = [
            pl.lit(None if col.required else col.default).cast(col.dtype).alias(col_name)
            for col_name, col in self.columns.items()
            if col_name not in present
        ]
        if additions:
            lf = lf.with_columns(additions)

        casts = [
            pl.col(col_name).cast(col.dtype, strict=False)
            for col_name, col in self.columns.items()
            if col_name in present and present[col_name] != col.dtype
        ]
        if casts:
            lf = lf.with_columns(casts)

        # Boolean fills strictly AFTER the cast pass — an inferred pl.Null
        # column must be Boolean before fill_null can coerce its literal
        # (ordering is load-bearing; mirrors loader.enforce_schema).
        fills = [
            pl.col(col_name).fill_null(pl.lit(col.default).cast(pl.Boolean))
            for col_name, col in self.columns.items()
            if col.fill_null_default and col_name in present
        ]
        if fills:
            lf = lf.with_columns(fills)

        return lf.select(list(self.columns)), missing_required

    def empty_frame(self) -> pl.LazyFrame:
        """A zero-row, schema-complete, sealed frame for this edge."""
        empty = pl.LazyFrame(schema={col_name: col.dtype for col_name, col in self.columns.items()})
        return brand(empty, self.name)


def seal(lf: pl.LazyFrame, edge: EdgeContract) -> pl.LazyFrame:
    """Conform ``lf`` to ``edge`` and brand the result.

    The contracts-level primitive: pipeline stages go through
    ``engine.materialise.materialise_sealed_edge`` (which also materialises
    the plan); tests and fixture builders call ``seal`` directly.
    """
    return brand(edge.conform(lf), edge.name)


def seal_lenient(lf: pl.LazyFrame, edge: EdgeContract) -> tuple[pl.LazyFrame, list[str]]:
    """Leniently conform ``lf`` to ``edge``, brand it, report missing columns.

    The loader-boundary seal: missing required columns are injected as
    typed nulls and returned by name so the caller can accumulate
    data-quality errors instead of raising.
    """
    conformed, missing = edge.conform_lenient(lf)
    return brand(conformed, edge.name), missing


def brand(lf: pl.LazyFrame, edge_name: str) -> pl.LazyFrame:
    """Mark ``lf`` as sealed for ``edge_name``.

    The brand is a plain instance attribute: any transformation returns a
    NEW LazyFrame without it, so only the exact object that went through
    the seal carries the brand. That is load-bearing — a derived frame has
    not been validated and must not claim to be sealed.
    """
    setattr(lf, _BRAND_ATTR, edge_name)
    return lf


def sealed_edge_of(lf: pl.LazyFrame) -> str | None:
    """The edge name ``lf`` was sealed for, or None if unsealed."""
    return getattr(lf, _BRAND_ATTR, None)


def require_brand(
    lf: pl.LazyFrame,
    edge_name: str | tuple[str, ...],
    *,
    owner: str,
    field_name: str,
) -> None:
    """Raise unless ``lf`` carries one of the accepted edge brands.

    Called from bundle ``__post_init__`` for fields registered in
    ``contracts.bundles.SEALED_FRAME_FIELDS``. A tuple means the field
    legitimately carries more than one producer's seal (e.g. a frame that
    is replaced by a later optional stage sealing the same shape).
    """
    accepted = (edge_name,) if isinstance(edge_name, str) else edge_name
    found = sealed_edge_of(lf)
    if found in accepted:
        return
    wanted = " or ".join(f"'{name}'" for name in accepted)
    if found is None:
        raise EdgeContractViolation(
            f"{owner}.{field_name} requires a frame sealed for edge {wanted}, "
            "got an unsealed frame — construct it via the stage producer or a "
            "contract-derived test builder (transforming a sealed frame removes "
            "its brand)"
        )
    raise EdgeContractViolation(
        f"{owner}.{field_name} requires a frame sealed for edge {wanted}, "
        f"got a frame sealed for '{found}'"
    )


def edge_columns_from_specs(
    schema: Mapping[str, ColumnSpec],
    *,
    boolean_fill: bool = True,
) -> dict[str, EdgeColumn]:
    """Seed edge columns from an existing ``ColumnSpec`` schema.

    Maps ``ColumnSpec(dtype, default, required)`` onto ``EdgeColumn``; with
    ``boolean_fill`` (the default), Boolean columns that carry a non-None
    default also fill present-but-null values — preserving the loader's
    ``enforce_schema`` semantics when an input-table schema becomes an edge
    contract.
    """
    return {
        col_name: EdgeColumn(
            dtype=spec.dtype,
            required=spec.required,
            default=None if spec.required else spec.default,
            fill_null_default=(
                boolean_fill
                and not spec.required
                and spec.dtype == pl.Boolean
                and spec.default is not None
            ),
        )
        for col_name, spec in schema.items()
    }


# ---------------------------------------------------------------------------
# Edge definitions — loader (raw input tables)
# ---------------------------------------------------------------------------


def _raw_table_edges() -> dict[str, EdgeContract]:
    """Per-table loader edge contracts, seeded from the input schemas.

    Keys are ``RawDataBundle`` frame field names; edge names carry the
    ``raw_`` prefix. The loader seals every table it loads against these
    (leniently — missing required columns become data-quality errors), and
    the contract-derived test builders construct frames through the same
    seal so test bundles are shape-identical to production-loaded ones.
    """
    from rwa_calc.data import schemas

    table_schemas = {
        "facilities": schemas.FACILITY_SCHEMA,
        "loans": schemas.LOAN_SCHEMA,
        "counterparties": schemas.COUNTERPARTY_SCHEMA,
        "facility_mappings": schemas.FACILITY_MAPPING_SCHEMA,
        "org_mappings": schemas.ORG_MAPPING_SCHEMA,
        "lending_mappings": schemas.LENDING_MAPPING_SCHEMA,
        "contingents": schemas.CONTINGENTS_SCHEMA,
        "collateral": schemas.COLLATERAL_SCHEMA,
        "collateral_links": schemas.COLLATERAL_LINK_SCHEMA,
        "guarantees": schemas.GUARANTEE_SCHEMA,
        "provisions": schemas.PROVISION_SCHEMA,
        "ratings": schemas.RATINGS_SCHEMA,
        "equity_exposures": schemas.EQUITY_EXPOSURE_SCHEMA,
        "ciu_holdings": schemas.CIU_HOLDINGS_SCHEMA,
        "specialised_lending": schemas.SPECIALISED_LENDING_SCHEMA,
        "fx_rates": schemas.FX_RATES_SCHEMA,
        "model_permissions": schemas.MODEL_PERMISSIONS_SCHEMA,
        "securitisation_allocations": schemas.SECURITISATION_ALLOCATION_SCHEMA,
    }
    return {
        field_name: EdgeContract(name=f"raw_{field_name}", columns=edge_columns_from_specs(schema))
        for field_name, schema in table_schemas.items()
    }


RAW_TABLE_EDGES: dict[str, EdgeContract] = _raw_table_edges()


# ---------------------------------------------------------------------------
# Edge definitions — hierarchy exit
# ---------------------------------------------------------------------------


def _hierarchy_resolved_columns() -> dict[str, EdgeColumn]:
    """The 78 columns HierarchyResolver always emits on the unified frame.

    Seeded from the observed schema (scripts/dump_hierarchy_exit_schema.py,
    2026-06-12): shape-stable across minimal/rich inputs and CRR/B31 after
    the loader-edge guard deletion — every column is required because the
    producer emits all of them unconditionally (absent inputs surface as
    typed nulls / neutral values, never as absent columns).
    """
    return {
        "exposure_reference": EdgeColumn(dtype=pl.String),
        "exposure_type": EdgeColumn(dtype=pl.String),
        "product_type": EdgeColumn(dtype=pl.String),
        "book_code": EdgeColumn(dtype=pl.String),
        "counterparty_reference": EdgeColumn(dtype=pl.String),
        "value_date": EdgeColumn(dtype=pl.Date),
        "maturity_date": EdgeColumn(dtype=pl.Date),
        "currency": EdgeColumn(dtype=pl.String),
        "drawn_amount": EdgeColumn(dtype=pl.Float64),
        "interest": EdgeColumn(dtype=pl.Float64),
        "undrawn_amount": EdgeColumn(dtype=pl.Float64),
        "nominal_amount": EdgeColumn(dtype=pl.Float64),
        "lgd": EdgeColumn(
            dtype=pl.Float64,
            null_meaning="null = no modelled LGD supplied (FIRB/SA rows)",
        ),
        "lgd_unsecured": EdgeColumn(dtype=pl.Float64),
        "has_sufficient_collateral_data": EdgeColumn(
            dtype=pl.Boolean,
            citation="CRR Art. 169A/169B",
            null_meaning="loader fills null->False; False = Foundation fallback",
        ),
        "beel": EdgeColumn(
            dtype=pl.Float64,
            citation="PS1/26 Art. 181(1)(h)(ii)",
        ),
        "seniority": EdgeColumn(dtype=pl.String),
        "risk_type": EdgeColumn(dtype=pl.String),
        "underlying_risk_type": EdgeColumn(dtype=pl.String),
        "ccf_modelled": EdgeColumn(dtype=pl.Float64),
        "ead_modelled": EdgeColumn(dtype=pl.Float64),
        "is_short_term_trade_lc": EdgeColumn(dtype=pl.Boolean),
        "is_obs_commitment": EdgeColumn(dtype=pl.Boolean),
        "is_uk_residential_mortgage_commitment": EdgeColumn(dtype=pl.Boolean),
        "is_purchased_receivable_commitment": EdgeColumn(dtype=pl.Boolean),
        "is_payroll_loan": EdgeColumn(dtype=pl.Boolean),
        "is_buy_to_let": EdgeColumn(dtype=pl.Boolean),
        "is_under_construction": EdgeColumn(dtype=pl.Boolean),
        "has_one_day_maturity_floor": EdgeColumn(dtype=pl.Boolean),
        "is_sft": EdgeColumn(dtype=pl.Boolean),
        "effective_maturity": EdgeColumn(dtype=pl.Float64),
        "netting_agreement_reference": EdgeColumn(dtype=pl.String),
        "facility_termination_date": EdgeColumn(dtype=pl.Date),
        "ltv": EdgeColumn(
            dtype=pl.Float64,
            citation="CRR Art. 124-126 / PS1/26 Art. 124C-124K",
            null_meaning="null = no loan-level LTV; never fabricated",
        ),
        "property_type": EdgeColumn(dtype=pl.String),
        "has_income_cover": EdgeColumn(dtype=pl.Boolean, citation="CRR Art. 126(2)"),
        "is_defaulted": EdgeColumn(dtype=pl.Boolean, citation="CRR Art. 178"),
        "purchased_receivables_subtype": EdgeColumn(dtype=pl.String),
        "exposure_collateral_type": EdgeColumn(dtype=pl.String),
        "exposure_security_cqs": EdgeColumn(dtype=pl.Int8),
        "exposure_security_residual_maturity_years": EdgeColumn(dtype=pl.Float64),
        "ava_amount": EdgeColumn(dtype=pl.Float64, citation="CRR Art. 159"),
        "other_own_funds_reductions": EdgeColumn(dtype=pl.Float64, citation="CRR Art. 159"),
        "original_counterparty_reference": EdgeColumn(dtype=pl.String),
        "mof_risk_type_source": EdgeColumn(dtype=pl.String),
        "is_revolving": EdgeColumn(dtype=pl.Boolean),
        "is_qrre_transactor": EdgeColumn(dtype=pl.Boolean),
        "facility_limit": EdgeColumn(dtype=pl.Float64),
        "source_facility_reference": EdgeColumn(dtype=pl.String),
        "mapped_parent_facility": EdgeColumn(dtype=pl.String),
        "parent_facility_reference": EdgeColumn(dtype=pl.String),
        "exposure_has_parent": EdgeColumn(dtype=pl.Boolean),
        "ancestor_facilities": EdgeColumn(dtype=pl.List(pl.String)),
        "root_facility_reference": EdgeColumn(dtype=pl.String),
        "facility_hierarchy_depth": EdgeColumn(dtype=pl.Int8),
        "cqs": EdgeColumn(
            dtype=pl.Int8,
            null_meaning="external-rating concept only; null = unrated (never inferred)",
        ),
        "pd": EdgeColumn(dtype=pl.Float64),
        "internal_pd": EdgeColumn(
            dtype=pl.Float64,
            null_meaning="null = no internal rating; gates ALL IRB branches",
        ),
        "external_cqs": EdgeColumn(dtype=pl.Int8),
        "external_rating_is_issue_specific": EdgeColumn(
            dtype=pl.Boolean, citation="PS1/26 Art. 139(2B)"
        ),
        "model_id": EdgeColumn(dtype=pl.String),
        "has_short_term_ecai": EdgeColumn(dtype=pl.Boolean),
        "original_currency": EdgeColumn(dtype=pl.String),
        "original_amount": EdgeColumn(dtype=pl.Float64),
        "fx_rate_applied": EdgeColumn(dtype=pl.Float64),
        "is_qualifying_re": EdgeColumn(
            dtype=pl.Boolean,
            null_meaning="hierarchy fills null->True (unreported RE qualifies unless flagged)",
        ),
        "prior_charge_ltv": EdgeColumn(dtype=pl.Float64),
        "total_exposure_amount": EdgeColumn(dtype=pl.Float64),
        "residential_collateral_value": EdgeColumn(dtype=pl.Float64),
        "property_collateral_value": EdgeColumn(dtype=pl.Float64),
        "residential_collateral_value_uncapped": EdgeColumn(dtype=pl.Float64),
        "commercial_collateral_value_uncapped": EdgeColumn(dtype=pl.Float64),
        "has_facility_property_collateral": EdgeColumn(dtype=pl.Boolean),
        "re_collateral_non_qualifying": EdgeColumn(dtype=pl.Boolean),
        "exposure_for_retail_threshold": EdgeColumn(dtype=pl.Float64),
        "lending_group_reference": EdgeColumn(
            dtype=pl.String,
            citation="CRR Art. 4(1)(39)",
            null_meaning="null = group-of-one (no lending-group mapping)",
        ),
        "lending_group_total_exposure": EdgeColumn(dtype=pl.Float64),
        "lending_group_adjusted_exposure": EdgeColumn(dtype=pl.Float64),
    }


HIERARCHY_RESOLVED_EDGE: EdgeContract = EdgeContract(
    name="hierarchy_resolved",
    columns=_hierarchy_resolved_columns(),
)


HIERARCHY_EXIT_EDGE: EdgeContract = EdgeContract(
    name="hierarchy_exit",
    columns={
        **_hierarchy_resolved_columns(),
        # attach_securitisation_lookup runs unconditionally with canonical
        # defaults (1.0 / empty list) when no allocations are supplied, so
        # both columns are REQUIRED at this edge (CRR Art. 244-246).
        "securitisation_residual_pct": EdgeColumn(dtype=pl.Float64, citation="CRR Art. 244"),
        "securitisation_pool_allocations": EdgeColumn(
            dtype=pl.List(pl.Struct({"pool_reference": pl.String, "allocation_pct": pl.Float64})),
            citation="CRR Art. 244",
        ),
    },
)


CCR_EXIT_EDGE: EdgeContract = EdgeContract(
    name="ccr_exit",
    columns={
        **HIERARCHY_EXIT_EDGE.columns,
        # CCR synthetic-row provenance (CRR Art. 274-280 SA-CCR): present on
        # the post-concat frame for every run with a derivatives book —
        # diagonal_relaxed fills them as nulls on traditional lending rows.
        "source_netting_set_id": EdgeColumn(dtype=pl.String),
        "ccr_method": EdgeColumn(dtype=pl.String),
        "cp_is_ccp_client_cleared": EdgeColumn(dtype=pl.Boolean),
        "wwr_lgd_override": EdgeColumn(dtype=pl.Float64),
        "addon_aggregate": EdgeColumn(dtype=pl.Float64, citation="CRR Art. 278"),
        "addon_by_asset_class": EdgeColumn(
            dtype=pl.Struct(
                {
                    "interest_rate": pl.Float64,
                    "fx": pl.Float64,
                    "credit": pl.Float64,
                    "equity": pl.Float64,
                    "commodity": pl.Float64,
                }
            ),
            citation="CRR Art. 277",
        ),
        "pfe_multiplier": EdgeColumn(dtype=pl.Float64, citation="CRR Art. 278"),
        "pfe_addon": EdgeColumn(dtype=pl.Float64),
        "rc_unmargined": EdgeColumn(dtype=pl.Float64, citation="CRR Art. 275"),
        "rc_margined": EdgeColumn(dtype=pl.Float64, citation="CRR Art. 275"),
        "rc": EdgeColumn(dtype=pl.Float64),
        "alpha_applied": EdgeColumn(dtype=pl.Float64, citation="CRR Art. 274(2)"),
        "transitional_add_on": EdgeColumn(dtype=pl.Float64, citation="PS1/26 Art. 274(2A)"),
        "ead_ccr": EdgeColumn(dtype=pl.Float64, citation="CRR Art. 274(3)"),
    },
)
"""The CCR stage exit: the hierarchy_exit shape plus the SA-CCR synthetic-row
provenance columns. Only produced when the run has a derivatives book."""
