"""
COREP C 09.01 / C 09.02 — geographical breakdown of exposures, declarative.

Pipeline position:
    sealed aggregator-exit ledger -> per-template population + derived
    discriminators -> ONE TemplateSpec per framework -> cellspec.execute()
    per country sheet -> dict["TOTAL" | ISO code, DataFrame]

Cell semantics (recorded decisions, this slice):

- C 09.01's PRIMARY columns key the APPLIED Art. 112 class
  (``reporting_class_origin`` — recorded fix 2026-07-12: the Annex II
  instructions define them "same as the CR SA template", so a defaulted
  SA exposure moves to row 0100 exactly as C 07.00 assigns it), while the
  0020 "Defaulted exposures" MEMORANDUM keys the raw ORIGINAL class (the
  instruction's counterfactual "would have been" row) — a two-basis
  template like Pillar 3 CR4. C 09.02 keys the sealed
  ``reporting_class_origin`` (== raw ``exposure_class`` for the IRB
  book — number-neutral convergence; the IRB template has no default
  row by design) over the ``reporting_approach_origin`` population.
  Under B31 the RE-split mortgage classes match no class row and
  surface ONLY in the Total row.
- C 09.01 shares C 07.00's population (``c07_population`` — the SA book
  plus BOTH counterparty-credit-risk populations: FCCM SFT synthetic rows
  and SA-CCR derivative netting sets, admitted by ``risk_type``). That
  shared population is why the Basel 3.1 institution row is now populated:
  the derivative netting sets used to be dropped by the
  ``standardised_ccr`` output-floor relabel and never reached either
  template. C 09.02 is the IRB book INCLUDING slotting (the retired inline
  comment claiming exclusion was misleading).
- The retired reverse-map row keying is preserved: a row whose key is not
  a ``C09_01_SA_CLASS_MAP`` value renders ALL-NULL (the SME / short-term /
  CIU / real-estate sub-rows are permanently null — recorded dead code,
  never "fixed"); the corporate rows fan in corporate + corporate_sme +
  specialised_lending; retail fans in retail_other (+ retail_qrre /
  retail_mortgage per template).
- Empty class rows render ALL-NULL (the dominant null path); the Total
  rows (0170 / 0150) compute over the WHOLE country frame — never nulled,
  and they aggregate exposures no class row displays.
- C 09.02's PD/LGD averages weight by ``ead_final`` (NOT the default
  ``reporting_ead``), report RAW ratios (no x100 despite the "(%)"
  labels), read ``lgd_post_crm`` only, and preserve the retired
  UNWEIGHTED-mean fallback when the subset carries zero total EAD (a
  module post-step — the WeightedAvg verb has no such fallback).
- Column ladders are the retired ones, narrower than C 07/C 08: gross =
  pick(ead_gross, nominal_amount, drawn_amount) (a single column, never a
  SafeSum); RWEA = pick(rwa_final, rwa) (NO rwa_post_factor); the CRR
  "pre supporting factors" RWEA equals the post-factor value (0080==0090,
  0110==0125 — no adjustment is computed; the SF adjustment columns are
  structurally null).
- No Annex II "(-)" negation and no provision_held fallback ladder on
  either template; provisions are the (unsealed) SCRA/GCRA carriers.

References:
- Regulation (EU) 2021/451, Annex I/II (C 09.01 / C 09.02)
- PRA PS1/26 Annex I/II (OF 09.01 / OF 09.02); CRR Art. 112 / Art. 147
- docs/plans/phase7-declarative-reporting.md §3.2/§6 (S8)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import polars as pl
from watchfire import cites

from rwa_calc.reporting.cellspec import (
    CellSpec,
    Formula,
    RowPredicate,
    Sum,
    TemplateSpec,
    WeightedAvg,
    execute,
    matched_counts,
    subset_rows,
)
from rwa_calc.reporting.corep.c07 import c07_population
from rwa_calc.reporting.corep.templates import (
    C09_01_SA_CLASS_MAP,
    get_c09_01_columns,
    get_c09_01_rows,
    get_c09_02_columns,
    get_c09_02_rows,
)
from rwa_calc.reporting.kernel import pick

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    type _PostStep = Callable[[pl.DataFrame, pl.DataFrame], pl.DataFrame]

    from rwa_calc.reporting.corep.templates import COREPRow

_IRB_APPROACHES: tuple[str, ...] = ("foundation_irb", "advanced_irb", "slotting")

# C 09.02 row keys that map directly to a single exposure_class value.
_C09_02_DIRECT_EC: frozenset[str] = frozenset(
    {
        "central_govt_central_bank",
        "institution",
        "retail_mortgage",
        "retail_qrre",
        "retail_other",
        "equity",
    }
)

# C 09.02 row keys that always report empty (flags not yet in the pipeline).
_C09_02_EMPTY_KEYS: frozenset[str] = frozenset(
    {"corporate_purchased_receivables", "retail_purchased_receivables"}
)

# The four B31 retail-RE rows: (property_type values, is the SME split).
_C09_02_RE_ROWS: dict[str, tuple[tuple[str, ...], bool]] = {
    "retail_resi_re_sme": (("residential", "rre"), True),
    "retail_resi_re_non_sme": (("residential", "rre"), False),
    "retail_comm_re_sme": (("commercial", "cre"), True),
    "retail_comm_re_non_sme": (("commercial", "cre"), False),
}

_CORPORATE_FAMILY: tuple[str, ...] = ("corporate", "corporate_sme")


class _Row:
    """Minimal TemplateRow for the geo templates."""

    __slots__ = ("name", "ref")

    def __init__(self, ref: str, name: str) -> None:
        self.ref = ref
        self.name = name


def _const(value: float | None):  # noqa: ANN202 - tiny Formula factory
    def fn(_cells: Mapping[str, float | None], _prior: bool) -> float | None:
        return value

    return fn


# =============================================================================
# C 09.01 / OF 09.01 — geographical breakdown, SA
# =============================================================================


@cites("PS1/26, paragraph 1.3")
def generate_c09_01(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, pl.DataFrame]:
    """Execute C 09.01 / OF 09.01 per country over the C 07.00 population."""
    if pick(cols, "exposure_class") is None:
        errors.append("C09.01: Missing required column (exposure_class)")
        return {}
    if pick(cols, "cp_country_code") is None:
        errors.append(
            "C09.01: Missing cp_country_code column — cannot produce geographical breakdown"
        )
        return {}
    sa_df = c07_population(results, cols).collect()
    if sa_df.height == 0:
        return {}
    data = sa_df.with_columns(_defaulted_expr(cols).alias("c09_defaulted"))
    spec, row_preds = _c09_01_spec(set(data.columns), framework)
    return _per_country_sheets(data, spec, row_preds, post=None)


def _c09_01_row_pred(row_def: COREPRow, basis_col: str) -> RowPredicate | None:
    """The reverse-map keying over ``basis_col``: rows whose key is not a
    class-map VALUE are permanently null (the map short-circuits before
    the SME / RE / SL / CIU sub-filters ever run — recorded dead code).

    Recorded fix (2026-07-12, Annex II C 09.1 instructions): the PRIMARY
    columns key the APPLIED Art. 112 class (``reporting_class_origin`` —
    "same definition as the CR SA template" columns, so a defaulted SA
    exposure moves to row 0100 exactly as in C 07.00), while the 0020
    "Defaulted exposures" MEMORANDUM keys the raw ORIGINAL class ("where
    the obligors would have been reported if those exposures were not
    assigned to 'exposures in default'")."""
    if row_def.ref == "0170":
        return RowPredicate()
    key = row_def.exposure_class_value
    if key is None:
        return None
    classes = sorted(ec for ec, mapped in C09_01_SA_CLASS_MAP.items() if mapped == key)
    if not classes:
        return None
    return _class_union(*classes, col=basis_col)


def _c09_01_spec(
    cols: set[str], framework: str
) -> tuple[TemplateSpec, dict[str, RowPredicate | None]]:
    column_refs = tuple(col.ref for col in get_c09_01_columns(framework))
    row_defs = get_c09_01_rows(framework)
    ead_gross_col = pick(cols, "ead_gross", "nominal_amount", "drawn_amount")
    ead_col = pick(cols, "ead_final")
    rwa_col = pick(cols, "rwa_final", "rwa")
    rows = tuple(_Row(row_def.ref, row_def.name) for row_def in row_defs)
    row_preds: dict[str, RowPredicate | None] = {}
    cells: dict[tuple[str, str], CellSpec] = {}
    for row_def in row_defs:
        # Primary columns: the APPLIED Art. 112 class (the sealed obligor
        # applied ladder — defaulted exposures sit in row 0100, as C 07.00).
        pred = _c09_01_row_pred(row_def, "reporting_class_origin")
        # 0020 memo: the raw ORIGINAL class + defaulted (the counterfactual
        # "would have been" row of the instruction).
        memo_pred = _c09_01_row_pred(row_def, "exposure_class")
        row_preds[row_def.ref] = _either_pred(pred, memo_pred)
        if pred is None:
            continue
        ref = row_def.ref
        cells[(ref, "0010")] = _sum_or_null(ead_gross_col, pred)
        if ead_gross_col is not None and memo_pred is not None:
            cells[(ref, "0020")] = CellSpec(
                Sum(ead_gross_col),
                predicate=_conjoin(memo_pred, ("c09_defaulted", True)),
            )
        cells[(ref, "0050")] = CellSpec(Sum("gcra_provision_amount"), predicate=pred)
        cells[(ref, "0055")] = CellSpec(Sum("scra_provision_amount"), predicate=pred)
        for null_ref in ("0040", "0060", "0061", "0070"):
            cells[(ref, null_ref)] = CellSpec(Formula(refs=(), fn=_const(None)))
        cells[(ref, "0075")] = _sum_or_null(ead_col, pred)
        if "0080" in column_refs:
            cells[(ref, "0080")] = _sum_or_null(rwa_col, pred)
            cells[(ref, "0081")] = CellSpec(Formula(refs=(), fn=_const(None)))
            cells[(ref, "0082")] = CellSpec(Formula(refs=(), fn=_const(None)))
        cells[(ref, "0090")] = _sum_or_null(rwa_col, pred)
    spec = TemplateSpec(
        name="c09_01", rows=rows, column_refs=column_refs, cells=cells, empty_cell="zero"
    )
    return spec, row_preds


# =============================================================================
# C 09.02 / OF 09.02 — geographical breakdown, IRB
# =============================================================================


@cites("PS1/26, paragraph 1.3")
def generate_c09_02(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, pl.DataFrame]:
    """Execute C 09.02 / OF 09.02 per country over the IRB book
    (F-IRB / A-IRB / slotting — slotting stays IN the population)."""
    if pick(cols, "exposure_class") is None:
        errors.append("C09.02: Missing required column (exposure_class)")
        return {}
    if pick(cols, "cp_country_code") is None:
        errors.append(
            "C09.02: Missing cp_country_code column — cannot produce geographical breakdown"
        )
        return {}
    irb_df = _irb_population(results, cols).collect()
    if irb_df.height == 0:
        return {}
    approach_col = pick(cols, "reporting_approach_origin", "approach")
    data = _c09_02_prepare(irb_df, cols, approach_col)
    ead_col = pick(cols, "ead_final")
    pd_col = pick(cols, "pd_floored", "pd")
    lgd_col = pick(cols, "lgd_post_crm")
    spec, row_preds = _c09_02_spec(cols, framework, approach_col)

    def post(frame: pl.DataFrame, country_df: pl.DataFrame) -> pl.DataFrame:
        return _c09_02_avg_postfix(
            frame, country_df, row_preds, ead_col=ead_col, pd_col=pd_col, lgd_col=lgd_col
        )

    return _per_country_sheets(data, spec, row_preds, post=post)


def _irb_population(results: pl.LazyFrame, cols: set[str]) -> pl.LazyFrame:
    """The retired _filter_by_irb_approach: keyed to approach_applied only."""
    if "reporting_approach_origin" not in cols:
        return results.filter(pl.lit(value=False))
    return results.filter(pl.col("reporting_approach_origin").is_in(list(_IRB_APPROACHES)))


def _c09_02_prepare(data: pl.DataFrame, cols: set[str], approach_col: str | None) -> pl.DataFrame:
    """Derive the C 09.02 discriminators. Null semantics are load-bearing:
    the retired ``!= True`` filters DROP null-flag rows (no fill), while
    the non-SME anti-join KEEPS rows with no SME indicator (fill to
    False before negating)."""
    exprs: list[pl.Expr] = [_defaulted_expr(cols).alias("c09_defaulted")]
    if "sme_supporting_factor_eligible" in cols:
        sme = (pl.col("sme_supporting_factor_eligible") == True).fill_null(value=False)  # noqa: E712
    else:
        sme = pl.col("exposure_class").str.contains("sme").fill_null(value=False)
    exprs.append(sme.alias("c09_sme"))
    # The retired _filter_non_sme is an exposure_reference anti-join; with no
    # reference column it returns the base UNCHANGED (SME rows included).
    non_sme = sme.not_() if "exposure_reference" in cols else pl.lit(value=True)
    exprs.append(non_sme.alias("c09_non_sme"))
    if "sme_supporting_factor_eligible" in cols:
        corp_non_sme = pl.col("sme_supporting_factor_eligible") != True  # noqa: E712
    else:
        corp_non_sme = pl.col("exposure_class").str.contains("sme").not_()
    if "cp_apply_fi_scalar" in cols:
        corp_non_sme = corp_non_sme & (pl.col("cp_apply_fi_scalar") != True)  # noqa: E712
    exprs.append(corp_non_sme.alias("c09_corp_non_sme"))
    if approach_col is not None:
        exprs.append((pl.col(approach_col) == "slotting").alias("c09_slotting"))
    return data.with_columns(exprs)


def _c09_02_row_pred(  # noqa: PLR0911 - the retired branch cascade, one return per row family
    row_def: COREPRow, cols: set[str], approach_col: str | None
) -> RowPredicate | None:
    """The retired _filter_c09_02_row branch cascade as predicates."""
    if row_def.ref == "0150":
        return RowPredicate()
    key = row_def.exposure_class_value
    if key is None or key in _C09_02_EMPTY_KEYS:
        return None
    if key in _C09_02_DIRECT_EC:
        return RowPredicate(equals=(("reporting_class_origin", key),))
    if key == "corporate":
        return _class_union(*_CORPORATE_FAMILY, "specialised_lending")
    if key == "sl_excl_slotting":
        terms: tuple[tuple[str, str | bool], ...] = (
            ("reporting_class_origin", "specialised_lending"),
        )
        if approach_col is not None:
            terms = (*terms, ("c09_slotting", False))
        return RowPredicate(equals=terms)
    if key == "sl_slotting":
        if approach_col is None:
            return None
        return RowPredicate(
            equals=(("reporting_class_origin", "specialised_lending"), ("c09_slotting", True))
        )
    if key == "corporate_sme":
        return _conjoin(_class_union(*_CORPORATE_FAMILY), ("c09_sme", True))
    if key == "corporate_fse_large":
        return _conjoin(_class_union(*_CORPORATE_FAMILY), ("cp_apply_fi_scalar", True))
    if key == "corporate_non_sme":
        return _conjoin(_class_union(*_CORPORATE_FAMILY), ("c09_corp_non_sme", True))
    if key == "retail":
        return _class_union("retail_mortgage", "retail_qrre", "retail_other")
    if key in ("retail_mortgage_sme", "retail_mortgage_non_sme"):
        flag = "c09_sme" if key == "retail_mortgage_sme" else "c09_non_sme"
        return RowPredicate(equals=(("reporting_class_origin", "retail_mortgage"), (flag, True)))
    if key in ("retail_other_sme", "retail_other_non_sme"):
        flag = "c09_sme" if key == "retail_other_sme" else "c09_non_sme"
        return RowPredicate(equals=(("reporting_class_origin", "retail_other"), (flag, True)))
    if key in _C09_02_RE_ROWS:
        ptypes, is_sme = _C09_02_RE_ROWS[key]
        terms = (
            ("reporting_class_origin", "retail_mortgage"),
            ("c09_sme" if is_sme else "c09_non_sme", True),
        )
        # The retired code skips the property filter when the column is
        # absent (the whole mortgage base stays in) — generate-time variant.
        if "property_type" in cols:
            limbs = tuple(RowPredicate(equals=(("property_type", ptype),)) for ptype in ptypes)
            return RowPredicate(equals=terms, any_of=limbs)
        return RowPredicate(equals=terms)
    return None


def _c09_02_spec(
    cols: set[str], framework: str, approach_col: str | None
) -> tuple[TemplateSpec, dict[str, RowPredicate | None]]:
    column_refs = tuple(col.ref for col in get_c09_02_columns(framework))
    row_defs = get_c09_02_rows(framework)
    ead_gross_col = pick(cols, "ead_gross", "nominal_amount", "drawn_amount")
    ead_col = pick(cols, "ead_final")
    rwa_col = pick(cols, "rwa_final", "rwa")  # deliberately two-wide
    pd_col = pick(cols, "pd_floored", "pd")
    lgd_col = pick(cols, "lgd_post_crm")
    rows = tuple(_Row(row_def.ref, row_def.name) for row_def in row_defs)
    row_preds: dict[str, RowPredicate | None] = {}
    cells: dict[tuple[str, str], CellSpec] = {}
    for row_def in row_defs:
        pred = _c09_02_row_pred(row_def, cols, approach_col)
        row_preds[row_def.ref] = pred
        if pred is None:
            continue
        ref = row_def.ref
        def_pred = _conjoin(pred, ("c09_defaulted", True))
        cells[(ref, "0010")] = _sum_or_null(ead_gross_col, pred)
        if ead_gross_col is not None:
            cells[(ref, "0030")] = CellSpec(Sum(ead_gross_col), predicate=def_pred)
        for null_ref in ("0040", "0060", "0070"):
            cells[(ref, null_ref)] = CellSpec(Formula(refs=(), fn=_const(None)))
        cells[(ref, "0050")] = CellSpec(Sum("gcra_provision_amount"), predicate=pred)
        cells[(ref, "0055")] = CellSpec(Sum("scra_provision_amount"), predicate=pred)
        cells[(ref, "0080")] = _wavg_or_null(pd_col, ead_col, pred)
        cells[(ref, "0090")] = _wavg_or_null(lgd_col, ead_col, pred)
        cells[(ref, "0100")] = _wavg_or_null(lgd_col, ead_col, def_pred)
        cells[(ref, "0105")] = _sum_or_null(ead_col, pred)
        if "0107" in column_refs and ead_col is not None:
            cells[(ref, "0107")] = CellSpec(Sum(ead_col), predicate=def_pred)
        if "0110" in column_refs:
            cells[(ref, "0110")] = _sum_or_null(rwa_col, pred)
        if rwa_col is not None:
            cells[(ref, "0120")] = CellSpec(Sum(rwa_col), predicate=def_pred)
        if "0121" in column_refs:
            cells[(ref, "0121")] = CellSpec(Formula(refs=(), fn=_const(None)))
            cells[(ref, "0122")] = CellSpec(Formula(refs=(), fn=_const(None)))
        cells[(ref, "0125")] = _sum_or_null(rwa_col, pred)
        cells[(ref, "0130")] = CellSpec(Sum("expected_loss"), predicate=pred)
    spec = TemplateSpec(
        name="c09_02", rows=rows, column_refs=column_refs, cells=cells, empty_cell="zero"
    )
    return spec, row_preds


def _c09_02_avg_postfix(
    frame: pl.DataFrame,
    country_df: pl.DataFrame,
    row_preds: Mapping[str, RowPredicate | None],
    *,
    ead_col: str | None,
    pd_col: str | None,
    lgd_col: str | None,
) -> pl.DataFrame:
    """The retired _weighted_avg_or_mean fallback: an UNWEIGHTED mean of
    non-null values when the subset's total EAD weight is <= 0 (the
    WeightedAvg verb has no such fallback — value-dependent post-step)."""
    if pd_col is None and lgd_col is None:
        return frame
    overrides: dict[str, dict[str, float | None]] = {}
    live_preds = {ref: pred for ref, pred in row_preds.items() if pred is not None}
    row_subsets = subset_rows(country_df, live_preds)
    for ref, subset in row_subsets.items():
        if subset.height == 0:
            continue
        fixes: dict[str, float | None] = {}
        ead_sum = float(subset[ead_col].fill_null(0.0).sum()) if ead_col else 0.0
        if ead_col is None or ead_sum <= 0.0:
            if pd_col is not None:
                fixes["0080"] = _mean_or_none(subset[pd_col])
            if lgd_col is not None:
                fixes["0090"] = _mean_or_none(subset[lgd_col])
        if lgd_col is not None:
            defaulted = subset.filter(pl.col("c09_defaulted"))
            if defaulted.height > 0:
                def_sum = float(defaulted[ead_col].fill_null(0.0).sum()) if ead_col else 0.0
                if ead_col is None or def_sum <= 0.0:
                    fixes["0100"] = _mean_or_none(defaulted[lgd_col])
        if fixes:
            overrides[ref] = {k: v for k, v in fixes.items() if k in frame.columns}
    return _apply_overrides(frame, overrides)


# =============================================================================
# Shared helpers (population split, predicates, post-steps)
# =============================================================================


def _per_country_sheets(
    data: pl.DataFrame,
    spec: TemplateSpec,
    row_preds: dict[str, RowPredicate | None],
    *,
    post: _PostStep | None,
) -> dict[str, pl.DataFrame]:
    """TOTAL first (the whole population, null-country rows included),
    then one sheet per sorted distinct non-null cp_country_code."""
    result: dict[str, pl.DataFrame] = {}
    result["TOTAL"] = _one_sheet(data, spec, row_preds, post)
    countries = (
        data.select(pl.col("cp_country_code"))
        .filter(pl.col("cp_country_code").is_not_null())
        .unique()
        .sort("cp_country_code")
        .to_series()
        .to_list()
    )
    for country in countries:
        country_df = data.filter(pl.col("cp_country_code") == country)
        result[country] = _one_sheet(country_df, spec, row_preds, post)
    return result


def _one_sheet(
    country_df: pl.DataFrame,
    spec: TemplateSpec,
    row_preds: dict[str, RowPredicate | None],
    post: _PostStep | None,
) -> pl.DataFrame:
    frame = execute(spec, country_df)
    frame = _null_empty_rows(frame, country_df, row_preds)
    if post is not None:
        frame = post(frame, country_df)
    return frame


def _class_union(*classes: str, col: str = "reporting_class_origin") -> RowPredicate:
    if len(classes) == 1:
        return RowPredicate(equals=((col, classes[0]),))
    return RowPredicate(any_of=tuple(RowPredicate(equals=((col, ec),)) for ec in classes))


def _either_pred(primary: RowPredicate | None, memo: RowPredicate | None) -> RowPredicate | None:
    """The row-emptiness basis for C 09.01: a row is null only when BOTH
    its primary (applied-class) and memo (original-class) subsets are
    empty — a class row whose only exposures defaulted keeps its 0020
    memo while the primary columns move to row 0100."""
    if primary is None:
        return memo
    if memo is None:
        return primary
    limbs: list[RowPredicate] = []
    for pred in (primary, memo):
        if pred.any_of:
            limbs.extend(pred.any_of)
        elif pred.equals:
            limbs.append(RowPredicate(equals=pred.equals))
    if not limbs:
        return RowPredicate()
    return RowPredicate(any_of=tuple(limbs))


def _conjoin(pred: RowPredicate, term: tuple[str, str | bool]) -> RowPredicate:
    return RowPredicate(equals=(*pred.equals, term), any_of=pred.any_of)


def _sum_or_null(col: str | None, pred: RowPredicate) -> CellSpec:
    if col is None:
        return CellSpec(Formula(refs=(), fn=_const(None)))
    return CellSpec(Sum(col), predicate=pred)


def _wavg_or_null(col: str | None, weight: str | None, pred: RowPredicate) -> CellSpec:
    if col is None or weight is None:
        return CellSpec(Formula(refs=(), fn=_const(None)))
    return CellSpec(WeightedAvg(col, weight=weight), predicate=pred, empty_cell="null")


def _defaulted_expr(cols: set[str]) -> pl.Expr:
    """The retired _filter_defaulted ladder as a Boolean expression."""
    if "is_defaulted" in cols:
        return pl.col("is_defaulted").fill_null(value=False)
    if "default_status" in cols:
        return pl.col("default_status") == True  # noqa: E712
    class_col = "exposure_class_applied" if "exposure_class_applied" in cols else "exposure_class"
    if class_col in cols:
        return pl.col(class_col) == "defaulted"
    if "pd_floored" in cols:
        return pl.col("pd_floored") >= 1.0
    return pl.lit(value=False)


def _null_empty_rows(
    frame: pl.DataFrame,
    country_df: pl.DataFrame,
    row_preds: Mapping[str, RowPredicate | None],
) -> pl.DataFrame:
    """Render dead rows (no predicate) and empty class subsets ALL-NULL —
    the Total row (no equals/any_of terms) is never nulled."""
    constrained = {
        ref: pred
        for ref, pred in row_preds.items()
        if pred is not None and (pred.equals or pred.any_of)
    }
    counts = matched_counts(country_df, constrained)
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


def _apply_overrides(
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


def _mean_or_none(series: pl.Series) -> float | None:
    vals = series.drop_nulls()
    return float(cast("float", vals.mean())) if len(vals) > 0 else None
