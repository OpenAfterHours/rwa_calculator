"""
Data transfer bundles for RWA calculator pipeline.

Defines immutable dataclass containers for passing data between
pipeline components. Each bundle represents the output of one
component and input to the next:

    Loader -> RawDataBundle
                    |
            HierarchyResolver -> ResolvedHierarchyBundle
                                        |
                                  Classifier -> ClassifiedExposuresBundle
                                                        |
                                                  CRMProcessor -> CRMAdjustedBundle
                                                                        |
                                                        SA/IRB Calculators -> results

Each bundle contains LazyFrames to enable deferred execution
and efficient memory usage with Polars.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

from rwa_calc.domain.enums import EquityApproach

if TYPE_CHECKING:
    import polars as pl

    from rwa_calc.contracts.errors import CalculationError


@dataclass(frozen=True)
class RawDataBundle:
    """
    Output from the data loader component.

    Contains all raw input data as LazyFrames, exactly as loaded
    from source systems. No transformations applied.

    Attributes:
        facilities: Credit facility records
        loans: Drawn loan records
        contingents: Off-balance sheet contingent items
        counterparties: Counterparty/borrower information
        collateral: Security/collateral items
        guarantees: Guarantee/credit protection items
        provisions: IFRS 9 provisions (SCRA/GCRA)
        ratings: Internal and external credit ratings
        facility_mappings: Facility hierarchy mappings
        org_mappings: Organisational hierarchy mappings
        lending_mappings: Lending group mappings (for retail aggregation)
        specialised_lending: Specialised lending metadata (slotting)
        equity_exposures: Equity exposure details
        fx_rates: FX rates for currency conversion (optional)
        model_permissions: Per-model IRB permissions (optional, overrides org-wide IRBPermissions)
        securitisation_allocations: Raw user-supplied mapping of exposures to
            securitisation pools (many rows per exposure). Resolved by the
            SecuritisationAllocator stage; see CRR Art. 244-246.
        ccr: Optional Counterparty Credit Risk inputs (trade /
            netting set / margin agreement / CCR collateral). None
            when the firm has no CCR scope; the CCR stage no-ops in
            that case. See CRR Art. 271-272.
        errors: Validation errors found during loading
    """

    facilities: pl.LazyFrame
    loans: pl.LazyFrame
    counterparties: pl.LazyFrame
    facility_mappings: pl.LazyFrame
    lending_mappings: pl.LazyFrame
    org_mappings: pl.LazyFrame | None = None
    contingents: pl.LazyFrame | None = None
    collateral: pl.LazyFrame | None = None
    guarantees: pl.LazyFrame | None = None
    provisions: pl.LazyFrame | None = None
    ratings: pl.LazyFrame | None = None
    specialised_lending: pl.LazyFrame | None = None
    equity_exposures: pl.LazyFrame | None = None
    ciu_holdings: pl.LazyFrame | None = None
    fx_rates: pl.LazyFrame | None = None
    model_permissions: pl.LazyFrame | None = None
    securitisation_allocations: pl.LazyFrame | None = None
    ccr: RawCCRBundle | None = None
    errors: list[CalculationError] = field(default_factory=list)


@dataclass(frozen=True)
class CounterpartyLookup:
    """
    Resolved counterparty hierarchy information.

    All lookups are LazyFrames for maximum performance.
    Use joins to look up values instead of dict access.

    Attributes:
        counterparties: Counterparty data with resolved hierarchy
        parent_mappings: LazyFrame with child_counterparty_reference -> parent_counterparty_reference
        ultimate_parent_mappings: LazyFrame with counterparty_reference -> ultimate_parent_reference, hierarchy_depth
        rating_inheritance: LazyFrame with counterparty_reference -> rating info with inheritance metadata
    """

    counterparties: pl.LazyFrame
    parent_mappings: pl.LazyFrame
    ultimate_parent_mappings: pl.LazyFrame
    rating_inheritance: pl.LazyFrame


@dataclass(frozen=True)
class ResolvedHierarchyBundle:
    """
    Output from the hierarchy resolver component.

    Contains exposures with fully resolved hierarchies:
    - Counterparty hierarchy (for rating inheritance)
    - Facility hierarchy (for CRM inheritance)
    - Lending group aggregation (for retail threshold)

    Attributes:
        exposures: Unified exposure records (facilities, loans, contingents)
                   with hierarchy metadata added
        counterparty_lookup: Resolved counterparty information
        lending_group_totals: Aggregated exposures by lending group
        collateral: Collateral with beneficiary hierarchy resolved (optional)
        guarantees: Guarantees with beneficiary hierarchy resolved (optional)
        provisions: Provisions with beneficiary hierarchy resolved (optional)
        model_permissions: Per-model IRB permissions (optional, passed from RawDataBundle)
        specialised_lending: Specialised lending metadata (optional, passed from RawDataBundle)
        hierarchy_errors: Any errors encountered during resolution
    """

    exposures: pl.LazyFrame
    counterparty_lookup: CounterpartyLookup
    lending_group_totals: pl.LazyFrame
    collateral: pl.LazyFrame | None = None
    guarantees: pl.LazyFrame | None = None
    provisions: pl.LazyFrame | None = None
    equity_exposures: pl.LazyFrame | None = None
    ciu_holdings: pl.LazyFrame | None = None
    specialised_lending: pl.LazyFrame | None = None
    model_permissions: pl.LazyFrame | None = None
    # Per-exposure resolved securitisation lookup emitted by the
    # SecuritisationAllocator stage. One row per (exposure_reference,
    # exposure_type) carrying residual_pct, pool_allocations struct list,
    # and audit metadata. Joined onto the unified exposures frame so the
    # columns ride downstream to the aggregator.
    securitisation_audit: pl.LazyFrame | None = None
    hierarchy_errors: list[CalculationError] = field(default_factory=list)


@dataclass(frozen=True)
class ClassifiedExposuresBundle:
    """
    Output from the classifier component.

    Contains exposures classified by exposure class and approach.
    Splits exposures into SA-applicable and IRB-applicable sets.

    Attributes:
        all_exposures: All exposures with classification metadata
        sa_exposures: Exposures to be processed via Standardised Approach
        irb_exposures: Exposures to be processed via IRB (F-IRB or A-IRB)
        slotting_exposures: Specialised lending for slotting approach
        equity_exposures: Equity exposures (SA only under Basel 3.1)
        collateral: Collateral data for CRM processing (passed through)
        guarantees: Guarantee data for CRM processing (passed through)
        provisions: Provision data for CRM processing (passed through)
        counterparty_lookup: Counterparty data for guarantor risk weights
        classification_audit: Audit trail of classification decisions
        classification_errors: Any errors during classification
    """

    all_exposures: pl.LazyFrame
    sa_exposures: pl.LazyFrame
    irb_exposures: pl.LazyFrame
    slotting_exposures: pl.LazyFrame | None = None
    equity_exposures: pl.LazyFrame | None = None
    ciu_holdings: pl.LazyFrame | None = None
    collateral: pl.LazyFrame | None = None
    guarantees: pl.LazyFrame | None = None
    provisions: pl.LazyFrame | None = None
    counterparty_lookup: CounterpartyLookup | None = None
    classification_audit: pl.LazyFrame | None = None
    # Pass-through of the resolved securitisation lookup from
    # ResolvedHierarchyBundle. Untouched by the classifier.
    securitisation_audit: pl.LazyFrame | None = None
    classification_errors: list[CalculationError] = field(default_factory=list)


@dataclass(frozen=True)
class CRMAdjustedBundle:
    """
    Output from the CRM processor component.

    Contains exposures with credit risk mitigation applied:
    - Collateral effects (haircuts, allocation)
    - Guarantee effects (substitution)
    - Provision effects (SCRA/GCRA)

    EAD and LGD values are adjusted based on CRM.

    Attributes:
        exposures: Exposures with CRM-adjusted EAD and LGD
        sa_exposures: SA exposures after CRM
        irb_exposures: IRB exposures after CRM
        slotting_exposures: Specialised lending exposures for slotting approach
        equity_exposures: Equity exposures (passed through, no CRM)
        crm_audit: Detailed audit trail of CRM application
        collateral_allocation: How collateral was allocated to exposures
        crm_errors: Any errors during CRM processing
    """

    exposures: pl.LazyFrame
    sa_exposures: pl.LazyFrame
    irb_exposures: pl.LazyFrame
    slotting_exposures: pl.LazyFrame | None = None
    equity_exposures: pl.LazyFrame | None = None
    ciu_holdings: pl.LazyFrame | None = None
    crm_audit: pl.LazyFrame | None = None
    collateral_allocation: pl.LazyFrame | None = None
    # Audit trail emitted by the RealEstateSplitter stage. One row per
    # original exposure that was split, with parent EAD, secured/residual
    # split, effective threshold, target class, and triggering regime.
    re_split_audit: pl.LazyFrame | None = None
    # Pass-through of the resolved securitisation lookup originally emitted
    # by the SecuritisationAllocator stage. Carried downstream so the
    # aggregator can derive the per-pool summary and per-parent
    # reconciliation views.
    securitisation_audit: pl.LazyFrame | None = None
    crm_errors: list[CalculationError] = field(default_factory=list)


@dataclass(frozen=True)
class TradeBundle:
    """
    Trade-level input for SA-CCR.

    Holds the per-derivative-trade LazyFrame consumed by the CCR
    calculator stage. One row per OTC derivative or long-settlement
    transaction; SFTs flow through the same bundle with the
    schema-level ``risk_type`` discriminator (P8.5 extends
    ``VALID_RISK_TYPES_INPUT`` with ``CCR_DERIVATIVE`` and
    ``CCR_SFT``).

    The row schema is enforced by ``TRADE_SCHEMA`` in
    ``rwa_calc.data.schemas`` (added in P8.5). Required columns:
    ``trade_id``, ``netting_set_id``, ``asset_class``,
    ``transaction_type``, ``notional``, ``currency``,
    ``maturity_date``, ``start_date``, ``delta``, ``is_long``,
    ``mtm_value``. Optional: ``underlying_reference``,
    ``option_strike``, ``payment_leg_index_id``.

    References:
    - CRR Art. 272 (definitions)
    - PRA Rulebook CCR (CRR) Part Art. 277(3), 279a-c, 280
    - BCBS CRE52.30-52.43
    """

    trades: pl.LazyFrame
    errors: list[CalculationError] = field(default_factory=list)


@dataclass(frozen=True)
class NettingSetBundle:
    """
    Netting-set-level input for SA-CCR.

    Holds the per-netting-set LazyFrame keyed by ``netting_set_id``.
    Carries the legal-enforceability flag (CRR Art. 295-297) and
    the denormalised margin-agreement parameters consumed by the
    Replacement Cost formula (CRR Art. 275). For the first batch
    (CCR-A1) every netting set is single-trade, unmargined, and
    legally enforceable; the threshold / MTA / NICA / MPOR columns
    are null but schema-present so margined Replacement Cost (P8.11)
    and margined Maturity Factor (P8.14) can read them without
    schema change.

    Row schema enforced by ``NETTING_SET_SCHEMA`` in
    ``rwa_calc.data.schemas`` (added in P8.5).

    References:
    - CRR Art. 272(4) (netting set), 272(7) (margin agreement),
      272(9) (margin period of risk)
    - CRR Art. 295, 296, 297 (recognition of contractual netting)
    - PRA Rulebook CCR (CRR) Part Art. 275(1)-(2), 279c
    - BCBS CRE52.10-52.18, CRE52.51-52
    """

    netting_sets: pl.LazyFrame
    errors: list[CalculationError] = field(default_factory=list)


@dataclass(frozen=True)
class MarginAgreementBundle:
    """
    Margin-agreement-level input for SA-CCR.

    Holds the per-margin-agreement LazyFrame. Separate from
    ``NettingSetBundle`` so a single ISDA CSA covering multiple
    netting sets can be represented without denormalisation.
    For CCR-A1 this bundle's LazyFrame is empty (zero rows,
    schema present) — the four denormalised columns on
    ``NettingSetBundle`` cover the single-netting-set case.

    Row schema enforced by ``MARGIN_AGREEMENT_SCHEMA`` in
    ``rwa_calc.data.schemas`` (added in P8.5).

    References:
    - CRR Art. 272(7) (margin agreement)
    - PRA Rulebook CCR (CRR) Part Art. 275(2), 285(5)
    - BCBS CRE52.17, CRE52.51
    """

    margin_agreements: pl.LazyFrame
    errors: list[CalculationError] = field(default_factory=list)


@dataclass(frozen=True)
class CCRCollateralBundle:
    """
    CCR-specific collateral input for SA-CCR.

    Holds collateral keyed by ``netting_set_id``, which is
    structurally different from ``RawDataBundle.collateral``
    (which is keyed by ``beneficiary_type`` / ``beneficiary_reference``
    against the SA / IRB exposure model). Kept separate so the
    existing collateral-resolution pipeline is untouched.
    Haircut lookup reuses the supervisory haircut tables in
    ``engine/crm/`` (CRR Art. 224); no duplicate table.

    Row schema enforced by ``CCR_COLLATERAL_SCHEMA`` in
    ``rwa_calc.data.schemas`` (added in P8.5).

    References:
    - CRR Art. 275(1)-(2) (net collateral C in RC formula)
    - CRR Art. 224 (supervisory haircuts)
    - CRR Art. 285(3a)-(c) (segregated initial margin)
    """

    ccr_collateral: pl.LazyFrame
    errors: list[CalculationError] = field(default_factory=list)


@dataclass(frozen=True)
class FailedTradesBundle:
    """
    Failed-trade (settlement-risk) input for CRR Title V (Art. 378-380).

    Holds the per-failed-settlement LazyFrame consumed by the
    ``engine/ccr/failed_trades.py`` calculator. One row per failed DvP
    settlement or non-DvP free-delivery transaction, discriminated by
    the schema-level ``settlement_type`` field
    (``"dvp"`` vs ``"non_dvp_free_delivery"``).

    Row schema enforced by ``FAILED_TRADE_SCHEMA`` in
    ``rwa_calc.data.schemas`` (added in P8.24).

    References:
    - CRR Art. 378 + Table 1 (DvP multiplier ladder)
    - CRR Art. 379(1) + Table 2 (non-DvP free-delivery exposure)
    - CRR Art. 379(2)-(3), Art. 380 (electives — schema reserves
      the flags; engine currently treats them as no-op false)
    """

    failed_trades: pl.LazyFrame
    errors: list[CalculationError] = field(default_factory=list)


@dataclass(frozen=True)
class RawCCRBundle:
    """
    Aggregate CCR input bundle — composes the four P8.1 leaf bundles.

    Structurally analogous to ``RawDataBundle``: a frozen composite of
    the per-domain input frames plus a bundle-level ``errors`` list.
    Held as an optional field on ``RawDataBundle`` so firms without
    derivative or SFT books continue to construct valid pipelines —
    the CCR stage (P8.20) no-ops when ``raw.ccr is None``.

    Composition mirrors the CRR Chapter 6 input model:
    - ``trades``: per-derivative-trade rows (CRR Art. 271(1), 272(2))
    - ``netting_sets``: per-netting-set rows (CRR Art. 272(4))
    - ``margin_agreements``: per-CSA rows (CRR Art. 272(7))
    - ``ccr_collateral``: netting-set-keyed collateral (CRR Art. 275(1))
    - ``failed_trades``: optional failed-settlement rows (Art. 378-380)

    Each leaf bundle's LazyFrame may be empty (zero rows, schema
    present) when the firm has no instances of that domain — e.g.
    unmargined single-trade netting sets in CCR-A1 produce an empty
    ``margin_agreements`` frame. Optionality lives one level up at
    ``RawDataBundle.ccr``, not inside this bundle.

    ``failed_trades`` is itself optional: firms without any failed
    settlements leave it as ``None`` and the failed-trade calculator is
    skipped entirely. Backward-compatible with all existing CCR-bundle
    constructions (P8.5 onwards).

    Attributes:
        trades: Trade-level inputs for SA-CCR
        netting_sets: Netting-set-level inputs for SA-CCR
        margin_agreements: Margin-agreement (CSA) inputs for SA-CCR
        ccr_collateral: Netting-set-keyed collateral inputs
        failed_trades: Optional failed-settlement inputs (Art. 378-380)
        errors: Bundle-level wiring errors (e.g. missing leaf file,
            cross-leaf consistency failures). Row-level data-quality
            errors live on the individual leaf bundles.

    References:
    - CRR Art. 271 (scope of CCR — derivatives, repos, SFTs,
      long-settlement, margin lending)
    - CRR Art. 272(4) (netting set), 272(7) (margin agreement),
      272(9) (margin period of risk)
    - CRR Art. 378-380 (settlement risk — failed trades)
    """

    trades: TradeBundle
    netting_sets: NettingSetBundle
    margin_agreements: MarginAgreementBundle
    ccr_collateral: CCRCollateralBundle
    failed_trades: FailedTradesBundle | None = None
    errors: list[CalculationError] = field(default_factory=list)


@dataclass(frozen=True)
class SAResultBundle:
    """
    Output from the SA calculator component.

    Contains Standardised Approach RWA calculations.

    Attributes:
        results: SA calculation results with risk weights and RWA
        calculation_audit: Detailed calculation breakdown
        errors: Any errors during SA calculation
    """

    results: pl.LazyFrame
    calculation_audit: pl.LazyFrame | None = None
    errors: list[CalculationError] = field(default_factory=list)


@dataclass(frozen=True)
class IRBResultBundle:
    """
    Output from the IRB calculator component.

    Contains IRB RWA calculations (F-IRB and A-IRB).

    Attributes:
        results: IRB calculation results with K, RW, RWA
        expected_loss: Expected loss calculations
        calculation_audit: Detailed calculation breakdown (PD, LGD, M, R, K)
        errors: Any errors during IRB calculation
    """

    results: pl.LazyFrame
    expected_loss: pl.LazyFrame | None = None
    calculation_audit: pl.LazyFrame | None = None
    errors: list[CalculationError] = field(default_factory=list)


@dataclass(frozen=True)
class SlottingResultBundle:
    """
    Output from the Slotting calculator component.

    Contains slotting approach RWA calculations for specialised lending.

    Attributes:
        results: Slotting calculation results with risk weights and RWA
        calculation_audit: Detailed calculation breakdown
        errors: Any errors during slotting calculation
    """

    results: pl.LazyFrame
    calculation_audit: pl.LazyFrame | None = None
    errors: list[CalculationError] = field(default_factory=list)


@dataclass(frozen=True)
class EquityResultBundle:
    """
    Output from the Equity calculator component.

    Contains equity exposure RWA calculations under either:
    - Article 133 (Standardised Approach)
    - Article 155 (IRB Simple Risk Weight)

    Attributes:
        results: Equity calculation results with risk weights and RWA
        calculation_audit: Detailed calculation breakdown
        approach: The equity approach used (EquityApproach.SA or EquityApproach.IRB_SIMPLE)
        errors: Any errors during equity calculation
    """

    results: pl.LazyFrame
    calculation_audit: pl.LazyFrame | None = None
    approach: EquityApproach = EquityApproach.SA
    errors: list[CalculationError] = field(default_factory=list)


@dataclass(frozen=True)
class ELPortfolioSummary:
    """
    Portfolio-level expected loss summary with T2 credit cap.

    Aggregates per-exposure EL shortfall/excess into portfolio totals
    and applies the T2 credit cap per CRR Art. 62(d).

    Key responsibilities:
    - Sum per-exposure EL, provisions, AVAs, other own funds reductions,
      shortfall, and excess
    - Compute T2 credit cap (0.6% of IRB RWA per CRR Art. 62(d))
    - Compute T2 credit (min of total excess and cap)
    - Compute CET1 deduction (100% of shortfall per Art. 36(1)(d), Art. 159)
    - Apply Art. 159(3) two-branch rule: when non-defaulted EL exceeds
      non-defaulted provisions AND defaulted provisions exceed defaulted
      EL simultaneously, shortfall and excess are computed separately
      for each pool — defaulted excess cannot offset non-defaulted shortfall

    Pool B per Art. 159(1) includes:
    (a) General credit risk adjustments (GCRA)
    (b) Specific credit risk adjustments (SCRA) for non-defaulted
    (c) Additional value adjustments (AVAs per Art. 34)
    (d) Other own funds reductions

    References:
    - CRR Art. 62(d): T2 credit cap for EL excess
    - CRR Art. 158: EL shortfall deduction
    - CRR Art. 159(1): Pool B composition
    - CRR Art. 159(3): Two-branch no-cross-offset rule
    - CRR Art. 34, Art. 105: Additional value adjustments

    Attributes:
        total_expected_loss: Sum of expected loss across all IRB exposures
        total_provisions_allocated: Sum of provisions allocated to IRB exposures
        total_ava_amount: Sum of AVAs (Art. 34) allocated to IRB exposures
        total_other_own_funds_reductions: Sum of other own funds reductions
        total_pool_b: Total Pool B (provisions + AVA + other own funds reductions)
        total_el_shortfall: Effective shortfall after Art. 159(3) rule
        total_el_excess: Effective excess after Art. 159(3) rule
        total_irb_rwa: Total IRB RWA (denominator for T2 cap)
        t2_credit_cap: 0.6% of total IRB RWA
        t2_credit: min(total_el_excess, t2_credit_cap) — addable to T2 capital
        cet1_deduction: 100% of total_el_shortfall — deducted from CET1 (Art. 36(1)(d))
        t2_deduction: Always zero — no T2 deduction for shortfall (kept for API stability)
        non_defaulted_el_shortfall: Shortfall from non-defaulted exposures only
        non_defaulted_el_excess: Excess from non-defaulted exposures only
        defaulted_el_shortfall: Shortfall from defaulted exposures only
        defaulted_el_excess: Excess from defaulted exposures only
        art_159_3_applies: True when two-branch condition is triggered
    """

    total_expected_loss: Decimal
    total_provisions_allocated: Decimal
    total_el_shortfall: Decimal
    total_el_excess: Decimal
    total_irb_rwa: Decimal
    t2_credit_cap: Decimal
    t2_credit: Decimal
    cet1_deduction: Decimal
    t2_deduction: Decimal
    non_defaulted_el_shortfall: Decimal = Decimal("0")
    non_defaulted_el_excess: Decimal = Decimal("0")
    defaulted_el_shortfall: Decimal = Decimal("0")
    defaulted_el_excess: Decimal = Decimal("0")
    art_159_3_applies: bool = False
    total_ava_amount: Decimal = Decimal("0")
    total_other_own_funds_reductions: Decimal = Decimal("0")
    total_pool_b: Decimal = Decimal("0")


@dataclass(frozen=True)
class OutputFloorSummary:
    """
    Portfolio-level output floor summary (Basel 3.1).

    The output floor is applied at portfolio level per PRA PS1/26 Art. 92
    para 2A: TREA = max(U-TREA, x * S-TREA + OF-ADJ). When the floor binds,
    the shortfall is distributed pro-rata across floor-eligible exposures
    (IRB + slotting) proportional to each exposure's SA-equivalent RWA.

    OF-ADJ = 12.5 * (IRB_T2 - IRB_CET1 - GCRA + SA_T2) reconciles the
    different provision treatments between IRB (EL shortfall/excess) and SA
    (general credit risk adjustments) so the floor comparison is like-for-like.

    Attributes:
        u_trea: Total RWA for floor-eligible exposures using actual approaches
        s_trea: Total SA-equivalent RWA for the same exposures
        floor_pct: Floor percentage applied (e.g. 0.725 for 72.5%)
        floor_threshold: x * s_trea + of_adj — the minimum acceptable RWA
        shortfall: max(0, floor_threshold - u_trea) — add-on when floor binds
        portfolio_floor_binding: True when the portfolio floor binds
        floored_modelled_rwa: u_trea + shortfall (= max(u_trea, floor_threshold))
            — modelled-only post-floor RWA. Excludes SA and equity rows.
        total_rwa_post_floor: Genuine portfolio total post-floor RWA
            = floored_modelled_rwa + sa_rwa_total + equity_rwa_total.
        of_adj: Output Floor Adjustment per Art. 92 para 2A
        irb_t2_credit: Art. 62(d) IRB T2 credit (capped at 0.6% of IRB RWA)
        irb_cet1_deduction: Art. 36(1)(d) + Art. 40 CET1 deductions
        gcra_amount: General credit risk adjustments (capped at 1.25% of S-TREA)
        sa_t2_credit: Art. 62(c) SA T2 credit
        sa_rwa_total: Sum of ``rwa_final`` across SA rows in the portfolio
        equity_rwa_total: Sum of ``rwa_final`` across equity rows in the portfolio

    References:
    - PRA PS1/26 Art. 92 para 2A
    - CRE99.1-8: Output floor (Basel 3.1)
    """

    u_trea: float
    s_trea: float
    floor_pct: float
    floor_threshold: float
    shortfall: float
    portfolio_floor_binding: bool
    floored_modelled_rwa: float
    of_adj: float = 0.0
    irb_t2_credit: float = 0.0
    irb_cet1_deduction: float = 0.0
    gcra_amount: float = 0.0
    sa_t2_credit: float = 0.0
    sa_rwa_total: float = 0.0
    equity_rwa_total: float = 0.0
    total_rwa_post_floor: float = 0.0


@dataclass(frozen=True)
class AggregatedResultBundle:
    """
    Final aggregated output from the output aggregator.

    Combines SA and IRB results with output floor application
    and supporting factor adjustments.

    Attributes:
        results: Final RWA results with all adjustments
        sa_results: Original SA results (for floor comparison)
        irb_results: Original IRB results (before floor)
        slotting_results: Original slotting results
        equity_results: Equity calculation results
        floor_impact: Output floor impact analysis (per-exposure)
        output_floor_summary: Portfolio-level output floor summary
        supporting_factor_impact: Supporting factor impact (CRR only)
        summary_by_class: RWA summarised by exposure class
        summary_by_approach: RWA summarised by approach
        pre_crm_summary: Pre-CRM summary (gross view by original class)
        post_crm_detailed: Post-CRM detailed view (split rows for guarantees)
        post_crm_summary: Post-CRM summary (net view by effective class)
        el_summary: Portfolio-level EL summary with T2 credit cap (IRB only)
        securitisation_summary: Per-pool EAD/RWA summary derived from each
            row's ``securitisation_pool_allocations`` (phase 1: placeholder
            RWA = standard RWA × allocation_pct; SEC-SA/SEC-IRBA out of
            scope). Null when no securitisation allocations were supplied.
        securitisation_audit: Per-exposure reconciliation showing the parent
            EAD, residual portion, sum of pool slices, and any validation
            status flags from the allocator stage (CRR Art. 244-246).
        errors: All errors accumulated throughout pipeline
    """

    results: pl.LazyFrame
    sa_results: pl.LazyFrame | None = None
    irb_results: pl.LazyFrame | None = None
    slotting_results: pl.LazyFrame | None = None
    equity_results: pl.LazyFrame | None = None
    floor_impact: pl.LazyFrame | None = None
    output_floor_summary: OutputFloorSummary | None = None
    supporting_factor_impact: pl.LazyFrame | None = None
    summary_by_class: pl.LazyFrame | None = None
    summary_by_approach: pl.LazyFrame | None = None
    pre_crm_summary: pl.LazyFrame | None = None
    post_crm_detailed: pl.LazyFrame | None = None
    post_crm_summary: pl.LazyFrame | None = None
    el_summary: ELPortfolioSummary | None = None
    securitisation_summary: pl.LazyFrame | None = None
    securitisation_audit: pl.LazyFrame | None = None
    errors: list[CalculationError] = field(default_factory=list)


# =============================================================================
# HELPER FUNCTIONS FOR BUNDLE CREATION
# =============================================================================


@dataclass(frozen=True)
class ComparisonBundle:
    """
    Output from dual-framework comparison (M3.1).

    Holds CRR and Basel 3.1 pipeline results side by side, plus
    pre-computed delta LazyFrames for impact analysis.

    Why: During the Basel 3.1 transition period, firms must run both
    frameworks in parallel to understand capital impact. This bundle
    provides the joined results needed for M3.2 capital impact analysis
    and M3.3 transitional floor schedule modelling.

    Attributes:
        crr_results: Full CRR pipeline output
        b31_results: Full Basel 3.1 pipeline output
        exposure_deltas: Per-exposure comparison (CRR vs B31 RWA, risk weights, EAD)
        summary_by_class: Delta RWA aggregated by exposure class
        summary_by_approach: Delta RWA aggregated by calculation approach
        errors: Combined errors from both pipeline runs
    """

    crr_results: AggregatedResultBundle
    b31_results: AggregatedResultBundle
    exposure_deltas: pl.LazyFrame
    summary_by_class: pl.LazyFrame
    summary_by_approach: pl.LazyFrame
    errors: list[CalculationError] = field(default_factory=list)


@dataclass(frozen=True)
class TransitionalScheduleBundle:
    """
    Output from transitional floor schedule modelling (M3.3).

    Runs the same portfolio through Basel 3.1 for each transitional year
    (2027-2032) to show how the output floor progressively tightens.

    Why: PRA PS1/26 phases in the output floor from 50% (2027) to 72.5%
    (2032+). Firms need to model the year-by-year capital trajectory to
    plan for the increasing floor bite. This bundle provides the timeline
    data needed for capital planning and M3.4 Marimo visualisation.

    Timeline columns:
        reporting_date: The as-of date for each year
        year: Calendar year (2027-2032)
        floor_percentage: Output floor percentage for that year
        total_rwa_pre_floor: Total IRB RWA before floor application
        total_rwa_post_floor: Total RWA after floor (final regulatory RWA)
        total_floor_impact: Additional RWA from the floor binding
        floor_binding_count: Number of exposures where floor binds
        total_irb_exposure_count: Total IRB exposures in portfolio
        total_ead: Total EAD across all exposures
        total_sa_rwa: Total SA-equivalent RWA (floor benchmark)

    Attributes:
        timeline: Year-by-year floor impact summary
        yearly_results: Full pipeline results for each transitional year
        errors: Combined errors from all pipeline runs
    """

    timeline: pl.LazyFrame
    yearly_results: dict[int, AggregatedResultBundle] = field(default_factory=dict)
    errors: list[CalculationError] = field(default_factory=list)


@dataclass(frozen=True)
class CapitalImpactBundle:
    """
    Output from capital impact analysis (M3.2).

    Decomposes the RWA delta between CRR and Basel 3.1 into attributable
    regulatory drivers using a sequential waterfall methodology:

    1. Scaling factor removal — CRR applies 1.06x to IRB RWA; Basel 3.1 removes it
    2. Supporting factor removal — CRR applies SME/infrastructure factors; Basel 3.1 removes them
    3. Methodology & parameter changes — residual (PD/LGD floors, SA RW changes, etc.)
    4. Output floor impact — Basel 3.1 floors IRB RWA at X% of SA RWA

    Why: During Basel 3.1 transition, firms need to understand not just
    the total capital impact but WHY RWA changes — which regulatory
    drivers are responsible. This enables targeted capital planning and
    stakeholder communication about transition effects.

    The waterfall is additive: scaling + supporting + floor + methodology = delta_rwa.

    Attributes:
        exposure_attribution: Per-exposure driver attribution
        portfolio_waterfall: Portfolio-level waterfall steps (CRR baseline to B31)
        summary_by_class: Attribution aggregated by exposure class
        summary_by_approach: Attribution aggregated by calculation approach
        errors: Any errors during analysis
    """

    exposure_attribution: pl.LazyFrame
    portfolio_waterfall: pl.LazyFrame
    summary_by_class: pl.LazyFrame
    summary_by_approach: pl.LazyFrame
    errors: list[CalculationError] = field(default_factory=list)


# =============================================================================
# HELPER FUNCTIONS FOR BUNDLE CREATION
# =============================================================================


def create_empty_raw_data_bundle() -> RawDataBundle:
    """
    Create an empty RawDataBundle for testing.

    Returns a bundle with empty LazyFrames that conform to
    expected schemas.
    """
    import polars as pl

    return RawDataBundle(
        facilities=pl.LazyFrame(),
        loans=pl.LazyFrame(),
        counterparties=pl.LazyFrame(),
        facility_mappings=pl.LazyFrame(),
        lending_mappings=pl.LazyFrame(),
        org_mappings=None,
        contingents=None,
        collateral=None,
        guarantees=None,
        provisions=None,
        ratings=None,
        fx_rates=None,
        securitisation_allocations=None,
    )


def create_empty_counterparty_lookup() -> CounterpartyLookup:
    """Create an empty CounterpartyLookup for testing."""
    import polars as pl

    return CounterpartyLookup(
        counterparties=pl.LazyFrame(schema={"counterparty_reference": pl.String}),
        parent_mappings=pl.LazyFrame(
            schema={
                "child_counterparty_reference": pl.String,
                "parent_counterparty_reference": pl.String,
            }
        ),
        ultimate_parent_mappings=pl.LazyFrame(
            schema={
                "counterparty_reference": pl.String,
                "ultimate_parent_reference": pl.String,
                "hierarchy_depth": pl.Int32,
            }
        ),
        rating_inheritance=pl.LazyFrame(
            schema={
                "counterparty_reference": pl.String,
                "internal_pd": pl.Float64,
                "internal_model_id": pl.String,
                "external_cqs": pl.Int8,
                "cqs": pl.Int8,
                "pd": pl.Float64,
            }
        ),
    )


def create_empty_resolved_hierarchy_bundle() -> ResolvedHierarchyBundle:
    """Create an empty ResolvedHierarchyBundle for testing."""
    import polars as pl

    return ResolvedHierarchyBundle(
        exposures=pl.LazyFrame(),
        counterparty_lookup=create_empty_counterparty_lookup(),
        lending_group_totals=pl.LazyFrame(),
        collateral=None,
        guarantees=None,
        provisions=None,
    )


def create_empty_classified_bundle() -> ClassifiedExposuresBundle:
    """Create an empty ClassifiedExposuresBundle for testing."""
    import polars as pl

    return ClassifiedExposuresBundle(
        all_exposures=pl.LazyFrame(),
        sa_exposures=pl.LazyFrame(),
        irb_exposures=pl.LazyFrame(),
    )


def create_empty_crm_adjusted_bundle() -> CRMAdjustedBundle:
    """Create an empty CRMAdjustedBundle for testing."""
    import polars as pl

    return CRMAdjustedBundle(
        exposures=pl.LazyFrame(),
        sa_exposures=pl.LazyFrame(),
        irb_exposures=pl.LazyFrame(),
    )
