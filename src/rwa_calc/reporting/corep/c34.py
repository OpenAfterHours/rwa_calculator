"""
COREP C 34.01 / C 34.02 / C 34.04 / C 34.08 — counterparty credit risk, declarative.

Pipeline position:
    sealed aggregator-exit ledger
        -> c34_0x_plans() -> SheetPlan(s) -> cellspec.execute()
        -> DataFrame | None | dict[str, DataFrame]

The four in-scope C 34 templates, converted from the imperative
``COREPGenerator._generate_c34_0x`` methods to declarative ``TemplateSpec``\\s
run through the one ``cellspec.execute`` executor (Phase 7 S8; R27a the three
single-frame templates, R27b the per-netting-set C 34.02). The shared CCR
population helpers (``collect_ccr_rows`` / ``collect_default_fund``) are the CCR
home for the whole family.

Lineage-instrumented: each ``c34_0x_plans`` exposes its execution plan(s) so
``reporting.lineage`` can drill into a reported cell; the ``c34_0x_frames``
wrappers key the reported frame (with the emission gate) under the same key(s) —
the single-frame canonical key for C 34.01/04/08 (R27a), one key per netting set
for C 34.02 (R27b, the first multi-sheet C 34 template). None carry a
post-``execute`` pass, so a cell's reported value is a plain ``execute`` of its
plan.

Cell semantics (recorded decisions, unchanged from the imperative generators —
golden-gated for C 34.01 / C 34.02 / C 34.08; the CVA C 34.04 has no producing
golden fixture and is pinned by the CVA-A1 unit estate + a seeded lineage unit
pin):

- **C 34.01 (SA-CCR analysis by approach).** One row (0010, "SA-CCR"): col 0010
  sums ``ead_final`` and col 0020 ``rwa_final`` over the SA-CCR netting-set
  population — the synthetic ``ccr__``-prefixed rows, with FCCM SFTs EXCLUDED
  (``risk_type == "CCR_SFT"`` reports on C 07.00 row 0090, not the SA-CCR
  templates; PS1/26 App. 17). The plan frame IS that pre-filtered population (the
  CR8 pattern), so both cells sum the whole frame. None when the portfolio has no
  such rows (the ``generate_of_02_01`` gated precedent).
- **C 34.02 (SA-CCR EAD per netting set).** ONE sheet per netting set, keyed on
  the ``netting_set_id`` stripped from the ``ccr__`` reference prefix. Each
  sheet's single row (0010) sums ``ead_final`` (col 0010) over that netting
  set's legs — the same SA-CCR population as C 34.01, partitioned by netting set
  (CRR Art. 274(2) EAD = alpha * (RC + PFE) per netting set; Art. 275 the
  netting-set boundary). Empty dict when the portfolio has no SA-CCR rows (the
  imperative ``{}`` preserved).
- **C 34.04 (CVA capital, BA-CVA).** Basel 3.1 ONLY. One row (0010): col 0010 is
  the portfolio ``cva_rwa`` roll-up — a broadcast per-row constant surfaced by
  the aggregation stage's BA-CVA roll-up, read as a ``FirstNonNull`` over the
  whole ledger (the OV1 row-26 broadcast-constant idiom; byte-identical to the
  imperative ``max(cva_rwa)`` because the column is constant). None under CRR, or
  when ``cva_rwa`` is absent / non-positive.
- **C 34.08 (CCP exposures).** Discloses exposures to CENTRAL COUNTERPARTIES
  only. Row 0010 (QCCP trade) and row 0020 (non-QCCP trade) draw from the SA-CCR
  netting-set population RESTRICTED to CCP counterparties
  (``cp_entity_type == "ccp"``), split by the qualifying-CCP flag
  (``cp_is_qccp.fill_null(True)`` — derived here as ``c34_qccp``; CRR Art. 306(1)
  QCCP vs Art. 107(2)(a) non-QCCP). A bilateral OTC counterparty is NEITHER row
  (it discloses on C 34.01/02, the R5 CCP restriction). Row 0030 (default fund)
  draws its OWN population — the ``CCR_DEFAULT_FUND`` risk type (Art. 308/309).
  Each row reports EAD (col 0010) and RWEA (col 0020). Emitted only when the
  portfolio has CCP trade legs or default-fund contributions (the R5 emission
  gate).

References:
- Regulation (EU) 2021/451, Annex I/II (C 34 CCR template family)
- CRR Art. 274(2): SA-CCR EAD = alpha * (RC + PFE)
- CRR Art. 306(1)(a)/(c): 2% / 4% QCCP trade-leg risk weight; Art. 107(2)(a)
- CRR Art. 308/309: default fund contribution exposures
- PRA PS1/26 App.1 CVA Part Ch.4.2-4.4 (BA-CVA reduced — C 34.04)
- docs/plans/phase7-declarative-reporting.md §3.2/§6 (S8)
- docs/features/report-cell-lineage.md (per-template lineage recipe)
"""

