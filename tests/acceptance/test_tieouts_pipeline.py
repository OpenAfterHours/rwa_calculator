"""
Acceptance test: the cross-template tie-outs hold on a real end-to-end run.

Runs the full pipeline over the IRB fixture estate (SA + F-IRB + A-IRB +
slotting) for both frameworks, generates the COREP and Pillar 3 template
bundles the same way production does, and asserts
``check_cross_template_consistency`` finds ZERO breaks. This is the ground-truth
gate for the curated ties: if a real run failed a tie we believed valid, the tie
(not the tolerance) is wrong.

One break is a known ENGINE defect, not a tie defect: P1.367 (IMPLEMENTATION_PLAN)
— ``engine/aggregator/_floor.py`` takes the Basel 3.1 output floor over the
modelled subset and re-adds the SA book outside the max, so wherever its floor
binds the engine's total (OV1 row 29, Σ ``rwa_final``) exceeds the PS1/26
Art. 92(2A) TREA that C 02.00 states by up to (1 − x) · SA book. The fix releases
capital and awaits owner sign-off. A second follows from any binding floor:
P3.8 — Pillar 3 OV1 rows 3-5 still sum ``rwa_final``, which carries the engine's
pro-rata floor add-on, while C 08.01 reports the un-floored own-approach RWEA, so
``irb_rwea_c08_01_vs_ov1`` differs by exactly the engine's shortfall (the
module docstring of ``reporting/tieouts.py`` records it). The Basel 3.1 test
therefore admits exactly those two ties, each only by exactly the amount it
derives from the run's own ``OutputFloorSummary``; when the owning item lands
the amount is zero and the tie must hold. The floor binds on this estate since the product-review fixes of
2026-11-18 raised S-TREA (e.g. IV-01's pre-operational default for project
finance with no phase).
"""

from __future__ import annotations

from datetime import date

import pytest
from workbooks.shared.fixture_loader import load_fixtures

from rwa_calc.contracts.bundles import OutputFloorSummary
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator
from rwa_calc.reporting.pillar3.generator import Pillar3Generator
from rwa_calc.reporting.tieouts import check_cross_template_consistency
from tests.acceptance.acceptance_helpers import make_irb_bundle
from tests.fixtures.irb_test_helpers import create_full_irb_model_permissions


def _run_and_generate(framework: str):
    """Run the IRB fixture estate and return (corep_bundle, pillar3_bundle)."""
    bundle = make_irb_bundle(load_fixtures(), create_full_irb_model_permissions())
    if framework == "CRR":
        config = CalculationConfig.crr(
            reporting_date=date(2025, 12, 31), permission_mode=PermissionMode.IRB
        )
    else:
        config = CalculationConfig.basel_3_1(
            reporting_date=date(2027, 1, 1), permission_mode=PermissionMode.IRB
        )
    response = PipelineOrchestrator().run_with_data(bundle, config)
    summary = response.output_floor_summary
    # Thread the run's OutputFloorSummary exactly as production does
    # (api/rest.py get_template_bundles): without it C 02.00 cannot state the
    # Basel 3.1 floor (row 0010 column 0030), so on a run whose floor binds the
    # C 02.00 TREA read the un-floored total while OV1 [29] (Σ rwa_final) carried
    # the add-on — a harness gap, not a template one. The floor binds on this
    # estate since the product-review fixes raised S-TREA (e.g. IV-01 / IV-02).
    corep = COREPGenerator().generate_from_lazyframe(
        response.results,
        framework=framework,
        output_floor_summary=summary,
    )
    pillar3 = Pillar3Generator().generate_from_lazyframe(
        response.results,
        framework=framework,
        output_floor_summary=summary,
    )
    return corep, pillar3, summary


def _p1_367_overstatement(summary: OutputFloorSummary | None) -> float:
    """Engine post-floor total minus the PS1/26 Art. 92(2A) TREA (P1.367).

    The engine floors the modelled subset — ``book + max(U_m, x·S_m + adj)`` —
    where the article floors the whole book — ``max(U_m + book, x·(S_m + book) +
    adj)``; ``book`` is the SA and equity RWA the engine re-adds outside the max.
    Zero where no floor applies (CRR) or the two agree.
    """
    if summary is None:
        return 0.0
    book = summary.sa_rwa_total + summary.equity_rwa_total
    article = max(
        summary.u_trea + book,
        summary.floor_pct * (summary.s_trea + book) + summary.of_adj,
    )
    return summary.total_rwa_post_floor - article


def _amount(text: str | None) -> float:
    return float((text or "0").replace(",", ""))


@pytest.fixture(scope="module")
def crr_bundles():
    return _run_and_generate("CRR")


@pytest.fixture(scope="module")
def b31_bundles():
    return _run_and_generate("BASEL_3_1")


def test_crr_run_has_no_tieout_findings(crr_bundles):
    corep, pillar3, _summary = crr_bundles
    findings = check_cross_template_consistency(corep, pillar3, "CRR")
    assert findings == [], [str(f) for f in findings]


def test_b31_run_has_no_tieout_findings(b31_bundles):
    """Every tie holds, bar two known engine / Pillar 3 gaps by exactly their amounts."""
    corep, pillar3, summary = b31_bundles
    findings = check_cross_template_consistency(corep, pillar3, "BASEL_3_1")
    known = {
        # P1.367: the engine floors the modelled subset (Art. 92(2A) floors the book).
        "total_rwea_c02_vs_ov1": _p1_367_overstatement(summary),
        # P3.8: OV1 rows 3-5 sum rwa_final, which carries the floor add-on.
        "irb_rwea_c08_01_vs_ov1": summary.shortfall if summary is not None else 0.0,
    }
    others = [f for f in findings if f.field_name not in known]
    assert others == [], [str(f) for f in others]

    for tie, amount in known.items():
        breaks = [f for f in findings if f.field_name == tie]
        if amount < 1.0:
            assert breaks == [], [str(f) for f in breaks]
            continue
        assert len(breaks) == 1, [str(f) for f in breaks]
        gap = abs(_amount(breaks[0].expected_value) - _amount(breaks[0].actual_value))
        assert gap == pytest.approx(amount, abs=0.01), tie


def test_crr_run_exercises_the_irb_and_sa_ties(crr_bundles):
    """Guard: the real run actually POPULATES both SA and IRB sides, so the
    zero-findings assertion above is not vacuously passing on skipped ties."""
    corep, _pillar3, _summary = crr_bundles
    assert corep.c07_00  # SA sheets present
    assert corep.c08_01  # IRB sheets present
    assert corep.c_02_00 is not None
