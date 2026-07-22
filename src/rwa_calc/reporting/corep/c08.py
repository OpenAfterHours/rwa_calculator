"""
COREP C 08.01/02/03/04/05/06/07 — IRB credit risk, declarative.

Pipeline position:
    sealed aggregator-exit ledger -> _prepare() -> per-template TemplateSpecs
    (C 08.01 static rows; C 08.02 data-driven grade/PD-band rows; C 08.03/05
    sparse PD-range rows; C 08.04 fixed flow rows; C 08.06 per-SL-type
    category x maturity rows; C 08.07 scope-of-use class rows over the FULL
    population) -> cellspec.execute() -> dict[class, DataFrame] each
    (C 08.07: one DataFrame | None)

Cell semantics (recorded decisions, this slice):

- All five dicts key the sealed ``reporting_class_origin`` (== raw
  ``exposure_class`` for IRB rows — the obligor basis, number-neutral
  convergence; no applied-class ladder and NO specialised-lending merge,
  unlike C 07.00). The population is the origin IRB book keyed on
  ``reporting_approach_origin`` (F-IRB / A-IRB / slotting); C 08.03/04/05
  exclude slotting per template. C 08.07 alone keeps the RAW class key
  (Art. 147 origination taxonomy over the FULL population).
- C 08.01/02 share one value surface (computed framework-agnostic, filtered
  by each framework's column refs): gross exposures, the CRM waterfall
  0090 = 0020 - 0040 - 0050 - 0060 - 0070 + 0080 over POSITIVE magnitudes,
  the cross-sheet substitution inflow (0080, C 08.01 Total row only; C 08.02 excludes it) via
  ``ReportingContext.substitution_inflow``, the two "of which: off balance
  sheet" memo columns on their RECORDED bases (R11): 0100 (POST-CRM PRE-CCF
  group) = the off-BS slice of the 0090 waterfall, derived per row in
  ``_c08_off_bs_pre_ccf`` over ``c08_bs == "off"`` legs (the 0080 inflow is
  excluded — a total-row cross-sheet scalar with no leg-level BS attribution);
  0120 (EXPOSURE VALUE post-CCF group) = Sum(ead_final) over the off-BS legs,
  EAD-weighted PD/LGD, maturity
  in DAYS (x365 — ``irb_maturity_m`` is years despite the suffix), LFSE
  sub-splits gated on ``cp_apply_fi_scalar`` presence, defaulted sub-splits
  via the retired detection ladder, CRR supporting-factor deltas (the
  asymmetric dedicated flag names preserved), B31 adjustment/output-floor
  columns, and the provisions ladder (SCRA/GCRA sums falling back, when they
  net to ~0, to ``provision_held`` if the frame carries it else the sealed
  ``provision_allocated`` — R10b; a value-dependent PER-CELL branch applied as
  a module post-step). The Annex II §1.3 "(-)" negation covers
  the CRM substitution outflows 0040/0050/0060/0070 (both frameworks), B31's
  on-BS netting adjustment 0035 and slotting FCCM adjustments 0102/0103
  (structural-null today), the CRR supporting-factor adjustments 0256/0257,
  and provisions 0290 — applied AFTER the CRM waterfall (0090) has consumed
  the positive magnitudes, with a zero deduction normalised to ``+0.0``.
  Lineage-instrumented (R23): ``c08_01_plans`` / ``c08_02_plans`` expose the
  per-class execution plans, passing ``_NEGATIVE_COLS`` explicitly so the
  drill-down's sign-aware reconciliation holds on the negated columns (0256
  non-zero on corporate_sme). C 08.01's plans thread the real per-class
  substitution inflow, so the Total-row col 0080 (``SideContext``) drills to its
  real value (the C 07.00 pattern); C 08.02's per-grade 0080 is a constant 0.0
  (R12) and its String label col 0005 is skipped by the tie-out value-column sweep.
  Ratchet note (R23/R24): each extraction bumped ``max_reporting_module_loc``
  (2016 -> post-R23 -> 2320 post-R24, zero slack) — the mechanical additive
  cost of exposing each template's cells/plans builders with their mandated
  docstrings, no behaviour change. Unlike the c07/cr4/cr8/cr7a extractions this
  module alone needs a bump per wave: it hosts SEVEN templates in one file.
  R24 added the ``c08_03_plans`` / ``c08_05_plans`` / ``c08_06_plans`` builders
  (and split ``_c08_03_cells`` / ``_c08_05_cells`` and the c08_06 row helpers
  out of their generators). Splitting c08.py per-template is the honest
  long-term answer — recorded as a deferred follow-up (shared value surface,
  its own risky item).
- The EL memo columns 0280 (pre post-model adjustment) and its B31 twin 0282
  (after post-model adjustments) coalesce PER LEG (R10a): they read the
  formula-IRB ``el_pre_adjustment`` / ``el_after_adjustment`` where non-null
  else the base ``expected_loss``. The adjustment columns exist whenever ANY
  formula-IRB leg exists in the run but are NULL on slotting legs (their EL
  comes from the slotting calculator, on ``expected_loss``), so the retired
  Sum-with-null-fill reported a masked 0.0 for slotting EL on those sheets
  while C 08.06 col 0090 (Sum ``expected_loss``) reported it correctly; the
  coalesce is a value no-op on formula-IRB legs (el_pre == expected_loss
  there) and surfaces the real slotting EL on slotting legs. The aggregator
  injects ``el_pre_adjustment`` onto the sealed frame under BOTH frameworks
  (CRR's ``apply_post_model_adjustments`` copies expected_loss into it), so
  the coalesce corrects 0280 for either framework's slotting sheets; B31 alone
  additionally carries 0282 (``el_after_adjustment``). The derived
  ``c08_el_pre`` / ``c08_el_after`` columns are built in ``_prepare``.
- C 08.02's rows are data-driven (distinct firm grades when
  ``cp_internal_rating_grade`` has values, else the populated fixed PD
  bands, plus an "Unassigned" residual); ``row_ref == row_name == the
  String column 0005``, injected post-execute — the CR9.1 pattern.
- RECORDED DECISION (R12) — the cross-class substitution INFLOW (col 0080,
  and hence its contribution to the 0090 waterfall) is DELIBERATELY EXCLUDED
  from C 08.02: 0080 stays 0.0 on every grade row (``is_total=False`` for all
  rows, so no ``SideContext`` inflow reaches it). Two facts about the sealed
  origin-basis ledger make per-grade attribution unsound, not merely omitted:
  (i) C 08 keys ``reporting_class_origin`` (the obligor basis — a recorded
  number-neutral convergence decision), so a guaranteed leg substituted from
  class X into class Y physically sits in X's ORIGIN sheet, reported there as
  an OUTFLOW (col 0070) at the OBLIGOR's grade — the inflow into Y is made of
  legs that live in OTHER sheets, never in Y's partition; (ii) that leg carries
  the OBLIGOR's ``pd_floored`` / ``cp_internal_rating_grade``, NEVER the
  guarantor's — IRB parameter substitution computes the guarantor RW/EL inside
  a local swap-restore window without overwriting the leg's own PD/grade
  (``engine/irb/guarantee.py::_apply_parameter_substitution``), and under CRR
  the guarantor is SA-RW-substituted with no guarantor PD grade at all. The
  inflow into Y is a per-destination-class SCALAR
  (``ReportingContext.substitution_inflow``, ``_substitution_inflows`` grouped
  by ``post_crm_exposure_class_guaranteed``) that C 08.01 lands on its
  constraint-free Total row (0010); C 08.02 has NO Total row and no
  origin-basis grade home for a cross-sheet scalar. Banding it to a grade would
  require the GUARANTOR's rating grade sealed per-leg (a deferred engine
  enhancement) — banding by the leg's own grade would misattribute the inflow
  to a foreign obligor's grade in a different class's rating scale. This
  mirrors C 08.01's inflow-on-Total-row-only convention and C 07.00's
  class-level-scalar convention. Reconciliation consequence, pinned as a
  MONITORED divergence (not silent drift): on a destination sheet the sum over
  grade rows of col 0080 == 0.0, which is NOT equal to C 08.01's Total 0080,
  and the sum of col 0090 is short of C 08.01's Total 0090 by exactly the
  inflow; the OUTFLOW side (col 0070) reconciles. Regulatory basis: Reg (EU)
  2021/451 Annex II (C 08.01/02 share the CRM-substitution column block);
  PS1/26 Annex XXII (obligor-basis reporting bars substitution effects from the
  grade breakdown). Pin:
  ``tests/unit/reporting/corep/test_c08_02.py::TestC0802SubstitutionInflowDisposition``.
- C 08.03/05 allocate rows over the 17 fixed PD ranges (B31 allocates on
  the pre-input-floor ``pd``, CRR on ``pd_floored``; the reported PD is
  always post-floor), emit ONLY populated buckets (sparse) plus an
  optional 9999 "Unassigned" row, and C 08.03's on/off-BS gross columns
  keep the retired whole-bucket fallback when the balance-sheet split
  yields nothing. C 08.05's averages are null-filled arithmetic means
  (weighted by a constant-one column), with the CR9-style point-in-time
  fallbacks for the prior-year/historical carriers.
  Lineage-instrumented (R24): ``c08_03_plans`` / ``c08_05_plans`` expose the
  per-class sparse-PD-range plans (the data-driven c08_02 pattern; each row keys
  the derived ``c08_pd_range`` band carried in ``row_terms``). C 08.05 is
  execute-only (R13 deleted the rate postfix). C 08.03's two post-execute passes
  (the on/off-BS whole-bucket fallback on cols 0010/0020; the provisions ladder
  on col 0110) stay on the reported frame the drill-down reads: the fallback
  fires for col 0020 on a loans-only book (off-BS split empty) but is a VALUE
  NO-OP there (both the fallback and the off-BS binding sum to 0.0), recorded as
  a limitation with the tie-out sweep as the tripwire.
- C 08.04 is the CR8-clone flow: only the closing-RWEA cell (row 0090) is
  populated — note its DELIBERATELY two-wide RWA ladder (``rwa_final``,
  ``rwa`` — no ``rwa_post_factor``). Lineage-instrumented (R22): ``c08_04_plans``
  exposes the per-class current-period plans (no prior frame), so its opening
  (row 0010, a ``PriorPeriod`` cell) and residual (row 0080, a ``Formula``
  deriving from it) rows are refused by the drill-down exactly as CR8 refuses
  its rows 1/8; the reported ``generate_c08_04`` keeps threading the prior
  frame.
- C 08.06 keys per-SL-type sheets (CRR's IPRE absorbs HVCRE when
  ``is_hvcre`` exists; B31 splits HVCRE out; empty SL types emit NO sheet)
  over the slotting-only book, with a per-ROW two-branch policy: empty
  non-Total rows zero-fill (0070 = the fixed display risk weight from the
  row definition), live rows and both maturity-split Total rows compute on
  data (0050/0060/0070/0031 null where the retired code reported None).
  CRR's 0080 prefers ``rwa_post_factor``; the maturity fallback is
  asymmetric (no ``is_short_maturity`` column -> short band empty, long
  band absorbs the category); the "substantially stronger" sub-rows are
  unconditionally empty. Lineage-instrumented (R24): ``c08_06_plans`` exposes
  the per-SL-type plans, and because the row set is number-neutral but the
  EMPTY-row set is per-sheet, each sheet gets its OWN spec — an empty non-Total
  row's col 0070 (a fixed display RW, not a measured weighted average) is left
  UNBOUND (``_c08_06_empty_refs``), so the drill-down reports the template's
  empty policy and reads its value from the reported frame rather than a
  WeightedAvg with no legs. The three value-dependent post-passes (empty-row
  zero-fill; the live 0030/0040/0070 fixes; the provisions ladder) stay on the
  reported frame.
- C 08.07 reads the FULL population (SA enters every denominator; null
  approach falls to SA; slotting counts as IRB) keyed on RAW
  ``exposure_class``; percentages are intra-row formulas guarding zero
  denominators to 0.0; the structural-null rows are a FIXED set (empty
  real-class rows stay 0.0 — the opposite of C 07.00's empty-subset rule);
  B31 materiality columns 0160-0180 are always null (the retired
  ``output_floor_config`` gate was dead code, recorded). Col 0040 ("% subject
  to a roll-out plan", CRR Art. 148) carves the roll-out-plan slice out of the
  SA coverage: the SA-treated legs (``~c0807_irb``) flagged by the optional
  ``is_under_irb_rollout`` INPUT column go to 0040 and col 0030 drops to
  permanent-partial-use only (Art. 150), preserving 0030 + 0040 == the whole SA
  %. Absent the input column the slice is empty, 0040 = 0.0 and 0030 keeps the
  whole SA share (byte-identical to the pre-R14 output). Col 0040 first carries
  the roll-out EAD Sum and is rescaled to a percentage post-execute
  (``_c08_07_rollout_pct``). Lineage-instrumented (R22, single frame):
  ``c08_07_plans`` exposes the one full-population plan; the two post-execute
  passes (col-0040 rescale, ``_null_fixed_rows``) stay on the reported frame
  (``c08_07_frames``), which the drill-down reads a cell's value from.

References:
- CRR Art. 142-191 (IRB); Art. 153 (risk weights), Art. 180 (PD
  validation), Art. 501/501a (supporting factors); Reg (EU) 2021/451
  Annex I/II (C 08.0x); PRA PS1/26 Annex I/II (OF 08.0x)
- docs/plans/phase7-declarative-reporting.md §3.2/§6 (S8)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import polars as pl
from watchfire import cites

from rwa_calc.reporting.cellspec import (
    CellSpec,
    Count,
    Formula,
    PriorPeriod,
    RowPredicate,
    SafeSum,
    SideContext,
    Sum,
    TemplateSpec,
    WeightedAvg,
    execute,
    matched_counts,
    subset_rows,
)
from rwa_calc.reporting.corep.templates import (
    C08_03_PD_RANGES,
    C08_04_ROWS,
    C08_06_CATEGORY_MAP,
    C08_07_CRR_RETAIL_CLASSES,
    C08_07_IRB_APPROACHES,
    PD_BANDS,
    get_c08_02_columns,
    get_c08_03_columns,
    get_c08_04_columns,
    get_c08_05_columns,
    get_c08_06_columns,
    get_c08_06_rows,
    get_c08_06_sl_types,
    get_c08_07_columns,
    get_c08_07_rows,
    get_c08_columns,
    get_irb_row_sections,
)
from rwa_calc.reporting.kernel import (
    available_columns,
    col_sum,
    gross_carrier,
    gross_carriers,
    pick,
    safe_sum,
)
from rwa_calc.reporting.metadata import ReportingContext
from rwa_calc.reporting.plans import SheetPlan

if TYPE_CHECKING:
    from collections.abc import Mapping

# Annex II §1.3 "(-)"-labelled deduction columns on the C 08.01/02 surface,
# negated post-execute (AFTER the CRM waterfall consumes positive magnitudes):
# the CRM substitution outflows 0040/0050/0060/0070 (both frameworks), B31's
# on-balance-sheet netting adjustment 0035, B31's slotting financial-collateral
# adjustments 0102/0103 (structural-null today — the negation is a no-op that
# keeps the sign truthful if a carrier is ever wired), the CRR supporting-factor
# adjustments 0256/0257, and value adjustments/provisions 0290. The set is
# framework-guarded by intersection with the frame's columns in ``_negate`` —
# 0035/0102/0103 (B31-only) and 0256/0257 (CRR-only) are absent no-ops in the
# other regime.
_NEGATIVE_COLS: frozenset[str] = frozenset(
    {"0035", "0040", "0050", "0060", "0070", "0102", "0103", "0256", "0257", "0290"}
)

_IRB_APPROACHES: tuple[str, ...] = ("foundation_irb", "advanced_irb", "slotting")

# Single-frame lineage key: C 08.07 has no sheet axis, so its one plan keys
# under a canonical name (see reporting.plans / _resolve_sheet_key single_frame).
_C08_07_SHEET_KEY = "c08_07"

_Terms = tuple[tuple[str, str | bool], ...]
type _EmptyCell = Literal["zero", "null"]


class _Row:
    """Minimal TemplateRow for data-driven row axes."""

    __slots__ = ("name", "ref")

    def __init__(self, ref: str, name: str) -> None:
        self.ref = ref
        self.name = name


def _const(value: float | None):  # noqa: ANN202 - tiny Formula factory
    def fn(_cells: Mapping[str, float | None], _prior: bool) -> float | None:
        return value

    return fn


def _crm_waterfall(cells: Mapping[str, float | None], _prior: bool) -> float | None:
    """0090 = 0020 - 0040 - 0050 - 0060 - 0070 + 0080 (positive magnitudes)."""
    return (
        (cells["0020"] or 0.0)
        - (cells["0040"] or 0.0)
        - (cells["0050"] or 0.0)
        - (cells["0060"] or 0.0)
        - (cells["0070"] or 0.0)
        + (cells["0080"] or 0.0)
    )


def _copy_of_0040(cells: Mapping[str, float | None], _prior: bool) -> float | None:
    return cells["0040"]


def _observed_rate(cells: Mapping[str, float | None], _prior: bool) -> float | None:
    """C 08.05 col 0040 = col 0030 / col 0020 as rendered (0.0 when no obligors).

    The denominator is col 0020 — the obligor count at the start of the
    observation period (prior-year cohort when ``prior_year_obligor_count`` is
    supplied, else the current-period fallback col 0020 itself reports). Col
    0030 (defaulted during the year) over col 0020 is the accepted cross-period
    proxy for the observed default rate; keeping the denominator equal to col
    0020 makes the disclosure internally consistent (Annex II C 08.05).
    """
    obligors = cells["0020"] or 0.0
    if obligors <= 0:
        return 0.0
    return (cells["0030"] or 0.0) / obligors


def _c08_04_other_flow(cells: Mapping[str, float | None], prior_available: bool) -> float | None:
    """C 08.04 row 0080 (Other) = closing(0090) - opening(0010) with a prior
    period, else null (the CR8 row-8 convention; a None side coerces to zero —
    PS1/26 Annex XXII paragraph 11)."""
    if not prior_available:
        return None
    return (cells["0090"] or 0.0) - (cells["0010"] or 0.0)


# =============================================================================
# Shared population + derived discriminators
# =============================================================================


def _irb_population(results: pl.LazyFrame, cols: set[str]) -> pl.LazyFrame:
    """The IRB book (retired _filter_by_irb_approach): F-IRB/A-IRB/slotting."""
    approach_col = pick(cols, "reporting_approach_origin")
    if approach_col is None:
        return results.filter(pl.lit(value=False))
    return results.filter(pl.col(approach_col).is_in(list(_IRB_APPROACHES)))


def _prepare(data: pl.DataFrame, cols: set[str]) -> pl.DataFrame:
    """Add the module-derived discriminator columns (each only when its
    sources exist — underived columns make their tolerant terms match
    nothing, reproducing the retired absent-column behaviour)."""
    exprs: list[pl.Expr] = [pl.lit(1.0).alias("c08_one")]

    # Defaulted ladder (retired _filter_defaulted precedence).
    if "is_defaulted" in cols:
        exprs.append(pl.col("is_defaulted").fill_null(value=False).alias("c08_defaulted"))
    elif "default_status" in cols:
        exprs.append((pl.col("default_status") == True).alias("c08_defaulted"))  # noqa: E712
    elif "exposure_class_applied" in cols or "exposure_class" in cols:
        class_col = (
            "exposure_class_applied" if "exposure_class_applied" in cols else "exposure_class"
        )
        exprs.append((pl.col(class_col) == "defaulted").alias("c08_defaulted"))
    elif "pd_floored" in cols:
        exprs.append((pl.col("pd_floored") >= 1.0).alias("c08_defaulted"))

    # Substitution flag (retired outflow filter: gp>0 and pre != post).
    if {"guaranteed_portion", "pre_crm_exposure_class", "post_crm_exposure_class_guaranteed"} <= (
        cols
    ):
        exprs.append(
            (
                (pl.col("guaranteed_portion") > 0)
                & (pl.col("pre_crm_exposure_class") != pl.col("post_crm_exposure_class_guaranteed"))
            )
            .fill_null(value=False)
            .alias("c08_substituted")
        )
    else:
        exprs.append(pl.lit(value=False).alias("c08_substituted"))

    # On/off-balance-sheet (kernel rule: bs_type preferred, else exposure_type).
    if "bs_type" in cols:
        exprs.append(
            pl.when(pl.col("bs_type") == "ONB")
            .then(pl.lit("on"))
            .when(pl.col("bs_type") == "OFB")
            .then(pl.lit("off"))
            .otherwise(pl.lit(None, dtype=pl.String))
            .alias("c08_bs")
        )
    elif "exposure_type" in cols:
        exprs.append(
            pl.when(pl.col("exposure_type") == "loan")
            .then(pl.lit("on"))
            .when(pl.col("exposure_type").is_in(["facility", "contingent"]))
            .then(pl.lit("off"))
            .otherwise(pl.lit(None, dtype=pl.String))
            .alias("c08_bs")
        )

    # Supporting-factor RWEA delta (CRR cols 0256/0257).
    if "rwa_pre_factor" in cols:
        rwa_source = pick(cols, "rwa_final", "rwa_post_factor", "rwa")
        if rwa_source is not None:
            exprs.append(
                (pl.col("rwa_pre_factor").fill_null(0.0) - pl.col(rwa_source).fill_null(0.0)).alias(
                    "c08_sf_delta"
                )
            )

    # B31 section-3 unrated-corporate discriminators (retired
    # _filter_section3_unrated_corp / _filter_section3_unrated_ig).
    if "exposure_class" in cols:
        corp = (
            pl.col("exposure_class").str.contains("corporate", literal=True).fill_null(value=False)
        )
        unrated = pl.col("sa_cqs").is_null() if "sa_cqs" in cols else pl.lit(value=True)
        exprs.append((corp & unrated).alias("c08_unrated_corp"))
        if "cp_is_investment_grade" in cols:
            ig = pl.col("cp_is_investment_grade").fill_null(value=False) == True  # noqa: E712
            exprs.append((corp & unrated & ig).alias("c08_unrated_ig"))
        elif "pd_floored" in cols:
            exprs.append((corp & unrated & (pl.col("pd_floored") <= 0.005)).alias("c08_unrated_ig"))

    # Col 0280/0282 expected-loss coalesce (R10a). The formula-IRB post-model-
    # adjustment EL columns (``el_pre_adjustment`` / ``el_after_adjustment``,
    # engine/irb/adjustments.py::apply_post_model_adjustments) are produced ONLY
    # on the formula-IRB leg, so they are NULL on slotting legs — whose real EL
    # rides on ``expected_loss`` (from the slotting calculator). A plain
    # Sum("el_pre_adjustment") fills those slotting nulls to 0.0, masking the
    # slotting EL that C 08.06 col 0090 reports correctly as Sum("expected_loss").
    # A PER-LEG coalesce reports the formula-IRB adjustment EL where present, else
    # the base expected_loss — a value no-op on formula-IRB legs (el_pre_adjustment
    # == expected_loss there) that surfaces the true slotting EL on slotting legs.
    if "el_pre_adjustment" in cols:
        exprs.append(
            (
                pl.coalesce("el_pre_adjustment", "expected_loss")
                if "expected_loss" in cols
                else pl.col("el_pre_adjustment")
            ).alias("c08_el_pre")
        )
    if "el_after_adjustment" in cols:
        exprs.append(
            (
                pl.coalesce("el_after_adjustment", "expected_loss")
                if "expected_loss" in cols
                else pl.col("el_after_adjustment")
            ).alias("c08_el_after")
        )

    return data.with_columns(exprs)


def _substitution_inflows(irb_df: pl.DataFrame, cols: set[str]) -> dict[str, float]:
    """Per-destination-class substitution inflows (retired
    _compute_substitution_flows, inflow side)."""
    if not (
        {"guaranteed_portion", "pre_crm_exposure_class", "post_crm_exposure_class_guaranteed"}
        <= cols
    ):
        return {}
    migrated = irb_df.filter(pl.col("c08_substituted"))
    if len(migrated) == 0:
        return {}
    grouped = migrated.group_by("post_crm_exposure_class_guaranteed").agg(
        pl.col("guaranteed_portion").fill_null(0.0).sum().alias("inflow")
    )
    return {
        row["post_crm_exposure_class_guaranteed"]: float(row["inflow"])
        for row in grouped.iter_rows(named=True)
    }


# =============================================================================
# The shared C 08.01/02 value surface
# =============================================================================


def _lfse_cell(
    cols: set[str],
    binding_factory,  # noqa: ANN001 - a zero-arg ValueBinding factory
    terms: _Terms,
    *,
    empty: _EmptyCell = "zero",
) -> CellSpec:
    """LFSE sub-split cells: bound over ``cp_apply_fi_scalar == True`` when
    the flag column exists (empty LFSE subsets report 0.0), else the
    recorded constant-None."""
    if "cp_apply_fi_scalar" not in cols:
        return CellSpec(Formula(refs=(), fn=_const(None)))
    return CellSpec(
        binding_factory(),
        predicate=RowPredicate(equals=(*terms, ("cp_apply_fi_scalar", True))),
        empty_cell=empty,
    )


def _sf_adjustment_cell(terms: _Terms, cols: set[str], dedicated: str, flag_col: str) -> CellSpec:
    """CRR supporting-factor adjustment: Σ(rwa_pre_factor - rwa) over the
    applied rows; None when no carrier. ``dedicated`` preserves the retired
    asymmetric flag names."""
    if "rwa_pre_factor" not in cols:
        return CellSpec(Formula(refs=(), fn=_const(None)))
    if dedicated in cols:
        return CellSpec(
            Sum("c08_sf_delta"), predicate=RowPredicate(equals=(*terms, (dedicated, True)))
        )
    if flag_col in cols and "supporting_factor_applied" in cols:
        return CellSpec(
            Sum("c08_sf_delta"),
            predicate=RowPredicate(
                equals=(*terms, (flag_col, True), ("supporting_factor_applied", True))
            ),
        )
    return CellSpec(Formula(refs=(), fn=_const(None)))


def _value_cells(  # noqa: C901, PLR0915 - the full C 08.01/02 column surface
    terms: _Terms,
    cols: set[str],
    ead_col: str,
    rwa_col: str,
    column_refs: tuple[str, ...],
    *,
    is_total: bool,
) -> dict[str, CellSpec]:
    member = RowPredicate(equals=terms)

    def narrowed(*extra: tuple[str, str | bool]) -> RowPredicate:
        return RowPredicate(equals=(*terms, *extra))

    lgd_col = pick(cols, "lgd_floored", "lgd_input")
    cells: dict[str, CellSpec] = {
        "0010": CellSpec(
            WeightedAvg("pd_floored", weight=ead_col), predicate=member, empty_cell="null"
        ),
        "0020": CellSpec(
            SafeSum(gross_carriers(cols, "drawn_amount", "undrawn_amount")), predicate=member
        ),
        "0030": _lfse_cell(
            cols, lambda: SafeSum(gross_carriers(cols, "drawn_amount", "undrawn_amount")), terms
        ),
        "0035": CellSpec(Sum("on_bs_netting_amount"), predicate=member),
        "0040": (
            CellSpec(
                Sum("guaranteed_portion"), predicate=narrowed(("protection_type", "guarantee"))
            )
            if "protection_type" in cols
            else CellSpec(Sum("guaranteed_portion"), predicate=member)
        ),
        "0050": (
            CellSpec(
                Sum("guaranteed_portion"),
                predicate=narrowed(("protection_type", "credit_derivative")),
            )
            if "protection_type" in cols
            else CellSpec(Formula(refs=(), fn=_const(0.0)))
        ),
        "0060": CellSpec(
            SafeSum(
                (
                    "collateral_re_value",
                    "collateral_receivables_value",
                    "collateral_other_physical_value",
                )
            ),
            predicate=member,
        ),
        "0070": CellSpec(Sum("guaranteed_portion"), predicate=narrowed(("c08_substituted", True))),
        "0080": (
            CellSpec(SideContext("substitution_inflow"))
            if is_total
            else CellSpec(Formula(refs=(), fn=_const(0.0)))
        ),
        "0090": CellSpec(
            Formula(refs=("0020", "0040", "0050", "0060", "0070", "0080"), fn=_crm_waterfall)
        ),
        # 0100 ("of which: off balance sheet") sits in the POST-CRM PRE-CCF
        # group (the 0090 waterfall), so it is the off-BS slice of that
        # pre-conversion-factor quantity — filled by ``_c08_off_bs_pre_ccf``
        # post-execute (the executor has no intra-row sub-waterfall verb). The
        # placeholder null is what an inert row keeps (R11).
        "0100": CellSpec(Formula(refs=(), fn=_const(None))),
        "0101": CellSpec(Formula(refs=(), fn=_const(None))),
        "0102": CellSpec(Formula(refs=(), fn=_const(None))),
        "0103": CellSpec(Formula(refs=(), fn=_const(None))),
        "0104": CellSpec(Formula(refs=(), fn=_const(None))),
        "0110": CellSpec(Sum(ead_col), predicate=member),
        # 0120 ("of which: off balance sheet") sits in the EXPOSURE VALUE
        # (post-CCF) group, so it is Sum(ead_final) over the off-BS legs —
        # exactly the basis the old 0100 carried before R11 moved it here.
        "0120": CellSpec(Sum(ead_col), predicate=narrowed(("c08_bs", "off"))),
        "0125": CellSpec(Sum(ead_col), predicate=narrowed(("c08_defaulted", True))),
        "0130": CellSpec(Formula(refs=(), fn=_const(None))),
        "0140": _lfse_cell(cols, lambda: Sum(ead_col), terms),
        "0150": (
            CellSpec(
                Sum("guaranteed_portion"), predicate=narrowed(("protection_type", "guarantee"))
            )
            if "protection_type" in cols
            else CellSpec(Sum("guaranteed_portion"), predicate=member)
        ),
        "0160": (
            CellSpec(
                Sum("guaranteed_portion"),
                predicate=narrowed(("protection_type", "credit_derivative")),
            )
            if "protection_type" in cols
            else CellSpec(Formula(refs=(), fn=_const(0.0)))
        ),
        "0170": CellSpec(Formula(refs=(), fn=_const(0.0))),
        "0171": CellSpec(Formula(refs=(), fn=_const(0.0))),
        "0172": CellSpec(Formula(refs=(), fn=_const(0.0))),
        "0173": CellSpec(Formula(refs=(), fn=_const(0.0))),
        "0180": CellSpec(Sum("collateral_financial_value"), predicate=member),
        "0190": CellSpec(Sum("collateral_re_value"), predicate=member),
        "0200": CellSpec(Sum("collateral_other_physical_value"), predicate=member),
        "0210": CellSpec(Sum("collateral_receivables_value"), predicate=member),
        "0220": CellSpec(Sum("double_default_unfunded_protection"), predicate=member),
        "0230": (
            CellSpec(WeightedAvg(lgd_col, weight=ead_col), predicate=member, empty_cell="null")
            if lgd_col is not None
            else CellSpec(Formula(refs=(), fn=_const(None)))
        ),
        "0240": (
            _lfse_cell(cols, lambda: WeightedAvg(lgd_col, weight=ead_col), terms)
            if lgd_col is not None
            else CellSpec(Formula(refs=(), fn=_const(None)))
        ),
        "0250": CellSpec(
            WeightedAvg("irb_maturity_m", weight=ead_col, scale=365.0),
            predicate=member,
            empty_cell="null",
        ),
        "0251": CellSpec(Sum("rwa_pre_adjustments"), predicate=member),
        "0252": CellSpec(Sum("post_model_adjustment_rwa"), predicate=member),
        "0253": CellSpec(Sum("mortgage_rw_floor_adjustment"), predicate=member),
        "0254": CellSpec(Sum("unrecognised_exposure_adjustment"), predicate=member),
        "0255": CellSpec(
            Sum("rwa_pre_factor" if "rwa_pre_factor" in cols else rwa_col), predicate=member
        ),
        "0256": _sf_adjustment_cell(terms, cols, "sme_supporting_factor_applied", "is_sme"),
        "0257": _sf_adjustment_cell(
            terms, cols, "infrastructure_factor_applied", "is_infrastructure"
        ),
        "0260": CellSpec(Sum(rwa_col), predicate=member),
        "0265": CellSpec(Sum(rwa_col), predicate=narrowed(("c08_defaulted", True))),
        "0270": _lfse_cell(cols, lambda: Sum(rwa_col), terms),
        "0275": CellSpec(Sum(ead_col), predicate=member),
        "0276": (
            CellSpec(Sum("sa_rwa"), predicate=member)
            if "sa_rwa" in cols
            else CellSpec(Formula(refs=(), fn=_const(None)))
        ),
        "0280": CellSpec(
            Sum("c08_el_pre" if "el_pre_adjustment" in cols else "expected_loss"),
            predicate=member,
        ),
        "0281": CellSpec(Sum("post_model_adjustment_el"), predicate=member),
        "0282": CellSpec(
            Sum("c08_el_after" if "el_after_adjustment" in cols else "el_after_adjustment"),
            predicate=member,
        ),
        "0290": CellSpec(
            SafeSum(("scra_provision_amount", "gcra_provision_amount")), predicate=member
        ),
        "0300": (
            CellSpec(Count("counterparty_reference", distinct=True), predicate=member)
            if "counterparty_reference" in cols
            else CellSpec(Count("exposure_reference"), predicate=member)
        ),
        "0310": CellSpec(Sum(rwa_col), predicate=member),
    }
    return {ref: cell for ref, cell in cells.items() if ref in column_refs}


# =============================================================================
# C 08.01
# =============================================================================


def _c08_01_row_terms(framework: str, cols: set[str]) -> dict[str, _Terms | None]:
    """Membership terms per C 08.01 row ref (None = inert all-null row).

    Ports the retired section dispatch: section 1's "of which" rows are
    hardwired null; section 2 splits on/off-BS (B31's CCF-bucket and
    netting-set rows are inert); section 3 splits the origin approach
    (F-IRB/A-IRB vs slotting) plus the B31 unrated-corporate memo rows.
    """
    terms: dict[str, _Terms | None] = {}
    for section_index, section in enumerate(get_irb_row_sections(framework)):
        for row in section.rows:
            ref = row.ref
            if section_index == 0:
                terms[ref] = () if ref == "0010" else None
            elif section_index == 1:
                if ref == "0020":
                    terms[ref] = (("c08_bs", "on"),)
                elif ref == "0030":
                    terms[ref] = (("c08_bs", "off"),)
                else:
                    terms[ref] = None
            elif ref == "0070":
                terms[ref] = None  # composed via any_of below
            elif ref == "0080":
                terms[ref] = (("reporting_approach_origin", "slotting"),)
            elif ref == "0190":
                terms[ref] = (("c08_unrated_corp", True),)
            elif ref == "0200":
                terms[ref] = (("c08_unrated_ig", True),)
            else:
                terms[ref] = None
    return terms


def _c08_01_grades_pred() -> RowPredicate:
    """Row 0070 (obligor grades/pools) — the F-IRB/A-IRB non-slotting union.

    A two-limb ``any_of`` over ``reporting_approach_origin`` (slotting reports on
    row 0080). Defined once and shared by ``_c08_01_spec`` (merges it into every
    0070 cell) and ``_c08_01_row_preds`` (rebuilds it for the generate post-passes),
    so the drill-down's spec and the generator's predicate never drift."""
    return RowPredicate(
        any_of=(
            RowPredicate(equals=(("reporting_approach_origin", "foundation_irb"),)),
            RowPredicate(equals=(("reporting_approach_origin", "advanced_irb"),)),
        )
    )


def _c08_01_spec(framework: str, cols: set[str], ead_col: str, rwa_col: str) -> TemplateSpec:
    """The C 08.01 TemplateSpec for one run (built cols-aware).

    Shared by ``c08_01_plans`` and ``generate_c08_01`` so the drill-down re-runs
    the exact predicate the generator executed. Row 0070 merges the F-IRB/A-IRB
    union into every value cell; other rows carry their ``_c08_01_row_terms``, and
    the Total row (0010) carries the ``SideContext`` inflow (col 0080). ``cols`` is
    the PRE-``_prepare`` base-column set (``_value_cells`` reads it for base-column
    membership only, binding derived columns by name for the executor to resolve)."""
    column_refs = tuple(col.ref for col in get_c08_columns(framework))
    rows = tuple(row for section in get_irb_row_sections(framework) for row in section.rows)
    row_terms = _c08_01_row_terms(framework, cols)
    cells: dict[tuple[str, str], CellSpec] = {}
    for row in rows:
        terms = row_terms.get(row.ref)
        if row.ref == "0070":
            pred = _c08_01_grades_pred()
            for col_ref, cell in _value_cells(
                (), cols, ead_col, rwa_col, column_refs, is_total=False
            ).items():
                merged = (
                    CellSpec(cell.binding, predicate=pred, empty_cell=cell.empty_cell)
                    if cell.predicate is None or not cell.predicate.equals
                    else CellSpec(
                        cell.binding,
                        predicate=RowPredicate(equals=cell.predicate.equals, any_of=pred.any_of),
                        empty_cell=cell.empty_cell,
                    )
                )
                cells[(row.ref, col_ref)] = merged
            continue
        if terms is None:
            continue
        for col_ref, cell in _value_cells(
            terms, cols, ead_col, rwa_col, column_refs, is_total=row.ref == "0010"
        ).items():
            cells[(row.ref, col_ref)] = cell
    return TemplateSpec(
        name="c08_01", rows=rows, column_refs=column_refs, cells=cells, empty_cell="zero"
    )


def _c08_01_row_preds(row_terms: dict[str, _Terms | None]) -> dict[str, RowPredicate | None]:
    """Rebuild the C 08.01 per-row predicates from the plan's row terms.

    The three generate post-passes need each row's ``RowPredicate`` — including row
    0070's ``any_of`` union, which simple equals-terms cannot express — so it is
    rebuilt from the same ``row_terms`` the plan carries (deterministic, so
    identical to the retired inline set). ``None`` = an inert (all-null) row;
    ``()`` = the constraint-free Total row."""
    preds: dict[str, RowPredicate | None] = {}
    for ref, terms in row_terms.items():
        if ref == "0070":
            preds[ref] = _c08_01_grades_pred()
        elif terms is None:
            preds[ref] = None
        else:
            preds[ref] = RowPredicate(equals=terms) if terms else RowPredicate()
    return preds


def c08_01_plans(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, SheetPlan]:
    """Build the per-obligor-class C 08.01 execution plans for lineage.

    Keys the per-class plans on the sealed ``reporting_class_origin`` over the
    WHOLE IRB book (F-IRB / A-IRB / slotting — C 08.01 does NOT exclude slotting),
    preserving ``generate_c08_01``'s error contract. Each plan threads the real
    per-destination-class CRM substitution INFLOW into its ``ReportingContext`` (the
    C 07.00 pattern), so the Total row's col 0080 drills to its real value rather
    than being refused, and passes ``_NEGATIVE_COLS`` EXPLICITLY (the first large
    Annex II §1.3 "(-)" negation set through lineage since C 07.00)."""
    ec_col = pick(cols, "reporting_class_origin")
    ead_col = pick(cols, "ead_final")
    rwa_col = pick(cols, "rwa_final", "rwa_post_factor", "rwa")
    if ec_col is None or ead_col is None or rwa_col is None:
        if ead_col is None or rwa_col is None:
            errors.append("C08.01: Missing EAD or RWA columns")
        if ec_col is None:
            errors.append("C08.01: Missing exposure_class column")
        return {}
    irb_df = _irb_population(results, cols).collect()
    if len(irb_df) == 0:
        return {}
    data_cols = set(irb_df.columns)
    irb_df = _prepare(irb_df, data_cols)
    inflow_map = _substitution_inflows(irb_df, data_cols)
    spec = _c08_01_spec(framework, data_cols, ead_col, rwa_col)
    row_terms = _c08_01_row_terms(framework, data_cols)
    plans: dict[str, SheetPlan] = {}
    for ec in irb_df[ec_col].drop_nulls().unique().sort().to_list():
        plans[ec] = SheetPlan(
            spec=spec,
            frame=irb_df.filter(pl.col(ec_col) == ec),
            ctx=ReportingContext(substitution_inflow=inflow_map.get(ec, 0.0)),
            negative_cols=_NEGATIVE_COLS,
            row_terms=row_terms,
        )
    return plans


@cites("PS1/26, paragraph 1.3")
def generate_c08_01(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, pl.DataFrame]:
    """Execute C 08.01 per obligor-class sheet over the sealed ledger.

    Iterates ``c08_01_plans`` and applies the four post-execute passes on the
    reported frame (the off-BS pre-CCF memo 0100, the all-null inert rows, the
    provisions ladder 0290, the Annex II §1.3 "(-)" negation) — the drill-down
    reads a cell's value from HERE, so it honours every pass. The per-row
    predicates the passes need are rebuilt from the plan's ``row_terms``."""
    result: dict[str, pl.DataFrame] = {}
    for ec, plan in c08_01_plans(results, cols, framework, errors).items():
        row_preds = _c08_01_row_preds(plan.row_terms)
        data_cols = set(plan.frame.columns)
        frame = execute(plan.spec, plan.frame, plan.ctx)
        frame = _c08_off_bs_pre_ccf(frame, plan.frame, row_preds)
        frame = _null_empty_rows(frame, plan.frame, row_preds)
        frame = _provisions_postfix(frame, plan.frame, row_preds, data_cols, ref="0290")
        result[ec] = _negate(frame)
    return result


