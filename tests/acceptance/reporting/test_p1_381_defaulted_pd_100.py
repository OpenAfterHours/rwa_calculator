"""
P1.381 - a defaulted IRB obligor carries a PD of 100% and is reported in the 100% PD row.

Pipeline position:
    registered portfolio (``irb-classes``; ``crm-substitution`` with one obligor
    put into default) -> PipelineOrchestrator -> COREPGenerator / Pillar3Generator

The defect: the engine overrode K, RWEA and EL for a defaulted IRB leg but never
its PD, so ``IRC-LN-RRE-DEF`` (obligor in default, internal PD 0.6%) carried
``pd = pd_floored = 0.006`` on the sealed ledger. Every template that bands or
averages a PD then reported it as a performing 0.6% obligor: C / OF 08.03 and
08.05 put it in row 0060 and never emitted row 0170, C / OF 08.02 pooled it into
the "0.50% - 0.75%" band, and C / OF 08.01 column 0010, C / OF 09.02 column 0080
and Pillar 3 CR6 / CR9 column f averaged it in at 0.6%.

The rule (both regimes, one wording):

- PS1/26 Art. 160(3): "An institution shall use a PD of 100% for obligors in
  default." Art. 163(2): the retail twin, "or ... for exposures in default".
- CRR Art. 160(3): "The PD of obligors in default shall be 100 %."; Art. 163(2).
- CRR / PS1/26 Annex II, C / OF 08.03 and 08.05 rows: "All defaulted exposures
  shall be included in the bucket representing PD of 100%." C / OF 08.02 rows:
  "PD of obligors in default shall be 100%."

The 100% is the PD itself, not a floor, so Basel 3.1 needs it on BOTH bases: the
pre-input-floor ``pd`` its OF 08.03 / 08.05 row axis is stated on, and the
post-input-floor ``pd_floored`` its averages report. The firm's own estimate
stays on ``internal_pd``.

Every assertion below is absolute. ``irb-classes``' retail-mortgage sheet holds
the defaulted leg beside two performing legs at the same PD (the two-leg control
LESSONS B5 asks for), so a fix that drops the defaulted leg, or one that zeroes
the sheet, cannot pass. The ``crm-substitution`` limb runs the IRB guarantee
stage, which reseals the post-CRM PD carriers; ``irb-classes`` has no guarantee
input, so the stage returns early there and those carriers are absent.

Capital does not move: K, RWEA and EL already came from the default flag.

References:
- PRA PS1/26 Art. 160(3), Art. 163(2); CRR Art. 160(3), Art. 163(2)
- CRR Annex II C 08.02 / 08.03 / 08.05 row instructions; PS1/26 Annex II
  OF 08.02 / 08.03 / 08.05 row instructions
- PS1/26 Annex XXII CR6 / CR9 column f
- tests/fixtures/reporting_irb_classes_portfolio.py (``LN_RRE_DEF``)
"""

from __future__ import annotations

from functools import cache
from typing import NamedTuple

import polars as pl
import pytest
from tests.acceptance.reporting.test_supervisory_validations import _irb_config
from tests.fixtures.raw_bundle import make_raw_bundle
from tests.fixtures.reporting_crm_substitution_portfolio import (
    OB_S1,
    build_reporting_crm_substitution_bundle,
)
from tests.fixtures.reporting_irb_classes_portfolio import (
    BEEL_RRE_DEF,
    DRAWN_QRRE,
    DRAWN_RRE,
    DRAWN_RRE_DEF,
    DRAWN_RRE_FLOOR,
    LN_RRE,
    LN_RRE_DEF,
    LN_RRE_FLOOR,
    PD_QRRE,
    PD_RRE,
    build_reporting_irb_classes_bundle,
)

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.edges import RAW_TABLE_EDGES
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator, COREPTemplateBundle
from rwa_calc.reporting.corep.pd_scale import pd_band_col
from rwa_calc.reporting.pillar3.generator import Pillar3Generator, Pillar3TemplateBundle

# =============================================================================
# Constants
# =============================================================================

