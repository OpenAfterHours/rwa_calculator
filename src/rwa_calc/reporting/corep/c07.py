"""
COREP C 07.00 — SA credit risk (per obligor-class sheets), declarative.

Pipeline position:
    sealed aggregator-exit ledger -> _prepare() -> one TemplateSpec per
    framework (built cols-aware) executed per exposure-class sheet
    -> dict[class, DataFrame]

Cell semantics (the recorded F4 decision —
docs/plans/phase7-declarative-reporting.md §6):

- Sheets key the OBLIGOR applied class (the ``exposure_class_applied`` ->
  ``exposure_class`` ladder — identical to the sealed
  ``reporting_class_origin`` on ledger frames; the raw ladder is kept so
  the synthetic COREP unit estate needs no shim). Specialised lending is
  merged into corporate before keying (Art. 112(1)(g): SL is a corporate
  sub-type under SA; the SL "of which" rows split it back via sl_type).
- The population is the standardised book plus BOTH counterparty-credit-risk
  populations (``risk_type in {"CCR_SFT", "CCR_DERIVATIVE"}`` — SA-risk-weighted
  but tagged ``standardised_ccr`` under the output floor, so they are admitted by
  ``risk_type``, never by the approach label; relabelling the approach back would
  break the output floor, which routes on it).
  Annex II is explicit that C 07.00 covers CCR: rows 0070/0080 say "Exposures
  that are subject to counterparty credit risk shall be reported in rows
  0090 - 0130, and therefore shall not be reported in this row", row 0110 is
  "Derivatives and Long Settlement Transactions netting sets" (the ADDITIVE
  PARENT of the QCCP "of which" row 0120; 0100 is the same "of which" for the
  SFT row 0090), and cols 0210/0211 carry the CCR exposure value and its
  Art. 301(1) CCP-cleared exclusion. C 07.00 and C 34 are NOT alternatives —
  C 34 analyses CCR by approach, C 07.00 risk-weights those same exposures
  under SA; a derivative belongs in both, and no roll-up sums the two.
  Row 0130 (contractual cross-product netting sets, Art. 295(c)) is inert
  because it is NOT MODELLED — no input carrier exists for a cross-product
  netting agreement. See ``docs/plans/c07-ccr-derivatives.md``.
- Substitution outflow (col 0090) sums the guaranteed portions migrating
  OUT of each row subset (``guaranteed_portion > 0`` and the pre-CRM class
  differs from the guarantor class — the raw-twin semantics preserved
  verbatim; the two-leg-ledger equivalence is pinned at the aggregator
  layer by ``test_substitution_flows_reconstruct_by_grouping``).
  Substitution inflow (col 0100) is a CROSS-SHEET number — precomputed
  over the whole population per destination class and threaded to the
  total row 0010 via the ``ReportingContext.substitution_inflow`` side
  input (the out-of-frame escape; sub-rows report 0.0).
- The intra-row waterfalls are Formulas over positive magnitudes:
  0040 = 0010 - 0030 (- 0035 under Basel 3.1); 0110 = 0040 - 0050 - 0060
  - 0070 - 0080 - 0090 + 0100; 0150 = max(0, 0110 - 0130). The COREP
  Annex II §1.3 "(-)" sign convention is applied by a module post-step
  AFTER execution (negating {0030, 0035, 0050, 0060, 0070, 0080, 0090,
  0130, 0140} plus the CRR supporting-factor adjustments {0216, 0217};
  -0.0 normalised; null stays null).
- Row subsets reproduce the retired section builders as tolerant-equals
  terms over raw and module-derived discriminator columns (defaulted /
  SME / materially-dependent / qualifying-RE ladders, the RW band label,
  the CCF bucket, the substitution flag, on/off-balance-sheet). A row
  whose subset is EMPTY (or whose discriminators are absent) renders
  ALL-NULL — the retired ``_null_row`` contract — via a module post-step
  that re-applies each row's predicate.
- Cells whose sources are never produced render None via constant
  Formulas (0240; 0210/0211 when no ``risk_type`` / ``cp_entity_type``
  carrier is sealed; the CCF buckets and supporting-factor adjustments
  when their carriers are absent), preserving the recorded structural-null
  cells.

References:
- CRR Art. 111-113 (SA exposure values / RWEA); Art. 501/501a
  (supporting factors); COREP Annex II C 07.00 ¶40-43/¶56/¶56A (class
  assignment + substitution); PRA PS1/26 Annex II/App. 17 (OF 07.00)
- docs/plans/phase7-declarative-reporting.md §3.2/§6 (S8, decision F4)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import polars as pl
from watchfire import cites

from rwa_calc.domain.enums import ExposureClass
from rwa_calc.reporting.cellspec import (
    CellSpec,
    Formula,
    RowPredicate,
    SafeSum,
    SideContext,
    Sum,
    TemplateSpec,
    execute,
    matched_counts,
)
from rwa_calc.reporting.corep.templates import (
    get_c07_columns,
    get_sa_risk_weight_bands,
    get_sa_row_sections,
)
from rwa_calc.reporting.kernel import filter_by_approach, gross_carriers, pick
from rwa_calc.reporting.metadata import ReportingContext

if TYPE_CHECKING:
    from collections.abc import Mapping

# COREP Annex II §1.3 "(-)"-labelled deduction columns, negated post-execute.
# 0216/0217 are the CRR-only "(-) SME/Infrastructure supporting factor adjustment"
# columns (Art. 501/501a) — reported negative so 0215 + 0216 + 0217 = 0220 foots.
_NEGATIVE_COLS: frozenset[str] = frozenset(
    {"0030", "0035", "0050", "0060", "0070", "0080", "0090", "0130", "0140", "0216", "0217"}
)

# CCF bucket maps: ccf_applied (rounded to 4dp) -> column ref.
_CCF_MAP_CRR: dict[float, str] = {0.0: "0160", 0.2: "0170", 0.5: "0180", 1.0: "0190"}
_CCF_MAP_B31: dict[float, str] = {0.1: "0160", 0.2: "0170", 0.4: "0171", 0.5: "0180", 1.0: "0190"}
_CCF_REFS: tuple[str, ...] = ("0160", "0170", "0171", "0180", "0190")

# What counts as counterparty credit risk in C 07.00: the population limb
# (``c07_population``) and the "of which: arising from CCR" discriminator (cols
# 0210/0211) read the SAME set. All three members are SA-risk-weighted but carry
# ``standardised_ccr`` under the output floor, so they are admitted by risk_type,
# never by the approach label.
#
# The CCR set is THREE risk types, not two: FCCM SFT synthetic rows, SA-CCR
# derivative netting sets, and ``CCR_DEFAULT_FUND`` — CCP default-fund
# contributions (Art. 307-309), which are Chapter 6 counterparty credit risk just
# as much as the other two. Do not trim it back to two: without it the population
# would silently depend on the approach LABEL (default-fund rows carry
# ``approach_applied == "standardised"``, so they reach C 07.00 anyway today — the
# limb makes the intent explicit), and the 0210/0211 "of which CCR" columns would
# under-report a book that holds default-fund contributions. It also keeps this
# template's definition of CCR identical to OF 02.01's and CMS1's, so one
# submission cannot carry two contradictory definitions.
#
# Deliberately LOCAL to C 07.00 (docs/plans/c07-ccr-derivatives.md §4 D4): each
# template owns its own tuple — a shared risk-type constant is how one template's
# basis leaks into CR4/CR5/OV1, which key their own recorded bases.
_CCR_RISK_TYPES: tuple[str, ...] = ("CCR_SFT", "CCR_DERIVATIVE", "CCR_DEFAULT_FUND")

# Section 1 "of which" maps (retired _C07_* constants, preserved verbatim).
_SL_TYPE_MAP: dict[str, str] = {
    "0021": "object_finance",
    "0022": "commodities_finance",
    "0023": "project_finance",
}
_PF_PHASE_MAP: dict[str, str] = {
    "0024": "pre_operational",
    "0025": "operational",
    "0026": "high_quality_operational",
}
_CIU_ROW_APPROACH: dict[str, str] = {
    "0281": "look_through",
    "0282": "mandate_based",
    "0283": "fallback",
}
# Memo defaulted-at-RW rows: ref -> the RW band label (Art. 127 100%/150%).
_MEMO_DEFAULTED_RW: dict[str, str] = {"0300": "100%", "0320": "150%"}
_MEMO_RE_SECURED: dict[str, str] = {"0290": "commercial", "0310": "residential"}
_RE_ROW_FILTERS: dict[str, dict[str, Any]] = {
    "0330": {"property_type": "residential"},
    "0331": {"property_type": "residential", "materially_dependent": False},
    "0332": {"property_type": "residential", "materially_dependent": True},
    "0340": {"property_type": "commercial"},
    "0341": {"property_type": "commercial", "materially_dependent": False, "is_sme": False},
    "0342": {"property_type": "commercial", "materially_dependent": True},
    "0343": {"property_type": "commercial", "materially_dependent": False, "is_sme": True},
    "0344": {"property_type": "commercial", "materially_dependent": True, "is_sme": True},
    "0350": {"is_qualifying": False},
    "0351": {"is_qualifying": False, "property_type": "residential", "materially_dependent": False},
    "0352": {"is_qualifying": False, "property_type": "residential", "materially_dependent": True},
    "0353": {"is_qualifying": False, "property_type": "commercial", "materially_dependent": False},
    "0354": {"is_qualifying": False, "property_type": "commercial", "materially_dependent": True},
    "0360": {"is_adc": True},
}
_EQUITY_TRANSITIONAL_FILTERS: dict[str, tuple[str, bool]] = {
    "0371": ("sa_transitional", True),
    "0372": ("sa_transitional", False),
    "0373": ("irb_transitional", True),
    "0374": ("irb_transitional", False),
}

_Terms = tuple[tuple[str, str | bool], ...]


def _const(value: float | None):  # noqa: ANN202 - tiny Formula factory
    def fn(_cells: Mapping[str, float | None], _prior: bool) -> float | None:
        return value

    return fn


def _net_of_adjustments(cells: Mapping[str, float | None], _prior: bool) -> float | None:
    """0040 = 0010 - 0030 - 0035 (positive magnitudes; 0035 absent under CRR)."""
    return (cells["0010"] or 0.0) - (cells["0030"] or 0.0) - (cells.get("0035") or 0.0)


def _net_after_substitution(cells: Mapping[str, float | None], _prior: bool) -> float | None:
    """0110 = 0040 - 0050 - 0060 - 0070 - 0080 - 0090 + 0100."""
    return (
        (cells["0040"] or 0.0)
        - (cells["0050"] or 0.0)
        - (cells["0060"] or 0.0)
        - (cells["0070"] or 0.0)
        - (cells["0080"] or 0.0)
        - (cells["0090"] or 0.0)
        + (cells["0100"] or 0.0)
    )


def _fully_adjusted(cells: Mapping[str, float | None], _prior: bool) -> float | None:
    """0150 = max(0, 0110 - 0130)."""
    return max(0.0, (cells["0110"] or 0.0) - (cells["0130"] or 0.0))


@dataclass(frozen=True)
class SheetPlan:
    """Everything one C 07.00 sheet is executed from.

    The spec + the prepared, partitioned frame + the side context ARE the
    definition of every cell on that sheet: ``execute(spec, frame, ctx)``
    produces it. Exposing the plan (rather than only the rendered frame) lets a
    consumer that must explain a cell — the lineage drill-down — read the very
    same ``CellSpec`` and run the very same ``RowPredicate`` over the very same
    rows the generator used, instead of re-deriving the population, the Art.
    112(1)(g) merge, the derived discriminators and the sheet partition (a copy
    that could silently drift from the reported figure).

    ``row_terms`` and ``negative_cols`` carry the two post-``execute`` passes
    (all-null inert rows; the Annex II §1.3 "(-)" negation), so a consumer knows
    a rendered cell's sign and emptiness policy without re-deciding either.
    """

    spec: TemplateSpec
    frame: pl.DataFrame
    ctx: ReportingContext
    row_terms: dict[str, _Terms | None]
    negative_cols: frozenset[str] = _NEGATIVE_COLS


@cites("PS1/26, paragraph 1.3")
def c07_plans(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, SheetPlan]:
    """Build the per-obligor-class execution plans for C 07.00.

    Preserves the generator's contracts: missing EAD/RWA columns record
    "C07: Missing EAD or RWA columns in results"; a missing class column records
    "C07: Missing exposure_class column"; an empty SA population yields ``{}``.
    """
    # Phase 7 convergence: the sealed obligor applied class, single name
    # (== the retired exposure_class_applied/exposure_class ladder).
    ec_col = pick(cols, "reporting_class_origin")
    ead_col = pick(cols, "ead_final")
    rwa_col = pick(cols, "rwa_final", "rwa_post_factor", "rwa")
    if ec_col is None or ead_col is None or rwa_col is None:
        if ead_col is None or rwa_col is None:
            errors.append("C07: Missing EAD or RWA columns in results")
        if ec_col is None:
            errors.append("C07: Missing exposure_class column")
        return {}

    sa_df = c07_population(results, cols).collect()
    if len(sa_df) == 0:
        return {}

    # Art. 112 Table A2: SL is a corporate sub-type under SA.
    sa_df = sa_df.with_columns(
        pl.when(pl.col(ec_col) == ExposureClass.SPECIALISED_LENDING.value)
        .then(pl.lit(ExposureClass.CORPORATE.value))
        .otherwise(pl.col(ec_col))
        .alias(ec_col)
    )
    data_cols = set(sa_df.columns)
    sa_df = _prepare(sa_df, data_cols, framework)
    inflow_map = _substitution_inflows(sa_df, data_cols)

    row_terms = _row_terms(framework, data_cols)
    spec = _build_spec(framework, data_cols, ead_col, rwa_col, row_terms)

    plans: dict[str, SheetPlan] = {}
    # Sealed-ledger rule: the class column always exists; a null key
    # (no source on a synthetic frame) partitions into NO sheet.
    for ec in sa_df[ec_col].drop_nulls().unique().sort().to_list():
        plans[ec] = SheetPlan(
            spec=spec,
            frame=sa_df.filter(pl.col(ec_col) == ec),
            ctx=ReportingContext(substitution_inflow=inflow_map.get(ec, 0.0)),
            row_terms=row_terms,
        )
    return plans


@cites("PS1/26, paragraph 1.3")
def generate_c07(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, pl.DataFrame]:
    """Execute C 07.00 per obligor-class sheet over the sealed ledger."""
    result: dict[str, pl.DataFrame] = {}
    for ec, plan in c07_plans(results, cols, framework, errors).items():
        frame = execute(plan.spec, plan.frame, plan.ctx)
        frame = _null_empty_rows(frame, plan.frame, plan.row_terms)
        result[ec] = _negate_deduction_cols(frame)
    return result


@cites("PS1/26")
def c07_population(results: pl.LazyFrame, cols: set[str]) -> pl.LazyFrame:
    """The C 07.00 population: the standardised book plus the CCR rows.

    The CCR limb admits BOTH counterparty-credit-risk risk types (FCCM SFT
    synthetic rows and SA-CCR derivative netting sets) by ``risk_type`` —
    Annex II puts them in rows 0090-0130, and C 07.00 risk-weights under SA the
    very exposures C 34 analyses by approach. Admission cannot key the approach
    label: under the output floor ``engine/stages/calc.py`` relabels CCR rows to
    ``standardised_ccr`` so they route into the floor-eligible approaches, which
    is load-bearing and must NOT be undone here.

    Under CRR the derivative rows already arrive on the ``"standardised"`` limb;
    the ``unique`` dedupe means admitting them again costs nothing (the CRR
    totals do not move). Under Basel 3.1 this limb is the only one that admits
    them at all.
    """
    sa = filter_by_approach(
        results, "standardised", cols, candidates=("reporting_approach_origin",)
    )
    if "risk_type" not in cols:
        return sa
    ccr = results.filter(pl.col("risk_type").is_in(_CCR_RISK_TYPES))
    # The dedupe keys the exposure reference, which the sealed ledger always
    # carries. The `subset=None` fallback (synthetic unit frames only, where no
    # reference column exists) dedupes on ALL columns — two genuinely distinct
    # exposures identical in every column would collapse into one. Harmless
    # where it can fire; do not promote this fallback to the ledger path.
    return pl.concat([sa, ccr], how="diagonal_relaxed").unique(
        subset=["exposure_reference"] if "exposure_reference" in cols else None,
        keep="first",
    )


def _prepare(data: pl.DataFrame, cols: set[str], framework: str) -> pl.DataFrame:
    """Add the module-derived discriminator columns (each only when its
    sources exist — an underived column makes its tolerant terms match
    nothing, reproducing the retired absent-column null rows)."""
    exprs: list[pl.Expr] = []

    # Defaulted ladder (retired _filter_defaulted, verbatim precedence).
    if "is_defaulted" in cols:
        exprs.append(pl.col("is_defaulted").fill_null(value=False).alias("c07_defaulted"))
    elif "default_status" in cols:
        exprs.append((pl.col("default_status") == True).alias("c07_defaulted"))  # noqa: E712
    elif "exposure_class_applied" in cols or "exposure_class" in cols:
        class_col = (
            "exposure_class_applied" if "exposure_class_applied" in cols else "exposure_class"
        )
        exprs.append((pl.col(class_col) == "defaulted").alias("c07_defaulted"))
    elif "pd_floored" in cols:
        exprs.append((pl.col("pd_floored") >= 1.0).alias("c07_defaulted"))

    # SME ladder (retired _filter_sme).
    if "sme_supporting_factor_eligible" in cols:
        exprs.append(
            (pl.col("sme_supporting_factor_eligible") == True).alias("c07_sme")  # noqa: E712
        )
    elif "exposure_class" in cols:
        exprs.append(
            pl.col("exposure_class").str.contains("sme").fill_null(value=False).alias("c07_sme")
        )

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
            .alias("c07_substituted")
        )
    else:
        exprs.append(pl.lit(value=False).alias("c07_substituted"))

    # On/off-balance-sheet (kernel rule: bs_type preferred, else exposure_type).
    if "bs_type" in cols:
        exprs.append(
            pl.when(pl.col("bs_type") == "ONB")
            .then(pl.lit("on"))
            .when(pl.col("bs_type") == "OFB")
            .then(pl.lit("off"))
            .otherwise(pl.lit(None, dtype=pl.String))
            .alias("c07_bs")
        )
    elif "exposure_type" in cols:
        exprs.append(
            pl.when(pl.col("exposure_type") == "loan")
            .then(pl.lit("on"))
            .when(pl.col("exposure_type").is_in(["facility", "contingent"]))
            .then(pl.lit("off"))
            .otherwise(pl.lit(None, dtype=pl.String))
            .alias("c07_bs")
        )

    # RW band label (retired _compute_rw_section_rows assignment).
    if "risk_weight" in cols:
        band_expr = pl.lit("Other risk weights")
        for rw_value, label in reversed(get_sa_risk_weight_bands(framework)):
            band_expr = (
                pl.when(
                    pl.col("risk_weight").cast(pl.Float64, strict=False).round(4)
                    == round(rw_value, 4)
                )
                .then(pl.lit(label))
                .otherwise(band_expr)
            )
        exprs.append(band_expr.alias("c07_rw_band"))

    # CCF bucket ref (retired _c07_ccf_cols map).
    if "ccf_applied" in cols:
        ccf_map = _CCF_MAP_B31 if framework == "BASEL_3_1" else _CCF_MAP_CRR
        bucket_expr: pl.Expr = pl.lit(None, dtype=pl.String)
        for ccf_value, ref in ccf_map.items():
            bucket_expr = (
                pl.when(
                    pl.col("ccf_applied").cast(pl.Float64, strict=False).round(4)
                    == round(ccf_value, 4)
                )
                .then(pl.lit(ref))
                .otherwise(bucket_expr)
            )
        exprs.append(bucket_expr.alias("c07_ccf_bucket"))

    # Materially-dependent ladder (exact field keeps nulls-excluded; proxies
    # fill null to False — retired _filter_re_materially_dependent).
    if "materially_dependent_on_property" in cols:
        exprs.append(pl.col("materially_dependent_on_property").alias("c07_md"))
    elif "has_income_cover" in cols:
        exprs.append(pl.col("has_income_cover").fill_null(value=False).alias("c07_md"))
    elif "is_income_producing" in cols:
        exprs.append(pl.col("is_income_producing").fill_null(value=False).alias("c07_md"))

    if "property_type" in cols:
        exprs.append(pl.col("property_type").is_not_null().alias("c07_has_property"))
    if "is_qualifying_re" in cols:
        exprs.append(pl.col("is_qualifying_re").fill_null(value=True).alias("c07_qualifying_re"))
    if "ppu_reason" in cols:
        exprs.append(
            pl.col("ppu_reason")
            .str.starts_with("art_150_1_")
            .fill_null(value=False)
            .alias("c07_ppu")
        )
    if "sa_cqs" in cols:
        exprs.append(pl.col("sa_cqs").is_not_null().alias("c07_rated"))

    # CCR discriminators (cols 0210/0211). 0210 = "of which: arising from
    # counterparty credit risk"; 0211 = the same, excluding the Art. 301(1)
    # CCP-cleared transactions. RowPredicate carries no negation, so the
    # "excluding CCP" side is derived here as its own flag.
    if "risk_type" in cols:
        is_ccr = pl.col("risk_type").is_in(_CCR_RISK_TYPES).fill_null(value=False)
        exprs.append(is_ccr.alias("c07_ccr"))
        if "cp_entity_type" in cols:
            exprs.append(
                (is_ccr & (pl.col("cp_entity_type").fill_null("") != "ccp")).alias(
                    "c07_ccr_non_ccp"
                )
            )

    # QCCP discriminator (the "of which: cleared through a QCCP" rows 0100/0120).
    # The project-wide canonical form, mirrored verbatim: a ``ccp`` entity_type
    # whose flag is not an EXPLICIT False (CRR Art. 272 Def (88) / Art. 306 — an
    # absent flag is treated as qualifying; only an explicit False demotes a
    # ``ccp`` to the Art. 107(2)(a) institution ladder). Identical to
    # engine/sa/risk_weights.py's 2%/4% override, the aggregator's
    # ``rwa_ccr_qccp_trade`` partition and Pillar 3 CCR8. It MUST be derived
    # rather than expressed as a RowPredicate term: a bare ("cp_is_qccp", True)
    # compiles to ``== True``, so a NULL flag would drop a netting set that the
    # very same sheet already reports in the 2% risk-weight band.
    if {"cp_entity_type", "cp_is_qccp"} <= cols:
        exprs.append(
            ((pl.col("cp_entity_type") == "ccp") & pl.col("cp_is_qccp").fill_null(value=True))
            .fill_null(value=False)
            .alias("c07_qccp")
        )

    # Collateral volatility/maturity adjustment (col 0140 = market - Cvam).
    if "collateral_market_value" in cols:
        adjusted = (
            pl.col("collateral_adjusted_value").fill_null(0.0)
            if "collateral_adjusted_value" in cols
            else pl.lit(0.0)
        )
        exprs.append(
            (pl.col("collateral_market_value").fill_null(0.0) - adjusted).alias("c07_vol_mat_adj")
        )

    # Supporting-factor RWEA delta (cols 0216/0217 = pre - post per row).
    if "rwa_pre_factor" in cols:
        rwa_source = pick(cols, "rwa_final", "rwa_post_factor", "rwa")
        if rwa_source is not None:
            exprs.append(
                (pl.col("rwa_pre_factor").fill_null(0.0) - pl.col(rwa_source).fill_null(0.0)).alias(
                    "c07_sf_delta"
                )
            )

    return data.with_columns(exprs) if exprs else data


def _substitution_inflows(sa_df: pl.DataFrame, cols: set[str]) -> dict[str, float]:
    """Per-destination-class substitution inflows (retired
    _compute_substitution_flows, inflow side): guaranteed portions of
    substituted rows grouped by the guarantor's class."""
    if not (
        {"guaranteed_portion", "pre_crm_exposure_class", "post_crm_exposure_class_guaranteed"}
        <= cols
    ):
        return {}
    migrated = sa_df.filter(pl.col("c07_substituted"))
    if len(migrated) == 0:
        return {}
    grouped = migrated.group_by("post_crm_exposure_class_guaranteed").agg(
        pl.col("guaranteed_portion").fill_null(0.0).sum().alias("inflow")
    )
    return {
        row["post_crm_exposure_class_guaranteed"]: float(row["inflow"])
        for row in grouped.iter_rows(named=True)
    }


