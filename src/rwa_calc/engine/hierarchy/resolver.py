"""
Hierarchy resolver recipe for the hierarchy stage.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier

Key responsibilities:
- ``HierarchyResolver.resolve``: the stage recipe — the PS1/26 Art.
  138(1)(g) implicit-support ratings filter, counterparty lookup
  build, exposure unification, short-term rating override, FX conversion,
  real-estate collateral-link expansion (``re_links``), LTV /
  property-coverage / lending-group enrichment, lending_group_totals
  aggregate, and the ``hierarchy_resolved`` producer seal.
- Thin delegating private methods preserving the historical
  ``HierarchyResolver._*`` surface for tests and callers; the
  implementations live in the sibling sub-modules (``graph``, ``ratings``,
  ``facility_undrawn``, ``unify``, ``enrich``).

References:
- CRR Art. 131: Short-term rating override for institutional exposures
- CRR Art. 135 / 136 / 138 / 139 / 140: ECAI rating use and mapping
- PS1/26 Art. 138(1)(g): implicit-government-support assessments (Basel 3.1)
- CRR Art. 4(1)(39): Group of connected clients (hierarchy resolution)

Usage:
    from rwa_calc.engine.hierarchy import HierarchyResolver

    resolver = HierarchyResolver()
    resolved = resolver.resolve(raw_data, config)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.bundles import (
    CounterpartyLookup,
    RawDataBundle,
    ResolvedHierarchyBundle,
)
from rwa_calc.contracts.edges import HIERARCHY_RESOLVED_EDGE, seal
from rwa_calc.engine.fx import convert_resolved_frames
from rwa_calc.engine.hierarchy.enrich import (
    add_collateral_ltv,
    apply_short_term_rating_override,
    attach_obligor_country_to_equity,
    enrich_with_lending_group,
    enrich_with_property_coverage,
    enrich_with_residential_security,
)
from rwa_calc.engine.hierarchy.facility_undrawn import calculate_facility_undrawn
from rwa_calc.engine.hierarchy.graph import (
    build_counterparty_lookup,
    build_facility_ancestor_closure,
    build_facility_root_lookup,
    build_ultimate_parent_lazy,
)
from rwa_calc.engine.hierarchy.ratings import (
    build_rating_inheritance_lazy,
    disregard_implicit_support_ratings,
)
from rwa_calc.engine.hierarchy.re_links import expand_real_estate_links
from rwa_calc.engine.hierarchy.unify import unify_exposures
from rwa_calc.rulebook import RulepackV0

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.contracts.errors import CalculationError
    from rwa_calc.rulebook.resolve import ResolvedRulepack

logger = logging.getLogger(__name__)


class HierarchyResolver:
    """
    Resolve counterparty and exposure hierarchies.

    Implements HierarchyResolverProtocol for:
    - Building counterparty org hierarchy lookups
    - Inheriting ratings from parent entities
    - Resolving facility-to-exposure mappings
    - Aggregating lending group exposures for retail threshold

    All operations use Polars LazyFrames for deferred execution.
    """

    def resolve(
        self,
        data: RawDataBundle,
        config: CalculationConfig,
        *,
        pack: ResolvedRulepack | None = None,
    ) -> ResolvedHierarchyBundle:
        """
        Resolve all hierarchies and return enriched data.

        Args:
            data: Raw data bundle from loader
            config: Calculation configuration
            pack: Optional resolved rulepack — the run's, which the hierarchy
                stage passes so an injected overlay is honoured; falls back to
                ``RulepackV0.from_config(config).pack`` when ``None``. Read by
                the Art. 140(1) short-term-ECAI obligor-class gate, whose
                entity-type -> SA-class map must be the one the classifier
                reads (P1.370), and by the PS1/26 Art. 138(1)(g)
                implicit-support filter (its Feature and the same map).

        Returns:
            ResolvedHierarchyBundle with hierarchy metadata added
        """
        resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack
        errors: list[CalculationError] = []

        # PS1/26 Art. 138(1)(g) (Basel 3.1 only): drop the implicit-support
        # external assessments of institution obligors from the TABLE, before the
        # long-term Art. 138 selection and the short-term override below both read
        # it — (g) shrinks the set those selections choose from. A no-op under CRR.
        # The DQ015 unsolicited count is taken on this filtered table, so a
        # disregarded unsolicited assessment (never used) is not counted.
        ratings = disregard_implicit_support_ratings(
            data.ratings, data.counterparties, resolved_pack
        )

        counterparty_lookup, cp_errors = self._build_counterparty_lookup(
            data.counterparties,
            data.org_mappings,
            ratings,
        )
        errors.extend(cp_errors)

        # facility_mappings is sealed at the loader edge: ``child_type`` always
        # exists (typed null when unreported) and the legacy ``node_type``
        # alias has already been translated by the loader.
        # ``fx_rates`` reaches the unify step only to put each drawing in its
        # FACILITY's currency before headroom is netted (CM-02 / SF-01); the
        # run's conversion to the reporting currency still happens below.
        exposures, exp_errors = self._unify_exposures(
            data.loans,
            data.contingents,
            data.facilities,
            data.facility_mappings,
            counterparty_lookup,
            config,
            fx_rates=data.fx_rates,
            pack=resolved_pack,
        )
        errors.extend(exp_errors)

        # Per-exposure short-term rating override (PRA PS1/26 Art. 120(2B) Table
        # 4A, Art. 122(3) Table 6A). Short-term ECAI assessments are issue-
        # specific, attached to a particular exposure rather than the
        # counterparty as a whole; when present, they override the counterparty-
        # level long-term rating for SA risk-weight routing.
        exposures = self._apply_short_term_rating_override(
            exposures, ratings, counterparty_lookup, errors, pack=resolved_pack
        )

        # Apply FX conversion so threshold calculations use consistent currency.
        # The converter methods also preserve ``original_currency`` when conversion
        # is disabled or no FX rates are supplied, so downstream FX-mismatch checks
        # (Art. 224 H_fx on collateral, guarantees) always have the pre-conversion
        # currency pair available. The unify -> FX -> enrich ordering is
        # load-bearing — do not move this call (LTV / property coverage /
        # lending-group totals below assume reporting-currency amounts).
        exposures, collateral, guarantees, provisions, equity_exposures = convert_resolved_frames(
            exposures,
            data.collateral,
            data.guarantees,
            data.provisions,
            data.equity_exposures,
            data.fx_rates,
            config,
        )

        equity_exposures = attach_obligor_country_to_equity(
            equity_exposures, counterparty_lookup.counterparties
        )

        # P1.450 (review CL-13): the property enrichment reads a view in which
        # each real-estate item spread by ``collateral_links`` is one row per
        # link, so every linked loan carries the property, a pro-rata share of
        # its value and, where no LTV is supplied, the PS1/26 Art. 124C(3) pooled
        # LTV. The bundle keeps the collateral as supplied: the CRM stage expands
        # the links itself.
        property_collateral = expand_real_estate_links(
            exposures,
            collateral,
            data.collateral_links,
            enabled=config.enable_collateral_link_splitting,
        )
        exposures = self._add_collateral_ltv(exposures, property_collateral)

        # .over() window functions avoid group_by + join-back plan tree branching
        exposures = self._enrich_with_property_coverage(exposures, property_collateral)
        # PS1/26 Art. 147(5B): residential security on every route the CRM
        # allocates collateral on, links and the facility cascade included (P1.324).
        exposures = enrich_with_residential_security(exposures, collateral, data.collateral_links)
        exposures = self._enrich_with_lending_group(exposures, data.lending_mappings)

        # Derive lending_group_totals for bundle API contract
        lending_group_totals = (
            exposures.filter(pl.col("lending_group_reference").is_not_null())
            .group_by("lending_group_reference")
            .agg(
                [
                    pl.col("drawn_amount").clip(lower_bound=0.0).sum().alias("total_drawn"),
                    pl.col("nominal_amount").sum().alias("total_nominal"),
                    (pl.col("drawn_amount").clip(lower_bound=0.0) + pl.col("nominal_amount"))
                    .sum()
                    .alias("total_exposure"),
                    pl.col("exposure_for_retail_threshold").sum().alias("adjusted_exposure"),
                    pl.col("residential_collateral_value")
                    .sum()
                    .alias("total_residential_coverage"),
                    pl.len().alias("exposure_count"),
                ]
            )
        )

        return ResolvedHierarchyBundle(
            # Producer seal (Phase 3): pure plan-level conform + brand — no
            # materialisation here. The orchestrator re-seals against the
            # full hierarchy_exit contract after attaching the
            # securitisation lookup, where the stage-exit collect happens.
            exposures=seal(exposures, HIERARCHY_RESOLVED_EDGE),
            counterparty_lookup=counterparty_lookup,
            collateral=collateral,
            collateral_links=data.collateral_links,
            guarantees=guarantees,
            provisions=provisions,
            equity_exposures=equity_exposures,
            ciu_holdings=data.ciu_holdings,
            specialised_lending=data.specialised_lending,
            model_permissions=data.model_permissions,
            lending_group_totals=lending_group_totals,
            hierarchy_errors=errors,
        )

    # -------------------------------------------------------------------
    # Thin delegators — back-compat private-method surface.
    #
    # The implementations moved to the stage sub-modules (Phase 4 Slice 2).
    # Tests and callers continue to invoke these on a resolver instance;
    # each delegator preserves the original signature exactly.
    # -------------------------------------------------------------------

    def _build_counterparty_lookup(
        self,
        counterparties: pl.LazyFrame,
        org_mappings: pl.LazyFrame | None,
        ratings: pl.LazyFrame | None,
    ) -> tuple[CounterpartyLookup, list[CalculationError]]:
        """Delegate to :func:`graph.build_counterparty_lookup`."""
        return build_counterparty_lookup(counterparties, org_mappings, ratings)

    def _build_ultimate_parent_lazy(
        self,
        org_mappings: pl.LazyFrame,
        max_depth: int = 10,
    ) -> pl.LazyFrame:
        """Delegate to :func:`graph.build_ultimate_parent_lazy`."""
        return build_ultimate_parent_lazy(org_mappings, max_depth)

    def _build_rating_inheritance_lazy(
        self,
        counterparties: pl.LazyFrame,
        ratings: pl.LazyFrame,
        ultimate_parents: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """Delegate to :func:`ratings.build_rating_inheritance_lazy`."""
        return build_rating_inheritance_lazy(counterparties, ratings, ultimate_parents)

    def _build_facility_root_lookup(
        self,
        facility_mappings: pl.LazyFrame,
        max_depth: int = 10,
    ) -> pl.LazyFrame:
        """Delegate to :func:`graph.build_facility_root_lookup`."""
        return build_facility_root_lookup(facility_mappings, max_depth)

    def _build_facility_ancestor_closure(
        self,
        facility_mappings: pl.LazyFrame,
        max_depth: int = 10,
    ) -> pl.LazyFrame:
        """Delegate to :func:`graph.build_facility_ancestor_closure`."""
        return build_facility_ancestor_closure(facility_mappings, max_depth)

    def _calculate_facility_undrawn(
        self,
        facilities: pl.LazyFrame,
        loans: pl.LazyFrame,
        contingents: pl.LazyFrame | None,
        facility_mappings: pl.LazyFrame,
        facility_root_lookup: pl.LazyFrame | None = None,
        counterparty_lookup: CounterpartyLookup | None = None,
        config: CalculationConfig | None = None,
        fx_rates: pl.LazyFrame | None = None,
        *,
        pack: ResolvedRulepack | None = None,
    ) -> pl.LazyFrame:
        """Delegate to :func:`facility_undrawn.calculate_facility_undrawn`."""
        return calculate_facility_undrawn(
            facilities,
            loans,
            contingents,
            facility_mappings,
            facility_root_lookup,
            counterparty_lookup=counterparty_lookup,
            config=config,
            fx_rates=fx_rates,
            pack=pack,
        )

    def _unify_exposures(
        self,
        loans: pl.LazyFrame,
        contingents: pl.LazyFrame | None,
        facilities: pl.LazyFrame | None,
        facility_mappings: pl.LazyFrame,
        counterparty_lookup: CounterpartyLookup,
        config: CalculationConfig | None = None,
        fx_rates: pl.LazyFrame | None = None,
        *,
        pack: ResolvedRulepack | None = None,
    ) -> tuple[pl.LazyFrame, list[CalculationError]]:
        """Delegate to :func:`unify.unify_exposures`."""
        return unify_exposures(
            loans,
            contingents,
            facilities,
            facility_mappings,
            counterparty_lookup,
            config,
            fx_rates=fx_rates,
            pack=pack,
        )

    def _apply_short_term_rating_override(
        self,
        exposures: pl.LazyFrame,
        ratings: pl.LazyFrame | None,
        counterparty_lookup: CounterpartyLookup,
        errors: list[CalculationError],
        *,
        pack: ResolvedRulepack | None = None,
    ) -> pl.LazyFrame:
        """Delegate to :func:`enrich.apply_short_term_rating_override`.

        Threads the counterparty lookup and the run's pack (for the Art. 140(1)
        obligor-class gate) and the run's error accumulator (for DQ009
        mis-scope warnings).
        """
        return apply_short_term_rating_override(
            exposures, ratings, counterparty_lookup, errors, pack=pack
        )

    def _enrich_with_property_coverage(
        self,
        exposures: pl.LazyFrame,
        collateral: pl.LazyFrame | None,
    ) -> pl.LazyFrame:
        """Delegate to :func:`enrich.enrich_with_property_coverage`."""
        return enrich_with_property_coverage(exposures, collateral)

    def _enrich_with_lending_group(
        self,
        exposures: pl.LazyFrame,
        lending_mappings: pl.LazyFrame | None,
    ) -> pl.LazyFrame:
        """Delegate to :func:`enrich.enrich_with_lending_group`."""
        return enrich_with_lending_group(exposures, lending_mappings)

    def _add_collateral_ltv(
        self,
        exposures: pl.LazyFrame,
        collateral: pl.LazyFrame | None,
    ) -> pl.LazyFrame:
        """Delegate to :func:`enrich.add_collateral_ltv`."""
        return add_collateral_ltv(exposures, collateral)
