"""
Acceptance test: the cross-template tie-outs hold on a real end-to-end run.

Runs the full pipeline over the IRB fixture estate (SA + F-IRB + A-IRB +
slotting) for both frameworks, generates the COREP and Pillar 3 template
bundles the same way production does, and asserts
``check_cross_template_consistency`` finds ZERO breaks. This is the ground-truth
gate for the curated ties: if a real run failed a tie we believed valid, the tie
(not the tolerance) is wrong.
"""

from __future__ import annotations

from datetime import date

import pytest
from workbooks.shared.fixture_loader import load_fixtures

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
    results = PipelineOrchestrator().run_with_data(bundle, config).results
    corep = COREPGenerator().generate_from_lazyframe(results, framework=framework)
    pillar3 = Pillar3Generator().generate_from_lazyframe(results, framework=framework)
    return corep, pillar3


@pytest.fixture(scope="module")
def crr_bundles():
    return _run_and_generate("CRR")


@pytest.fixture(scope="module")
def b31_bundles():
    return _run_and_generate("BASEL_3_1")


def test_crr_run_has_no_tieout_findings(crr_bundles):
    corep, pillar3 = crr_bundles
    findings = check_cross_template_consistency(corep, pillar3, "CRR")
    assert findings == [], [str(f) for f in findings]


def test_b31_run_has_no_tieout_findings(b31_bundles):
    corep, pillar3 = b31_bundles
    findings = check_cross_template_consistency(corep, pillar3, "BASEL_3_1")
    assert findings == [], [str(f) for f in findings]


def test_crr_run_exercises_the_irb_and_sa_ties(crr_bundles):
    """Guard: the real run actually POPULATES both SA and IRB sides, so the
    zero-findings assertion above is not vacuously passing on skipped ties."""
    corep, _pillar3 = crr_bundles
    assert corep.c07_00  # SA sheets present
    assert corep.c08_01  # IRB sheets present
    assert corep.c_02_00 is not None