def _row_terms(framework: str, cols: set[str]) -> dict[str, _Terms | None]:
    """Tolerant-equals membership terms per row ref (None = inert row —
    rendered all-null). Ports the retired section-subset builders."""
    terms: dict[str, _Terms | None] = {}
    for section_index, section in enumerate(get_sa_row_sections(framework)):
        for row in section.rows:
            terms[row.ref] = _terms_for_row(section_index, row.ref, row.name, cols)
    return terms


def _terms_for_row(  # noqa: PLR0911, PLR0912, C901 - a direct table of the retired dispatch
    section_index: int, ref: str, name: str, cols: set[str]
) -> _Terms | None:
    if section_index == 0:
        if ref == "0010":
            return ()
        if ref == "0015":
            return (("c07_defaulted", True),)
        if ref == "0020":
            return (("c07_sme", True),)
        if ref in _SL_TYPE_MAP:
            return (("sl_type", _SL_TYPE_MAP[ref]),)
        if ref in _PF_PHASE_MAP:
            return (("sl_type", "project_finance"), ("sl_project_phase", _PF_PHASE_MAP[ref]))
        if ref in _RE_ROW_FILTERS:
            return _re_terms(cols, **_RE_ROW_FILTERS[ref])  # type: ignore[arg-type]
        if ref == "0030":
            return _supporting_factor_terms(cols, "sme")
        if ref == "0035":
            return _supporting_factor_terms(cols, "infrastructure")
        if ref == "0050":
            return (("c07_ppu", True),)
        if ref == "0060":
            return (("ppu_reason", "art_148_rollout"),)
        return None
    if section_index == 1:
        if ref == "0070":
            return (("c07_bs", "on"),)
        if ref == "0080":
            return (("c07_bs", "off"),)
        if ref == "0090":
            return (("risk_type", "CCR_SFT"),)
        if ref == "0100":  # of which: SFT netting sets cleared through a QCCP
            return (("risk_type", "CCR_SFT"), ("c07_qccp", True))
        if ref == "0110":  # derivative + long-settlement netting sets — the
            # ADDITIVE PARENT of 0120: every netting set, INCLUDING the
            # QCCP-cleared ones. Writing it as "derivative AND NOT qccp" would
            # make 0120 a sibling and the breakdown would stop footing.
            return (("risk_type", "CCR_DERIVATIVE"),)
        if ref == "0120":  # of which: derivative netting sets cleared via a QCCP
            return (("risk_type", "CCR_DERIVATIVE"), ("c07_qccp", True))
        # 0130 (contractual cross-product netting sets, Art. 295(c)) is NOT
        # MODELLED: no input carrier exists for a cross-product netting
        # agreement. Inert, not "checked and found empty".
        return None
    if section_index == 2:  # noqa: PLR2004 - RW band section
        return (("c07_rw_band", name),)
    if section_index == 3:  # noqa: PLR2004 - CIU section
        if ref in _CIU_ROW_APPROACH:
            return (("ciu_approach", _CIU_ROW_APPROACH[ref]),)
        return None
    # Section 5: memorandum items
    if ref in _EQUITY_TRANSITIONAL_FILTERS:
        approach, higher_risk = _EQUITY_TRANSITIONAL_FILTERS[ref]
        base: _Terms = (("equity_transitional_approach", approach),)
        if "equity_higher_risk" in cols:
            return (*base, ("equity_higher_risk", higher_risk))
        if higher_risk:
            return None
        return base
    if ref == "0380":
        return (("currency_mismatch_multiplier_applied", True),)
    if ref in _MEMO_DEFAULTED_RW:
        return (("c07_defaulted", True), ("c07_rw_band", _MEMO_DEFAULTED_RW[ref]))
    if ref in _MEMO_RE_SECURED:
        return (("property_type", _MEMO_RE_SECURED[ref]),)
    return None