# =============================================================================
# C 08.02
# =============================================================================


def _c08_02_spec(
    labels: list[str],
    cols: set[str],
    ead_col: str,
    rwa_col: str,
    value_refs: tuple[str, ...],
) -> TemplateSpec:
    """One C 08.02 class sheet's data-driven spec (a row per grade/PD-band label).

    Each row keys the derived ``c08_02_key`` label; the value cells are the shared
    C 08.01/02 surface (``_value_cells``, ``is_total=False`` — no Total row, so col
    0080 stays a constant 0.0, the R12 disposition). ``labels`` empty -> an empty
    spec (rows ``()``); the caller emits an ``_empty_frame`` instead of executing.
    ``cols`` is the PRE-``_prepare`` base-column set (see ``_c08_01_spec``)."""
    rows = tuple(_Row(label, label) for label in labels)
    cells: dict[tuple[str, str], CellSpec] = {}
    for label in labels:
        terms: _Terms = (("c08_02_key", label),)
        for col_ref, cell in _value_cells(
            terms, cols, ead_col, rwa_col, value_refs, is_total=False
        ).items():
            cells[(label, col_ref)] = cell
    return TemplateSpec(
        name="c08_02", rows=rows, column_refs=value_refs, cells=cells, empty_cell="zero"
    )


