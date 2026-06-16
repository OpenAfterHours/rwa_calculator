"""
Exposure classifier recipe for the classification stage.

Pipeline position:
    HierarchyResolver -> ExposureClassifier (stages/classify) -> CRMProcessor

Key responsibilities:
- ``ExposureClassifier.classify``: the stage recipe — counterparty
  attribute join, SL join, independent flags, subtype classification,
  corporate→retail reclassification, RE-split candidate flagging, model
  permission resolution, approach assignment, B31 subclass derivation,
  the stage-exit ``materialise_edge``, the two post-materialise diagnostic
  collects, and the brand-selected producer ``seal``.
- ``ExposureClassifier._build_bundle``: assemble the
  ``ClassifiedExposuresBundle`` (pass-through frames + audit trail).

The step implementations live in the sibling sub-modules (``attributes``,
``subtypes``, ``permissions``, ``approach``, ``audit``) plus the co-located
RE-split candidate flagging in ``stages/re_split/flagging.py`` (Slice 4).

References:
- CRR Art. 112-134: Exposure classes
- CRR Art. 147-153: IRB approach assignment
- CRR Art. 501: SME supporting factor definition

Usage:
    from rwa_calc.engine.stages.classify import ExposureClassifier

    classifier = ExposureClassifier()
    classified = classifier.classify(resolved_data, config)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from watchfire import cites

from rwa_calc.contracts.bundles import (
    ClassifiedExposuresBundle,
    ResolvedHierarchyBundle,
)
from rwa_calc.contracts.edges import (
    CLASSIFIER_EXIT_CCR_EDGE,
    CLASSIFIER_EXIT_EDGE,
    seal,
    sealed_edge_of,
)
from rwa_calc.engine.materialise import materialise_edge
from rwa_calc.engine.stages.classify.approach import assign_approach
from rwa_calc.engine.stages.classify.attributes import (
    add_counterparty_attributes,
    derive_independent_flags,
    join_specialised_lending,
)
from rwa_calc.engine.stages.classify.audit import (
    build_audit_trail,
    collect_beel_on_non_defaulted_warnings,
    collect_input_warnings,
)
from rwa_calc.engine.stages.classify.permissions import (
    emit_model_permission_diagnostics,
    resolve_model_permissions,
)
from rwa_calc.engine.stages.classify.subtypes import (
    classify_exposure_subtypes,
    derive_exposure_subclass,
    reclassify_corporate_to_retail,
    sync_irb_exposure_class,
)
from rwa_calc.engine.stages.re_split.flagging import (
    flag_property_reclassification_candidates,
)
from rwa_calc.rulebook import RulepackV0

if TYPE_CHECKING:
    import polars as pl

    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.contracts.errors import CalculationError
    from rwa_calc.rulebook.resolve import ResolvedRulepack

logger = logging.getLogger(__name__)


class ExposureClassifier:
    """
    Classify exposures by exposure class and approach.

    Implements ClassifierProtocol for:
    - Mapping counterparty types to exposure classes
    - Checking SME criteria (turnover thresholds)
    - Checking retail criteria (aggregate exposure thresholds)
    - Determining IRB eligibility based on permissions
    - Identifying specialised lending for slotting
    - Splitting exposures by calculation approach

    All operations use Polars LazyFrames for deferred execution.
    The classifier batches expressions into 4 .with_columns() calls
    to keep the query plan shallow (5 nodes instead of 21).
    """

    @cites("CRR Art. 112")
    @cites("CRR Art. 147")
    def classify(
        self,
        data: ResolvedHierarchyBundle,
        config: CalculationConfig,
        *,
        pack: ResolvedRulepack | None = None,
    ) -> ClassifiedExposuresBundle:
        """
        Classify exposures and split by approach.

        Args:
            data: Hierarchy-resolved data from HierarchyResolver
            config: Calculation configuration

        Returns:
            ClassifiedExposuresBundle with exposures split by approach
        """
        resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack

        # Reads top-to-bottom as a recipe; each helper owns one regulatory
        # concept. See the sibling sub-modules for per-step regulatory
        # references.
        exposures = add_counterparty_attributes(
            data.exposures,
            data.counterparty_lookup.counterparties,
        )
        exposures = join_specialised_lending(exposures, data.specialised_lending)

        # Single schema snapshot — used by the remaining schema-conditional
        # helpers (non-contract scratch columns and the EU-sovereign currency
        # probe) without re-scanning the LazyFrame. Contract columns
        # (hierarchy_exit / cp_lookup_* / raw_model_permissions) need no
        # presence gate — sealed inputs always carry them.
        schema_names = set(exposures.collect_schema().names())

        classification_errors = collect_input_warnings(data, config, pack=resolved_pack)

        classified = derive_independent_flags(exposures, config, schema_names, pack=resolved_pack)
        classified = classify_exposure_subtypes(classified, config, pack=resolved_pack)
        classified = reclassify_corporate_to_retail(
            classified, config, schema_names, pack=resolved_pack
        )
        classified = flag_property_reclassification_candidates(
            classified, config, schema_names, pack=resolved_pack
        )
        classified = sync_irb_exposure_class(classified)

        has_model_permissions = data.model_permissions is not None
        if data.model_permissions is not None:
            classified = resolve_model_permissions(classified, data.model_permissions)

        classified = assign_approach(
            classified,
            config,
            schema_names,
            has_model_permissions=has_model_permissions,
            pack=resolved_pack,
        )
        classified = derive_exposure_subclass(classified, config, pack=resolved_pack)

        # Stage-exit edge (producer-side): the diagnostic emits below run
        # against in-memory data instead of re-executing the upstream lazy
        # plan, and CRMProcessor receives an eager-backed frame. Laziness is
        # strictly intra-stage (migration Phase 1).
        classified = materialise_edge(classified, config, "classifier_exit")

        classification_errors.extend(collect_beel_on_non_defaulted_warnings(classified))
        if has_model_permissions:
            classification_errors.extend(emit_model_permission_diagnostics(classified))

        # Producer seal (Phase 3): validates the contract and strips
        # intra-stage scratch (including _model_permission_diagnostic) —
        # pure plan ops over the eager-backed frame. CCR runs carry the
        # SA-CCR provenance columns through, so the contract is selected
        # by the input frame's brand.
        exit_edge = (
            CLASSIFIER_EXIT_CCR_EDGE
            if sealed_edge_of(data.exposures) == "ccr_exit"
            else CLASSIFIER_EXIT_EDGE
        )
        classified = seal(classified, exit_edge)

        return self._build_bundle(classified, data, classification_errors)

    def _build_bundle(
        self,
        classified: pl.LazyFrame,
        data: ResolvedHierarchyBundle,
        classification_errors: list[CalculationError],
    ) -> ClassifiedExposuresBundle:
        """Assemble the classifier's output bundle around the unified frame."""
        classification_audit = build_audit_trail(classified)

        return ClassifiedExposuresBundle(
            all_exposures=classified,
            equity_exposures=data.equity_exposures,
            ciu_holdings=data.ciu_holdings,
            collateral=data.collateral,
            collateral_links=data.collateral_links,
            guarantees=data.guarantees,
            provisions=data.provisions,
            counterparty_lookup=data.counterparty_lookup,
            classification_audit=classification_audit,
            securitisation_audit=data.securitisation_audit,
            classification_errors=classification_errors,
        )
