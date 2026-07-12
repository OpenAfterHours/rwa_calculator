"""Parallel-run reconciliation registry + column-mapping configuration.

The canonical component registry (which result components can be reconciled
legacy-vs-ours, with their tolerances, additivity and derived-ratio rules) plus
the ``LegacyColumnMapping`` / ``ComponentMapping`` configuration that maps an
external (legacy) calculator's output columns onto those components.

This is analysis-layer configuration — it describes how a *finished* run is
reconciled, not how input data is validated — so it lives in ``analysis/``
(migration Phase 6) rather than ``data/schemas.py`` / ``contracts/config.py``.
The reconciliation engine (``rwa_calc.analysis.reconciliation``) and the API
loader read it; ``LegacyColumnMapping`` validates its component names against the
registry in-module (no cross-layer import).

References:
- CRR Part Three / PRA SS1/23: parallel-run validation and output reconciliation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True, slots=True)
class ReconcilableComponent:
    """A single result component that can be reconciled legacy-vs-ours.

    Attributes:
        name: Canonical component name used in config and output columns (e.g. "pd").
        kind: "numeric" (delta + tolerance) or "categorical" (normalised equality).
        our_columns: Candidate column names on our results frame, in preference
            order; the first present is used as our value.
        explain_columns: Columns carrying OUR rationale (reason / source / which
            floor bound) — surfaced on the reconciliation row to answer "why did we
            get this value". Absent columns are silently dropped.
        input_columns: Raw upstream drivers that FED our value — surfaced so an
            analyst can attribute a break to bad input data vs engine logic.
            Absent columns are silently dropped.
        additive: True when the value sums across guarantee/RE sub-rows on collapse
            (EAD, RWA, expected loss); False for rates/categoricals.
        derived_ratio: When set, ``(numerator_component, denominator_component)`` —
            the value is recomputed after a collapse as sum(num)/sum(den) rather
            than summed or taken first (e.g. risk_weight = rwa/ead).
        default_tol_kind: "rel" (relative) or "abs" (absolute) tolerance default.
        default_tol: Default tolerance magnitude (overridable per-component in the
            mapping config).
    """

    name: str
    kind: Literal["numeric", "categorical"]
    our_columns: tuple[str, ...]
    explain_columns: tuple[str, ...] = ()
    input_columns: tuple[str, ...] = ()
    additive: bool = False
    derived_ratio: tuple[str, str] | None = None
    default_tol_kind: Literal["rel", "abs"] = "rel"
    default_tol: float = 0.01


RECONCILABLE_COMPONENTS: tuple[ReconcilableComponent, ...] = (
    ReconcilableComponent(
        # Per-key / break-attribution class. Uses ``reporting_class_origin`` — the
        # sealed ledger's obligor applied class (folds SME-managed-as-retail +
        # defaulted; = exposure_class_applied) — which is UNIFORM across a guaranteed
        # exposure's __G_/__REM legs, so a partially-guaranteed exposure's break is
        # attributed deterministically to its borrower class rather than an arbitrary
        # first leg. The POST-guarantee money split (guaranteed slice under the
        # guarantor) is a separate, aggregate view built by ``_class_allocation`` off
        # ``reporting_class`` — see that function. Single sealed name, no fallback
        # ladder (Phase 7 S4): the column is contract-guaranteed on aggregator_exit.
        "exposure_class",
        "categorical",
        our_columns=("reporting_class_origin",),
        explain_columns=(
            "exposure_class_reason",
            "exposure_class_post_crm",
            "exposure_class",
            "pre_crm_exposure_class",
        ),
    ),
    ReconcilableComponent(
        "approach",
        "categorical",
        our_columns=("reporting_approach_origin",),
        explain_columns=("approach_selection_reason", "approach_permitted"),
        input_columns=("model_id",),
    ),
    ReconcilableComponent(
        # Credit-quality step. SA uses sa_cqs; external_cqs is the rating-agency
        # CQS behind it (take-first by presence). Exact-int match: tol 0 means any
        # CQS difference is a break (the exact-epsilon branch passes equal values).
        "cqs",
        "numeric",
        our_columns=("external_cqs",),
        explain_columns=("sa_rating_source",),
        default_tol_kind="abs",
        default_tol=0.0,
    ),
    ReconcilableComponent(
        # The IRB engine emits the floored PD as ``pd_floored`` and the pre-floor
        # working PD as ``pd`` — there is no ``irb_``-prefixed output column
        # (``CALCULATION_OUTPUT_SCHEMA`` declares ``irb_pd_floored`` but nothing
        # produces it). No separate original/floor column is persisted on output.
        "pd",
        "numeric",
        our_columns=("pd_floored",),
        input_columns=("internal_pd",),
        default_tol_kind="abs",
        default_tol=5e-5,
    ),
    ReconcilableComponent(
        # Floored regulatory LGD (drives K / EL) is ``lgd_floored``; ``lgd_input``
        # is the CRM-adjusted input and ``lgd`` the raw value — mirrors the
        # reporting layer's ``_pick(cols, "lgd_floored", "lgd_input")``. No
        # ``irb_``-prefixed output exists; ``lgd_pre_crm`` is the pre-CRM rationale.
        "lgd",
        "numeric",
        our_columns=("lgd_floored",),
        explain_columns=("lgd_pre_crm",),
        default_tol_kind="abs",
        default_tol=1e-3,
    ),
    ReconcilableComponent(
        "maturity",
        "numeric",
        our_columns=("irb_maturity_m",),
        input_columns=("residual_maturity_years", "original_maturity_date"),
        default_tol_kind="abs",
        default_tol=1e-2,
    ),
    ReconcilableComponent(
        "ccf",
        "numeric",
        our_columns=("ccf",),
        explain_columns=("ccf_source",),
        input_columns=("exposure_type", "undrawn_amount", "converted_undrawn"),
        default_tol_kind="abs",
        default_tol=1e-4,
    ),
    ReconcilableComponent(
        # CRM — eligible collateral after haircuts. Additive: a split exposure's
        # collateralised sub-rows sum to the key grain. The per-type split and the
        # gross/haircut explain how we reached the net value.
        "collateral",
        "numeric",
        our_columns=("collateral_adjusted_value",),
        explain_columns=(
            "collateral_gross_value",
            "collateral_haircut_applied",
            "collateral_allocation_method",
        ),
        input_columns=(
            "collateral_financial_value",
            "collateral_re_value",
            "collateral_receivables_value",
            "collateral_other_physical_value",
        ),
        additive=True,
        default_tol_kind="rel",
        default_tol=0.01,
    ),
    ReconcilableComponent(
        # CRM — unfunded protection (substitution). The additive guaranteed
        # EAD portion (``guaranteed_portion``): the amount our engine treated
        # as covered by the guarantee, which sums across split sub-rows to
        # the key grain. The guarantor approach / class and coverage ratio
        # explain it. The RWA-relief side reconciles separately via the
        # sealed ``guarantee_rwa_benefit`` component below (Phase 7 F8).
        "guarantee",
        "numeric",
        our_columns=("guaranteed_portion",),
        explain_columns=(
            "guarantor_approach",
            "guarantor_exposure_class",
            "guarantee_ratio",
        ),
        input_columns=(
            "guarantee_amount",
            "unguaranteed_portion",
        ),
        additive=True,
        default_tol_kind="rel",
        default_tol=0.01,
    ),
    ReconcilableComponent(
        # CRM — the Art. 235/236 substitution RELIEF (Phase 7 decision F8):
        # the additive per-leg ``ead_final x (borrower-basis RW - substituted
        # RW)``, PRE-supporting-factor / PRE-floor, sealed by the aggregator.
        # Sums across split sub-rows to the key grain, so a guarantee-relief
        # mismatch gets its own component row instead of diffusing into the
        # risk_weight/rwa deltas. Null = relief not modelled (runs with
        # no CRM guarantee sub-step).
        "guarantee_rwa_benefit",
        "numeric",
        our_columns=("guarantee_rwa_benefit",),
        explain_columns=(
            "guarantor_approach",
            "guarantor_exposure_class",
            "guarantee_benefit_rw",
        ),
        input_columns=(
            "guaranteed_portion",
            "guarantor_rw",
            "pre_crm_risk_weight",
        ),
        additive=True,
        default_tol_kind="rel",
        default_tol=0.01,
    ),
    ReconcilableComponent(
        "ead",
        "numeric",
        our_columns=("ead_final",),
        explain_columns=("gross_ead", "converted_undrawn"),
        # collateral_adjusted_value / guaranteed_portion stay as EAD drivers so our
        # side is always visible; when the `collateral` / `guarantee` components are
        # mapped they graduate to their own chain step and the forensic view's
        # de-dup (``_driver_chain``) drops the EAD driver row to avoid repetition.
        input_columns=(
            "drawn_amount",
            "undrawn_amount",
            "ccf_applied",
            "collateral_adjusted_value",
            "guaranteed_portion",
        ),
        additive=True,
        default_tol_kind="rel",
        default_tol=0.01,
    ),
    ReconcilableComponent(
        "risk_weight",
        "numeric",
        our_columns=("risk_weight",),
        explain_columns=("sa_rw_regulatory_ref", "sa_rw_adjustment_reason"),
        input_columns=("external_cqs", "sa_cqs", "property_ltv", "ltv_band"),
        derived_ratio=("rwa", "ead"),
        default_tol_kind="abs",
        default_tol=1e-4,
    ),
    ReconcilableComponent(
        "supporting_factor",
        "numeric",
        our_columns=("supporting_factor",),
        explain_columns=("infra_supporting_factor", "supporting_factor_benefit"),
        default_tol_kind="abs",
        default_tol=1e-4,
    ),
    ReconcilableComponent(
        "expected_loss",
        "numeric",
        our_columns=("expected_loss",),
        additive=True,
        default_tol_kind="rel",
        default_tol=0.01,
    ),
    ReconcilableComponent(
        "rwa",
        "numeric",
        our_columns=("rwa_final",),
        additive=True,
        default_tol_kind="rel",
        default_tol=0.01,
    ),
)

# Index by canonical name for O(1) lookup by config validators / the engine.
RECONCILABLE_COMPONENTS_BY_NAME: dict[str, ReconcilableComponent] = {
    c.name: c for c in RECONCILABLE_COMPONENTS
}


_RECON_UNITS = ("raw", "decimal", "percent")
_RECON_TOL_KINDS = ("rel", "abs")


@dataclass(frozen=True)
class ComponentMapping:
    """How one legacy column maps onto one of our canonical components.

    Attributes:
        legacy_column: Column name in the legacy output file (pre-normalisation;
            the loader lowercases + underscores it before lookup).
        scale: Multiplier applied to the legacy value to reach our units — e.g.
            legacy RWA in millions uses ``scale=1_000_000``. Amount components only.
        unit: ``"raw"`` (use as-is), ``"decimal"`` (already 0.20), or ``"percent"``
            (20.0 → divided by 100). Use for ratio components (pd/lgd/ccf/rw/sf).
        value_map: Optional legacy→canonical label synonyms for categorical
            components, e.g. ``{"CORP": "corporate"}``. Keys are matched
            case-insensitively after normalisation.
        tol_kind: Optional override of the registry tolerance kind ("rel"|"abs").
        tol: Optional override of the registry tolerance magnitude.
    """

    legacy_column: str
    scale: float = 1.0
    unit: Literal["raw", "decimal", "percent"] = "raw"
    value_map: dict[str, str] = field(default_factory=dict)
    tol_kind: Literal["rel", "abs"] | None = None
    tol: float | None = None

    def __post_init__(self) -> None:
        if self.unit not in _RECON_UNITS:
            raise ValueError(f"unit must be one of {_RECON_UNITS}, got {self.unit!r}")
        if self.tol_kind is not None and self.tol_kind not in _RECON_TOL_KINDS:
            raise ValueError(f"tol_kind must be one of {_RECON_TOL_KINDS}, got {self.tol_kind!r}")
        if self.tol is not None and self.tol < 0:
            raise ValueError(f"tol must be non-negative, got {self.tol}")


@dataclass(frozen=True)
class LegacyColumnMapping:
    """Declares how to join and compare a legacy output against our results.

    Attributes:
        legacy_keys: Ordered key columns in the legacy file forming the join key.
        our_keys: Ordered key columns on our results frame, positionally aligned
            with ``legacy_keys``. Defaults to a single ``exposure_reference`` key.
        components: Canonical-component-name → ``ComponentMapping``. At least one
            required; names must exist in ``RECONCILABLE_COMPONENTS``.
    """

    legacy_keys: tuple[str, ...]
    our_keys: tuple[str, ...] = ("exposure_reference",)
    components: dict[str, ComponentMapping] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Coerce list inputs (e.g. from a TOML loader) to tuples for hashability.
        object.__setattr__(self, "legacy_keys", tuple(self.legacy_keys))
        object.__setattr__(self, "our_keys", tuple(self.our_keys))

        if not self.legacy_keys:
            raise ValueError("legacy_keys must not be empty")
        if len(self.legacy_keys) != len(self.our_keys):
            raise ValueError(
                "legacy_keys and our_keys must be the same length "
                f"({len(self.legacy_keys)} vs {len(self.our_keys)})"
            )
        if not self.components:
            raise ValueError("at least one component mapping is required")

        unknown = set(self.components) - set(RECONCILABLE_COMPONENTS_BY_NAME)
        if unknown:
            valid = sorted(RECONCILABLE_COMPONENTS_BY_NAME)
            raise ValueError(
                f"unknown reconciliation components: {sorted(unknown)} (valid: {valid})"
            )