def c08_02_plans(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, SheetPlan]:
    """Build the per-class C 08.02 execution plans for lineage (data-driven rows).

    Each class sheet has its OWN spec — rows are the distinct firm grades (else the
    populated PD bands + "Unassigned") derived per class by ``_c08_02_keyed`` (the
    CR9.1 pattern), so the plans fn builds per-sheet specs exactly as the generator
    does. Keys on the sealed ``reporting_class_origin`` over the WHOLE IRB book,
    preserving ``generate_c08_02``'s error contract. The cross-class substitution
    INFLOW is DELIBERATELY excluded (col 0080 a per-grade constant 0.0, R12), so
    each plan carries an empty ``ReportingContext`` and ``_NEGATIVE_COLS`` explicitly
    (0256 still negates on C 08.02)."""
    ec_col = pick(cols, "reporting_class_origin")
    ead_col = pick(cols, "ead_final")
    rwa_col = pick(cols, "rwa_final", "rwa_post_factor", "rwa")
    pd_col = pick(cols, "pd_floored", "pd")
    grade_col = pick(cols, "cp_internal_rating_grade")
    if ec_col is None or ead_col is None or rwa_col is None:
        errors.append("C08.02: Missing required columns")
        return {}
    if pd_col is None:
        errors.append("C08.02: No PD column available — skipping PD grade breakdown")
        return {}
    irb_df = _irb_population(results, cols).collect()
    if len(irb_df) == 0:
        return {}
    data_cols = set(irb_df.columns)
    irb_df = _prepare(irb_df, data_cols)
    value_refs = tuple(col.ref for col in get_c08_02_columns(framework) if col.ref != "0005")
    plans: dict[str, SheetPlan] = {}
    for ec in irb_df[ec_col].drop_nulls().unique().sort().to_list():
        class_df = irb_df.filter(pl.col(ec_col) == ec)
        labels, keyed = _c08_02_keyed(class_df, pd_col, grade_col)
        plans[ec] = SheetPlan(
            spec=_c08_02_spec(labels, data_cols, ead_col, rwa_col, value_refs),
            frame=keyed,
            ctx=ReportingContext(),
            negative_cols=_NEGATIVE_COLS,
        )
    return plans


