"""
SA-CCR / SFT stage findings: the CCR024-CCR026 plans of one run.

Pipeline position:
    ccr_sa_ccr / sft_fccm stages -> [derivative_findings / sft_findings] ->
    contracts/ccr_collateral_checks.collect_findings -> STAGE_ERRORS

Key responsibilities:
- Assemble, from the same engine/ccr expressions that price the netting sets,
  the lazy plans of the inputs priced with a visible treatment: CCR collateral
  left out of VM / NICA (CCR024), conflicting CSA terms (CCR025) and amounts
  — including an FX trade's second payment leg — with no spot rate to the
  reporting currency (CCR026).
- Hand each plan to its decoder in ``contracts/ccr_collateral_checks.py``; the
  collect happens there, once per stage (``collect_findings``).

References:
- CCR (CRR) Part Art. 274(1), 275(2), 276(1)(a)/(b), 279b(3); CRR Art. 197,
  Art. 223(5), Art. 285.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from rwa_calc.contracts.ccr_collateral_checks import (
    FindingsPlan,
    ccr_collateral_errors,
    fx_leg_currency_errors,
    margin_term_conflict_errors,
    reporting_currency_errors,
)
from rwa_calc.engine.ccr.collateral import ccr_collateral_findings
from rwa_calc.engine.ccr.margin_terms import margin_term_conflicts
from rwa_calc.engine.ccr.reporting_currency import (
    fx_leg_currency_findings,
    reporting_currency_findings,
    reporting_currency_rates,
)

if TYPE_CHECKING:
    import polars as pl

    from rwa_calc.contracts.bundles import RawCCRBundle, RawSFTBundle
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.rulebook.resolve import ResolvedRulepack

logger = logging.getLogger(__name__)


def derivative_findings(
    stated: RawCCRBundle,
    gated: RawCCRBundle,
    fx_rates: pl.LazyFrame | None,
    run_config: CalculationConfig,
    pack: ResolvedRulepack,
) -> list[FindingsPlan]:
    """The CCR024 / CCR025 / CCR026 plans of the derivatives book.

    CCR026 has two plans: every trade's and collateral item's ``currency``, and
    the second payment leg (``currency_leg2``) of an FX trade, which the
    Art. 279b(1)(b) branch converts itself (P1.406).

    Args:
        stated: The derivatives bundle as input (before the enforceability gate).
        gated: The bundle after the enforceability / WWR gates — the netting
            sets and re-keyed collateral the adapter prices.
        fx_rates: The run's FX rates.
        run_config: The run configuration (reporting currency, FX switch,
            haircut table).
        pack: The run's resolved rulepack.

    Returns:
        ``(plan, decoder)`` pairs for ``collect_findings``.
    """
    collateral = gated.ccr_collateral.ccr_collateral
    rates = reporting_rates(fx_rates, run_config)
    return [
        (
            margin_term_conflicts(
                stated.netting_sets.netting_sets, stated.margin_agreements.margin_agreements
            ),
            margin_term_conflict_errors,
        ),
        (
            ccr_collateral_findings(
                collateral,
                gated.netting_sets.netting_sets,
                stated.netting_sets.netting_sets.select("netting_set_id"),
                run_config,
                pack,
            ),
            ccr_collateral_errors,
        ),
        (
            reporting_currency_findings(
                {
                    "ccr.trades|trade_id": gated.trades.trades,
                    "ccr.ccr_collateral|ccr_collateral_reference": collateral,
                },
                rates,
            ),
            reporting_currency_errors,
        ),
        (fx_leg_currency_findings(gated.trades.trades, rates), fx_leg_currency_errors),
    ]


def sft_findings(
    sft: RawSFTBundle,
    fx_rates: pl.LazyFrame | None,
    run_config: CalculationConfig,
) -> list[FindingsPlan]:
    """The CCR026 plan of the SFT book (trades and collateral).

    Args:
        sft: The SFT bundle.
        fx_rates: The run's FX rates.
        run_config: The run configuration.

    Returns:
        ``(plan, decoder)`` pairs for ``collect_findings``.
    """
    frames = {
        "sft.trades|trade_id": sft.trades.sft_trades,
        "sft.collateral|sft_collateral_reference": (
            sft.collateral.sft_collateral if sft.collateral is not None else None
        ),
    }
    return [
        (
            reporting_currency_findings(frames, reporting_rates(fx_rates, run_config)),
            reporting_currency_errors,
        )
    ]


def reporting_rates(
    fx_rates: pl.LazyFrame | None,
    run_config: CalculationConfig,
) -> pl.LazyFrame | None:
    """The run's spot rates to the reporting currency, or None when FX conversion is off.

    Args:
        fx_rates: The run's FX rates.
        run_config: The run configuration (``apply_fx_conversion``,
            ``base_currency``).

    Returns:
        ``reporting_currency_rates`` output, or None.
    """
    if not run_config.apply_fx_conversion:
        return None
    return reporting_currency_rates(fx_rates, run_config.base_currency)