from __future__ import annotations

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
from rwa_calc.reporting.corep.templates import (
    C34_01_COLUMN_REFS,
    C34_01_ROWS,
    C34_02_COLUMN_REFS,
    C34_02_ROWS,
    C34_04_COLUMN_REFS,
    C34_04_ROWS,
    C34_08_COLUMN_REFS,
    C34_08_ROWS,
)
from rwa_calc.reporting.kernel import pick
from rwa_calc.reporting.metadata import ReportingContext
from rwa_calc.reporting.plans import SheetPlan

# Single-frame lineage keys: each single-frame C 34 template has no sheet axis, so its one
# plan keys under a canonical name (see reporting.plans / _resolve_sheet_key
# single_frame path). The reported catalogue id is the same string.
_C34_01_KEY = "c34_01"
_C34_04_KEY = "c34_04"
_C34_08_KEY = "c34_08"

# The module-derived C 34.08 discriminator columns (the established pattern —
# of02_is_ccr, c07_qccp): a RowPredicate carries no ``str.starts_with`` and no
# ``fill_null`` term, so both the CCR-population membership and the
# null-treated-as-qualifying QCCP flag are derived here as Boolean flag columns.
_IS_CCR: str = "c34_is_ccr"
_QCCP: str = "c34_qccp"


# =============================================================================
# C 34.01 — SA-CCR analysis by approach (EAD + RWEA total)
# =============================================================================


@cites("CRR Art. 274")
def generate_c34_01(results: pl.LazyFrame, cols: set[str]) -> pl.DataFrame | None:
    """Execute C 34.01 (SA-CCR total EAD col 0010 + RWEA col 0020).

    Returns None when the portfolio carries no SA-CCR netting-set rows — the
    gated precedent of ``generate_of_02_01``.
    """
    ccr = collect_ccr_rows(results, cols)
    if ccr is None or len(ccr) == 0:
        return None
    return execute(_c34_01_spec(), ccr)


def c34_01_plans(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, SheetPlan]:
    """Build the single C 34.01 execution plan for lineage (single frame).

    The plan frame IS the pre-filtered SA-CCR netting-set population (the CR8
    pattern), so both cells sum the whole frame and the scope wording carries the
    population. No "(-)"-labelled deduction column, so ``negative_cols`` is empty.
    Yields ``{}`` when the portfolio has no such rows (a clean no-lineage, the
    reported None).
    """
    ccr = collect_ccr_rows(results, cols)
    if ccr is None or len(ccr) == 0:
        return {}
    return {
        _C34_01_KEY: SheetPlan(
            spec=_c34_01_spec(),
            frame=ccr,
            ctx=ReportingContext(),
            negative_cols=frozenset(),
        )
    }


def c34_01_frames(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, pl.DataFrame]:
    """Render the single C 34.01 frame for lineage (keyed like ``c34_01_plans``)."""
    frame = generate_c34_01(results, cols)
    return {_C34_01_KEY: frame} if frame is not None else {}


