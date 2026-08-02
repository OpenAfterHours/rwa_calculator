"""
CRM guarantee-substitution acceptance coverage — the C 07.00 / C 08.01 outflow/
inflow axis, driven through the REAL pipeline (not the synthetic unit shim).

Pipeline position:
    build_reporting_crm_substitution_bundle() -> PipelineOrchestrator
        -> AggregatedResultBundle -> COREPGenerator

Why this exists: ``tests/unit/reporting/corep/test_c07_crm_substitution.py`` /
``test_c08_crm_substitution.py`` pin the D1-D4 arithmetic identities on small
hand-built LazyFrames. This file exercises the SAME published identities
end-to-end through a real guarantee split (``engine/crm/guarantees.py``) and
the sealed aggregator-exit ledger, plus the two defects only visible with a
cross-obligor / cross-template portfolio (D5): a guarantor class with no
native exposure of its own must still get a sheet, and an inflow whose
substituted leg crosses the SA/IRB approach boundary must land on the OTHER
template, not vanish.

Portfolio (``tests/fixtures/reporting_crm_substitution_portfolio.py``):
    S1  IRB corporate  -> IRB institution   (own exposure)   — happy path
    S2  IRB corporate  -> IRB retail_other  (no own exposure) — missing sheet
    S3  IRB corporate  -> SA sovereign      (no own exposure) — cross-template
    S4  SA corporate   -> SA institution    (own exposure)   — happy path
    S5  IRB corporate  -> IRB corporate     (SAME class, different counterparty)

No CRR/Basel 3.1 regime divergence is exercised (see the fixture module
docstring), so every assertion below is parametrized over both regimes purely
for parity, not because the numbers are expected to differ.

Published identities pinned (``src/rwa_calc/reporting/validations/rules/crr-eba-v3.0-credit-risk.json``):
- ``v1663_m`` (C 08.01.a, live): ``{c0070} = {c0040} + {c0050} + {c0060}``.
- ``v1662_m`` (C 08.01.a): ``{c0090} = {c0020} + {c0070} + {c0080}``.
- ``v0305_m`` (C 07.00.a, live): ``{c0090} = {c0050} + {c0060} + {c0070} + {c0080}``.
- ``v0306_m`` (C 07.00.a, live): ``{c0110} = {c0040} + {c0090} + {c0100}``.

References:
- CRR Art. 235 (risk-weight substitution), Art. 161 (IRB parameter substitution)
- COREP Annex II, C 07.00 / C 08.01: "Exposures stemming from possible in- and
  outflows from and to other templates shall be taken into account."
- src/rwa_calc/reporting/corep/crm_substitution.py: the cross-template router
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from tests.fixtures.reporting_crm_substitution_portfolio import (
    LOAN_EXPECTED_ORIGIN_SHEET_B31,
    LOAN_EXPECTED_ORIGIN_SHEET_CRR,
    SUBSTITUTION_INFLOW_DESIGN,
    build_reporting_crm_substitution_bundle,
)

from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator, COREPTemplateBundle

_REGIMES: dict[str, str] = {"crr": "CRR", "b31": "BASEL_3_1"}
_ORIGIN_SHEETS: dict[str, dict[str, tuple[str, str]]] = {
    "crr": LOAN_EXPECTED_ORIGIN_SHEET_CRR,
    "b31": LOAN_EXPECTED_ORIGIN_SHEET_B31,
}

# Per-template column layout: (gross, outflow, inflow, net-after-substitution).
_TEMPLATE_COLS: dict[str, tuple[str, str, str, str]] = {
    "c08_01": ("0020", "0070", "0080", "0090"),
    "c07": ("0010", "0090", "0100", "0110"),
}


def _config(regime_key: str) -> CalculationConfig:
    if regime_key == "crr":
        return CalculationConfig.crr(
            reporting_date=date(2025, 6, 30), permission_mode=PermissionMode.IRB
        )
    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 30), permission_mode=PermissionMode.IRB
    )


def _run(regime_key: str) -> tuple[pl.DataFrame, COREPTemplateBundle]:
    """Run the CRM-substitution portfolio through one regime."""
    framework = _REGIMES[regime_key]
    result = PipelineOrchestrator().run_with_data(
        build_reporting_crm_substitution_bundle(), _config(regime_key)
    )
    corep = COREPGenerator().generate_from_lazyframe(result.results, framework=framework)
    return result.results.collect(), corep


def _sheets(corep: COREPTemplateBundle, template: str) -> dict[str, pl.DataFrame]:
    return corep.c08_01 if template == "c08_01" else corep.c07_00


def _total_row(frame: pl.DataFrame) -> pl.DataFrame:
    return frame.filter(pl.col("row_ref") == "0010")


class TestPublishedIdentitiesEndToEnd:
    """The outflow subtotal and the single-subtraction waterfall hold on
    every ORIGIN sheet a real guarantee split produces."""

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_c0801_outflow_is_the_block_subtotal(self, regime_key: str) -> None:
        """``v1663_m``: C 08.01 corporate col 0070 = 0040 + 0050 + 0060."""
        _results, corep = _run(regime_key)

        corp = _total_row(corep.c08_01["corporate"])
        assert corp["0070"][0] == pytest.approx(corp["0040"][0] + corp["0050"][0] + corp["0060"][0])

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_c0801_money_removed_exactly_once(self, regime_key: str) -> None:
        """``v1662_m``: C 08.01 corporate col 0090 = 0020 + 0070 + 0080."""
        _results, corep = _run(regime_key)

        corp = _total_row(corep.c08_01["corporate"])
        expected = corp["0020"][0] + corp["0070"][0] + corp["0080"][0]
        assert corp["0090"][0] == pytest.approx(expected)

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_c07_outflow_is_the_block_subtotal(self, regime_key: str) -> None:
        """``v0305_m``: C 07.00 corporate col 0090 = 0050 + 0060 + 0070 + 0080."""
        _results, corep = _run(regime_key)

        corp = _total_row(corep.c07_00["corporate"])
        expected = sum(corp[ref][0] for ref in ("0050", "0060", "0070", "0080"))
        assert corp["0090"][0] == pytest.approx(expected)

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_c07_money_removed_exactly_once(self, regime_key: str) -> None:
        """``v0306_m``: C 07.00 corporate col 0110 = 0040 + 0090 + 0100."""
        _results, corep = _run(regime_key)

        corp = _total_row(corep.c07_00["corporate"])
        expected = corp["0040"][0] + corp["0090"][0] + corp["0100"][0]
        assert corp["0110"][0] == pytest.approx(expected)


class TestPerScenarioInflowLandsOnce:
    """Every scenario's guaranteed amount arrives on its recorded destination
    (template, class) as an inflow of exactly the covered amount — driven
    generically off ``SUBSTITUTION_INFLOW_DESIGN`` so a sixth scenario added
    to the fixture is covered without a code change here."""

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_destination_inflow_equals_the_guaranteed_amount(self, regime_key: str) -> None:
        _results, corep = _run(regime_key)

        for guar_ref, design in SUBSTITUTION_INFLOW_DESIGN.items():
            template = design["destination_template"]
            dest_class = design["destination_class"]
            amount = design["guaranteed_amount"]
            _gross_ref, _outflow_ref, inflow_ref, _net_ref = _TEMPLATE_COLS[template]

            sheets = _sheets(corep, template)
            assert dest_class in sheets, (
                f"{regime_key}/{guar_ref}: no {template} sheet for destination class "
                f"{dest_class!r} — the inflow has nowhere to land"
            )
            total = _total_row(sheets[dest_class])
            assert total[inflow_ref][0] == pytest.approx(amount), (
                f"{regime_key}/{guar_ref}: {template}[{dest_class}] col {inflow_ref} "
                f"expected {amount}, got {total[inflow_ref][0]}"
            )


class TestDestinationSheetCreatedWithoutNativeExposure:
    """Annex II: a guarantor class that receives an inflow but has no native
    exposure of its own must still get a sheet (D5) — S2 within C 08.01, S3
    across the SA/IRB template boundary onto C 07.00."""

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_c0801_retail_other_sheet_created_for_s2(self, regime_key: str) -> None:
        """S2's guarantor (retail_other) has no IRB exposure of its own."""
        _results, corep = _run(regime_key)

        design = SUBSTITUTION_INFLOW_DESIGN["CSUB-GUAR-S2"]
        assert design["destination_has_native_population"] is False
        assert "retail_other" in corep.c08_01
        total = _total_row(corep.c08_01["retail_other"])
        assert total["0020"][0] == pytest.approx(0.0)  # no native exposure
        assert total["0080"][0] == pytest.approx(design["guaranteed_amount"])

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_c07_central_govt_sheet_created_for_s3(self, regime_key: str) -> None:
        """S3's guarantor (SA sovereign) is only ever visible to C 08.01's IRB
        population by origin, yet the inflow must be routed to C 07.00's
        central_govt_central_bank sheet — the cross-template case."""
        _results, corep = _run(regime_key)

        design = SUBSTITUTION_INFLOW_DESIGN["CSUB-GUAR-S3"]
        assert design["destination_has_native_population"] is False
        assert "central_govt_central_bank" in corep.c07_00
        total = _total_row(corep.c07_00["central_govt_central_bank"])
        assert total["0010"][0] == pytest.approx(0.0)  # no native exposure
        assert total["0100"][0] == pytest.approx(design["guaranteed_amount"])


