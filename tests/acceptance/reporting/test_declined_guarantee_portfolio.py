"""
Acceptance: the declined-guarantee portfolio, end to end through COREP (P1.398).

Pipeline wired: ``build_reporting_declined_guarantee_bundle`` ->
``PipelineOrchestrator`` -> ``COREPGenerator``. No mocking.

The portfolio (``tests/fixtures/reporting_declined_guarantee_portfolio.py``) holds
three IRB obligors whose SA-routed guarantee the IRB stage DECLINES and one whose
guarantee it RECOGNISES. A declined guarantee is not recognised (CRR Art. 193(1)/
(3); PS1/26 Art. 193(2A)), so its legs keep the IRB exposure value of CRR
Art. 166(8)-(10) / PS1/26 Art. 166A-166D, and C 08.01 / OF 08.01 column 0110
reports that value. The recognised one keeps the SA conversion factor on its
covered part and books its substitution outflow (cols 0040 / 0070) — the leg that
must survive the fix.

Hand calculation of the exposure value per obligor (drawn + CCF x undrawn; the
covered share of the recognised obligor's undrawn amount at the SA 50%):

                 CRR own CCF   CRR exposure value   B31 own CCF   B31 exposure value
    DG-FIRB         75%            725,000              50%           650,000
    DG-AIRB         80%            680,000              80%           680,000
    DG-LC           20%            350,000              50%           425,000
    DG-KEPT         75%            830,000              50%           800,000
                                   (600,000 + 0.7 x 400,000 x 50% + 0.3 x 400,000 x own)

C 08.01 / OF 08.01 col 0110 then holds every IRB-retained part: all of the three
declined obligors plus DG-KEPT's uncovered 30% (600,000 x 0.3 + 0.3 x 400,000 x
own = 270,000 CRR / 240,000 Basel 3.1). Before the fix CRR col 0110 read
1,957,500 against 2,025,000 and the Basel 3.1 A-IRB sheet 627,500 against 680,000.
"""

from __future__ import annotations

import polars as pl
import pytest
from tests.acceptance.reporting.test_supervisory_validations import _irb_config
from tests.fixtures.reporting_declined_guarantee_portfolio import (
    CP_AIRB,
    CP_FIRB,
    CP_KEPT,
    CP_LC,
    DECLINED,
    LEGS,
    OBLIGORS,
    OWN_CCF,
    build_reporting_declined_guarantee_bundle,
    facility_reference,
    loan_reference,
)

from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator

_SA_MEDIUM_RISK_CCF: float = 0.50

#: Each obligor's own IRB conversion factor on its undrawn amount, per framework:
#: CRR Art. 166(8)(d) 75% / (b) 20% / own estimate; PS1/26 Art. 166C(1) (the
#: Table A1 factor) / Art. 166D(1)(a) (own estimate).
_OWN_CCF: dict[str, dict[str, float]] = {
    "CRR": {CP_FIRB: 0.75, CP_AIRB: OWN_CCF, CP_LC: 0.20, CP_KEPT: 0.75},
    "BASEL_3_1": {CP_FIRB: 0.50, CP_AIRB: OWN_CCF, CP_LC: 0.50, CP_KEPT: 0.50},
}

_DECLINED_STATUS = "GUARANTEE_NOT_APPLIED_NON_BENEFICIAL"


def _undrawn(obligor: str) -> float:
    _, drawn, limit, _, _ = LEGS[obligor]
    return limit - drawn


def _expected_exposure_value(framework: str, obligor: str) -> float:
    """Drawn + CCF x undrawn; a recognised guarantee's covered part at the SA factor."""
    _, drawn, _, cover, _ = LEGS[obligor]
    own = _OWN_CCF[framework][obligor]
    if obligor in DECLINED:
        return drawn + own * _undrawn(obligor)
    return drawn + _undrawn(obligor) * (cover * _SA_MEDIUM_RISK_CCF + (1.0 - cover) * own)


def _irb_retained(framework: str, obligor: str) -> float:
    """The part of the obligor's exposure value that stays on its IRB sheet."""
    if obligor in DECLINED:
        return _expected_exposure_value(framework, obligor)
    _, drawn, _, cover, _ = LEGS[obligor]
    return (1.0 - cover) * (drawn + _OWN_CCF[framework][obligor] * _undrawn(obligor))