def _c34_01_spec() -> TemplateSpec:
    """The C 34.01 spec: one SA-CCR row summing EAD (0010) and RWEA (0020) over
    the pre-filtered netting-set population. Shared by the reported generator and
    the lineage plan."""
    return TemplateSpec(
        name="c34_01",
        rows=tuple(C34_01_ROWS),
        column_refs=tuple(C34_01_COLUMN_REFS),
        cells={
            ("0010", "0010"): CellSpec(Sum("ead_final")),
            ("0010", "0020"): CellSpec(Sum("rwa_final")),
        },
        empty_cell="zero",
    )


# =============================================================================
# C 34.02 — SA-CCR EAD per netting set (one sheet per netting_set_id)
# =============================================================================


@cites("CRR Art. 274")
def generate_c34_02(results: pl.LazyFrame, cols: set[str]) -> dict[str, pl.DataFrame]:
    """Execute C 34.02 (SA-CCR EAD per netting set).

    Returns one 1-row DataFrame per netting set (col 0010 sums that netting
    set's ``ead_final``), keyed by ``netting_set_id`` — the multi-sheet dict the
    exporter fans out to ``c34_02__<netting_set_id>`` sheets. Empty dict when the
    portfolio carries no SA-CCR netting-set rows (the imperative ``{}``).
    """
    return _c34_02_render(c34_02_plans(results, cols, "", []))


def c34_02_plans(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, SheetPlan]:
    """Build the per-netting-set C 34.02 execution plans for lineage.

    First multi-sheet C 34 instrumentation (the ``c08_04`` / ``cr7a`` pattern):
    each sheet's plan frame is that netting set's slice of the pre-filtered
    SA-CCR population (FCCM SFTs already excluded by ``collect_ccr_rows``), so
    the single ``Sum("ead_final")`` cell sums exactly that netting set's legs.
    Sheets key on the ``netting_set_id`` derived from the ``ccr__`` reference
    prefix, sorted for determinism (the ``c08_04`` keying). Yields ``{}`` when
    the portfolio has no such rows (a clean no-lineage, the reported empty dict).
    C 34.02 carries no "(-)"-labelled deduction column, so ``negative_cols`` is
    empty.
    """
    ccr = collect_ccr_rows(results, cols)
    if ccr is None or len(ccr) == 0:
        return {}
    spec = _c34_02_spec()
    plans: dict[str, SheetPlan] = {}
    for ns_id in ccr["netting_set_id"].drop_nulls().unique().sort().to_list():
        plans[ns_id] = SheetPlan(
            spec=spec,
            frame=ccr.filter(pl.col("netting_set_id") == ns_id),
            ctx=ReportingContext(),
            negative_cols=frozenset(),
        )
    return plans


def c34_02_frames(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, pl.DataFrame]:
    """Render the per-netting-set C 34.02 frames for lineage (keyed like
    ``c34_02_plans``). Identical to the reported ``generate_c34_02`` — C 34.02
    has no framework dependency, no prior period and no post-execute pass, so a
    cell's reported value is a plain ``execute`` of its plan."""
    return _c34_02_render(c34_02_plans(results, cols, framework, errors))


def _c34_02_render(plans: dict[str, SheetPlan]) -> dict[str, pl.DataFrame]:
    """Execute each netting-set plan into its reported frame."""
    return {key: execute(plan.spec, plan.frame, plan.ctx) for key, plan in plans.items()}


def _c34_02_spec() -> TemplateSpec:
    """The C 34.02 spec: one netting-set row summing EAD (col 0010) over that
    netting set's slice of the SA-CCR population. Shared by the reported
    generator and the lineage plans — the per-sheet frame supplies the
    netting-set narrowing, so the spec itself carries no predicate."""
    return TemplateSpec(
        name="c34_02",
        rows=tuple(C34_02_ROWS),
        column_refs=tuple(C34_02_COLUMN_REFS),
        cells={("0010", "0010"): CellSpec(Sum("ead_final"))},
        empty_cell="zero",
    )


