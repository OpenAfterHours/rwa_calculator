"""
COREP C 02.00 / OF 02.00 — own funds requirements (the master roll-up).

Pipeline position:
    sealed aggregator-exit ledger -> typed pre-pass aggregation kernels
    (approach / SA-class / IRB-class / SL-type / B31 sub-row group-bys)
    -> thin row-assembly shell -> DataFrame | None

This template is the recorded Kind-9 exception (plan §8.2): a portfolio-
total cross-approach roll-up whose row values are ratios of PRE-COMPUTED
aggregates with value-dependent fallbacks — it deliberately does NOT run
through the cellspec executor. The retired instance-state dicts
(``self._irb_class_rwa`` / ``_slotting_type_rwa`` / ``_irb_sub_rwa``)
become pure-function returns; everything else is relocated verbatim.

Cell semantics (recorded decisions, this slice):

- ``rwa_final`` is ALREADY post-floor: col 0030 (output floor) = the same
  total — never re-floored, never plus ``floor_impact_rwa``.
  ``rwa_pre_floor`` is read ONLY for the row-0034 activation boolean
  (total > pre-floor + 0.01).
- Equity RWA appears in THREE rows by design (0210 SA class, 0060 SA
  total, 0420 equity approach) while the flat total counts it once.
- SA class rows key RAW ``exposure_class`` through the many-to-one
  ACCUMULATING ``C02_00_SA_CLASS_MAP`` (retail fans four classes into
  0140; corporate absorbs specialised_lending into 0130).
- The ``_irb_*_split`` fallbacks are NOT filters: with no sub-row data the
  whole total lands in one bucket (corporate -> non-SME 0297/0356; RE ->
  residential-non-SME 0383; retail-other -> SME 0400 for CRR heritage).
- ``exposure_subclass`` is the canonical corporate split signal
  (financial/large -> 0295, SME -> 0296/0355, other -> 0297/0356); the
  is_sme / FSE-flag heuristic is the fallback. A-IRB folds FSE into the
  non-SME row 0356 while F-IRB keeps it separate in 0295 — asymmetric,
  preserved.
- B31 column policy: only the three approach parents (0220/0240/0300)
  zero out cols 0020/0030; every IRB sub-row mirrors col 0010; the
  totals take the portfolio SA-equivalent / floor values; 0040 takes
  x0.08 of each.
- The 0500 currency-mismatch memo is populated AFTER the B31 column pass,
  so its 0020/0030 render null (memo-only, excluded from the TREA total).
- Rows in ``C02_00_CREDIT_RISK_ROWS`` with no value zero-fill; the six
  other-risk-type rows null-fill.
- The floor indicator rows 0034/0035/0036 are gated on
  ``OutputFloorConfig.is_floor_applicable()`` (None config => applicable)
  and read ``OutputFloorSummary.floor_pct``/``of_adj`` (absent => 0.0,
  not null).

References:
- CRR Art. 92 (own funds requirements)
- PRA PS1/26 Art. 92 para 2A/3A/5 (output floor); Art. 123B (currency
  mismatch memo)
- docs/plans/phase7-declarative-reporting.md §8.2 (Kind-9 pre-pass)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import polars as pl
from watchfire import cites

from rwa_calc.reporting.corep.templates import (
    B31_C02_00_COLUMN_REFS,
    C02_00_CREDIT_RISK_ROWS,
    C02_00_SA_CLASS_MAP,
    CRR_C02_00_COLUMN_REFS,
    get_c02_00_row_sections,
)
from rwa_calc.reporting.kernel import null_row, pick

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import OutputFloorSummary
    from rwa_calc.contracts.config import OutputFloorConfig
    from rwa_calc.reporting.corep.templates import COREPRow, RowSection

# The finer-grained B31 sub-row aggregation key:
# (approach, exposure_class, is_sme, is_fse, property_type).
type _SubKey = tuple[str, str, bool | None, bool | None, str | None]


@cites("PS1/26, paragraph 1.3")
def generate_c02_00(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
    *,
    output_floor_summary: OutputFloorSummary | None = None,
    output_floor_config: OutputFloorConfig | None = None,
) -> pl.DataFrame | None:
    """Generate C 02.00 (CRR) / OF 02.00 (Basel 3.1) Own Funds Requirements.

    The master capital template aggregating RWEA across all risk types.
    This calculator only populates credit risk rows (SA, F-IRB, A-IRB,
    slotting, equity); all other risk-type rows (CCR, market, op risk)
    are null.
    """
    ead_col = pick(cols, "ead_final")
    rwa_col = pick(cols, "rwa_final", "rwa_post_factor", "rwa")
    if ead_col is None or rwa_col is None:
        errors.append("C 02.00 skipped: missing EAD or RWA columns in results")
        return None

    is_b31 = framework == "BASEL_3_1"
    column_refs = B31_C02_00_COLUMN_REFS if is_b31 else CRR_C02_00_COLUMN_REFS
    row_sections = get_c02_00_row_sections(framework)

    ec_col = pick(cols, "exposure_class")
    approach_col = pick(cols, "approach_applied")

    approach_rwa: dict[str, float] = {}
    sa_class_rwa: dict[str, float] = {}
    irb_class_rwa: dict[tuple[str, str], float] = {}
    slotting_type_rwa: dict[str, float] = {}
    irb_sub_rwa: dict[_SubKey, float] = {}

    if approach_col and ec_col:
        total_rwa, irb_class_rwa, slotting_type_rwa, irb_sub_rwa = _aggregate_by_approach(
            results, approach_col, ec_col, rwa_col, cols, is_b31, approach_rwa, sa_class_rwa
        )
    else:
        # Fallback: just compute total RWA (no per-approach breakdowns).
        total_stats = results.select(
            pl.col(rwa_col).fill_null(0.0).sum().alias("total_rwa"),
        ).collect()
        total_rwa = float(total_stats["total_rwa"][0])

    # SA-equivalent RWA for floor comparison (B31 col 0020)
    sa_equiv_rwa = 0.0
    if is_b31 and "sa_rwa" in cols:
        sa_equiv_stats = results.select(
            pl.col("sa_rwa").fill_null(0.0).sum().alias("sa_equiv"),
        ).collect()
        sa_equiv_rwa = float(sa_equiv_stats["sa_equiv"][0])

    # Output floor RWEA (B31 col 0030) — rwa_final is ALREADY post-floor;
    # rwa_pre_floor feeds only the activation boolean.
    floor_rwa = total_rwa
    floor_activated = False
    if is_b31 and "rwa_pre_floor" in cols:
        pre_floor_stats = results.select(
            pl.col("rwa_pre_floor").fill_null(0.0).sum().alias("pre_floor"),
        ).collect()
        pre_floor_total = float(pre_floor_stats["pre_floor"][0])
        floor_rwa = total_rwa
        floor_activated = total_rwa > pre_floor_total + 0.01

    sa_rwa_total = approach_rwa.get("standardised", 0.0)
    equity_rwa = approach_rwa.get("equity", 0.0)
    firb_rwa = approach_rwa.get("foundation_irb", 0.0)
    airb_rwa = approach_rwa.get("advanced_irb", 0.0)
    slotting_rwa = approach_rwa.get("slotting", 0.0)
    irb_total_rwa = firb_rwa + airb_rwa + slotting_rwa

    # Own funds requirement = 8% x TREA (Art. 92(1))
    own_funds_req = total_rwa * 0.08

    row_values: dict[str, dict[str, object]] = {}
    row_values["0010"] = {"0010": total_rwa}
    row_values["0040"] = {"0010": own_funds_req}
    row_values["0050"] = {"0010": total_rwa}  # Credit risk = total (only CR in scope)
    row_values["0060"] = {"0010": sa_rwa_total + equity_rwa}

    _sa_rows(row_values, sa_class_rwa, is_b31=is_b31)
    row_values["0220"] = {"0010": irb_total_rwa}
    _firb_rows(row_values, firb_rwa, irb_class_rwa, irb_sub_rwa, is_b31=is_b31)
    _airb_corp_rows(row_values, airb_rwa, irb_class_rwa, irb_sub_rwa, is_b31=is_b31)
    _airb_retail_rows(row_values, irb_class_rwa, irb_sub_rwa, is_b31=is_b31)
    _slotting_rows(row_values, slotting_rwa, slotting_type_rwa, is_b31=is_b31)
    row_values["0420"] = {"0010": equity_rwa}

    _floor_indicator_rows(
        row_values,
        output_floor_summary,
        output_floor_config,
        floor_activated=floor_activated,
        is_b31=is_b31,
    )
    if is_b31:
        _apply_b31_cols(row_values, sa_equiv_rwa, floor_rwa)

    # B31 memo row 0500 (PRA PS1/26 Art. 123B): portfolio-total RWEA of all
    # rows that fired the 1.5x currency-mismatch multiplier. Memo-only — only
    # col 0010 is populated (0020/0030 stay None via the build .get()), and
    # the row is excluded from the TREA total. Absent under CRR (the row is
    # not in CRR_C02_00_ROW_SECTIONS, so the build step never emits it).
    if is_b31 and "currency_mismatch_multiplier_applied" in cols:
        mismatch_rwea = float(
            results.filter(pl.col("currency_mismatch_multiplier_applied").fill_null(False))
            .select(pl.col(rwa_col).fill_null(0.0).sum().alias("rwea"))
            .collect()["rwea"][0]
        )
        row_values["0500"] = {"0010": mismatch_rwea}

    rows = _build_rows(row_values, row_sections, list(column_refs))
    schema: dict[str, pl.DataType | type[pl.DataType]] = {
        "row_ref": pl.String,
        "row_name": pl.String,
    }
    for ref in column_refs:
        schema[ref] = pl.Float64
    return pl.DataFrame(rows, schema=schema)


# =============================================================================
# Pre-pass aggregation kernels (pure functions — the retired self-state)
# =============================================================================


def _aggregate_by_approach(
    results: pl.LazyFrame,
    approach_col: str,
    ec_col: str,
    rwa_col: str,
    cols: set[str],
    is_b31: bool,  # noqa: FBT001 - retired positional signature preserved
    approach_rwa: dict[str, float],
    sa_class_rwa: dict[str, float],
) -> tuple[float, dict[tuple[str, str], float], dict[str, float], dict[_SubKey, float]]:
    """The retired instance-state aggregation as a pure function.

    Mutates ``approach_rwa`` / ``sa_class_rwa`` in place (the retired
    contract) and RETURNS what used to live on ``self``: the total, the
    IRB (approach, class) map, the slotting SL-type map, and the B31
    sub-row map.
    """
    collected = results.select(
        pl.col(approach_col).alias("_approach"),
        pl.col(ec_col).alias("_ec"),
        pl.col(rwa_col).fill_null(0.0).alias("_rwa"),
    ).collect()

    total_rwa = float(collected["_rwa"].sum())

    by_approach = collected.group_by("_approach").agg(pl.col("_rwa").sum().alias("rwa"))
    for row in by_approach.iter_rows(named=True):
        approach_rwa[row["_approach"]] = float(row["rwa"])

    # SA class breakdown (equity folds into the SA class group-by)
    sa_mask = collected["_approach"] == "standardised"
    equity_mask = collected["_approach"] == "equity"
    sa_rows = collected.filter(sa_mask | equity_mask)
    by_class = sa_rows.group_by("_ec").agg(pl.col("_rwa").sum().alias("rwa"))
    for row in by_class.iter_rows(named=True):
        sa_class_rwa[row["_ec"]] = float(row["rwa"])

    # IRB per-approach-and-class breakdown
    irb_rows = collected.filter(~sa_mask & ~equity_mask)
    irb_class_approach = irb_rows.group_by(["_approach", "_ec"]).agg(
        pl.col("_rwa").sum().alias("rwa")
    )
    irb_class_rwa = {
        (row["_approach"], row["_ec"]): float(row["rwa"])
        for row in irb_class_approach.iter_rows(named=True)
    }

    slotting_type_rwa = _slotting_type_agg(results, approach_col, rwa_col, cols)
    irb_sub_rwa = _irb_sub_agg(results, approach_col, ec_col, rwa_col, cols) if is_b31 else {}
    return total_rwa, irb_class_rwa, slotting_type_rwa, irb_sub_rwa


def _slotting_type_agg(
    results: pl.LazyFrame, approach_col: str, rwa_col: str, cols: set[str]
) -> dict[str, float]:
    """Aggregate slotting RWA by ``sl_type``. Returns empty dict if absent."""
    if "sl_type" not in cols:
        return {}
    sl_collected = (
        results.filter(pl.col(approach_col) == "slotting")
        .select(
            pl.col("sl_type").alias("_sl"),
            pl.col(rwa_col).fill_null(0.0).alias("_rwa"),
        )
        .collect()
    )
    by_sl = sl_collected.group_by("_sl").agg(pl.col("_rwa").sum().alias("rwa"))
    return {
        row["_sl"]: float(row["rwa"])
        for row in by_sl.iter_rows(named=True)
        if row["_sl"] is not None
    }


def _irb_sub_agg(
    results: pl.LazyFrame,
    approach_col: str,
    ec_col: str,
    rwa_col: str,
    cols: set[str],
) -> dict[_SubKey, float]:
    """Finer-grained IRB aggregation for B3.1 corporate/retail sub-rows."""
    sub_select: list[pl.Expr] = [
        pl.col(approach_col).alias("_approach"),
        pl.col(ec_col).alias("_ec"),
        pl.col(rwa_col).fill_null(0.0).alias("_rwa"),
    ]
    # The classifier-derived ``exposure_subclass`` (PRA PS1/26 Art. 147A(1)(e)/(f))
    # is the canonical corporate split signal: ``corporate_financial_large``
    # (FSE OR revenue > GBP 440m) -> row 0295, ``corporate_sme`` -> 0296/0355,
    # ``corporate_other`` -> 0297/0356. When it is absent (e.g. CRR frames or
    # pre-classifier inputs) fall back to the is_sme / FSE-flag heuristic.
    has_subclass = "exposure_subclass" in cols
    has_sme = "is_sme" in cols
    has_fse = (
        has_subclass or "cp_apply_fi_scalar" in cols or "cp_is_financial_sector_entity" in cols
    )
    has_pt = "property_type" in cols
    if has_sme or has_subclass:
        has_sme = True
        if has_subclass:
            sme_expr = pl.col("exposure_subclass") == "corporate_sme"
            if "is_sme" in cols:
                sme_expr = sme_expr | pl.col("is_sme").fill_null(value=False)
        else:
            sme_expr = pl.col("is_sme").fill_null(value=False)
        sub_select.append(sme_expr.alias("_sme"))
    if has_fse:
        if has_subclass:
            fse_expr = pl.col("exposure_subclass") == "corporate_financial_large"
        else:
            fse_col = (
                "cp_apply_fi_scalar"
                if "cp_apply_fi_scalar" in cols
                else "cp_is_financial_sector_entity"
            )
            fse_expr = pl.col(fse_col).fill_null(value=False)
        sub_select.append(fse_expr.alias("_fse"))
    if has_pt:
        sub_select.append(pl.col("property_type").alias("_pt"))

    irb_approaches = {"foundation_irb", "advanced_irb"}
    sub_collected = (
        results.filter(pl.col(approach_col).is_in(irb_approaches)).select(sub_select).collect()
    )
    gb_cols = ["_approach", "_ec"]
    if has_sme:
        gb_cols.append("_sme")
    if has_fse:
        gb_cols.append("_fse")
    if has_pt:
        gb_cols.append("_pt")
    sub_agg = sub_collected.group_by(gb_cols).agg(pl.col("_rwa").sum().alias("rwa"))
    return {
        (
            row["_approach"],
            row["_ec"],
            row.get("_sme"),
            row.get("_fse"),
            row.get("_pt"),
        ): float(row["rwa"])
        for row in sub_agg.iter_rows(named=True)
    }


def _irb_sub_split(
    sub_rwa: dict[_SubKey, float],
    approach: str,
    ec: str,
    total: float,
) -> tuple[float, float, float]:
    """Split IRB corporate RWA into (FSE/large, SME, non-SME) using sub_rwa.

    When sub_rwa has no data for the given approach/ec, falls back to
    (0.0, 0.0, total) — all RWA reported as non-SME.
    """
    fse = 0.0
    sme = 0.0
    nonsme = 0.0
    matched = False
    for key, rwa in sub_rwa.items():
        a, e, is_sme, is_fse, _pt = key
        if a != approach or e != ec:
            continue
        matched = True
        if is_fse:
            fse += rwa
        elif is_sme:
            sme += rwa
        else:
            nonsme += rwa
    if not matched:
        return 0.0, 0.0, total
    return fse, sme, nonsme


def _classify_re_bucket(is_comm: bool, is_sme: bool | None) -> tuple[int, int, int, int]:  # noqa: FBT001
    """Return a 4-tuple selector ``(resi_sme, resi_nonsme, comm_sme, comm_nonsme)``.

    Exactly one element is 1 (the bucket to credit), the rest are 0.
    Lets ``_irb_re_sub_split`` add RWA to the right bucket without a branch
    cascade.
    """
    if is_comm:
        return (0, 0, 1, 0) if is_sme else (0, 0, 0, 1)
    # residential / rre / null -> default to residential
    return (1, 0, 0, 0) if is_sme else (0, 1, 0, 0)


def _irb_re_sub_split(
    sub_rwa: dict[_SubKey, float],
    approach: str,
    ec: str,
    total: float,
) -> tuple[float, float, float, float]:
    """Split IRB retail mortgage into (resi_sme, resi_nonsme, comm_sme, comm_nonsme).

    Uses property_type ('residential'/'rre' vs 'commercial'/'cre') and is_sme
    from the sub_rwa dict. Falls back to (0, total, 0, 0) when no sub data.
    """
    buckets = [0.0, 0.0, 0.0, 0.0]
    matched = False
    for key, rwa in sub_rwa.items():
        a, e, is_sme, _fse, pt = key
        if a != approach or e != ec:
            continue
        matched = True
        is_comm = pt in ("commercial", "cre")
        for idx, weight in enumerate(_classify_re_bucket(is_comm, is_sme)):
            buckets[idx] += weight * rwa
    if not matched:
        return 0.0, total, 0.0, 0.0
    return buckets[0], buckets[1], buckets[2], buckets[3]


def _irb_other_sme_split(
    sub_rwa: dict[_SubKey, float],
    approach: str,
    ec: str,
    total: float,
) -> tuple[float, float]:
    """Split IRB retail_other into (SME, non-SME).

    Falls back to (total, 0.0) when no sub data (all reported as SME for
    backward compatibility with CRR row 0400).
    """
    sme = 0.0
    nonsme = 0.0
    matched = False
    for key, rwa in sub_rwa.items():
        a, e, is_sme, _fse, _pt = key
        if a != approach or e != ec:
            continue
        matched = True
        if is_sme:
            sme += rwa
        else:
            nonsme += rwa
    if not matched:
        return total, 0.0
    return sme, nonsme


# =============================================================================
# Row-assembly shell (relocated verbatim)
# =============================================================================


def _sa_rows(
    row_values: dict[str, dict[str, object]],
    sa_class_rwa: dict[str, float],
    *,
    is_b31: bool,
) -> None:
    """Populate SA per-class rows + B31 specialised-lending sub-row (0131)."""
    for ec_value, row_ref in C02_00_SA_CLASS_MAP.items():
        if ec_value in sa_class_rwa:
            if row_ref not in row_values:
                row_values[row_ref] = {"0010": 0.0}
            existing = float(cast("float", row_values[row_ref].get("0010", 0.0) or 0.0))
            row_values[row_ref]["0010"] = existing + sa_class_rwa[ec_value]

    if is_b31 and "specialised_lending" in sa_class_rwa:
        row_values["0131"] = {"0010": sa_class_rwa["specialised_lending"]}


def _firb_rows(
    row_values: dict[str, dict[str, object]],
    firb_rwa: float,
    irb_class_rwa: dict[tuple[str, str], float],
    irb_sub_rwa: dict[_SubKey, float],
    *,
    is_b31: bool,
) -> None:
    """Populate F-IRB rows (0240, 0250, 0260, 0271, 0290, 0295-0297)."""
    row_values["0240"] = {"0010": firb_rwa}

    firb_inst = irb_class_rwa.get(("foundation_irb", "institution"), 0.0)
    row_values["0250"] = {"0010": firb_inst}
    if is_b31:
        row_values["0271"] = {"0010": firb_inst}

    firb_corp = irb_class_rwa.get(("foundation_irb", "corporate"), 0.0)
    firb_sl = irb_class_rwa.get(("foundation_irb", "specialised_lending"), 0.0)
    row_values["0260"] = {"0010": firb_corp + firb_sl}

    if is_b31:
        row_values["0290"] = {"0010": firb_sl}
        firb_fse, firb_sme, firb_nonsme = _irb_sub_split(
            irb_sub_rwa, "foundation_irb", "corporate", firb_corp
        )
        row_values["0295"] = {"0010": firb_fse}  # Financial/large corporates
        row_values["0296"] = {"0010": firb_sme}  # Other general corporates SME
        row_values["0297"] = {"0010": firb_nonsme}  # Other general corporates non-SME


def _airb_corp_rows(
    row_values: dict[str, dict[str, object]],
    airb_rwa: float,
    irb_class_rwa: dict[tuple[str, str], float],
    irb_sub_rwa: dict[_SubKey, float],
    *,
    is_b31: bool,
) -> None:
    """Populate A-IRB sovereign / institution / corporate rows (0300-0356)."""
    row_values["0300"] = {"0010": airb_rwa}

    airb_sovereign = irb_class_rwa.get(("advanced_irb", "central_government"), 0.0)
    row_values["0310"] = {"0010": airb_sovereign}

    airb_inst = irb_class_rwa.get(("advanced_irb", "institution"), 0.0)
    row_values["0330"] = {"0010": airb_inst}

    airb_corp = irb_class_rwa.get(("advanced_irb", "corporate"), 0.0)
    airb_sl_excl = irb_class_rwa.get(("advanced_irb", "specialised_lending"), 0.0)
    row_values["0340"] = {"0010": airb_corp + airb_sl_excl}

    if is_b31:
        row_values["0350"] = {"0010": airb_sl_excl}
        airb_fse, airb_sme, airb_nonsme = _irb_sub_split(
            irb_sub_rwa, "advanced_irb", "corporate", airb_corp
        )
        # A-IRB folds FSE into the non-SME row (0356) — F-IRB keeps 0295.
        row_values["0355"] = {"0010": airb_sme}
        row_values["0356"] = {"0010": airb_nonsme + airb_fse}


def _airb_retail_rows(
    row_values: dict[str, dict[str, object]],
    irb_class_rwa: dict[tuple[str, str], float],
    irb_sub_rwa: dict[_SubKey, float],
    *,
    is_b31: bool,
) -> None:
    """Populate A-IRB retail rows (0370, 0380-0385, 0390, 0400, 0410-CRR)."""
    airb_retail_mort = irb_class_rwa.get(("advanced_irb", "retail_mortgage"), 0.0)
    airb_retail_qrre = irb_class_rwa.get(("advanced_irb", "retail_qrre"), 0.0)
    airb_retail_other = irb_class_rwa.get(("advanced_irb", "retail_other"), 0.0)

    row_values["0370"] = {"0010": airb_retail_mort + airb_retail_qrre + airb_retail_other}
    row_values["0380"] = {"0010": airb_retail_mort}

    if is_b31:
        resi_sme, resi_nonsme, comm_sme, comm_nonsme = _irb_re_sub_split(
            irb_sub_rwa, "advanced_irb", "retail_mortgage", airb_retail_mort
        )
        row_values["0382"] = {"0010": resi_sme}
        row_values["0383"] = {"0010": resi_nonsme}
        row_values["0384"] = {"0010": comm_sme}
        row_values["0385"] = {"0010": comm_nonsme}

    row_values["0390"] = {"0010": airb_retail_qrre}

    if is_b31:
        other_sme, other_nonsme = _irb_other_sme_split(
            irb_sub_rwa, "advanced_irb", "retail_other", airb_retail_other
        )
        row_values["0400"] = {"0010": other_sme}
        row_values["0410"] = {"0010": other_nonsme}
    else:
        row_values["0400"] = {"0010": airb_retail_other}


def _slotting_rows(
    row_values: dict[str, dict[str, object]],
    slotting_rwa: float,
    slotting_type_rwa: dict[str, float],
    *,
    is_b31: bool,
) -> None:
    """Populate slotting rows: CRR single 0410 vs B31 per-SL-type 0411-0416."""
    if is_b31:
        row_values["0411"] = {"0010": slotting_rwa}
        row_values["0412"] = {"0010": slotting_type_rwa.get("project_finance", 0.0)}
        row_values["0413"] = {"0010": slotting_type_rwa.get("object_finance", 0.0)}
        row_values["0414"] = {"0010": slotting_type_rwa.get("commodities_finance", 0.0)}
        row_values["0415"] = {"0010": slotting_type_rwa.get("ipre", 0.0)}
        row_values["0416"] = {"0010": slotting_type_rwa.get("hvcre", 0.0)}
    else:
        row_values["0410"] = {"0010": slotting_rwa}


def _floor_indicator_rows(
    row_values: dict[str, dict[str, object]],
    output_floor_summary: OutputFloorSummary | None,
    output_floor_config: OutputFloorConfig | None,
    *,
    floor_activated: bool,
    is_b31: bool,
) -> None:
    """Populate B31 output floor indicator rows 0034/0035/0036.

    Art. 92 para 2A: floor applies only to certain entity-type/basis combos.
    When ``output_floor_config`` provides ``is_floor_applicable() == False``,
    the indicator rows are still emitted but with zero values.
    """
    if not is_b31:
        return

    floor_applicable = output_floor_config is None or output_floor_config.is_floor_applicable()
    if floor_applicable:
        row_values["0034"] = {"0010": 1.0 if floor_activated else 0.0}
        if output_floor_summary is not None:
            row_values["0035"] = {"0010": output_floor_summary.floor_pct * 100.0}
            row_values["0036"] = {"0010": output_floor_summary.of_adj}
        else:
            row_values["0035"] = {"0010": 0.0}
            row_values["0036"] = {"0010": 0.0}
    else:
        row_values["0034"] = {"0010": 0.0}
        row_values["0035"] = {"0010": 0.0}
        row_values["0036"] = {"0010": 0.0}


def _apply_b31_cols(
    row_values: dict[str, dict[str, object]],
    sa_equiv_rwa: float,
    floor_rwa: float,
) -> None:
    """Fill B3.1 cols 0020 (SA-equivalent) and 0030 (output floor) for each row.

    Each row's policy follows row-ref membership: totals take the portfolio
    SA-equiv / floor values, indicator rows mirror col 0010, IRB rows zero out,
    and SA rows default to col 0010.
    """
    for ref, vals in row_values.items():
        col_0010 = vals.get("0010")
        if ref in {"0010", "0050"}:
            vals["0020"] = sa_equiv_rwa
            vals["0030"] = floor_rwa
        elif ref == "0040":
            vals["0020"] = sa_equiv_rwa * 0.08
            vals["0030"] = floor_rwa * 0.08
        elif ref in {"0034", "0035", "0036"}:
            vals["0020"] = col_0010
            vals["0030"] = col_0010
        elif ref == "0060":
            vals["0020"] = vals["0010"]
            vals["0030"] = vals["0010"]
        elif ref in {"0220", "0240", "0300"}:
            vals["0020"] = 0.0
            vals["0030"] = 0.0
        else:
            vals["0020"] = col_0010 if col_0010 is not None else None
            vals["0030"] = col_0010 if col_0010 is not None else None


def _row_dict(
    row_def: COREPRow,
    row_values: dict[str, dict[str, object]],
    column_refs: list[str],
) -> dict[str, object]:
    """Build a single C 02.00 DataFrame row dict.

    Three regimes: populated (ref in row_values), zero-fill (credit-risk row
    without data), or null-fill (out-of-scope row).
    """
    if row_def.ref in row_values:
        vals = row_values[row_def.ref]
        return {
            "row_ref": row_def.ref,
            "row_name": row_def.name,
            **{ref: vals.get(ref) for ref in column_refs},
        }
    if row_def.ref in C02_00_CREDIT_RISK_ROWS:
        return {
            "row_ref": row_def.ref,
            "row_name": row_def.name,
            **dict.fromkeys(column_refs, 0.0),
        }
    return null_row(row_def.ref, row_def.name, column_refs)


def _build_rows(
    row_values: dict[str, dict[str, object]],
    row_sections: list[RowSection],
    column_refs: list[str],
) -> list[dict[str, object]]:
    """Assemble C 02.00 DataFrame rows from ``row_values`` + section templates."""
    return [
        _row_dict(row_def, row_values, column_refs)
        for section in row_sections
        for row_def in section.rows
    ]
