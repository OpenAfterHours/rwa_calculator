"""Parallel-run reconciliation registry + column-mapping configuration.

The canonical component registry (which result components can be reconciled
legacy-vs-ours, with their tolerances, additivity and derived-ratio rules) plus
the ``LegacyColumnMapping`` / ``ComponentMapping`` configuration that maps an
external (legacy) calculator's output columns onto those components.

Alongside the components sits a second, smaller registry: ``LEDGER_CARRIERS``.
A component is an AMOUNT — it has a delta, a tolerance and a bucket. A carrier is
a NAME or a FLAG: an obligor reference, an exposure type, a default status. Those
cannot be reconciled, but the reporting templates key rows, populations and
distinct counts on them, and the legacy loader drops every column the mapping
does not declare — so the legacy ledger projection (``analysis.legacy_ledger``)
needs a home for them that is not a component. Carrier mappings are optional and
are ignored by the reconciliation engine.

BOTH REGISTRIES TARGET SEALED COLUMNS ONLY. Every ``our_columns`` head and every
``ledger_column`` is declared on ``AGGREGATOR_EXIT_EDGE``. The reporting
generators resolve most quantities through a LADDER whose first rungs
(``scra_provision_amount``, ``bs_type``, ``sa_cqs``, ``ccf_applied``,
``provision_held``, ``default_status``, ...) exist only on synthetic unit frames,
so our own side always traverses the sealed fallback. Targeting a synthetic rung
would put the legacy side on a DIFFERENT rung of the same ladder and produce two
plausible numbers computed from different bases — the silent basis difference
this whole feature exists to expose.

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
        # Pre-conversion-factor gross exposure, ON-balance-sheet side. The sealed
        # aggregator-exit carrier (``reporting_gross_on_bs`` = floored drawn +
        # interest) is what COREP C 07.00 col 0010, C 08.01 col 0020 and C 08.03
        # col 0010 actually sum, so a legacy engine's on-balance-sheet gross
        # reconciles here AND lands on the reporting ledger for the template
        # projection (``analysis.legacy_ledger``). Additive: a split exposure's
        # sub-rows sum to the key grain.
        #
        # THIS IS THE OVERRIDE ROUTE, not the default one. Prefer mapping the raw
        # ``drawn`` / ``interest`` amounts and letting ``ensure_gross_side_carriers``
        # derive this column with production's own rule; map it directly only when
        # the firm's extract already carries a per-side gross and you want their
        # split rather than ours. Mapping it WINS: the generator only derives the
        # column when it is absent.
        "gross_on_balance_sheet",
        "numeric",
        our_columns=("reporting_gross_on_bs",),
        input_columns=("drawn_amount", "interest"),
        additive=True,
        default_tol_kind="rel",
        default_tol=0.01,
    ),
    ReconcilableComponent(
        # Pre-conversion-factor gross exposure, OFF-balance-sheet side. Beyond
        # C 07.00 col 0010 / C 08.01 col 0020 / C 08.03 col 0020 it is also the
        # WEIGHT of the average-CCF cells (C 08.03 col 0030) and the quantity the
        # C 07.00 CCF buckets (cols 0160-0190) break down — so an unsupplied
        # off-BS gross silences four cells, not one. The override route again —
        # see ``gross_on_balance_sheet``; prefer ``undrawn`` / ``nominal``.
        "gross_off_balance_sheet",
        "numeric",
        our_columns=("reporting_gross_off_bs",),
        input_columns=("undrawn_amount", "nominal_amount"),
        additive=True,
        default_tol_kind="rel",
        default_tol=0.01,
    ),
    ReconcilableComponent(
        # The RAW on-balance-sheet drawn balance. Mapping this (with ``interest``,
        # ``undrawn``, ``nominal`` and the ``exposure_type`` carrier) lets the
        # generator derive the two sealed gross carriers ITSELF, through
        # ``kernel/columns.py::ensure_gross_side_carriers`` — the same production
        # rule the aggregator seal applies, including its floor-at-0 and its
        # "a wholly unknown side stays null" contract. That is the ROUTE TO PREFER:
        # a firm's extract carries a drawn balance, not a "reporting gross on-BS".
        "drawn",
        "numeric",
        our_columns=("drawn_amount",),
        additive=True,
        default_tol_kind="rel",
        default_tol=0.01,
    ),
    ReconcilableComponent(
        # Accrued interest — the second term of the on-balance-sheet gross.
        "interest",
        "numeric",
        our_columns=("interest",),
        additive=True,
        default_tol_kind="rel",
        default_tol=0.01,
    ),
    ReconcilableComponent(
        # Undrawn commitment headroom — the off-BS gross of a ``facility_undrawn``.
        "undrawn",
        "numeric",
        our_columns=("undrawn_amount",),
        additive=True,
        default_tol_kind="rel",
        default_tol=0.01,
    ),
    ReconcilableComponent(
        # Nominal amount — the off-BS gross of a ``contingent``.
        "nominal",
        "numeric",
        our_columns=("nominal_amount",),
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
        # RWEA BEFORE the Art. 501/501a supporting factors. Reported in its own
        # right (COREP C 07.00 col 0215, C 08.01 col 0255) and it is what the
        # supporting-factor adjustment columns are measured against —
        # ``rwa_pre_factor - rwa_final`` (C 07.00 cols 0216/0217, C 08.01 cols
        # 0256/0257) — so without it five CRR columns cannot be populated.
        "rwa_pre_factor",
        "numeric",
        our_columns=("rwa_pre_factor",),
        explain_columns=("supporting_factor", "infra_supporting_factor"),
        input_columns=("rwa_final",),
        additive=True,
        default_tol_kind="rel",
        default_tol=0.01,
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
        # Credit risk adjustments. THE TARGET IS THE SEALED PAIR, NOT SCRA/GCRA,
        # and that is the whole point of this entry.
        #
        # Every provisions cell in scope reads a LADDER that checks
        # ``scra_provision_amount`` / ``gcra_provision_amount`` FIRST and falls
        # through to a sealed carrier: ``provision_deducted`` for C 07.00 col 0030
        # (``corep/c07.py::_prepare``) and ``provision_allocated`` for the C 08.01
        # col 0290 / C 08.03 col 0110 post-pass (``corep/postpass.py``). Neither
        # SCRA carrier is declared on ``AGGREGATOR_EXIT_EDGE`` — they exist only on
        # synthetic unit frames — so OUR side always traverses the fallback rung.
        # Landing a firm's provisions on SCRA/GCRA would put the legacy side on a
        # DIFFERENT rung of the same ladder, and ``c07_provision`` also feeds
        # ``_block_cap_scale`` (the cap basis for the C 07.00 protection block), so
        # the divergence would leak into cells well beyond the provisions column.
        # Two sides computing a plausible number from different bases is precisely
        # the silent basis difference this feature exists to expose.
        #
        # ONE component, not a specific/general pair: the sealed ledger carries no
        # such split, so a ``general_provisions`` component would have no our-side
        # column to compare against and could only ever report REC001. A firm that
        # distinguishes the two maps their SUM here — which is what all three
        # template cells compute anyway (each is a ``SafeSum`` of the pair).
        "provisions",
        "numeric",
        our_columns=("provision_allocated", "provision_deducted"),
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


@dataclass(frozen=True, slots=True)
class LedgerCarrier:
    """A legacy column PASSED THROUGH to the ledger without being reconciled.

    A component is an AMOUNT: it has a delta, a tolerance and a bucket. A carrier
    is a label or a flag — a name, a type, a status. There is nothing to compare
    within a tolerance, but the reporting templates key rows, populations and
    distinct counts on exactly these, and the legacy loader drops every column the
    mapping does not declare. Without carriers the projection could never see them.

    EVERY ``ledger_column`` HERE IS DECLARED ON ``AGGREGATOR_EXIT_EDGE``, and the
    registry is closed for that reason. Several plausible targets are NOT sealed —
    they exist only on synthetic unit frames — and writing one would put the legacy
    side on a different rung of a generator ladder from our own side. ``bs_type``
    is the trap: it is the FIRST rung of every balance-sheet ladder in the
    reporting layer and it is not sealed, so the real ledger always resolves to
    ``exposure_type``. Map ``exposure_type``.

    Attributes:
        name: Canonical carrier name used in config (the TOML ``[carriers.*]``
            table key) and as the ``legacy_<name>`` loader output column.
        kind: ``"string"`` (a label / reference) or ``"boolean"`` (a flag —
            parsed from a documented token set, unknown tokens becoming null).
        ledger_column: The SEALED reporting-ledger column the projection writes
            the value to.
    """

    name: str
    kind: Literal["string", "boolean", "numeric"]
    ledger_column: str


LEDGER_CARRIERS: tuple[LedgerCarrier, ...] = (
    # The obligor reference. COREP C 08.01 col 0300 and C 08.03 col 0060 are a
    # DISTINCT count of it; without it the generators fall back to counting
    # exposure ROWS, which over-counts a multi-facility obligor — a populated cell
    # on a different measure, which is worse than an empty one.
    LedgerCarrier("obligor", "string", "counterparty_reference"),
    # The exposure type, in the engine's own vocabulary: "loan" (on-balance-sheet),
    # "contingent" / "facility_undrawn" (off) — use a ``value_map`` to translate.
    # It does THREE jobs, which is why it is the highest-value carrier of the four:
    # it drives the c07_bs / c08_bs balance-sheet ladders (C 07.00 rows 0070/0080
    # and the off-side narrowing of its CCF buckets; C 08.01 rows 0020/0030 and
    # cols 0100/0120), it selects the side each raw gross amount lands on in
    # ``ensure_gross_side_carriers``, and it gates C 07.00's CCR gross limb.
    LedgerCarrier("exposure_type", "string", "exposure_type"),
    # Default flag. C 07.00 rows 0015/0290-0320 and C 08.01 cols 0125/0265 key it.
    # Absent, the ladder falls through to ``pd_floored >= 1.0``, which is a
    # DIFFERENT statement — map it rather than rely on that. Note the sealed name
    # is ``is_defaulted``; ``default_status`` is a synthetic-frame-only rung.
    LedgerCarrier("defaulted", "boolean", "is_defaulted"),
    # Which kind of unfunded protection. Splits C 07.00 cols 0050/0060 and
    # C 08.01 cols 0040/0050. Absent, ``_protection_exprs`` puts every covered
    # part in the guarantee column and reports a hard 0.0 for credit derivatives.
    LedgerCarrier("protection_type", "string", "protection_type"),
    # C 08.06 / OF 08.06 sheet and row placement. These are labels/flags, not
    # reconcilable amounts: without them the generator either emits a generic
    # sheet or silently assigns every exposure to the long-maturity rows. The
    # coverage layer therefore treats the first three as blocking discriminators.
    LedgerCarrier("sl_type", "string", "sl_type"),
    LedgerCarrier("slotting_category", "string", "slotting_category"),
    LedgerCarrier("is_short_maturity", "boolean", "is_short_maturity"),
    # Optional alternative to a direct maturity band. The projection derives
    # ``is_short_maturity = remaining_maturity_years < 2.5`` from it only when
    # no direct band carrier is mapped (the exact boundary is long maturity).
    LedgerCarrier("remaining_maturity_years", "numeric", "remaining_maturity_years"),
    # Optional explicit HVCRE flag. The ledger projection derives this from a
    # canonical ``sl_type == \"hvcre\"`` when it is absent; an explicit mapping
    # wins, allowing a firm's distinct classification flag to be preserved.
    LedgerCarrier("is_hvcre", "boolean", "is_hvcre"),
)

# Index by canonical name for O(1) lookup by config validators / the projection.
LEDGER_CARRIERS_BY_NAME: dict[str, LedgerCarrier] = {c.name: c for c in LEDGER_CARRIERS}


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
class CarrierMapping:
    """How one legacy column maps onto one of our canonical ledger carriers.

    The carrier twin of ``ComponentMapping``. No ``scale`` / ``unit`` / ``tol``:
    a carrier is a name or a flag, so there is nothing to convert and nothing
    to compare within a tolerance.

    Attributes:
        legacy_column: Column name in the legacy output file (pre-normalisation;
            the loader lowercases + underscores it before lookup).
        value_map: Optional legacy→canonical synonyms, e.g.
            ``{"TERM LOAN": "loan", "RCF": "facility_undrawn"}`` for
            ``exposure_type``, or ``{"D": "true"}`` for ``defaulted``. Keys match
            case-insensitively; the VALUE is written verbatim, because the engine
            vocabularies a carrier targets are case-sensitive.
    """

    legacy_column: str
    value_map: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class LegacyColumnMapping:
    """Declares how to join and compare a legacy output against our results.

    Attributes:
        legacy_keys: Ordered key columns in the legacy file forming the join key.
        our_keys: Ordered key columns on our results frame, positionally aligned
            with ``legacy_keys``. Defaults to a single ``exposure_reference`` key.
        components: Canonical-component-name → ``ComponentMapping``. At least one
            required; names must exist in ``RECONCILABLE_COMPONENTS``.
        carriers: Canonical-carrier-name → ``CarrierMapping``. OPTIONAL and empty
            by default, so every mapping written before the reporting-ledger
            projection existed keeps working untouched. Names must exist in
            ``LEDGER_CARRIERS``. Carriers are ignored by the exposure-grain
            reconciliation (there is no delta to bucket) and consumed only by
            ``analysis.legacy_ledger``.
    """

    legacy_keys: tuple[str, ...]
    our_keys: tuple[str, ...] = ("exposure_reference",)
    components: dict[str, ComponentMapping] = field(default_factory=dict)
    carriers: dict[str, CarrierMapping] = field(default_factory=dict)

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

        unknown_carriers = set(self.carriers) - set(LEDGER_CARRIERS_BY_NAME)
        if unknown_carriers:
            valid_carriers = sorted(LEDGER_CARRIERS_BY_NAME)
            raise ValueError(
                f"unknown ledger carriers: {sorted(unknown_carriers)} (valid: {valid_carriers})"
            )