@cites("PS1/26, paragraph 1.3")
def generate_c08_02(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, pl.DataFrame]:
    """Execute C 08.02 per class sheet with data-driven grade/PD-band rows.

    Iterates ``c08_02_plans`` and per sheet applies the off-BS pre-CCF memo (0100),
    the provisions ladder (0290) and the Annex II §1.3 "(-)" negation, then injects
    the String row label into col 0005 (the CR9.1 post-execute pattern). An
    empty-label class emits an ``_empty_frame`` (0005 typed String). Each row's
    predicate is rebuilt from the plan spec's row refs (each a ``c08_02_key``
    label)."""
    column_refs = tuple(col.ref for col in get_c08_02_columns(framework))
    result: dict[str, pl.DataFrame] = {}
    for ec, plan in c08_02_plans(results, cols, framework, errors).items():
        if not plan.spec.rows:
            result[ec] = _empty_frame(column_refs, string_refs=("0005",))
            continue
        row_preds: dict[str, RowPredicate | None] = {
            row.ref: RowPredicate(equals=(("c08_02_key", row.ref),)) for row in plan.spec.rows
        }
        data_cols = set(plan.frame.columns)
        frame = execute(plan.spec, plan.frame, plan.ctx)
        frame = _c08_off_bs_pre_ccf(frame, plan.frame, row_preds)
        frame = _provisions_postfix(frame, plan.frame, row_preds, data_cols, ref="0290")
        frame = _negate(frame)
        frame = frame.with_columns(pl.col("row_name").alias("0005"))
        result[ec] = frame.select(["row_ref", "row_name", *column_refs])
    return result


def _c08_02_keyed(
    class_df: pl.DataFrame, pd_col: str, grade_col: str | None
) -> tuple[list[str], pl.DataFrame]:
    """Derive the C 08.02 row key column: distinct firm grades when the
    grade column has values (null grades -> "Unassigned"), else the
    populated fixed PD bands (out-of-band/null PD -> "Unassigned")."""
    if grade_col is not None and grade_col in class_df.columns:
        non_null = class_df.filter(pl.col(grade_col).is_not_null())
        if len(non_null) > 0:
            keyed = class_df.with_columns(
                pl.col(grade_col).fill_null("Unassigned").alias("c08_02_key")
            )
            labels = non_null[grade_col].unique().sort().to_list()
            if len(non_null) < len(class_df):
                labels.append("Unassigned")
            return labels, keyed
    band_expr: pl.Expr = pl.lit("Unassigned")
    for lower, upper, label in reversed(PD_BANDS):
        band_expr = (
            pl.when((pl.col(pd_col) >= lower) & (pl.col(pd_col) < upper))
            .then(pl.lit(label))
            .otherwise(band_expr)
        )
    keyed = class_df.with_columns(band_expr.alias("c08_02_key"))
    present = set(keyed["c08_02_key"].to_list())
    labels = [label for _lo, _hi, label in PD_BANDS if label in present]
    if "Unassigned" in present:
        labels.append("Unassigned")
    return labels, keyed


# =============================================================================
# C 08.03 / C 08.05 — the sparse PD-range pair
# =============================================================================


def _pd_alloc_col(cols: set[str], framework: str) -> str | None:
    if framework == "BASEL_3_1":
        return pick(cols, "pd", "pd_floored")
    return pick(cols, "pd_floored", "pd")


def _banded_rows(
    class_df: pl.DataFrame, alloc_pd_col: str
) -> tuple[list[tuple[str, str]], pl.DataFrame]:
    """Assign the 17 fixed PD ranges; return the populated (ref, label) rows
    in canonical order (plus 9999 Unassigned) and the banded frame."""
    band_expr: pl.Expr = pl.lit("Unassigned")
    for lower, upper, _ref, label in reversed(C08_03_PD_RANGES):
        band_expr = (
            pl.when((pl.col(alloc_pd_col) >= lower) & (pl.col(alloc_pd_col) < upper))
            .then(pl.lit(label))
            .otherwise(band_expr)
        )
    banded = class_df.with_columns(band_expr.alias("c08_pd_range"))
    present = set(banded["c08_pd_range"].to_list())
    rows = [(ref, label) for _lo, _hi, ref, label in C08_03_PD_RANGES if label in present]
    if "Unassigned" in present:
        rows.append(("9999", "Unassigned"))
    return rows, banded


def _c08_03_cells(  # noqa: PLR0913 - the full C 08.03 sparse-PD-range column surface
    band_rows: list[tuple[str, str]],
    cols: set[str],
    ead_col: str,
    rwa_col: str,
    pd_report_col: str,
    lgd_col: str | None,
) -> dict[tuple[str, str], CellSpec]:
    """The C 08.03 per-band cell surface (one PD range = one row).

    Shared by ``c08_03_plans`` (the lineage spec) and ``generate_c08_03`` (the
    reported frame). Cols 0010/0020 split the band on ``c08_bs`` (on/off balance
    sheet); their retired whole-bucket fallback still runs post-execute
    (``_c08_03_bs_fallback``) on the REPORTED frame, so the drill-down reads a
    band's on/off gross from there."""
    cells: dict[tuple[str, str], CellSpec] = {}
    for ref, label in band_rows:
        terms: _Terms = (("c08_pd_range", label),)
        member = RowPredicate(equals=terms)
        cells[(ref, "0010")] = CellSpec(
            SafeSum(gross_carriers(cols, "drawn_amount", "interest")),
            predicate=RowPredicate(equals=(*terms, ("c08_bs", "on"))),
        )
        cells[(ref, "0020")] = CellSpec(
            Sum(gross_carrier(cols, "nominal_amount")),
            predicate=RowPredicate(equals=(*terms, ("c08_bs", "off"))),
        )
        cells[(ref, "0030")] = CellSpec(
            WeightedAvg("ccf", weight="nominal_amount"), predicate=member, empty_cell="null"
        )
        cells[(ref, "0040")] = CellSpec(Sum(ead_col), predicate=member)
        cells[(ref, "0050")] = CellSpec(
            WeightedAvg(pd_report_col, weight=ead_col), predicate=member, empty_cell="null"
        )
        cells[(ref, "0060")] = (
            CellSpec(Count("counterparty_reference", distinct=True), predicate=member)
            if "counterparty_reference" in cols
            else CellSpec(Count("exposure_reference"), predicate=member)
        )
        cells[(ref, "0070")] = (
            CellSpec(WeightedAvg(lgd_col, weight=ead_col), predicate=member, empty_cell="null")
            if lgd_col is not None
            else CellSpec(Formula(refs=(), fn=_const(None)))
        )
        cells[(ref, "0080")] = CellSpec(
            WeightedAvg("irb_maturity_m", weight=ead_col), predicate=member, empty_cell="null"
        )
        cells[(ref, "0090")] = CellSpec(Sum(rwa_col), predicate=member)
        cells[(ref, "0100")] = CellSpec(Sum("expected_loss"), predicate=member)
        cells[(ref, "0110")] = CellSpec(
            SafeSum(("scra_provision_amount", "gcra_provision_amount")), predicate=member
        )
    return cells


def c08_03_plans(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, SheetPlan]:
    """Build the per-class C 08.03 execution plans for lineage (sparse PD rows).

    Each class sheet has its OWN spec — rows are the populated PD ranges (plus an
    optional 9999 Unassigned) derived per class by ``_banded_rows`` (the c08_02
    data-driven pattern), keyed on the derived ``c08_pd_range`` label carried in
    ``row_terms``. Keys on the sealed ``reporting_class_origin`` over the IRB
    NON-slotting book, preserving ``generate_c08_03``'s error contract. C 08.03
    carries no "(-)"-labelled deduction column, so ``negative_cols`` is empty. The
    two post-execute passes (the retired on/off-BS whole-bucket fallback on cols
    0010/0020; the provisions ladder on col 0110) live on the REPORTED frame
    (``generate_c08_03``), which the drill-down reads a cell's value from — so on a
    bucket where the fallback fires the reported cell stays authoritative."""
    ec_col = pick(cols, "reporting_class_origin")
    ead_col = pick(cols, "ead_final")
    rwa_col = pick(cols, "rwa_final", "rwa_post_factor", "rwa")
    if ec_col is None or ead_col is None or rwa_col is None:
        errors.append("C08.03: Missing required columns (exposure_class/ead/rwa)")
        return {}
    alloc_pd_col = _pd_alloc_col(cols, framework)
    report_pd_col = pick(cols, "pd_floored", "pd")
    if alloc_pd_col is None:
        errors.append("C08.03: No PD column available — skipping PD range breakdown")
        return {}
    irb_df = _non_slotting(results, cols).collect()
    if len(irb_df) == 0:
        return {}
    data_cols = set(irb_df.columns)
    irb_df = _prepare(irb_df, data_cols)
    column_refs = tuple(col.ref for col in get_c08_03_columns(framework))
    lgd_col = pick(data_cols, "lgd_floored", "lgd_input")
    pd_report_col = report_pd_col or alloc_pd_col
    plans: dict[str, SheetPlan] = {}
    for ec in irb_df[ec_col].drop_nulls().unique().sort().to_list():
        class_df = irb_df.filter(pl.col(ec_col) == ec)
        band_rows, banded = _banded_rows(class_df, alloc_pd_col)
        cells = _c08_03_cells(band_rows, data_cols, ead_col, rwa_col, pd_report_col, lgd_col)
        rows = tuple(_Row(ref, label) for ref, label in band_rows)
        plans[ec] = SheetPlan(
            spec=TemplateSpec(
                name="c08_03", rows=rows, column_refs=column_refs, cells=cells, empty_cell="zero"
            ),
            frame=banded,
            ctx=ReportingContext(),
            negative_cols=frozenset(),
            row_terms={ref: (("c08_pd_range", label),) for ref, label in band_rows},
        )
    return plans


