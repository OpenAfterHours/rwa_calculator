"""
Acceptance: the QRRE multi-option-facility portfolio, end to end through COREP (P1.355).

Pipeline wired: ``build_reporting_qrre_mof_bundle`` -> ``PipelineOrchestrator`` ->
``COREPGenerator``. No mocking. The portfolio is registered in ``RUNS``
(``tests/acceptance/reporting/test_supervisory_validations.py``) under both
regimes, so the supervisory register, the registered goldens and the coverage
ratchets read the same book.

CRR Art. 154(4)(c) / PS1/26 Art. 147(5A)(c) cap the aggregate nominal exposure to
a single individual. Under a multi-option facility the per-individual figure is
capped at the umbrella's limit (P1.355): the MOVER's two 60,000 sub-limits under
its fully drawn 80,000 umbrella count 80,000, not 120,000, so its two loans leave
the other-retail sheet for the QRRE sheet of C 08.01 / OF 08.01. Before the fix
they reported as other retail, in both regimes.

The book is two-legged on both sheets (LESSONS B5): the HEADROOM obligor is QRRE
on both sides of the change and the two SHARED obligors are other retail on both
sides, so "the movers moved" is distinguishable from "a sheet was zeroed". Each
sheet's row 0010 is asserted as the sum of the legs designed for it — the
movers at their drawn amounts, which nothing but the class decides.

References:
- CRR Art. 154(4)(c) / PS1/26 Art. 147(5A)(c).
- tests/fixtures/reporting_qrre_mof_portfolio.py: the book and its arithmetic.
"""

from __future__ import annotations

import polars as pl
import pytest
from tests.acceptance.reporting.test_supervisory_validations import _irb_config
from tests.fixtures.reporting_qrre_mof_portfolio import (
    HEADROOM_ROOT_LIMIT,
    HEADROOM_SUB_LIMIT,
    MOVER_DRAWN,
    MOVER_ROOT_LIMIT,
    MOVER_SUB_LIMIT,
    MOVERS,
    OTHER_SURVIVORS,
    QRRE_SURVIVORS,
    SHARED_OWN_LIMIT,
    SHARED_ROOT_LIMIT,
    SHARED_SUB_LIMIT,
    build_reporting_qrre_mof_bundle,
)

from rwa_calc.domain.enums import ExposureClass
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.engine.thresholds import regulatory_threshold
from rwa_calc.reporting.corep.generator import COREPGenerator
from rwa_calc.rulebook import RulepackV0

_QRRE = ExposureClass.RETAIL_QRRE.value
_RETAIL_OTHER = ExposureClass.RETAIL_OTHER.value

#: The C 08.01 / OF 08.01 sheet each retail sub-class reports on, per framework
#: (BoE Banking Taxonomy v4.1.1 for Basel 3.1: OF 08.01 sheets 0015 / 0017).
_SHEETS: dict[str, dict[str, str]] = {
    "CRR": {_QRRE: "retail_qrre", _RETAIL_OTHER: "retail_other"},
    "BASEL_3_1": {_QRRE: "retail_qrre_airb", _RETAIL_OTHER: "retail_other_non_sme_airb"},
}

#: The legs each sheet must hold after the fix.
_DESIGNED: dict[str, tuple[str, ...]] = {
    _QRRE: (*MOVERS, *QRRE_SURVIVORS),
    _RETAIL_OTHER: OTHER_SURVIVORS,
}


@pytest.fixture(scope="module", params=["CRR", "BASEL_3_1"])
def run(request: pytest.FixtureRequest) -> tuple[str, float, pl.DataFrame, dict[str, pl.DataFrame]]:
    """One pipeline run, its QRRE ceiling and its C 08.01 sheets, per framework."""
    framework: str = request.param
    config = _irb_config(framework)
    result = PipelineOrchestrator().run_with_data(build_reporting_qrre_mof_bundle(), config)
    corep = COREPGenerator().generate_from_lazyframe(
        result.results, framework=framework, output_floor_summary=result.output_floor_summary
    )
    pack = RulepackV0.from_config(config).pack
    ceiling = float(regulatory_threshold(pack, "qrre_max_limit", config.eur_gbp_rate))
    return framework, ceiling, result.results.collect(), corep.c08_01


def _total_row(c08_01: dict[str, pl.DataFrame], sheet: str) -> dict[str, object]:
    assert sheet in c08_01, f"C 08.01 sheet {sheet!r} not emitted; got {sorted(c08_01)}"
    rows = c08_01[sheet].filter(pl.col("row_ref") == "0010")
    assert rows.height == 1, sheet
    return rows.row(0, named=True)


