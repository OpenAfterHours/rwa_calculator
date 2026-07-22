"""
Unit tests: report-cell lineage (reporting.lineage).

Pins the model that makes the drill-down honest:
- the SIX cell kinds fall out of the binding vocabulary, so every cell gets a
  truthful answer — not just the summable ones. A formula cell derives from
  other CELLS (no rows); a constant cell is a source the engine never produces;
  an unbound cell is the template's empty policy.
- a cell's filter criteria are read off the spec the generator executes, and each
  term is tagged ledger (a sealed fact) or derived (a template discriminator).
- an uninstrumented template resolves to None — a clean "no lineage", never a
  re-derived guess.

References:
- docs/plans/report-cell-lineage.md §4 (Phase B)
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl
import pytest

from rwa_calc.reporting import lineage
from rwa_calc.reporting.cellspec import (
    CellSpec,
    Count,
    FirstNonNull,
    Formula,
    Mean,
    PriorPeriod,
    Ratio,
    RowPredicate,
    SafeSum,
    SideContext,
    Sum,
    TemplateSpec,
    WeightedAvg,
    execute,
)
from rwa_calc.reporting.metadata import ReportingContext
from rwa_calc.reporting.plans import SheetPlan

# =============================================================================
# The six cell kinds
# =============================================================================


def test_summing_bindings_are_row_backed() -> None:
    # Act / Assert — these are the cells with contributing exposures.
    assert lineage._binding_facts(Sum("rwa_final")) == ("rows", "sum", ("rwa_final",), ())
    assert lineage._binding_facts(SafeSum(("a", "b"))) == ("rows", "sum", ("a", "b"), ())
    assert lineage._binding_facts(Mean("pd")) == ("rows", "mean", ("pd",), ())
    assert lineage._binding_facts(WeightedAvg("lgd")) == (
        "rows",
        "weighted_avg",
        ("lgd", "reporting_ead"),
        (),
    )
    assert lineage._binding_facts(Ratio("a", "b")) == ("rows", "ratio", ("a", "b"), ())
    assert lineage._binding_facts(Count("x", distinct=True)) == ("rows", "count", ("x",), ())
    assert lineage._binding_facts(FirstNonNull("x")) == ("rows", "first_non_null", ("x",), ())


def test_a_formula_cell_derives_from_other_cells_not_from_rows() -> None:
    # Arrange — C 07.00's 0040 = 0010 - 0030 waterfall.
    binding = Formula(refs=("0010", "0030"), fn=lambda _cells, _prior: 0.0)

    # Act
    kind, metric, columns, refs = lineage._binding_facts(binding)

    # Assert
    assert (kind, metric, columns) == ("formula", None, ())
    assert refs == ("0010", "0030")


def test_a_refless_formula_is_a_constant_not_a_derivation_of_nothing() -> None:
    # Arrange — the recorded structural-null / fixed-zero cells (e.g. 0210).
    binding = Formula(refs=(), fn=lambda _cells, _prior: None)

    # Act
    kind, _metric, _columns, refs = lineage._binding_facts(binding)

    # Assert
    assert kind == "constant"
    assert refs == ()


def test_side_context_and_prior_period_are_out_of_frame_kinds() -> None:
    # Act / Assert — C 07.00 col 0100 (substitution inflow); CR8/C 08.04 opening.
    assert lineage._binding_facts(SideContext("substitution_inflow")) == (
        "side_context",
        "side_context",
        ("substitution_inflow",),
        (),
    )
    assert lineage._binding_facts(PriorPeriod(Sum("rwa_final"))) == (
        "prior_period",
        "sum",
        ("rwa_final",),
        (),
    )


def test_an_unbound_cell_is_the_templates_empty_policy() -> None:
    # Act / Assert
    assert lineage._binding_facts(None) == ("unbound", None, (), ())


# =============================================================================
# Filter criteria — read off the spec, tagged ledger vs derived
# =============================================================================


_SEALED = {"reporting_class_origin", "reporting_leg_role", "is_defaulted", "reporting_rw"}


def test_sealed_ledger_terms_are_tagged_ledger() -> None:
    # Arrange
    predicate = RowPredicate(
        classes_origin=("corporate",), leg_role="guaranteed", is_defaulted=True
    )

    # Act
    terms = lineage._terms(predicate, _SEALED)

    # Assert
    assert [(t.column, t.op, t.value, t.source) for t in terms] == [
        ("reporting_class_origin", "in", ("corporate",), "ledger"),
        ("reporting_leg_role", "eq", "guaranteed", "ledger"),
        ("is_defaulted", "eq", True, "ledger"),
    ]


def test_template_derived_discriminators_are_tagged_derived() -> None:
    # Arrange — C 07.00 derives its RW band / CCF bucket for its own row structure.
    predicate = RowPredicate(equals=(("c07_rw_band", "100%"),))

    # Act
    (term,) = lineage._terms(predicate, _SEALED)

    # Assert — a reviewer can see this is not a sealed fact about the exposure.
    assert (term.column, term.source) == ("c07_rw_band", "derived")


def test_band_and_any_of_terms_are_flattened() -> None:
    # Arrange
    predicate = RowPredicate(
        rw_between=(0.0, 0.2),
        between=(("cr5_rw_bucket", 0.35, 0.5),),
        any_of=(RowPredicate(classes_origin=("retail",)),),
    )

    # Act
    terms = lineage._terms(predicate, _SEALED)

    # Assert
    ops = {(t.column, t.op) for t in terms}
    assert ("reporting_rw", "between") in ops
    assert ("cr5_rw_bucket", "between") in ops
    assert ("any_of", "any_of") in ops


def test_no_predicate_means_no_constraint() -> None:
    # Act / Assert — C 07.00's total row (0010) selects the whole sheet.
    assert lineage._terms(None, _SEALED) == []
    assert lineage._terms(RowPredicate(), _SEALED) == []


# =============================================================================
# Coverage boundary
# =============================================================================


def test_only_instrumented_templates_have_lineage() -> None:
    # Assert — C 34.02 (per netting set, R27b) and CCR1-8 (R27c) are still
    # imperative: no TemplateSpec to read, so no lineage. C 34.01/04/08 were
    # instrumented in R27a. Coverage is explicit, never a guess.
    assert "c07_00" in lineage.LINEAGE_PLANS
    assert "c34_01" in lineage.LINEAGE_PLANS
    assert "c34_02" not in lineage.LINEAGE_PLANS
    assert "ccr1" not in lineage.LINEAGE_PLANS


# R20 — the four single-frame Pillar 3 templates (cr4/cr6a/cr7/cr8) instrumented.
_R20_SINGLE_FRAME_TEMPLATES = ("cr4", "cr6a", "cr7", "cr8")


@pytest.mark.parametrize("template_id", _R20_SINGLE_FRAME_TEMPLATES)
def test_r20_pillar3_templates_are_single_frame_instrumented(template_id: str) -> None:
    # Assert — each R20 template is instrumented as a SINGLE-FRAME provider (no
    # sheet axis -> cells report sheet=None), with a populated scope (the
    # population wording a reviewer checks) and no sheet label.
    assert lineage.is_instrumented(template_id)
    provider = lineage.LINEAGE_PLANS[template_id]
    assert provider.single_frame is True
    assert provider.scope
    assert provider.sheet_label == ""


def test_cr8_opening_row_is_a_prior_period_cell() -> None:
    # Assert — CR8's row 1 (opening RWEA) is a PriorPeriod binding, so its cell
    # kind is "prior_period" (out-of-frame, not row-backed). CR8 is the first
    # such template through the tie-out sweep.
    from rwa_calc.reporting.pillar3.cr8 import CR8_SPEC

    binding = CR8_SPEC.cells[("1", "a")].binding
    kind, metric, _columns, _refs = lineage._binding_facts(binding)
    assert (kind, metric) == ("prior_period", "sum")


def test_cr8_prior_period_derived_cells_are_refused_by_the_resolver() -> None:
    # Arrange — a current-period IRB frame (CR8 reads approach_applied + rwa_final).
    frame = pl.DataFrame(
        {
            "exposure_reference": ["EXP-FIRB", "EXP-AIRB"],
            "approach_applied": ["foundation_irb", "advanced_irb"],
            "rwa_final": [720_000.0, 430_000.0],
        }
    )
    resolver = lineage.sheet_lineage(_FrameSource(frame), "cr8")
    assert resolver is not None

    # Act / Assert — the closing row (9, current period) resolves and is
    # row-backed; the opening (1, PriorPeriod) and residual (8, Formula over the
    # opening) rows are prior-period-derived, so the resolver DECLINES them — a
    # clean refusal, never a cell_value that could contradict a comparative period.
    closing = resolver.query("9", "a")
    assert closing is not None
    assert closing.derives_from_prior_period is False
    assert resolver.cell("9", "a") is not None
    for prior_row in ("1", "8"):
        query = resolver.query(prior_row, "a")
        assert query is not None
        assert query.derives_from_prior_period is True
        assert resolver.cell(prior_row, "a") is None


# R21 — four more single-frame Pillar 3 templates (ov1/cr5/cms1/cms2) instrumented.
_R21_SINGLE_FRAME_TEMPLATES = ("ov1", "cr5", "cms1", "cms2")


@pytest.mark.parametrize("template_id", _R21_SINGLE_FRAME_TEMPLATES)
def test_r21_pillar3_templates_are_single_frame_instrumented(template_id: str) -> None:
    # Assert — each R21 template is instrumented as a SINGLE-FRAME provider (no
    # sheet axis -> cells report sheet=None), with a populated scope and no sheet
    # label.
    assert lineage.is_instrumented(template_id)
    provider = lineage.LINEAGE_PLANS[template_id]
    assert provider.single_frame is True
    assert provider.scope
    assert provider.sheet_label == ""


def test_ov1_floor_rows_are_first_non_null_and_side_context_kinds() -> None:
    # Assert — OV1 row 26 (output-floor multiplier) is a FirstNonNull (kind
    # "rows"/first_non_null) and row 27 (OF-ADJ) is a SideContext — OV1 is the
    # first template with those two kinds through the tie-out sweep.
    from rwa_calc.reporting.pillar3.ov1 import _OV1_SPECS

    spec = _OV1_SPECS["BASEL_3_1"]
    assert lineage._binding_facts(spec.cells[("26", "a")].binding) == (
        "rows",
        "first_non_null",
        ("output_floor_pct",),
        (),
    )
    assert lineage._binding_facts(spec.cells[("27", "a")].binding) == (
        "side_context",
        "side_context",
        ("of_adj",),
        (),
    )


@pytest.mark.parametrize("template_id", ("cms1", "cms2"))
def test_cms_lineage_is_a_clean_no_lineage_under_crr(template_id: str) -> None:
    # Arrange — CMS1/CMS2 are Basel 3.1 only; their plans() yield nothing under a
    # CRR run (_FrameSource.framework == "CRR").
    frame = pl.DataFrame(
        {
            "exposure_reference": ["E1"],
            "reporting_approach_origin": ["standardised"],
            "exposure_class": ["corporate"],
            "rwa_final": [100.0],
        }
    )

    # Act / Assert — the resolver degrades to None (a clean no-lineage), exactly
    # like an uninstrumented template, rather than crashing on a CRR frame.
    assert lineage.is_instrumented(template_id)
    assert lineage.sheet_lineage(_FrameSource(frame), template_id) is None


def test_ov1_row27_side_context_is_refused_so_it_never_contradicts_a_floored_report() -> None:
    # Arrange — a Basel 3.1 book. The REPORTED template is generated WITH the
    # run's output-floor summary (as production does — api/rest.py
    # get_template_bundles), so row 27's OF-ADJ is a real figure on the screen.
    from rwa_calc.contracts.bundles import OutputFloorSummary
    from rwa_calc.reporting.pillar3.ov1 import generate_ov1

    frame = pl.DataFrame(
        {
            "exposure_reference": ["E1"],
            "reporting_approach_origin": ["advanced_irb"],
            "reporting_class_origin": ["corporate"],
            "rwa_final": [1_000_000.0],
            "reporting_rw": [1.0],
        }
    )
    cols = set(frame.columns)
    summary = OutputFloorSummary(
        u_trea=1_000_000.0,
        s_trea=900_000.0,
        floor_pct=0.725,
        floor_threshold=902_500.0,
        shortfall=0.0,
        portfolio_floor_binding=False,
        floored_modelled_rwa=1_000_000.0,
        of_adj=250_000.0,
    )
    reported = generate_ov1(frame.lazy(), cols, "BASEL_3_1", [], summary)
    assert reported is not None
    row27_reported = reported.filter(pl.col("row_ref") == "27")["a"][0]
    assert row27_reported == pytest.approx(250_000.0)  # a real OF-ADJ on the screen

    # Act — the drill-down runs the no-side view (ov1_plans threads no summary).
    resolver = lineage.sheet_lineage(_FrameSource(frame, "BASEL_3_1"), "ov1")
    assert resolver is not None
    q27 = resolver.query("27", "a")
    q26 = resolver.query("26", "a")

    # Assert — row 27 (a SideContext with no of_adj on the plan) is REFUSED, so
    # the drill-down never serves the null that would contradict the 250,000 on
    # the screen. The refusal is CONDITIONAL on the SideContext value being
    # absent — row 26 (a FirstNonNull, not a side context) is NOT refused.
    assert q27 is not None
    assert (q27.kind, q27.reads_unavailable_side_value) == ("side_context", True)
    assert resolver.cell("27", "a") is None
    assert q26 is not None
    assert q26.reads_unavailable_side_value is False
    assert resolver.cell("26", "a") is not None


def test_c07_substitution_inflow_side_context_stays_drillable() -> None:
    # Assert — the refusal is not kind-blanket: C 07.00's col 0100 is a
    # SideContext whose c07_plans threads the real per-sheet inflow, so its
    # side_value is present and the cell must NOT be refused (a threaded
    # SideContext ties out to its real figure).
    ctx = ReportingContext(substitution_inflow=1234.0)
    plan = SheetPlan(
        spec=TemplateSpec(
            name="t",
            rows=(_Row("0010", "Total"),),
            column_refs=("0100",),
            cells={("0010", "0100"): CellSpec(SideContext("substitution_inflow"))},
            empty_cell="zero",
        ),
        frame=pl.DataFrame({"exposure_reference": ["E1"]}),
        ctx=ctx,
        negative_cols=frozenset(),
    )
    query = lineage.describe_cell(
        lineage.LINEAGE_PLANS["c07_00"], plan, "c07_00", None, "0010", "0100", sealed=set()
    )
    assert query.kind == "side_context"
    assert query.reads_unavailable_side_value is False


# =============================================================================
# R22 — two multi-sheet templates (the first since C 07.00) + two single-frame
# =============================================================================

_R22_MULTI_SHEET_TEMPLATES = ("c08_04", "cr7a")
_R22_SINGLE_FRAME_TEMPLATES = ("c08_07", "of_02_01")


@pytest.mark.parametrize("template_id", _R22_MULTI_SHEET_TEMPLATES)
def test_r22_multi_sheet_templates_are_instrumented(template_id: str) -> None:
    # Assert — each R22 multi-sheet template is instrumented as a PER-SHEET
    # provider (single_frame False -> its cells carry a sheet axis), with a
    # populated scope and a sheet label naming that axis (c08_04 by exposure
    # class, cr7a by origin approach).
    assert lineage.is_instrumented(template_id)
    provider = lineage.LINEAGE_PLANS[template_id]
    assert provider.single_frame is False
    assert provider.scope
    assert provider.sheet_label != ""


@pytest.mark.parametrize("template_id", _R22_SINGLE_FRAME_TEMPLATES)
def test_r22_single_frame_templates_are_instrumented(template_id: str) -> None:
    # Assert — each R22 single-frame template is instrumented (no sheet axis ->
    # cells report sheet=None), with a populated scope and no sheet label.
    assert lineage.is_instrumented(template_id)
    provider = lineage.LINEAGE_PLANS[template_id]
    assert provider.single_frame is True
    assert provider.scope
    assert provider.sheet_label == ""


def test_c08_04_prior_period_derived_rows_are_refused_by_the_resolver() -> None:
    # Arrange — a current-period IRB non-slotting frame (C 08.04 keys the sheet on
    # reporting_class_origin, narrows on reporting_approach_origin, sums rwa_final).
    frame = pl.DataFrame(
        {
            "exposure_reference": ["EXP-FIRB", "EXP-AIRB"],
            "reporting_class_origin": ["corporate", "corporate"],
            "reporting_approach_origin": ["foundation_irb", "advanced_irb"],
            "rwa_final": [720_000.0, 430_000.0],
        }
    )
    resolver = lineage.sheet_lineage(_FrameSource(frame), "c08_04", "corporate")
    assert resolver is not None

    # Act / Assert — the closing row (0090, current period) resolves and is
    # row-backed; the opening (0010, PriorPeriod) and residual (0080, Formula over
    # the opening) rows are prior-period-derived — C 08.04's rows 0010/0080 mirror
    # CR8's 1/8 — so the resolver DECLINES them (R20's refusal, free).
    closing = resolver.query("0090", "0010")
    assert closing is not None
    assert closing.derives_from_prior_period is False
    assert resolver.cell("0090", "0010") is not None
    for prior_row in ("0010", "0080"):
        query = resolver.query(prior_row, "0010")
        assert query is not None
        assert query.derives_from_prior_period is True
        assert resolver.cell(prior_row, "0010") is None


def test_of_02_01_lineage_is_a_clean_no_lineage_under_crr() -> None:
    # Arrange — OF 02.01 is Basel 3.1 only; its plans() yield nothing under a CRR
    # run (_FrameSource.framework == "CRR"), exactly like CMS1/CMS2.
    frame = pl.DataFrame(
        {
            "exposure_reference": ["E1"],
            "approach_applied": ["advanced_irb"],
            "risk_type": ["CREDIT"],
            "rwa_pre_floor": [100.0],
            "sa_rwa": [80.0],
        }
    )

    # Act / Assert — the resolver degrades to None (a clean no-lineage), exactly
    # like an uninstrumented template, rather than producing a CRR frame.
    assert lineage.is_instrumented("of_02_01")
    assert lineage.sheet_lineage(_FrameSource(frame), "of_02_01") is None


# =============================================================================
# R23 — the two remaining C 08 instrument templates (per exposure class)
# =============================================================================

_R23_MULTI_SHEET_TEMPLATES = ("c08_01", "c08_02")


@pytest.mark.parametrize("template_id", _R23_MULTI_SHEET_TEMPLATES)
def test_r23_multi_sheet_templates_are_instrumented(template_id: str) -> None:
    # Assert — each R23 template is instrumented as a PER-SHEET provider
    # (single_frame False -> its cells carry a sheet axis), keyed by exposure
    # class, with a populated scope and a sheet label naming that axis.
    assert lineage.is_instrumented(template_id)
    provider = lineage.LINEAGE_PLANS[template_id]
    assert provider.single_frame is False
    assert provider.scope
    assert provider.sheet_label == "exposure class"


def test_c08_01_substitution_inflow_side_context_drills_to_its_real_value() -> None:
    # Arrange — a corporate leg guaranteed INTO institution (the R12 cross-class
    # substitution shape). C 08.01 lands that per-destination-class inflow on the
    # destination sheet's Total row col 0080 (a SideContext), so the institution
    # sheet reports a real 800 there.
    frame = pl.DataFrame(
        {
            "exposure_reference": ["CORP-1", "CORP-GTD", "INST-1"],
            "reporting_class_origin": ["corporate", "corporate", "institution"],
            "reporting_approach_origin": [
                "foundation_irb",
                "foundation_irb",
                "foundation_irb",
            ],
            "ead_final": [5000.0, 3000.0, 2000.0],
            "rwa_final": [3500.0, 1800.0, 600.0],
            "guaranteed_portion": [0.0, 800.0, 0.0],
            "pre_crm_exposure_class": ["corporate", "corporate", "institution"],
            "post_crm_exposure_class_guaranteed": [
                "corporate",
                "institution",
                "institution",
            ],
        }
    )
    resolver = lineage.sheet_lineage(_FrameSource(frame), "c08_01", "institution")
    assert resolver is not None

    # Act
    query = resolver.query("0010", "0080")
    result = resolver.cell("0010", "0080")

    # Assert — c08_01_plans threads the real inflow into the plan's ReportingContext,
    # so the SideContext value is PRESENT (not refused) and the cell drills down to
    # its real figure — the conditional-refusal escape does NOT fire here.
    assert query is not None
    assert (query.kind, query.reads_unavailable_side_value) == ("side_context", False)
    assert result is not None
    assert result.cell_value == pytest.approx(800.0)


def test_c08_02_substitution_inflow_is_a_constant_zero_at_grade_grain() -> None:
    # Arrange — C 08.02 has no Total row, so its col 0080 is a per-grade constant
    # 0.0 (the recorded R12 disposition: a cross-class inflow has no origin-basis
    # grade home). Two corporate legs at PD 1% fall in one PD band -> one row.
    frame = pl.DataFrame(
        {
            "exposure_reference": ["CORP-1", "CORP-2"],
            "reporting_class_origin": ["corporate", "corporate"],
            "reporting_approach_origin": ["foundation_irb", "foundation_irb"],
            "ead_final": [5000.0, 3000.0],
            "rwa_final": [3500.0, 1800.0],
            "pd_floored": [0.01, 0.01],
        }
    )
    resolver = lineage.sheet_lineage(_FrameSource(frame), "c08_02", "corporate")
    assert resolver is not None
    (row,) = resolver._plan.spec.rows  # noqa: SLF001 - the single populated PD band

    # Act
    query = resolver.query(row.ref, "0080")
    result = resolver.cell(row.ref, "0080")

    # Assert — col 0080 reads as a CONSTANT kind (a refless Formula), so it drills
    # down with no contributing legs and a reported 0.0 (never the C 08.01 inflow).
    assert query is not None
    assert query.kind == "constant"
    assert result is not None
    assert result.total_rows == 0
    assert result.cell_value == pytest.approx(0.0)


# =============================================================================
# R24 — the three C 08 instrument templates (sparse PD ranges + slotting SL types)
# =============================================================================

_R24_MULTI_SHEET_TEMPLATES = ("c08_03", "c08_05", "c08_06")


@pytest.mark.parametrize("template_id", _R24_MULTI_SHEET_TEMPLATES)
def test_r24_multi_sheet_templates_are_instrumented(template_id: str) -> None:
    # Assert — each R24 template is instrumented as a PER-SHEET provider
    # (single_frame False -> its cells carry a sheet axis), with a populated scope
    # and a sheet label naming that axis (c08_03/05 by exposure class, c08_06 by
    # SL type).
    assert lineage.is_instrumented(template_id)
    provider = lineage.LINEAGE_PLANS[template_id]
    assert provider.single_frame is False
    assert provider.scope
    assert provider.sheet_label != ""


def test_c08_03_pd_band_cell_drills_to_the_bands_legs() -> None:
    # Arrange — two corporate F-IRB legs at PD 1% fall in one C 08.03 PD band
    # (the sparse-row axis: only populated buckets emit a row).
    frame = pl.DataFrame(
        {
            "exposure_reference": ["CORP-1", "CORP-2"],
            "reporting_class_origin": ["corporate", "corporate"],
            "reporting_approach_origin": ["foundation_irb", "foundation_irb"],
            "ead_final": [5000.0, 3000.0],
            "rwa_final": [3500.0, 1800.0],
            "pd_floored": [0.01, 0.01],
        }
    )
    resolver = lineage.sheet_lineage(_FrameSource(frame), "c08_03", "corporate")
    assert resolver is not None
    (row,) = resolver._plan.spec.rows  # noqa: SLF001 - the single populated PD band

    # Act — col 0040 (EAD) sums ead_final over the band's legs.
    query = resolver.query(row.ref, "0040")
    result = resolver.cell(row.ref, "0040")

    # Assert — a row-backed cell whose legs ARE the band's two exposures; the
    # drill-down re-runs the c08_pd_range band predicate the generator ran.
    assert query is not None
    assert (query.kind, query.metric, query.metric_columns) == ("rows", "sum", ("ead_final",))
    assert result is not None
    assert result.total_rows == 2
    assert result.contribution_total == pytest.approx(8000.0)
    assert result.cell_value == pytest.approx(8000.0)


def test_c08_06_empty_category_row_col_0070_is_an_unbound_fixed_display_rw() -> None:
    # Arrange — one slotting project-finance leg in Category 1 (Strong), long
    # maturity. Every OTHER category x maturity row is empty; an empty non-Total
    # row is hard zero-filled with the row definition's FIXED display risk weight
    # in col 0070 (a template artefact, not a measured weighted average).
    frame = pl.DataFrame(
        {
            "exposure_reference": ["PF-1"],
            "reporting_approach_origin": ["slotting"],
            "sl_type": ["project_finance"],
            "slotting_category": ["strong"],
            "ead_final": [1000.0],
            "rwa_final": [700.0],
            "risk_weight": [0.7],
            "is_short_maturity": [False],
        }
    )
    resolver = lineage.sheet_lineage(_FrameSource(frame), "c08_06", "project_finance")
    assert resolver is not None

    # Act — row 0050 (Category 3 Satisfactory, short maturity) is empty; its col
    # 0070 renders the fixed 115% display weight from the zero-fill pass. Row 0020
    # (Category 1 Strong, long) is the live row.
    empty_query = resolver.query("0050", "0070")
    empty_result = resolver.cell("0050", "0070")
    live_query = resolver.query("0020", "0070")

    # Assert — the empty row's 0070 is UNBOUND (the template's empty policy), so
    # the drill-down reports no legs and reads the fixed display value from the
    # reported frame — never a WeightedAvg whose no-leg value would contradict the
    # 115% on the screen. The live row's 0070 stays a row-backed weighted average.
    assert empty_query is not None
    assert empty_query.kind == "unbound"
    assert empty_result is not None
    assert empty_result.total_rows == 0
    assert empty_result.cell_value == pytest.approx(1.15)
    assert live_query is not None
    assert (live_query.kind, live_query.metric) == ("rows", "weighted_avg")


# =============================================================================
# R25 — the two C 09 geo templates (per country) + Pillar 3 CR6 (per class)
# =============================================================================

_R25_MULTI_SHEET_TEMPLATES = ("c09_01", "c09_02", "cr6")


@pytest.mark.parametrize("template_id", _R25_MULTI_SHEET_TEMPLATES)
def test_r25_multi_sheet_templates_are_instrumented(template_id: str) -> None:
    # Assert — each R25 template is instrumented as a PER-SHEET provider
    # (single_frame False -> its cells carry a sheet axis), with a populated scope
    # and a sheet label naming that axis (c09_01/c09_02 by country, cr6 by
    # exposure class).
    assert lineage.is_instrumented(template_id)
    provider = lineage.LINEAGE_PLANS[template_id]
    assert provider.single_frame is False
    assert provider.scope
    assert provider.sheet_label != ""


def test_c09_01_two_basis_primary_drills_applied_class_memo_drills_original() -> None:
    # Arrange — a defaulted corporate leg whose APPLIED class moved to 'defaulted'
    # (reporting_class_origin) while its ORIGINAL class stayed corporate
    # (exposure_class), alongside a live non-defaulted corporate leg. No risk_type
    # column, so the C 07.00 population is just the standardised book.
    frame = pl.DataFrame(
        {
            "exposure_reference": ["CORP-LIVE", "CORP-DEF"],
            "reporting_approach_origin": ["standardised", "standardised"],
            "reporting_class_origin": ["corporate", "defaulted"],
            "exposure_class": ["corporate", "corporate"],
            "is_defaulted": [False, True],
            "cp_country_code": ["GB", "GB"],
            "ead_gross": [5000.0, 2000.0],
            "ead_final": [5000.0, 2000.0],
            "rwa_final": [3500.0, 3000.0],
        }
    )
    resolver = lineage.sheet_lineage(_FrameSource(frame), "c09_01", "TOTAL")
    assert resolver is not None

    # Act — row 0070 (Corporates): col 0090 is a PRIMARY RWEA cell (applied basis),
    # col 0020 is the defaulted MEMORANDUM (original basis + defaulted).
    primary = resolver.cell("0070", "0090")
    memo = resolver.cell("0070", "0020")

    # Assert — the primary cell drills the APPLIED-class leg only (the live
    # corporate, keyed on reporting_class_origin); the 0020 memo drills the
    # ORIGINAL-class defaulted leg only (keyed on exposure_class + defaulted). The
    # two cells of the SAME row select DIFFERENT legs — the two-basis model.
    assert primary is not None and memo is not None
    assert primary.cell_value == pytest.approx(3500.0)
    assert set(primary.rows["exposure_reference"].to_list()) == {"CORP-LIVE"}
    assert memo.cell_value == pytest.approx(2000.0)
    assert set(memo.rows["exposure_reference"].to_list()) == {"CORP-DEF"}


def test_cr6_defaulted_leg_drills_in_the_100pct_band() -> None:
    # Arrange — a defaulted F-IRB corporate leg whose model PD (0.02) would band in
    # row 10, but Annex XXII forces all defaulted exposures into the 100% band (row
    # 17) via the derived cr6_alloc_pd column.
    frame = pl.DataFrame(
        {
            "exposure_reference": ["CORP-DEF"],
            "reporting_approach_origin": ["foundation_irb"],
            "reporting_class_origin": ["corporate"],
            "exposure_class": ["corporate"],
            "reporting_on_balance_sheet": [True],
            "is_defaulted": [True],
            "pd_floored": [0.02],
            "reporting_ead": [1000.0],
            "ead_final": [1000.0],
            "rwa_final": [1500.0],
        }
    )
    resolver = lineage.sheet_lineage(_FrameSource(frame), "cr6", "corporate")
    assert resolver is not None

    # Act — col e (EAD) on the 100% band (row 17) vs the leg's model-PD band (row 10).
    band_100 = resolver.cell("17", "e")
    band_model = resolver.cell("10", "e")

    # Assert — the defaulted leg lands in the 100% band (forced by cr6_alloc_pd),
    # not its model-PD band; row 10 has no legs and renders an empty (null) band.
    assert band_100 is not None
    assert band_100.total_rows == 1
    assert band_100.cell_value == pytest.approx(1000.0)
    assert set(band_100.rows["exposure_reference"].to_list()) == {"CORP-DEF"}
    assert band_model is not None
    assert band_model.total_rows == 0
    assert band_model.cell_value is None


# =============================================================================
# R26 — the CR9 family (per approach x leaf class, Basel 3.1 only) + CR10 (per
# subtemplate). The FINAL instrumentation item.
# =============================================================================

_R26_TEMPLATES = ("cr9", "cr9_1", "cr10")


@pytest.mark.parametrize("template_id", _R26_TEMPLATES)
def test_r26_templates_are_instrumented(template_id: str) -> None:
    # Assert — each R26 template is instrumented as a PER-SHEET provider
    # (single_frame False -> its cells carry a sheet axis), with a populated scope
    # and a sheet label naming that axis (cr9/cr9_1 by approach and leaf class, cr10
    # by subtemplate).
    assert lineage.is_instrumented(template_id)
    provider = lineage.LINEAGE_PLANS[template_id]
    assert provider.single_frame is False
    assert provider.scope
    assert provider.sheet_label != ""


def _cr9_b31_frame() -> pl.DataFrame:
    """Two F-IRB and one A-IRB corporate legs — an obligor-basis CR9 book. Absent
    the SME / financial-large discriminators, the corporate legs collapse onto the
    non-SME leaf (`corporate_other_non_sme`) under both approaches."""
    return pl.DataFrame(
        {
            "exposure_reference": ["FIRB-1", "FIRB-2", "AIRB-1"],
            "counterparty_reference": ["CP-1", "CP-2", "CP-3"],
            "exposure_class": ["corporate", "corporate", "corporate"],
            "approach_applied": ["foundation_irb", "foundation_irb", "advanced_irb"],
            "reporting_approach_origin": ["foundation_irb", "foundation_irb", "advanced_irb"],
            "reporting_class_origin": ["corporate", "corporate", "corporate"],
            "pd": [0.01, 0.01, 0.02],
            "pd_floored": [0.01, 0.01, 0.02],
            "reporting_ead": [1000.0, 2000.0, 1500.0],
            "ead_final": [1000.0, 2000.0, 1500.0],
            "is_defaulted": [False, False, False],
        }
    )


def test_cr9_plans_key_on_the_compound_approach_and_leaf_class() -> None:
    # Arrange — the F-IRB/A-IRB corporate book (Basel 3.1 only).
    from rwa_calc.reporting.pillar3.cr9 import cr9_plans, generate_cr9

    frame = _cr9_b31_frame()
    cols = set(frame.columns)

    # Act — the plans and the reported generator both key by the COMPOUND
    # "approach - leaf class" sheet key.
    plans = cr9_plans(frame.lazy(), cols, "BASEL_3_1", [])
    generated = generate_cr9(frame.lazy(), cols, "BASEL_3_1", [])

    # Assert — the two F-IRB legs and the one A-IRB leg produce the two compound
    # sheets, and plans() / generate() key identically (the lineage contract).
    assert set(plans) == {
        "foundation_irb - corporate_other_non_sme",
        "advanced_irb - corporate_other_non_sme",
    }
    assert set(generated) == set(plans)

    # A band cell drills to the band's legs: the two F-IRB legs at PD 1% band in
    # row 10 (1.00 to < 2.50%); col c counts their two distinct obligors.
    resolver = lineage.sheet_lineage(
        _FrameSource(frame, "BASEL_3_1"), "cr9", "foundation_irb - corporate_other_non_sme"
    )
    assert resolver is not None
    obligors = resolver.cell("10", "c")
    assert obligors is not None
    assert (obligors.query.kind, obligors.query.metric) == ("rows", "count")
    assert obligors.total_rows == 2
    assert obligors.cell_value == pytest.approx(2.0)


def test_cr9_degrades_to_no_lineage_under_crr() -> None:
    # Arrange — CR9 is Basel 3.1 only; its plans() yield nothing under a CRR run.
    frame = _cr9_b31_frame()

    # Act / Assert — a CRR lineage request degrades to a clean no-lineage (the CMS
    # pattern), never a crash.
    assert lineage.sheet_lineage(_FrameSource(frame, "CRR"), "cr9") is None


def test_cr9_1_seeded_frame_plans_and_generate_key_identically() -> None:
    # Arrange — CR9.1 is EMPTY on the real portfolio (the engine produces neither
    # ecai_pd_mapping nor external_rating_equivalent), so it has no acceptance
    # tie-out; a seeded ECAI frame exercises the instrumentation instead.
    from rwa_calc.reporting.pillar3.cr9 import cr9_1_plans, generate_cr9_1

    frame = pl.DataFrame(
        {
            "exposure_reference": ["A-1", "A-2"],
            "counterparty_reference": ["CP-1", "CP-2"],
            "exposure_class": ["corporate", "corporate"],
            "approach_applied": ["advanced_irb", "advanced_irb"],
            "reporting_approach_origin": ["advanced_irb", "advanced_irb"],
            "reporting_class_origin": ["corporate", "corporate"],
            "ecai_pd_mapping": [True, True],
            "external_rating_equivalent": ["BBB", "BBB"],
            "pd": [0.01, 0.01],
            "pd_floored": [0.01, 0.01],
            "reporting_ead": [1000.0, 2000.0],
            "ead_final": [1000.0, 2000.0],
            "is_defaulted": [False, False],
        }
    )
    cols = set(frame.columns)

    # Act
    plans = cr9_1_plans(frame.lazy(), cols, "BASEL_3_1", [])
    generated = generate_cr9_1(frame.lazy(), cols, "BASEL_3_1", [])

    # Assert — the seeded ECAI book produces the one compound sheet, keyed
    # identically by plans() and generate(); the grade row drills to its legs.
    assert set(plans) == {"advanced_irb - corporate_other_non_sme"}
    assert set(generated) == set(plans)
    resolver = lineage.sheet_lineage(
        _FrameSource(frame, "BASEL_3_1"), "cr9_1", "advanced_irb - corporate_other_non_sme"
    )
    assert resolver is not None
    grade = resolver.cell("BBB", "c")
    assert grade is not None
    assert grade.total_rows == 2
    assert grade.cell_value == pytest.approx(2.0)


def test_cr10_fixed_col_c_is_an_unbound_display_weight() -> None:
    # Arrange — one slotting project-finance leg, Category 1 (Strong), long
    # maturity. Col c is the FIXED Art. 153(5) display risk weight, injected
    # post-execute — UNBOUND in the spec (not a measured weighted average).
    frame = pl.DataFrame(
        {
            "exposure_reference": ["PF-1"],
            "reporting_approach_origin": ["slotting"],
            "sl_type": ["project_finance"],
            "slotting_category": ["strong"],
            "reporting_on_balance_sheet": [True],
            "is_short_maturity": [False],
            "reporting_ead": [1000.0],
            "ead_final": [1000.0],
            "rwa_final": [700.0],
            "expected_loss": [5.0],
            "risk_weight": [0.7],
            # The CRR CR10.5 equity sheet is force-emitted (over the empty
            # equity-simple population), and its spec bands on reporting_rw.
            "reporting_rw": [0.7],
        }
    )
    resolver = lineage.sheet_lineage(_FrameSource(frame), "cr10", "project_finance")
    assert resolver is not None

    # Act — row 2 is Category 1 Strong / long maturity (>= 2.5y): its col c renders
    # the fixed 70% weight (x100) from the post-step; col e is the live RWEA sum.
    c_query = resolver.query("2", "c")
    c_result = resolver.cell("2", "c")
    e_query = resolver.query("2", "e")
    e_result = resolver.cell("2", "e")

    # Assert — col c is UNBOUND (the template's empty policy), so the drill-down
    # reports no legs and reads the fixed 70.0 display value from the reported frame
    # — never a binding whose value could differ from the weight on the screen. Col
    # e stays a row-backed Sum that reconciles to the leg's RWEA.
    assert c_query is not None
    assert c_query.kind == "unbound"
    assert c_result is not None
    assert c_result.total_rows == 0
    assert c_result.cell_value == pytest.approx(70.0)
    assert e_query is not None
    assert (e_query.kind, e_query.metric) == ("rows", "sum")
    assert e_result is not None
    assert e_result.total_rows == 1
    assert e_result.cell_value == pytest.approx(700.0)


def test_cr10_equity_col_b_is_unbound_and_col_a_mirrors_col_d() -> None:
    # Arrange — one CRR simple-RW equity leg at a 290% applied risk weight (the
    # Art. 155(2) exchange-traded band, row 2).
    frame = pl.DataFrame(
        {
            "exposure_reference": ["EQ-1"],
            "reporting_approach_origin": ["equity"],
            "equity_method": ["irb_simple"],
            "reporting_rw": [2.9],
            "reporting_ead": [1_000_000.0],
            "ead_final": [1_000_000.0],
            "rwa_final": [2_900_000.0],
            "expected_loss": [0.0],
        }
    )
    resolver = lineage.sheet_lineage(_FrameSource(frame), "cr10", "equity")
    assert resolver is not None

    # Act — row 2 (290% band): col a (on-BS) mirrors col d (exposure value); col b
    # (off-BS) is UNBOUND (equity has no off-balance-sheet component).
    a_result = resolver.cell("2", "a")
    b_query = resolver.query("2", "b")
    b_result = resolver.cell("2", "b")
    d_result = resolver.cell("2", "d")

    # Assert — a == d (the on-BS mirror), and col b is the unbound (null) policy.
    assert a_result is not None and d_result is not None
    assert a_result.cell_value == pytest.approx(1_000_000.0)
    assert d_result.cell_value == pytest.approx(1_000_000.0)
    assert b_query is not None
    assert b_query.kind == "unbound"
    assert b_result is not None
    assert b_result.cell_value is None


# =============================================================================
# R27a — the C 34 counterparty-credit-risk templates (single frame)
# =============================================================================

_R27A_TEMPLATES = ("c34_01", "c34_04", "c34_08")


@pytest.mark.parametrize("template_id", _R27A_TEMPLATES)
def test_r27a_c34_templates_are_single_frame_instrumented(template_id: str) -> None:
    # Assert — each R27a C 34 template is instrumented as a SINGLE-FRAME provider
    # (no sheet axis -> cells report sheet=None), with a populated scope and no
    # sheet label. C 34.02 (per netting set) stays imperative (R27b).
    assert lineage.is_instrumented(template_id)
    provider = lineage.LINEAGE_PLANS[template_id]
    assert provider.single_frame is True
    assert provider.scope
    assert provider.sheet_label == ""


def _c34_08_ledger() -> pl.DataFrame:
    """A CCR derivatives ledger: a QCCP, a non-QCCP, and a bilateral leg (the R5
    fixture shape). Only the two CCP legs may reach C 34.08."""
    return pl.DataFrame(
        {
            "exposure_reference": ["ccr__NS_QCCP", "ccr__NS_NONQCCP", "ccr__NS_BILAT"],
            "risk_type": ["CCR_DERIVATIVE", "CCR_DERIVATIVE", "CCR_DERIVATIVE"],
            "cp_entity_type": ["ccp", "ccp", "institution"],
            "cp_is_qccp": [True, False, None],
            "reporting_class_origin": ["institution", "institution", "institution"],
            "reporting_ead": [1_000_000.0, 2_000_000.0, 3_000_000.0],
            "ead_final": [1_000_000.0, 2_000_000.0, 3_000_000.0],
            "rwa_final": [20_000.0, 200_000.0, 1_500_000.0],
        },
        schema_overrides={"cp_is_qccp": pl.Boolean},
    )


def test_c34_08_lineage_preserves_the_r5_ccp_restriction() -> None:
    # Arrange — the R5 ledger through the C 34.08 lineage resolver (single frame).
    frame = _c34_08_ledger()
    resolver = lineage.sheet_lineage(_FrameSource(frame), "c34_08")
    assert resolver is not None

    # Act — row 0010 (QCCP) drills the qualifying CCP leg only; row 0020 (non-QCCP)
    # drills the non-qualifying CCP leg only — NOT the bilateral (institution) one.
    qccp = resolver.cell("0010", "0010")
    non_qccp = resolver.cell("0020", "0010")

    # Assert — the bilateral 3m leg reaches NEITHER row (the R5 CCP restriction),
    # and each row's drill-down reconciles to its own single CCP leg.
    assert qccp is not None
    assert qccp.total_rows == 1
    assert qccp.cell_value == pytest.approx(1_000_000.0)
    assert non_qccp is not None
    assert non_qccp.total_rows == 1
    assert non_qccp.cell_value == pytest.approx(2_000_000.0)
    assert 3_000_000.0 not in set(non_qccp.rows["ead_final"].to_list())


def _c34_04_seeded_frame() -> pl.DataFrame:
    """A Basel-3.1 CCR ledger carrying a broadcast ``cva_rwa`` constant."""
    return pl.DataFrame(
        {
            "exposure_reference": ["ccr__NS_CVA", "LN-1"],
            "risk_type": ["CCR_DERIVATIVE", None],
            "reporting_class_origin": ["institution", "corporate"],
            "reporting_ead": [1_000.0, 500.0],
            "ead_final": [1_000.0, 500.0],
            "rwa_final": [500.0, 100.0],
            "cva_rwa": [4_429_997.983, 4_429_997.983],
        }
    )


def test_c34_04_seeded_frame_plans_and_generate_key_identically() -> None:
    # Arrange — C 34.04 (CVA) has no producing golden fixture (the CCR portfolio
    # carries no CVA counterparties), so it has no acceptance tie-out; a seeded
    # frame with a broadcast cva_rwa exercises the instrumentation instead.
    from rwa_calc.reporting.corep.c34 import c34_04_frames, c34_04_plans

    frame = _c34_04_seeded_frame()
    cols = set(frame.columns)

    # Act
    plans = c34_04_plans(frame.lazy(), cols, "BASEL_3_1", [])
    generated = c34_04_frames(frame.lazy(), cols, "BASEL_3_1", [])

    # Assert — the one CVA plan is keyed identically by plans() and generate(); the
    # cell reads the portfolio BA-CVA roll-up as a FirstNonNull broadcast constant.
    assert set(plans) == {"c34_04"}
    assert set(generated) == set(plans)
    resolver = lineage.sheet_lineage(_FrameSource(frame, "BASEL_3_1"), "c34_04")
    assert resolver is not None
    cell = resolver.cell("0010", "0010")
    assert cell is not None
    assert (cell.query.kind, cell.query.metric) == ("rows", "first_non_null")
    assert cell.cell_value == pytest.approx(4_429_997.983)


def test_c34_04_degrades_to_no_lineage_under_crr() -> None:
    # Arrange — C 34.04 is Basel 3.1 only; its plans() yield nothing under CRR.
    frame = _c34_04_seeded_frame()

    # Act / Assert — a CRR lineage request degrades to a clean no-lineage (the
    # CMS/OF 02.01 pattern), never a crash.
    assert lineage.sheet_lineage(_FrameSource(frame, "CRR"), "c34_04") is None


# =============================================================================
# Sheet-key resolution — multi-sheet vs the single-frame {sheet: None} convention
# =============================================================================


def _stub_plan() -> SheetPlan:
    """A minimal SheetPlan — enough for the key-only resolution helper."""
    return SheetPlan(
        spec=TemplateSpec(name="t", rows=(), column_refs=(), cells={}, empty_cell="zero"),
        frame=pl.DataFrame(),
        ctx=ReportingContext(),
        negative_cols=frozenset(),
    )


def test_resolve_sheet_key_multi_sheet_defaults_to_first_and_rejects_unknown() -> None:
    # Arrange
    plans = {"corporate": _stub_plan(), "retail": _stub_plan()}

    # Act / Assert — sheet=None defaults to the first sheet; a named sheet
    # resolves to itself; an unknown sheet is unresolvable (a clean no-lineage).
    assert lineage._resolve_sheet_key(plans, None, single_frame=False) == ("corporate", "corporate")
    assert lineage._resolve_sheet_key(plans, "retail", single_frame=False) == ("retail", "retail")
    assert lineage._resolve_sheet_key(plans, "nope", single_frame=False) is None


def test_resolve_sheet_key_single_frame_always_reports_sheet_none() -> None:
    # Arrange — a single-frame template keys its one plan under a canonical key.
    plans = {"__single__": _stub_plan()}

    # Act / Assert — the sheet param is ignored; the reported sheet is None.
    assert lineage._resolve_sheet_key(plans, None, single_frame=True) == ("__single__", None)
    assert lineage._resolve_sheet_key(plans, "anything", single_frame=True) == ("__single__", None)


@dataclass(frozen=True)
class _Row:
    """A structural TemplateRow for a synthetic spec."""

    ref: str
    name: str


class _FrameSource:
    """A minimal ResultsSource over a hand-built frame (no parquet round-trip)."""

    def __init__(self, frame: pl.DataFrame, framework: str = "CRR") -> None:
        self._frame = frame
        self.framework = framework

    def scan_results(self) -> pl.LazyFrame:
        return self._frame.lazy()


def _single_frame_provider() -> tuple[lineage._Provider, pl.DataFrame]:
    """A synthetic single-frame template: one plan, one Sum cell, sheet=None."""
    frame = pl.DataFrame(
        {
            "reporting_class_origin": ["corporate", "corporate"],
            "rwa_final": [100.0, 50.0],
            "exposure_reference": ["E1", "E2"],
        }
    )
    spec = TemplateSpec(
        name="t_demo",
        rows=(_Row("0010", "Total"),),
        column_refs=("0220",),
        cells={("0010", "0220"): CellSpec(Sum("rwa_final"))},
        empty_cell="zero",
    )
    ctx = ReportingContext()
    plan = SheetPlan(spec=spec, frame=frame, ctx=ctx, negative_cols=frozenset())

    def _plans(
        _results: pl.LazyFrame, _cols: set[str], _framework: str, _errors: list[str]
    ) -> dict[str, SheetPlan]:
        return {"__single__": plan}

    def _generate(
        _results: pl.LazyFrame, _cols: set[str], _framework: str, _errors: list[str]
    ) -> dict[str, pl.DataFrame]:
        return {"__single__": execute(spec, frame, ctx)}

    provider = lineage._Provider(
        plans=_plans,
        generate=_generate,
        scope=("demo scope",),
        sheet_label="",
        single_frame=True,
    )
    return provider, frame


def test_single_frame_template_resolves_end_to_end_with_sheet_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange — register a synthetic single-frame provider.
    provider, frame = _single_frame_provider()
    monkeypatch.setitem(lineage.LINEAGE_PLANS, "t_demo", provider)

    # Act — no sheet named (the single-frame caller passes None).
    result = lineage.drilldown(_FrameSource(frame), "t_demo", "0010", "0220")

    # Assert — the cell resolves, its sheet axis is None, and its legs sum back.
    assert result is not None
    assert result.query.sheet is None
    assert result.cell_value == pytest.approx(150.0)
    assert result.contribution_total == pytest.approx(150.0)
    assert result.total_rows == 2
    # A single-frame template adds no "Sheet: … = …" scope line.
    assert not any("Sheet:" in step for step in result.query.scope)