def _re_terms(
    cols: set[str],
    *,
    property_type: str | None = None,
    materially_dependent: bool | None = None,
    is_sme: bool | None = None,
    is_adc: bool | None = None,
    is_qualifying: bool | None = None,
) -> _Terms | None:
    """RE "of which" membership terms (retired _filter_re semantics)."""
    terms: list[tuple[str, str | bool]] = []
    if property_type is not None:
        terms.append(("property_type", property_type))
    else:
        terms.append(("c07_has_property", True))
    if is_qualifying is not None:
        if "is_qualifying_re" not in cols and is_qualifying is False:
            return None  # no non-qualifying RE to report
        terms.append(("c07_qualifying_re", is_qualifying))
    if materially_dependent is not None:
        terms.append(("c07_md", materially_dependent))
    if is_sme is not None:
        terms.append(("c07_sme", is_sme))
    if is_adc is not None:
        if "is_adc" not in cols and is_adc is True:
            return None
        terms.append(("is_adc", is_adc))
    return tuple(terms)


def _supporting_factor_terms(cols: set[str], factor_type: str) -> _Terms | None:
    """Section 1 supporting-factor row terms (retired _filter_supporting_factor)."""
    flag_col = "is_sme" if factor_type == "sme" else "is_infrastructure"
    if flag_col not in cols:
        return None
    applied = pick(cols, f"{factor_type}_supporting_factor_applied", "supporting_factor_applied")
    if applied is None:
        return ((flag_col, True),)
    return ((flag_col, True), (applied, True))