@cites("PS1/26, paragraph 1.3")
def generate_c08_03(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, pl.DataFrame]:
    """Execute C 08.03 per class sheet over sparse PD-range rows.

    Iterates ``c08_03_plans`` and applies the two post-execute passes on the
    reported frame — the retired on/off-BS whole-bucket fallback (cols 0010/0020)
    and the provisions ladder (col 0110) — which the drill-down reads a cell's
    value from. Each row's predicate is rebuilt from the plan's ``row_terms``
    (each a ``c08_pd_range`` label)."""
    column_refs = tuple(col.ref for col in get_c08_03_columns(framework))
    result: dict[str, pl.DataFrame] = {}
    for ec, plan in c08_03_plans(results, cols, framework, errors).items():
        if not plan.spec.rows:
            result[ec] = _empty_frame(column_refs)
            continue
        banded = plan.frame
        data_cols = set(banded.columns)
        row_preds: dict[str, RowPredicate | None] = {
            ref: RowPredicate(equals=terms) for ref, terms in plan.row_terms.items() if terms
        }
        frame = execute(plan.spec, banded)
        frame = _c08_03_bs_fallback(frame, banded, plan.row_terms, data_cols)
        frame = _provisions_postfix(frame, banded, row_preds, data_cols, ref="0110")
        result[ec] = frame
    return result


def _c08_03_bs_fallback(
    frame: pl.DataFrame,
    banded: pl.DataFrame,
    row_terms: Mapping[str, _Terms | None],
    cols: set[str],
) -> pl.DataFrame:
    """The retired whole-bucket fallback: when a bucket's on-BS (off-BS)
    split is empty, columns 0010 (0020) sum the WHOLE bucket instead.

    Iterates the plan's ``row_terms`` (ref -> the ``c08_pd_range`` band label), so
    the reported generator and the lineage plan share one row definition."""
    on_available = "c08_bs" in banded.columns
    fixes_0010: dict[str, float | None] = {}
    fixes_0020: dict[str, float | None] = {}
    for ref, terms in row_terms.items():
        if not terms:
            continue
        label = terms[0][1]
        bucket = banded.filter(pl.col("c08_pd_range") == label)
        on_empty = len(bucket.filter(pl.col("c08_bs") == "on")) == 0 if on_available else True
        off_empty = len(bucket.filter(pl.col("c08_bs") == "off")) == 0 if on_available else True
        if on_empty:
            total = 0.0
            found = False
            for source in gross_carriers(cols, "drawn_amount", "interest"):
                if source in cols:
                    total += float(bucket[source].fill_null(0.0).sum())
                    found = True
            fixes_0010[ref] = total if found else 0.0
        if off_empty:
            fixes_0020[ref] = (
                float(bucket[gross_carrier(cols, "nominal_amount")].fill_null(0.0).sum())
                if "nominal_amount" in cols
                else None
            )
    if not fixes_0010 and not fixes_0020:
        return frame
    exprs = []
    for col_ref, fixes in (("0010", fixes_0010), ("0020", fixes_0020)):
        if fixes:
            expr: pl.Expr = pl.col(col_ref)
            for ref, value in fixes.items():
                expr = (
                    pl.when(pl.col("row_ref") == ref)
                    .then(pl.lit(value, dtype=pl.Float64))
                    .otherwise(expr)
                )
            exprs.append(expr.alias(col_ref))
    return frame.with_columns(exprs)


def _c08_05_cells(  # noqa: PLR0913 - the full C 08.05 PD-backtesting column surface
    band_rows: list[tuple[str, str]],
    cols: set[str],
    pd_report_col: str,
    *,
    prior_present: bool,
    hist_present: bool,
) -> dict[tuple[str, str], CellSpec]:
    """The C 08.05 per-band cell surface (PD back-testing over sparse ranges).

    Shared by ``c08_05_plans`` and ``generate_c08_05``. R13 deleted this
    template's rate postfix, so it is execute-only — the cleanest of the C 08.03/
    05/06 trio: col 0040 (observed default rate) is an intra-row Formula and 0050
    a copy-of-0040 fallback (or the WeightedAvg historical rate when supplied)."""
    cells: dict[tuple[str, str], CellSpec] = {}
    for ref, label in band_rows:
        terms: _Terms = (("c08_pd_range", label),)
        member = RowPredicate(equals=terms)
        cells[(ref, "0010")] = CellSpec(
            WeightedAvg(pd_report_col, weight="c08_one"), predicate=member, empty_cell="null"
        )
        if prior_present:
            cells[(ref, "0020")] = CellSpec(Sum("prior_year_obligor_count"), predicate=member)
        elif "counterparty_reference" in cols:
            cells[(ref, "0020")] = CellSpec(
                Count("counterparty_reference", distinct=True), predicate=member
            )
        else:
            cells[(ref, "0020")] = CellSpec(Count("exposure_reference"), predicate=member)
        if "counterparty_reference" in cols:
            cells[(ref, "0030")] = CellSpec(
                Count("counterparty_reference", distinct=True),
                predicate=RowPredicate(equals=(*terms, ("c08_05_defaulted", True))),
            )
        else:
            cells[(ref, "0030")] = CellSpec(
                Count("exposure_reference"),
                predicate=RowPredicate(equals=(*terms, ("c08_05_defaulted", True))),
            )
        cells[(ref, "0040")] = CellSpec(Formula(refs=("0020", "0030"), fn=_observed_rate))
        if hist_present:
            cells[(ref, "0050")] = CellSpec(
                WeightedAvg("historical_annual_default_rate", weight="c08_one"), predicate=member
            )
        else:
            cells[(ref, "0050")] = CellSpec(Formula(refs=("0040",), fn=_copy_of_0040))
    return cells


def c08_05_plans(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, SheetPlan]:
    """Build the per-class C 08.05 execution plans for lineage (sparse PD rows).

    Shares ``_banded_rows`` / ``_pd_alloc_col`` with C 08.03; each class sheet has
    its OWN sparse-PD-range spec, keyed on the sealed ``reporting_class_origin``
    over the IRB NON-slotting book (preserving ``generate_c08_05``'s error
    contract). Execute-only (R13 deleted the rate postfix), so ``generate_c08_05``
    is a plain ``execute`` of each plan — no post-execute pass, and no
    "(-)"-labelled deduction column (``negative_cols`` empty)."""
    ec_col = pick(cols, "reporting_class_origin")
    if ec_col is None:
        errors.append("C08.05: Missing required column (exposure_class)")
        return {}
    alloc_pd_col = _pd_alloc_col(cols, framework)
    report_pd_col = pick(cols, "pd_floored", "pd")
    if alloc_pd_col is None:
        errors.append("C08.05: No PD column available — skipping PD backtesting")
        return {}
    irb_df = _non_slotting(results, cols).collect()
    if len(irb_df) == 0:
        return {}
    data_cols = set(irb_df.columns)
    pd_report_col = report_pd_col or alloc_pd_col
    irb_df = _c08_05_prepare(_prepare(irb_df, data_cols), data_cols, pd_report_col)
    column_refs = tuple(col.ref for col in get_c08_05_columns(framework))
    prior_present = "prior_year_obligor_count" in data_cols
    hist_present = "historical_annual_default_rate" in data_cols
    plans: dict[str, SheetPlan] = {}
    for ec in irb_df[ec_col].drop_nulls().unique().sort().to_list():
        class_df = irb_df.filter(pl.col(ec_col) == ec)
        band_rows, banded = _banded_rows(class_df, alloc_pd_col)
        cells = _c08_05_cells(
            band_rows,
            data_cols,
            pd_report_col,
            prior_present=prior_present,
            hist_present=hist_present,
        )
        rows = tuple(_Row(ref, label) for ref, label in band_rows)
        plans[ec] = SheetPlan(
            spec=TemplateSpec(
                name="c08_05", rows=rows, column_refs=column_refs, cells=cells, empty_cell="zero"
            ),
            frame=banded,
            ctx=ReportingContext(),
            negative_cols=frozenset(),
            row_terms={ref: (("c08_pd_range", label),) for ref, label in band_rows},
        )
    return plans


@cites("PS1/26, paragraph 1.3")
def generate_c08_05(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, pl.DataFrame]:
    """Execute C 08.05 per class sheet (PD back-testing over sparse ranges).

    Iterates ``c08_05_plans`` and executes each plan — R13 left this template
    execute-only, so there is no post-execute pass to reconcile the drill-down
    against."""
    column_refs = tuple(col.ref for col in get_c08_05_columns(framework))
    result: dict[str, pl.DataFrame] = {}
    for ec, plan in c08_05_plans(results, cols, framework, errors).items():
        result[ec] = (
            _empty_frame(column_refs) if not plan.spec.rows else execute(plan.spec, plan.frame)
        )
    return result


def _c08_05_prepare(data: pl.DataFrame, cols: set[str], report_pd_col: str) -> pl.DataFrame:
    """The C 08.05 default-detection ladder (is_defaulted else PD >= 100%)."""
    if "is_defaulted" in cols:
        flag = pl.col("is_defaulted") == True  # noqa: E712
    elif report_pd_col in cols:
        flag = (pl.col(report_pd_col) >= 1.0).fill_null(value=False)
    else:
        flag = pl.lit(value=False)
    return data.with_columns(flag.alias("c08_05_defaulted"))


# =============================================================================
# C 08.04 — the flow clone
# =============================================================================


def _c08_04_spec(cols: set[str], framework: str) -> TemplateSpec:
    """The C 08.04 flow spec (the CR8 clone): closing (row 0090, current
    period), opening (row 0010, a ``PriorPeriod`` binding) and residual (row
    0080, a ``Formula`` deriving from both). Shared by the reported generator
    (which threads a prior-period frame) and the lineage plan (the
    current-period view — no prior, so the opening/residual rows stay null and
    are refused by the drill-down exactly as CR8 refuses its rows 1/8). The RWA
    ladder is deliberately two-wide (no ``rwa_post_factor``) — the retired
    ladder."""
    rwa_col = pick(cols, "rwa_final", "rwa")
    column_refs = tuple(col.ref for col in get_c08_04_columns(framework))
    rows = tuple(C08_04_ROWS)
    cells: dict[tuple[str, str], CellSpec] = {}
    if rwa_col is not None:
        cells[("0090", "0010")] = CellSpec(Sum(rwa_col))  # closing RWEA
        cells[("0010", "0010")] = CellSpec(PriorPeriod(Sum(rwa_col)))  # opening RWEA
        cells[("0080", "0010")] = CellSpec(
            Formula(refs=("0090", "0010"), fn=_c08_04_other_flow)  # signed residual
        )
    return TemplateSpec(
        name="c08_04", rows=rows, column_refs=column_refs, cells=cells, empty_cell="null"
    )


def c08_04_plans(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, SheetPlan]:
    """Build the per-class C 08.04 execution plans for lineage (current period).

    The current-period view: no prior-period frame is threaded, so the opening
    (row 0010, a ``PriorPeriod`` cell) and residual (row 0080, a ``Formula``
    deriving from it) rows stay null — both are prior-period-derived, so lineage
    REFUSES them exactly as CR8 refuses its opening/residual rows (R20's refusal,
    free). Keys the per-class plans on the sealed ``reporting_class_origin``,
    identically to ``generate_c08_04``, and preserves its error contract. C 08.04
    carries no "(-)"-labelled deduction column, so ``negative_cols`` is empty.
    """
    ec_col = pick(cols, "reporting_class_origin")
    if ec_col is None:
        errors.append("C08.04: Missing required column (exposure_class)")
        return {}
    irb_df = _non_slotting(results, cols).collect()
    if len(irb_df) == 0:
        return {}
    data_cols = set(irb_df.columns)
    spec = _c08_04_spec(data_cols, framework)
    plans: dict[str, SheetPlan] = {}
    for ec in irb_df[ec_col].drop_nulls().unique().sort().to_list():
        plans[ec] = SheetPlan(
            spec=spec,
            frame=irb_df.filter(pl.col(ec_col) == ec),
            ctx=ReportingContext(),
            negative_cols=frozenset(),
        )
    return plans


def c08_04_frames(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, pl.DataFrame]:
    """Render the current-period C 08.04 frames for lineage (keyed like
    ``c08_04_plans``). The lineage-facing generator — no prior-period frame —
    so a cell's reported value and its spec are looked up under the same class
    key. C 08.04 has no post-execute passes, so this is a plain ``execute``.
    ``generate_c08_04`` (the prior-aware dispatch entry) keeps its distinct
    signature and threads the external prior frame the current-period lineage
    view cannot carry."""
    return {
        key: execute(plan.spec, plan.frame, plan.ctx)
        for key, plan in c08_04_plans(results, cols, framework, errors).items()
    }