REGIMES: tuple[str, ...] = ("CRR", "BASEL_3_1")

#: The C / OF 08.0x sheet the retail-mortgage legs land on, per regime.
RRE_SHEET: dict[str, str] = {
    "CRR": "retail_mortgage",
    "BASEL_3_1": "retail_residential_re_non_sme_airb",
}

#: The C / OF 09.02 row the retail-mortgage legs land on, per regime.
C09_02_RRE_ROW: dict[str, str] = {"CRR": "0070", "BASEL_3_1": "0072"}

#: Art. 160(3) / 163(2): the PD of an obligor in default.
PD_DEFAULT: float = 1.0

#: The defaulted leg's exposure value, and its EL (A-IRB: BEEL x EAD, Art. 158(5)).
EAD_DEFAULTED: float = DRAWN_RRE_DEF
EL_DEFAULTED: float = BEEL_RRE_DEF * DRAWN_RRE_DEF

#: The two performing legs that share the sheet and the obligor grade.
EAD_PERFORMING: float = DRAWN_RRE + DRAWN_RRE_FLOOR

#: The exposure-weighted PD of the three retail-mortgage legs, the defaulted one at 100%.
RRE_AVERAGE_PD: float = (EAD_PERFORMING * PD_RRE + EAD_DEFAULTED * PD_DEFAULT) / (
    EAD_PERFORMING + EAD_DEFAULTED
)

ROW_DEFAULT: str = "0170"
ROW_PERFORMING: str = "0060"
C08_02_DEFAULT_ROW: str = "Default (100%)"
C08_02_PERFORMING_ROW: str = "0.50% - 0.75%"


class _Run(NamedTuple):
    results: pl.DataFrame
    corep: COREPTemplateBundle
    pillar3: Pillar3TemplateBundle


# =============================================================================
# irb-classes: the defaulted retail-mortgage leg
# =============================================================================


@pytest.mark.parametrize("framework", REGIMES)
def test_defaulted_irb_leg_carries_a_pd_of_100pct_on_both_bases(framework: str) -> None:
    """Art. 160(3) / 163(2): the sealed ledger carries PD 100% for the defaulted leg.

    Both the post-input-floor carrier (``pd_floored``) and the carrier the PD
    scale bands on (Basel 3.1: the pre-input-floor ``pd``; CRR: ``pd_floored``)
    read 1.0. The firm's own estimate survives on ``internal_pd``, and the
    performing legs on the same obligor grade keep theirs.
    """
    # Arrange
    run = _irb_classes(framework)
    _assert_adequate(run.results)
    leg = _leg(run.results, LN_RRE_DEF)
    band_carrier = pd_band_col(set(run.results.columns), framework)

    # Act
    carriers = {"pd": leg["pd"], "pd_floored": leg["pd_floored"], band_carrier: leg[band_carrier]}

    # Assert
    assert carriers == {"pd": PD_DEFAULT, "pd_floored": PD_DEFAULT, band_carrier: PD_DEFAULT}
    assert leg["internal_pd"] == pytest.approx(PD_RRE)
    for reference in (LN_RRE, LN_RRE_FLOOR):
        assert _leg(run.results, reference)["pd_floored"] == pytest.approx(PD_RRE)


@pytest.mark.parametrize("framework", REGIMES)
def test_defaulted_leg_capital_is_unchanged_by_the_pd(framework: str) -> None:
    """K, RWEA and EL come from the default flag, not the PD (Art. 153(1)(ii) /
    154(1)(i), Art. 158(5)): the A-IRB defaulted leg at LGD = BEEL keeps RWEA 0
    and EL = BEEL x EAD."""
    # Arrange
    run = _irb_classes(framework)

    # Act
    leg = _leg(run.results, LN_RRE_DEF)

    # Assert
    assert leg["ead_final"] == pytest.approx(EAD_DEFAULTED)
    assert leg["rwa_final"] == pytest.approx(0.0, abs=1e-9)
    assert leg["expected_loss"] == pytest.approx(EL_DEFAULTED)