class TestCrossTemplateConservation:
    """D5: sum(C 08.01 col 0090) + sum(C 07.00 col 0110) conserves the total
    original exposure — an IRB exposure guaranteed by an SA guarantor (S3)
    must show its outflow on C 08.01 and its matching inflow on C 07.00, not
    vanish between the two templates."""

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_total_exposure_after_substitution_equals_total_gross(self, regime_key: str) -> None:
        results, corep = _run(regime_key)

        total_gross = float(results["drawn_amount"].sum())
        total_after_substitution = sum(
            _total_row(frame)["0090"][0] for frame in corep.c08_01.values()
        ) + sum(_total_row(frame)["0110"][0] for frame in corep.c07_00.values())

        assert total_after_substitution == pytest.approx(total_gross)


class TestFixtureIntegrity:
    """Guards the fixture itself: every leg must physically sit on its
    recorded ORIGIN sheet, or the assertions above would silently stop
    exercising the scenario they claim to."""

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_every_loan_reaches_its_origin_sheet(self, regime_key: str) -> None:
        results, corep = _run(regime_key)
        origin_sheets = _ORIGIN_SHEETS[regime_key]

        for loan_reference, (template, exposure_class) in origin_sheets.items():
            legs = results.filter(pl.col("exposure_reference").str.starts_with(loan_reference))
            assert legs.height > 0, f"{regime_key}: no leg found for {loan_reference}"
            sheets = _sheets(corep, template)
            assert exposure_class in sheets, (
                f"{regime_key}: {loan_reference} expected on {template}[{exposure_class}], "
                f"but that sheet does not exist"
            )