@pytest.fixture(scope="module", params=["CRR", "BASEL_3_1"])
def run(request: pytest.FixtureRequest) -> tuple[str, pl.DataFrame, dict[str, pl.DataFrame]]:
    """One pipeline run and its C 08.01 sheets, per framework."""
    framework: str = request.param
    result = PipelineOrchestrator().run_with_data(
        build_reporting_declined_guarantee_bundle(), _irb_config(framework)
    )
    corep = COREPGenerator().generate_from_lazyframe(
        result.results, framework=framework, output_floor_summary=result.output_floor_summary
    )
    return framework, result.results.collect(), corep.c08_01


def _obligor_rows(df: pl.DataFrame, obligor: str) -> pl.DataFrame:
    stems = (facility_reference(obligor), loan_reference(obligor))
    return df.filter(
        pl.col("exposure_reference").str.starts_with(stems[0])
        | pl.col("exposure_reference").str.starts_with(stems[1])
    )


def test_the_portfolio_holds_the_population_it_exists_for(
    run: tuple[str, pl.DataFrame, dict[str, pl.DataFrame]],
) -> None:
    """Adequacy (LESSONS C11): three declined SA-routed off-BS legs, one recognised."""
    # Arrange
    _, df, _ = run
    covered = df.filter(pl.col("exposure_reference").str.contains("__G_"))

    # Act
    off_bs = covered.filter(pl.col("nominal_amount") > 0)

    # Assert
    assert set(covered["guarantor_approach"].to_list()) == {"sa"}
    assert off_bs.height == len(OBLIGORS)
    for obligor in OBLIGORS:
        statuses = set(_obligor_rows(covered, obligor)["guarantee_status"].to_list())
        expected = _DECLINED_STATUS if obligor in DECLINED else "SA_RW_SUBSTITUTION"
        assert statuses == {expected}, obligor


@pytest.mark.parametrize("obligor", OBLIGORS)
def test_each_obligor_carries_its_hand_calculated_exposure_value(
    run: tuple[str, pl.DataFrame, dict[str, pl.DataFrame]], obligor: str
) -> None:
    """Declined: the own IRB value. Recognised: the SA factor on the covered part."""
    # Arrange
    framework, df, _ = run

    # Act
    ead = float(_obligor_rows(df, obligor)["ead_final"].sum())

    # Assert
    assert ead == pytest.approx(_expected_exposure_value(framework, obligor), rel=1e-12)


def test_c08_01_exposure_value_reports_the_irb_retained_value(
    run: tuple[str, pl.DataFrame, dict[str, pl.DataFrame]],
) -> None:
    """Col 0110 on the obligor sheet(s) sums every IRB-retained part (Art. 166 / 166A-D)."""
    # Arrange
    framework, _, c08_01 = run
    if framework == "CRR":
        sheets = {"corporate": OBLIGORS}
    else:
        sheets = {
            "corporate_non_sme_firb": (CP_FIRB, CP_LC, CP_KEPT),
            "corporate_non_sme_airb": (CP_AIRB,),
        }

    for sheet, obligors in sheets.items():
        # Act
        total = c08_01[sheet].filter(pl.col("row_ref") == "0010")

        # Assert
        expected = sum(_irb_retained(framework, ob) for ob in obligors)
        assert total["0110"][0] == pytest.approx(expected, rel=1e-12), sheet


def test_only_the_recognised_guarantee_books_a_substitution_outflow(
    run: tuple[str, pl.DataFrame, dict[str, pl.DataFrame]],
) -> None:
    """Cols 0040 / 0070 carry DG-KEPT's covered exposure value and nothing else.

    A declined guarantee books no outflow (``reporting/corep/crm_substitution.py``
    gates on the beneficial flag), so the sheet's outflow is exactly the recognised
    covered part: 0.7 x (600,000 + 400,000 x 50%) = 560,000 in both regimes.
    """
    # Arrange
    framework, _, c08_01 = run
    sheet = "corporate" if framework == "CRR" else "corporate_non_sme_firb"
    _, drawn, _, cover, _ = LEGS[CP_KEPT]
    covered = cover * (drawn + _SA_MEDIUM_RISK_CCF * _undrawn(CP_KEPT))

    # Act
    total = c08_01[sheet].filter(pl.col("row_ref") == "0010")

    # Assert
    assert total["0070"][0] == pytest.approx(-covered, rel=1e-12)
    assert total["0040"][0] == pytest.approx(-covered, rel=1e-12)
