"""
Golden gate: the IRB class-and-PD-band portfolio (the C 08.xx sheet and row axes).

Pipeline position:
    reporting_irb_classes_portfolio -> PipelineOrchestrator -> COREP + Pillar 3
        -> frozen goldens (structure-exact + float rtol)

Why this exists: the rich portfolio's IRB book is three exposures, so the C 08.xx
family emitted only the ``corporate`` and ``retail_other`` sheets and one PD band
each on C 08.03 / C 08.05. Every published rule scoped to the IRB
central-government, institution, retail-mortgage or QRRE sheet was
NOT_EVALUATED, and so was every PD-range sum-check — those are PARENT/CHILD
identities within one sheet (``{r0070} = {r0080} + {r0090}``), so they need the
whole band group populated on the same class, which a sparse ladder never is.

The assertions below the golden gate are the part that does not move: the sheet
each row lands on, the approach it resolves to per regime, and the PD-band row
groups the sum-checks address. If those go quiet the goldens keep passing while
the coverage they were built to create quietly disappears.

This portfolio surfaced the C 08.03 / C 08.05 row-taxonomy break: the published
rows are NESTED (parent band + child bands, e.g. Basel 3.1 ``r0010`` is the sum
of ``r0015``, ``r0025`` and ``r0030``) while this estate models 17 FLAT bands
with no 0015 / 0025 at all. So ``v09753_m``-``v09760_m`` and
``boe_b0768``-``boe_b0776`` now execute and FAIL rather than silently not
running, and ``boe_b0767`` / ``boe_b0773`` remain structurally unevaluable. That
is the portfolio doing its job — the failures are recorded in
``validation_known_breaks.json``, not tuned away here.

Regenerate with REGEN_REPORTING_GOLDENS=1 only alongside a recorded decision —
never to make a red suite green.

References:
- CRR Art. 147(2)-(5) / PS1/26 Art. 147: IRB exposure classes
- CRR Art. 160(1): the 0.03% PD floor, scoped to corporates and institutions
- PS1/26 Art. 147A(1)(a): the Basel 3.1 Standardised-only sovereign class
- COREP Annex II, C 08.03 / C 08.05: the PD-range row breakdowns
- tests/fixtures/reporting_irb_classes_portfolio.py: the oracle portfolio
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
from tests.fixtures.reporting_irb_classes_portfolio import (
    CORP_MASTERSCALE,
    IRB_CLASS_EXPECTED_APPROACH,
    IRB_CLASS_EXPECTED_SHEET_B31,
    IRB_CLASS_EXPECTED_SHEET_CRR,
    build_reporting_irb_classes_bundle,
)

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator, COREPTemplateBundle
from rwa_calc.reporting.pillar3.generator import Pillar3Generator

# regime key -> (golden subdir, framework string)
_REGIMES: dict[str, tuple[str, str]] = {
    "crr": ("irb_classes_crr", "CRR"),
    "b31": ("irb_classes_b31", "BASEL_3_1"),
}

_EXPECTED_SHEETS: dict[str, dict[str, str]] = {
    "crr": IRB_CLASS_EXPECTED_SHEET_CRR,
    "b31": IRB_CLASS_EXPECTED_SHEET_B31,
}

#: Index into ``IRB_CLASS_EXPECTED_APPROACH``'s (CRR, Basel 3.1) pairs.
_APPROACH_INDEX: dict[str, int] = {"crr": 0, "b31": 1}

#: The C 08.03 / C 08.05 band groups the published parent/child sum-checks
#: address, and which therefore have to be populated TOGETHER on one sheet for
#: the rule to reach a verdict at all. Keyed by the parent row.
#: ``v09754_m`` {r0070}={r0080}+{r0090}; ``v09755_m`` {r0100}={r0110}+{r0120};
#: ``v09756_m`` {r0130}={r0140}+{r0150}+{r0160}.
_BAND_GROUPS: dict[str, tuple[str, ...]] = {
    "0070": ("0080", "0090"),
    "0100": ("0110", "0120"),
    "0130": ("0140", "0150", "0160"),
}


def _config(regime_key: str) -> CalculationConfig:
    if regime_key == "crr":
        return CalculationConfig.crr(
            reporting_date=date(2025, 12, 31), permission_mode=PermissionMode.IRB
        )
    # enforce_retail_granularity=False, as the rich portfolio does: the 0.2%-of-
    # portfolio granularity limb is unsatisfiable for a compact oracle, and
    # without the suppression every natural-person row reclassifies to corporate
    # and the retail-mortgage / QRRE sheets vanish.
    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 1),
        permission_mode=PermissionMode.IRB,
        enforce_retail_granularity=False,
    )


def _run(regime_key: str) -> tuple[pl.DataFrame, COREPTemplateBundle]:
    """Run the portfolio through one regime; return the results and COREP bundle."""
    framework = _REGIMES[regime_key][1]
    result = PipelineOrchestrator().run_with_data(
        build_reporting_irb_classes_bundle(), _config(regime_key)
    )
    corep = COREPGenerator().generate_from_lazyframe(result.results, framework=framework)
    return result.results.collect(), corep


def _generate_frames(regime_key: str) -> tuple[dict[str, pl.DataFrame], dict]:
    """Run the portfolio through one regime, flatten both template bundles."""
    framework = _REGIMES[regime_key][1]
    result = PipelineOrchestrator().run_with_data(
        build_reporting_irb_classes_bundle(), _config(regime_key)
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
def test_irb_classes_reporting_templates_match_golden(regime_key: str) -> None:
    """Generated templates match the frozen goldens (structure + float rtol).

    Arrange: the IRB class-and-PD-band portfolio + regime config.
    Act:     run pipeline -> generate both bundles -> flatten to per-template frames.
    Assert:  every golden frame is reproduced, the frame set matches exactly, and
             the None/scalar metadata matches.
    """
    subdir = _REGIMES[regime_key][0]
    golden_dir: Path = _GOLDEN_ROOT / subdir

    if _REGEN:
        _capture_frames(golden_dir, *_generate_frames(regime_key))
        pytest.skip(f"REGEN_REPORTING_GOLDENS=1 — captured IRB-class goldens for {regime_key!r}")

    manifest_path = golden_dir / "manifest.json"
    assert manifest_path.exists(), (
        f"No IRB-class reporting goldens for {regime_key!r} at {golden_dir}. Capture them first: "
        "REGEN_REPORTING_GOLDENS=1 uv run pytest "
        "tests/acceptance/reporting/test_reporting_irb_classes_golden.py"
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

    assert not errors, "IRB-class reporting golden mismatch ({}):\n{}".format(
        regime_key, "\n".join(errors)
    )


# =============================================================================
# What does not move: the fixture's own contract
# =============================================================================


@pytest.mark.parametrize("regime_key", list(_REGIMES))
def test_every_irb_exposure_class_sheet_is_emitted(regime_key: str) -> None:
    """Every IRB row reaches the C 08.xx sheet its Art. 147 class names.

    Guards the fixture itself. This portfolio's whole purpose is the sheet
    (z-axis) coverage; if a row stopped reaching its class the goldens would
    still pass while the rules scoped to that sheet returned NOT_EVALUATED,
    which is indistinguishable from a pass.

    Arrange: the IRB portfolio under one regime.
    Act:     run the pipeline and generate the COREP bundle.
    Assert:  every intended sheet key is present on C 08.01 / C 08.03 / C 08.05.
    """
    # Arrange / Act
    _results, corep = _run(regime_key)

    # Assert
    expected_sheets = set(_EXPECTED_SHEETS[regime_key].values())
    for template, sheets in (
        ("C 08.01", corep.c08_01),
        ("C 08.03", corep.c08_03),
        ("C 08.05", corep.c08_05),
    ):
        missing = sorted(expected_sheets - set(sheets))
        assert not missing, (
            f"{regime_key}: {template} is missing sheet(s) {missing} — the published "
            "rules scoped to them will report NOT_EVALUATED, not a break"
        )


@pytest.mark.parametrize("regime_key", list(_REGIMES))
def test_every_row_resolves_its_intended_approach(regime_key: str) -> None:
    """Each row routes F-IRB / A-IRB / SA as its class and inputs require.

    The sovereign trio is the regime signal: PS1/26 Art. 147A(1)(a) read with
    Art. 147(3) makes the class Standardised-only, so those rows leave the IRB
    book entirely under Basel 3.1. That is the change itself, not a tolerance.

    Arrange: the IRB portfolio under one regime.
    Act:     run the pipeline.
    Assert:  the sealed approach on each row matches the recorded expectation.
    """
    # Arrange / Act
    results, _corep = _run(regime_key)
    index = _APPROACH_INDEX[regime_key]

    # Assert
    actual = dict(
        results.select("exposure_reference", "reporting_approach_origin").iter_rows()  # type: ignore[arg-type]
    )
    expected = {ref: pair[index] for ref, pair in IRB_CLASS_EXPECTED_APPROACH.items()}
    assert actual == expected, f"{regime_key}: approach routing changed"


@pytest.mark.parametrize("regime_key", list(_REGIMES))
def test_the_pd_band_sum_check_groups_are_populated_together(regime_key: str) -> None:
    """Each parent band and all of its child bands land on ONE C 08.03 sheet.

    This is the property the masterscale exists to create. The published PD-range
    checks are parent/child sums within a single class sheet, and the evaluator
    skips a coordinate whose referenced row is absent — so a group that is only
    partly populated leaves its rule NOT_EVALUATED however many exposures the
    portfolio has. Asserting the groups, not just "some rows exist", is what
    keeps this portfolio's coverage from decaying silently.

    Arrange: the IRB portfolio under one regime.
    Act:     read the emitted C 08.03 row refs per sheet.
    Assert:  some sheet carries each parent band together with every child band.
    """
    # Arrange / Act
    _results, corep = _run(regime_key)
    rows_by_sheet = {
        sheet: set(frame["row_ref"].to_list())
        for sheet, frame in corep.c08_03.items()  # type: ignore[attr-defined]
    }

    # Assert
    for parent, children in _BAND_GROUPS.items():
        group = {parent, *children}
        assert any(group <= rows for rows in rows_by_sheet.values()), (
            f"{regime_key}: no C 08.03 sheet carries the whole band group {sorted(group)} — "
            "the parent/child sum-check written over it cannot be evaluated. "
            f"Emitted: { {k: sorted(v) for k, v in rows_by_sheet.items()} }"
        )


def test_the_masterscale_grades_are_distinct_and_ordered() -> None:
    """The masterscale is a monotonic ladder of distinct PDs.

    A duplicated or out-of-order grade would collapse two bands into one and
    silently break a band group above, which the group assertion would then
    report as an estate defect rather than a fixture one.

    Arrange: the recorded masterscale.
    Act:     read the PDs in declaration order.
    Assert:  they strictly increase, and the grade labels are unique.
    """
    # Arrange / Act
    grades = [grade for grade, _pd in CORP_MASTERSCALE]
    pds = [pd_value for _grade, pd_value in CORP_MASTERSCALE]

    # Assert
    assert len(set(grades)) == len(grades), "duplicate masterscale grade label"
    assert pds == sorted(pds) and len(set(pds)) == len(pds), (
        "the masterscale PDs must strictly increase — two grades in one band "
        "would empty a band the published sum-checks reference"
    )
