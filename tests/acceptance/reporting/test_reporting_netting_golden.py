"""
Golden gate: the on-balance-sheet netting portfolio (the agreement-perimeter axis).

Pipeline position:
    reporting_netting_portfolio -> PipelineOrchestrator -> COREP + Pillar 3 bundles
        -> frozen goldens (structure-exact + float rtol)

Why this exists — the coverage gap recorded in PR #487. The netting commit on this
branch makes on-balance-sheet netting key on ``netting_agreement_reference`` ALONE
(CRR/PS1-26 Art. 195 / 205(a) / 219), so a deposit held by counterparty A now
offsets a loan to counterparty B under the same agreement. NO golden, oracle or
RUNS-registered reporting portfolio in the estate carried an agreement that spans
counterparties: of the three fixture files that set a netting reference at all,
``p1_241`` and the ``r1_negative_gross`` portfolio put every leg under ONE
counterparty (such a reference nets identically whichever perimeter key is in
force), and ``p1_238`` — which DOES span counterparties and whose RWA the Feature
DOES move — is an in-memory acceptance fixture asserting RWA, not template cells,
and is not registered in ``RUNS``. The change was therefore invisible to every
golden, census and supervisory rule, and C 07.00 col 0035 was dead
(``NO_FIXTURE``) in every registered run. This portfolio is the fixture that
lights it.

Two-leg design (LESSONS.md B5 — a single moving row leaves the cell at 0.00
afterwards, so a test over it cannot tell "the change worked" from "the change
zeroed the cell"):

- ``AGR_SAME`` (CP_D's own deposit and own loan) is the leg that SURVIVES either
  Feature state — ``NETTING_D`` is 1,000,000 whether the perimeter key is the
  agreement alone or ``(agreement, counterparty)``;
- ``AGR_GROUP`` (CP_A's deposit against CP_B's and CP_C's loans) is the leg that
  MOVES — 2,000,000 of pro-rata benefit under the default Feature, zero with it
  disabled.

The regime asymmetry of col 0035 is pinned explicitly rather than left implicit.
``reporting/corep/c07.py`` binds ``0035`` ("(-) Adjustment due to on-balance sheet
netting") only under ``if is_b31:``; the CRR C 07.00 sheet has no such column at
all and shows the netting only through the col 0200 exposure value. A test that
merely skipped the cell under CRR would look identical to one written against a
template that had lost the column.

Sign note: the reported col 0035 cell is the NEGATION of
``Sum("on_bs_netting_amount")``. ``reporting/corep/postpass.py::negate_deduction_cols``
applies the COREP Annex II §1.3 "(-)"-label convention to it after execution, so
the assertions below expect ``-TOTAL_NETTING_*``. The fixture constants stay
positive magnitudes, which is what the engine carrier holds.

Regenerate with REGEN_REPORTING_GOLDENS=1 only alongside a recorded decision —
never to make a red suite green.

References:
- CRR Art. 195 / 205(a) / 219; PRA PS1/26 equivalents (on-balance-sheet netting)
- CRR Art. 122 / PS1/26 Art. 122(2) Table 6 (unrated corporate SA risk weight)
- COREP Annex II, C 07.00 col 0035 and §1.3 (the "(-)" sign convention)
- tests/fixtures/reporting_netting_portfolio.py: the oracle portfolio
- Pack Feature ``on_bs_netting_perimeter_is_agreement`` (both regimes, enabled)
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
from tests.fixtures.reporting_netting_portfolio import (
    AGR_GROUP,
    AGR_SAME,
    DEP_A,
    DEP_D,
    EXPECTED_NETTING,
    EXPOSURE_VALUE_DISABLED,
    EXPOSURE_VALUE_ENABLED,
    GROSS_ON_BS,
    LN_B,
    LN_D,
    NETTING_B,
    NETTING_D,
    NETTING_FEATURE,
    TOTAL_NETTING_DISABLED,
    TOTAL_NETTING_ENABLED,
    build_reporting_netting_bundle,
)

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import ERROR_CROSS_COUNTERPARTY_NETTING
from rwa_calc.domain.enums import CQS, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator
from rwa_calc.reporting.pillar3.generator import Pillar3Generator
from rwa_calc.rulebook import RulepackV0
from rwa_calc.rulebook.compile import lookup_float_map
from rwa_calc.rulebook.model import Citation, Feature

# regime key -> (golden subdir, framework string)
_REGIMES: dict[str, tuple[str, str]] = {
    "crr": ("netting_crr", "CRR"),
    "b31": ("netting_b31", "BASEL_3_1"),
}

#: The single C 07.00 sheet this portfolio produces — five unrated corporates.
_C07_CORPORATE: str = "corep__c07_00__corporate"

#: "(-) Adjustment due to on-balance sheet netting" — Basel 3.1 template only.
_NETTING_COL: str = "0035"

#: The unrated-corporate SA risk weight is read from the resolved pack, never
#: typed (LESSONS.md A4). The two regimes hold it in differently-named entries
#: under differently-typed "unrated" keys — CRR keys the table on the ``CQS``
#: enum, Basel 3.1 on raw ints with ``None`` for unrated.
_CORPORATE_RW_ENTRY: dict[str, str] = {
    "crr": "corporate_risk_weights",
    "b31": "b31_corporate_risk_weights",
}
_UNRATED_KEY: dict[str, object] = {"crr": CQS.UNRATED, "b31": None}

#: Citation framework for the Feature-disabled control pack, per regime.
_DISABLED_CITATION_FRAMEWORK: dict[str, str] = {"crr": "CRR", "b31": "PS1/26"}


def _config(regime_key: str) -> CalculationConfig:
    # STANDARDISED on purpose: every counterparty is an unrated corporate, so the
    # whole book routes SA and C 07.00 is the template that carries it. Col 0035
    # is an SA-template column; an IRB permission would buy nothing here and cost
    # a pipeline run.
    if regime_key == "crr":
        return CalculationConfig.crr(
            reporting_date=date(2025, 12, 31), permission_mode=PermissionMode.STANDARDISED
        )
    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 1), permission_mode=PermissionMode.STANDARDISED
    )


def _unrated_corporate_rw(regime_key: str) -> float:
    """The unrated-corporate SA risk weight, as the ENGINE resolves it."""
    pack = RulepackV0.from_config(_config(regime_key)).pack
    table = pack.lookup(_CORPORATE_RW_ENTRY[regime_key])
    return lookup_float_map(table)[_UNRATED_KEY[regime_key]]  # type: ignore[index]


def _perimeter_disabled_rulepack(regime_key: str) -> RulepackV0:
    """A rulepack with ``on_bs_netting_perimeter_is_agreement`` flipped OFF.

    The pre-reversal (P1.238) reading: the perimeter reverts to
    ``(agreement, counterparty)`` keying, so AGR_GROUP's three-counterparty legs
    stop netting and AGR_SAME's single-counterparty pair still does.
    """
    config = _config(regime_key)
    pack = RulepackV0.from_config(config).pack.with_overrides(
        **{
            NETTING_FEATURE: Feature(
                name=NETTING_FEATURE,
                enabled=False,
                citation=Citation(
                    _DISABLED_CITATION_FRAMEWORK[regime_key],
                    "195",
                    "agreement perimeter disabled for test",
                ),
            )
        }
    )
    return RulepackV0.from_resolved(config, pack)


def _run(regime_key: str, *, netting_enabled: bool = True):
    """Run the netting portfolio through one regime, in one Feature state."""
    config = _config(regime_key)
    if netting_enabled:
        return PipelineOrchestrator().run_with_data(build_reporting_netting_bundle(), config)
    return PipelineOrchestrator().run_with_data(
        build_reporting_netting_bundle(),
        config,
        rulepack=_perimeter_disabled_rulepack(regime_key),
    )


def _generate_frames(
    regime_key: str, *, netting_enabled: bool = True
) -> tuple[dict[str, pl.DataFrame], dict]:
    """Run the netting portfolio through one regime, flatten both bundles."""
    framework = _REGIMES[regime_key][1]
    result = _run(regime_key, netting_enabled=netting_enabled)

    corep = COREPGenerator().generate_from_lazyframe(result.results, framework=framework)
    pillar3 = Pillar3Generator().generate_from_lazyframe(result.results, framework=framework)

    corep_frames, corep_meta = _flatten_bundle("corep", corep)
    p3_frames, p3_meta = _flatten_bundle("pillar3", pillar3)
    return {**corep_frames, **p3_frames}, {"corep": corep_meta, "pillar3": p3_meta}


def _cell(sheet: pl.DataFrame, row_ref: str, col: str) -> float | None:
    """One C 07.00 cell by row ref, or None when the row/column is absent."""
    if col not in sheet.columns:
        return None
    row = sheet.filter(pl.col("row_ref") == row_ref)
    return None if row.height == 0 else row[col][0]


def _netting_by_reference(result) -> dict[str, float]:
    """``exposure_reference -> on_bs_netting_amount`` off the result frame."""
    df = result.results.select("exposure_reference", "on_bs_netting_amount").collect()
    return dict(zip(df["exposure_reference"], df["on_bs_netting_amount"], strict=True))


def _crm016(result) -> list:
    return [e for e in result.errors if e.code == ERROR_CROSS_COUNTERPARTY_NETTING]


# =============================================================================
# The golden gate
# =============================================================================


@pytest.mark.parametrize("regime_key", list(_REGIMES))
def test_netting_reporting_templates_match_golden(regime_key: str) -> None:
    """Generated templates match the frozen netting goldens (structure + float rtol).

    Arrange: on-balance-sheet netting portfolio + regime config.
    Act:     run pipeline -> generate both bundles -> flatten to per-template frames.
    Assert:  every golden frame is reproduced, the frame set matches exactly, and
             the None/scalar metadata matches.
    """
    subdir = _REGIMES[regime_key][0]
    golden_dir: Path = _GOLDEN_ROOT / subdir

    if _REGEN:
        _capture_frames(golden_dir, *_generate_frames(regime_key))
        pytest.skip(f"REGEN_REPORTING_GOLDENS=1 — captured netting goldens for {regime_key!r}")

    manifest_path = golden_dir / "manifest.json"
    assert manifest_path.exists(), (
        f"No netting reporting goldens for {regime_key!r} at {golden_dir}. Capture them first: "
        "REGEN_REPORTING_GOLDENS=1 uv run pytest "
        "tests/acceptance/reporting/test_reporting_netting_golden.py"
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

    assert not errors, "Netting reporting golden mismatch ({}):\n{}".format(
        regime_key, "\n".join(errors)
    )


# =============================================================================
# What does not move: the per-exposure netting, the template cells, the Feature
# =============================================================================


@pytest.mark.parametrize("regime_key", list(_REGIMES))
def test_every_netting_leg_carries_its_art_219_pro_rata_share(regime_key: str) -> None:
    """Each loan leg carries the on-balance-sheet netting benefit it is owed.

    The engine-side oracle. AGR_GROUP's 2,000,000 deposit is allocated
    drawn-against-drawn across CP_B's and CP_C's loans (CRR Art. 219: 10/15 and
    5/15); AGR_SAME's 1,000,000 lands whole on CP_D's own loan; the un-netted
    control carries exactly 0.0. Both deposit rows carry 0.0 — the benefit is
    reported on the borrowing side, not on the leg that provides it.

    Arrange: the netting portfolio under one regime.
    Act:     run the pipeline.
    Assert:  every loan leg's ``on_bs_netting_amount`` equals its constant, both
             deposits carry 0.0, and no row publishes a null (a null and a
             legitimate zero are different claims).
    """
    # Arrange
    assert sum(EXPECTED_NETTING.values()) == pytest.approx(TOTAL_NETTING_ENABLED), (
        "the per-leg constants do not foot to TOTAL_NETTING_ENABLED, so the "
        "template assertions below and the engine assertions here are testing "
        "two different portfolios"
    )

    # Act
    result = _run(regime_key)
    actual = _netting_by_reference(result)

    # Assert
    assert None not in actual.values(), (
        f"{regime_key}: a row published a null on_bs_netting_amount — "
        f"a null and a legitimate zero are different claims: {actual}"
    )
    for reference, expected in EXPECTED_NETTING.items():
        assert actual[reference] == pytest.approx(expected), f"{regime_key} {reference}"
    for deposit in (DEP_A, DEP_D):
        assert actual[deposit] == pytest.approx(0.0), (
            f"{regime_key} {deposit}: the deposit leg carries netting benefit of "
            "its own, so the benefit is double-counted across the pool"
        )
    assert sum(actual.values()) == pytest.approx(TOTAL_NETTING_ENABLED), regime_key


@pytest.mark.parametrize("regime_key", list(_REGIMES))
def test_c07_reports_the_netted_corporate_book(regime_key: str) -> None:
    """C 07.00's gross, netting-adjustment and exposure-value cells, per regime.

    Col 0010 is the PRE-netting gross (the sealed on-balance-sheet carriers floor
    the two deposits to 0.0, so it is the four positive drawn balances); col 0200
    is the exposure value AFTER netting; col 0220 is that at the unrated-corporate
    SA risk weight, read from the resolved pack rather than typed.

    Col 0035 is the regime asymmetry this portfolio exists to pin. It is bound
    only under ``if is_b31:`` in ``reporting/corep/c07.py`` — the CRR sheet does
    not carry the column at all, and shows the netting only through col 0200. It
    is reported NEGATIVE: the Annex II §1.3 "(-)" convention is applied to it by
    ``postpass.negate_deduction_cols`` after execution.

    Arrange: the netting portfolio under one regime.
    Act:     generate C 07.00.
    Assert:  the total row (0010) and the on-balance-sheet row (0070) carry the
             figures above and are non-null; the off-balance-sheet row (0080)
             carries no netting adjustment; and col 0035 is present under Basel
             3.1 and absent under CRR.
    """
    # Arrange
    risk_weight = _unrated_corporate_rw(regime_key)
    assert risk_weight > 0.0, (
        f"{regime_key}: the unrated-corporate risk weight resolved to {risk_weight}, "
        "so col 0220 would be 0 whatever the exposure value and the assertion "
        "below could not distinguish a correct RWEA from a lost one"
    )

    # Act
    frames, _meta = _generate_frames(regime_key)

    # Assert — the sheet is emitted at all (LESSONS.md B4: absence, not wrongness)
    assert _C07_CORPORATE in frames, (
        f"{regime_key}: {_C07_CORPORATE} was not emitted; the portfolio is five "
        f"corporates, so every assertion below would vacuously pass. Got: {sorted(frames)}"
    )
    sheet = frames[_C07_CORPORATE]

    # The total row and the on-balance-sheet row. The whole book is drawn, so the
    # two must agree — this is the breakdown-foots-to-parent leg.
    for row_ref in ("0010", "0070"):
        assert _cell(sheet, row_ref, "0010") == pytest.approx(GROSS_ON_BS), (
            f"{regime_key} {row_ref}"
        )
        assert _cell(sheet, row_ref, "0200") == pytest.approx(EXPOSURE_VALUE_ENABLED), (
            f"{regime_key} {row_ref}"
        )
        assert _cell(sheet, row_ref, "0220") == pytest.approx(
            EXPOSURE_VALUE_ENABLED * risk_weight
        ), f"{regime_key} {row_ref}"

    # The off-balance-sheet row has no exposure at all, so it renders all-null.
    assert _cell(sheet, "0080", "0010") is None, regime_key

    if regime_key == "b31":
        assert _NETTING_COL in sheet.columns, (
            "col 0035 is bound under `if is_b31:` in reporting/corep/c07.py and is "
            "missing from the Basel 3.1 sheet"
        )
        for row_ref in ("0010", "0070"):
            assert _cell(sheet, row_ref, _NETTING_COL) == pytest.approx(-TOTAL_NETTING_ENABLED), (
                f"row {row_ref}: col 0035 carries the Annex II §1.3 '(-)' sign, so it "
                "is the negation of Sum(on_bs_netting_amount)"
            )
        assert _cell(sheet, "0080", _NETTING_COL) is None, (
            "the off-balance-sheet row has no on-balance-sheet netting to adjust"
        )
    else:
        assert _NETTING_COL not in sheet.columns, (
            "col 0035 appeared on the CRR C 07.00 sheet. It is bound only under "
            "`if is_b31:` — CRR has no dedicated netting-adjustment column and "
            "shows the netting through col 0200. A CRR sheet that carries it is "
            "reporting a Basel 3.1 column into a CRR return."
        )


@pytest.mark.parametrize("regime_key", list(_REGIMES))
def test_agreement_perimeter_feature_moves_one_leg_and_not_the_other(regime_key: str) -> None:
    """The two-leg Feature test: one netting leg MOVES, one SURVIVES.

    LESSONS.md B5/C1.11 — a detector comes with the mutation it detects. Running
    the same bundle against a pack with ``on_bs_netting_perimeter_is_agreement``
    disabled restores the pre-reversal ``(agreement, counterparty)`` keying, so:

    - ``LN_B`` (AGR_GROUP, CP_B's loan against CP_A's deposit) loses its benefit
      entirely — the leg that MOVES;
    - ``LN_D`` (AGR_SAME, CP_D's own loan against CP_D's own deposit) keeps
      ``NETTING_D`` in BOTH states — the leg that SURVIVES, without which a
      zeroed cell would look identical to a working one.

    Arrange: the netting portfolio, run twice per regime (default pack, disabled
             pack).
    Act:     read the per-leg netting amounts and generate C 07.00 for each state.
    Assert:  col 0200 moves by the group agreement's benefit in both regimes;
             col 0035 moves with it under Basel 3.1; the two legs behave as above.
    """
    # Arrange — C11 adequacy: the two states must actually differ.
    assert TOTAL_NETTING_ENABLED != TOTAL_NETTING_DISABLED, (
        "the enabled and disabled netting totals are equal, so no assertion below "
        "can distinguish an agreement-perimeter run from a counterparty-perimeter "
        "one and this test guards nothing"
    )
    assert EXPOSURE_VALUE_ENABLED != EXPOSURE_VALUE_DISABLED, (
        "the enabled and disabled exposure values are equal, so col 0200 cannot witness the Feature"
    )
    assert NETTING_B != 0.0, "the moving leg carries no benefit to lose"

    # Act
    enabled_netting = _netting_by_reference(_run(regime_key))
    disabled_netting = _netting_by_reference(_run(regime_key, netting_enabled=False))
    enabled_frames, _ = _generate_frames(regime_key)
    disabled_frames, _ = _generate_frames(regime_key, netting_enabled=False)
    enabled_sheet = enabled_frames[_C07_CORPORATE]
    disabled_sheet = disabled_frames[_C07_CORPORATE]

    # Assert — the leg that MOVES and the leg that SURVIVES
    assert enabled_netting[LN_B] == pytest.approx(NETTING_B), regime_key
    assert disabled_netting[LN_B] == pytest.approx(0.0), (
        f"{regime_key}: {LN_B} still nets with the agreement perimeter disabled. "
        "CP_A, CP_B and CP_C are three different counterparties, so under "
        "(agreement, counterparty) keying no leg of AGR_GROUP has a partner."
    )
    assert enabled_netting[LN_D] == pytest.approx(NETTING_D), regime_key
    assert disabled_netting[LN_D] == pytest.approx(NETTING_D), (
        f"{regime_key}: disabling the agreement perimeter also zeroed {LN_D}, "
        "which is a SAME-counterparty pair and nets under either reading. A "
        "Feature that zeroes this leg is not restoring P1.238, it is breaking "
        "on-balance-sheet netting outright."
    )

    # Assert — the template cells, both regimes on col 0200
    assert _cell(enabled_sheet, "0010", "0200") == pytest.approx(EXPOSURE_VALUE_ENABLED), regime_key
    assert _cell(disabled_sheet, "0010", "0200") == pytest.approx(EXPOSURE_VALUE_DISABLED), (
        regime_key
    )

    # Assert — col 0035, Basel 3.1 only, carrying the Annex II "(-)" sign
    if regime_key == "b31":
        assert _cell(enabled_sheet, "0010", _NETTING_COL) == pytest.approx(-TOTAL_NETTING_ENABLED)
        assert _cell(disabled_sheet, "0010", _NETTING_COL) == pytest.approx(-TOTAL_NETTING_DISABLED)


@pytest.mark.parametrize("regime_key", list(_REGIMES))
def test_spanning_agreement_raises_exactly_one_crm016_audit_record(regime_key: str) -> None:
    """CRM016 records the applied cross-counterparty offset — once, for AGR_GROUP.

    The offset IS applied under the agreement perimeter, so CRM016 is an audit
    trail rather than a rejection: Art. 205(a) enforceability against every party
    to the agreement has to be evidenced separately. One record per spanning
    agreement — AGR_SAME never crosses a counterparty boundary and must not
    appear, or the warning stops carrying information (LESSONS.md B9: an alarm
    that fires on everything is not an alarm).

    Arrange: the netting portfolio under one regime.
    Act:     run the pipeline and filter the error channel to CRM016.
    Assert:  exactly one record, naming AGR_GROUP and its three counterparties,
             and none naming AGR_SAME.
    """
    # Arrange + Act
    result = _run(regime_key)
    warnings = _crm016(result)

    # Assert
    assert len(warnings) == 1, (
        f"{regime_key}: expected exactly one CRM016 (AGR_GROUP), got "
        f"{[w.message for w in warnings]}"
    )
    message = warnings[0].message
    assert AGR_GROUP in message, (
        f"{regime_key}: CRM016 does not name {AGR_GROUP!r}, so the audit record "
        f"does not say which agreement needs Art. 205(a) evidence: {message!r}"
    )
    assert "across 3 counterparties" in message, (
        f"{regime_key}: CRM016 does not say how many counterparties the agreement "
        f"spans; the count is the reviewable part of the record: {message!r}"
    )
    assert AGR_SAME not in message, (
        f"{regime_key}: CRM016 names {AGR_SAME!r}, a single-counterparty agreement "
        f"that crosses no boundary: {message!r}"
    )


@pytest.mark.parametrize("regime_key", list(_REGIMES))
def test_all_six_portfolio_exposures_reach_the_templates(regime_key: str) -> None:
    """The six designed rows survive the pipeline in both regimes.

    A swallowed deposit row would silently shrink the netting pool without failing
    the golden gate on its own — the remaining loans would still net a smaller,
    internally consistent amount — so the row count is pinned explicitly.

    Arrange: the netting portfolio.
    Act:     run the pipeline under one regime.
    Assert:  six rows, all of ``exposure_type`` "loan" (deposits are negative
             drawn loans, CRR Art. 195/219), and every designed reference present.
    """
    # Arrange + Act
    df = _run(regime_key).results.collect()

    # Assert
    assert df.height == 6, regime_key
    counts = dict(df["exposure_type"].value_counts().iter_rows())
    assert counts == {"loan": 6}, regime_key
    assert {DEP_A, DEP_D, *EXPECTED_NETTING} <= set(df["exposure_reference"]), regime_key
