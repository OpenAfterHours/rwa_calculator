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
- ``boe_b0739`` (OF 08.01/03, live): expected loss is consistent across the
  templates after substitution.

References:
- CRR Art. 235 (risk-weight substitution), Art. 161 (IRB parameter substitution)
- COREP Annex II, C 07.00 / C 08.01: "Exposures stemming from possible in- and
  outflows from and to other templates shall be taken into account."
- EBA Q&A 2017_3509: C 08.01/02 c0280 includes CRM with substitution effects.
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
from rwa_calc.reporting.corep.templates import C08_03_PD_PARENT_REFS

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
    (template, class) as an inflow — driven generically off
    ``SUBSTITUTION_INFLOW_DESIGN`` so an eighth scenario added to the fixture
    is covered without a code change here.

    Two or more scenarios may legitimately share one destination (S1 and S7
    both land on institution/C 08.01 — see the fixture module docstring), so
    the assertion is grouped by (template, class) and compares the sheet's
    inflow cell against the SUM of every scenario's ``guaranteed_amount``
    that the design table maps to that destination — not any single
    scenario's amount in isolation. "Lands once" is still enforced by that
    grouping, not diluted by it: the comparison is exact equality against the
    sum of ONLY the entries recorded for that one destination, so it still
    fails if a leg's inflow lands on the wrong sheet (its true destination's
    sum comes up short), lands twice (its destination's sum comes up long —
    equality, not `>=`, catches this), or never lands at all (its
    destination's sum comes up short, including a destination with exactly
    one design entry, which is the original one-to-one case degenerating out
    of the general grouped one)."""

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_destination_inflow_equals_the_guaranteed_amount(self, regime_key: str) -> None:
        _results, corep = _run(regime_key)

        destination_totals: dict[tuple[str, str], float] = {}
        for design in SUBSTITUTION_INFLOW_DESIGN.values():
            key = (design["destination_template"], design["destination_class"])
            destination_totals[key] = destination_totals.get(key, 0.0) + design["guaranteed_amount"]

        for (template, dest_class), expected_amount in destination_totals.items():
            _gross_ref, _outflow_ref, inflow_ref, _net_ref = _TEMPLATE_COLS[template]

            sheets = _sheets(corep, template)
            assert dest_class in sheets, (
                f"{regime_key}: no {template} sheet for destination class "
                f"{dest_class!r} — the inflow has nowhere to land"
            )
            total = _total_row(sheets[dest_class])
            assert total[inflow_ref][0] == pytest.approx(expected_amount), (
                f"{regime_key}: {template}[{dest_class}] col {inflow_ref} expected "
                f"{expected_amount} (sum of every scenario mapped to this destination "
                f"in SUBSTITUTION_INFLOW_DESIGN), got {total[inflow_ref][0]}"
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


class TestC0803PostCrmBasis:
    """C 08.03 keeps gross on the obligor but moves EAD/RWEA/EL to IRB guarantors."""

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_leaf_pd_ranges_reconcile_to_c0801_by_post_crm_class(self, regime_key: str) -> None:
        """C 08.03 post-CRM measures equal C 08.01's non-slotting row per sheet."""
        results, corep = _run(regime_key)

        assert set(corep.c08_03) == {"corporate", "institution", "retail_other"}
        for exposure_class, c08_03 in corep.c08_03.items():
            leaves = c08_03.filter(~pl.col("row_ref").is_in(list(C08_03_PD_PARENT_REFS)))
            c08_01 = corep.c08_01[exposure_class].filter(pl.col("row_ref") == "0070")
            c08_02 = corep.c08_02[exposure_class]
            post_legs = results.filter(
                pl.col("reporting_approach").is_in(["foundation_irb", "advanced_irb"])
                & (pl.col("reporting_class") == exposure_class)
            )

            assert leaves["0040"].sum() == pytest.approx(c08_01["0110"][0])
            assert leaves["0090"].sum() == pytest.approx(c08_01["0260"][0])
            assert leaves["0100"].sum() == pytest.approx(c08_01["0280"][0])
            assert c08_02["0280"].sum() == pytest.approx(c08_01["0280"][0])
            assert leaves["0100"].sum() == pytest.approx(
                post_legs["expected_loss"].fill_null(0.0).sum()
            )

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_destination_only_retail_sheet_has_post_values_but_no_origin_gross(
        self, regime_key: str
    ) -> None:
        """S2's 3.3m covered leg creates a retail guarantor sheet, not retail gross."""
        _results, corep = _run(regime_key)
        leaves = corep.c08_03["retail_other"].filter(
            ~pl.col("row_ref").is_in(list(C08_03_PD_PARENT_REFS))
        )

        assert leaves["0010"].sum() + leaves["0020"].sum() == pytest.approx(0.0)
        assert leaves["0040"].sum() == pytest.approx(3_300_000.0)
        assert leaves["0100"].sum() > 0.0

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_el_shortfall_and_excess_are_recomputed_from_post_crm_el(self, regime_key: str) -> None:
        """The real pipeline's Art. 159 carriers use the substituted EL."""
        results, _corep = _run(regime_key)
        irb = results.filter(pl.col("expected_loss").is_not_null()).with_columns(
            (
                pl.col("provision_allocated").fill_null(0.0)
                + pl.col("ava_amount").fill_null(0.0)
                + pl.col("other_own_funds_reductions").fill_null(0.0)
            ).alias("pool_b")
        )

        expected_shortfall = (pl.col("expected_loss") - pl.col("pool_b")).clip(lower_bound=0.0)
        expected_excess = (pl.col("pool_b") - pl.col("expected_loss")).clip(lower_bound=0.0)
        assert irb["el_shortfall"].to_list() == pytest.approx(
            irb.select(expected_shortfall)["expected_loss"].to_list()
        )
        assert irb["el_excess"].to_list() == pytest.approx(
            irb.select(expected_excess)["pool_b"].to_list()
        )

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_destination_pd_uses_guarantor_parameter_in_origin_obligor_band(
        self, regime_key: str
    ) -> None:
        """The row stays on borrower PD, while col0050 reports effective guarantor PD."""
        _results, corep = _run(regime_key)

        s1_band = corep.c08_03["institution"].filter(pl.col("row_ref") == "0060")
        s2_band = corep.c08_03["retail_other"].filter(pl.col("row_ref") == "0060")
        assert s1_band["0040"][0] == pytest.approx(2_000_000.0)
        assert s1_band["0050"][0] == pytest.approx(0.003)
        assert s2_band["0040"][0] == pytest.approx(3_300_000.0)
        assert s2_band["0050"][0] == pytest.approx(0.020)

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_retail_maturity_is_not_reported(self, regime_key: str) -> None:
        """Annex II excludes maturity from every retail exposure-class sheet."""
        _results, corep = _run(regime_key)
        assert corep.c08_03["retail_other"]["0080"].null_count() == len(
            corep.c08_03["retail_other"]
        )


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