def _build_spec(
    framework: str,
    cols: set[str],
    ead_col: str,
    rwa_col: str,
    row_terms: dict[str, _Terms | None],
) -> TemplateSpec:
    """The C 07.00 TemplateSpec for one run (built cols-aware so carrier
    ladders and structural-null variants resolve once per generate call)."""
    column_refs = tuple(col.ref for col in get_c07_columns(framework))
    is_b31 = framework == "BASEL_3_1"
    rows = tuple(row for section in get_sa_row_sections(framework) for row in section.rows)

    cells: dict[tuple[str, str], CellSpec] = {}
    for row in rows:
        terms = row_terms.get(row.ref)
        if terms is None:
            continue
        for col_ref, cell in _row_cells(
            terms, cols, ead_col, rwa_col, column_refs, is_b31=is_b31, is_total=row.ref == "0010"
        ).items():
            cells[(row.ref, col_ref)] = cell
    return TemplateSpec(
        name="c07_00",
        rows=rows,
        column_refs=column_refs,
        cells=cells,
        empty_cell="zero",
    )


def _row_cells(  # noqa: PLR0913 - the full 24-column surface of one row
    terms: _Terms,
    cols: set[str],
    ead_col: str,
    rwa_col: str,
    column_refs: tuple[str, ...],
    *,
    is_b31: bool,
    is_total: bool,
) -> dict[str, CellSpec]:
    member = RowPredicate(equals=terms)

    def narrowed(*extra: tuple[str, str | bool]) -> RowPredicate:
        return RowPredicate(equals=(*terms, *extra))

    cells: dict[str, CellSpec] = {
        "0010": CellSpec(
            SafeSum(gross_carriers(cols, "drawn_amount", "undrawn_amount")), predicate=member
        ),
        "0020": CellSpec(Sum("own_funds_deduction_amount"), predicate=member),
        "0030": CellSpec(
            SafeSum(("scra_provision_amount", "gcra_provision_amount")), predicate=member
        ),
        "0050": (
            CellSpec(
                Sum("guaranteed_portion"),
                predicate=narrowed(("protection_type", "guarantee")),
            )
            if "protection_type" in cols
            else CellSpec(Sum("guaranteed_portion"), predicate=member)
        ),
        "0060": (
            CellSpec(
                Sum("guaranteed_portion"),
                predicate=narrowed(("protection_type", "credit_derivative")),
            )
            if "protection_type" in cols
            else CellSpec(Formula(refs=(), fn=_const(0.0)))
        ),
        "0070": CellSpec(SafeSum(("fcsm_collateral_value",)), predicate=member),
        "0080": CellSpec(
            SafeSum(
                (
                    "collateral_re_value",
                    "collateral_receivables_value",
                    "collateral_other_physical_value",
                )
            ),
            predicate=member,
        ),
        "0090": CellSpec(Sum("guaranteed_portion"), predicate=narrowed(("c07_substituted", True))),
        "0110": CellSpec(
            Formula(
                refs=("0040", "0050", "0060", "0070", "0080", "0090", "0100"),
                fn=_net_after_substitution,
            )
        ),
        "0120": CellSpec(Formula(refs=(), fn=_const(0.0))),
        "0130": CellSpec(Sum("collateral_adjusted_value"), predicate=member),
        "0140": (
            CellSpec(Sum("c07_vol_mat_adj"), predicate=member)
            if "collateral_market_value" in cols
            else CellSpec(Formula(refs=(), fn=_const(None)))
        ),
        "0150": CellSpec(Formula(refs=("0110", "0130"), fn=_fully_adjusted)),
        "0200": CellSpec(Sum(ead_col), predicate=member),
        # Annex II col 0200: "Exposure values for CCR business shall be the same
        # as reported in column 0210" — so 0210 is the row's exposure value
        # narrowed to its CCR rows, and 0211 narrows further by excluding the
        # Art. 301(1) CCP-cleared transactions.
        "0210": (
            CellSpec(Sum(ead_col), predicate=narrowed(("c07_ccr", True)))
            if "risk_type" in cols
            else CellSpec(Formula(refs=(), fn=_const(None)))
        ),
        "0211": (
            CellSpec(Sum(ead_col), predicate=narrowed(("c07_ccr_non_ccp", True)))
            if {"risk_type", "cp_entity_type"} <= cols
            else CellSpec(Formula(refs=(), fn=_const(None)))
        ),
        "0220": CellSpec(Sum(rwa_col), predicate=member),
        "0240": CellSpec(Formula(refs=(), fn=_const(None))),
    }
    if is_total:
        cells["0100"] = CellSpec(SideContext("substitution_inflow"))
    if is_b31:
        cells["0035"] = CellSpec(Sum("on_bs_netting_amount"), predicate=member)
        cells["0040"] = CellSpec(Formula(refs=("0010", "0030", "0035"), fn=_net_of_adjustments))
    else:
        cells["0040"] = CellSpec(Formula(refs=("0010", "0030"), fn=_net_of_adjustments))
        # CRR supporting-factor columns (Art. 501/501a).
        cells["0215"] = CellSpec(
            Sum("rwa_pre_factor" if "rwa_pre_factor" in cols else rwa_col), predicate=member
        )
        cells["0216"] = _sf_adjustment_cell(terms, cols, "sme_supporting_factor_applied", "is_sme")
        cells["0217"] = _sf_adjustment_cell(
            terms, cols, "infrastructure_factor_applied", "is_infrastructure"
        )

    # CCF buckets: bucketed sums when the carrier exists, else structural null.
    ccf_refs = [ref for ref in _CCF_REFS if ref in column_refs]
    for ref in ccf_refs:
        if "ccf_applied" in cols:
            bucket_terms: _Terms = (*terms, ("c07_ccf_bucket", ref))
            if "bs_type" in cols:
                bucket_terms = (*bucket_terms, ("c07_bs", "off"))
            cells[ref] = CellSpec(Sum(ead_col), predicate=RowPredicate(equals=bucket_terms))
        else:
            cells[ref] = CellSpec(Formula(refs=(), fn=_const(None)))

    # ECAI split (0230/0235): sa_cqs is never sealed — populated on synthetic
    # frames only.
    if "sa_cqs" in cols:
        cells["0230"] = CellSpec(Sum(rwa_col), predicate=narrowed(("c07_rated", True)))
        if "0235" in column_refs:
            cells["0235"] = CellSpec(Sum(rwa_col), predicate=narrowed(("c07_rated", False)))
    else:
        cells["0230"] = CellSpec(Formula(refs=(), fn=_const(None)))
        if "0235" in column_refs:
            cells["0235"] = CellSpec(Formula(refs=(), fn=_const(None)))

    return {ref: cell for ref, cell in cells.items() if ref in column_refs}