def _legs(df: pl.DataFrame, refs: tuple[str, ...]) -> pl.DataFrame:
    legs = df.filter(pl.col("exposure_reference").is_in(refs))
    assert sorted(legs["exposure_reference"]) == sorted(refs), "a designed leg is missing"
    return legs


def test_the_book_straddles_the_pack_ceiling_as_designed(
    run: tuple[str, float, pl.DataFrame, dict[str, pl.DataFrame]],
) -> None:
    """Adequacy (LESSONS C11): the mover is over the ceiling counted sub-limit by
    sub-limit and within it capped at its umbrella; the HEADROOM obligor is
    within it capped; each SHARED owner is over it correctly counted and within
    it on the standalone revolver alone (what a cap pooled across the owners
    would leave one of them)."""
    # Arrange
    _, ceiling, _, _ = run

    # Assert
    assert MOVER_ROOT_LIMIT <= ceiling < 2 * MOVER_SUB_LIMIT
    assert HEADROOM_ROOT_LIMIT <= ceiling < HEADROOM_SUB_LIMIT + 2 * HEADROOM_ROOT_LIMIT
    assert SHARED_OWN_LIMIT <= ceiling < min(SHARED_ROOT_LIMIT, SHARED_SUB_LIMIT) + SHARED_OWN_LIMIT


@pytest.mark.parametrize("exposure_class", [_QRRE, _RETAIL_OTHER])
def test_each_leg_is_advanced_irb_in_its_designed_class(
    run: tuple[str, float, pl.DataFrame, dict[str, pl.DataFrame]], exposure_class: str
) -> None:
    """The movers are QRRE (FAILS PRE-FIX: other retail); the survivors are in
    their class on both sides. Every leg is A-IRB, so it reaches a C 08.01 sheet."""
    # Arrange
    _, _, df, _ = run

    # Act
    legs = _legs(df, _DESIGNED[exposure_class])

    # Assert
    assert set(legs["exposure_class"]) == {exposure_class}
    assert set(legs["approach"]) == {"advanced_irb"}


def test_the_movers_are_reported_at_their_drawn_amounts(
    run: tuple[str, float, pl.DataFrame, dict[str, pl.DataFrame]],
) -> None:
    """The movers' exposure value is their drawn balance (a fully drawn umbrella
    has no headroom), so the QRRE sheet's figure below is anchored absolutely."""
    # Arrange
    _, _, df, _ = run

    # Act
    movers = _legs(df, MOVERS)

    # Assert
    assert movers["ead_final"].to_list() == pytest.approx([MOVER_DRAWN] * len(MOVERS), rel=1e-12)


@pytest.mark.parametrize("exposure_class", [_QRRE, _RETAIL_OTHER])
def test_c08_01_exposure_value_is_the_designed_legs(
    run: tuple[str, float, pl.DataFrame, dict[str, pl.DataFrame]], exposure_class: str
) -> None:
    """Row 0010 col 0110 of each retail sheet sums exactly the legs designed for
    it. FAILS PRE-FIX on both sheets: the movers' 80,000 sit on the other-retail
    sheet there."""
    # Arrange
    framework, _, df, c08_01 = run
    legs = _legs(df, _DESIGNED[exposure_class])

    # Act
    total = _total_row(c08_01, _SHEETS[framework][exposure_class])

    # Assert
    assert total["0110"] == pytest.approx(float(legs["ead_final"].sum()), rel=1e-12)


@pytest.mark.parametrize("exposure_class", [_QRRE, _RETAIL_OTHER])
def test_c08_01_rwea_is_the_designed_legs(
    run: tuple[str, float, pl.DataFrame, dict[str, pl.DataFrame]], exposure_class: str
) -> None:
    """Row 0010 col 0260 (RWEA) follows the legs. FAILS PRE-FIX."""
    # Arrange
    framework, _, df, c08_01 = run
    legs = _legs(df, _DESIGNED[exposure_class])

    # Act
    total = _total_row(c08_01, _SHEETS[framework][exposure_class])

    # Assert
    assert total["0260"] == pytest.approx(float(legs["rwa_final"].sum()), rel=1e-9)


@pytest.mark.parametrize("exposure_class", [_QRRE, _RETAIL_OTHER])
def test_both_retail_sheets_stay_live(
    run: tuple[str, float, pl.DataFrame, dict[str, pl.DataFrame]], exposure_class: str
) -> None:
    """Green on both sides (LESSONS B5): each sheet keeps a survivor, so a change
    that zeroed one is not mistaken for one that moved the movers."""
    # Arrange
    framework, _, _, c08_01 = run

    # Act
    total = _total_row(c08_01, _SHEETS[framework][exposure_class])

    # Assert
    assert total["0110"] > 0.0
    assert total["0260"] > 0.0
