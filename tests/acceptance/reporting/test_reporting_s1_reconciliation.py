"""
Phase 7 S1 reconciliation regression locks.

Pipeline position:
    build_reporting_bundle -> PipelineOrchestrator -> result.results
        -> COREPGenerator / Pillar3Generator

Key responsibilities:
- Lock the S1 latent-bug fix: the COREP/Pillar 3 generators now read the SEALED
  canonical PD/LGD column names (``pd_floored`` / ``pd`` / ``lgd_floored`` /
  ``lgd_input``) instead of the fictional ``irb_``-prefixed names. Before S1 these
  probes missed and C 08.02 / C 08.03 / C 08.05 + Pillar 3 CR6 / CR9 emitted EMPTY
  from real sealed output. These tests assert those templates are now NON-empty.
- Lock the equity surfacing: the reporting oracle now carries one equity exposure,
  and the aggregator concatenates equity into ``result.results`` before the seal,
  so an ``approach_applied='equity'`` row reaches reporting.
- Document the accept-empty decision: CR9.1 stays empty (gated on an ECAI PD-
  mapping disclosure the engine does not produce — out of S1 scope).

These are production-grounded (real sealed pipeline output), unlike the synthetic
unit estate, so they are the trustworthy oracle for the reconciliation.

References:
- .claude/state/phase7-plan.md: S1 sealed-input reconciliation
- tests/fixtures/reporting_portfolio.py: the oracle portfolio (now incl. equity)
- tests/acceptance/reporting/test_reporting_golden.py: the frozen golden gate
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

import polars as pl
import pytest
from tests.fixtures.reporting_portfolio import build_reporting_bundle

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator, COREPTemplateBundle
from rwa_calc.reporting.pillar3.generator import Pillar3Generator, Pillar3TemplateBundle


def _crr_config() -> CalculationConfig:
    return CalculationConfig.crr(
        reporting_date=date(2025, 12, 31), permission_mode=PermissionMode.IRB
    )


def _b31_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 1),
        permission_mode=PermissionMode.IRB,
        enforce_retail_granularity=False,
    )


# regime key -> (framework string, config factory)
_REGIMES: dict[str, tuple[str, Callable[[], CalculationConfig]]] = {
    "crr": ("CRR", _crr_config),
    "b31": ("BASEL_3_1", _b31_config),
}


def _run(
    regime_key: str,
) -> tuple[pl.DataFrame, COREPTemplateBundle, Pillar3TemplateBundle]:
    """Run the oracle portfolio through one regime; return (results_df, corep, pillar3)."""
    framework, config_factory = _REGIMES[regime_key]
    config = config_factory()
    result = PipelineOrchestrator().run_with_data(build_reporting_bundle(), config)
    results_df = result.results.collect()
    corep = COREPGenerator().generate_from_lazyframe(result.results, framework=framework)
    pillar3 = Pillar3Generator().generate_from_lazyframe(result.results, framework=framework)
    return results_df, corep, pillar3


@pytest.mark.parametrize("regime_key", list(_REGIMES))
@pytest.mark.parametrize("template", ["c08_02", "c08_03", "c08_05"])
def test_irb_pd_templates_populate_from_sealed_output(regime_key: str, template: str) -> None:
    """C 08.02/03/05 populate from real sealed output (S1 PD-probe retarget).

    Arrange: oracle portfolio (has F-IRB + A-IRB exposures) under one regime.
    Act:     run pipeline -> COREP generate.
    Assert:  the IRB PD-keyed template is a non-empty dict (was {} before S1).
    """
    _results, corep, _p3 = _run(regime_key)
    frames = getattr(corep, template)
    assert frames, f"{template} is empty under {regime_key} — PD probe retarget regressed"


@pytest.mark.parametrize("regime_key", list(_REGIMES))
def test_cr6_populates_from_sealed_output(regime_key: str) -> None:
    """Pillar 3 CR6 populates from real sealed output (S1 PD/LGD-probe retarget)."""
    _results, _corep, pillar3 = _run(regime_key)
    assert pillar3.cr6, f"CR6 is empty under {regime_key} — PD/LGD probe retarget regressed"


def test_cr9_populates_under_b31() -> None:
    """Pillar 3 CR9 (B31-only backtesting) populates from real sealed output."""
    _results, _corep, pillar3 = _run("b31")
    assert pillar3.cr9, "CR9 is empty under B31 — PD probe retarget regressed"


@pytest.mark.parametrize("regime_key", list(_REGIMES))
def test_equity_row_reaches_results(regime_key: str) -> None:
    """The oracle equity exposure surfaces in result.results (equity->results wiring)."""
    results_df, _corep, _p3 = _run(regime_key)
    approaches = set(results_df["approach_applied"].to_list())
    assert "equity" in approaches, (
        f"no equity row in result.results under {regime_key} — equity wiring regressed"
    )


@pytest.mark.parametrize("regime_key", list(_REGIMES))
def test_cr9_1_stays_empty_accept_empty_ecai(regime_key: str) -> None:
    """CR9.1 stays empty: gated on ECAI PD-mapping the engine does not produce (accept-empty).

    Documents the recorded S1 accept-empty decision so a future non-empty CR9.1
    (e.g. once an ECAI PD-mapping pipeline lands) flags this assertion for review.
    """
    _results, _corep, pillar3 = _run(regime_key)
    assert not pillar3.cr9_1, (
        f"CR9.1 unexpectedly populated under {regime_key} — revisit the accept-empty ECAI decision"
    )
