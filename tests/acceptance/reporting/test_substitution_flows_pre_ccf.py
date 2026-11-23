"""
Substitution flows of a covered undrawn amount are booked PRE-conversion-factor.

Pipeline position:
    build_reporting_offbs_substitution_bundle() -> PipelineOrchestrator
        -> AggregatedResultBundle -> COREPGenerator -> C 07.00 / C 08.01

Why this exists: Annex II defines every substitution flow as "the covered part of
the Original Exposure pre-conversion factors" — CRR C 07.00 cols 0090-0100 (p.88)
and C 08.01 cols 0070-0080 (p.100); PS1/26 OF 07.00 cols 0050-0100 (pp.83-84) and
OF 08.01 cols 0040-0080 (pp.103-104), which add "institutions shall separate each
exposure, prior to the application of conversion factors, into a covered part and
an uncovered part". The templates booked the engine's ``guaranteed_portion`` —
the covered EXPOSURE VALUE, i.e. after the factor — beside a pre-conversion col
0010 / 0020, so wherever the covered part included an undrawn amount the
pre-conversion waterfall mixed two bases, and the C 07.00 conversion-factor
breakdown no longer added up to the col 0150 it breaks down.

The portfolio (``tests/fixtures/reporting_offbs_substitution_portfolio.py``) holds
one committed facility per route — F-IRB obligor with an SA guarantor (the
cross-approach case), SA with SA, F-IRB with an IRB guarantor — plus a drawn,
part-collateralised control loan whose flows must NOT move. Each route is asserted
under BOTH regimes separately (LESSONS C7): under CRR the cross-approach leg's
covered part is converted at the SA 50% against the obligor's F-IRB 75%, which is
a second defect the Basel 3.1 run cannot show (Basel 3.1 F-IRB takes the SA factor
anyway).

Expected figures are stated from the fixture's own constants: a flow is the
covered fraction times the leg's limit-minus-drawn (off) or drawn (on) amount.

References:
- CRR Annex II C 07.00 cols 0090/0100, 0150-0200; C 08.01 cols 0020, 0040-0090
- PRA PS1/26 Annex II OF 07.00 cols 0050-0200; OF 08.01 cols 0040-0090
- Published rules: v6364_m / v0308_m (CRR C 07.00), boe_b0471 (OF 07.00)
"""

from __future__ import annotations

import functools
from datetime import date

import polars as pl
import pytest
from tests.fixtures.reporting_offbs_substitution_portfolio import (
    CTRL_COVER,
    CTRL_DRAWN,
    FACILITY_ROUTES,
    ROUTE_CTRL,
    ROUTE_IRBIRB,
    ROUTE_IRBSA,
    ROUTE_SASA,
    build_reporting_offbs_substitution_bundle,
    covered_pre_ccf,
    loan,
)

from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator, COREPTemplateBundle
from rwa_calc.reporting.filing.checks import evaluate_all
from rwa_filer.validate.evaluate import STATUS_FAIL

_REGIMES: dict[str, str] = {"crr": "CRR", "b31": "BASEL_3_1"}

#: The obligors' and the IRB guarantor's C 08.01 sheets, per regime. Under Basel
#: 3.1 a GBP 600m-revenue corporate is a large corporate (OF 08.01 sheet 0011).
_IRB_OBLIGOR_SHEET: dict[str, str] = {"crr": "corporate", "b31": "corporate_financial_large_firb"}
_IRB_GUARANTOR_SHEET: dict[str, str] = {"crr": "institution", "b31": "institution_firb"}

#: The C 07.00 conversion-factor columns and the factor each one stands for — the
#: published ``v0308_m`` (CRR) / ``boe_b0471`` (OF 07.00) weights are ``1 - factor``.
_CCF_COLUMNS: dict[str, dict[str, float]] = {
    "crr": {"0160": 0.0, "0170": 0.2, "0180": 0.5, "0190": 1.0},
    "b31": {"0160": 0.1, "0170": 0.2, "0171": 0.4, "0180": 0.5, "0190": 1.0},
}

#: The CTRL loan's covered exposure value: its cash collateral is recognised
#: first, so the guarantee covers 40% of the 350,000 that remains.
_CTRL_COVERED: float = 140_000.0


def _config(regime_key: str) -> CalculationConfig:
    """The ``RUNS`` IRB configs (``test_supervisory_validations._irb_config``)."""
    if regime_key == "crr":
        return CalculationConfig.crr(
            reporting_date=date(2025, 12, 31), permission_mode=PermissionMode.IRB
        )
    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 1),
        permission_mode=PermissionMode.IRB,
        enforce_retail_granularity=False,
    )


@functools.cache
def _run(regime_key: str) -> tuple[pl.DataFrame, COREPTemplateBundle]:
    """One pipeline run + COREP per regime, memoised. Treat the result as read-only."""
    result = PipelineOrchestrator().run_with_data(
        build_reporting_offbs_substitution_bundle(), _config(regime_key)
    )
    corep = COREPGenerator().generate_from_lazyframe(
        result.results,
        framework=_REGIMES[regime_key],
        output_floor_summary=result.output_floor_summary,
    )
    return result.results.collect(), corep


