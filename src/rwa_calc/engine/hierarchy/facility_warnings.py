"""
Facility undrawn-commitment warnings for the hierarchy stage (HIE004-HIE006, DQ021).

Pipeline position:
    Loader -> HierarchyResolver (engine/hierarchy) -> Classifier
    Sub-module of the hierarchy stage package; called by ``unify`` right after
    ``facility_undrawn.calculate_facility_undrawn`` has planned the undrawn rows
    these warnings describe.

Key responsibilities:
- HIE004: an uncommitted facility declaring a risk type other than the UCC
  bucket ``LR`` — its undrawn row is priced as LR regardless.
- HIE005: an amount whose conversion into its facility's currency needs an FX
  rate the run does not hold — a drawing (not netted against the headroom) or
  a sub-facility limit (no slice of its umbrella's waterfall).
- HIE006: a facility other than an umbrella with no limit — no undrawn row.
- DQ021 (exposure children): a loan / contingent mapped under more than one
  facility, and how ``graph.resolve_exposure_mappings`` resolved it — the root
  whose headroom it reduces, once, and any mapping under another root ignored
  (review findings RC-01 / SF-03). Read off the RAW mappings, since the
  resolved ones no longer show the extra parents.
- Build all three as ONE small plan and materialise it once. The HIE005 rows
  come from the SAME expressions the netting sums read
  (``facility_utilisation_rows``, ``with_facility_currency_factor``), so a
  warning cannot disagree with the number it describes.

References:
- PRA PS1/26 Glossary "commitment"; Art. 111 Table A1 row (7)
- CRR Art. 111, Annex I item 4(a)
- CRR Art. 4(1)(56) / PRA PS1/26 Glossary "conversion factor"
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.errors import (
    ERROR_FACILITY_HEADROOM_FX_RATE_MISSING,
    ERROR_FACILITY_LIMIT_MISSING,
    ERROR_FACILITY_MAPPING_MULTI_PARENT,
    ERROR_UNCOMMITTED_FACILITY_RISK_TYPE,
    facility_headroom_fx_rate_missing_warning,
    facility_limit_missing_warning,
    facility_multi_parent_warning,
    facility_warning_summary,
    uncommitted_facility_risk_type_warning,
)
from rwa_calc.data.schemas import RISK_TYPE_SYNONYMS, VALID_CHILD_TYPES
from rwa_calc.domain.enums import ErrorCategory
from rwa_calc.engine.hierarchy.facility_fx import (
    build_facility_fx,
    facility_currency_lookup,
    with_facility_currency_factor,
)
from rwa_calc.engine.hierarchy.facility_undrawn import (
    UCC_RISK_TYPE,
    facility_utilisation_rows,
)
from rwa_calc.engine.hierarchy.graph import (
    filter_mappings_by_child_type,
    resolve_to_root_facility,
)

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.contracts.errors import CalculationError
    from rwa_calc.engine.hierarchy.facility_fx import FacilityFx

logger = logging.getLogger(__name__)

#: The columns every warning row carries (null where a code does not use one).
_WARNING_SCHEMA: dict[str, pl.DataType] = {
    "_code": pl.String(),
    "_facility": pl.String(),
    "_value": pl.String(),
    "_target_currency": pl.String(),
    "_umbrella": pl.String(),
    # DQ021 only: the child's mapping type, every parent and the ignored ones.
    "_child_type": pl.String(),
    "_parents": pl.String(),
    "_ignored": pl.String(),
}


def collect_facility_undrawn_warnings(
    facilities: pl.LazyFrame,
    loans: pl.LazyFrame,
    contingents: pl.LazyFrame | None,
    facility_mappings: pl.LazyFrame,
    facility_root_lookup: pl.LazyFrame,
    *,
    fx_rates: pl.LazyFrame | None,
    config: CalculationConfig | None,
    sample_cap: int = 5,
    raw_facility_mappings: pl.LazyFrame | None = None,
) -> list[CalculationError]:
    """Return the HIE004 / HIE005 / HIE006 / DQ021 warnings for one run's facilities.

    One warning per facility (HIE004, HIE006), per (facility, currency) pair
    (HIE005) or per multi-parent loan / contingent (DQ021), in code-then-facility
    order, under the estate's ``sample_cap`` contract (as DQ005 / DQ013): at most
    ``sample_cap`` named per code, then one summary carrying the truthful count
    of the rest. Clean input returns ``[]``.

    Args:
        facilities: Sealed facilities frame.
        loans: Sealed loans frame.
        contingents: Sealed contingents frame, or None.
        facility_mappings: Sealed facility mappings.
        facility_root_lookup: Output of :func:`graph.build_facility_root_lookup`.
        fx_rates: The run's FX rates, or None when none were supplied.
        config: Calculation configuration (reporting currency, FX switch).
        sample_cap: Facilities named per code before the rest are summarised.
        raw_facility_mappings: The mappings BEFORE ``resolve_exposure_mappings``
            (the source of DQ021); None skips DQ021.

    Returns:
        The warnings, as ``CalculationError`` WARNINGs — category HIERARCHY for
        the HIE codes, DATA_QUALITY for DQ021.
    """
    plan = facility_undrawn_warning_plan(
        facilities,
        loans,
        contingents,
        facility_mappings,
        facility_root_lookup,
        fx_rates=fx_rates,
        config=config,
        raw_facility_mappings=raw_facility_mappings,
    )
    # Targeted mid-pipeline collect: the warning rows are a small dimension
    # (empty on clean input, at most one per facility and currency) and must
    # become ``CalculationError`` objects here, in the stage that made the
    # decisions they report. Paid for by collecting the facility graph edges
    # once instead of twice (``unify``).
    found = plan.collect()
    # Grouped in plain Python: an eager DataFrame filter / unique would run its
    # own lazy collect, a materialisation per code the run does not need.
    by_code: dict[str, list[dict[str, str | None]]] = {}
    for row in found.iter_rows(named=True):
        by_code.setdefault(str(row["_code"]), []).append(row)
    errors: list[CalculationError] = []
    for code, rows in by_code.items():
        errors.extend(_to_error(row) for row in rows[:sample_cap])
        omitted = len(rows) - sample_cap
        if omitted > 0:
            errors.append(
                facility_warning_summary(
                    code=code,
                    omitted=omitted,
                    sample_cap=sample_cap,
                    detail=_summary_detail(code, rows[sample_cap:]),
                    category=(
                        ErrorCategory.DATA_QUALITY
                        if code == ERROR_FACILITY_MAPPING_MULTI_PARENT
                        else ErrorCategory.HIERARCHY
                    ),
                )
            )
    return errors


def facility_undrawn_warning_plan(
    facilities: pl.LazyFrame,
    loans: pl.LazyFrame,
    contingents: pl.LazyFrame | None,
    facility_mappings: pl.LazyFrame,
    facility_root_lookup: pl.LazyFrame,
    *,
    fx_rates: pl.LazyFrame | None,
    config: CalculationConfig | None,
    raw_facility_mappings: pl.LazyFrame | None = None,
) -> pl.LazyFrame:
    """The lazy plan behind :func:`collect_facility_undrawn_warnings`.

    Returns one row per warning with the columns of ``_WARNING_SCHEMA``,
    de-duplicated and sorted by code, facility and value.
    """
    frames = [
        # The empty typed frame gives the diagonal concat every column, so a
        # code that does not use one still reads it (as null) when decoded.
        pl.LazyFrame(schema=_WARNING_SCHEMA),
        _uncommitted_risk_type_rows(facilities),
        _limit_missing_rows(facilities, facility_mappings),
    ]
    if raw_facility_mappings is not None:
        frames.append(_multi_parent_rows(raw_facility_mappings, facility_root_lookup))
    fx = build_facility_fx(fx_rates, config)
    if fx.enabled:
        frames.extend(
            _unconvertible_rows(
                facilities, loans, contingents, facility_mappings, facility_root_lookup, fx
            )
        )
    return (
        pl.concat(frames, how="diagonal_relaxed")
        .select(list(_WARNING_SCHEMA))
        .unique()
        .sort(["_code", "_facility", "_value"], nulls_last=True)
    )


def _uncommitted_risk_type_rows(facilities: pl.LazyFrame) -> pl.LazyFrame:
    """HIE004: ``committed=False`` with a declared, non-blank, non-LR risk_type.

    The declared value is canonicalised through the same synonym map the CCF
    builders use, so ``"low_risk"`` / ``"lr"`` are LR and raise nothing.
    """
    declared = pl.col("risk_type")
    canonical = declared.str.to_lowercase().replace(RISK_TYPE_SYNONYMS)
    return facilities.filter(
        pl.col("committed").eq_missing(False)
        & declared.is_not_null()
        & (declared.str.strip_chars() != "")
        & (canonical != UCC_RISK_TYPE)
    ).select(
        pl.lit(ERROR_UNCOMMITTED_FACILITY_RISK_TYPE).alias("_code"),
        pl.col("facility_reference").alias("_facility"),
        declared.alias("_value"),
    )


def _limit_missing_rows(facilities: pl.LazyFrame, facility_mappings: pl.LazyFrame) -> pl.LazyFrame:
    """HIE006: a null ``limit`` on any facility that is not an umbrella.

    An umbrella (a facility with at least one ``child_type='facility'`` child)
    may legitimately carry no limit — its sub-facilities then keep their own
    headroom uncapped — so it is excluded.
    """
    umbrellas = (
        filter_mappings_by_child_type(facility_mappings, "facility")
        .select(pl.col("parent_facility_reference").alias("facility_reference"))
        .unique()
    )
    return (
        facilities.filter(pl.col("limit").is_null())
        .join(umbrellas, on="facility_reference", how="anti")
        .select(
            pl.lit(ERROR_FACILITY_LIMIT_MISSING).alias("_code"),
            pl.col("facility_reference").alias("_facility"),
        )
    )


def _multi_parent_rows(raw_mappings: pl.LazyFrame, root_lookup: pl.LazyFrame) -> pl.LazyFrame:
    """DQ021: a loan / contingent mapped under more than one parent facility.

    ``_facility`` is the root whose headroom the child reduces — the root of its
    lowest-referenced parent, exactly as ``graph.resolve_exposure_mappings``
    chooses it — ``_parents`` every distinct parent and ``_ignored`` those under
    any other root (the mappings that resolution drops). Same-root children have
    an empty ``_ignored``: every sub-limit keeps them, the root nets them once.
    """
    kind = pl.col("child_type").str.to_lowercase()
    pairs = (
        raw_mappings.filter(
            kind.is_in(sorted(VALID_CHILD_TYPES - {"facility"})).eq_missing(True)
            & pl.col("parent_facility_reference").is_not_null()
            & pl.col("child_reference").is_not_null()
        )
        .select(
            kind.alias("_child_type"),
            pl.col("child_reference"),
            pl.col("parent_facility_reference"),
        )
        .unique()
    )
    resolved = resolve_to_root_facility(pairs, root_lookup)
    keys = ["_child_type", "child_reference"]
    summary = (
        resolved.group_by(keys)
        .agg(
            pl.col("parent_facility_reference").sort().alias("_parent_list"),
            pl.col("aggregation_facility")
            .sort_by("parent_facility_reference")
            .first()
            .alias("_facility"),
        )
        .filter(pl.col("_parent_list").list.len() > 1)
    )
    ignored = (
        resolved.join(summary.select([*keys, "_facility"]), on=keys, how="inner")
        .filter(pl.col("aggregation_facility") != pl.col("_facility"))
        .group_by(keys)
        .agg(pl.col("parent_facility_reference").sort().str.join(", ").alias("_ignored"))
    )
    return summary.join(ignored, on=keys, how="left").select(
        pl.lit(ERROR_FACILITY_MAPPING_MULTI_PARENT).alias("_code"),
        pl.col("_facility"),
        pl.col("child_reference").alias("_value"),
        pl.col("_child_type"),
        pl.col("_parent_list").list.join(", ").alias("_parents"),
        pl.col("_ignored"),
    )


def _unconvertible_rows(
    facilities: pl.LazyFrame,
    loans: pl.LazyFrame,
    contingents: pl.LazyFrame | None,
    facility_mappings: pl.LazyFrame,
    root_lookup: pl.LazyFrame,
    fx: FacilityFx,
) -> list[pl.LazyFrame]:
    """HIE005: every amount ``facility_undrawn`` had to leave un-netted.

    Three sources, mirroring the three conversions the netting performs: a
    drawing against its ROOT facility, a drawing against the sub-facility it is
    mapped to (sub-facilities only — a root's direct children are the first
    case), and a sub-facility's own headroom against its umbrella.
    """
    facility_currency = facility_currency_lookup(
        facilities, key="_netting_facility", currency="_netting_currency"
    )
    sub_facilities = root_lookup.select(
        pl.col("child_facility_reference").alias("_netting_facility")
    ).unique()

    frames: list[pl.LazyFrame] = []
    for frame, child_type in ((loans, "loan"), (contingents, "contingent")):
        if frame is None:
            continue
        for to_root in (True, False):
            rows = facility_utilisation_rows(
                frame,
                child_type,
                facility_mappings,
                root_lookup,
                facility_currency,
                fx,
                to_root=to_root,
            )
            if not to_root:
                rows = rows.join(sub_facilities, on="_netting_facility", how="semi")
            frames.append(
                rows.filter(pl.col("_fx_factor").is_null() & (pl.col("_amount") != 0.0)).select(
                    pl.lit(ERROR_FACILITY_HEADROOM_FX_RATE_MISSING).alias("_code"),
                    pl.col("_netting_facility").alias("_facility"),
                    pl.col("_amount_currency").alias("_value"),
                    pl.col("_netting_currency").alias("_target_currency"),
                )
            )

    sub_limits = (
        root_lookup.select(
            pl.col("child_facility_reference").alias("_facility"),
            pl.col("root_facility_reference").alias("_umbrella"),
        )
        .join(
            facilities.filter(pl.col("limit").is_not_null()).select(
                pl.col("facility_reference").alias("_facility"),
                pl.col("currency").alias("_value"),
            ),
            on="_facility",
            how="inner",
        )
        .join(
            facility_currency.rename(
                {"_netting_facility": "_umbrella", "_netting_currency": "_target_currency"}
            ),
            on="_umbrella",
            how="left",
        )
    )
    frames.append(
        with_facility_currency_factor(
            sub_limits,
            fx,
            amount_currency="_value",
            facility_currency="_target_currency",
            factor="_sub_fx_factor",
        )
        .filter(pl.col("_sub_fx_factor").is_null())
        .select(
            pl.lit(ERROR_FACILITY_HEADROOM_FX_RATE_MISSING).alias("_code"),
            pl.col("_facility"),
            pl.col("_value"),
            pl.col("_target_currency"),
            pl.col("_umbrella"),
        )
    )
    return frames


def _summary_detail(code: str, omitted: list[dict[str, str | None]]) -> str:
    """What the omitted facilities of one code have in common, for its summary."""
    if code == ERROR_FACILITY_MAPPING_MULTI_PARENT:
        return (
            "loans / contingents mapped under more than one facility, each reducing "
            "one root's headroom once"
        )
    if code == ERROR_UNCOMMITTED_FACILITY_RISK_TYPE:
        return "committed=False facilities declaring a non-LR risk_type, priced as LR"
    if code == ERROR_FACILITY_HEADROOM_FX_RATE_MISSING:
        currencies = ", ".join(sorted({str(row["_value"]) for row in omitted}))
        return (
            f"amounts in {currencies} with no FX rate into their facility's currency, "
            "not netted against its headroom"
        )
    return "facilities with no limit, so no undrawn commitment row"


def _to_error(row: dict[str, str | None]) -> CalculationError:
    """Turn one warning row into its ``CalculationError``."""
    facility = str(row["_facility"])
    code = row["_code"]
    if code == ERROR_FACILITY_MAPPING_MULTI_PARENT:
        ignored = row["_ignored"]
        return facility_multi_parent_warning(
            child_reference=str(row["_value"]),
            child_type=str(row["_child_type"]),
            parents=str(row["_parents"]).split(", "),
            kept=facility,
            ignored=ignored.split(", ") if ignored else (),
        )
    if code == ERROR_UNCOMMITTED_FACILITY_RISK_TYPE:
        return uncommitted_facility_risk_type_warning(
            facility_reference=facility, risk_type=str(row["_value"])
        )
    if code == ERROR_FACILITY_HEADROOM_FX_RATE_MISSING:
        return facility_headroom_fx_rate_missing_warning(
            facility_reference=facility,
            currency=str(row["_value"]),
            facility_currency=str(row["_target_currency"]),
            umbrella_reference=row["_umbrella"],
        )
    return facility_limit_missing_warning(facility_reference=facility)
