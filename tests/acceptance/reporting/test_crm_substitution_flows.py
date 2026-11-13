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

Published identities pinned (``packages/rwa-filer/src/rwa_filer/rules/data/crr-eba-v3.0-credit-risk.json``):
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

import functools
from datetime import date

import polars as pl
import pytest
from tests.fixtures.reporting_crm_substitution_portfolio import (
    B31_C08_01_DESTINATION_SHEET,
    LOAN_EXPECTED_ORIGIN_SHEET_B31,
    LOAN_EXPECTED_ORIGIN_SHEET_CRR,
    SUBSTITUTION_INFLOW_DESIGN,
    build_reporting_crm_substitution_bundle,
)

from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.c07 import c07_class_sheets
from rwa_calc.reporting.corep.c08_sheets import c08_class_sheets
from rwa_calc.reporting.corep.generator import COREPGenerator, COREPTemplateBundle
from rwa_calc.reporting.corep.templates import (
    C08_03_PD_PARENT_REFS,
    get_c08_03_pd_ranges,
)

_REGIMES: dict[str, str] = {"crr": "CRR", "b31": "BASEL_3_1"}
_ORIGIN_SHEETS: dict[str, dict[str, tuple[str, str]]] = {
    "crr": LOAN_EXPECTED_ORIGIN_SHEET_CRR,
    "b31": LOAN_EXPECTED_ORIGIN_SHEET_B31,
}

#: The IRB sheet of each class this portfolio populates, per regime. CRR C 08 is
#: keyed by exposure class. RE-ANCHORED 2026-11-13 for Basel 3.1, which was read
#: off the same class keys: OF 08 is published per class AND approach (BoE
#: Banking Taxonomy v4.1.1, ``OF08.01.01.01``), every modelled obligor here is
#: F-IRB, and the corporates are non-SME — published sheets 0012 and 0006.
_IRB_SHEET: dict[str, dict[str, str]] = {
    "crr": {"corporate": "corporate", "institution": "institution"},
    "b31": {"corporate": "corporate_non_sme_firb", "institution": "institution_firb"},
}