def _cell(sheet: pl.DataFrame, row: str, column: str) -> float:
    values = sheet.filter(pl.col("row_ref") == row)[column]
    assert len(values) == 1, f"row {row} is not on the sheet"
    value = values[0]
    assert value is not None, f"row {row} col {column} is empty"
    return float(value)


def _on_off(*routes: str) -> tuple[float, float]:
    """Summed (on, off) pre-conversion covered parts of the facility routes."""
    parts = [covered_pre_ccf(route) for route in routes]
    return sum(on for on, _ in parts), sum(off for _, off in parts)


class TestThePortfolioCanSeeTheBasis:
    """Adequacy first (LESSONS C11): every route's covered undrawn leg is beneficially
    substituted and carries a conversion factor below 100%, so its covered exposure
    value and its covered pre-conversion amount differ."""

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    @pytest.mark.parametrize("route", list(FACILITY_ROUTES))
    def test_covered_undrawn_leg_differs_on_the_two_bases(
        self, regime_key: str, route: str
    ) -> None:
        results, _corep = _run(regime_key)
        legs = results.filter(
            pl.col("exposure_reference").str.contains(f"OBS-FAC-{route}_UNDRAWN__G_")
        )
        assert legs.height == 1, f"{regime_key}/{route}: no covered undrawn leg"
        leg = legs.row(0, named=True)

        _on, off = covered_pre_ccf(route)
        assert leg["is_guarantee_beneficial"] is True
        assert leg["reporting_gross_off_bs"] == pytest.approx(off)
        assert 0.0 < leg["guaranteed_portion"] < off, (
            f"{regime_key}/{route}: covered EAD equals the pre-conversion amount - "
            "this file would prove nothing"
        )

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_control_leg_is_collateralised_below_its_gross(self, regime_key: str) -> None:
        """The CTRL leg's covered EAD sits below its covered gross, so a flow sized
        as a share of the gross would move it; one that only undoes a conversion
        factor would not."""
        results, _corep = _run(regime_key)
        leg = results.filter(
            pl.col("exposure_reference").str.starts_with(f"{loan(ROUTE_CTRL)}__G_")
        ).row(0, named=True)

        assert leg["reporting_gross_on_bs"] == pytest.approx(CTRL_DRAWN * CTRL_COVER)
        assert leg["guaranteed_portion"] == pytest.approx(_CTRL_COVERED)


class TestIrbTemplateBooksPreConversionFlows:
    """C 08.01: the obligor sheet's outflow and the IRB guarantor's inflow."""

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    @pytest.mark.parametrize(("row", "side"), [("0010", "total"), ("0020", "on"), ("0030", "off")])
    def test_obligor_outflow_is_the_covered_part_pre_conversion(
        self, regime_key: str, row: str, side: str
    ) -> None:
        """Cols 0040 and 0070 deduct 0.7 x 1,000,000 + 0.8 x 1,100,000 = 1,580,000."""
        _results, corep = _run(regime_key)
        sheet = corep.c08_01[_IRB_OBLIGOR_SHEET[regime_key]]
        on, off = _on_off(ROUTE_IRBSA, ROUTE_IRBIRB)
        expected = {"total": on + off, "on": on, "off": off}[side]

        assert _cell(sheet, row, "0040") == pytest.approx(-expected)
        assert _cell(sheet, row, "0070") == pytest.approx(-expected)

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_obligor_exposure_after_substitution_is_the_uncovered_gross(
        self, regime_key: str
    ) -> None:
        """Col 0090 = col 0020 less the pre-conversion outflow = the two facilities'
        uncovered limits, 0.3 x 1,000,000 + 0.2 x 1,100,000 = 520,000."""
        _results, corep = _run(regime_key)
        sheet = corep.c08_01[_IRB_OBLIGOR_SHEET[regime_key]]
        uncovered = sum(
            limit * (1.0 - cover)
            for route, (limit, _drawn, cover) in FACILITY_ROUTES.items()
            if route in (ROUTE_IRBSA, ROUTE_IRBIRB)
        )

        assert _cell(sheet, "0010", "0090") == pytest.approx(uncovered)

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    @pytest.mark.parametrize(("row", "side"), [("0010", "total"), ("0020", "on"), ("0030", "off")])
    def test_irb_guarantor_inflow_is_the_covered_part_pre_conversion(
        self, regime_key: str, row: str, side: str
    ) -> None:
        """The institution sheet's col 0080 receives 0.8 x 1,100,000 = 880,000."""
        _results, corep = _run(regime_key)
        sheet = corep.c08_01[_IRB_GUARANTOR_SHEET[regime_key]]
        on, off = _on_off(ROUTE_IRBIRB)
        expected = {"total": on + off, "on": on, "off": off}[side]

        assert _cell(sheet, row, "0080") == pytest.approx(expected)

    def test_b31_inflow_lands_on_its_conversion_factor_row(self) -> None:
        """OF 08.01 row 0033 (50%) carries the covered undrawn part it came from."""
        _results, corep = _run("b31")
        sheet = corep.c08_01[_IRB_GUARANTOR_SHEET["b31"]]
        _on, off = _on_off(ROUTE_IRBIRB)

        assert _cell(sheet, "0033", "0080") == pytest.approx(off)