# =============================================================================
# C 34.04 — CVA capital (BA-CVA RWEA, Basel 3.1 only)
# =============================================================================


@cites("PS1/26, paragraph 4.2")
def generate_c34_04(results: pl.LazyFrame, cols: set[str], framework: str) -> pl.DataFrame | None:
    """Execute C 34.04 (BA-CVA RWEA, col 0010). Basel 3.1 only.

    Returns None under CRR, or when no ``cva_rwa`` column / a non-positive value
    is present — mirroring the ``generate_of_02_01`` gated-grid precedent. The
    gate reads the whole-ledger ``max(cva_rwa)`` (the imperative basis); the cell
    reads the same broadcast constant via ``FirstNonNull``.
    """
    if framework != "BASEL_3_1":
        return None
    if not _cva_positive(results, cols):
        return None
    return execute(_c34_04_spec(), results)


def c34_04_plans(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, SheetPlan]:
    """Build the single C 34.04 execution plan for lineage (single frame).

    Framework-gated like CMS1/CMS2/OF 02.01: a CRR run yields ``{}`` (C 34.04 is
    not produced under CRR), so a CRR lineage request degrades to a clean
    no-lineage. Also gated on a positive ``cva_rwa``. The cell reads the
    portfolio BA-CVA roll-up as a broadcast constant over the whole ledger (the
    OV1 row-26 idiom), so the plan frame is the full ledger and the drill-down
    shows the legs carrying that constant. No "(-)" deduction column.
    """
    if framework != "BASEL_3_1":
        return {}
    if not _cva_positive(results, cols):
        return {}
    return {
        _C34_04_KEY: SheetPlan(
            spec=_c34_04_spec(),
            frame=results.collect(),
            ctx=ReportingContext(),
            negative_cols=frozenset(),
        )
    }


def c34_04_frames(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, pl.DataFrame]:
    """Render the single C 34.04 frame for lineage (keyed like ``c34_04_plans``)."""
    frame = generate_c34_04(results, cols, framework)
    return {_C34_04_KEY: frame} if frame is not None else {}


def _c34_04_spec() -> TemplateSpec:
    """The C 34.04 spec: one CVA row reading the portfolio ``cva_rwa`` roll-up
    (a broadcast constant) as ``FirstNonNull``. Shared by the reported generator
    and the lineage plan."""
    return TemplateSpec(
        name="c34_04",
        rows=tuple(C34_04_ROWS),
        column_refs=tuple(C34_04_COLUMN_REFS),
        cells={("0010", "0010"): CellSpec(FirstNonNull("cva_rwa"))},
        empty_cell="zero",
    )


def _cva_positive(results: pl.LazyFrame, cols: set[str]) -> bool:
    """Whether ``cva_rwa`` is present and its portfolio roll-up is positive.

    Reads the whole-ledger maximum (the imperative basis) — ``cva_rwa`` is a
    broadcast constant, so ``max`` == the value the ``FirstNonNull`` cell reads.
    """
    cva_col = pick(cols, "cva_rwa")
    if cva_col is None:
        return False
    value = results.select(pl.col(cva_col).max().alias("_cva")).collect()["_cva"][0]
    return value is not None and float(value) > 0.0


# =============================================================================
# C 34.08 — CCP exposures (QCCP trade, non-QCCP, default fund)
# =============================================================================


@cites("CRR Art. 306")
def generate_c34_08(results: pl.LazyFrame, cols: set[str]) -> pl.DataFrame | None:
    """Execute C 34.08 (CCP exposures: QCCP 0010 / non-QCCP 0020 / default fund
    0030, each EAD col 0010 + RWEA col 0020).

    Emitted only when the portfolio has CCP trade legs or default-fund
    contributions (the R5 emission gate) — a book of purely bilateral derivatives
    has nothing to disclose here.
    """
    if not _c34_08_emits(results, cols):
        return None
    return execute(_c34_08_spec(), _prepare_c34_08(results, cols))


