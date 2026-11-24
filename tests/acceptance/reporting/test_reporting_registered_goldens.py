"""
Golden gate for every registered reporting run that no portfolio-specific module owns.

Pipeline position:
    RUNS (test_supervisory_validations.py) -> each run's own builder, config and
        prior-period config -> PipelineOrchestrator -> COREP + Pillar 3 bundles
        -> frozen goldens (structure-exact + float rtol), one directory per run

Why this exists (plan item P5.48). The supervisory register and the two
coverage ratchets are all UNIONS over the runs of ``RUNS``: a rule is vacuous
only if no run gets a real verdict out of it, and a cell is live if any run
populates it. So two kinds of change were invisible on a registered portfolio
that had no golden:

- a change in VALUE, not emptiness, to any cell the portfolio's focused
  acceptance test does not pin — no ratchet freezes values;
- a cell live on two or more runs emptied on just ONE of them — the census, the
  ``cells_live`` ratchet and register legs (f)/(g) all stay green while another
  run keeps the cell (or the rule) alive.

Only six portfolios had goldens (rich, off-bs, ccr, sa-classes, irb-classes,
netting — twelve directories). Ten portfolios, nineteen runs, had none:
crm-substitution, re-split, art199, irb-shapes, netting-mismatch,
over-collateralised, facility-share-binding, facility-share-nonbinding and
row-scope in both regimes, plus equity-transitional under Basel 3.1. Their
focused tests are strong on the columns each fixture was built for and silent on
the rest of the portfolio's COREP + Pillar 3 surface.

What this module freezes, and why from ``RUNS`` itself:
    Every run is generated from the ``GateInput``'s OWN ``build_bundle``,
    ``build_config`` and ``build_prior_config`` — the ``functools.partial``
    date-bound builders and facility-share's own config helpers included — so
    each golden freezes the pipeline result the register evaluates. A cloned
    config would freeze a different one (LESSONS B5, third form: registered,
    wrong config, dead cell).

    Both generators then get the two side inputs the REST layer passes them
    (``api/rest.py::get_template_bundles``, and ``_export_pillar3`` for the
    Pillar 3 downloads): the prior-period frame (where the run has one) and the
    run's own output-floor summary. Without the first, C 08.04's and CR8's flow
    rows are null by construction; without the second, Basel 3.1 OV1 row 27
    ("Output floor adjustment") is.

    The Python API does NOT give Pillar 3 the run's summary.
    ``ResultExporter.export_to_pillar3`` and ``export_pillar3_facts`` forward only
    a caller-supplied one (default ``None``), ``CalculationResponse.to_pillar3()``
    supplies none, and ``validate_submission`` hands its Pillar 3 bundle only the
    caller's (its COREP bundle falls back to the run's own). So on those paths
    OV1 row 27 is null in production, as is the Pillar 3 that
    ``validate_submission`` checks by default. These goldens follow REST, so they
    freeze a figure the Python API paths leave null. That gap is owed work, not
    a property of this module.

    The register and ``scripts/coverage_report.py`` withhold BOTH side inputs
    from Pillar 3, and the cell census withholds the summary, so the golden's
    Pillar 3 frames are a SUPERSET of the estate the register evaluates. CR8's
    flow rows are populated here and in the census but reach no register rule.
    OV1 row 27 is populated in no other gate over a registered run: only unit
    tests with a synthetic summary reach it
    (``tests/unit/reporting/pillar3/test_p2_29_ov1_equity_subapproach.py``,
    ``tests/unit/api/test_export.py``).

    The ownership rule is computed from ``RUNS``, not listed: a run whose
    portfolio is not in ``_LEGACY_GOLDEN_DIRS`` belongs to this module. So the
    next portfolio registered in ``RUNS`` lands here automatically, and
    ``test_every_registered_run_has_a_golden`` stays red until its golden is
    banked — a registered run can no longer skip one.

The two side-input parity limbs, and what is OWED:
    The legacy goldens of ``rich`` and ``irb-classes`` (four runs) were captured
    without the prior frame ``RUNS`` gives them, so their C 08.04 rows 0010-0080
    and CR8 rows 1-8 are frozen as null while the register evaluates C 08.04
    populated. Every legacy module also generates Pillar 3 without the
    output-floor summary, so all six legacy Basel 3.1 goldens freeze OV1 row 27
    as null. Re-capturing them moves existing golden directories, which needs a
    recorded preserve-or-fix decision (LESSONS E1), so it is NOT done here: the
    runs are listed in ``_PRIOR_FRAME_OWED`` and ``_FLOOR_SUMMARY_OWED``, and
    each limb holds its list two-way — every other run in scope must freeze a
    non-null figure, and an owed run that starts freezing one must leave the
    list. Until then a value change in those owed cells reaches no golden.

Regenerating:
    ``REGEN_REGISTERED_GOLDENS`` takes a comma-separated selection, never "all":
    ``regime/portfolio`` keys (``crr/re-split,b31/re-split``) rewrite those
    runs' directories only, and ``missing`` captures the runs that have no golden
    yet. Each run owns its own directory, so ``_capture_frames``'
    delete-and-rewrite of ``*.ndjson`` can never touch another run's frames
    (LESSONS E1). ``REGEN_REPORTING_GOLDENS`` does not reach this module. A moved
    cell in an existing golden needs a recorded preserve-or-fix decision — never
    regenerate to make a red gate green. These goldens bank the runs' CURRENT
    figures, including those the register records as gateway breaks, so a later
    fix on any of these portfolios will move a golden here and owes that record.

References:
- tests/acceptance/reporting/test_supervisory_validations.py: ``RUNS``, the
  register, and its "Where the single-portfolio case actually goes" paragraph
- tests/acceptance/reporting/test_reporting_golden.py: the comparison machinery
- COREP Annex II §3.3.6.1 ¶79 (CRR) / PS1/26 Annex II: C 08.04 flows against the
  prior reference date
- src/rwa_calc/reporting/pillar3/ov1.py::generate_ov1: OV1 row 27 takes the
  output-floor adjustment from the external summary, null without it
- .claude/LESSONS.md B5 (registration and config), E1 (surgical regeneration)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

import polars as pl
import pytest
from tests.acceptance.reporting.test_reporting_golden import (
    _GOLDEN_ROOT,
    _capture_frames,
    _flatten_bundle,
    _frame_diffs,
    _read_golden,
)
from tests.acceptance.reporting.test_supervisory_validations import RUNS, GateInput

from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator
from rwa_calc.reporting.pillar3.generator import Pillar3Generator

if TYPE_CHECKING:
    from collections.abc import Iterable

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

#: The six portfolios whose goldens predate this module, with the directory
#: name pattern each uses and the module that compares it. Two names break the
#: ``<portfolio>_<regime>`` rule (``rich`` and ``off-bs``), which is why the map is
#: explicit rather than derived.
_LEGACY_GOLDEN_DIRS: dict[str, tuple[str, str]] = {
    "rich": ("{regime}", "test_reporting_golden.py"),
    "off-bs": ("offbs_{regime}", "test_reporting_offbs_golden.py"),
    "ccr": ("ccr_{regime}", "test_reporting_ccr_golden.py"),
    "sa-classes": ("sa_classes_{regime}", "test_reporting_sa_classes_golden.py"),
    "irb-classes": ("irb_classes_{regime}", "test_reporting_irb_classes_golden.py"),
    "netting": ("netting_{regime}", "test_reporting_netting_golden.py"),
}

#: Prior-period runs whose LEGACY golden freezes C 08.04 and CR8 without the prior
#: frame (captured before ``RUNS`` gave them one). Owed: re-capture with the prior
#: frame under a recorded E1 decision, then delete the entry — the parity limb
#: fails until you do.
_PRIOR_FRAME_OWED: frozenset[tuple[str, str]] = frozenset(
    {
        ("crr", "rich"),
        ("b31", "rich"),
        ("crr", "irb-classes"),
        ("b31", "irb-classes"),
    }
)

#: The opening-balance cells the parity limb reads: C 08.04 row 0010 col 0010 and
#: its Pillar 3 twin, CR8 row 1 col a ("RWEA at the end of the previous period").
_C08_04_PREFIX = "corep__c08_04__"
_CR8_FRAME = "pillar3__cr8"
_OPENING_CELLS: dict[str, tuple[str, str]] = {
    _C08_04_PREFIX: ("0010", "0010"),
    _CR8_FRAME: ("1", "a"),
}

#: Basel 3.1 runs whose LEGACY golden freezes Pillar 3 OV1 row 27 ("Output floor
#: adjustment") as null, because their modules generate Pillar 3 without the run's
#: output-floor summary — every legacy module passes it to COREP only. Owed:
#: re-capture with the summary under a recorded E1 decision, then delete the entry —
#: the floor-adjustment limb fails until you do.
_FLOOR_SUMMARY_OWED: frozenset[tuple[str, str]] = frozenset(
    {
        ("b31", "rich"),
        ("b31", "off-bs"),
        ("b31", "ccr"),
        ("b31", "sa-classes"),
        ("b31", "irb-classes"),
        ("b31", "netting"),
    }
)

#: The output-floor adjustment cell the floor limb reads: OV1 row 27 col a. Only the
#: Basel 3.1 OV1 carries row 27; the CRR template has no output floor.
_OV1_FRAME = "pillar3__ov1"
_FLOOR_ADJUSTMENT_CELL: tuple[str, str] = ("27", "a")
_FLOOR_FRAMEWORK = "BASEL_3_1"

#: The CRM-substitution outflow/inflow columns ``crm-substitution`` exists to
#: exercise, per COREP template family, as measured on its banked goldens in both
#: regimes. C 07.00 col 0050 ("(-) Guarantees") is deliberately absent: measured
#: 2026-11-23 it reads 0.00 or null here and on every other registered run, so no
#: golden in the estate freezes a figure in it.
_SUBSTITUTION_COLUMNS: dict[str, tuple[str, ...]] = {
    "corep__c07_00__": ("0060", "0090", "0100"),
    "corep__c08_01__": ("0040", "0050", "0070", "0080"),
    "corep__c08_02__": ("0080",),
}

_REGEN_ENV = "REGEN_REGISTERED_GOLDENS"
_REGEN_MISSING = "missing"
_REGEN_SELECTION: frozenset[str] = frozenset(
    token.strip() for token in os.environ.get(_REGEN_ENV, "").split(",") if token.strip()
)


def run_key(run: GateInput) -> str:
    """The ``regime/portfolio`` key a run is reported and regenerated under."""
    return f"{run.regime}/{run.portfolio}"


def golden_dir(run: GateInput) -> Path:
    """The golden directory of one registered run.

    Legacy portfolios keep their historical names; every other run's directory is
    ``<portfolio with underscores>_<regime>``, one per run.
    """
    legacy = _LEGACY_GOLDEN_DIRS.get(run.portfolio)
    if legacy is not None:
        return _GOLDEN_ROOT / legacy[0].format(regime=run.regime)
    return _GOLDEN_ROOT / f"{run.portfolio.replace('-', '_')}_{run.regime}"


#: The registered runs this module owns: every run of a non-legacy portfolio.
OWNED_RUNS: tuple[GateInput, ...] = tuple(
    run for run in RUNS if run.portfolio not in _LEGACY_GOLDEN_DIRS
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_every_registered_run_has_a_golden() -> None:
    """Every run in ``RUNS`` has a banked golden directory with a manifest.

    Arrange: the registered runs and their golden directories.
    Act:     look for each run's ``manifest.json``.
    Assert:  none is missing — a registered portfolio may not skip its golden.
    """
    missing = [
        f"{run_key(run)} -> {golden_dir(run).relative_to(_GOLDEN_ROOT)}"
        for run in RUNS
        if not (golden_dir(run) / "manifest.json").is_file()
    ]

    assert not missing, (
        f"{len(missing)} registered run(s) have no golden:\n  "
        + "\n  ".join(missing)
        + f"\nCapture with {_REGEN_ENV}={_REGEN_MISSING} uv run pytest "
        "tests/acceptance/reporting/test_reporting_registered_goldens.py"
    )


def test_every_golden_directory_belongs_to_a_registered_run() -> None:
    """No golden directory is orphaned, and the legacy map is not stale.

    Arrange: the golden directories on disk and the legacy portfolio map.
    Act:     match each directory to a run, each legacy portfolio to ``RUNS``.
    Assert:  every directory is some run's golden, and every legacy portfolio is
             registered with its comparing module present — a renamed portfolio
             cannot leave a golden that nothing compares.
    """
    expected = {golden_dir(run).name for run in RUNS}
    on_disk = {path.name for path in _GOLDEN_ROOT.iterdir() if path.is_dir()}
    registered = {run.portfolio for run in RUNS}
    here = Path(__file__).parent

    orphans = sorted(on_disk - expected)
    stale = sorted(
        f"{portfolio} ({module})"
        for portfolio, (_pattern, module) in _LEGACY_GOLDEN_DIRS.items()
        if portfolio not in registered or not (here / module).is_file()
    )

    assert not orphans, f"golden directories no registered run owns: {orphans}"
    assert not stale, f"legacy golden map entries with no registered run or module: {stale}"


@pytest.mark.parametrize("run", OWNED_RUNS, ids=run_key)
def test_registered_run_matches_its_golden(run: GateInput) -> None:
    """A registered run's COREP + Pillar 3 output matches its frozen golden.

    Arrange: the run's own builder, config and prior-period config from ``RUNS``.
    Act:     run the pipeline (and the prior period), generate both bundles,
             flatten them to per-template frames.
    Assert:  the frame set, the None/scalar bundle metadata and every frame
             (structure-exact, Float64 within rtol) match the golden.
    """
    _reject_unknown_regen_tokens()
    directory = golden_dir(run)
    manifest_path = directory / "manifest.json"
    if _regen_selected(run, manifest_path):
        capture_run(run)
        pytest.skip(f"{_REGEN_ENV} - captured the golden for {run_key(run)}")

    assert manifest_path.is_file(), (
        f"No golden for {run_key(run)} at {directory}. Capture it: "
        f"{_REGEN_ENV}={run_key(run)} uv run pytest "
        "tests/acceptance/reporting/test_reporting_registered_goldens.py"
    )
    manifest = json.loads(manifest_path.read_text())
    frames, meta = generate_run_frames(run)

    errors = _golden_errors(directory, manifest, frames, meta)

    assert not errors, f"Reporting golden mismatch ({run_key(run)}):\n" + "\n".join(errors)


def test_every_prior_period_run_freezes_its_opening_balance() -> None:
    """A run with a prior-period config freezes a non-null opening RWEA.

    Arrange: every run in ``RUNS`` with ``build_prior_config`` set, and the owed
             list of legacy goldens captured without the prior frame.
    Act:     read the C 08.04 row 0010 and CR8 row 1 cells from each golden.
    Assert:  every non-owed run freezes a figure in BOTH; every owed run still
             freezes neither (so a fix must shrink ``_PRIOR_FRAME_OWED``), and
             every owed entry names a registered prior-period run.
    """
    prior_runs = {(run.regime, run.portfolio): run for run in RUNS if run.build_prior_config}
    stale_owed = sorted(f"{r}/{p}" for r, p in _PRIOR_FRAME_OWED - prior_runs.keys())

    problems: list[str] = []
    for key, run in sorted(prior_runs.items()):
        frozen = _frozen_opening_balances(golden_dir(run))
        if frozen is None:
            problems.append(f"{run_key(run)}: no golden")
            continue
        if key in _PRIOR_FRAME_OWED:
            if any(frozen.values()):
                problems.append(
                    f"{run_key(run)}: owed entry now freezes an opening balance "
                    f"{frozen} - remove it from _PRIOR_FRAME_OWED"
                )
            continue
        if not all(frozen.values()):
            problems.append(
                f"{run_key(run)}: opening balance frozen null {frozen} - the golden was "
                "captured without the run's prior-period frame"
            )

    assert not stale_owed, f"_PRIOR_FRAME_OWED names no registered prior run: {stale_owed}"
    assert not problems, "prior-frame parity:\n  " + "\n  ".join(problems)


def test_every_basel_3_1_run_freezes_its_output_floor_adjustment() -> None:
    """A Basel 3.1 run freezes a non-null Pillar 3 OV1 output-floor adjustment.

    Arrange: every Basel 3.1 run in ``RUNS``, and the owed list of legacy goldens
             whose Pillar 3 was generated without the output-floor summary.
    Act:     read OV1 row 27 col a ("Output floor adjustment") from each golden.
    Assert:  every non-owed run freezes a figure there; every owed run still
             freezes null (so a fix must shrink ``_FLOOR_SUMMARY_OWED``), and every
             owed entry names a registered Basel 3.1 run.

    Why zero counts as a figure: row 27 holds OF-ADJ, PS1/26 Art. 92(2A)
    ``12.5 x (IRB T2 - IRB CET1 - GCRA + SA T2)`` (computed in
    ``engine/aggregator/_floor.py``), the provisions and expected-loss term of
    the floored TREA, not the floor add-on. It does not depend on whether the
    floor binds: ``facility-share-binding``, where it binds, freezes -800 and
    ``crm-substitution`` freezes -2,530,000. On a run with none of the four
    amounts it is 0.0. Only a withheld summary makes it null.
    """
    floor_runs = {
        (run.regime, run.portfolio): run for run in RUNS if run.framework == _FLOOR_FRAMEWORK
    }
    stale_owed = sorted(f"{r}/{p}" for r, p in _FLOOR_SUMMARY_OWED - floor_runs.keys())

    problems: list[str] = []
    for key, run in sorted(floor_runs.items()):
        frozen = _frozen_floor_adjustment(golden_dir(run))
        if frozen is None:
            problems.append(f"{run_key(run)}: no golden")
            continue
        if key in _FLOOR_SUMMARY_OWED:
            if frozen:
                problems.append(
                    f"{run_key(run)}: owed entry now freezes an output-floor adjustment "
                    "- remove it from _FLOOR_SUMMARY_OWED"
                )
            continue
        if not frozen:
            problems.append(
                f"{run_key(run)}: OV1 row 27 col a frozen null - the golden's Pillar 3 was "
                "generated without the run's output-floor summary"
            )

    assert not stale_owed, f"_FLOOR_SUMMARY_OWED names no registered B31 run: {stale_owed}"
    assert not problems, "output-floor adjustment:\n  " + "\n  ".join(problems)


@pytest.mark.parametrize("regime", ["crr", "b31"])
def test_the_crm_substitution_golden_freezes_figures_in_its_substitution_columns(
    regime: str,
) -> None:
    """The ``crm-substitution`` golden holds a non-zero figure in every column it exercises.

    Arrange: the banked ``crm-substitution`` golden for one regime.
    Act:     look for a non-null, non-zero cell in each substitution column of
             C 07.00, C 08.01 and C 08.02, on any sheet.
    Assert:  every column carries one — so emptying it on this portfolio alone,
             which the union census and the vacuity legs cannot see while another
             run keeps the column live, reddens this module's comparison.
    """
    (run,) = (r for r in OWNED_RUNS if (r.regime, r.portfolio) == (regime, "crm-substitution"))
    directory = golden_dir(run)
    manifest_path = directory / "manifest.json"
    assert manifest_path.is_file(), f"{run_key(run)}: no golden at {directory}"
    schemas: dict[str, dict[str, str]] = json.loads(manifest_path.read_text())["frames"]

    empty = [
        f"{family}*.{column}"
        for family, columns in _SUBSTITUTION_COLUMNS.items()
        for column in columns
        if not any(
            _read_golden(directory / f"{key}.ndjson", schema)
            .filter(pl.col(column).is_not_null() & (pl.col(column) != 0.0))
            .height
            for key, schema in schemas.items()
            if key.startswith(family) and column in schema
        )
    ]

    assert not empty, f"{run_key(run)}: substitution columns frozen empty: {empty}"


# ---------------------------------------------------------------------------
# Supporting public helpers
# ---------------------------------------------------------------------------


def generate_run_frames(run: GateInput) -> tuple[dict[str, pl.DataFrame], dict[str, Any]]:
    """Generate one registered run's COREP + Pillar 3 frames, as the REST layer does.

    The run's pipeline inputs are the register's. The side inputs are those
    ``api/rest.py::get_template_bundles`` passes: the prior-period frame, where
    the run has one, reaches both generators (C 08.04 and its Pillar 3 twin
    CR8), and the run's output-floor summary reaches both (OF 02.00 and OV1
    row 27). The Python API's Pillar 3 paths (``api/export.py``,
    ``CalculationResponse.to_pillar3``) withhold the summary unless the caller
    supplies one; see the module docstring.
    """
    result = PipelineOrchestrator().run_with_data(run.build_bundle(), run.build_config())
    prior_results = (
        None
        if run.build_prior_config is None
        else PipelineOrchestrator()
        .run_with_data(run.build_bundle(), run.build_prior_config())
        .results
    )
    corep = COREPGenerator().generate_from_lazyframe(
        result.results,
        framework=run.framework,
        # As production generates it: OF 02.00 takes OF-ADJ from the run's summary.
        output_floor_summary=result.output_floor_summary,
        previous_period_results=prior_results,
    )
    pillar3 = Pillar3Generator().generate_from_lazyframe(
        result.results,
        framework=run.framework,
        # As api/rest.py generates it: OV1 row 27 (Basel 3.1) takes OF-ADJ from it.
        # api/export.py's Pillar 3 paths pass only a caller-supplied summary.
        output_floor_summary=result.output_floor_summary,
        previous_period_results=prior_results,
    )
    corep_frames, corep_meta = _flatten_bundle("corep", corep)
    p3_frames, p3_meta = _flatten_bundle("pillar3", pillar3)
    return {**corep_frames, **p3_frames}, {"corep": corep_meta, "pillar3": p3_meta}


def capture_run(run: GateInput) -> Path:
    """Write one owned run's golden into its own directory; return the directory.

    Refuses a legacy portfolio: those directories belong to their own modules.
    """
    if run.portfolio in _LEGACY_GOLDEN_DIRS:
        raise ValueError(f"{run_key(run)} is owned by {_LEGACY_GOLDEN_DIRS[run.portfolio][1]}")
    directory = golden_dir(run)
    _capture_frames(directory, *generate_run_frames(run))
    return directory


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _golden_errors(
    directory: Path,
    manifest: dict[str, Any],
    frames: dict[str, pl.DataFrame],
    meta: dict[str, Any],
) -> list[str]:
    """Every difference between a golden and freshly generated frames (empty == match)."""
    errors: list[str] = []
    expected_keys, actual_keys = set(manifest["frames"]), set(frames)
    if added := sorted(actual_keys - expected_keys):
        errors.append(f"NEW template frames not in golden: {added}")
    if dropped := sorted(expected_keys - actual_keys):
        errors.append(f"MISSING template frames present in golden: {dropped}")
    if manifest["meta"] != meta:
        errors.append(
            f"bundle metadata changed:\n  expected: {manifest['meta']}\n  actual:   {meta}"
        )
    for key in sorted(expected_keys & actual_keys):
        expected_df = _read_golden(directory / f"{key}.ndjson", manifest["frames"][key])
        errors.extend(_frame_diffs(expected_df, frames[key], key))
    return errors


def _frozen_opening_balances(directory: Path) -> dict[str, bool] | None:
    """Whether a golden freezes a non-null opening RWEA, per opening-balance frame family.

    ``None`` when the directory holds no golden. A family the golden does not emit
    at all reads ``False``: a prior-period run with no C 08.04 freezes no opening.
    """
    manifest_path = directory / "manifest.json"
    if not manifest_path.is_file():
        return None
    schemas: dict[str, dict[str, str]] = json.loads(manifest_path.read_text())["frames"]
    return {
        family: _any_cell_populated(
            (
                _read_golden(directory / f"{key}.ndjson", schema)
                for key, schema in schemas.items()
                if key.startswith(family)
            ),
            row_ref,
            column,
        )
        for family, (row_ref, column) in _OPENING_CELLS.items()
    }


def _frozen_floor_adjustment(directory: Path) -> bool | None:
    """Whether a golden freezes a non-null OV1 output-floor adjustment (row 27 col a).

    ``None`` when the directory holds no golden; ``False`` when it holds no OV1 frame.
    """
    manifest_path = directory / "manifest.json"
    if not manifest_path.is_file():
        return None
    schemas: dict[str, dict[str, str]] = json.loads(manifest_path.read_text())["frames"]
    row_ref, column = _FLOOR_ADJUSTMENT_CELL
    return _any_cell_populated(
        (
            _read_golden(directory / f"{key}.ndjson", schema)
            for key, schema in schemas.items()
            if key == _OV1_FRAME
        ),
        row_ref,
        column,
    )


def _any_cell_populated(frames: Iterable[pl.DataFrame], row_ref: str, column: str) -> bool:
    """True if any frame holds a non-null ``column`` value on row ``row_ref``."""
    return any(
        frame.filter(pl.col("row_ref") == row_ref)[column].is_not_null().any()
        for frame in frames
        if column in frame.columns
    )


def _regen_selected(run: GateInput, manifest_path: Path) -> bool:
    """Whether ``REGEN_REGISTERED_GOLDENS`` selects this run for capture."""
    if run_key(run) in _REGEN_SELECTION:
        return True
    return _REGEN_MISSING in _REGEN_SELECTION and not manifest_path.is_file()


def _reject_unknown_regen_tokens() -> None:
    """Fail on a regeneration token that names no owned run (a typo, or ``1``)."""
    known = {run_key(run) for run in OWNED_RUNS} | {_REGEN_MISSING}
    unknown = sorted(_REGEN_SELECTION - known)
    if unknown:
        pytest.fail(
            f"{_REGEN_ENV} names no owned run: {unknown}. It takes 'missing' or "
            "comma-separated regime/portfolio keys; there is deliberately no 'all'."
        )
