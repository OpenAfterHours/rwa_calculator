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
    S2  IRB corporate  -> natural person    (Art. 201-ineligible) — declined
    S3  IRB corporate  -> SA sovereign      (no own exposure) — cross-template
    S4  SA corporate   -> SA institution    (own exposure)   — happy path
    S5  IRB corporate  -> IRB corporate     (SAME class, different counterparty)

S2 was built as an IRB retail_other inflow-only sheet. A natural person is in
no limb of Art. 201(1)/(2), so since P1.384 the protection is not recognised and
S2 is asserted here as a decline: no outflow, no inflow, no retail sheet.
``test_p1_384_s2_natural_person_declined.py`` pins the leg's own numbers.

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
    AMOUNT_COVERED_S1,
    AMOUNT_COVERED_S4,
    B31_C08_01_DESTINATION_SHEET,
    DECLINED_GUARANTEE_DESIGN,
    DRAWN_S1,
    DRAWN_S2,
    DRAWN_S4,
    DRAWN_S4_GTOR_OWN,
    GTOR_S4,
    LN_S4,
    LOAN_EXPECTED_ORIGIN_SHEET_B31,
    LOAN_EXPECTED_ORIGIN_SHEET_CRR,
    PD_GTOR_S2,
    PD_OB_S1,
    PD_OB_S2,
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
    get_sa_risk_weight_bands,
    get_sa_row_sections,
)
from rwa_calc.reporting.filing.canonical import (
    FILING_MODULE,
    FILING_TAXONOMY,
    build_canonical_return,
)
from rwa_filer.boe.engine import STATUS_PASS
from rwa_filer.model import ReturnHeader
from rwa_filer.release import resolve_release
from rwa_filer.validate.returns import validate_return

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
#: here, not read from the generator. The F-IRB / slotting Total takes every
#: modelled leg. No retail class: S2's natural-person guarantee is declined
#: (P1.384), so no leg of this portfolio is retail after substitution.
_SHEET_POST_CLASSES: dict[str, dict[str, tuple[str, ...]]] = {
    "crr": {
        "corporate": ("corporate",),
        "institution": ("institution",),
    },
    "b31": {
        "corporate_non_sme_firb": ("corporate",),
        "institution_firb": ("institution",),
        "total_firb_slotting": ("corporate", "institution"),
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
    exposure of its own must still get a sheet (D5) — S3 across the SA/IRB
    template boundary onto C 07.00.

    S2 used to exercise the same case within C 08.01 (an inflow-only CRR
    retail_other sheet). Since P1.384 its natural-person guarantee is not
    recognised, so it is asserted here as the decline it now is, and no
    registered portfolio reaches a C 08.01 inflow-only sheet.
    """

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_declined_s2_books_no_outflow_and_no_inflow(self, regime_key: str) -> None:
        """S2's 3,300,000 stays native on its obligor's corporate sheet.

        The corporate sheet's outflow is exactly the recognised guarantees whose
        loans originate there (S1, S3, S5, S7 — not S2) and its inflow is S5's
        same-class leg alone. Before P1.384 S2 added 3,300,000 to the outflow
        under both regimes and, under Basel 3.1, 3,300,000 to the inflow too.
        """
        _results, corep = _run(regime_key)
        corporate_sheet = _IRB_SHEET[regime_key]["corporate"]
        origin_sheets = _ORIGIN_SHEETS[regime_key]
        recognised_outflow = sum(
            float(design["guaranteed_amount"])  # type: ignore[arg-type]
            for design in SUBSTITUTION_INFLOW_DESIGN.values()
            if origin_sheets[str(design["loan_reference"])] == ("c08_01", corporate_sheet)
        )
        declined = DECLINED_GUARANTEE_DESIGN["CSUB-GUAR-S2"]
        same_class = SUBSTITUTION_INFLOW_DESIGN["CSUB-GUAR-S5"]

        total = _total_row(corep.c08_01[corporate_sheet])

        assert origin_sheets[str(declined["loan_reference"])] == ("c08_01", corporate_sheet)
        assert total["0070"][0] == pytest.approx(-recognised_outflow)
        assert total["0080"][0] == pytest.approx(same_class["guaranteed_amount"])

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_declined_s2_creates_no_retail_sheet(self, regime_key: str) -> None:
        """No exposure of this portfolio is retail, before or after substitution."""
        _results, corep = _run(regime_key)

        assert sorted(key for key in corep.c08_01 if key.startswith("retail")) == []
        assert sorted(key for key in corep.c08_03 if key.startswith("retail")) == []

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

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_declined_s2_bands_on_the_obligors_pd_not_the_guarantors(self, regime_key: str) -> None:
        """S2's whole 6,000,000 bands on its obligor's 0.60% PD, none on 2.00%.

        The obligor's band also holds S1's retained 3,000,000 at 0.50% (the same
        "0.50 to <0.75" band). Before P1.384 the 3,300,000 covered part banded on
        the natural person's 2.00% PD (CRR: the retail_other sheet; Basel 3.1:
        row 0090 of the obligor's sheet), leaving 5,700,000 in the obligor's band.
        """
        _results, corep = _run(regime_key)
        # Leaf bands only: the PD scale is hierarchical (0070 is the parent of
        # 0080 and 0090), and a parent row also holds every leg of its children.
        bands = [
            band
            for band in get_c08_03_pd_ranges(_REGIMES[regime_key])
            if band[2] not in C08_03_PD_PARENT_REFS
        ]
        ob_ref = next(ref for lo, hi, ref, _ in bands if lo <= PD_OB_S2 < hi)
        s1_ref = next(ref for lo, hi, ref, _ in bands if lo <= PD_OB_S1 < hi)
        gtor_ref = next(ref for lo, hi, ref, _ in bands if lo <= PD_GTOR_S2 < hi)
        sheet = corep.c08_03[_IRB_SHEET[regime_key]["corporate"]]

        obligor_band = sheet.filter(pl.col("row_ref") == ob_ref)
        guarantor_band = sheet.filter(pl.col("row_ref") == gtor_ref)

        assert s1_ref == ob_ref, "S1's retained leg must share the band for the sum below"
        assert obligor_band["0040"][0] == pytest.approx(DRAWN_S2 + (DRAWN_S1 - AMOUNT_COVERED_S1))
        assert guarantor_band.height == 0 or not guarantor_band["0040"][0]

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
        0.30% — the two are the same risk and the template now says so.

        S2 used to pin the other direction (a guarantor PD five bands DOWN the
        scale). Its natural-person guarantee is not recognised since P1.384, so
        no registered leg now moves DOWN the PD scale on substitution.
        """
        _results, corep = _run(regime_key)

        # RE-ANCHORED 2026-11-13: the sheet was read by class key. Basel 3.1
        # reports S1 on published sheet 0006; the BAND is what this test is about.
        s1_sheet = _IRB_SHEET[regime_key]["institution"]
        s1_band = corep.c08_03[s1_sheet].filter(pl.col("row_ref") == "0050")
        assert s1_band["0040"][0] == pytest.approx(6_000_000.0)
        assert s1_band["0050"][0] == pytest.approx(0.003)

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


#: S4's covered leg: the engine splits the guaranteed loan into this leg and a remainder.
_S4_COVERED_LEG: str = f"{LN_S4}__G_{GTOR_S4}"

#: The OF 07.00 / C 07.00 risk-weight block is the third row section (Annex II rows
#: 0140-0280 under Basel 3.1, 0140-0290 under CRR); each row is named by its band.
_RW_SECTION_INDEX: int = 2

#: A checksum-valid LEI, as the filing-mapping ratchet uses; the rules do not depend on it.
_ENTITY_IDENTIFIER: str = "5493001KJTIIGC8Y1R12"


def _s4_covered_leg(results: pl.DataFrame) -> dict[str, object]:
    matched = results.filter(pl.col("exposure_reference") == _S4_COVERED_LEG)
    assert matched.height == 1, f"{_S4_COVERED_LEG}: expected one leg, got {matched.height}"
    return matched.row(0, named=True)


def _band_row(regime_key: str, weight: float) -> str:
    """The risk-weight row a weight is reported in, read off the template's own band list."""
    framework = _REGIMES[regime_key]
    labels = [
        label
        for rung, label in get_sa_risk_weight_bands(framework)
        if round(rung, 4) == round(weight, 4)
    ]
    assert len(labels) == 1, f"{regime_key}: weight {weight} is on no published rung"
    section = get_sa_row_sections(framework)[_RW_SECTION_INDEX]
    refs = [row.ref for row in section.rows if row.name == labels[0]]
    assert len(refs) == 1, f"{regime_key}: band {labels[0]!r} names {refs}"
    return refs[0]


def _row(sheet: pl.DataFrame, row_ref: str) -> dict[str, object]:
    matched = sheet.filter(pl.col("row_ref") == row_ref)
    assert matched.height == 1, f"expected one row {row_ref}, got {matched.height}"
    return matched.row(0, named=True)


def _value_cells(row: dict[str, object]) -> dict[str, object]:
    return {ref: value for ref, value in row.items() if ref not in ("row_ref", "row_name")}


class TestRiskWeightRowsOfASubstitutedLeg:
    """A substituted covered part is reported in TWO risk-weight rows, one per basis.

    PS1/26 Annex II (ps1-26-annex-ii-reporting-instructions.pdf), and the C 07.00
    text it repeats:

    - p.94, rows 0140-0280: "Institutions shall report the information on the
      allocation of risk weights within the respective exposure class".
    - p.84, cols 0090 / 0100: "Outflows shall correspond to the covered part of the
      Original Exposure pre-conversion factors that is deducted from the obligor's
      exposure class and subsequently assigned to the protection provider's exposure
      class. That amount shall be considered as an inflow into the protection
      provider's exposure class."
    - p.81, col 0010: "... without taking into account ... the effect of credit risk
      mitigation techniques".
    - EBA Q&A 2014_1636 (same C 07.00 text): "Decisive for the reporting of exposures
      in column 010 ... is not only the risk weight, but also the exposure class";
      the guaranteed parts "are substituted to the exposure class of the protection
      provider where the secured exposure is assigned to the risk weight 0% included
      from column 100 and reported explicitly from column 150 onwards".

    So cols 0010-0040 of the WHOLE S4 loan sit at the obligor's own weight on the
    obligor's sheet; from col 0150 on (and the col 0100 inflow) the covered part sits
    at the provider's weight on the provider's sheet. Banded on its post-substitution
    weight for every column, the covered part's original exposure sat in the
    PROVIDER's row of the obligor's sheet: Basel 3.1 corporates r0182 (30%), which
    the Bank's ``boe_b0441`` / ``boe_b0441_1`` require empty; CRR corporates r0200.
    """

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_original_exposure_is_reported_at_the_obligors_own_risk_weight(
        self, regime_key: str
    ) -> None:
        results, corep = _run(regime_key)
        leg = _s4_covered_leg(results)
        # Adequacy (LESSONS C11): the protection was applied, and the two weights
        # band on different rows, or this test could not see the defect.
        assert leg["is_guarantee_beneficial"] is True
        own_row = _band_row(regime_key, float(leg["pre_crm_risk_weight"]))
        provider_row = _band_row(regime_key, float(leg["risk_weight"]))
        assert own_row != provider_row

        corporate = corep.c07_00["corporate"]
        own = _row(corporate, own_row)
        provider = _row(corporate, provider_row)

        assert own["0010"] == pytest.approx(DRAWN_S4)
        assert own["0040"] == pytest.approx(DRAWN_S4)
        assert _value_cells(provider) == dict.fromkeys(_value_cells(provider))

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_exposure_value_and_rwea_stay_at_the_providers_risk_weight(
        self, regime_key: str
    ) -> None:
        """CONTROL, green before and after: the survivor leg of LESSONS B5's two-leg shape.

        Its mutation is banding the post-basis cells (or the col 0100 inflow) on the
        obligor's weight too: the institution row then loses the 2,800,000 covered
        part and the corporate row gains it.
        """
        results, corep = _run(regime_key)
        leg = _s4_covered_leg(results)
        own_row = _band_row(regime_key, float(leg["pre_crm_risk_weight"]))
        provider_row = _band_row(regime_key, float(leg["risk_weight"]))
        arrived = DRAWN_S4_GTOR_OWN + AMOUNT_COVERED_S4
        stayed = DRAWN_S4 - AMOUNT_COVERED_S4

        provider = _row(corep.c07_00["institution"], provider_row)
        own = _row(corep.c07_00["corporate"], own_row)

        assert provider["0150"] == pytest.approx(arrived)
        assert provider["0200"] == pytest.approx(arrived)
        assert provider["0220"] == pytest.approx(arrived * float(leg["risk_weight"]))
        assert own["0150"] == pytest.approx(stayed)
        assert own["0200"] == pytest.approx(stayed)
        assert own["0220"] == pytest.approx(stayed * float(leg["pre_crm_risk_weight"]))

    def test_bank_row_availability_rules_hold_on_the_corporates_sheet(self) -> None:
        """``boe_b0441`` / ``boe_b0441_1``: no figure in a row Art. 122 gives no corporate.

        The rule names the corporates sheet (z0008) rows that are not corporate risk
        weights, row 0182 (30%) among them, over cols 0010-0240 of OF07.00.01.01 and
        col 0210 of OF07.00.01.02. Anchored on the Bank's published rule, which cannot
        drift with our generator (LESSONS B3).
        """
        _results, corep = _run("b31")
        header = ReturnHeader(_ENTITY_IDENTIFIER, date(2027, 3, 31), FILING_MODULE)
        pack = resolve_release(FILING_MODULE, FILING_TAXONOMY).pack
        validation = validate_return(
            build_canonical_return(corep, header, pack=pack).canonical, pack
        )
        assert validation.report is not None

        verdicts = {
            result.rule_id: result.status
            for result in validation.report.results
            if result.rule_id in ("boe_b0441", "boe_b0441_1")
        }
        assert verdicts == {"boe_b0441": STATUS_PASS, "boe_b0441_1": STATUS_PASS}


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
