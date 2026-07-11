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

- All five dicts key on RAW ``exposure_class`` (== ``reporting_class_origin``
  for IRB rows — the obligor basis, number-neutral; no applied-class ladder
  and NO specialised-lending merge, unlike C 07.00). The population is the
  origin IRB book (F-IRB / A-IRB / slotting); C 08.03/04/05 exclude
  slotting per template.
- C 08.01/02 share one value surface (computed framework-agnostic, filtered
  by each framework's column refs): gross exposures, the CRM waterfall
  0090 = 0020 - 0040 - 0050 - 0060 - 0070 + 0080 over POSITIVE magnitudes,
  the cross-sheet substitution inflow (0080, total row only) via
  ``ReportingContext.substitution_inflow``, EAD-weighted PD/LGD, maturity
  in DAYS (x365 — ``irb_maturity_m`` is years despite the suffix), LFSE
  sub-splits gated on ``cp_apply_fi_scalar`` presence, defaulted sub-splits
  via the retired detection ladder, CRR supporting-factor deltas (the
  asymmetric dedicated flag names preserved), B31 adjustment/output-floor
  columns, and the provisions ladder (SCRA/GCRA sums falling back to
  ``provision_held`` only when they net to ~0 — a value-dependent branch
  applied as a module post-step). ONLY column 0290 carries the Annex II
  "(-)" negation (a much smaller set than C 07.00's).
- The column-presence-vs-value-nullness distinction is load-bearing: e.g.
  column 0280 reads ``el_pre_adjustment`` whenever the COLUMN exists (its
  null values fill to 0.0 — masking ``expected_loss`` on slotting sheets,
  the recorded golden behaviour), falling back to ``expected_loss`` only
  when the column is absent.
- C 08.02's rows are data-driven (distinct firm grades when
  ``cp_internal_rating_grade`` has values, else the populated fixed PD
  bands, plus an "Unassigned" residual); ``row_ref == row_name == the
  String column 0005``, injected post-execute — the CR9.1 pattern.
- C 08.03/05 allocate rows over the 17 fixed PD ranges (B31 allocates on
  the pre-input-floor ``pd``, CRR on ``pd_floored``; the reported PD is
  always post-floor), emit ONLY populated buckets (sparse) plus an
  optional 9999 "Unassigned" row, and C 08.03's on/off-BS gross columns
  keep the retired whole-bucket fallback when the balance-sheet split
  yields nothing. C 08.05's averages are null-filled arithmetic means
  (weighted by a constant-one column), with the CR9-style point-in-time
  fallbacks for the prior-year/historical carriers.
- C 08.04 is the CR8-clone flow: only the closing-RWEA cell (row 0090) is
  populated — note its DELIBERATELY two-wide RWA ladder (``rwa_final``,
  ``rwa`` — no ``rwa_post_factor``).
- C 08.06 keys per-SL-type sheets (CRR's IPRE absorbs HVCRE when
  ``is_hvcre`` exists; B31 splits HVCRE out; empty SL types emit NO sheet)
  over the slotting-only book, with a per-ROW two-branch policy: empty
  non-Total rows zero-fill (0070 = the fixed display risk weight from the
  row definition), live rows and both maturity-split Total rows compute on
  data (0050/0060/0070/0031 null where the retired code reported None).
  CRR's 0080 prefers ``rwa_post_factor``; the maturity fallback is
  asymmetric (no ``is_short_maturity`` column -> short band empty, long
  band absorbs the category); the "substantially stronger" sub-rows are
  unconditionally empty.
- C 08.07 reads the FULL population (SA enters every denominator; null
  approach falls to SA; slotting counts as IRB) keyed on RAW
  ``exposure_class``; percentages are intra-row formulas guarding zero
  denominators to 0.0; the structural-null rows are a FIXED set (empty
  real-class rows stay 0.0 — the opposite of C 07.00's empty-subset rule);
  B31 materiality columns 0160-0180 are always null (the retired
  ``output_floor_config`` gate was dead code, recorded).

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
    RowPredicate,
    SafeSum,
    SideContext,
    Sum,
    TemplateSpec,
    WeightedAvg,
    execute,
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
from rwa_calc.reporting.kernel import col_sum, pick
from rwa_calc.reporting.metadata import ReportingContext

if TYPE_CHECKING:
    from collections.abc import Mapping

# Annex II "(-)" negation set for the C 08.01/02 surface — 0290 ONLY.
_NEGATIVE_COLS: frozenset[str] = frozenset({"0290"})

_IRB_APPROACHES: tuple[str, ...] = ("foundation_irb", "advanced_irb", "slotting")

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
    """C 08.05 col 0040 = defaults / obligors (0.0 when no obligors)."""
    obligors = cells["0020"] or 0.0
    if obligors <= 0:
        return 0.0
    return (cells["0030"] or 0.0) / obligors


# =============================================================================
# Shared population + derived discriminators
# =============================================================================


def _irb_population(results: pl.LazyFrame, cols: set[str]) -> pl.LazyFrame:
    """The IRB book (retired _filter_by_irb_approach): F-IRB/A-IRB/slotting."""
    approach_col = pick(cols, "approach_applied")
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
        "0020": CellSpec(SafeSum(("drawn_amount", "undrawn_amount")), predicate=member),
        "0030": _lfse_cell(cols, lambda: SafeSum(("drawn_amount", "undrawn_amount")), terms),
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
        "0100": CellSpec(Sum(ead_col), predicate=narrowed(("c08_bs", "off"))),
        "0101": CellSpec(Formula(refs=(), fn=_const(None))),
        "0102": CellSpec(Formula(refs=(), fn=_const(None))),
        "0103": CellSpec(Formula(refs=(), fn=_const(None))),
        "0104": CellSpec(Formula(refs=(), fn=_const(None))),
        "0110": CellSpec(Sum(ead_col), predicate=member),
        "0120": CellSpec(Formula(refs=(), fn=_const(None))),
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
            Sum("el_pre_adjustment" if "el_pre_adjustment" in cols else "expected_loss"),
            predicate=member,
        ),
        "0281": CellSpec(Sum("post_model_adjustment_el"), predicate=member),
        "0282": CellSpec(Sum("el_after_adjustment"), predicate=member),
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
                terms[ref] = (("approach_applied", "slotting"),)
            elif ref == "0190":
                terms[ref] = (("c08_unrated_corp", True),)
            elif ref == "0200":
                terms[ref] = (("c08_unrated_ig", True),)
            else:
                terms[ref] = None
    return terms


@cites("PS1/26, paragraph 1.3")
def generate_c08_01(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, pl.DataFrame]:
    """Execute C 08.01 per obligor-class sheet over the sealed ledger."""
    ec_col = pick(cols, "exposure_class")
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

    column_refs = tuple(col.ref for col in get_c08_columns(framework))
    rows = tuple(row for section in get_irb_row_sections(framework) for row in section.rows)
    row_terms = _c08_01_row_terms(framework, data_cols)

    cells: dict[tuple[str, str], CellSpec] = {}
    row_preds: dict[str, RowPredicate | None] = {}
    for row in rows:
        terms = row_terms.get(row.ref)
        if row.ref == "0070":
            # F-IRB/A-IRB (non-slotting) — a two-limb union.
            pred = RowPredicate(
                any_of=(
                    RowPredicate(equals=(("approach_applied", "foundation_irb"),)),
                    RowPredicate(equals=(("approach_applied", "advanced_irb"),)),
                )
            )
            row_preds[row.ref] = pred
            for col_ref, cell in _value_cells(
                (), data_cols, ead_col, rwa_col, column_refs, is_total=False
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
            row_preds[row.ref] = None
            continue
        row_preds[row.ref] = RowPredicate(equals=terms) if terms else RowPredicate()
        for col_ref, cell in _value_cells(
            terms, data_cols, ead_col, rwa_col, column_refs, is_total=row.ref == "0010"
        ).items():
            cells[(row.ref, col_ref)] = cell

    spec = TemplateSpec(
        name="c08_01", rows=rows, column_refs=column_refs, cells=cells, empty_cell="zero"
    )

    result: dict[str, pl.DataFrame] = {}
    for ec in irb_df[ec_col].unique().sort().to_list():
        class_df = irb_df.filter(pl.col(ec_col) == ec)
        ctx = ReportingContext(substitution_inflow=inflow_map.get(ec, 0.0))
        frame = execute(spec, class_df, ctx)
        frame = _null_empty_rows(frame, class_df, row_preds)
        frame = _provisions_postfix(frame, class_df, row_preds, data_cols, ref="0290")
        result[ec] = _negate(frame)
    return result


# =============================================================================
# C 08.02
# =============================================================================


@cites("PS1/26, paragraph 1.3")
def generate_c08_02(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, pl.DataFrame]:
    """Execute C 08.02 per class sheet with data-driven grade/PD-band rows."""
    ec_col = pick(cols, "exposure_class")
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

    column_refs = tuple(col.ref for col in get_c08_02_columns(framework))
    value_refs = tuple(ref for ref in column_refs if ref != "0005")

    result: dict[str, pl.DataFrame] = {}
    for ec in irb_df[ec_col].unique().sort().to_list():
        class_df = irb_df.filter(pl.col(ec_col) == ec)
        labels, keyed = _c08_02_keyed(class_df, pd_col, grade_col)
        if not labels:
            result[ec] = _empty_frame(column_refs, string_refs=("0005",))
            continue
        rows = tuple(_Row(label, label) for label in labels)
        cells: dict[tuple[str, str], CellSpec] = {}
        row_preds: dict[str, RowPredicate | None] = {}
        for label in labels:
            terms: _Terms = (("c08_02_key", label),)
            row_preds[label] = RowPredicate(equals=terms)
            for col_ref, cell in _value_cells(
                terms, data_cols, ead_col, rwa_col, value_refs, is_total=False
            ).items():
                cells[(label, col_ref)] = cell
        spec = TemplateSpec(
            name="c08_02", rows=rows, column_refs=value_refs, cells=cells, empty_cell="zero"
        )
        frame = execute(spec, keyed)
        frame = _provisions_postfix(frame, keyed, row_preds, data_cols, ref="0290")
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


@cites("PS1/26, paragraph 1.3")
def generate_c08_03(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, pl.DataFrame]:
    """Execute C 08.03 per class sheet over sparse PD-range rows."""
    ec_col = pick(cols, "exposure_class")
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

    result: dict[str, pl.DataFrame] = {}
    for ec in irb_df[ec_col].unique().sort().to_list():
        class_df = irb_df.filter(pl.col(ec_col) == ec)
        band_rows, banded = _banded_rows(class_df, alloc_pd_col)
        if not band_rows:
            result[ec] = _empty_frame(column_refs)
            continue
        cells: dict[tuple[str, str], CellSpec] = {}
        row_preds: dict[str, RowPredicate | None] = {}
        for ref, label in band_rows:
            terms: _Terms = (("c08_pd_range", label),)
            member = RowPredicate(equals=terms)
            row_preds[ref] = member
            cells[(ref, "0010")] = CellSpec(
                SafeSum(("drawn_amount", "interest")),
                predicate=RowPredicate(equals=(*terms, ("c08_bs", "on"))),
            )
            cells[(ref, "0020")] = CellSpec(
                Sum("nominal_amount"),
                predicate=RowPredicate(equals=(*terms, ("c08_bs", "off"))),
            )
            cells[(ref, "0030")] = CellSpec(
                WeightedAvg("ccf", weight="nominal_amount"), predicate=member, empty_cell="null"
            )
            cells[(ref, "0040")] = CellSpec(Sum(ead_col), predicate=member)
            cells[(ref, "0050")] = CellSpec(
                WeightedAvg(report_pd_col or alloc_pd_col, weight=ead_col),
                predicate=member,
                empty_cell="null",
            )
            cells[(ref, "0060")] = (
                CellSpec(Count("counterparty_reference", distinct=True), predicate=member)
                if "counterparty_reference" in data_cols
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
        rows = tuple(_Row(ref, label) for ref, label in band_rows)
        spec = TemplateSpec(
            name="c08_03", rows=rows, column_refs=column_refs, cells=cells, empty_cell="zero"
        )
        frame = execute(spec, banded)
        frame = _c08_03_bs_fallback(frame, banded, band_rows, data_cols)
        frame = _provisions_postfix(frame, banded, row_preds, data_cols, ref="0110")
        result[ec] = frame
    return result


def _c08_03_bs_fallback(
    frame: pl.DataFrame,
    banded: pl.DataFrame,
    band_rows: list[tuple[str, str]],
    cols: set[str],
) -> pl.DataFrame:
    """The retired whole-bucket fallback: when a bucket's on-BS (off-BS)
    split is empty, columns 0010 (0020) sum the WHOLE bucket instead."""
    on_available = "c08_bs" in banded.columns
    fixes_0010: dict[str, float | None] = {}
    fixes_0020: dict[str, float | None] = {}
    for ref, label in band_rows:
        bucket = banded.filter(pl.col("c08_pd_range") == label)
        on_empty = len(bucket.filter(pl.col("c08_bs") == "on")) == 0 if on_available else True
        off_empty = len(bucket.filter(pl.col("c08_bs") == "off")) == 0 if on_available else True
        if on_empty:
            total = 0.0
            found = False
            for source in ("drawn_amount", "interest"):
                if source in cols:
                    total += float(bucket[source].fill_null(0.0).sum())
                    found = True
            fixes_0010[ref] = total if found else 0.0
        if off_empty:
            fixes_0020[ref] = (
                float(bucket["nominal_amount"].fill_null(0.0).sum())
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


@cites("PS1/26, paragraph 1.3")
def generate_c08_05(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, pl.DataFrame]:
    """Execute C 08.05 per class sheet (PD back-testing over sparse ranges)."""
    ec_col = pick(cols, "exposure_class")
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
    irb_df = _c08_05_prepare(_prepare(irb_df, data_cols), data_cols, report_pd_col or alloc_pd_col)
    column_refs = tuple(col.ref for col in get_c08_05_columns(framework))
    prior_present = "prior_year_obligor_count" in data_cols
    hist_present = "historical_annual_default_rate" in data_cols

    result: dict[str, pl.DataFrame] = {}
    for ec in irb_df[ec_col].unique().sort().to_list():
        class_df = irb_df.filter(pl.col(ec_col) == ec)
        band_rows, banded = _banded_rows(class_df, alloc_pd_col)
        if not band_rows:
            result[ec] = _empty_frame(column_refs)
            continue
        cells: dict[tuple[str, str], CellSpec] = {}
        for ref, label in band_rows:
            terms: _Terms = (("c08_pd_range", label),)
            member = RowPredicate(equals=terms)
            cells[(ref, "0010")] = CellSpec(
                WeightedAvg(report_pd_col or alloc_pd_col, weight="c08_one"),
                predicate=member,
                empty_cell="null",
            )
            if prior_present:
                cells[(ref, "0020")] = CellSpec(Sum("prior_year_obligor_count"), predicate=member)
            elif "counterparty_reference" in data_cols:
                cells[(ref, "0020")] = CellSpec(
                    Count("counterparty_reference", distinct=True), predicate=member
                )
            else:
                cells[(ref, "0020")] = CellSpec(Count("exposure_reference"), predicate=member)
            if "counterparty_reference" in data_cols:
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
                    WeightedAvg("historical_annual_default_rate", weight="c08_one"),
                    predicate=member,
                )
            else:
                cells[(ref, "0050")] = CellSpec(Formula(refs=("0040",), fn=_copy_of_0040))
        rows = tuple(_Row(ref, label) for ref, label in band_rows)
        spec = TemplateSpec(
            name="c08_05", rows=rows, column_refs=column_refs, cells=cells, empty_cell="zero"
        )
        frame = execute(spec, banded)
        if prior_present:
            frame = _c08_05_rate_postfix(frame, banded, band_rows, data_cols)
        result[ec] = frame
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


def _c08_05_rate_postfix(
    frame: pl.DataFrame,
    banded: pl.DataFrame,
    band_rows: list[tuple[str, str]],
    cols: set[str],
) -> pl.DataFrame:
    """When a prior-year carrier is supplied, col 0040 still divides by the
    CURRENT obligor count (not the prior sum in col 0020) — recompute."""
    cp_present = "counterparty_reference" in cols
    fixes: dict[str, float] = {}
    for ref, label in band_rows:
        bucket = banded.filter(pl.col("c08_pd_range") == label)
        obligors = (
            float(bucket["counterparty_reference"].n_unique()) if cp_present else float(len(bucket))
        )
        defaulted = bucket.filter(pl.col("c08_05_defaulted"))
        defaults = (
            float(defaulted["counterparty_reference"].n_unique())
            if cp_present
            else float(len(defaulted))
        )
        fixes[ref] = defaults / obligors if obligors > 0 else 0.0
    expr: pl.Expr = pl.col("0040")
    for ref, value in fixes.items():
        expr = pl.when(pl.col("row_ref") == ref).then(pl.lit(value)).otherwise(expr)
    return frame.with_columns(expr.alias("0040"))


# =============================================================================
# C 08.04 — the flow clone
# =============================================================================


@cites("PS1/26, paragraph 1.3")
def generate_c08_04(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, pl.DataFrame]:
    """Execute C 08.04 per class sheet (only the closing-RWEA row 0090)."""
    ec_col = pick(cols, "exposure_class")
    if ec_col is None:
        errors.append("C08.04: Missing required column (exposure_class)")
        return {}
    irb_df = _non_slotting(results, cols).collect()
    if len(irb_df) == 0:
        return {}
    data_cols = set(irb_df.columns)
    # Deliberately two-wide (no rwa_post_factor) — the retired ladder.
    rwa_col = pick(data_cols, "rwa_final", "rwa")
    column_refs = tuple(col.ref for col in get_c08_04_columns(framework))
    rows = tuple(C08_04_ROWS)
    cells: dict[tuple[str, str], CellSpec] = {}
    if rwa_col is not None:
        cells[("0090", "0010")] = CellSpec(Sum(rwa_col))
    spec = TemplateSpec(
        name="c08_04", rows=rows, column_refs=column_refs, cells=cells, empty_cell="null"
    )
    result: dict[str, pl.DataFrame] = {}
    for ec in irb_df[ec_col].unique().sort().to_list():
        class_df = irb_df.filter(pl.col(ec_col) == ec)
        result[ec] = execute(spec, class_df)
    return result


# =============================================================================
# C 08.06 / OF 08.06 — specialised lending slotting (per SL-type sheets)
# =============================================================================


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
    rows, even when empty) compute on data with per-cell null policy.
    """
    ead_col = pick(cols, "ead_final")
    rwa_col = pick(cols, "rwa_final", "rwa_post_factor", "rwa")
    if ead_col is None or rwa_col is None:
        errors.append("C08.06: Missing required columns (ead/rwa)")
        return {}
    if pick(cols, "approach_applied", "approach") is None:
        errors.append("C08.06: No approach column — cannot identify slotting exposures")
        return {}
    # The retired dispatch pre-filtered the IRB book on ``approach_applied``
    # only — an ``approach``-only frame silently yields nothing.
    if "approach_applied" not in cols:
        return {}
    slotting_df = results.filter(pl.col("approach_applied") == "slotting").collect()
    if slotting_df.height == 0:
        return {}
    if "slotting_category" not in cols:
        errors.append("C08.06: Missing slotting_category column — cannot generate template")
        return {}
    data = _c08_06_prepare(slotting_df, cols)
    spec, row_defs, row_preds = _c08_06_spec(cols, ead_col, rwa_col, framework)
    result: dict[str, pl.DataFrame] = {}
    if "sl_type" in cols:
        for sl_key in get_c08_06_sl_types(framework):
            type_df = _c08_06_sl_type_sheet(data, sl_key, cols, framework)
            if type_df.height == 0:
                continue
            result[sl_key] = _c08_06_sheet(spec, type_df, row_defs, row_preds, cols, ead_col)
    else:
        result["specialised_lending"] = _c08_06_sheet(
            spec, data, row_defs, row_preds, cols, ead_col
        )
    return result


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
    cols: set[str], ead_col: str, rwa_col: str, framework: str
) -> tuple[
    TemplateSpec,
    list[tuple[str, str, bool | None, str]],
    dict[str, RowPredicate],
]:
    """The C 08.06 spec (framework-shaped, sheet-independent)."""
    column_refs = tuple(col.ref for col in get_c08_06_columns(framework))
    row_defs = [
        row_def
        for row_def in get_c08_06_rows(framework)
        if row_def[1] == "Total" or row_def[1] in C08_06_CATEGORY_MAP
    ]
    has_maturity = "is_short_maturity" in cols
    rows = tuple(_Row(row_def[0], row_def[1]) for row_def in row_defs)
    row_preds = {
        row_def[0]: _c08_06_row_pred(row_def[1], row_def[2], has_maturity=has_maturity)
        for row_def in row_defs
    }
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
            SafeSum(("drawn_amount", "interest", "nominal_amount", "undrawn_amount")),
            predicate=pred,
        )
        cells[(ref, "0020")] = (
            CellSpec(Sum(crm_col), predicate=pred)
            if crm_col is not None
            else CellSpec(Formula(refs=("0010",), fn=_copy_of_0010))
        )
        cells[(ref, "0030")] = CellSpec(
            SafeSum(("nominal_amount", "undrawn_amount")), predicate=off_pred
        )
        if "0031" in column_refs:
            cells[(ref, "0031")] = CellSpec(Formula(refs=(), fn=_const(None)))
        cells[(ref, "0040")] = CellSpec(Sum(ead_col), predicate=pred)
        cells[(ref, "0050")] = CellSpec(Sum(ead_col), predicate=off_pred, empty_cell="null")
        cells[(ref, "0060")] = CellSpec(Formula(refs=(), fn=_const(None)))
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
    spec = TemplateSpec(
        name="c08_06", rows=rows, column_refs=column_refs, cells=cells, empty_cell="zero"
    )
    return spec, row_defs, row_preds


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
    for row_ref, label, _is_short, rw_display in row_defs:
        subset = row_preds[row_ref].apply(type_df)
        if subset.height == 0 and label != "Total":
            overrides[row_ref] = _c08_06_zero_row(spec.column_refs, rw_display)
            continue
        fixes: dict[str, float | None] = {}
        if subset.filter(pl.col("c0806_off_bs")).height == 0:
            fixes["0030"] = col_sum(subset, cols, "nominal_amount")
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
    formulas guarding a zero denominator to 0.0. Rows with no exposure
    class binding (and no aggregate rule) render ALL-NULL; empty real-class
    rows stay 0.0 — the opposite split from C 07.00. The B31 materiality
    columns 0160-0180 are structurally null regardless of reporting basis
    (the retired ``output_floor_config`` gate was dead code).
    """
    ead_col = pick(cols, "ead_final")
    approach_col = pick(cols, "approach_applied", "approach")
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
    rwa_col = pick(cols, "rwa_final", "rwa_post_factor", "rwa")
    row_defs = get_c08_07_rows(framework)
    spec, null_rows = _c08_07_spec(row_defs, ec_col, ead_col, rwa_col, framework)
    frame = execute(spec, data)
    return _null_fixed_rows(frame, null_rows)


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
        cells[(row_ref, "0010")] = CellSpec(Sum(ead_col), predicate=irb_pred)
        cells[(row_ref, "0020")] = CellSpec(Sum(ead_col), predicate=total_pred)
        cells[(row_ref, "0030")] = CellSpec(Formula(refs=("0010", "0020"), fn=_pct_sa))
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


def _pct_sa(cells: Mapping[str, float | None], _prior: bool) -> float | None:
    """0030 = SA share of the row's EAD, % (0.0 on a zero denominator)."""
    total = cells["0020"] or 0.0
    if total <= 0:
        return 0.0
    return (total - (cells["0010"] or 0.0)) / total * 100.0


def _pct_irb(cells: Mapping[str, float | None], _prior: bool) -> float | None:
    """0050 = IRB share of the row's EAD, % (0.0 on a zero denominator)."""
    total = cells["0020"] or 0.0
    if total <= 0:
        return 0.0
    return (cells["0010"] or 0.0) / total * 100.0


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
    approach_col = pick(cols, "approach_applied", "approach")
    if approach_col is not None:
        return irb.filter(pl.col(approach_col) != "slotting")
    return irb


def _null_empty_rows(
    frame: pl.DataFrame, class_df: pl.DataFrame, row_preds: dict[str, RowPredicate | None]
) -> pl.DataFrame:
    """Render inert rows and rows with EMPTY subsets all-null."""
    null_refs = [
        ref
        for ref, pred in row_preds.items()
        if pred is None or ((pred.equals or pred.any_of) and pred.apply(class_df).height == 0)
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
    """The retired provisions ladder: when the SCRA/GCRA sum nets to ~0 AND
    a ``provision_held`` column exists, the cell reports the held sum
    instead (a value-dependent branch — applied per row subset)."""
    if ref not in frame.columns or "provision_held" not in cols:
        return frame
    fixes: dict[str, float] = {}
    for row_ref, pred in row_preds.items():
        if pred is None:
            continue
        current = frame.filter(pl.col("row_ref") == row_ref)
        if current.height == 0 or current[ref][0] is None:
            continue
        if abs(current[ref][0]) >= 1e-9:
            continue
        subset = pred.apply(class_df)
        if subset.height == 0:
            continue
        fixes[row_ref] = float(subset["provision_held"].fill_null(0.0).sum())
    if not fixes:
        return frame
    expr: pl.Expr = pl.col(ref)
    for row_ref, value in fixes.items():
        expr = pl.when(pl.col("row_ref") == row_ref).then(pl.lit(value)).otherwise(expr)
    return frame.with_columns(expr.alias(ref))


def _negate(frame: pl.DataFrame) -> pl.DataFrame:
    """Annex II §1.3: only column 0290 is emitted negative on the C 08
    surface (-0.0 normalised; null stays null)."""
    targets = [col for col in frame.columns if col in _NEGATIVE_COLS]
    if not targets:
        return frame
    return frame.with_columns(((-pl.col(col)) + pl.lit(0.0)).alias(col) for col in targets)


def _empty_frame(column_refs: tuple[str, ...], string_refs: tuple[str, ...] = ()) -> pl.DataFrame:
    schema: dict[str, pl.DataType | type[pl.DataType]] = {
        "row_ref": pl.String,
        "row_name": pl.String,
    }
    for ref in column_refs:
        schema[ref] = pl.String if ref in string_refs else pl.Float64
    return pl.DataFrame(schema=schema)
