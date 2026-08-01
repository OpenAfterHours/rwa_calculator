"""
Golden gate: the SA quasi-sovereign portfolio (the C 07.00 / OF 07.00 sheet axis).

Pipeline position:
    reporting_sa_classes_portfolio -> PipelineOrchestrator -> COREP + Pillar 3
        -> frozen goldens (structure-exact + float rtol)

Why this exists: C 07.00 is published per obligor class, and a rule scoped to a
sheet we never emit is not evaluated at all. Across the three pre-existing
reporting portfolios the estate emitted six of the sixteen Art. 112(1) sheet
codes, so every published rule written over the regional-government, public
sector entity, multilateral-development-bank, international-organisation and
covered-bond sheets had no coordinate to run at — 47 of them under CRR and
Basel 3.1 combined, silently NOT_EVALUATED rather than failing.

The assertions below the golden gate are the part that does not move: each row
reaches its intended sheet, and each resolves the risk weight its article
prescribes — including the one row (``LN_MDB_RATED``) whose weight legitimately
differs between the regimes. If those go quiet the goldens keep passing while
the sheets they were built to cover quietly empty out.

Regenerate with REGEN_REPORTING_GOLDENS=1 only alongside a recorded decision —
never to make a red suite green.

References:
- CRR Art. 115 (RGLA), 116 (PSE), 117 (MDB), 118 (international organisations),
  Art. 129(4) (covered bonds); PRA PS1/26 counterparts
- COREP Annex II, C 07.00: the Art. 112(1)(a)-(q) sheet (z-axis) breakdown
- tests/fixtures/reporting_sa_classes_portfolio.py: the oracle portfolio
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
from tests.fixtures.reporting_sa_classes_portfolio import (
    SA_CLASS_EXPECTED_RW,
    SA_CLASS_EXPECTED_SHEET,
    build_reporting_sa_classes_bundle,
)

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator
from rwa_calc.reporting.pillar3.generator import Pillar3Generator

# regime key -> (golden subdir, framework string)
_REGIMES: dict[str, tuple[str, str]] = {
    "crr": ("sa_classes_crr", "CRR"),
    "b31": ("sa_classes_b31", "BASEL_3_1"),
}

#: Index into ``SA_CLASS_EXPECTED_RW``'s (CRR, Basel 3.1) pairs.
_RW_INDEX: dict[str, int] = {"crr": 0, "b31": 1}

#: Risk weights are exact table lookups, not computed quantities — a mismatch
#: here is a wrong table entry, never float drift.
_RW_TOLERANCE = 1e-12


def _config(regime_key: str) -> CalculationConfig:
    # STANDARDISED on purpose: C 07.00 is the SA template, and every obligor in
    # this portfolio carries an external rating or none, so the permission mode
    # only has to not offer IRB a way in.
    if regime_key == "crr":
        return CalculationConfig.crr(
            reporting_date=date(2025, 12, 31), permission_mode=PermissionMode.STANDARDISED
        )
    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 1), permission_mode=PermissionMode.STANDARDISED
    )


def _run(regime_key: str) -> pl.DataFrame:
    """Run the portfolio through one regime and collect the sealed results."""
    result = PipelineOrchestrator().run_with_data(
        build_reporting_sa_classes_bundle(), _config(regime_key)
    )
    return result.results.collect()


def _generate_frames(regime_key: str) -> tuple[dict[str, pl.DataFrame], dict]:
    """Run the portfolio through one regime, flatten both template bundles."""
    _subdir, framework = _REGIMES[regime_key]
    result = PipelineOrchestrator().run_with_data(
        build_reporting_sa_classes_bundle(), _config(regime_key)
    )

    corep = COREPGenerator().generate_from_lazyframe(result.results, framework=framework)
    pillar3 = Pillar3Generator().generate_from_lazyframe(result.results, framework=framework)

    corep_frames, corep_meta = _flatten_bundle("corep", corep)
    p3_frames, p3_meta = _flatten_bundle("pillar3", pillar3)
    return {**corep_frames, **p3_frames}, {"corep": corep_meta, "pillar3": p3_meta}


# =============================================================================
# The golden gate
# =============================================================================


@pytest.mark.parametrize("regime_key", list(_REGIMES))
def test_sa_classes_reporting_templates_match_golden(regime_key: str) -> None:
    """Generated templates match the frozen goldens (structure + float rtol).

    Arrange: the SA quasi-sovereign portfolio + regime config.
    Act:     run pipeline -> generate both bundles -> flatten to per-template frames.
    Assert:  every golden frame is reproduced, the frame set matches exactly, and
             the None/scalar metadata matches.
    """
    subdir = _REGIMES[regime_key][0]
    golden_dir: Path = _GOLDEN_ROOT / subdir

    if _REGEN:
        _capture_frames(golden_dir, *_generate_frames(regime_key))
        pytest.skip(f"REGEN_REPORTING_GOLDENS=1 — captured SA-class goldens for {regime_key!r}")

    manifest_path = golden_dir / "manifest.json"
    assert manifest_path.exists(), (
        f"No SA-class reporting goldens for {regime_key!r} at {golden_dir}. Capture them first: "
        "REGEN_REPORTING_GOLDENS=1 uv run pytest "
        "tests/acceptance/reporting/test_reporting_sa_classes_golden.py"
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

    assert not errors, "SA-class reporting golden mismatch ({}):\n{}".format(
        regime_key, "\n".join(errors)
    )


# =============================================================================
# What does not move: the fixture's own contract
# =============================================================================


@pytest.mark.parametrize("regime_key", list(_REGIMES))
def test_every_sa_exposure_class_sheet_is_emitted(regime_key: str) -> None:
    """Every row reaches the C 07.00 sheet its exposure class names.

    Guards the fixture itself. The whole point of this portfolio is the sheet
    (z-axis) coverage; if a row stopped reaching its class the goldens would
    still pass while the published rules written over that sheet went back to
    NOT_EVALUATED — the fail-open shape this portfolio exists to close.

    Arrange: the SA quasi-sovereign portfolio under one regime.
    Act:     run the pipeline and generate the COREP bundle.
    Assert:  every intended sheet key is present, and each exposure carries the
             sealed reporting class that puts it there.
    """
    # Arrange / Act
    framework = _REGIMES[regime_key][1]
    result = PipelineOrchestrator().run_with_data(
        build_reporting_sa_classes_bundle(), _config(regime_key)
    )
    results = result.results.collect()
    corep = COREPGenerator().generate_from_lazyframe(result.results, framework=framework)

    # Assert — the sealed class on each row...
    actual = dict(
        results.select("exposure_reference", "reporting_class_origin").iter_rows()  # type: ignore[arg-type]
    )
    assert actual == SA_CLASS_EXPECTED_SHEET, (
        f"{regime_key}: exposures no longer classify onto their intended C 07.00 sheets"
    )

    # ...and the sheet the generator actually emitted for it.
    expected_sheets = set(SA_CLASS_EXPECTED_SHEET.values())
    assert expected_sheets <= set(corep.c07_00), (
        f"{regime_key}: C 07.00 is missing sheet(s) "
        f"{sorted(expected_sheets - set(corep.c07_00))} — the rules scoped to them "
        "will report NOT_EVALUATED, which is indistinguishable from a pass"
    )


@pytest.mark.parametrize("regime_key", list(_REGIMES))
def test_every_quasi_sovereign_row_takes_its_article_risk_weight(regime_key: str) -> None:
    """Each class resolves the risk weight its article prescribes, per regime.

    The MDB row is the one that moves: CRR Art. 117(1) sends an unlisted MDB to
    the Art. 120 institution table (CQS 2 -> 50%) while PS1/26 gives MDBs their
    own ECRA schedule (CQS 2 -> 30%). Pinning both arms is what stops a
    regression that collapsed the class onto the institution ladder from being
    invisible.

    Arrange: the portfolio under one regime.
    Act:     run the pipeline.
    Assert:  rwa_final / ead_final equals the article's weight for every row.
    """
    # Arrange / Act
    results = _run(regime_key)
    index = _RW_INDEX[regime_key]

    # Assert
    weights = {
        ref: rwa / ead
        for ref, ead, rwa in results.select(
            "exposure_reference", "ead_final", "rwa_final"
        ).iter_rows()  # type: ignore[arg-type]
        if ref in SA_CLASS_EXPECTED_RW
    }
    wrong = {
        ref: (actual, SA_CLASS_EXPECTED_RW[ref][index])
        for ref, actual in weights.items()
        if abs(actual - SA_CLASS_EXPECTED_RW[ref][index]) > _RW_TOLERANCE
    }
    assert not wrong, (
        f"{regime_key}: risk weight(s) do not match the article (actual, expected): {wrong}"
    )


def test_the_mdb_risk_weight_is_the_one_that_moves_between_regimes() -> None:
    """The regime pair is load-bearing, not two copies of the same assertion.

    If a future change made the two regimes agree on every row, this portfolio
    would still pass both golden gates while having lost the only cross-regime
    signal it carries. Asserting the divergence exists keeps that honest.

    Arrange: the recorded per-regime expectations.
    Act:     find the rows whose weight differs between the regimes.
    Assert:  it is exactly the rated-MDB row.
    """
    # Arrange / Act
    divergent = {ref for ref, (crr, b31) in SA_CLASS_EXPECTED_RW.items() if crr != b31}

    # Assert
    assert divergent == {"SAC-LN-MDB-RATED"}, (
        "the CRR / Basel 3.1 divergence this portfolio pins has changed shape: "
        f"expected only the rated-MDB row to move, got {sorted(divergent)}"
    )