class TestSaTemplateBooksPreConversionFlows:
    """C 07.00 corporates: SA-origin outflows and inflows from both templates."""

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    @pytest.mark.parametrize(("row", "side"), [("0010", "total"), ("0070", "on"), ("0080", "off")])
    def test_outflow_is_the_covered_part_pre_conversion(
        self, regime_key: str, row: str, side: str
    ) -> None:
        """Col 0090: SASA's 0.6 x 900,000 plus the control's 140,000 (on-balance)."""
        _results, corep = _run(regime_key)
        sheet = corep.c07_00["corporate"]
        on, off = _on_off(ROUTE_SASA)
        on += _CTRL_COVERED
        expected = {"total": on + off, "on": on, "off": off}[side]

        assert _cell(sheet, row, "0090") == pytest.approx(-expected)

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    @pytest.mark.parametrize(("row", "side"), [("0010", "total"), ("0070", "on"), ("0080", "off")])
    def test_inflow_is_the_covered_part_pre_conversion(
        self, regime_key: str, row: str, side: str
    ) -> None:
        """Col 0100: SASA and CTRL from this template, IRBSA's 700,000 from C 08.01."""
        _results, corep = _run(regime_key)
        sheet = corep.c07_00["corporate"]
        on, off = _on_off(ROUTE_SASA, ROUTE_IRBSA)
        on += _CTRL_COVERED
        expected = {"total": on + off, "on": on, "off": off}[side]

        assert _cell(sheet, row, "0100") == pytest.approx(expected)

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_cross_approach_leg_is_in_its_sa_conversion_factor_column(
        self, regime_key: str
    ) -> None:
        """Row 0080 col 0180 (50%) holds every off-balance leg on the sheet's post
        basis: SASA's covered 240,000 and uncovered 160,000 and IRBSA's covered
        280,000, which the engine converted at the SA 50% (CRR F-IRB: 75%)."""
        _results, corep = _run(regime_key)
        sheet = corep.c07_00["corporate"]
        _sasa_on, sasa_off = _on_off(ROUTE_SASA)
        _irbsa_on, irbsa_off = _on_off(ROUTE_IRBSA)
        limit, drawn, cover = FACILITY_ROUTES[ROUTE_SASA]
        sasa_uncovered_off = (limit - drawn) * (1.0 - cover)

        assert _cell(sheet, "0080", "0180") == pytest.approx(
            sasa_off + sasa_uncovered_off + irbsa_off
        )

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    @pytest.mark.parametrize("sheet_key", ["corporate", "total"])
    def test_off_balance_row_breaks_down_into_its_conversion_factors(
        self, regime_key: str, sheet_key: str
    ) -> None:
        """``v6364_m``: row 0080 ``{c0150} = {c0160} + ... + {c0190}``."""
        _results, corep = _run(regime_key)
        sheet = corep.c07_00[sheet_key]
        row = sheet.filter(pl.col("row_ref") == "0080")
        buckets = sum(float(row[ref][0] or 0.0) for ref in _CCF_COLUMNS[regime_key])

        assert _cell(sheet, "0080", "0150") == pytest.approx(buckets)

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    @pytest.mark.parametrize("sheet_key", ["corporate", "total"])
    @pytest.mark.parametrize("row_ref", ["0010", "0070", "0080"])
    def test_exposure_value_is_the_fully_adjusted_value_converted(
        self, regime_key: str, sheet_key: str, row_ref: str
    ) -> None:
        """``v0308_m`` / ``boe_b0471``: ``{c0200} = {c0150} - sum((1 - f) x bucket)``."""
        _results, corep = _run(regime_key)
        sheet = corep.c07_00[sheet_key]
        row = sheet.filter(pl.col("row_ref") == row_ref)
        reduction = sum(
            (1.0 - factor) * float(row[ref][0] or 0.0)
            for ref, factor in _CCF_COLUMNS[regime_key].items()
        )

        assert _cell(sheet, row_ref, "0200") == pytest.approx(
            _cell(sheet, row_ref, "0150") - reduction
        )


class TestPublishedRulesHold:
    """The rules the mixed basis broke report no failing C 07.00 coordinate."""

    @pytest.mark.parametrize(
        ("regime_key", "rule_id"),
        [("crr", "v6364_m"), ("crr", "v0308_m"), ("b31", "boe_b0471")],
    )
    def test_rule_has_no_failing_coordinate(self, regime_key: str, rule_id: str) -> None:
        _results, corep = _run(regime_key)
        report = evaluate_all(corep, None, _REGIMES[regime_key])
        outcome = next(o for o in report.outcomes if o.rule_id == rule_id)

        assert outcome.evaluated > 0, f"{rule_id} was not evaluated - vacuous"
        assert outcome.status != STATUS_FAIL, outcome.coordinates