def c34_08_plans(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, SheetPlan]:
    """Build the single C 34.08 execution plan for lineage (single frame).

    The plan frame is the prepared FULL ledger (with the derived ``c34_is_ccr`` /
    ``c34_qccp`` discriminators): each cell's own predicate narrows it — rows
    0010/0020 to the CCP subset of the SA-CCR population, row 0030 to the
    ``CCR_DEFAULT_FUND`` risk type. Yields ``{}`` under the R5 emission gate (a
    clean no-lineage, the reported None). No "(-)" deduction column.
    """
    if not _c34_08_emits(results, cols):
        return {}
    return {
        _C34_08_KEY: SheetPlan(
            spec=_c34_08_spec(),
            frame=_prepare_c34_08(results, cols).collect(),
            ctx=ReportingContext(),
            negative_cols=frozenset(),
        )
    }


def c34_08_frames(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, pl.DataFrame]:
    """Render the single C 34.08 frame for lineage (keyed like ``c34_08_plans``)."""
    frame = generate_c34_08(results, cols)
    return {_C34_08_KEY: frame} if frame is not None else {}


def _c34_08_spec() -> TemplateSpec:
    """The C 34.08 spec: rows 0010/0020 partition the CCP subset of the SA-CCR
    population by the derived ``c34_qccp`` flag; row 0030 keys the
    ``CCR_DEFAULT_FUND`` risk type. Shared by the reported generator and the
    lineage plan."""
    ccp_qccp = RowPredicate(equals=((_IS_CCR, True), ("cp_entity_type", "ccp"), (_QCCP, True)))
    ccp_non_qccp = RowPredicate(equals=((_IS_CCR, True), ("cp_entity_type", "ccp"), (_QCCP, False)))
    default_fund = RowPredicate(equals=(("risk_type", "CCR_DEFAULT_FUND"),))
    return TemplateSpec(
        name="c34_08",
        rows=tuple(C34_08_ROWS),
        column_refs=tuple(C34_08_COLUMN_REFS),
        cells={
            ("0010", "0010"): CellSpec(Sum("ead_final"), predicate=ccp_qccp),
            ("0010", "0020"): CellSpec(Sum("rwa_final"), predicate=ccp_qccp),
            ("0020", "0010"): CellSpec(Sum("ead_final"), predicate=ccp_non_qccp),
            ("0020", "0020"): CellSpec(Sum("rwa_final"), predicate=ccp_non_qccp),
            ("0030", "0010"): CellSpec(Sum("ead_final"), predicate=default_fund),
            ("0030", "0020"): CellSpec(Sum("rwa_final"), predicate=default_fund),
        },
        empty_cell="zero",
    )


def _prepare_c34_08(results: pl.LazyFrame, cols: set[str]) -> pl.LazyFrame:
    """Derive the two C 34.08 discriminator columns the row predicates key off.

    ``c34_is_ccr`` mirrors ``collect_ccr_rows``: a ``ccr__``-prefixed reference
    with FCCM SFTs excluded (absent ``risk_type`` -> no exclusion; absent
    ``exposure_reference`` -> no CCR rows). ``c34_qccp`` is
    ``cp_is_qccp.fill_null(True)`` (null CCP treated as qualifying, CRR
    Art. 306(1)); absent ``cp_is_qccp`` yields an all-null flag so BOTH rows
    0010/0020 select nothing — matching the imperative's ``has_disc`` gate.
    """
    if "exposure_reference" in cols:
        is_ccr = pl.col("exposure_reference").str.starts_with("ccr__")
        if "risk_type" in cols:
            is_ccr = is_ccr & (pl.col("risk_type") != "CCR_SFT")
    else:
        is_ccr = pl.lit(value=False)
    qccp = (
        pl.col("cp_is_qccp").fill_null(value=True)
        if "cp_is_qccp" in cols
        else pl.lit(None, dtype=pl.Boolean)
    )
    return results.with_columns(is_ccr.alias(_IS_CCR), qccp.alias(_QCCP))