@cites("PS1/26, paragraph 1.3")
def generate_c08_04(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
    prior_results: pl.LazyFrame | None = None,
) -> dict[str, pl.DataFrame]:
    """Execute C 08.04 per class sheet — closing, opening, and residual flow.

    Mirrors Pillar 3 CR8 (``pillar3/cr8.py``): row 0090 (closing) sums the
    current period's RWEA; row 0010 (opening) sums the SAME population over
    the prior-period frame (``prior_results``, filtered identically and keyed
    per sheet) through the ``PriorPeriod`` binding; row 0080 (Other) carries
    the signed residual ``closing - opening`` so the statement foots. The six
    attributable driver rows (0020-0070) stay null — two point-in-time
    snapshots cannot supply the exposure-level period-over-period lineage they
    need. With NO prior period every row but the closing stays null (unchanged
    behaviour; PS1/26 Annex XXII paragraph 11).

    ``prior_results`` must be a prior run of the SAME sealed shape as
    ``results`` (an aggregator-exit frame): ``rwa_col`` is resolved from the
    CURRENT frame's columns and reused verbatim over the prior — safe only
    under that same-shape precondition (a prior frame missing that column
    yields a null opening, never a raise).

    Prior-only-class limitation (recorded, deliberate — NOT a bug): the sheet
    loop iterates the CURRENT period's classes only. A class that carried RWEA
    last period but has zero exposures this period (fully run off) therefore
    emits NO sheet, and its run-off leaves no trace in any flow statement. This
    is inherent to the per-class-sheet pattern — every C 08.0x template behaves
    this way. Unioning current+prior class keys to emit an opening-only run-off
    sheet is the possible future extension if a supervisor ever requires the
    run-off to be visible; it is intentionally NOT implemented here.
    """
    ec_col = pick(cols, "reporting_class_origin")
    if ec_col is None:
        errors.append("C08.04: Missing required column (exposure_class)")
        return {}
    irb_df = _non_slotting(results, cols).collect()
    if len(irb_df) == 0:
        return {}
    data_cols = set(irb_df.columns)
    prior_irb_df, prior_ec_col = _c08_04_prior(prior_results)
    spec = _c08_04_spec(data_cols, framework)
    result: dict[str, pl.DataFrame] = {}
    for ec in irb_df[ec_col].drop_nulls().unique().sort().to_list():
        class_df = irb_df.filter(pl.col(ec_col) == ec)
        ctx: ReportingContext | None = None
        if prior_irb_df is not None and prior_ec_col is not None:
            prior_class = prior_irb_df.filter(pl.col(prior_ec_col) == ec)
            ctx = ReportingContext(previous_period_results=prior_class.lazy())
        result[ec] = execute(spec, class_df, ctx)
    return result


def _c08_04_prior(
    prior_results: pl.LazyFrame | None,
) -> tuple[pl.DataFrame | None, str | None]:
    """Collect and IRB-filter the prior-period frame for the opening RWEA.

    Returns ``(None, None)`` when no prior period is supplied, or when the
    prior frame lacks the ``reporting_class_origin`` key the current sheets
    are keyed on — the opening then stays null (graceful degradation, never a
    raise). The prior frame is IRB non-slotting filtered exactly as the
    current one, so its per-class RWEA sum is the like-for-like opening.
    """
    if prior_results is None:
        return None, None
    prior_cols = available_columns(prior_results)
    prior_ec_col = pick(prior_cols, "reporting_class_origin")
    if prior_ec_col is None:
        return None, None
    return _non_slotting(prior_results, prior_cols).collect(), prior_ec_col


# =============================================================================
# C 08.06 / OF 08.06 — specialised lending slotting (per SL-type sheets)
# =============================================================================


def _c08_06_row_defs(framework: str) -> list[tuple[str, str, bool | None, str]]:
    """The C 08.06 category x maturity row definitions (category + Total rows
    only) for one framework — shared by the spec, the plan and the sheet
    post-passes."""
    return [
        row_def
        for row_def in get_c08_06_rows(framework)
        if row_def[1] == "Total" or row_def[1] in C08_06_CATEGORY_MAP
    ]


def _c08_06_row_preds(
    row_defs: list[tuple[str, str, bool | None, str]], cols: set[str]
) -> dict[str, RowPredicate]:
    """Each row's category x maturity subset predicate (the asymmetric
    ``is_short_maturity`` fallback preserved)."""
    has_maturity = "is_short_maturity" in cols
    return {
        row_def[0]: _c08_06_row_pred(row_def[1], row_def[2], has_maturity=has_maturity)
        for row_def in row_defs
    }


def _c08_06_empty_refs(
    type_df: pl.DataFrame,
    row_defs: list[tuple[str, str, bool | None, str]],
    row_preds: dict[str, RowPredicate],
) -> frozenset[str]:
    """Non-Total rows with an EMPTY subset on this SL-type sheet.

    These rows are hard zero-filled by ``_c08_06_sheet`` (every cell 0.0 except
    col 0070 = the row definition's FIXED display risk weight), so their col 0070
    is a display artefact, not a measured weighted average. The per-sheet spec
    therefore leaves that cell UNBOUND (its value comes from the reported frame's
    zero-fill pass), so lineage reports it as the template's empty policy rather
    than a WeightedAvg with no legs whose value would contradict the screen. Uses
    the SAME emptiness test as ``_c08_06_sheet`` (subset height 0, label != Total)."""
    subsets = subset_rows(type_df, dict(row_preds))
    return frozenset(
        row_def[0]
        for row_def in row_defs
        if row_def[1] != "Total" and subsets[row_def[0]].height == 0
    )


def _c08_06_sheets(data: pl.DataFrame, cols: set[str], framework: str) -> dict[str, pl.DataFrame]:
    """The per-SL-type frames (empty SL types emit no sheet); a frame with no
    ``sl_type`` column is one ``specialised_lending`` sheet."""
    if "sl_type" not in cols:
        return {"specialised_lending": data}
    sheets: dict[str, pl.DataFrame] = {}
    for sl_key in get_c08_06_sl_types(framework):
        type_df = _c08_06_sl_type_sheet(data, sl_key, cols, framework)
        if type_df.height > 0:
            sheets[sl_key] = type_df
    return sheets


def c08_06_plans(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, SheetPlan]:
    """Build the per-SL-type C 08.06 execution plans for lineage (slotting only).

    Keys per-SL-TYPE sheets (CRR's IPRE absorbs HVCRE; B31 splits HVCRE; empty SL
    types emit NO sheet) over the slotting-only book, preserving
    ``generate_c08_06``'s error contract. Each sheet gets its OWN spec because the
    row set is number-neutral but the EMPTY-row set is per-sheet: an empty
    non-Total row's col 0070 is a fixed display risk weight (a zero-fill artefact),
    so the spec leaves that one cell UNBOUND (``_c08_06_empty_refs``) — the
    drill-down then reports it as the template's empty policy and reads its value
    from the reported frame, honouring the zero-fill without a WeightedAvg that has
    no legs. The three value-dependent post-passes (empty-row zero-fill; the 0030
    nominal / 0040 clamp / 0070 first-non-null live fixes; the provisions ladder)
    live on the REPORTED frame (``generate_c08_06``). C 08.06 carries no
    "(-)"-labelled deduction column, so ``negative_cols`` is empty."""
    ead_col = pick(cols, "ead_final")
    rwa_col = pick(cols, "rwa_final", "rwa_post_factor", "rwa")
    if ead_col is None or rwa_col is None:
        errors.append("C08.06: Missing required columns (ead/rwa)")
        return {}
    if pick(cols, "reporting_approach_origin", "approach") is None:
        errors.append("C08.06: No approach column — cannot identify slotting exposures")
        return {}
    # The retired dispatch pre-filtered the IRB book on the applied
    # approach only — an ``approach``-only frame silently yields nothing.
    if "reporting_approach_origin" not in cols:
        return {}
    slotting_df = results.filter(pl.col("reporting_approach_origin") == "slotting").collect()
    if slotting_df.height == 0:
        return {}
    if "slotting_category" not in cols:
        errors.append("C08.06: Missing slotting_category column — cannot generate template")
        return {}
    data = _c08_06_prepare(slotting_df, cols)
    row_defs = _c08_06_row_defs(framework)
    row_preds = _c08_06_row_preds(row_defs, cols)
    plans: dict[str, SheetPlan] = {}
    for sl_key, type_df in _c08_06_sheets(data, cols, framework).items():
        empty_refs = _c08_06_empty_refs(type_df, row_defs, row_preds)
        plans[sl_key] = SheetPlan(
            spec=_c08_06_spec(cols, ead_col, rwa_col, framework, empty_refs),
            frame=type_df,
            ctx=ReportingContext(),
            negative_cols=frozenset(),
        )
    return plans


@cites("PS1/26, paragraph 1.3")
def generate_c08_06(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, pl.DataFrame]:
    """Execute C 08.06 / OF 08.06 per SL-type sheet (slotting only).

    Rows = slotting category x maturity band (plus the two maturity-split
    Total rows); the retired two-branch row policy is preserved: an EMPTY
    non-Total row zero-fills every cell and reports the row definition's
    fixed display risk weight in 0070, while live rows (and both Total
    rows, even when empty) compute on data with per-cell null policy. Iterates
    ``c08_06_plans`` and applies ``_c08_06_sheet``'s value-dependent overrides on
    each plan's reported frame, which the drill-down reads a cell's value from."""
    plans = c08_06_plans(results, cols, framework, errors)
    if not plans:
        return {}
    ead_col = pick(cols, "ead_final")
    if ead_col is None:  # unreachable — a non-empty plan set implies ead_final resolved
        return {}
    row_defs = _c08_06_row_defs(framework)
    row_preds = _c08_06_row_preds(row_defs, cols)
    return {
        sl_key: _c08_06_sheet(plan.spec, plan.frame, row_defs, row_preds, cols, ead_col)
        for sl_key, plan in plans.items()
    }


def _c08_06_prepare(data: pl.DataFrame, cols: set[str]) -> pl.DataFrame:
    """Derive the off-balance discriminator (the kernel filter_off_bs rule:
    ``bs_type == "OFB"`` else ``exposure_type in {facility, contingent}``
    else nothing) and the always-False carrier behind the permanently-empty
    "substantially stronger" sub-rows."""
    if "bs_type" in cols:
        off_bs = pl.col("bs_type") == "OFB"
    elif "exposure_type" in cols:
        off_bs = pl.col("exposure_type").is_in(["facility", "contingent"])
    else:
        off_bs = pl.lit(value=False)
    return data.with_columns(
        off_bs.alias("c0806_off_bs"),
        pl.lit(value=False).alias("c0806_never"),
    )


def _c08_06_sl_type_sheet(
    data: pl.DataFrame, sl_key: str, cols: set[str], framework: str
) -> pl.DataFrame:
    """The retired HVCRE routing: CRR's IPRE sheet absorbs HVCRE (only when
    ``is_hvcre`` exists); B31's HVCRE sheet admits ``is_hvcre`` flags too."""
    has_hvcre = "is_hvcre" in cols
    if sl_key == "ipre" and framework != "BASEL_3_1" and has_hvcre:
        return data.filter(pl.col("sl_type").is_in(["ipre", "hvcre"]))
    if sl_key == "hvcre" and framework == "BASEL_3_1" and has_hvcre:
        return data.filter((pl.col("sl_type") == "hvcre") | pl.col("is_hvcre"))
    return data.filter(pl.col("sl_type") == sl_key)


def _c08_06_row_pred(label: str, is_short: bool | None, *, has_maturity: bool) -> RowPredicate:
    """One category x maturity row subset. The retired asymmetric fallback
    is preserved: with no maturity column the SHORT band is empty while the
    LONG band absorbs the whole category."""
    never = RowPredicate(equals=(("c0806_never", True),))
    if "substantially stronger" in label:
        return never
    terms: list[tuple[str, str | bool]] = []
    if label != "Total":
        terms.append(("slotting_category", C08_06_CATEGORY_MAP[label]))
    if is_short is not None:
        if has_maturity:
            terms.append(("is_short_maturity", is_short))
        elif is_short:
            return never
    return RowPredicate(equals=tuple(terms))


