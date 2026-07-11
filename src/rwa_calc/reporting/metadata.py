"""
Reporting metadata context — the typed side-car for out-of-frame inputs.

Pipeline position:
    resolve(regime, date).reporting() + RunConfig elections -> ReportingContext
        -> {COREPGenerator, Pillar3Generator} (declarative executor, Phase 7 S7+)

Key responsibilities:
- Carry the regime's resolved ``ReportingTemplateSet`` (which templates apply,
  which ``TemplateSpec`` variant to select) so the declarative reporting layer
  is pack-driven instead of testing ``framework == "BASEL_3_1"`` strings.
- Carry the out-of-frame side inputs the templates need beyond the sealed
  aggregator-exit ledger: the portfolio output-floor summary (OF 02.01 / OV1
  floor rows), the prior-period results frame (CR8 / C 08.04 opening-RWEA
  carry-forward), the Pillar 3 capital-ratio overrides (CMS1/KM1-style rows),
  and the firm's reporting-basis / institution-type elections.

"Reporting input = the sealed aggregator exit" is completed by this context:
the ledger carries every per-exposure fact; everything else a template cell
needs travels here, typed — never smuggled as frame columns and never read
from ``api/`` (import direction: reporting sits below api).

References:
- docs/plans/phase7-declarative-reporting.md §3.1/§3.2 (S6)
- PRA PS1/26 Art. 92(2A) (output floor summary); Reg (EU) 2021/451 Annex I
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import polars as pl

    from rwa_calc.contracts.bundles import OutputFloorSummary
    from rwa_calc.contracts.config import Pillar3CapitalRatioOverrides
    from rwa_calc.rulebook.model import ReportingTemplateSet


@dataclass(frozen=True)
class ReportingContext:
    """Typed out-of-frame inputs for one reporting run.

    Attributes:
        template_set: The regime's cited reporting template inventory,
            resolved from the rulepack (``resolve(...).reporting()``).
            ``None`` while the generators remain pack-blind (the S8 strangler
            slices thread the resolved set; the executor itself never needs
            it — variant selection happens at spec-choice time).
        output_floor_summary: Portfolio-level output-floor summary
            (Basel 3.1 only; ``None`` under CRR or when the floor did not run).
        previous_period_results: Prior-run results LazyFrame for flow
            templates (CR8, C 08.04 opening RWEA). ``None`` = no prior period.
        capital_ratio_overrides: Firm-supplied capital ratios for the
            Pillar 3 capital templates. ``None`` = derive/blank per template.
        reporting_basis: Reporting-basis election (consolidated / solo …)
            from the run config; ``None`` when not elected.
        institution_type: Institution-type election from the run config;
            ``None`` when not elected.
        substitution_inflow: The CRM substitution inflow into the sheet's
            exposure class (COREP C 07.00 col 0100 — a cross-sheet number:
            guaranteed portions migrating INTO this class from other
            obligor classes, precomputed over the whole population and
            threaded per sheet execution). ``None`` when not applicable.
    """

    template_set: ReportingTemplateSet | None = None
    output_floor_summary: OutputFloorSummary | None = None
    previous_period_results: pl.LazyFrame | None = None
    capital_ratio_overrides: Pillar3CapitalRatioOverrides | None = None
    reporting_basis: str | None = None
    institution_type: str | None = None
    substitution_inflow: float | None = None

    def side_value(self, key: str) -> float | None:
        """Resolve a named out-of-frame scalar for a ``SideContext`` binding.

        Explicit key registry — a spec naming an unknown key is a programming
        error and raises. ``of_adj`` reads the output-floor summary (None when
        the floor did not run); the six ``*_ratio_pre_floor*`` keys read the
        Pillar 3 capital-ratio overrides (None when not supplied — the OV1
        ratio rows stay null).
        """
        if key == "of_adj":
            return float(self.output_floor_summary.of_adj) if self.output_floor_summary else None
        if key == "substitution_inflow":
            return self.substitution_inflow
        ratio_fields = {
            "cet1_ratio_pre_floor",
            "cet1_ratio_pre_floor_transitional",
            "tier1_ratio_pre_floor",
            "tier1_ratio_pre_floor_transitional",
            "total_ratio_pre_floor",
            "total_ratio_pre_floor_transitional",
        }
        if key in ratio_fields:
            if self.capital_ratio_overrides is None:
                return None
            value = getattr(self.capital_ratio_overrides, key)
            return float(value) if value is not None else None
        raise KeyError(f"unknown ReportingContext side value: {key!r}")
