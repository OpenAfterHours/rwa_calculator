"""
Golden gate: the off-balance-sheet reporting portfolio (the CCF-bucket axis).

Pipeline position:
    reporting_offbs_portfolio -> PipelineOrchestrator -> COREP + Pillar 3 bundles
        -> frozen goldens (structure-exact + float rtol)

Why this exists: the rich reporting portfolio is entirely drawn, so across all 26
committed golden files not one C 07.00 row carries a value in the CCF-bucket
columns 0160 / 0170 / 0171 / 0180 / 0190. The whole conversion-factor axis of the
SA template — and every published supervisory validation rule written over it —
had no oracle at all.

Building this portfolio exposed three defects, all fixed on 2026-08-01; these
goldens capture the FIXED behaviour:

1. ``reporting/corep/c07.py`` bucketed on a column named ``ccf_applied``, which
   no pipeline run produces — the sealed aggregator exit carries ``ccf``, as
   C 08.01 / CR5 / CR6 already read it. Every submission published null buckets.
2. The bucket cells summed the POST-conversion ``ead_final``. Annex II heads that
   block "fully adjusted exposure value of off-balance sheet items", so the cells
   must carry the PRE-conversion value; they now sum ``reporting_gross_off_bs``,
   the same carrier col 0010 sums on the off-side. Fixing only the name would
   have populated the columns and still failed every rule written over them.
3. ``obs_product`` did not survive the hierarchy stage, so the Art. 111(1)
   product -> risk_type fill in ``engine/ccf.py`` was unreachable end-to-end.

The assertions below the golden gate are the part that does not move: the
per-row CCFs the engine resolves, the exact bucket values per regime, and the
three supervisory identities evaluated against generated cells rather than
recomputed from inputs — ``v6364_m``, ``boe_b0471``, and the CRR analogue.

Regenerate with REGEN_REPORTING_GOLDENS=1 only alongside a recorded decision —
never to make a red suite green.

References:
- COREP Annex II, C 07.00 cols 0160-0190 (fully adjusted exposure value of
  off-balance-sheet items, broken down by conversion factor)
- CRR Art. 111(1) + Annex I paras 1-4; PRA PS1/26 Art. 111(1) Table A1 Rows 1-7
- tests/fixtures/reporting_offbs_portfolio.py: the oracle portfolio
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
from tests.fixtures.reporting_offbs_portfolio import (
    CT_DOC_CREDIT,
    CT_GUARANTEE,
    CT_STANDBY_MR,
    FAC_NIF,
    FAC_OC,
    FAC_UCC,
    LIMIT_NIF,
    LIMIT_UCC,
    NOMINAL_DOC_CREDIT,
    NOMINAL_FRC_FWD,
    NOMINAL_GUARANTEE,
    NOMINAL_STANDBY,
    OFFBS_EXPECTED_CCF,
    UNDRAWN_OC,
    UNDRAWN_SUFFIX,
    build_reporting_offbs_bundle,
)

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator
from rwa_calc.reporting.pillar3.generator import Pillar3Generator

# regime key -> (golden subdir, framework string)
_REGIMES: dict[str, tuple[str, str]] = {
    "crr": ("offbs_crr", "CRR"),
    "b31": ("offbs_b31", "BASEL_3_1"),
}

#: The five C 07.00 CCF-bucket columns. 0171 (the Basel 3.1 40% "other
#: commitments" bucket) exists only on the Basel 3.1 template.
_CCF_COLUMNS: tuple[str, ...] = ("0160", "0170", "0171", "0180", "0190")


def _config(regime_key: str) -> CalculationConfig:
    # STANDARDISED on purpose: C 07.00 is the SA template and its CCF columns are
    # defined over the Art. 111 / Table A1 schedule. An F-IRB CCF (e.g. the
    # Art. 166(8)(d) 75%) has no bucket on this template to land in.
    if regime_key == "crr":
        return CalculationConfig.crr(
            reporting_date=date(2025, 12, 31), permission_mode=PermissionMode.STANDARDISED
        )
    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 1), permission_mode=PermissionMode.STANDARDISED
    )


def _cell(sheet: pl.DataFrame, row_ref: str, col: str) -> float | None:
    """One C 07.00 cell by row ref, or None when the row/column is absent."""
    if col not in sheet.columns:
        return None
    row = sheet.filter(pl.col("row_ref") == row_ref)
    return None if row.height == 0 else row[col][0]


def _generate_frames(regime_key: str) -> tuple[dict[str, pl.DataFrame], dict]:
    """Run the off-balance-sheet portfolio through one regime, flatten both bundles."""
    _subdir, framework = _REGIMES[regime_key]
    result = PipelineOrchestrator().run_with_data(
        build_reporting_offbs_bundle(), _config(regime_key)
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
def test_offbs_reporting_templates_match_golden(regime_key: str) -> None:
    """Generated templates match the frozen off-BS goldens (structure + float rtol).

    Arrange: off-balance-sheet portfolio + regime config.
    Act:     run pipeline -> generate both bundles -> flatten to per-template frames.
    Assert:  every golden frame is reproduced, the frame set matches exactly, and
             the None/scalar metadata matches.
    """
    subdir = _REGIMES[regime_key][0]
    golden_dir: Path = _GOLDEN_ROOT / subdir

    if _REGEN:
        _capture_frames(golden_dir, *_generate_frames(regime_key))
        pytest.skip(f"REGEN_REPORTING_GOLDENS=1 — captured off-BS goldens for {regime_key!r}")

    manifest_path = golden_dir / "manifest.json"
    assert manifest_path.exists(), (
        f"No off-BS reporting goldens for {regime_key!r} at {golden_dir}. Capture them first: "
        "REGEN_REPORTING_GOLDENS=1 uv run pytest "
        "tests/acceptance/reporting/test_reporting_offbs_golden.py"
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

    assert not errors, "Off-BS reporting golden mismatch ({}):\n{}".format(
        regime_key, "\n".join(errors)
    )


# =============================================================================
# What does not move: the fixture's own contract, and the pinned defect
# =============================================================================


@pytest.mark.parametrize("regime_key", list(_REGIMES))
def test_every_ccf_bucket_is_exercised_at_the_engine(regime_key: str) -> None:
    """Every portfolio row resolves its intended Art. 111 / Table A1 CCF.

    Guards the fixture itself. If this goes quiet the goldens stop testing the
    CCF axis and the C 07.00 defect below would look "fixed" by absence.

    Arrange: the off-balance-sheet portfolio under one regime.
    Act:     run the pipeline.
    Assert:  each off-BS exposure carries the CCF its Annex I / Table A1 row
             prescribes, and the regime's full bucket set is covered.
    """
    # Arrange + Act
    result = PipelineOrchestrator().run_with_data(
        build_reporting_offbs_bundle(), _config(regime_key)
    )
    rows = (
        result.results.filter(pl.col("exposure_reference").is_in(list(OFFBS_EXPECTED_CCF)))
        .select("exposure_reference", "ccf")
        .collect()
    )
    actual = dict(zip(rows["exposure_reference"], rows["ccf"], strict=True))
    index = 0 if regime_key == "crr" else 1
    expected = {ref: ccfs[index] for ref, ccfs in OFFBS_EXPECTED_CCF.items()}

    # Assert
    assert actual == pytest.approx(expected), regime_key
    # CRR Art. 111 has four buckets (0/20/50/100%), Table A1 five (10/20/40/50/100%).
    assert len(set(expected.values())) == (4 if regime_key == "crr" else 5), regime_key


@pytest.mark.parametrize("regime_key", list(_REGIMES))
def test_c07_ccf_buckets_report_the_pre_conversion_value(regime_key: str) -> None:
    """Cols 0160-0190 carry the fully adjusted OFF-BS value per CCF bucket.

    The oracle this portfolio exists for. Annex II heads the block "breakdown of
    the fully adjusted exposure value of off-balance sheet items by conversion
    factors", so each cell is the PRE-conversion value of the items in that
    bucket — not the post-conversion EAD, and not the on-balance-sheet book.

    Note where the regimes diverge: ``FAC_OC`` (6.0m of undrawn "other
    commitments") sits in 0180 under CRR Annex I item 2(b) at 50% and in 0171
    under Table A1 Row 5 at 40% — column 0171 is not on the CRR template at all.

    Arrange: the off-balance-sheet portfolio under one regime.
    Act:     generate C 07.00.
    Assert:  every bucket cell on both sheets, on the total row (0010), the
             off-balance row (0080), and the on-balance row (0070).
    """
    # Arrange
    corporate_buckets = (
        {
            "0160": LIMIT_UCC,
            "0170": NOMINAL_DOC_CREDIT,
            "0171": None,
            "0180": NOMINAL_STANDBY + LIMIT_NIF + UNDRAWN_OC,
            "0190": NOMINAL_GUARANTEE,
        }
        if regime_key == "crr"
        else {
            "0160": LIMIT_UCC,
            "0170": NOMINAL_DOC_CREDIT,
            "0171": UNDRAWN_OC,
            "0180": NOMINAL_STANDBY + LIMIT_NIF,
            "0190": NOMINAL_GUARANTEE,
        }
    )
    institution_buckets: dict[str, float | None] = {
        "0160": None,
        "0170": None,
        "0171": None,
        "0180": None,
        "0190": NOMINAL_FRC_FWD,
    }
    expected = {
        "corep__c07_00__corporate": corporate_buckets,
        "corep__c07_00__institution": institution_buckets,
    }

    # Act
    frames, _meta = _generate_frames(regime_key)

    # Assert
    for key, buckets in expected.items():
        sheet = frames[key]
        for row_ref in ("0010", "0080"):  # the total row and the off-balance row
            for col, value in buckets.items():
                if col not in sheet.columns:
                    assert value is None, f"{regime_key} {key} {col} absent but expected {value}"
                    continue
                assert _cell(sheet, row_ref, col) == pytest.approx(value), (
                    f"{regime_key} {key} row {row_ref} col {col}"
                )
        # The on-balance-sheet row must carry NO bucket. A drawn loan has
        # ccf 0.0, which IS a real CRR bucket (Annex I LR 0% -> col 0160), so
        # this pins the off-side narrowing rather than a numeric coincidence.
        for col in _CCF_COLUMNS:
            if col in sheet.columns:
                assert _cell(sheet, "0070", col) is None, f"{regime_key} {key} row 0070 {col}"


@pytest.mark.parametrize("regime_key", list(_REGIMES))
def test_ccf_buckets_decompose_the_off_balance_sheet_row(regime_key: str) -> None:
    """``v6364_m``: {c0150} = {c0160}+{c0170}+{c0171}+{c0180}+{c0190} on row 0080.

    The buckets partition the off-balance-sheet row's fully adjusted exposure
    value, so they must foot to it exactly. This is the identity that breaks the
    moment the cells go back to summing post-conversion EAD.

    Arrange: the off-balance-sheet portfolio under one regime.
    Act:     generate C 07.00 and sum the bucket columns of row 0080.
    Assert:  the sum equals col 0150 of the same row, on every sheet.
    """
    # Arrange + Act
    frames, _meta = _generate_frames(regime_key)
    sheets = {k: v for k, v in frames.items() if k.startswith("corep__c07_00__")}

    # Assert
    assert sheets
    for key, sheet in sheets.items():
        bucket_sum = sum(
            _cell(sheet, "0080", col) or 0.0 for col in _CCF_COLUMNS if col in sheet.columns
        )
        assert bucket_sum == pytest.approx(_cell(sheet, "0080", "0150")), key


def test_boe_b0471_sa_exposure_value_derivation_closes() -> None:
    """``boe_b0471`` (live, ERROR, Basel 3.1) closes exactly on real output.

        {c0200} = {c0150} - 0.9*{c0160} - 0.8*{c0170} - 0.6*{c0171} - 0.5*{c0180}

    Each coefficient is (1 - CCF) for its bucket, so the rule says what survives
    conversion is the fully adjusted value less the converted-away portion.
    Evaluated against the GENERATED cells, not recomputed from fixture inputs —
    this is the end-to-end proof, and it was unevaluable before the CCF-bucket
    carrier fix because every bucket cell rendered null.

    Arrange: the off-balance-sheet portfolio under Basel 3.1.
    Act:     generate C 07.00 and apply the rule's right-hand side to row 0010.
    Assert:  it equals the reported col 0200, on every sheet.
    """
    # Arrange + Act
    frames, _meta = _generate_frames("b31")
    sheets = {k: v for k, v in frames.items() if k.startswith("corep__c07_00__")}

    # Assert
    assert sheets
    for key, sheet in sheets.items():
        cells = {col: _cell(sheet, "0010", col) or 0.0 for col in _CCF_COLUMNS}
        rhs = (
            (_cell(sheet, "0010", "0150") or 0.0)
            - 0.9 * cells["0160"]
            - 0.8 * cells["0170"]
            - 0.6 * cells["0171"]
            - 0.5 * cells["0180"]
        )
        assert rhs == pytest.approx(_cell(sheet, "0010", "0200")), key


def test_crr_exposure_value_derivation_closes() -> None:
    """The CRR analogue of ``boe_b0471`` closes on the four-bucket schedule.

    CRR Art. 111 / Annex I has no 40% bucket, and col 0160 is the 0% UCC bucket
    rather than Basel 3.1's 10%, so the coefficients are 1.0 / 0.8 / 0.5:

        {c0200} = {c0150} - 1.0*{c0160} - 0.8*{c0170} - 0.5*{c0180}

    Pinned separately so the Basel 3.1 rule above is never quietly applied to a
    CRR sheet — the two coefficient sets are not interchangeable.

    Arrange: the off-balance-sheet portfolio under CRR.
    Act:     generate C 07.00 and apply the CRR right-hand side to row 0010.
    Assert:  it equals the reported col 0200, on every sheet.
    """
    # Arrange + Act
    frames, _meta = _generate_frames("crr")
    sheets = {k: v for k, v in frames.items() if k.startswith("corep__c07_00__")}

    # Assert
    assert sheets
    for key, sheet in sheets.items():
        cells = {col: _cell(sheet, "0010", col) or 0.0 for col in _CCF_COLUMNS}
        rhs = (
            (_cell(sheet, "0010", "0150") or 0.0)
            - 1.0 * cells["0160"]
            - 0.8 * cells["0170"]
            - 0.5 * cells["0180"]
        )
        assert rhs == pytest.approx(_cell(sheet, "0010", "0200")), key


@pytest.mark.parametrize("regime_key", list(_REGIMES))
def test_documentary_credit_resolves_its_risk_type_from_obs_product(regime_key: str) -> None:
    """``obs_product`` drives the Art. 111(1) risk_type fill end-to-end.

    ``CT_DOC_CREDIT`` carries ``obs_product="DOCUMENTARY_CREDIT"`` and NO
    explicit ``risk_type``. The hierarchy stage used to drop ``obs_product``, so
    the fill in ``engine/ccf.py`` was unreachable from a full pipeline run and
    this row fell to the conservative 50% MR default. Pinned end-to-end because
    an engine-level unit test cannot catch a lost column projection.

    Arrange: the off-balance-sheet portfolio under one regime.
    Act:     run the pipeline.
    Assert:  the row resolves risk_type MLR and the 20% Row 6(a) CCF.
    """
    # Arrange + Act
    result = PipelineOrchestrator().run_with_data(
        build_reporting_offbs_bundle(), _config(regime_key)
    )
    row = (
        result.results.filter(pl.col("exposure_reference") == CT_DOC_CREDIT)
        .select("risk_type", "ccf")
        .collect()
    )

    # Assert
    assert row.height == 1, regime_key
    assert row["risk_type"][0] == "MLR", regime_key
    assert row["ccf"][0] == pytest.approx(0.2), regime_key


def test_all_eight_portfolio_exposures_reach_the_templates() -> None:
    """The eight designed exposures survive the pipeline in both regimes.

    A dropped facility_undrawn row (uncommitted facilities emit none) or a
    swallowed contingent would shrink the bucket axis without failing the golden
    gate on its own, so the row count is pinned explicitly.

    Arrange: the off-balance-sheet portfolio.
    Act:     run the pipeline under each regime.
    Assert:  one drawn loan + four contingents + three facility_undrawn rows.
    """
    expected_offbs = {
        CT_GUARANTEE,
        CT_DOC_CREDIT,
        CT_STANDBY_MR,
        FAC_NIF + UNDRAWN_SUFFIX,
        FAC_OC + UNDRAWN_SUFFIX,
        FAC_UCC + UNDRAWN_SUFFIX,
    }
    for regime_key in _REGIMES:
        # Arrange + Act
        result = PipelineOrchestrator().run_with_data(
            build_reporting_offbs_bundle(), _config(regime_key)
        )
        df = result.results.collect()

        # Assert
        assert df.height == 8, regime_key
        assert expected_offbs <= set(df["exposure_reference"]), regime_key
        counts = dict(df["exposure_type"].value_counts().iter_rows())
        assert counts == {"loan": 1, "contingent": 4, "facility_undrawn": 3}, regime_key