@pytest.mark.parametrize("framework", REGIMES)
def test_c08_03_reports_the_defaulted_leg_in_the_100pct_row(framework: str) -> None:
    """C / OF 08.03: row 0170 holds the defaulted leg at PD 100%; row 0060 keeps
    the two performing legs. On Basel 3.1 the A-IRB Total sheet 0002 agrees."""
    # Arrange
    run = _irb_classes(framework)
    _assert_adequate(run.results)
    sheets = [RRE_SHEET[framework], *(("total_airb",) if framework == "BASEL_3_1" else ())]

    for sheet in sheets:
        # Act
        frame = run.corep.c08_03[sheet]

        # Assert
        default = _row(frame, ROW_DEFAULT)
        assert default["0010"] == pytest.approx(EAD_DEFAULTED), sheet
        assert default["0040"] == pytest.approx(EAD_DEFAULTED), sheet
        assert default["0050"] == pytest.approx(PD_DEFAULT), sheet
        assert default["0100"] == pytest.approx(EL_DEFAULTED), sheet
        performing = _row(frame, ROW_PERFORMING)
        assert performing["0040"] == pytest.approx(EAD_PERFORMING), sheet
        assert performing["0050"] == pytest.approx(PD_RRE), sheet


@pytest.mark.parametrize("framework", REGIMES)
def test_c08_05_reports_the_defaulted_obligor_in_the_100pct_row(framework: str) -> None:
    """C / OF 08.05: "All defaulted exposures shall be included in the bucket
    representing PD of 100%." Row 0170 counts the defaulted obligor at PD 100%;
    row 0060 keeps the two performing obligors and no default."""
    # Arrange
    run = _irb_classes(framework)
    _assert_adequate(run.results)

    # Act
    frame = run.corep.c08_05[RRE_SHEET[framework]]

    # Assert
    default = _row(frame, ROW_DEFAULT)
    assert (default["0010"], default["0020"], default["0030"]) == pytest.approx((1.0, 1.0, 1.0))
    performing = _row(frame, ROW_PERFORMING)
    assert (performing["0010"], performing["0020"], performing["0030"]) == pytest.approx(
        (PD_RRE, 2.0, 0.0)
    )


@pytest.mark.parametrize("framework", REGIMES)
def test_c08_02_reports_the_defaulted_leg_on_a_default_row(framework: str) -> None:
    """C / OF 08.02: "PD of obligors in default shall be 100%". The defaulted leg
    leaves the performing 0.50% - 0.75% band for the default row, at PD 100%."""
    # Arrange
    run = _irb_classes(framework)
    _assert_adequate(run.results)

    # Act
    frame = run.corep.c08_02[RRE_SHEET[framework]]

    # Assert
    assert frame["row_ref"].to_list() == [C08_02_PERFORMING_ROW, C08_02_DEFAULT_ROW]
    default = _row(frame, C08_02_DEFAULT_ROW)
    assert (default["0010"], default["0110"]) == pytest.approx((PD_DEFAULT, EAD_DEFAULTED))
    performing = _row(frame, C08_02_PERFORMING_ROW)
    assert (performing["0010"], performing["0110"]) == pytest.approx((PD_RRE, EAD_PERFORMING))


@pytest.mark.parametrize("framework", REGIMES)
def test_c08_01_average_pd_includes_the_defaulted_leg_at_100pct(framework: str) -> None:
    """C / OF 08.01 column 0010: the exposure-weighted average PD of the sheet's
    legs, the defaulted one at 100%. Basel 3.1's A-IRB Total also holds QRRE."""
    # Arrange
    run = _irb_classes(framework)
    _assert_adequate(run.results)
    expected = {RRE_SHEET[framework]: RRE_AVERAGE_PD}
    if framework == "BASEL_3_1":
        expected["total_airb"] = (
            EAD_PERFORMING * PD_RRE + EAD_DEFAULTED * PD_DEFAULT + DRAWN_QRRE * PD_QRRE
        ) / (EAD_PERFORMING + EAD_DEFAULTED + DRAWN_QRRE)

    # Act
    reported = {sheet: _row(run.corep.c08_01[sheet], "0010")["0010"] for sheet in expected}

    # Assert
    assert reported == pytest.approx(expected)


