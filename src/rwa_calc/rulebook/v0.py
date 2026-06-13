"""
RulepackV0 — the Phase 4 regime facade.

Pipeline position:
    Built once per run by the orchestrator (after the EUR/GBP FX-rate sync
    finalises the effective config) and passed to every registered stage as
    the ``rulepack`` argument of ``Stage(ctx, rulepack, run_config)``.

Key responsibilities:
- Freeze the final stage-signature slot for regulatory variation: stages
  that need regime information take it from the rulepack, never by
  re-deriving it. Phase 5 replaces the internals with a resolved,
  content-hashed rulepack; the attribute surface grows, the signature
  does not change.
- Carry the regime id and the canonical IRB K scaling factor (CRR
  Art. 153(1): 1.06 under CRR; removed under Basel 3.1 / PRA PS1/26) so the
  four engine sites currently reconstructing ``1.06 if config.is_crr else
  1.0`` have a single source to migrate onto.

Deliberately thin in v0: no table accessors are exposed until the slice
that migrates their consumers — speculative surface here would have to be
re-reviewed when Phase 5 swaps the implementation.

References:
- CRR Art. 153(1): IRB risk-weight scaling factor (1.06)
- docs/plans/target-architecture-migration.md (Phase 4 — "Define the final
  signature now"; Phase 5 — rulebook)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from rwa_calc.rulebook.registry import FRAMEWORK_TO_REGIME_ID
from rwa_calc.rulebook.resolve import resolve

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.domain.enums import RegulatoryFramework
    from rwa_calc.rulebook.resolve import ResolvedRulepack


@dataclass(frozen=True)
class RulepackV0:
    """Frozen facade over today's regime configuration.

    Phase 4 scaffolding: ``config`` is a full passthrough because the
    regulatory sub-configs (PD/LGD floors, supporting factors, output
    floor, thresholds, ...) are read throughout the engine. Phase 5 peels
    those into resolved pack entries and shrinks this passthrough away.

    Phase 5 S2: ``__post_init__`` resolves a content-hashed
    :class:`~rwa_calc.rulebook.resolve.ResolvedRulepack` for the run's
    ``(regime, reporting_date)`` and attaches it as :attr:`pack`. Because
    ``RulepackV0`` is built only from the *effective* config (after the
    orchestrator's FX-rate sync), the pack snapshots post-sync state. Stages
    adopt ``pack`` slice by slice; the ``is_crr`` / ``is_basel_3_1`` /
    ``scaling_factor`` facade stays during the strangler.
    """

    regime: RegulatoryFramework
    config: CalculationConfig
    pack: ResolvedRulepack = field(init=False, compare=False, repr=False)
    _pack_override: ResolvedRulepack | None = field(
        default=None, kw_only=True, compare=False, repr=False
    )

    def __post_init__(self) -> None:
        """Resolve and attach the content-hashed pack for this regime/date.

        An explicit ``_pack_override`` (see :meth:`from_resolved`) is attached
        verbatim — for amendment overlays and tests that substitute a custom
        resolved pack — instead of resolving from ``(regime, reporting_date)``.
        """
        if self._pack_override is not None:
            object.__setattr__(self, "pack", self._pack_override)
            return
        regime_id = FRAMEWORK_TO_REGIME_ID[self.config.framework]
        object.__setattr__(self, "pack", resolve(regime_id, self.config.reporting_date))

    @classmethod
    def from_config(cls, config: CalculationConfig) -> RulepackV0:
        """Build the v0 rulepack from a finalised run config.

        The config must be the *effective* one — after the orchestrator's
        EUR/GBP FX-rate sync, which may replace thresholds mid-bootstrap
        under CRR.
        """
        return cls(regime=config.framework, config=config)

    @classmethod
    def from_resolved(cls, config: CalculationConfig, pack: ResolvedRulepack) -> RulepackV0:
        """Build a v0 rulepack around an explicitly resolved (possibly overridden) pack.

        For callers that substitute a custom :class:`ResolvedRulepack` — an
        amendment overlay, or a test overriding a single entry (e.g. a floor
        bundle) — instead of the pack ``from_config`` would resolve from
        ``(regime, reporting_date)``. The rest of the facade (regime, config
        passthrough) is unchanged. Production uses :meth:`from_config`.
        """
        return cls(regime=config.framework, config=config, _pack_override=pack)

    @property
    def is_crr(self) -> bool:
        """True when the regime is CRR (pre-Basel-3.1)."""
        return self.config.is_crr

    @property
    def is_basel_3_1(self) -> bool:
        """True when the regime is Basel 3.1 (PRA PS1/26)."""
        return self.config.is_basel_3_1

    @property
    def scaling_factor(self) -> float:
        """Canonical IRB K scaling factor (CRR Art. 153(1)).

        1.06 under CRR; 1.0 under Basel 3.1. The single source the four
        inline ``1.06 if config.is_crr else 1.0`` reconstructions migrate
        onto (Phase 4 namespace-retirement slice).
        """
        return float(self.config.scaling_factor)
