"""
Pillar 3 CCR1 / CCR2 / CCR3 / CCR8 — counterparty-credit-risk disclosures, declarative.

Pipeline position:
    sealed aggregator-exit ledger
        -> ccrN_plans() -> SheetPlan -> cellspec.execute()
        -> DataFrame | None

The four Pillar 3 counterparty-credit-risk templates, converted from the
imperative ``Pillar3Generator._generate_ccrN`` methods to declarative
``TemplateSpec``\\s run through the one ``cellspec.execute`` executor (Phase 7
S8; R27c — the FINAL declarative conversion of the estate). Each template is a
SINGLE FRAME (no sheet axis). After this item the only uninstrumented template
is C 02.00 (a kernel-plus-thin-shell hybrid with no ``TemplateSpec`` to read).

Lineage-instrumented: each ``ccrN_plans`` exposes its execution plan so
``reporting.lineage`` can drill into a reported cell; the ``ccrN_frames``
wrappers key the reported frame (with the emission gate) under the same
single-frame canonical key. No template carries a post-``execute`` pass, so a
cell's reported value is a plain ``execute`` of its plan.

Cell semantics (recorded decisions, unchanged from the imperative generators —
golden-gated for CCR1 / CCR3 / CCR8; the CVA CCR2 has no producing golden
fixture and is pinned by the CVA-A1 unit estate + a seeded lineage unit pin):

- **CCR1 (analysis of CCR exposure by approach).** The SA-CCR row (0010=``1``)
  and the Total row (``11``) carry the portfolio SA-CCR EAD in col ``a``
  (Σ ``ead_final`` over the synthetic ``ccr__`` netting-set rows; CRR Art.
  274(2)) and the non-QCCP default-risk RWEA in col ``b`` (Σ ``rwa_final`` over
  the rows that are NOT QCCP trade legs — the derived ``ccr1_default_risk`` flag
  ``~((cp_entity_type == "ccp") & cp_is_qccp.fill_null(True))``; CRR Art.
  107(2)(a)). FCCM SFTs are EXCLUDED (``include_sft=False``): an SFT uses FCCM
  under Art. 220-223, not the SA-CCR Art. 274 approach these templates analyse —
  it reports on SA template C 07.00 row 0090. The IMM / Original-exposure rows
  are structural placeholders left null. None when the portfolio carries no
  ``ccr__`` rows.
- **CCR2 (CVA capital charge, BA-CVA).** The BA-CVA row (``4``) and the Total
  row (``6``) read the portfolio ``cva_rwa`` roll-up in col ``a`` — a broadcast
  per-row constant the aggregation stage stamps on the results frame, read as a
  ``FirstNonNull`` over the whole ledger (the OV1 row-26 / C 34.04 broadcast-
  constant idiom; byte-identical to the imperative first-non-null because the
  column is constant). Presence-gated exactly like the imperative generator (no
  explicit framework gate — CRR simply produces no ``cva_rwa``, so CCR2 is None
  there): None when ``cva_rwa`` is absent or all-null.
- **CCR3 (SA-CCR EAD by risk-weight band).** One row per SA risk-weight band:
  the band's EAD cell (col ``a``) sums ``ead_final`` over the ``ccr__`` rows
  (SFTs excluded, as CCR1) whose ``risk_weight`` matches the band rate within a
  small tolerance (±0.005) — matched here as the module-derived ``ccr3_band``
  label column (a first-match assignment over the framework's CR5 risk-weight
  bands, the CR5 ``cr5_rw_bucket`` derived-column pattern; the bands do not
  overlap, so first-match equals the imperative per-band filter). Unmatched rows
  fall to the "Other" row (``ccr3_band == "other"``); the Total row re-derives
  the portfolio ``ead_ccr_total``. An empty band is a null cell (the Pillar 3
  empty policy). Recorded, unreachable divergence vs the imperative
  ``band_eads[i] or None``: a NON-EMPTY band summing to exactly 0.0 would now
  render 0.0 where the retired code collapsed it to null — that needs a
  zero-EAD CCR netting-set row, which SA-CCR cannot produce (alpha x (RC+PFE)
  with non-negative components), and the goldens are byte-identical. None when
  no CCR rows exist; a missing ``risk_weight`` column records the CCR3 error
  and yields None.
- **CCR8 (exposures to central counterparties).** Discloses exposures to CENTRAL
  COUNTERPARTIES only (CRR Art. 439(i)): the population is ``include_sft=True``
  (a CCP-faced FCCM SFT IS a CCP exposure — CRR Art. 301(1)(b) brings SFTs into
  the Chapter 6 Section 9 material scope) and then RESTRICTED to
  ``cp_entity_type == "ccp"`` rows, split by the derived ``ccr8_qccp`` flag
  (``cp_is_qccp.fill_null(True)`` — a null CCP treated as qualifying, CRR Art.
  306(1)): row ``1`` (QCCPs), row ``2`` (non-QCCPs), row ``21`` (Total = the
  whole CCP population). A bilateral (non-CCP) derivative or SFT counterparty is
  NEITHER row — it discloses on CCR1/CCR3 instead (the R5 CCP restriction: never
  the whole non-QCCP-trade complement, which would sweep in every bilateral OTC /
  SFT counterparty). Col ``a`` carries the RWEA, col ``b`` the EAD. Emitted only
  when the portfolio has CCP exposures (the R5 emission gate). CCR8 is the
  disclosure counterpart of the OV1 UK8a QCCP memo row — both read the CCP
  population off the same ``cp_entity_type``/``cp_is_qccp`` discriminators.

References:
- CRR Art. 439 (Part 8 CCR disclosures: 439(f) CCR1, 439(h) CCR2, 439(i) CCR8);
  Art. 444(e) (CCR3 SA EAD by risk weight)
- CRR Art. 274(2): SA-CCR EAD = alpha * (RC + PFE)
- CRR Art. 306(1)(a): 2% QCCP proprietary trade RW; Art. 107(2)(a) non-QCCP
- CRR Art. 301(1)(b): SFTs within the CCP material scope (CCR8 include_sft)
- PRA PS1/26 App.1 CVA Part Ch.4.2-4.4 (BA-CVA reduced — CCR2); Disclosure Art.
  456 (the CCR table set)
- docs/plans/phase7-declarative-reporting.md §3.2/§6 (S8)
- docs/features/report-cell-lineage.md (per-template lineage recipe)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.reporting.cellspec import (
    CellSpec,
    FirstNonNull,
    RowPredicate,
    Sum,
    TemplateSpec,
    execute,
)
from rwa_calc.reporting.kernel import pick
from rwa_calc.reporting.metadata import ReportingContext
from rwa_calc.reporting.pillar3.templates import (
    CCR1_COLUMNS,
    CCR1_ROWS,
    CCR2_COLUMNS,
    CCR2_ROWS,
    CCR3_COLUMNS,
    CCR8_COLUMNS,
    CCR8_ROWS,
    get_ccr3_risk_weights,
    get_ccr3_rows,
)
from rwa_calc.reporting.plans import SheetPlan

if TYPE_CHECKING:
    pass

# Single-frame lineage keys: each CCR template has no sheet axis, so its one plan
# keys under a canonical name (see reporting.plans / _resolve_sheet_key
# single_frame path). The reported catalogue id is the same string.
_CCR1_KEY = "ccr1"
_CCR2_KEY = "ccr2"
_CCR3_KEY = "ccr3"
_CCR8_KEY = "ccr8"

# Module-derived discriminator columns the row predicates key off (the c34
# c34_qccp / cr5 cr5_rw_bucket pattern — a RowPredicate carries no negation, no
# ``fill_null`` and no tolerance banding, so the CCR1 default-risk complement,
# the CCR8 qualifying-CCP flag and the CCR3 risk-weight band are each derived
# here as an explicit flag / label column).
_DEFAULT_RISK = "ccr1_default_risk"  # ~((cp_entity_type == ccp) & cp_is_qccp.fill_null(True))
_QCCP = "ccr8_qccp"  # cp_is_qccp.fill_null(True)
_BAND = "ccr3_band"  # matched CR5 risk-weight band ref, else "other"

# The tolerance the imperative ``_ccr3_band_eads`` matched a risk weight to a
# band rate within (CRR Art. 120(1) Table 3 band rates are exact; the ±half-band
# absorbs float dust). Inclusive both ends, exactly as the retired band filter.
_BAND_TOL = 0.005


# =============================================================================
# CCR1 — analysis of CCR exposure by approach (SA-CCR EAD + default-risk RWEA)
# =============================================================================


@cites("CRR Art. 274")
def generate_ccr1(results: pl.LazyFrame, cols: set[str]) -> pl.DataFrame | None:
    """Execute CCR1 (SA-CCR EAD col ``a`` + non-QCCP default-risk RWEA col ``b``).

    Returns None when the portfolio carries no ``ccr__`` netting-set rows — the
    gated precedent shared with C 34.01 / ``generate_of_02_01``.
    """
    ccr = _collect_ccr_rows(results, cols)
    if ccr is None or ccr.height == 0:
        return None
    return execute(_ccr1_spec(), _prepare_ccr1(ccr))


def ccr1_plans(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, SheetPlan]:
    """Build the single CCR1 execution plan for lineage (single frame).

    The plan frame is the pre-filtered SA-CCR netting-set population (FCCM SFTs
    excluded) carrying the derived ``ccr1_default_risk`` flag, so col ``a`` sums
    the whole frame and col ``b`` narrows to the default-risk (non-QCCP-trade)
    partition. No "(-)"-labelled deduction column, so ``negative_cols`` is empty.
    Yields ``{}`` when the portfolio has no such rows (a clean no-lineage, the
    reported None).
    """
    ccr = _collect_ccr_rows(results, cols)
    if ccr is None or ccr.height == 0:
        return {}
    return {
        _CCR1_KEY: SheetPlan(
            spec=_ccr1_spec(),
            frame=_prepare_ccr1(ccr),
            ctx=ReportingContext(),
            negative_cols=frozenset(),
        )
    }


def ccr1_frames(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, pl.DataFrame]:
    """Render the single CCR1 frame for lineage (keyed like ``ccr1_plans``)."""
    frame = generate_ccr1(results, cols)
    return {_CCR1_KEY: frame} if frame is not None else {}


def _ccr1_spec() -> TemplateSpec:
    """The CCR1 spec: the SA-CCR (``1``) and Total (``11``) rows sum EAD (col
    ``a``) over the whole SA-CCR population and default-risk RWEA (col ``b``)
    over the ``ccr1_default_risk`` partition. Shared by the reported generator
    and the lineage plan."""
    default_risk = RowPredicate(equals=((_DEFAULT_RISK, True),))
    ead = CellSpec(Sum("ead_final"))
    rwea = CellSpec(Sum("rwa_final"), predicate=default_risk)
    return TemplateSpec(
        name="ccr1",
        rows=tuple(CCR1_ROWS),
        column_refs=tuple(col.ref for col in CCR1_COLUMNS),
        cells={
            ("1", "a"): ead,
            ("1", "b"): rwea,
            ("11", "a"): ead,
            ("11", "b"): rwea,
        },
        empty_cell="null",
    )


def _prepare_ccr1(ccr: pl.DataFrame) -> pl.DataFrame:
    """Derive the CCR1 ``ccr1_default_risk`` complement flag the col-``b``
    predicate keys off.

    ``~((cp_entity_type == "ccp") & cp_is_qccp.fill_null(True))`` — the non-QCCP-
    trade complement the imperative ``_ccr_rwa`` summed (CRR Art. 107(2)(a)).
    Absent ``cp_entity_type`` / ``cp_is_qccp`` yields an all-null flag so col
    ``b`` selects nothing (the imperative ``_ccr_rwa`` None guard)."""
    if {"cp_entity_type", "cp_is_qccp"} <= set(ccr.columns):
        default_risk = ~(
            (pl.col("cp_entity_type") == "ccp") & pl.col("cp_is_qccp").fill_null(value=True)
        )
    else:
        default_risk = pl.lit(None, dtype=pl.Boolean)
    return ccr.with_columns(default_risk.alias(_DEFAULT_RISK))


# =============================================================================
# CCR2 — CVA capital charge (BA-CVA RWEA, broadcast constant)
# =============================================================================


@cites("PS1/26, paragraph 4.2")
def generate_ccr2(results: pl.LazyFrame, cols: set[str]) -> pl.DataFrame | None:
    """Execute CCR2 (BA-CVA RWEA, col ``a``).

    Presence-gated exactly like the imperative generator: None when ``cva_rwa``
    is absent or all-null (which is what makes CCR2 None under CRR — no explicit
    framework gate). The gate and the cell read the same broadcast constant.
    """
    if _cva_rwea(results, cols) is None:
        return None
    return execute(_ccr2_spec(), results)


def ccr2_plans(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, SheetPlan]:
    """Build the single CCR2 execution plan for lineage (single frame).

    Presence-gated on ``cva_rwa`` (a CRR run carries none, so a CRR lineage
    request degrades to a clean no-lineage — the CMS/OF 02.01 pattern). The cell
    reads the portfolio BA-CVA roll-up as a broadcast per-row constant over the
    whole ledger (the OV1 row-26 idiom), so the plan frame is the full ledger and
    the drill-down shows the legs carrying that constant. No "(-)" deduction
    column.
    """
    if _cva_rwea(results, cols) is None:
        return {}
    return {
        _CCR2_KEY: SheetPlan(
            spec=_ccr2_spec(),
            frame=results.collect(),
            ctx=ReportingContext(),
            negative_cols=frozenset(),
        )
    }


def ccr2_frames(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, pl.DataFrame]:
    """Render the single CCR2 frame for lineage (keyed like ``ccr2_plans``)."""
    frame = generate_ccr2(results, cols)
    return {_CCR2_KEY: frame} if frame is not None else {}


def _ccr2_spec() -> TemplateSpec:
    """The CCR2 spec: the BA-CVA (``4``) and Total (``6``) rows read the
    portfolio ``cva_rwa`` roll-up (a broadcast constant) as ``FirstNonNull`` in
    col ``a``. The SA-CVA row (``5``) stays null. Shared by the reported
    generator and the lineage plan."""
    cva = CellSpec(FirstNonNull("cva_rwa"))
    return TemplateSpec(
        name="ccr2",
        rows=tuple(CCR2_ROWS),
        column_refs=tuple(col.ref for col in CCR2_COLUMNS),
        cells={
            ("4", "a"): cva,
            ("6", "a"): cva,
        },
        empty_cell="null",
    )


def _cva_rwea(results: pl.LazyFrame, cols: set[str]) -> float | None:
    """The portfolio BA-CVA roll-up (``cva_rwa``) as the first non-null value.

    Mirrors the imperative ``_first_non_null`` emission gate — ``cva_rwa`` is a
    broadcast constant, so the first non-null value is the one the
    ``FirstNonNull`` cell reads. None when the column is absent or all-null.
    """
    cva_col = pick(cols, "cva_rwa")
    if cva_col is None:
        return None
    value = results.select(pl.col(cva_col).drop_nulls().first()).collect()
    if value.height == 0:
        return None
    item = value.item()
    return float(item) if item is not None else None


# =============================================================================
# CCR3 — SA-CCR EAD by risk-weight band
# =============================================================================


@cites("CRR Art. 444")
def generate_ccr3(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> pl.DataFrame | None:
    """Execute CCR3 (SA-CCR EAD by risk-weight band, col ``a``).

    Returns None when the portfolio carries no ``ccr__`` rows; a missing
    ``risk_weight`` column records the CCR3 error and yields None (the imperative
    error contract).
    """
    ccr = _collect_ccr_rows(results, cols)
    if ccr is None or ccr.height == 0:
        return None
    if "risk_weight" not in ccr.columns:
        errors.append("CCR3: missing risk_weight column")
        return None
    return execute(_ccr3_spec(framework), _prepare_ccr3(ccr, framework))


def ccr3_plans(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, SheetPlan]:
    """Build the single CCR3 execution plan for lineage (single frame).

    The plan frame is the pre-filtered SA-CCR population carrying the derived
    ``ccr3_band`` label column, so each band row narrows to its matched band and
    the Total row sums the whole frame. Yields ``{}`` when no CCR rows exist or
    ``risk_weight`` is absent (a clean no-lineage; the error is recorded by the
    reported generator, not the lineage view). No "(-)" deduction column.
    """
    ccr = _collect_ccr_rows(results, cols)
    if ccr is None or ccr.height == 0 or "risk_weight" not in ccr.columns:
        return {}
    return {
        _CCR3_KEY: SheetPlan(
            spec=_ccr3_spec(framework),
            frame=_prepare_ccr3(ccr, framework),
            ctx=ReportingContext(),
            negative_cols=frozenset(),
        )
    }


def ccr3_frames(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, pl.DataFrame]:
    """Render the single CCR3 frame for lineage (keyed like ``ccr3_plans``)."""
    plans = ccr3_plans(results, cols, framework, errors)
    return {key: execute(plan.spec, plan.frame, plan.ctx) for key, plan in plans.items()}


def _ccr3_spec(framework: str) -> TemplateSpec:
    """The CCR3 spec: one ``Sum("ead_final")`` band row per CR5 risk-weight band
    (keyed on the derived ``ccr3_band`` label), an "Other" catch-all, and the
    Total row summing the whole SA-CCR population. Framework-variant (the CRR /
    Basel 3.1 CR5 band lists differ). Shared by the reported generator and the
    lineage plan."""
    rows = get_ccr3_rows(framework)
    rw_bands = get_ccr3_risk_weights(framework)
    cells: dict[tuple[str, str], CellSpec] = {}
    for i, _band in enumerate(rw_bands):
        ref = rows[i].ref
        cells[(ref, "a")] = CellSpec(
            Sum("ead_final"), predicate=RowPredicate(equals=((_BAND, ref),))
        )
    other_ref = rows[len(rw_bands)].ref
    cells[(other_ref, "a")] = CellSpec(
        Sum("ead_final"), predicate=RowPredicate(equals=((_BAND, "other"),))
    )
    total_ref = rows[len(rw_bands) + 1].ref
    cells[(total_ref, "a")] = CellSpec(Sum("ead_final"))
    return TemplateSpec(
        name="ccr3",
        rows=tuple(rows),
        column_refs=tuple(col.ref for col in CCR3_COLUMNS),
        cells=cells,
        empty_cell="null",
    )


def _prepare_ccr3(ccr: pl.DataFrame, framework: str) -> pl.DataFrame:
    """Derive the CCR3 ``ccr3_band`` label the band-row predicates key off.

    A first-match assignment of each ``ccr__`` row's ``risk_weight`` to a CR5
    band ref (within ±0.005, the retired ``_ccr3_band_eads`` tolerance), else
    ``"other"``. The bands do not overlap, so first-match equals the imperative
    independent per-band filter, and the "other" bucket is the complement of the
    union of the bands (the imperative ``~matched_mask``).
    """
    rows = get_ccr3_rows(framework)
    rw_bands = get_ccr3_risk_weights(framework)
    band_expr: pl.Expr | None = None
    for i, (rate, _label) in enumerate(rw_bands):
        in_band = (pl.col("risk_weight") >= rate - _BAND_TOL) & (
            pl.col("risk_weight") <= rate + _BAND_TOL
        )
        ref = pl.lit(rows[i].ref)
        band_expr = (
            pl.when(in_band).then(ref) if band_expr is None else band_expr.when(in_band).then(ref)
        )
    label = band_expr.otherwise(pl.lit("other")) if band_expr is not None else pl.lit("other")
    return ccr.with_columns(label.alias(_BAND))


# =============================================================================
# CCR8 — exposures to central counterparties (QCCP / non-QCCP / Total)
# =============================================================================


@cites("CRR Art. 306")
def generate_ccr8(results: pl.LazyFrame, cols: set[str]) -> pl.DataFrame | None:
    """Execute CCR8 (CCP exposures: QCCP ``1`` / non-QCCP ``2`` / Total ``21``,
    each RWEA col ``a`` + EAD col ``b``).

    Emitted only when the portfolio has CCP exposures (the R5 emission gate) —
    a book of purely bilateral derivatives / SFTs has nothing to disclose here.
    Returns None when the ``cp_entity_type`` / ``cp_is_qccp`` discriminators are
    absent, or no CCP counterparty is present.
    """
    ccr = _prepare_ccr8(results, cols)
    if ccr is None:
        return None
    return execute(_ccr8_spec(), ccr)


def ccr8_plans(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, SheetPlan]:
    """Build the single CCR8 execution plan for lineage (single frame).

    The plan frame is the ``include_sft=True`` SA-CCR population carrying the
    derived ``ccr8_qccp`` flag: each cell's own predicate narrows it to the CCP
    subset (rows 0010/0020 by the qualifying flag, row 0021 the whole CCP
    population). Yields ``{}`` under the R5 emission gate (a clean no-lineage,
    the reported None). No "(-)" deduction column.
    """
    ccr = _prepare_ccr8(results, cols)
    if ccr is None:
        return {}
    return {
        _CCR8_KEY: SheetPlan(
            spec=_ccr8_spec(),
            frame=ccr,
            ctx=ReportingContext(),
            negative_cols=frozenset(),
        )
    }


def ccr8_frames(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, pl.DataFrame]:
    """Render the single CCR8 frame for lineage (keyed like ``ccr8_plans``)."""
    frame = generate_ccr8(results, cols)
    return {_CCR8_KEY: frame} if frame is not None else {}


def _ccr8_spec() -> TemplateSpec:
    """The CCR8 spec: rows ``1``/``2`` partition the CCP subset by the derived
    ``ccr8_qccp`` flag; row ``21`` keys the whole CCP population. Each row sums
    RWEA (col ``a``) and EAD (col ``b``). Shared by the reported generator and
    the lineage plan."""
    qccp = RowPredicate(equals=(("cp_entity_type", "ccp"), (_QCCP, True)))
    non_qccp = RowPredicate(equals=(("cp_entity_type", "ccp"), (_QCCP, False)))
    ccp = RowPredicate(equals=(("cp_entity_type", "ccp"),))
    return TemplateSpec(
        name="ccr8",
        rows=tuple(CCR8_ROWS),
        column_refs=tuple(col.ref for col in CCR8_COLUMNS),
        cells={
            ("1", "a"): CellSpec(Sum("rwa_final"), predicate=qccp),
            ("1", "b"): CellSpec(Sum("ead_final"), predicate=qccp),
            ("2", "a"): CellSpec(Sum("rwa_final"), predicate=non_qccp),
            ("2", "b"): CellSpec(Sum("ead_final"), predicate=non_qccp),
            ("21", "a"): CellSpec(Sum("rwa_final"), predicate=ccp),
            ("21", "b"): CellSpec(Sum("ead_final"), predicate=ccp),
        },
        empty_cell="null",
    )


def _prepare_ccr8(results: pl.LazyFrame, cols: set[str]) -> pl.DataFrame | None:
    """Materialise the CCR8 population + derived ``ccr8_qccp`` flag, or None.

    Collects the ``include_sft=True`` SA-CCR population (a CCP-faced SFT IS a CCP
    exposure — CRR Art. 301(1)(b)), requires the ``cp_entity_type`` /
    ``cp_is_qccp`` discriminators, applies the R5 emission gate (at least one CCP
    counterparty), and derives ``ccr8_qccp = cp_is_qccp.fill_null(True)`` (a null
    CCP treated as qualifying, CRR Art. 306(1)). Returns None when any gate
    fails — the imperative CCR8 None path.
    """
    ccr = _collect_ccr_rows(results, cols, include_sft=True)
    if ccr is None or ccr.height == 0:
        return None
    if not {"cp_entity_type", "cp_is_qccp"} <= set(ccr.columns):
        return None
    if ccr.filter(pl.col("cp_entity_type") == "ccp").height == 0:
        return None
    return ccr.with_columns(pl.col("cp_is_qccp").fill_null(value=True).alias(_QCCP))


# =============================================================================
# SHARED CCR POPULATION HELPER (the Pillar 3 CCR home)
# =============================================================================


def _collect_ccr_rows(
    results: pl.LazyFrame, cols: set[str], *, include_sft: bool = False
) -> pl.DataFrame | None:
    """Collect the synthetic ``ccr__``-prefixed CCR rows, or None if absent.

    The CCR disclosure tables read the same synthetic netting-set rows the
    aggregator rolls up (CRR Art. 274(2)). Returns None when the results frame
    carries no ``exposure_reference`` column; an empty selection returns an empty
    DataFrame (the callers gate on ``height == 0``).

    ``include_sft`` selects whether FCCM SFT rows (``risk_type == "CCR_SFT"``)
    are kept. The SA-CCR analysis templates (CCR1/CCR3) take the default (SFTs
    EXCLUDED — an SFT uses FCCM under Art. 220-223, not the SA-CCR Art. 274
    approach these templates analyse; an SFT not faced to a CCP discloses under
    SA template C 07.00 row 0090). CCR8 ("Exposures to central counterparties",
    CRR Art. 439(i)) passes ``include_sft=True`` because a CCP-faced SFT trade
    exposure IS a CCP exposure (CRR Art. 301(1)(b)); CCR8 then restricts the
    population to CCP counterparties, which is what drops a bilateral SFT. The
    SFT exclusion (default path) is gated on ``risk_type`` being present so a
    portfolio that predates the column is unaffected.

    This is the Pillar 3 counterpart of ``corep.c34.collect_ccr_rows``; it is
    kept LOCAL (deliberately not shared) because it gates only on
    ``exposure_reference`` (not the C 34 ``{exposure_reference, ead_final,
    rwa_final}`` set) and returns an empty frame rather than None for an empty
    selection — the exact contract the retired ``_ccr_rows`` carried.
    """
    ref_col = pick(cols, "exposure_reference")
    if not ref_col:
        return None
    # An empty / all-null results frame can carry exposure_reference as a Null
    # dtype; ``.str.starts_with`` only operates on String. Cast defensively so
    # the CCR filter degenerates to an empty selection rather than raising.
    is_ccr = pl.col(ref_col).cast(pl.String).str.starts_with("ccr__")
    if include_sft:
        return results.filter(is_ccr).collect()
    not_sft = pl.col("risk_type") != "CCR_SFT" if "risk_type" in cols else pl.lit(value=True)
    return results.filter(is_ccr & not_sft).collect()