@pytest.mark.parametrize("framework", REGIMES)
def test_c09_02_average_pd_includes_the_defaulted_leg_at_100pct(framework: str) -> None:
    """C / OF 09.02 column 0080 on the residential-mortgage row of the Total
    country sheet: the exposure-weighted PD, the defaulted leg at 100%."""
    # Arrange
    run = _irb_classes(framework)
    _assert_adequate(run.results)

    # Act
    reported = _row(run.corep.c09_02["TOTAL"], C09_02_RRE_ROW[framework])["0080"]

    # Assert
    assert reported == pytest.approx(RRE_AVERAGE_PD)


@pytest.mark.parametrize("framework", REGIMES)
def test_cr6_reports_a_pd_of_100pct_on_the_default_row(framework: str) -> None:
    """Pillar 3 CR6 column f (exposure-weighted PD, in %): row 17 "100.00
    (Default)" reports 100, row 6 the performing 0.6, Total row 18 the blend."""
    # Arrange
    run = _irb_classes(framework)
    _assert_adequate(run.results)

    # Act
    frame = run.pillar3.cr6["retail_mortgage"]

    # Assert
    column_f = {ref: _row(frame, ref)["f"] for ref in ("6", "17", "18")}
    assert column_f == pytest.approx(
        {"6": PD_RRE * 100.0, "17": PD_DEFAULT * 100.0, "18": RRE_AVERAGE_PD * 100.0}
    )


def test_cr9_reports_a_pd_of_100pct_on_the_default_row() -> None:
    """Pillar 3 CR9 (Basel 3.1 only - the CRR estate has no CR9) columns f
    (exposure-weighted PD) and g (arithmetic average PD): row 17 reports 100."""
    # Arrange
    run = _irb_classes("BASEL_3_1")
    _assert_adequate(run.results)

    # Act
    default = _row(run.pillar3.cr9["advanced_irb - retail_rre_non_sme"], "17")

    # Assert
    assert (default["f"], default["g"]) == pytest.approx((100.0, 100.0))


# =============================================================================
# crm-substitution with OB_S1 in default: the post-CRM PD carriers
# =============================================================================


@pytest.mark.parametrize("framework", REGIMES)
def test_unsubstituted_defaulted_legs_carry_pd_100pct_on_the_post_crm_carriers(
    framework: str,
) -> None:
    """The IRB guarantee stage reseals ``reporting_pd_post_crm`` (post-input-floor)
    and ``reporting_pd_post_crm_pre_floor`` (the basis Basel 3.1's OF 08.03 post-CRM
    limb bands on) from the obligor's carriers on every leg that was not
    parameter-substituted. A defaulted obligor's legs must read 100% on both, and
    land in row 0170 of the obligor's C 08.03 sheet on the post-CRM columns too."""
    # Arrange
    run = _defaulted_crm_substitution(framework)
    legs = run.results.filter(pl.col("counterparty_reference") == OB_S1)
    assert {"reporting_pd_post_crm", "reporting_pd_post_crm_pre_floor"} <= set(legs.columns), (
        "the IRB guarantee stage did not run - the post-CRM carriers this test is for are absent"
    )
    assert legs.height >= 2, "OB_S1's loan is not split into guaranteed and retained legs"
    assert legs["is_defaulted"].all(), "OB_S1 is not in default - this test would prove nothing"
    unsubstituted = legs.filter(pl.col("guarantee_status") != "PD_PARAMETER_SUBSTITUTION")
    assert unsubstituted.height >= 1, "every OB_S1 leg was substituted - no carrier to check"

    # Act
    carriers = unsubstituted.select("reporting_pd_post_crm", "reporting_pd_post_crm_pre_floor")

    # Assert
    assert carriers.to_series(0).to_list() == [PD_DEFAULT] * unsubstituted.height
    assert carriers.to_series(1).to_list() == [PD_DEFAULT] * unsubstituted.height
    on_sheet = unsubstituted.filter(pl.col("reporting_class") == pl.col("reporting_class_origin"))
    sheet = _c08_03_sheet_of(run.corep, on_sheet["reporting_class_origin"][0], framework)
    default = _row(run.corep.c08_03[sheet], ROW_DEFAULT)
    assert default["0040"] == pytest.approx(float(on_sheet["ead_final"].sum()))
    assert default["0050"] == pytest.approx(PD_DEFAULT)


