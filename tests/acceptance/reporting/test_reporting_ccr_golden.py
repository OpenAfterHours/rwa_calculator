"""
Golden gate: the CCR reporting portfolio (SA-CCR derivatives in the templates).

Pipeline position:
    reporting_ccr_portfolio -> PipelineOrchestrator -> COREP + Pillar 3 bundles
        -> frozen goldens (structure-exact + float rtol)

Why this exists: the rich reporting portfolio has NO derivatives, so the whole
CCR template surface (C 34.x) and the C 07.00 counterparty-credit-risk rows had
no oracle at all — the recorded Phase 7 "S8-pre" gap. Without a golden, any fix
to C 07.00's derivative handling would be unprovable.

The goldens were captured BEFORE the C 07.00 fix, against behaviour that was
measurably defective: row 0110 ("Derivatives and Long Settlement Transactions
netting sets") was empty in both regimes, and under Basel 3.1 the derivatives
were dropped from C 07.00 entirely (the output-floor ``standardised_ccr`` relabel
moved them off the ``"standardised"`` population filter). The snapshot was never
a blessing — the fix's diff against it IS the proof.

The two assertions at the foot of this file state the behaviour Annex II
requires (CCR exposures in rows 0090-0130) rather than the behaviour that was
captured, so they hold the fix in place; the full expected-value oracle lives in
``tests/acceptance/reporting/test_c07_ccr_derivative_rows.py``. Regenerate the
goldens with REGEN_REPORTING_GOLDENS=1 only alongside a recorded decision —
never to make a red suite green.

References:
- COREP Annex II, C 07.00 rows 0090-0130; CRR Art. 274(2), Art. 306 (QCCP 2%)
- docs/plans/c07-ccr-derivatives.md
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import polars as pl
import pytest
from tests.acceptance.reporting.test_reporting_golden import (
    _GOLDEN_ROOT,
    _REGEN,
    _capture_frames,
    _flatten_bundle,
    _frame_diffs,
    _read_golden,
)
from tests.fixtures.reporting_ccr_portfolio import build_reporting_ccr_bundle

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator
from rwa_calc.reporting.pillar3.generator import Pillar3Generator

# regime key -> (golden subdir, framework string, config factory)
_REGIMES: dict[str, tuple[str, str]] = {
    "crr": ("ccr_crr", "CRR"),
    "b31": ("ccr_b31", "BASEL_3_1"),
}


def _config(regime_key: str) -> CalculationConfig:
    if regime_key == "crr":
        return CalculationConfig.crr(
            reporting_date=date(2025, 12, 31), permission_mode=PermissionMode.STANDARDISED
        )
    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 1), permission_mode=PermissionMode.STANDARDISED
    )


def _generate_frames(regime_key: str) -> tuple[dict[str, pl.DataFrame], dict]:
    """Run the CCR portfolio through one regime and flatten both bundles."""
    _subdir, framework = _REGIMES[regime_key]
    result = PipelineOrchestrator().run_with_data(build_reporting_ccr_bundle(), _config(regime_key))

    corep = COREPGenerator().generate_from_lazyframe(result.results, framework=framework)
    pillar3 = Pillar3Generator().generate_from_lazyframe(result.results, framework=framework)

    corep_frames, corep_meta = _flatten_bundle("corep", corep)
    p3_frames, p3_meta = _flatten_bundle("pillar3", pillar3)
    return {**corep_frames, **p3_frames}, {"corep": corep_meta, "pillar3": p3_meta}


# =============================================================================
# The golden gate
# =============================================================================


@pytest.mark.parametrize("regime_key", list(_REGIMES))
def test_ccr_reporting_templates_match_golden(regime_key: str) -> None:
    """Generated templates match the frozen CCR goldens (structure + float rtol)."""
    subdir = _REGIMES[regime_key][0]
    golden_dir: Path = _GOLDEN_ROOT / subdir

    if _REGEN:
        _capture_frames(golden_dir, *_generate_frames(regime_key))
        pytest.skip(f"REGEN_REPORTING_GOLDENS=1 — captured CCR goldens for {regime_key!r}")

    manifest_path = golden_dir / "manifest.json"
    assert manifest_path.exists(), (
        f"No CCR reporting goldens for {regime_key!r} at {golden_dir}. Capture them first: "
        "REGEN_REPORTING_GOLDENS=1 uv run pytest "
        "tests/acceptance/reporting/test_reporting_ccr_golden.py"
    )

    manifest = json.loads(manifest_path.read_text())
    frames, meta = _generate_frames(regime_key)

    errors: list[str] = []
    expected_keys, actual_keys = set(manifest["frames"]), set(frames)
    if expected_keys != actual_keys:
        if added := sorted(actual_keys - expected_keys):
            errors.append(f"NEW template frames not in golden: {added}")
        if dropped := sorted(expected_keys - actual_keys):
            errors.append(f"MISSING template frames present in golden: {dropped}")
    if manifest["meta"] != meta:
        errors.append(
            f"bundle metadata changed:\n  expected: {manifest['meta']}\n  actual:   {meta}"
        )
    for key in sorted(expected_keys & actual_keys):
        expected_df = _read_golden(golden_dir / f"{key}.ndjson", manifest["frames"][key])
        errors.extend(_frame_diffs(expected_df, frames[key], key))

    assert not errors, "CCR reporting golden mismatch ({}):\n{}".format(
        regime_key, "\n".join(errors)
    )


# =============================================================================
# The fix, pinned explicitly (so the snapshot is not mistaken for correct)
# =============================================================================


def test_derivatives_reach_the_engine_in_both_regimes() -> None:
    """The portfolio really does produce SA-CCR derivative rows — CRR and B3.1.

    Guards the fixture itself: if this ever goes quiet, the goldens below stop
    testing anything and the C 07.00 defect would look "fixed" by absence.
    """
    for regime_key in _REGIMES:
        result = PipelineOrchestrator().run_with_data(
            build_reporting_ccr_bundle(), _config(regime_key)
        )
        rows = result.results.filter(pl.col("risk_type") == "CCR_DERIVATIVE").collect()
        assert rows.height == 2, regime_key  # one bilateral, one QCCP-cleared
        assert float(rows["rwa_final"].sum()) > 0.0, regime_key


def test_c07_derivative_row_0110_reports_the_derivative_netting_sets() -> None:
    """C 07.00 row 0110 carries the derivative netting sets (was null — the defect).

    Annex II: row 0110 = "Netting sets containing only derivatives listed in
    Annex II CRR and long settlement transactions", and it is the additive parent
    of the QCCP "of which" row 0120. An empty 0110 means the exposure-type
    breakdown does not foot to the total.

    Arrange: the CCR portfolio under CRR (two derivative netting sets).
    Act:     run the pipeline -> COREP C 07.00 institution sheet.
    Assert:  row 0110 reports a positive exposure value and RWEA, and contains
             row 0120.

    Exact figures: tests/acceptance/reporting/test_c07_ccr_derivative_rows.py.
    """
    # Arrange + Act
    frames, _meta = _generate_frames("crr")
    sheet = frames["corep__c07_00__institution"]
    row_0110 = sheet.filter(pl.col("row_ref") == "0110")
    row_0120 = sheet.filter(pl.col("row_ref") == "0120")

    # Assert
    assert row_0110.height == 1
    assert row_0110["0200"][0] is not None, (
        "C 07.00 row 0110 must report the derivative netting sets (Annex II) — "
        "it is null, so section 2 does not foot to the total."
    )
    assert float(row_0110["0220"][0]) > 0.0
    assert float(row_0110["0200"][0]) >= float(row_0120["0200"][0]), (
        "row 0120 is an 'of which' subset of row 0110, not a sibling."
    )


def test_basel31_reports_derivatives_in_c07() -> None:
    """Basel 3.1: the derivatives reach C 07.00 (they were dropped — the defect).

    The ``standardised_ccr`` output-floor relabel moved them off the
    ``"standardised"`` population filter, so C 07.00 understated the SA EAD and
    RWEA. They are readmitted by ``risk_type`` — the label must stay
    ``standardised_ccr`` (it is load-bearing for the output floor). C 34.01 keeps
    reporting them too: C 07.00 and C 34 are not alternatives.

    Arrange: the CCR portfolio under Basel 3.1.
    Act:     run the pipeline -> COREP.
    Assert:  the institution C 07.00 sheet exists and carries RWEA; C 34.01 still
             reports the same book.
    """
    # Arrange + Act
    frames, _meta = _generate_frames("b31")

    # Assert
    c07_sheets = sorted(key for key in frames if key.startswith("corep__c07_00__"))
    assert c07_sheets == ["corep__c07_00__corporate", "corep__c07_00__institution"], (
        "the SA-CCR derivative netting sets must reach C 07.00 under Basel 3.1 "
        f"(sheets produced: {c07_sheets})"
    )
    institution = frames["corep__c07_00__institution"]
    total = institution.filter(pl.col("row_ref") == "0010")
    assert float(total["0220"][0]) > 0.0

    # The RWEA is on the ledger twice by design: C 34.01 reports it as well.
    c34_01 = frames["corep__c34_01"]
    assert float(c34_01["0020"][0]) > 0.0