#: The post-substitution classes each IRB sheet reports, per regime — stated
#: here, not read from the generator. Under Basel 3.1 the S2 leg (retail
#: guarantor, obligor's F-IRB approach kept) is a pair no sheet exists for and
#: stays with its obligor (``B31_C08_01_DESTINATION_SHEET``), and the F-IRB /
#: slotting Total takes every modelled leg.
_SHEET_POST_CLASSES: dict[str, dict[str, tuple[str, ...]]] = {
    "crr": {
        "corporate": ("corporate",),
        "institution": ("institution",),
        "retail_other": ("retail_other",),
    },
    "b31": {
        "corporate_non_sme_firb": ("corporate", "retail_other"),
        "institution_firb": ("institution",),
        "total_firb_slotting": ("corporate", "retail_other", "institution"),
    },
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


@functools.cache
def _run(regime_key: str) -> tuple[pl.DataFrame, COREPTemplateBundle]:
    """Run the CRM-substitution portfolio through one regime, once per process.

    The pipeline run plus COREP generation costs ~2.6 s and every test in this
    module asks for the same two inputs, so the result is memoised on the
    regime key. The cached tuple is SHARED across tests and must be treated as
    read-only. Most ``pl.DataFrame`` operations return a new frame, but the
    in-place methods (``drop_in_place``, ``insert_column``, ``replace_column``,
    ``extend``, and ``vstack`` / ``hstack`` with ``in_place=True``) mutate the
    cached ledger; ``COREPTemplateBundle`` is a frozen dataclass, but its
    per-class dicts are plain dicts. A test that needs to mutate a sheet, a
    dict, or the ledger must call ``_run.__wrapped__(regime_key)`` for an
    uncached copy rather than poison the memo for every test after it.
    """
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


def _destination_sheet(regime_key: str, guarantee: str) -> str:
    """The sheet one scenario's inflow lands on.

    The regulatory destination CLASS — except on Basel 3.1 OF 08.01, whose
    sheets are published per class and approach (``B31_C08_01_DESTINATION_SHEET``).
    """
    design = SUBSTITUTION_INFLOW_DESIGN[guarantee]
    if regime_key == "b31" and design["destination_template"] == "c08_01":
        return B31_C08_01_DESTINATION_SHEET[guarantee]
    return str(design["destination_class"])


class TestPublishedIdentitiesEndToEnd:
    """The outflow subtotal and the single-subtraction waterfall hold on
    every ORIGIN sheet a real guarantee split produces."""

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_c0801_outflow_is_the_block_subtotal(self, regime_key: str) -> None:
        """``v1663_m``: C 08.01 corporate col 0070 = 0040 + 0050 + 0060."""
        _results, corep = _run(regime_key)

        corp = _total_row(corep.c08_01[_IRB_SHEET[regime_key]["corporate"]])
        assert corp["0070"][0] == pytest.approx(corp["0040"][0] + corp["0050"][0] + corp["0060"][0])

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_c0801_money_removed_exactly_once(self, regime_key: str) -> None:
        """``v1662_m``: C 08.01 corporate col 0090 = 0020 + 0070 + 0080."""
        _results, corep = _run(regime_key)

        corp = _total_row(corep.c08_01[_IRB_SHEET[regime_key]["corporate"]])
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
        for guarantee, design in SUBSTITUTION_INFLOW_DESIGN.items():
            key = (design["destination_template"], _destination_sheet(regime_key, guarantee))
            destination_totals[key] = destination_totals.get(key, 0.0) + design["guaranteed_amount"]

        for (template, dest_class), expected_amount in destination_totals.items():
            _gross_ref, _outflow_ref, inflow_ref, _net_ref = _TEMPLATE_COLS[template]

            sheets = _sheets(corep, template)
            assert dest_class in sheets, (
                f"{regime_key}: no {template} sheet for destination "
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

    def test_c0801_retail_other_sheet_created_for_s2(self) -> None:
        """S2's guarantor (retail_other) has no IRB exposure of its own.

        CRR only: C 08.01 is keyed by exposure class, so the guarantor's class is
        a sheet. RE-ANCHORED 2026-11-13 — this ran under Basel 3.1 too, on a class
        sheet no published code names; the Basel 3.1 case is the test below.
        """
        _results, corep = _run("crr")

        design = SUBSTITUTION_INFLOW_DESIGN["CSUB-GUAR-S2"]
        assert design["destination_has_native_population"] is False
        assert "retail_other" in corep.c08_01
        total = _total_row(corep.c08_01["retail_other"])
        assert total["0020"][0] == pytest.approx(0.0)  # no native exposure
        assert total["0080"][0] == pytest.approx(design["guaranteed_amount"])

    def test_of0801_s2_stays_on_the_obligors_sheet_and_is_not_lost(self) -> None:
        """Basel 3.1: an (F-IRB, retail) leg has no sheet, and is not dropped.

        S2's covered part takes a retail guarantor's class while keeping its
        obligor's F-IRB approach. No published OF 08.01 sheet and no OF 02.00 row
        is F-IRB retail, so it is reported where OF 02.00 reports its RWEA — the
        obligor's sheet 0012 — as an outflow and an inflow on that one sheet.
        No retail sheet is invented for it, and its 3,300,000 is still there.
        """
        _results, corep = _run("b31")
        design = SUBSTITUTION_INFLOW_DESIGN["CSUB-GUAR-S2"]
        same_class = SUBSTITUTION_INFLOW_DESIGN["CSUB-GUAR-S5"]

        retail_sheets = sorted(key for key in corep.c08_01 if key.startswith("retail"))
        total = _total_row(corep.c08_01[_IRB_SHEET["b31"]["corporate"]])

        assert retail_sheets == []
        assert total["0080"][0] == pytest.approx(
            design["guaranteed_amount"] + same_class["guaranteed_amount"]
        )

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
        # Both templates are added up over their CLASS sheets: each Total sheet is
        # their sum, so including it would count that side twice. Re-anchored
        # 2026-11-13: OF 08.01 gained its two Total sheets (taxonomy v4.1.1
        # ``OF08.01.01.01`` codes 0001 / 0002), as C 07.00 gained its one.
        total_after_substitution = sum(
            _total_row(frame)["0090"][0] for frame in c08_class_sheets(corep.c08_01).values()
        ) + sum(_total_row(frame)["0110"][0] for frame in c07_class_sheets(corep.c07_00).values())

        assert total_after_substitution == pytest.approx(total_gross)


class TestC0803PostCrmBasis:
    """C 08.03 keeps gross on the obligor but moves EAD/RWEA/EL to IRB guarantors."""

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_leaf_pd_ranges_reconcile_to_c0801_by_post_crm_class(self, regime_key: str) -> None:
        """C 08.03 post-CRM measures equal C 08.01's non-slotting row per sheet."""
        results, corep = _run(regime_key)

        post_classes = _SHEET_POST_CLASSES[regime_key]
        assert set(corep.c08_03) == set(post_classes)
        for sheet_key, c08_03 in corep.c08_03.items():
            leaves = c08_03.filter(~pl.col("row_ref").is_in(list(C08_03_PD_PARENT_REFS)))
            c08_01 = corep.c08_01[sheet_key].filter(pl.col("row_ref") == "0070")
            c08_02 = corep.c08_02[sheet_key]
            post_legs = results.filter(
                pl.col("reporting_approach").is_in(["foundation_irb", "advanced_irb"])
                & pl.col("reporting_class").is_in(list(post_classes[sheet_key]))
            )

            assert leaves["0040"].sum() == pytest.approx(c08_01["0110"][0])
            assert leaves["0090"].sum() == pytest.approx(c08_01["0260"][0])
            assert leaves["0100"].sum() == pytest.approx(c08_01["0280"][0])
            assert c08_02["0280"].sum() == pytest.approx(c08_01["0280"][0])
            assert leaves["0100"].sum() == pytest.approx(
                post_legs["expected_loss"].fill_null(0.0).sum()
            )

    def test_destination_only_retail_sheet_has_post_values_but_no_origin_gross(self) -> None:
        """S2's 3.3m covered leg creates a retail guarantor sheet, not retail gross.

        CRR only (RE-ANCHORED 2026-11-13): under Basel 3.1 the leg has no retail
        sheet to create — see ``test_of0803_s2_band_has_post_values_but_no_gross``.
        """
        _results, corep = _run("crr")
        leaves = corep.c08_03["retail_other"].filter(
            ~pl.col("row_ref").is_in(list(C08_03_PD_PARENT_REFS))
        )

        assert leaves["0010"].sum() + leaves["0020"].sum() == pytest.approx(0.0)
        assert leaves["0040"].sum() == pytest.approx(3_300_000.0)
        assert leaves["0100"].sum() > 0.0

    def test_of0803_s2_band_has_post_values_but_no_gross(self) -> None:
        """Basel 3.1: S2's 3.3m arrives in a band of its obligor's sheet, gross-free.

        The covered leg stays on sheet 0012 (no F-IRB retail sheet exists) but
        still bands on the guarantor's 2.00% PD — row 0090, which no native leg
        of that sheet reaches, so the row carries post-substitution value and no
        original exposure, exactly as the CRR destination sheet does.
        """
        _results, corep = _run("b31")
        band = corep.c08_03[_IRB_SHEET["b31"]["corporate"]].filter(pl.col("row_ref") == "0090")

        assert band["0010"][0] + band["0020"][0] == pytest.approx(0.0)
        assert band["0040"][0] == pytest.approx(3_300_000.0)
        assert band["0100"][0] > 0.0

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
    def test_destination_band_follows_the_guarantor_pd_not_the_borrower(
        self, regime_key: str
    ) -> None:
        """An arrived leg bands on the PD that risk-weighted it.

        S1 (borrower PD 0.50%, guarantor PD 0.30%) lands on the institution
        sheet row 0050, sharing it with GTOR_S1's own 4,000,000 loan at the same
        0.30% — the two are the same risk and the template now says so. S2
        (borrower PD 0.60%, guarantor PD 2.00%) lands on retail_other row 0090,
        five bands DOWN the scale: the row axis follows the substituted PD in
        both directions, not only where the guarantee helps.
        """
        _results, corep = _run(regime_key)

        # RE-ANCHORED 2026-11-13: both sheets were read by class key. Basel 3.1
        # reports S1 on published sheet 0006 and S2 on its obligor's sheet 0012
        # (no F-IRB retail sheet exists); the BAND is what this test is about.
        s1_sheet = _IRB_SHEET[regime_key]["institution"]
        s2_sheet = "retail_other" if regime_key == "crr" else _IRB_SHEET[regime_key]["corporate"]
        s1_band = corep.c08_03[s1_sheet].filter(pl.col("row_ref") == "0050")
        s2_band = corep.c08_03[s2_sheet].filter(pl.col("row_ref") == "0090")
        assert s1_band["0040"][0] == pytest.approx(6_000_000.0)
        assert s1_band["0050"][0] == pytest.approx(0.003)
        assert s2_band["0040"][0] == pytest.approx(3_300_000.0)
        assert s2_band["0050"][0] == pytest.approx(0.020)

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_same_class_substitution_moves_a_band_without_moving_a_sheet(
        self, regime_key: str
    ) -> None:
        """S5's guarantor is in its obligor's OWN class, so only the band moves.

        The 5,400,000 covered part leaves the obligor's 0.90% band (row 0080)
        for the guarantor's 0.45% band (row 0050) on the same corporate sheet,
        while all 27,000,000 of pre-CRM gross stays on row 0080. On the
        origin-only row axis this substitution was invisible: one row, one
        blended PD, and a 0.69% average reported against a "0.75 to <1.75" band.
        """
        _results, corep = _run(regime_key)
        corporate = corep.c08_03[_IRB_SHEET[regime_key]["corporate"]]
        moved = corporate.filter(pl.col("row_ref") == "0050")
        origin = corporate.filter(pl.col("row_ref") == "0080")

        assert moved["0010"][0] == pytest.approx(0.0)
        assert moved["0040"][0] == pytest.approx(5_400_000.0)
        assert moved["0050"][0] == pytest.approx(0.0045)
        assert origin["0010"][0] == pytest.approx(27_000_000.0)
        assert origin["0050"][0] == pytest.approx(0.0080759, rel=1e-4)

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_every_band_contains_its_own_exposure_weighted_pd(self, regime_key: str) -> None:
        """The invariant the post-CRM row axis exists to hold, over every sheet.

        A reported average PD outside its own row's range means the row was
        keyed on a PD that did not produce the numbers beside it. Before this
        change three of the portfolio's bands breached it — institution 0060 at
        0.30%, retail_other 0060 at 2.00% and corporate 0080 at 0.69%.
        """
        _results, corep = _run(regime_key)
        framework = _REGIMES[regime_key]
        bands = {ref: (lo, hi) for lo, hi, ref, _label in get_c08_03_pd_ranges(framework)}

        for exposure_class, sheet in corep.c08_03.items():
            for row in sheet.iter_rows(named=True):
                if row["0050"] is None:
                    continue
                lower, upper = bands[row["row_ref"]]
                assert lower <= row["0050"] < upper, (exposure_class, row["row_ref"])

    def test_retail_maturity_is_not_reported(self) -> None:
        """Annex II excludes maturity from every retail exposure-class sheet.

        CRR only (RE-ANCHORED 2026-11-13): this portfolio reaches no Basel 3.1
        retail sheet, so the Basel 3.1 parametrisation had nothing to assert on.
        ``tests/unit/reporting/corep/test_c08_03.py`` holds column 0080 empty on a
        published Basel 3.1 retail sheet.
        """
        _results, corep = _run("crr")
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