# =============================================================================
# Helpers
# =============================================================================


@cache
def _irb_classes(framework: str) -> _Run:
    """``irb-classes`` through one regime, with its COREP and Pillar 3 bundles."""
    return _run(build_reporting_irb_classes_bundle(), framework)


@cache
def _defaulted_crm_substitution(framework: str) -> _Run:
    """``crm-substitution`` with obligor ``OB_S1`` put into default (Art. 178)."""
    bundle = build_reporting_crm_substitution_bundle()
    counterparties = bundle.counterparties.with_columns(
        pl.when(pl.col("counterparty_reference") == OB_S1)
        .then(pl.lit(value=True))
        .otherwise(pl.col("default_status"))
        .alias("default_status")
    )
    return _run(_with_tables(bundle, counterparties=counterparties), framework)


def _run(bundle: RawDataBundle, framework: str) -> _Run:
    result = PipelineOrchestrator().run_with_data(bundle, _irb_config(framework))
    corep = COREPGenerator().generate_from_lazyframe(
        result.results,
        framework=framework,
        output_floor_summary=result.output_floor_summary,
    )
    pillar3 = Pillar3Generator().generate_from_lazyframe(result.results, framework=framework)
    return _Run(result.results.collect(), corep, pillar3)


def _with_tables(bundle: RawDataBundle, **tables: pl.LazyFrame) -> RawDataBundle:
    """Reseal ``bundle`` with some of its raw tables replaced."""
    frames = {name: getattr(bundle, name) for name in RAW_TABLE_EDGES}
    return make_raw_bundle(**{**frames, **tables}, ccr=bundle.ccr)


def _assert_adequate(results: pl.DataFrame) -> None:
    """The retail-mortgage sheet holds the defaulted leg beside two performing
    legs at the SAME obligor PD, so the band split is visible on one sheet."""
    assert _leg(results, LN_RRE_DEF)["is_defaulted"], "LN_RRE_DEF is no longer defaulted"
    for reference in (LN_RRE, LN_RRE_FLOOR):
        assert not _leg(results, reference)["is_defaulted"], f"{reference} is defaulted"
        assert _leg(results, reference)["internal_pd"] == pytest.approx(PD_RRE)
    assert _leg(results, LN_RRE_DEF)["internal_pd"] == pytest.approx(PD_RRE), (
        "the defaulted leg's own estimate no longer equals the performing legs' - "
        "the 0060 / 0170 split would no longer isolate the default"
    )


def _leg(results: pl.DataFrame, reference: str) -> dict:
    rows = results.filter(pl.col("exposure_reference") == reference)
    assert rows.height == 1, f"{reference}: expected one ledger row, found {rows.height}"
    return rows.row(0, named=True)


def _row(frame: pl.DataFrame, ref: str) -> dict:
    rows = frame.filter(pl.col("row_ref") == ref)
    assert rows.height == 1, f"row {ref} not emitted; rows are {frame['row_ref'].to_list()}"
    return rows.row(0, named=True)


def _c08_03_sheet_of(corep: COREPTemplateBundle, exposure_class: str, framework: str) -> str:
    """The C 08.03 sheet a class lands on: the class itself (CRR), else the one
    Basel 3.1 per-class sheet whose key starts with it."""
    if framework == "CRR":
        return exposure_class
    matches = [key for key in corep.c08_03 if key.startswith(exposure_class)]
    assert len(matches) == 1, f"{exposure_class}: C 08.03 sheets {list(corep.c08_03)}"
    return matches[0]
