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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import polars as pl


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
    """

    facilities: pl.LazyFrame
    loans: pl.LazyFrame
    contingents: pl.LazyFrame
    counterparties: pl.LazyFrame
    collateral: pl.LazyFrame
    guarantees: pl.LazyFrame
    provisions: pl.LazyFrame
    ratings: pl.LazyFrame
    facility_mappings: pl.LazyFrame
    org_mappings: pl.LazyFrame
    lending_mappings: pl.LazyFrame
    specialised_lending: pl.LazyFrame | None = None
    equity_exposures: pl.LazyFrame | None = None


@dataclass(frozen=True)
class CounterpartyLookup:
    """
    Resolved counterparty hierarchy information.

    Provides quick access to counterparty attributes including
    inherited values from parent entities.

    Attributes:
        counterparties: Counterparty data with resolved hierarchy
        parent_lookup: Mapping child -> immediate parent reference
        ultimate_parent_lookup: Mapping child -> ultimate parent reference
        rating_lookup: Counterparty -> rating information (possibly inherited)
    """

    counterparties: pl.LazyFrame
    parent_lookup: dict[str, str] = field(default_factory=dict)
    ultimate_parent_lookup: dict[str, str] = field(default_factory=dict)
    rating_lookup: dict[str, dict] = field(default_factory=dict)


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
        collateral: Collateral with beneficiary hierarchy resolved
        guarantees: Guarantees with beneficiary hierarchy resolved
        provisions: Provisions with beneficiary hierarchy resolved
        lending_group_totals: Aggregated exposures by lending group
        hierarchy_errors: Any errors encountered during resolution
    """

    exposures: pl.LazyFrame
    counterparty_lookup: CounterpartyLookup
    collateral: pl.LazyFrame
    guarantees: pl.LazyFrame
    provisions: pl.LazyFrame
    lending_group_totals: pl.LazyFrame
    hierarchy_errors: list = field(default_factory=list)


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
        classification_audit: Audit trail of classification decisions
        classification_errors: Any errors during classification
    """

    all_exposures: pl.LazyFrame
    sa_exposures: pl.LazyFrame
    irb_exposures: pl.LazyFrame
    slotting_exposures: pl.LazyFrame | None = None
    equity_exposures: pl.LazyFrame | None = None
    classification_audit: pl.LazyFrame | None = None
    classification_errors: list = field(default_factory=list)


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
        crm_audit: Detailed audit trail of CRM application
        collateral_allocation: How collateral was allocated to exposures
        crm_errors: Any errors during CRM processing
    """

    exposures: pl.LazyFrame
    sa_exposures: pl.LazyFrame
    irb_exposures: pl.LazyFrame
    crm_audit: pl.LazyFrame | None = None
    collateral_allocation: pl.LazyFrame | None = None
    crm_errors: list = field(default_factory=list)


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
    errors: list = field(default_factory=list)


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
    errors: list = field(default_factory=list)


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
        floor_impact: Output floor impact analysis
        supporting_factor_impact: Supporting factor impact (CRR only)
        summary_by_class: RWA summarised by exposure class
        summary_by_approach: RWA summarised by approach
        errors: All errors accumulated throughout pipeline
    """

    results: pl.LazyFrame
    sa_results: pl.LazyFrame | None = None
    irb_results: pl.LazyFrame | None = None
    floor_impact: pl.LazyFrame | None = None
    supporting_factor_impact: pl.LazyFrame | None = None
    summary_by_class: pl.LazyFrame | None = None
    summary_by_approach: pl.LazyFrame | None = None
    errors: list = field(default_factory=list)


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
        contingents=pl.LazyFrame(),
        counterparties=pl.LazyFrame(),
        collateral=pl.LazyFrame(),
        guarantees=pl.LazyFrame(),
        provisions=pl.LazyFrame(),
        ratings=pl.LazyFrame(),
        facility_mappings=pl.LazyFrame(),
        org_mappings=pl.LazyFrame(),
        lending_mappings=pl.LazyFrame(),
    )


def create_empty_counterparty_lookup() -> CounterpartyLookup:
    """Create an empty CounterpartyLookup for testing."""
    import polars as pl

    return CounterpartyLookup(
        counterparties=pl.LazyFrame(),
        parent_lookup={},
        ultimate_parent_lookup={},
        rating_lookup={},
    )


def create_empty_resolved_hierarchy_bundle() -> ResolvedHierarchyBundle:
    """Create an empty ResolvedHierarchyBundle for testing."""
    import polars as pl

    return ResolvedHierarchyBundle(
        exposures=pl.LazyFrame(),
        counterparty_lookup=create_empty_counterparty_lookup(),
        collateral=pl.LazyFrame(),
        guarantees=pl.LazyFrame(),
        provisions=pl.LazyFrame(),
        lending_group_totals=pl.LazyFrame(),
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