def _sf_adjustment_cell(terms: _Terms, cols: set[str], dedicated: str, flag_col: str) -> CellSpec:
    """Supporting-factor RWEA adjustment (retired _supporting_factor_adjustment):
    Σ(rwa_pre_factor - rwa) over the applied rows; None when no carrier.
    ``dedicated`` is the factor's own applied-flag column (note the retired
    asymmetric names: sme_supporting_factor_applied vs
    infrastructure_factor_applied)."""
    if "rwa_pre_factor" not in cols:
        return CellSpec(Formula(refs=(), fn=_const(None)))
    if dedicated in cols:
        return CellSpec(
            Sum("c07_sf_delta"), predicate=RowPredicate(equals=(*terms, (dedicated, True)))
        )
    if flag_col in cols and "supporting_factor_applied" in cols:
        return CellSpec(
            Sum("c07_sf_delta"),
            predicate=RowPredicate(
                equals=(*terms, (flag_col, True), ("supporting_factor_applied", True))
            ),
        )
    return CellSpec(Formula(refs=(), fn=_const(None)))


def _null_empty_rows(
    frame: pl.DataFrame, class_df: pl.DataFrame, row_terms: dict[str, _Terms | None]
) -> pl.DataFrame:
    """Render inert rows and rows with EMPTY subsets all-null — the retired
    ``_null_row`` contract (the COREP zero policy applies only to populated
    rows' unbound cells)."""
    constrained = {
        ref: RowPredicate(equals=terms)
        for ref, terms in row_terms.items()
        if terms is not None and len(terms) > 0
    }
    counts = matched_counts(class_df, constrained)
    null_refs = [
        ref
        for ref, terms in row_terms.items()
        if terms is None or (len(terms) > 0 and counts[ref] == 0)
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


def _negate_deduction_cols(frame: pl.DataFrame) -> pl.DataFrame:
    """COREP Annex II §1.3: emit "(-)"-labelled deduction columns as negative
    figures (after the waterfalls consumed positive magnitudes); a zero
    deduction is normalised to ``+0.0`` and null stays null."""
    targets = [col for col in frame.columns if col in _NEGATIVE_COLS]
    if not targets:
        return frame
    return frame.with_columns(_negate_expr(col) for col in targets)


def _negate_expr(col: str) -> pl.Expr:
    """Negate a "(-)"-labelled deduction column, normalising a zero to ``+0.0``.

    Plain ``-pl.col(col)`` flips the IEEE sign bit, so a ``0.0`` cell would
    serialise as ``-0.0`` (``+ 0.0`` does NOT clear it in Polars); the explicit
    zero branch keeps a zero deduction as ``+0.0``. Null stays null. Identical
    expression to C 08.01/02's ``_negate`` pass."""
    return pl.when(pl.col(col) == 0.0).then(pl.lit(0.0)).otherwise(-pl.col(col)).alias(col)