def _c34_08_emits(results: pl.LazyFrame, cols: set[str]) -> bool:
    """The R5 emission gate: CCP trade legs OR default-fund contributions.

    Reproduces the imperative gate exactly — ``has_disc`` requires the
    ``cp_entity_type`` / ``cp_is_qccp`` discriminators present alongside the
    SA-CCR population, and a default-fund contribution alone is enough to emit.
    """
    ccr = collect_ccr_rows(results, cols)
    _fund_ead, fund_rwea = collect_default_fund(results, cols)
    has_disc = (
        ccr is not None and len(ccr) > 0 and {"cp_entity_type", "cp_is_qccp"} <= set(ccr.columns)
    )
    has_ccp = has_disc and len(ccr.filter(pl.col("cp_entity_type") == "ccp")) > 0
    return has_ccp or fund_rwea > 0.0


# =============================================================================
# SHARED CCR POPULATION HELPERS (the CCR home; C 34.02 imports these back)
# =============================================================================


def collect_ccr_rows(results: pl.LazyFrame, cols: set[str]) -> pl.DataFrame | None:
    """Materialise the synthetic SA-CCR netting-set rows from the results frame.

    Filters to the ``ccr__``-prefixed ``exposure_reference`` rows and derives a
    ``netting_set_id`` column by stripping that prefix (the per-row
    ``exposure_reference`` is ``ccr__{netting_set_id}``). Returns None when the
    discriminating columns are absent (CCR-free portfolio).

    FCCM SFT rows (``risk_type == "CCR_SFT"`` / ``ccr_method == "fccm_sft"``)
    share the ``ccr__`` reference prefix but are EXCLUDED here: per PS1/26
    App. 17 they are reported under SA template C 07.00 row 0090
    ("SFT netting sets"), not the SA-CCR templates (C 34.01/02/08). Only OTC
    derivatives (``risk_type == "CCR_DERIVATIVE"``) and CCP exposures belong in
    the SA-CCR templates (CRR Art. 274/306). The exclusion is gated on the
    ``risk_type`` column being present so a portfolio that predates the column
    is unaffected.

    References:
        CRR Art. 274(2): the synthetic SA-CCR rows carry EAD = alpha * (RC + PFE).
        PS1/26 App. 17: SFTs report under C 07.00 row 0090, not C 34.
    """
    if not ({"exposure_reference", "ead_final", "rwa_final"} <= cols):
        return None
    is_ccr = pl.col("exposure_reference").str.starts_with("ccr__")
    not_sft = pl.col("risk_type") != "CCR_SFT" if "risk_type" in cols else pl.lit(True)
    ccr = (
        results.filter(is_ccr & not_sft)
        .with_columns(
            pl.col("exposure_reference").str.strip_prefix("ccr__").alias("netting_set_id")
        )
        .collect()
    )
    if len(ccr) == 0:
        return None
    return ccr


def collect_default_fund(results: pl.LazyFrame, cols: set[str]) -> tuple[float, float]:
    """Sum EAD and RWEA over the synthetic ``CCR_DEFAULT_FUND`` rows.

    Returns ``(0.0, 0.0)`` when the ``risk_type`` discriminator is absent or no
    default-fund rows are present (CRR Art. 308/309).
    """
    if "risk_type" not in cols or "rwa_final" not in cols:
        return 0.0, 0.0
    ead_expr = (
        pl.col("ead_final").fill_null(0.0).sum().alias("_ead")
        if "ead_final" in cols
        else pl.lit(0.0).alias("_ead")
    )
    stats = (
        results.filter(pl.col("risk_type") == "CCR_DEFAULT_FUND")
        .select(ead_expr, pl.col("rwa_final").fill_null(0.0).sum().alias("_rwea"))
        .collect()
    )
    if len(stats) == 0:
        return 0.0, 0.0
    return float(stats["_ead"][0]), float(stats["_rwea"][0])
