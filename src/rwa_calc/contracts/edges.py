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
        inject: Only meaningful with ``required=False``. When False the
            column is CONDITIONAL — declared (validated, never stripped)
            when the producing sub-step ran, but NOT injected when absent.
            Preserves presence semantics for downstream consumers whose
            branches are still presence-gated; flip to inject=True
            consumer-group by consumer-group as those guards are deleted
            (verified null-path-equivalent). Lesson recorded 2026-06-12:
            blanket-injecting guarantee columns made the SA/IRB
            substitution machinery execute on null data and moved IRB risk
            weights — caught by the parity gate.
    """

    dtype: pl.DataType
    required: bool = True
    default: object = None
    fill_null_default: bool = False
    null_meaning: str | None = None
    citation: str | None = None
    inject: bool = True


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
            if col.required and not col.inject:
                problems.append(
                    f"{col_name}: inject=False is meaningless on a required column — "
                    "required asserts presence; mark the column optional"
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
            if col_name not in present and col.inject
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

        emitted = [
            col_name for col_name, col in self.columns.items() if col.inject or col_name in present
        ]
        return lf.select(emitted)

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
            if col_name not in present and (col.required or col.inject)
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

        emitted = [
            col_name
            for col_name, col in self.columns.items()
            if col.required or col.inject or col_name in present
        ]
        return lf.select(emitted), missing_required

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


# ---------------------------------------------------------------------------
# Edge definitions — counterparty lookup (hierarchy side-products)
# ---------------------------------------------------------------------------
# The four CounterpartyLookup frames are hierarchy-internal products consumed
# by the classifier (cp_* enrichment join) and CRM (guarantor resolution).
# Seeded from the observed schemas (2026-06-12), verified shape-stable with
# and without optional input tables (org_mappings / ratings sealed at the
# loader edge guarantee fixed shapes).

CP_LOOKUP_COUNTERPARTIES_EDGE: EdgeContract = EdgeContract(
    name="cp_lookup_counterparties",
    columns={
        "counterparty_reference": EdgeColumn(dtype=pl.String),
        "counterparty_name": EdgeColumn(dtype=pl.String),
        "entity_type": EdgeColumn(dtype=pl.String),
        "country_code": EdgeColumn(dtype=pl.String),
        "annual_revenue": EdgeColumn(
            dtype=pl.Float64,
            citation="CRR Art. 501(2)(b)",
            null_meaning="null = turnover unknown (assets fallback / no SME factor) — never 0.0",
        ),
        "total_assets": EdgeColumn(dtype=pl.Float64, citation="PS1/26 Art. 153(4)"),
        "default_status": EdgeColumn(dtype=pl.Boolean, citation="CRR Art. 178"),
        "sector_code": EdgeColumn(dtype=pl.String),
        "apply_fi_scalar": EdgeColumn(dtype=pl.Boolean),
        "is_managed_as_retail": EdgeColumn(dtype=pl.Boolean, citation="PS1/26 Art. 123A"),
        "is_natural_person": EdgeColumn(dtype=pl.Boolean),
        "qualifying_property_count": EdgeColumn(dtype=pl.Int32),
        "is_social_housing": EdgeColumn(dtype=pl.Boolean),
        "is_financial_sector_entity": EdgeColumn(dtype=pl.Boolean),
        "scra_grade": EdgeColumn(dtype=pl.String, citation="PS1/26 Art. 121"),
        "is_investment_grade": EdgeColumn(dtype=pl.Boolean),
        "is_ccp_client_cleared": EdgeColumn(dtype=pl.Boolean, citation="CRR Art. 305-306"),
        "borrower_income_currency": EdgeColumn(dtype=pl.String),
        "sovereign_cqs": EdgeColumn(dtype=pl.Int32),
        "local_currency": EdgeColumn(dtype=pl.String),
        "institution_cqs": EdgeColumn(dtype=pl.Int8),
        "eca_score": EdgeColumn(dtype=pl.Int8, citation="CRR Art. 137"),
        "is_core_market_participant": EdgeColumn(dtype=pl.Boolean, citation="CRR Art. 227(3)"),
        "is_qccp": EdgeColumn(dtype=pl.Boolean, citation="CRR Art. 107"),
        "counterparty_type": EdgeColumn(dtype=pl.String),
        "parent_counterparty_reference": EdgeColumn(dtype=pl.String),
        "ultimate_parent_reference": EdgeColumn(dtype=pl.String),
        "counterparty_hierarchy_depth": EdgeColumn(dtype=pl.Int32),
        "cqs": EdgeColumn(dtype=pl.Int8),
        "pd": EdgeColumn(dtype=pl.Float64),
        "internal_pd": EdgeColumn(dtype=pl.Float64),
        "external_cqs": EdgeColumn(dtype=pl.Int8),
        "external_rating_is_issue_specific": EdgeColumn(dtype=pl.Boolean),
        "internal_model_id": EdgeColumn(dtype=pl.String),
        "counterparty_has_parent": EdgeColumn(dtype=pl.Boolean),
    },
)

CP_LOOKUP_PARENTS_EDGE: EdgeContract = EdgeContract(
    name="cp_lookup_parents",
    columns={
        "child_counterparty_reference": EdgeColumn(dtype=pl.String),
        "parent_counterparty_reference": EdgeColumn(dtype=pl.String),
    },
)

CP_LOOKUP_ULTIMATE_PARENTS_EDGE: EdgeContract = EdgeContract(
    name="cp_lookup_ultimate_parents",
    columns={
        "counterparty_reference": EdgeColumn(dtype=pl.String),
        "ultimate_parent_reference": EdgeColumn(dtype=pl.String),
        "hierarchy_depth": EdgeColumn(dtype=pl.Int32),
    },
)

CP_LOOKUP_RATING_INHERITANCE_EDGE: EdgeContract = EdgeContract(
    name="cp_lookup_rating_inheritance",
    columns={
        "counterparty_reference": EdgeColumn(dtype=pl.String),
        # Per-type inheritance: own internal -> parent internal, own
        # external -> parent external, resolved independently. CQS is an
        # external-only concept; internal ratings carry PD.
        "internal_pd": EdgeColumn(dtype=pl.Float64),
        "internal_model_id": EdgeColumn(dtype=pl.String),
        "external_cqs": EdgeColumn(dtype=pl.Int8),
        "external_rating_is_issue_specific": EdgeColumn(
            dtype=pl.Boolean, citation="PS1/26 Art. 139(2B)"
        ),
        "cqs": EdgeColumn(dtype=pl.Int8),
        "pd": EdgeColumn(dtype=pl.Float64),
    },
)

CP_LOOKUP_EDGES: dict[str, EdgeContract] = {
    "counterparties": CP_LOOKUP_COUNTERPARTIES_EDGE,
    "parent_mappings": CP_LOOKUP_PARENTS_EDGE,
    "ultimate_parent_mappings": CP_LOOKUP_ULTIMATE_PARENTS_EDGE,
    "rating_inheritance": CP_LOOKUP_RATING_INHERITANCE_EDGE,
}
"""CounterpartyLookup field name -> edge contract."""


# ---------------------------------------------------------------------------
# Edge definitions — classifier exit
# ---------------------------------------------------------------------------


def _classifier_added_columns() -> dict[str, EdgeColumn]:
    """The columns the classifier adds to the hierarchy frame.

    Seeded from the observed schema (2026-06-12), regime-stable across
    CRR/B31. The model-permission audit columns are OPTIONAL: they exist
    only when a model_permissions table was supplied — declared with null
    defaults so the downstream shape is uniform either way.
    """
    return {
        # cp_* enrichment join from the sealed counterparty lookup
        "cp_entity_type": EdgeColumn(dtype=pl.String),
        "cp_country_code": EdgeColumn(dtype=pl.String),
        "cp_annual_revenue": EdgeColumn(
            dtype=pl.Float64,
            citation="CRR Art. 501(2)(b)",
            null_meaning="null = turnover unknown (assets fallback) — never 0.0",
        ),
        "cp_total_assets": EdgeColumn(dtype=pl.Float64, citation="PS1/26 Art. 153(4)"),
        "cp_default_status": EdgeColumn(dtype=pl.Boolean, citation="CRR Art. 178"),
        "cp_apply_fi_scalar": EdgeColumn(dtype=pl.Boolean),
        "cp_is_managed_as_retail": EdgeColumn(dtype=pl.Boolean, citation="PS1/26 Art. 123A"),
        "cp_is_natural_person": EdgeColumn(dtype=pl.Boolean),
        "cp_qualifying_property_count": EdgeColumn(dtype=pl.Int32),
        "cp_is_social_housing": EdgeColumn(dtype=pl.Boolean),
        "cp_is_financial_sector_entity": EdgeColumn(dtype=pl.Boolean, citation="PS1/26 Art. 147A"),
        "cp_scra_grade": EdgeColumn(dtype=pl.String, citation="PS1/26 Art. 121"),
        "cp_is_investment_grade": EdgeColumn(dtype=pl.Boolean),
        "cp_is_ccp_client_cleared": EdgeColumn(dtype=pl.Boolean, citation="CRR Art. 305-306"),
        "cp_is_qccp": EdgeColumn(dtype=pl.Boolean, citation="CRR Art. 107"),
        "cp_borrower_income_currency": EdgeColumn(dtype=pl.String),
        "cp_sovereign_cqs": EdgeColumn(dtype=pl.Int32),
        "cp_local_currency": EdgeColumn(dtype=pl.String),
        "cp_eca_score": EdgeColumn(dtype=pl.Int8, citation="CRR Art. 137"),
        "cp_institution_cqs": EdgeColumn(dtype=pl.Int8),
        "cp_internal_model_id": EdgeColumn(dtype=pl.String),
        # SME determination (CRR Art. 501 / PS1/26 Art. 153(4))
        "sme_size_metric_gbp": EdgeColumn(dtype=pl.Float64),
        "sme_size_source": EdgeColumn(dtype=pl.String),
        "is_sme": EdgeColumn(dtype=pl.Boolean, citation="CRR Art. 501"),
        # Specialised lending join (null when no SL table)
        "sl_type": EdgeColumn(dtype=pl.String),
        "slotting_category": EdgeColumn(dtype=pl.String, citation="CRR Art. 153(5)"),
        "is_hvcre": EdgeColumn(dtype=pl.Boolean),
        # Exposure classification (CRR Art. 112/147; PS1/26 Art. 112/147)
        "exposure_class_sa": EdgeColumn(dtype=pl.String),
        "exposure_class_irb": EdgeColumn(dtype=pl.String),
        "exposure_class": EdgeColumn(dtype=pl.String, citation="CRR Art. 112"),
        "exposure_class_for_sa": EdgeColumn(dtype=pl.String),
        "exposure_subclass": EdgeColumn(dtype=pl.String),
        "is_mortgage": EdgeColumn(dtype=pl.Boolean),
        "is_infrastructure": EdgeColumn(dtype=pl.Boolean, citation="CRR Art. 501a"),
        "is_adc": EdgeColumn(dtype=pl.Boolean, citation="PS1/26 Art. 124K"),
        "qualifies_as_retail": EdgeColumn(dtype=pl.Boolean, citation="CRR Art. 123"),
        "retail_threshold_exclusion_applied": EdgeColumn(dtype=pl.Boolean),
        "requires_fi_scalar": EdgeColumn(dtype=pl.Boolean),
        "reclassified_to_retail": EdgeColumn(dtype=pl.Boolean),
        "has_property_collateral": EdgeColumn(dtype=pl.Boolean),
        # RE-split precursors consumed by the RealEstateSplitter
        "re_split_target_class": EdgeColumn(dtype=pl.String),
        "re_split_mode": EdgeColumn(dtype=pl.String),
        "re_split_property_type": EdgeColumn(dtype=pl.String),
        "re_split_property_value": EdgeColumn(dtype=pl.Float64),
        "re_split_residential_value": EdgeColumn(dtype=pl.Float64),
        "re_split_commercial_value": EdgeColumn(dtype=pl.Float64),
        "re_split_residential_eligible": EdgeColumn(dtype=pl.Boolean),
        "re_split_commercial_eligible": EdgeColumn(dtype=pl.Boolean),
        "re_split_cre_rental_coverage_met": EdgeColumn(
            dtype=pl.Boolean, citation="CRR Art. 126(2)(d)"
        ),
        "re_split_force_other_re": EdgeColumn(dtype=pl.Boolean),
        # Approach routing
        "approach": EdgeColumn(dtype=pl.String, citation="CRR Art. 143"),
        # Model-permission audit columns — present only when a
        # model_permissions table was supplied; injected as typed nulls
        # otherwise so the downstream shape is uniform.
        "model_airb_permitted": EdgeColumn(dtype=pl.Boolean, required=False),
        "model_firb_permitted": EdgeColumn(dtype=pl.Boolean, required=False),
        "model_slotting_permitted": EdgeColumn(dtype=pl.Boolean, required=False),
        "ppu_reason": EdgeColumn(dtype=pl.String, required=False),
    }


def _classifier_exit_columns() -> dict[str, EdgeColumn]:
    columns = dict(_hierarchy_resolved_columns())
    # Securitisation lookup columns: required in the orchestrated pipeline
    # (the attach is unconditional) but OPTIONAL here so resolver-direct
    # classifier invocation in tests stays constructible — injected as
    # typed nulls in that case.
    columns["securitisation_residual_pct"] = EdgeColumn(
        dtype=pl.Float64, required=False, citation="CRR Art. 244"
    )
    columns["securitisation_pool_allocations"] = EdgeColumn(
        dtype=pl.List(pl.Struct({"pool_reference": pl.String, "allocation_pct": pl.Float64})),
        required=False,
        citation="CRR Art. 244",
    )
    columns.update(_classifier_added_columns())
    return columns


CLASSIFIER_EXIT_EDGE: EdgeContract = EdgeContract(
    name="classifier_exit",
    columns=_classifier_exit_columns(),
)


CLASSIFIER_EXIT_CCR_EDGE: EdgeContract = EdgeContract(
    name="classifier_exit_ccr",
    columns={
        **_classifier_exit_columns(),
        # SA-CCR provenance pass-through — the classifier selects this
        # contract when its input carries the ccr_exit brand.
        **{
            col_name: col
            for col_name, col in CCR_EXIT_EDGE.columns.items()
            if col_name not in HIERARCHY_EXIT_EDGE.columns
        },
    },
)


# ---------------------------------------------------------------------------
# Edge definitions — CRM exit and RE-split exit
# ---------------------------------------------------------------------------


def _crm_added_columns() -> dict[str, EdgeColumn]:
    """The 58 columns the CRM stage adds to the classified frame.

    Seeded from the observed schema (2026-06-12), regime-stable across
    CRR/B31. All required — the CRM chain (provisions -> CCF -> EAD ->
    collateral -> guarantees -> finalise) emits every column
    unconditionally; absent optional input tables surface as neutral
    values / nulls, never as absent columns.
    """
    return {
        # Provision resolution (CRR Art. 111(2)) and CCF (Art. 111 / 166)
        "nominal_after_provision": EdgeColumn(dtype=pl.Float64, citation="CRR Art. 111(2)"),
        "ccf": EdgeColumn(dtype=pl.Float64, citation="CRR Art. 111(1)"),
        "ccf_calculation": EdgeColumn(dtype=pl.String),
        "ccf_original": EdgeColumn(dtype=pl.Float64),
        "ccf_guaranteed": EdgeColumn(dtype=pl.Float64),
        "ccf_unguaranteed": EdgeColumn(dtype=pl.Float64),
        "effective_ccf": EdgeColumn(dtype=pl.Float64),
        "on_bs_for_ead": EdgeColumn(dtype=pl.Float64),
        "on_bs_netting_amount": EdgeColumn(dtype=pl.Float64, citation="CRR Art. 219"),
        "ead_from_ccf": EdgeColumn(dtype=pl.Float64),
        "ead_gross": EdgeColumn(dtype=pl.Float64),
        "ead_pre_crm": EdgeColumn(dtype=pl.Float64),
        "ead_for_crm": EdgeColumn(dtype=pl.Float64),
        "ead_after_collateral": EdgeColumn(dtype=pl.Float64),
        "ead_after_guarantee": EdgeColumn(dtype=pl.Float64),
        "ead_final": EdgeColumn(
            dtype=pl.Float64,
            citation="CRR Art. 111",
            null_meaning="never null on the pipeline path — finalised post-CRM EAD",
        ),
        "exposure_volatility_haircut": EdgeColumn(dtype=pl.Float64, citation="CRR Art. 223(5)"),
        "pre_crm_counterparty_reference": EdgeColumn(dtype=pl.String),
        "pre_crm_exposure_class": EdgeColumn(dtype=pl.String),
        # Collateral allocation (CRR Art. 193-230)
        "collateral_allocated": EdgeColumn(dtype=pl.Float64),
        "collateral_adjusted_value": EdgeColumn(dtype=pl.Float64),
        "collateral_market_value": EdgeColumn(dtype=pl.Float64),
        "collateral_financial_value": EdgeColumn(dtype=pl.Float64),
        "collateral_cash_value": EdgeColumn(dtype=pl.Float64),
        "collateral_re_value": EdgeColumn(dtype=pl.Float64),
        "collateral_receivables_value": EdgeColumn(dtype=pl.Float64),
        "collateral_other_physical_value": EdgeColumn(dtype=pl.Float64),
        "collateral_coverage_pct": EdgeColumn(dtype=pl.Float64),
        "crm_alloc_financial": EdgeColumn(dtype=pl.Float64, citation="CRR Art. 230"),
        "crm_alloc_covered_bond": EdgeColumn(dtype=pl.Float64),
        "crm_alloc_receivables": EdgeColumn(dtype=pl.Float64),
        "crm_alloc_real_estate": EdgeColumn(dtype=pl.Float64),
        "crm_alloc_other_physical": EdgeColumn(dtype=pl.Float64),
        "crm_alloc_life_insurance": EdgeColumn(dtype=pl.Float64, citation="CRR Art. 212"),
        "total_collateral_for_lgd": EdgeColumn(dtype=pl.Float64, citation="CRR Art. 230"),
        "lgd_pre_crm": EdgeColumn(dtype=pl.Float64),
        "lgd_post_crm": EdgeColumn(dtype=pl.Float64, citation="CRR Art. 161/230"),
        "lgd_secured": EdgeColumn(dtype=pl.Float64),
        "life_ins_collateral_value": EdgeColumn(dtype=pl.Float64),
        "life_ins_secured_rw": EdgeColumn(dtype=pl.Float64),
        "crm_calculation": EdgeColumn(dtype=pl.String),
        # Guarantees / substitution (CRR Art. 233-236)
        "is_guaranteed": EdgeColumn(dtype=pl.Boolean),
        "guarantee_amount": EdgeColumn(dtype=pl.Float64),
        "guaranteed_portion": EdgeColumn(dtype=pl.Float64, citation="CRR Art. 235"),
        "unguaranteed_portion": EdgeColumn(dtype=pl.Float64),
        "guarantee_ratio": EdgeColumn(dtype=pl.Float64),
        "guarantee_fx_haircut": EdgeColumn(dtype=pl.Float64, citation="CRR Art. 233(3)"),
        "guarantee_restructuring_haircut": EdgeColumn(dtype=pl.Float64),
        "guarantor_reference": EdgeColumn(dtype=pl.String),
        "guarantor_exposure_class": EdgeColumn(dtype=pl.String),
        "guarantor_approach": EdgeColumn(dtype=pl.String),
        "guarantor_rating_type": EdgeColumn(dtype=pl.String),
        "substitute_rw": EdgeColumn(dtype=pl.Float64, citation="CRR Art. 235"),
        "post_crm_counterparty_guaranteed": EdgeColumn(dtype=pl.String),
        "post_crm_exposure_class_guaranteed": EdgeColumn(dtype=pl.String),
        "protection_type": EdgeColumn(dtype=pl.String),
        # Provisions
        "provision_allocated": EdgeColumn(dtype=pl.Float64),
        "provision_deducted": EdgeColumn(dtype=pl.Float64, citation="CRR Art. 111(2)"),
        # Path-dependent OPTIONAL columns: real values only when the
        # producing sub-step ran (guarantee / provision / FCSM); injected as
        # typed nulls otherwise so the downstream shape is uniform. The
        # Wave-2 guarantor rework verified the consumers null-path-equivalent
        # (an all-null column yields the same values as the historical absent
        # column). ONE sentinel stays conditional: guarantor_entity_type
        # below.
        "provision_on_drawn": EdgeColumn(dtype=pl.Float64, required=False),
        "provision_on_nominal": EdgeColumn(dtype=pl.Float64, required=False),
        "parent_exposure_reference": EdgeColumn(dtype=pl.String, required=False),
        "guarantee_count": EdgeColumn(dtype=pl.UInt32, required=False),
        "original_guarantee_amount": EdgeColumn(dtype=pl.Float64, required=False),
        "guarantee_currency": EdgeColumn(
            dtype=pl.String, required=False, citation="CRR Art. 233(3)"
        ),
        "includes_restructuring": EdgeColumn(
            dtype=pl.Boolean, required=False, citation="CRR Art. 233(2)"
        ),
        "guarantee_reference": EdgeColumn(dtype=pl.String, required=False),
        "guarantor": EdgeColumn(dtype=pl.String, required=False),
        "guarantor_seniority": EdgeColumn(dtype=pl.String, required=False),
        # guarantor_entity_type stays CONDITIONAL (inject=False): it is the
        # run-level presence SENTINEL for the SA/IRB guarantee-substitution
        # machinery (engine/sa/namespace.py, engine/irb/guarantee.py), which
        # both gate on exactly this column. Lazy column addition is
        # row-independent, so once that machinery executes it emits its
        # derived audit columns (guarantor_rw, guarantee_status,
        # pre_crm_risk_weight, ...) regardless of values — an injected
        # all-null sentinel would put those columns (and pre_crm_summary's
        # total_rwa_pre_crm aggregate) on every unguaranteed run: the exact
        # shape divergence the 2026-06-12 decision-log lesson recorded.
        # Presence here means "the CRM guarantee sub-step ran".
        "guarantor_entity_type": EdgeColumn(
            dtype=pl.String, required=False, inject=False, citation="CRR Art. 235"
        ),
        "guarantor_country_code": EdgeColumn(dtype=pl.String, required=False),
        "guarantor_is_ccp_client_cleared": EdgeColumn(dtype=pl.Boolean, required=False),
        "guarantor_scra_grade": EdgeColumn(dtype=pl.String, required=False),
        "guarantor_cqs": EdgeColumn(dtype=pl.Int8, required=False, citation="CRR Art. 235"),
        "guarantor_pd": EdgeColumn(dtype=pl.Float64, required=False, citation="CRR Art. 161/236"),
        "guarantor_internal_pd": EdgeColumn(dtype=pl.Float64, required=False),
        # Financial Collateral Simple Method (CRR Art. 222): real values only
        # under the SIMPLE election; typed nulls otherwise. The SA consumer
        # fill_null(0.0)s both and is config-gated, so injected nulls on
        # Comprehensive runs are a no-op.
        "fcsm_collateral_value": EdgeColumn(
            dtype=pl.Float64, required=False, citation="CRR Art. 222"
        ),
        "fcsm_collateral_rw": EdgeColumn(dtype=pl.Float64, required=False, citation="CRR Art. 222"),
    }


CRM_EXIT_EDGE: EdgeContract = EdgeContract(
    name="crm_exit",
    columns={**_classifier_exit_columns(), **_crm_added_columns()},
)


CRM_EXIT_CCR_EDGE: EdgeContract = EdgeContract(
    name="crm_exit_ccr",
    columns={
        **_classifier_exit_columns(),
        **{
            col_name: col
            for col_name, col in CCR_EXIT_EDGE.columns.items()
            if col_name not in HIERARCHY_EXIT_EDGE.columns
        },
        **_crm_added_columns(),
    },
)


def _re_split_added_columns() -> dict[str, EdgeColumn]:
    """Columns the RealEstateSplitter adds (PS1/26 Art. 124C-124K split)."""
    return {
        "split_parent_id": EdgeColumn(
            dtype=pl.String,
            citation="PS1/26 Art. 124C",
            null_meaning="null = row was not produced by an RE split",
        ),
        "re_split_role": EdgeColumn(dtype=pl.String),
    }


RE_SPLIT_EXIT_EDGE: EdgeContract = EdgeContract(
    name="re_split_exit",
    columns={**CRM_EXIT_EDGE.columns, **_re_split_added_columns()},
)


RE_SPLIT_EXIT_CCR_EDGE: EdgeContract = EdgeContract(
    name="re_split_exit_ccr",
    columns={**CRM_EXIT_CCR_EDGE.columns, **_re_split_added_columns()},
)


# ---------------------------------------------------------------------------
# Edge definitions — calculator branch exits and aggregator exit
# ---------------------------------------------------------------------------
# Generated from observed schemas: the four-config parity snapshot
# (required = present in every config) plus guarantee / FCSM / provision /
# CCR-bearing harvests. Regime/config-gated columns are CONDITIONAL
# (inject=False) — validated when present, never injected. Composed from
# one shared column inventory plus per-contract extras (the four frames
# share the bulk of their shape).


def _calc_output_common_columns() -> dict[str, EdgeColumn]:
    """Columns shared by all three branch exits AND the aggregator exit."""
    return {
        "ancestor_facilities": EdgeColumn(dtype=pl.List(pl.String)),
        "approach": EdgeColumn(dtype=pl.String),
        "approach_applied": EdgeColumn(dtype=pl.String),
        "ava_amount": EdgeColumn(dtype=pl.Float64),
        "beel": EdgeColumn(dtype=pl.Float64),
        "book_code": EdgeColumn(dtype=pl.String),
        "ccf": EdgeColumn(dtype=pl.Float64),
        "ccf_calculation": EdgeColumn(dtype=pl.String),
        "ccf_guaranteed": EdgeColumn(dtype=pl.Float64),
        "ccf_modelled": EdgeColumn(dtype=pl.Float64),
        "ccf_original": EdgeColumn(dtype=pl.Float64),
        "ccf_unguaranteed": EdgeColumn(dtype=pl.Float64),
        "collateral_adjusted_value": EdgeColumn(dtype=pl.Float64),
        "collateral_allocated": EdgeColumn(dtype=pl.Float64),
        "collateral_cash_value": EdgeColumn(dtype=pl.Float64),
        "collateral_coverage_pct": EdgeColumn(dtype=pl.Float64),
        "collateral_financial_value": EdgeColumn(dtype=pl.Float64),
        "collateral_market_value": EdgeColumn(dtype=pl.Float64),
        "collateral_other_physical_value": EdgeColumn(dtype=pl.Float64),
        "collateral_re_value": EdgeColumn(dtype=pl.Float64),
        "collateral_receivables_value": EdgeColumn(dtype=pl.Float64),
        "commercial_collateral_value_uncapped": EdgeColumn(dtype=pl.Float64),
        "counterparty_reference": EdgeColumn(dtype=pl.String),
        "cp_annual_revenue": EdgeColumn(dtype=pl.Float64),
        "cp_apply_fi_scalar": EdgeColumn(dtype=pl.Boolean),
        "cp_borrower_income_currency": EdgeColumn(dtype=pl.String),
        "cp_country_code": EdgeColumn(dtype=pl.String),
        "cp_default_status": EdgeColumn(dtype=pl.Boolean),
        "cp_eca_score": EdgeColumn(dtype=pl.Int8),
        "cp_entity_type": EdgeColumn(dtype=pl.String),
        "cp_institution_cqs": EdgeColumn(dtype=pl.Int8),
        "cp_internal_model_id": EdgeColumn(dtype=pl.String),
        "cp_is_ccp_client_cleared": EdgeColumn(dtype=pl.Boolean),
        "cp_is_financial_sector_entity": EdgeColumn(dtype=pl.Boolean),
        "cp_is_investment_grade": EdgeColumn(dtype=pl.Boolean),
        "cp_is_managed_as_retail": EdgeColumn(dtype=pl.Boolean),
        "cp_is_natural_person": EdgeColumn(dtype=pl.Boolean),
        "cp_is_qccp": EdgeColumn(dtype=pl.Boolean),
        "cp_is_social_housing": EdgeColumn(dtype=pl.Boolean),
        "cp_local_currency": EdgeColumn(dtype=pl.String),
        "cp_qualifying_property_count": EdgeColumn(dtype=pl.Int32),
        "cp_scra_grade": EdgeColumn(dtype=pl.String),
        "cp_sovereign_cqs": EdgeColumn(dtype=pl.Int32),
        "cp_total_assets": EdgeColumn(dtype=pl.Float64),
        "cqs": EdgeColumn(dtype=pl.Int8),
        "crm_alloc_covered_bond": EdgeColumn(dtype=pl.Float64),
        "crm_alloc_financial": EdgeColumn(dtype=pl.Float64),
        "crm_alloc_life_insurance": EdgeColumn(dtype=pl.Float64),
        "crm_alloc_other_physical": EdgeColumn(dtype=pl.Float64),
        "crm_alloc_real_estate": EdgeColumn(dtype=pl.Float64),
        "crm_alloc_receivables": EdgeColumn(dtype=pl.Float64),
        "crm_calculation": EdgeColumn(dtype=pl.String),
        "currency": EdgeColumn(dtype=pl.String),
        "drawn_amount": EdgeColumn(dtype=pl.Float64),
        "e_star_group_drawn": EdgeColumn(dtype=pl.Float64, required=False, inject=False),
        "ead_after_collateral": EdgeColumn(dtype=pl.Float64),
        "ead_after_guarantee": EdgeColumn(dtype=pl.Float64),
        "ead_final": EdgeColumn(dtype=pl.Float64),
        "ead_for_crm": EdgeColumn(dtype=pl.Float64),
        "ead_from_ccf": EdgeColumn(dtype=pl.Float64),
        "ead_gross": EdgeColumn(dtype=pl.Float64),
        "ead_modelled": EdgeColumn(dtype=pl.Float64),
        "ead_pre_crm": EdgeColumn(dtype=pl.Float64),
        "effective_ccf": EdgeColumn(dtype=pl.Float64),
        "effective_maturity": EdgeColumn(dtype=pl.Float64),
        "exposure_class": EdgeColumn(dtype=pl.String),
        "exposure_class_for_sa": EdgeColumn(dtype=pl.String),
        "exposure_class_irb": EdgeColumn(dtype=pl.String),
        "exposure_class_sa": EdgeColumn(dtype=pl.String),
        "exposure_collateral_type": EdgeColumn(dtype=pl.String),
        "exposure_for_retail_threshold": EdgeColumn(dtype=pl.Float64),
        "exposure_has_parent": EdgeColumn(dtype=pl.Boolean),
        "exposure_reference": EdgeColumn(dtype=pl.String),
        "exposure_security_cqs": EdgeColumn(dtype=pl.Int8),
        "exposure_security_residual_maturity_years": EdgeColumn(dtype=pl.Float64),
        "exposure_subclass": EdgeColumn(dtype=pl.String),
        "exposure_type": EdgeColumn(dtype=pl.String),
        "exposure_volatility_haircut": EdgeColumn(dtype=pl.Float64),
        "external_cqs": EdgeColumn(dtype=pl.Int8),
        "external_rating_is_issue_specific": EdgeColumn(dtype=pl.Boolean),
        "facility_hierarchy_depth": EdgeColumn(dtype=pl.Int8),
        "facility_limit": EdgeColumn(dtype=pl.Float64),
        "facility_termination_date": EdgeColumn(dtype=pl.Date),
        "fx_rate_applied": EdgeColumn(dtype=pl.Float64),
        "guarantee_amount": EdgeColumn(dtype=pl.Float64),
        "guarantee_fx_haircut": EdgeColumn(dtype=pl.Float64),
        "guarantee_ratio": EdgeColumn(dtype=pl.Float64),
        "guarantee_restructuring_haircut": EdgeColumn(dtype=pl.Float64),
        "guaranteed_portion": EdgeColumn(dtype=pl.Float64),
        "guarantor_approach": EdgeColumn(dtype=pl.String),
        "guarantor_exposure_class": EdgeColumn(dtype=pl.String),
        "guarantor_rating_type": EdgeColumn(dtype=pl.String),
        "guarantor_reference": EdgeColumn(dtype=pl.String),
        "has_facility_property_collateral": EdgeColumn(dtype=pl.Boolean),
        "has_income_cover": EdgeColumn(dtype=pl.Boolean),
        "has_one_day_maturity_floor": EdgeColumn(dtype=pl.Boolean),
        "has_property_collateral": EdgeColumn(dtype=pl.Boolean),
        "has_short_term_ecai": EdgeColumn(dtype=pl.Boolean),
        "has_sufficient_collateral_data": EdgeColumn(dtype=pl.Boolean),
        "interest": EdgeColumn(dtype=pl.Float64),
        "internal_pd": EdgeColumn(dtype=pl.Float64),
        "is_adc": EdgeColumn(dtype=pl.Boolean),
        "is_buy_to_let": EdgeColumn(dtype=pl.Boolean),
        "is_defaulted": EdgeColumn(dtype=pl.Boolean),
        "is_guaranteed": EdgeColumn(dtype=pl.Boolean),
        "is_hvcre": EdgeColumn(dtype=pl.Boolean),
        "is_infrastructure": EdgeColumn(dtype=pl.Boolean),
        "is_mortgage": EdgeColumn(dtype=pl.Boolean),
        "is_obs_commitment": EdgeColumn(dtype=pl.Boolean),
        "is_payroll_loan": EdgeColumn(dtype=pl.Boolean),
        "is_purchased_receivable_commitment": EdgeColumn(dtype=pl.Boolean),
        "is_qrre_transactor": EdgeColumn(dtype=pl.Boolean),
        "is_qualifying_re": EdgeColumn(dtype=pl.Boolean),
        "is_revolving": EdgeColumn(dtype=pl.Boolean),
        "is_sft": EdgeColumn(dtype=pl.Boolean),
        "is_short_term_trade_lc": EdgeColumn(dtype=pl.Boolean),
        "is_sme": EdgeColumn(dtype=pl.Boolean),
        "is_uk_residential_mortgage_commitment": EdgeColumn(dtype=pl.Boolean),
        "is_under_construction": EdgeColumn(dtype=pl.Boolean),
        "lending_group_adjusted_exposure": EdgeColumn(dtype=pl.Float64),
        "lending_group_reference": EdgeColumn(dtype=pl.String),
        "lending_group_total_exposure": EdgeColumn(dtype=pl.Float64),
        "lgd": EdgeColumn(dtype=pl.Float64),
        "lgd_post_crm": EdgeColumn(dtype=pl.Float64),
        "lgd_pre_crm": EdgeColumn(dtype=pl.Float64),
        "lgd_secured": EdgeColumn(dtype=pl.Float64),
        "lgd_unsecured": EdgeColumn(dtype=pl.Float64),
        "life_ins_collateral_value": EdgeColumn(dtype=pl.Float64),
        "life_ins_secured_rw": EdgeColumn(dtype=pl.Float64),
        "ltv": EdgeColumn(dtype=pl.Float64),
        "mapped_parent_facility": EdgeColumn(dtype=pl.String),
        "maturity_date": EdgeColumn(dtype=pl.Date),
        "model_airb_permitted": EdgeColumn(dtype=pl.Boolean),
        "model_firb_permitted": EdgeColumn(dtype=pl.Boolean),
        "model_id": EdgeColumn(dtype=pl.String),
        "model_slotting_permitted": EdgeColumn(dtype=pl.Boolean),
        "mof_risk_type_source": EdgeColumn(dtype=pl.String),
        "netting_agreement_reference": EdgeColumn(dtype=pl.String),
        "nominal_after_provision": EdgeColumn(dtype=pl.Float64),
        "nominal_amount": EdgeColumn(dtype=pl.Float64),
        "on_bs_for_ead": EdgeColumn(dtype=pl.Float64),
        "on_bs_netting_amount": EdgeColumn(dtype=pl.Float64),
        "original_amount": EdgeColumn(dtype=pl.Float64),
        "original_counterparty_reference": EdgeColumn(dtype=pl.String),
        "original_currency": EdgeColumn(dtype=pl.String),
        "other_own_funds_reductions": EdgeColumn(dtype=pl.Float64),
        "parent_facility_reference": EdgeColumn(dtype=pl.String),
        "pd": EdgeColumn(dtype=pl.Float64),
        "post_crm_counterparty_guaranteed": EdgeColumn(dtype=pl.String),
        "post_crm_exposure_class_guaranteed": EdgeColumn(dtype=pl.String),
        "ppu_reason": EdgeColumn(dtype=pl.String),
        "pre_crm_counterparty_reference": EdgeColumn(dtype=pl.String),
        "pre_crm_exposure_class": EdgeColumn(dtype=pl.String),
        "prior_charge_ltv": EdgeColumn(dtype=pl.Float64),
        "product_type": EdgeColumn(dtype=pl.String),
        "property_collateral_value": EdgeColumn(dtype=pl.Float64),
        "property_type": EdgeColumn(dtype=pl.String),
        "protection_type": EdgeColumn(dtype=pl.String),
        "provision_allocated": EdgeColumn(dtype=pl.Float64),
        "provision_deducted": EdgeColumn(dtype=pl.Float64),
        "purchased_receivables_subtype": EdgeColumn(dtype=pl.String),
        "qualifies_as_retail": EdgeColumn(dtype=pl.Boolean),
        "re_collateral_non_qualifying": EdgeColumn(dtype=pl.Boolean),
        "re_split_commercial_eligible": EdgeColumn(dtype=pl.Boolean),
        "re_split_commercial_value": EdgeColumn(dtype=pl.Float64),
        "re_split_cre_rental_coverage_met": EdgeColumn(dtype=pl.Boolean),
        "re_split_force_other_re": EdgeColumn(dtype=pl.Boolean),
        "re_split_mode": EdgeColumn(dtype=pl.String),
        "re_split_property_type": EdgeColumn(dtype=pl.String),
        "re_split_property_value": EdgeColumn(dtype=pl.Float64),
        "re_split_residential_eligible": EdgeColumn(dtype=pl.Boolean),
        "re_split_residential_value": EdgeColumn(dtype=pl.Float64),
        "re_split_role": EdgeColumn(dtype=pl.String),
        "re_split_target_class": EdgeColumn(dtype=pl.String),
        "reclassified_to_retail": EdgeColumn(dtype=pl.Boolean),
        "requires_fi_scalar": EdgeColumn(dtype=pl.Boolean),
        "residential_collateral_value": EdgeColumn(dtype=pl.Float64),
        "residential_collateral_value_uncapped": EdgeColumn(dtype=pl.Float64),
        "retail_threshold_exclusion_applied": EdgeColumn(dtype=pl.Boolean),
        "risk_type": EdgeColumn(dtype=pl.String),
        "risk_weight": EdgeColumn(dtype=pl.Float64),
        "root_facility_reference": EdgeColumn(dtype=pl.String),
        "rwa_final": EdgeColumn(dtype=pl.Float64),
        "rwa_post_factor": EdgeColumn(dtype=pl.Float64),
        "rwa_pre_factor": EdgeColumn(dtype=pl.Float64),
        "securitisation_pool_allocations": EdgeColumn(
            dtype=pl.List(pl.Struct({"pool_reference": pl.String, "allocation_pct": pl.Float64}))
        ),
        "securitisation_residual_pct": EdgeColumn(dtype=pl.Float64),
        "seniority": EdgeColumn(dtype=pl.String),
        "sl_type": EdgeColumn(dtype=pl.String),
        "slotting_category": EdgeColumn(dtype=pl.String),
        "sme_size_metric_gbp": EdgeColumn(dtype=pl.Float64),
        "sme_size_source": EdgeColumn(dtype=pl.String),
        "source_facility_reference": EdgeColumn(dtype=pl.String),
        "split_parent_id": EdgeColumn(dtype=pl.String),
        "substitute_rw": EdgeColumn(dtype=pl.Float64),
        "supporting_factor": EdgeColumn(dtype=pl.Float64),
        "supporting_factor_applied": EdgeColumn(dtype=pl.Boolean),
        "total_collateral_for_lgd": EdgeColumn(dtype=pl.Float64),
        "total_cp_drawn": EdgeColumn(dtype=pl.Float64, required=False, inject=False),
        "total_exposure_amount": EdgeColumn(dtype=pl.Float64),
        "underlying_risk_type": EdgeColumn(dtype=pl.String),
        "undrawn_amount": EdgeColumn(dtype=pl.Float64),
        "unguaranteed_portion": EdgeColumn(dtype=pl.Float64),
        "value_date": EdgeColumn(dtype=pl.Date),
        "currency_mismatch_multiplier_applied": EdgeColumn(
            dtype=pl.Boolean, required=False, inject=False
        ),
        "risk_weight_pre_currency_mismatch": EdgeColumn(
            dtype=pl.Float64, required=False, inject=False
        ),
        "sa_rwa": EdgeColumn(dtype=pl.Float64, required=False, inject=False),
        "fcsm_collateral_rw": EdgeColumn(dtype=pl.Float64, required=False),
        "fcsm_collateral_value": EdgeColumn(dtype=pl.Float64, required=False),
        "guarantee_benefit_rw": EdgeColumn(dtype=pl.Float64, required=False, inject=False),
        "guarantee_count": EdgeColumn(dtype=pl.UInt32, required=False),
        "guarantee_currency": EdgeColumn(dtype=pl.String, required=False),
        "guarantee_reference": EdgeColumn(dtype=pl.String, required=False),
        "guarantee_status": EdgeColumn(dtype=pl.String, required=False, inject=False),
        "guarantor": EdgeColumn(dtype=pl.String, required=False),
        "guarantor_country_code": EdgeColumn(dtype=pl.String, required=False),
        "guarantor_cqs": EdgeColumn(dtype=pl.Int8, required=False),
        "guarantor_entity_type": EdgeColumn(dtype=pl.String, required=False, inject=False),
        "guarantor_internal_pd": EdgeColumn(dtype=pl.Float64, required=False),
        "guarantor_is_ccp_client_cleared": EdgeColumn(dtype=pl.Boolean, required=False),
        "guarantor_pd": EdgeColumn(dtype=pl.Float64, required=False),
        "guarantor_rw": EdgeColumn(dtype=pl.Float64, required=False, inject=False),
        "guarantor_scra_grade": EdgeColumn(dtype=pl.String, required=False),
        "guarantor_seniority": EdgeColumn(dtype=pl.String, required=False),
        "includes_restructuring": EdgeColumn(dtype=pl.Boolean, required=False),
        "is_guarantee_beneficial": EdgeColumn(dtype=pl.Boolean, required=False, inject=False),
        "original_guarantee_amount": EdgeColumn(dtype=pl.Float64, required=False),
        "parent_exposure_reference": EdgeColumn(dtype=pl.String, required=False),
        "pre_crm_risk_weight": EdgeColumn(dtype=pl.Float64, required=False, inject=False),
        "provision_on_drawn": EdgeColumn(dtype=pl.Float64, required=False),
        "provision_on_nominal": EdgeColumn(dtype=pl.Float64, required=False),
        "source_netting_set_id": EdgeColumn(dtype=pl.String, required=False, inject=False),
        "ccr_method": EdgeColumn(dtype=pl.String, required=False, inject=False),
        "wwr_lgd_override": EdgeColumn(dtype=pl.Float64, required=False, inject=False),
        "addon_aggregate": EdgeColumn(dtype=pl.Float64, required=False, inject=False),
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
            required=False,
            inject=False,
        ),
        "pfe_multiplier": EdgeColumn(dtype=pl.Float64, required=False, inject=False),
        "pfe_addon": EdgeColumn(dtype=pl.Float64, required=False, inject=False),
        "rc_unmargined": EdgeColumn(dtype=pl.Float64, required=False, inject=False),
        "rc_margined": EdgeColumn(dtype=pl.Float64, required=False, inject=False),
        "rc": EdgeColumn(dtype=pl.Float64, required=False, inject=False),
        "alpha_applied": EdgeColumn(dtype=pl.Float64, required=False, inject=False),
        "transitional_add_on": EdgeColumn(dtype=pl.Float64, required=False, inject=False),
        "ead_ccr": EdgeColumn(dtype=pl.Float64, required=False, inject=False),
    }


SA_BRANCH_EDGE: EdgeContract = EdgeContract(
    name="sa_branch",
    columns={
        **_calc_output_common_columns(),
        "cp_internal_rating_grade": EdgeColumn(dtype=pl.String),
        "cp_is_core_market_participant": EdgeColumn(dtype=pl.Boolean),
        "is_presold": EdgeColumn(dtype=pl.Boolean),
        "original_maturity_years": EdgeColumn(dtype=pl.Float64),
        "residual_maturity_years": EdgeColumn(dtype=pl.Float64),
        "sl_project_phase": EdgeColumn(dtype=pl.String),
        "ead_calculation_method": EdgeColumn(dtype=pl.String, required=False, inject=False),
        "pre_fcsm_risk_weight": EdgeColumn(dtype=pl.Float64, required=False, inject=False),
    },
)


IRB_BRANCH_EDGE: EdgeContract = EdgeContract(
    name="irb_branch",
    columns={
        **_calc_output_common_columns(),
        "correlation": EdgeColumn(dtype=pl.Float64),
        "el_after_adjustment": EdgeColumn(dtype=pl.Float64),
        "el_excess": EdgeColumn(dtype=pl.Float64),
        "el_pre_adjustment": EdgeColumn(dtype=pl.Float64),
        "el_shortfall": EdgeColumn(dtype=pl.Float64),
        "expected_loss": EdgeColumn(dtype=pl.Float64),
        "irb_maturity_m": EdgeColumn(dtype=pl.Float64),
        "is_airb": EdgeColumn(dtype=pl.Boolean),
        "k": EdgeColumn(dtype=pl.Float64),
        "lgd_floored": EdgeColumn(dtype=pl.Float64),
        "lgd_input": EdgeColumn(dtype=pl.Float64),
        "maturity": EdgeColumn(dtype=pl.Float64),
        "maturity_adjustment": EdgeColumn(dtype=pl.Float64),
        "mortgage_rw_floor_adjustment": EdgeColumn(dtype=pl.Float64),
        "pd_floored": EdgeColumn(dtype=pl.Float64),
        "post_model_adjustment_el": EdgeColumn(dtype=pl.Float64),
        "post_model_adjustment_rwa": EdgeColumn(dtype=pl.Float64),
        "rwa": EdgeColumn(dtype=pl.Float64),
        "rwa_pre_adjustments": EdgeColumn(dtype=pl.Float64),
        "scaling_factor": EdgeColumn(dtype=pl.Float64),
        "turnover_m": EdgeColumn(dtype=pl.Float64),
        "unrecognised_exposure_adjustment": EdgeColumn(dtype=pl.Float64),
        "cp_internal_rating_grade": EdgeColumn(dtype=pl.String, required=False, inject=False),
        "cp_is_core_market_participant": EdgeColumn(dtype=pl.Boolean, required=False, inject=False),
        "is_presold": EdgeColumn(dtype=pl.Boolean, required=False, inject=False),
        "original_maturity_years": EdgeColumn(dtype=pl.Float64, required=False, inject=False),
        "residual_maturity_years": EdgeColumn(dtype=pl.Float64, required=False, inject=False),
        "sl_project_phase": EdgeColumn(dtype=pl.String, required=False, inject=False),
        "double_default_unfunded_protection": EdgeColumn(
            dtype=pl.Float64, required=False, inject=False
        ),
        "expected_loss_irb_original": EdgeColumn(dtype=pl.Float64, required=False, inject=False),
        "guarantee_method_used": EdgeColumn(dtype=pl.String, required=False, inject=False),
        "guarantor_is_financial_sector_entity": EdgeColumn(
            dtype=pl.Boolean, required=False, inject=False
        ),
        "guarantor_rw_irb": EdgeColumn(dtype=pl.Float64, required=False, inject=False),
        "guarantor_rw_post_nbd": EdgeColumn(dtype=pl.Float64, required=False, inject=False),
        "irb_lgd_double_default": EdgeColumn(dtype=pl.Float64, required=False, inject=False),
        "is_double_default_eligible": EdgeColumn(dtype=pl.Boolean, required=False, inject=False),
        "pre_crm_rwa": EdgeColumn(dtype=pl.Float64, required=False, inject=False),
        "risk_weight_irb_original": EdgeColumn(dtype=pl.Float64, required=False, inject=False),
        "rw_direct": EdgeColumn(dtype=pl.Float64, required=False, inject=False),
        "rwa_irb_original": EdgeColumn(dtype=pl.Float64, required=False, inject=False),
    },
)


SLOTTING_BRANCH_EDGE: EdgeContract = EdgeContract(
    name="slotting_branch",
    columns={
        **_calc_output_common_columns(),
        "el_excess": EdgeColumn(dtype=pl.Float64),
        "el_shortfall": EdgeColumn(dtype=pl.Float64),
        "expected_loss": EdgeColumn(dtype=pl.Float64),
        "is_pre_operational": EdgeColumn(dtype=pl.Boolean),
        "is_short_maturity": EdgeColumn(dtype=pl.Boolean),
        "remaining_maturity_years": EdgeColumn(dtype=pl.Float64),
        "rwa": EdgeColumn(dtype=pl.Float64),
        "slotting_el_rate": EdgeColumn(dtype=pl.Float64),
        "cp_internal_rating_grade": EdgeColumn(dtype=pl.String, required=False, inject=False),
        "cp_is_core_market_participant": EdgeColumn(dtype=pl.Boolean, required=False, inject=False),
        "is_presold": EdgeColumn(dtype=pl.Boolean, required=False, inject=False),
        "original_maturity_years": EdgeColumn(dtype=pl.Float64, required=False, inject=False),
        "residual_maturity_years": EdgeColumn(dtype=pl.Float64, required=False, inject=False),
        "sl_project_phase": EdgeColumn(dtype=pl.String, required=False, inject=False),
    },
)


AGGREGATOR_EXIT_EDGE: EdgeContract = EdgeContract(
    name="aggregator_exit",
    columns={
        **_calc_output_common_columns(),
        "correlation": EdgeColumn(dtype=pl.Float64),
        "cp_internal_rating_grade": EdgeColumn(dtype=pl.String),
        "cp_is_core_market_participant": EdgeColumn(dtype=pl.Boolean),
        "el_after_adjustment": EdgeColumn(dtype=pl.Float64),
        "el_excess": EdgeColumn(dtype=pl.Float64),
        "el_pre_adjustment": EdgeColumn(dtype=pl.Float64),
        "el_shortfall": EdgeColumn(dtype=pl.Float64),
        "equity_type": EdgeColumn(dtype=pl.String, required=False),
        "expected_loss": EdgeColumn(dtype=pl.Float64),
        "irb_maturity_m": EdgeColumn(dtype=pl.Float64),
        "is_airb": EdgeColumn(dtype=pl.Boolean),
        "is_pre_operational": EdgeColumn(dtype=pl.Boolean),
        "is_presold": EdgeColumn(dtype=pl.Boolean),
        "is_short_maturity": EdgeColumn(dtype=pl.Boolean),
        "k": EdgeColumn(dtype=pl.Float64),
        "lgd_floored": EdgeColumn(dtype=pl.Float64),
        "lgd_input": EdgeColumn(dtype=pl.Float64),
        "maturity": EdgeColumn(dtype=pl.Float64),
        "maturity_adjustment": EdgeColumn(dtype=pl.Float64),
        "mortgage_rw_floor_adjustment": EdgeColumn(dtype=pl.Float64),
        "original_maturity_years": EdgeColumn(dtype=pl.Float64),
        "pd_floored": EdgeColumn(dtype=pl.Float64),
        "post_model_adjustment_el": EdgeColumn(dtype=pl.Float64),
        "post_model_adjustment_rwa": EdgeColumn(dtype=pl.Float64),
        "remaining_maturity_years": EdgeColumn(dtype=pl.Float64),
        "residual_maturity_years": EdgeColumn(dtype=pl.Float64),
        "rwa": EdgeColumn(dtype=pl.Float64),
        "rwa_pre_adjustments": EdgeColumn(dtype=pl.Float64),
        "scaling_factor": EdgeColumn(dtype=pl.Float64),
        "sl_project_phase": EdgeColumn(dtype=pl.String),
        "slotting_el_rate": EdgeColumn(dtype=pl.Float64),
        "turnover_m": EdgeColumn(dtype=pl.Float64),
        "unrecognised_exposure_adjustment": EdgeColumn(dtype=pl.Float64),
        "floor_impact_rwa": EdgeColumn(dtype=pl.Float64, required=False, inject=False),
        "floor_rwa": EdgeColumn(dtype=pl.Float64, required=False, inject=False),
        "is_floor_binding": EdgeColumn(dtype=pl.Boolean, required=False, inject=False),
        "output_floor_pct": EdgeColumn(dtype=pl.Float64, required=False, inject=False),
        "rwa_pre_floor": EdgeColumn(dtype=pl.Float64, required=False, inject=False),
        "double_default_unfunded_protection": EdgeColumn(
            dtype=pl.Float64, required=False, inject=False
        ),
        "ead_calculation_method": EdgeColumn(dtype=pl.String, required=False, inject=False),
        "expected_loss_irb_original": EdgeColumn(dtype=pl.Float64, required=False, inject=False),
        "guarantee_method_used": EdgeColumn(dtype=pl.String, required=False, inject=False),
        "guarantor_is_financial_sector_entity": EdgeColumn(
            dtype=pl.Boolean, required=False, inject=False
        ),
        "guarantor_rw_irb": EdgeColumn(dtype=pl.Float64, required=False, inject=False),
        "guarantor_rw_post_nbd": EdgeColumn(dtype=pl.Float64, required=False, inject=False),
        "irb_lgd_double_default": EdgeColumn(dtype=pl.Float64, required=False, inject=False),
        "is_double_default_eligible": EdgeColumn(dtype=pl.Boolean, required=False, inject=False),
        "pre_crm_rwa": EdgeColumn(dtype=pl.Float64, required=False, inject=False),
        "pre_fcsm_risk_weight": EdgeColumn(dtype=pl.Float64, required=False, inject=False),
        "risk_weight_irb_original": EdgeColumn(dtype=pl.Float64, required=False, inject=False),
        "rw_direct": EdgeColumn(dtype=pl.Float64, required=False, inject=False),
        "rwa_irb_original": EdgeColumn(dtype=pl.Float64, required=False, inject=False),
    },
)


CALC_BRANCH_EDGES: dict[str, EdgeContract] = {
    "sa_branch": SA_BRANCH_EDGE,
    "irb_branch": IRB_BRANCH_EDGE,
    "slotting_branch": SLOTTING_BRANCH_EDGE,
}
"""Branch label -> contract, consumed by the orchestrator's branch collect."""