def _c08_06_spec(
    cols: set[str], ead_col: str, rwa_col: str, framework: str, empty_refs: frozenset[str]
) -> TemplateSpec:
    """The C 08.06 spec for one SL-type sheet (framework-shaped).

    ``empty_refs`` names the non-Total rows whose subset is empty on THIS sheet:
    their col 0070 is a fixed display risk weight applied by the zero-fill
    post-pass, so it is left UNBOUND here (see ``_c08_06_empty_refs``). Every
    other cell is number-neutral across sheets."""
    column_refs = tuple(col.ref for col in get_c08_06_columns(framework))
    row_defs = _c08_06_row_defs(framework)
    rows = tuple(_Row(row_def[0], row_def[1]) for row_def in row_defs)
    row_preds = _c08_06_row_preds(row_defs, cols)
    crm_col = pick(cols, "ead_pre_ccf", "exposure_post_crm")
    if framework != "BASEL_3_1" and "rwa_post_factor" in cols:
        rwea_col = "rwa_post_factor"  # CRR prefers the post-supporting-factor RWEA
    else:
        rwea_col = rwa_col
    cells: dict[tuple[str, str], CellSpec] = {}
    for row_def in row_defs:
        ref = row_def[0]
        pred = row_preds[ref]
        off_pred = RowPredicate(equals=(*pred.equals, ("c0806_off_bs", True)))
        cells[(ref, "0010")] = CellSpec(
            SafeSum(
                gross_carriers(cols, "drawn_amount", "interest", "nominal_amount", "undrawn_amount")
            ),
            predicate=pred,
        )
        cells[(ref, "0020")] = (
            CellSpec(Sum(crm_col), predicate=pred)
            if crm_col is not None
            else CellSpec(Formula(refs=("0010",), fn=_copy_of_0010))
        )
        cells[(ref, "0030")] = CellSpec(
            SafeSum(gross_carriers(cols, "nominal_amount", "undrawn_amount")), predicate=off_pred
        )
        if "0031" in column_refs:
            cells[(ref, "0031")] = CellSpec(Formula(refs=(), fn=_const(None)))
        cells[(ref, "0040")] = CellSpec(Sum(ead_col), predicate=pred)
        cells[(ref, "0050")] = CellSpec(Sum(ead_col), predicate=off_pred, empty_cell="null")
        cells[(ref, "0060")] = CellSpec(Formula(refs=(), fn=_const(None)))
        # Col 0070 on an EMPTY non-Total row is a fixed display risk weight from
        # the zero-fill post-pass (not a measured weighted average), so it is left
        # UNBOUND — the drill-down reads its value from the reported frame and
        # reports the template's empty policy, never a WeightedAvg with no legs.
        if ref not in empty_refs:
            cells[(ref, "0070")] = CellSpec(
                WeightedAvg("risk_weight", weight=ead_col), predicate=pred, empty_cell="null"
            )
        cells[(ref, "0080")] = CellSpec(Sum(rwea_col), predicate=pred)
        cells[(ref, "0090")] = (
            CellSpec(Sum("expected_loss"), predicate=pred)
            if "expected_loss" in cols
            else CellSpec(Formula(refs=(), fn=_const(None)))
        )
        cells[(ref, "0100")] = CellSpec(
            SafeSum(("scra_provision_amount", "gcra_provision_amount")), predicate=pred
        )
    return TemplateSpec(
        name="c08_06", rows=rows, column_refs=column_refs, cells=cells, empty_cell="zero"
    )


def _c08_06_sheet(
    spec: TemplateSpec,
    type_df: pl.DataFrame,
    row_defs: list[tuple[str, str, bool | None, str]],
    row_preds: dict[str, RowPredicate],
    cols: set[str],
    ead_col: str,
) -> pl.DataFrame:
    """Execute one SL-type sheet and apply the retired value-dependent
    branches: the zero-fill policy for empty non-Total rows (fixed display
    RW in 0070), the whole-subset nominal fallback for 0030 when the row
    has no off-balance slice, the >0 clamp on 0040, the first-non-null
    risk weight when the subset carries zero total EAD, and the SCRA/GCRA
    -> provision_held provisions ladder."""
    frame = execute(spec, type_df)
    overrides: dict[str, dict[str, float | None]] = {}
    row_subsets = subset_rows(type_df, dict(row_preds))
    for row_ref, label, _is_short, rw_display in row_defs:
        subset = row_subsets[row_ref]
        if subset.height == 0 and label != "Total":
            overrides[row_ref] = _c08_06_zero_row(spec.column_refs, rw_display)
            continue
        fixes: dict[str, float | None] = {}
        if subset.filter(pl.col("c0806_off_bs")).height == 0:
            fixes["0030"] = col_sum(subset, cols, gross_carrier(cols, "nominal_amount"))
        ead_sum = float(subset[ead_col].fill_null(0.0).sum())
        if ead_sum <= 0.0:
            fixes["0040"] = 0.0
        if subset.height > 0 and ead_sum <= 0.0 and "risk_weight" in cols:
            rw_vals = subset["risk_weight"].drop_nulls()
            fixes["0070"] = float(rw_vals[0]) if len(rw_vals) > 0 else None
        if fixes:
            overrides[row_ref] = fixes
    frame = _c08_06_apply_overrides(frame, overrides)
    return _provisions_postfix(frame, type_df, row_preds, cols, ref="0100")


def _c08_06_zero_row(column_refs: tuple[str, ...], rw_display: str) -> dict[str, float | None]:
    """The retired zero-fill for an empty non-Total row: every cell 0.0
    except 0070 = the row definition's display risk weight ("50%" -> 0.5;
    unparseable/blank -> None)."""
    values: dict[str, float | None] = dict.fromkeys(column_refs, 0.0)
    if rw_display:
        try:
            values["0070"] = float(rw_display.replace("%", "").strip()) / 100.0
        except ValueError:
            values["0070"] = None
    else:
        values["0070"] = None
    return values


def _c08_06_apply_overrides(
    frame: pl.DataFrame, overrides: dict[str, dict[str, float | None]]
) -> pl.DataFrame:
    if not overrides:
        return frame
    exprs: list[pl.Expr] = []
    value_cols = [col for col in frame.columns if col not in ("row_ref", "row_name")]
    for col in value_cols:
        expr = pl.col(col)
        touched = False
        for row_ref, values in overrides.items():
            if col in values:
                expr = (
                    pl.when(pl.col("row_ref") == row_ref)
                    .then(pl.lit(values[col], dtype=pl.Float64))
                    .otherwise(expr)
                )
                touched = True
        if touched:
            exprs.append(expr.alias(col))
    return frame.with_columns(exprs) if exprs else frame


def _copy_of_0010(cells: Mapping[str, float | None], _prior: bool) -> float | None:
    """C 08.06 col 0020 falls back to col 0010 when no post-CRM carrier
    (``ead_pre_ccf`` / ``exposure_post_crm``) exists."""
    return cells["0010"]


# =============================================================================
# C 08.07 / OF 08.07 — IRB scope of use (single frame, full population)
# =============================================================================


@cites("CRR Art. 148")
@cites("PS1/26, paragraph 1.3")
def generate_c08_07(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> pl.DataFrame | None:
    """Execute C 08.07 / OF 08.07 over the FULL results population.

    SA and IRB both enter (the IRB side is ``approach_applied`` membership
    in the pinned ``C08_07_IRB_APPROACHES`` — slotting counts as IRB; a
    null approach falls to SA); coverage percentages are intra-row
    formulas guarding a zero denominator to 0.0. Col 0040 ("% subject to a
    roll-out plan", CRR Art. 148) is the SA-treated slice flagged by the
    optional ``is_under_irb_rollout`` INPUT column, carved out of col 0030
    (permanent partial use, Art. 150) so 0030 + 0040 == the whole SA coverage
    %; with no roll-out input col 0040 is 0.0 and 0030 keeps the whole SA share.
    Rows with no exposure class binding (and no aggregate rule) render ALL-NULL;
    empty real-class rows stay 0.0 — the opposite split from C 07.00. The B31
    materiality columns 0160-0180 are structurally null regardless of reporting
    basis (the retired ``output_floor_config`` gate was dead code).
    """
    prepared = _c08_07_prepared(results, cols, framework, errors)
    if prepared is None:
        return None
    spec, data, null_rows = prepared
    frame = execute(spec, data)
    frame = _c08_07_rollout_pct(frame)
    return _null_fixed_rows(frame, null_rows)


def _c08_07_prepared(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> tuple[TemplateSpec, pl.DataFrame, list[str]] | None:
    """Collect + derive the C 08.07 discriminators and build its spec.

    Shared by ``generate_c08_07`` (the reported frame, which re-applies the two
    post-execute passes) and ``c08_07_plans`` (the lineage plan). Returns
    ``None`` on the imperative generator's early exits (missing columns / empty
    population), recording the same error string.
    """
    ead_col = pick(cols, "ead_final")
    approach_col = pick(cols, "reporting_approach_origin", "approach")
    # Recorded basis: C 08.07 keys the RAW class over the FULL population
    # (Art. 147 origination taxonomy has no "defaulted" class) — the one
    # COREP sheet key deliberately NOT retargeted to the applied ladder.
    ec_col = pick(cols, "exposure_class")
    if ead_col is None or approach_col is None or ec_col is None:
        missing = [
            name
            for name, value in (("ead", ead_col), ("approach", approach_col), ("class", ec_col))
            if value is None
        ]
        errors.append(f"C 08.07: missing columns: {', '.join(missing)}")
        return None
    data = results.collect()
    if data.height == 0:
        return None
    data = data.with_columns(
        pl.col(approach_col).is_in(sorted(C08_07_IRB_APPROACHES)).alias("c0807_irb")
    )
    # CRR Art. 148/150 roll-out-plan discriminator (col 0040): an SA-treated leg
    # (``~c0807_irb``) that the firm's approved sequential-implementation plan
    # schedules to move to IRB. Derived ONLY when the optional input flag is
    # present — an absent flag leaves ``c0807_rollout`` off the frame, so the
    # tolerant col-0040 predicate matches nothing (0.0) and col 0030 keeps the
    # whole SA share, byte-identical to the pre-R14 output.
    rollout_col = pick(cols, "is_under_irb_rollout")
    if rollout_col is not None:
        data = data.with_columns(
            (~pl.col("c0807_irb") & pl.col(rollout_col).fill_null(value=False)).alias(
                "c0807_rollout"
            )
        )
    rwa_col = pick(cols, "rwa_final", "rwa_post_factor", "rwa")
    row_defs = get_c08_07_rows(framework)
    spec, null_rows = _c08_07_spec(row_defs, ec_col, ead_col, rwa_col, framework)
    return spec, data, null_rows


def c08_07_plans(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, SheetPlan]:
    """Build the single C 08.07 execution plan for lineage (single frame).

    C 08.07 has no sheet axis, so its one plan keys under the canonical
    single-frame key. The plan frame is the FULL prepared population (carrying
    the derived ``c0807_irb`` / ``c0807_rollout`` discriminators) and each cell's
    own predicate narrows it. C 08.07 has no "(-)"-labelled deduction column, so
    ``negative_cols`` is empty. The two post-execute passes
    (``_c08_07_rollout_pct`` rescaling col 0040 to a percentage,
    ``_null_fixed_rows`` on the structural-null rows) live on the REPORTED frame
    (``c08_07_frames`` / ``generate_c08_07``): the drill-down reads a cell's
    ``cell_value`` from there, so col 0040 shows its rescaled percentage and the
    fixed-null rows read null (they carry no cell binding — an ``unbound`` cell),
    never contradicting the sheet. Preserves the generator's error contract via
    ``_c08_07_prepared``.
    """
    prepared = _c08_07_prepared(results, cols, framework, errors)
    if prepared is None:
        return {}
    spec, data, _null_rows = prepared
    return {
        _C08_07_SHEET_KEY: SheetPlan(
            spec=spec, frame=data, ctx=ReportingContext(), negative_cols=frozenset()
        )
    }


def c08_07_frames(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, pl.DataFrame]:
    """Render the single C 08.07 frame for lineage (keyed like ``c08_07_plans``).

    Wraps ``generate_c08_07`` under the single-frame key so a cell's reported
    value carries the two post-execute passes the plan does not — the lineage
    drill-down reads ``cell_value`` from HERE, so it honours the rescaled col
    0040 and the nulled structural rows."""
    frame = generate_c08_07(results, cols, framework, errors)
    return {_C08_07_SHEET_KEY: frame} if frame is not None else {}


def _c08_07_spec(
    row_defs: list[tuple[str, str, str | None]],
    ec_col: str,
    ead_col: str,
    rwa_col: str | None,
    framework: str,
) -> tuple[TemplateSpec, list[str]]:
    """The C 08.07 spec + the fixed structural-null row set (CRR 0060/0100/
    0130; B31 0210/0280 — rows with neither a class binding nor an
    aggregate rule)."""
    is_b31 = framework == "BASEL_3_1"
    column_refs = tuple(col.ref for col in get_c08_07_columns(framework))
    rows = tuple(_Row(row_def[0], row_def[1]) for row_def in row_defs)
    cells: dict[tuple[str, str], CellSpec] = {}
    null_rows: list[str] = []
    for row_ref, row_name, ec_value in row_defs:
        union: tuple[RowPredicate, ...] = ()
        if row_name == "Total":
            class_terms: _Terms = ()
        elif ec_value is not None:
            class_terms = ((ec_col, ec_value),)
        elif row_ref == "0090":
            # The CRR "Retail" display aggregate — three retail classes.
            class_terms = ()
            union = tuple(
                RowPredicate(equals=((ec_col, ec),)) for ec in sorted(C08_07_CRR_RETAIL_CLASSES)
            )
        else:
            null_rows.append(row_ref)
            continue
        total_pred = RowPredicate(equals=class_terms, any_of=union)
        irb_pred = RowPredicate(equals=(*class_terms, ("c0807_irb", True)), any_of=union)
        rollout_pred = RowPredicate(equals=(*class_terms, ("c0807_rollout", True)), any_of=union)
        cells[(row_ref, "0010")] = CellSpec(Sum(ead_col), predicate=irb_pred)
        cells[(row_ref, "0020")] = CellSpec(Sum(ead_col), predicate=total_pred)
        # Col 0040 first carries the roll-out-plan EAD (SA-treated AND under an
        # Art. 148 plan); ``_c08_07_rollout_pct`` rescales it to a percentage of
        # the row total post-execute. A frame without ``c0807_rollout`` makes the
        # tolerant predicate match nothing -> 0.0 (permanent-partial-use only).
        cells[(row_ref, "0040")] = CellSpec(Sum(ead_col), predicate=rollout_pred)
        cells[(row_ref, "0030")] = CellSpec(Formula(refs=("0010", "0020", "0040"), fn=_pct_ppu))
        cells[(row_ref, "0050")] = CellSpec(Formula(refs=("0010", "0020"), fn=_pct_irb))
        if is_b31:
            if rwa_col is not None:
                cells[(row_ref, "0060")] = CellSpec(Sum(rwa_col), predicate=total_pred)
                cells[(row_ref, "0150")] = CellSpec(Sum(rwa_col), predicate=irb_pred)
                cells[(row_ref, "0140")] = CellSpec(Formula(refs=("0060", "0150"), fn=_sa_rwea))
            for ref in ("0160", "0170", "0180"):
                cells[(row_ref, ref)] = CellSpec(Formula(refs=(), fn=_const(None)))
    spec = TemplateSpec(
        name="c08_07", rows=rows, column_refs=column_refs, cells=cells, empty_cell="zero"
    )
    return spec, null_rows


def _pct_ppu(cells: Mapping[str, float | None], _prior: bool) -> float | None:
    """0030 = SA share subject to PERMANENT PARTIAL USE, % (0.0 on a zero
    denominator): the SA EAD (row total 0020 minus IRB 0010) EXCLUDING the
    roll-out-plan slice (col 0040, still the raw EAD Sum when this formula runs).
    0030 + 0040 == the total SA coverage %, so the aggregate the pre-R14 col 0030
    reported is preserved; with no roll-out data col 0040 is 0.0 and 0030 reduces
    to the whole SA share, bit-identical to the pre-R14 formula (``x - 0.0 == x``).
    Art. 148 (roll-out plans) vs Art. 150 (permanent partial use)."""
    total = cells["0020"] or 0.0
    if total <= 0:
        return 0.0
    return (total - (cells["0010"] or 0.0) - (cells["0040"] or 0.0)) / total * 100.0


def _pct_irb(cells: Mapping[str, float | None], _prior: bool) -> float | None:
    """0050 = IRB share of the row's EAD, % (0.0 on a zero denominator)."""
    total = cells["0020"] or 0.0
    if total <= 0:
        return 0.0
    return (cells["0010"] or 0.0) / total * 100.0


def _c08_07_rollout_pct(frame: pl.DataFrame) -> pl.DataFrame:
    """Rescale C 08.07 col 0040 from the roll-out-plan EAD (the Sum bound in the
    spec) to its percentage of the row total (col 0020), guarding a zero
    denominator to 0.0 — the executor has no verb for "percentage of another
    cell", so it is derived here post-execute. Col 0030 already excludes this
    slice (``_pct_ppu``), so 0030 + 0040 == the row's total SA coverage %. A
    no-op when no roll-out data is present (col 0040 EAD is 0.0)."""
    if "0040" not in frame.columns or "0020" not in frame.columns:
        return frame
    total = pl.col("0020")
    pct = pl.when(total > 0).then(pl.col("0040") / total * 100.0).otherwise(0.0)
    return frame.with_columns(pct.alias("0040"))


def _sa_rwea(cells: Mapping[str, float | None], _prior: bool) -> float | None:
    """B31 0140 = SA RWEA lumped as "other" (total 0060 minus IRB 0150 —
    no ``sa_use_reason`` carrier exists, so 0070-0130 stay 0.0 and the
    additive identity 0060 = Σ(0070..0140) + 0150 holds by construction)."""
    return (cells["0060"] or 0.0) - (cells["0150"] or 0.0)


def _null_fixed_rows(frame: pl.DataFrame, row_refs: list[str]) -> pl.DataFrame:
    """Render a FIXED row set all-null (the C 08.07 structural rows — NOT
    empty-subset detection: empty real-class rows must stay 0.0)."""
    if not row_refs:
        return frame
    value_cols = [col for col in frame.columns if col not in ("row_ref", "row_name")]
    return frame.with_columns(
        pl.when(pl.col("row_ref").is_in(row_refs))
        .then(pl.lit(None, dtype=pl.Float64))
        .otherwise(pl.col(col))
        .alias(col)
        for col in value_cols
    )


# =============================================================================
# Shared post-steps + small helpers
# =============================================================================


def _non_slotting(results: pl.LazyFrame, cols: set[str]) -> pl.LazyFrame:
    irb = _irb_population(results, cols)
    approach_col = pick(cols, "reporting_approach_origin", "approach")
    if approach_col is not None:
        return irb.filter(pl.col(approach_col) != "slotting")
    return irb


def _null_empty_rows(
    frame: pl.DataFrame, class_df: pl.DataFrame, row_preds: dict[str, RowPredicate | None]
) -> pl.DataFrame:
    """Render inert rows and rows with EMPTY subsets all-null."""
    constrained = {
        ref: pred
        for ref, pred in row_preds.items()
        if pred is not None and (pred.equals or pred.any_of)
    }
    counts = matched_counts(class_df, constrained)
    null_refs = [
        ref
        for ref, pred in row_preds.items()
        if pred is None or ((pred.equals or pred.any_of) and counts[ref] == 0)
    ]
    if not null_refs:
        return frame
    value_cols = [col for col in frame.columns if col not in ("row_ref", "row_name")]
    return frame.with_columns(
        pl.when(pl.col("row_ref").is_in(null_refs))
        .then(pl.lit(None, dtype=pl.Float64))
        .otherwise(pl.col(col))
        .alias(col)
        for col in value_cols
    )


def _provisions_postfix(
    frame: pl.DataFrame,
    class_df: pl.DataFrame,
    row_preds: Mapping[str, RowPredicate | None],
    cols: set[str],
    *,
    ref: str,
) -> pl.DataFrame:
    """The provisions ladder: when the SCRA/GCRA base sum nets to ~0, swap the
    whole cell to the best available provisions carrier for the row subset (a
    value-dependent, PER-CELL branch — the recorded C 08 granularity, distinct
    from C 07.00's per-row ladder).

    The fallback carrier is ``provision_held`` when the frame carries it (the
    synthetic COREP unit frames supply it), else the sealed ``provision_allocated``
    (R10b). The retired ``provision_held``-only fallback was DEAD on every real
    submission: ``provision_held`` is an input pass-through the aggregator seal
    strips, so ``"provision_held" not in cols`` returned early and the provisions
    cells (C 08.01/02 col 0290, C 08.03 col 0110, C 08.06 col 0100) rendered a
    hard 0.0. ``provision_allocated`` is the sealed provisions carrier that IS
    meaningful on the IRB book: unlike C 07.00's ``provision_deducted`` (R9), the
    Art. 111(2) drawn-first deduction is SA-only (engine/crm/provisions.py —
    IRB/Slotting: provision_on_drawn = 0, provision_on_nominal = 0, so
    provision_deducted is STRUCTURALLY 0.0 on every IRB/slotting leg), whereas
    provision_allocated is tracked for all approaches (it feeds the IRB EL
    shortfall/excess). scra/gcra stay the preferred base; a book that supplies
    them non-degenerately keeps that granular figure."""
    fallback_col = (
        "provision_held"
        if "provision_held" in cols
        else "provision_allocated"
        if "provision_allocated" in cols
        else None
    )
    if ref not in frame.columns or fallback_col is None:
        return frame
    needed: dict[str, RowPredicate | None] = {}
    for row_ref, pred in row_preds.items():
        if pred is None:
            continue
        current = frame.filter(pl.col("row_ref") == row_ref)
        if current.height == 0 or current[ref][0] is None:
            continue
        if abs(current[ref][0]) >= 1e-9:
            continue
        needed[row_ref] = pred
    fixes: dict[str, float] = {}
    for row_ref, subset in subset_rows(class_df, needed).items():
        if subset.height == 0:
            continue
        fixes[row_ref] = float(subset[fallback_col].fill_null(0.0).sum())
    if not fixes:
        return frame
    expr: pl.Expr = pl.col(ref)
    for row_ref, value in fixes.items():
        expr = pl.when(pl.col("row_ref") == row_ref).then(pl.lit(value)).otherwise(expr)
    return frame.with_columns(expr.alias(ref))


def _c08_off_bs_pre_ccf(
    frame: pl.DataFrame,
    class_df: pl.DataFrame,
    row_preds: Mapping[str, RowPredicate | None],
) -> pl.DataFrame:
    """Fill C 08.01/02 col 0100 with the off-BS slice of the 0090 waterfall.

    Col 0100 ("of which: off balance sheet") sits in the POST-CRM PRE-CCF
    column group (the 0090 "Exposure after CRM substitution pre CCFs"
    waterfall), so it reports the off-BS share of that PRE-conversion-factor
    quantity — NOT the post-CCF exposure value (that is col 0120). The
    executor has no intra-row sub-waterfall verb, so 0100 is derived here per
    row over the row's ``c08_bs == "off"`` legs, mirroring ``_value_cells`` +
    ``_crm_waterfall`` component-for-component:

        0100 = off-BS gross (0020: floored drawn+undrawn)
             - off-BS guarantees (0040)
             - off-BS credit derivatives (0050)
             - off-BS other funded collateral (0060)
             - off-BS substituted portion (0070)

    It is computed on POSITIVE magnitudes read from the raw ``class_df`` (so
    the result is independent of the later ``_negate`` sign pass). The 0080
    substitution INFLOW is EXCLUDED: it is a total-row cross-sheet scalar
    (``ReportingContext.substitution_inflow``, a per-destination-class
    aggregate with no leg-level on/off-BS attribution), so an off-BS memo
    cannot claim a share of it — recorded decision, matching 0090's own
    convention that the inflow only lands on the (constraint-free) total row.

    Every leg is either on- or off-BS (``c08_bs``) and every waterfall carrier
    is a leg-level amount pro-rated across the two-leg guarantee split, so
    summing the components over the off-BS legs is the EXACT slice. Inert
    (None-predicate) rows are left as the null placeholder for
    ``_null_empty_rows``; C 08.02 has none.
    """
    if "0100" not in frame.columns:
        return frame
    cols = set(class_df.columns)
    if "c08_bs" not in cols:
        return frame
    active = {ref: pred for ref, pred in row_preds.items() if pred is not None}
    if not active:
        return frame
    gross_cols = gross_carriers(cols, "drawn_amount", "undrawn_amount")
    collateral_cols = (
        "collateral_re_value",
        "collateral_receivables_value",
        "collateral_other_physical_value",
    )
    has_protection = "protection_type" in cols
    fixes: dict[str, float] = {}
    for row_ref, subset in subset_rows(class_df, active).items():
        off = subset.filter(pl.col("c08_bs") == "off")
        off_cols = set(off.columns)
        gross = safe_sum(off, off_cols, *gross_cols)
        if has_protection:
            out_guarantee = _gp_sum(off, off_cols, pl.col("protection_type") == "guarantee")
            out_derivative = _gp_sum(
                off, off_cols, pl.col("protection_type") == "credit_derivative"
            )
        else:
            out_guarantee = _gp_sum(off, off_cols, mask=None)
            out_derivative = 0.0
        out_collateral = safe_sum(off, off_cols, *collateral_cols)
        out_substituted = _gp_sum(off, off_cols, pl.col("c08_substituted"))
        fixes[row_ref] = gross - out_guarantee - out_derivative - out_collateral - out_substituted
    expr: pl.Expr = pl.col("0100")
    for row_ref, value in fixes.items():
        expr = (
            pl.when(pl.col("row_ref") == row_ref)
            .then(pl.lit(value, dtype=pl.Float64))
            .otherwise(expr)
        )
    return frame.with_columns(expr.alias("0100"))


def _gp_sum(data: pl.DataFrame, cols: set[str], mask: pl.Expr | None) -> float:
    """Sum ``guaranteed_portion`` over ``data`` (optionally masked); 0.0 when
    the column is absent — mirroring the waterfall's ``cells[...] or 0.0``
    coalesce of an absent CRM-outflow carrier."""
    if "guaranteed_portion" not in cols:
        return 0.0
    sub = data.filter(mask) if mask is not None else data
    return float(sub["guaranteed_portion"].fill_null(0.0).sum())


def _negate_expr(col: str) -> pl.Expr:
    """Negate a "(-)"-labelled deduction column, normalising a zero to ``+0.0``.

    Plain ``-pl.col(col)`` flips the IEEE sign bit, so a ``0.0`` cell would
    serialise as ``-0.0`` (``+ 0.0`` does NOT clear it in Polars); the explicit
    zero branch keeps a zero deduction as ``+0.0``. Null stays null (``== 0.0``
    is null on a null row, so the ``otherwise`` branch returns ``-null``). This
    is the identical expression used by C 07.00's ``_negate_deduction_cols``."""
    return pl.when(pl.col(col) == 0.0).then(pl.lit(0.0)).otherwise(-pl.col(col)).alias(col)


def _negate(frame: pl.DataFrame) -> pl.DataFrame:
    """Annex II §1.3: emit the "(-)"-labelled deduction columns negative on the
    C 08.01/02 surface (``_NEGATIVE_COLS``), AFTER the CRM waterfall (0090) has
    consumed their positive magnitudes. Intersecting with the frame's columns
    makes the framework-specific members (B31's 0035/0102/0103, CRR's 0256/0257)
    no-ops in the regime where the column is absent. A zero cell is emitted as
    ``+0.0`` (not ``-0.0`` — plain float negation flips the sign bit and Polars
    keeps it) and null stays null; identical expression to C 07.00's pass."""
    targets = [col for col in frame.columns if col in _NEGATIVE_COLS]
    if not targets:
        return frame
    return frame.with_columns(_negate_expr(col) for col in targets)


def _empty_frame(column_refs: tuple[str, ...], string_refs: tuple[str, ...] = ()) -> pl.DataFrame:
    schema: dict[str, pl.DataType | type[pl.DataType]] = {
        "row_ref": pl.String,
        "row_name": pl.String,
    }
    for ref in column_refs:
        schema[ref] = pl.String if ref in string_refs else pl.Float64
    return pl.DataFrame(schema=schema)
