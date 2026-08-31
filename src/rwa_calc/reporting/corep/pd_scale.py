"""
The fixed regulatory PD scale row axis shared by COREP C 08.03 and C 08.05.

Pipeline position:
    OutputAggregator -> corep.c08 (C 08.03 / C 08.05) -> COREPTemplateBundle

Key responsibilities:
- Derive the two PD-band label columns an exposure frame needs to key the
  hierarchical row axis (``c08_pd_range`` = leaf band, ``c08_pd_parent`` =
  enclosing parent band)
- Return the populated rows in published template order, sparse

Why two columns: the published scale is HIERARCHICAL, not a partition. Four of
its top-level bands repeat their span as a finer sub-breakdown on the rows
immediately below, so a parent row overlaps its children and equals their sum
(EBA v09753-v09756 / BoE boe_b0767-boe_b0770). An exposure sits in exactly one
LEAF band, but a parent row spans several leaves, so no single label column can
key every row. Splitting the label into leaf and parent keeps every row a single
equality term, which is the shape ``SheetPlan.row_terms`` and the rebuilt
drill-down predicates both require.

References:
- Regulation (EU) 2021/451 Annex I, template C 08.03 (row axis)
- PRA PS1/26 Annex I, template OF 08.03 (row axis; splits the first sub-band)
- PRA PS1/26 Annex II §3.3.5, "PD RANGE (PRE-INPUT FLOOR) (%)" row instructions
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.reporting.corep.templates import (
    C08_03_PD_PARENT_REFS,
    get_c08_03_pd_ranges,
)
from rwa_calc.reporting.kernel.columns import pick

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

#: The derived leaf-band label column: the one band an exposure actually sits in.
PD_LEAF_COL = "c08_pd_range"

#: The derived parent-band label column: the enclosing aggregate band, or
#: "Unassigned" for a PD outside every parent's span (the 0.15-0.75 and
#: 100%-default bands stand alone).
PD_PARENT_COL = "c08_pd_parent"

#: The residual row for a null / out-of-scale PD.
UNASSIGNED = "Unassigned"

#: Suffix marking the POST-CRM twin of each label column. C 08.03 bands its
#: post-CRM column block on the PD that actually risk-weighted the leg, so a
#: substituted leg carries one band under each basis; C 08.05 has no post-CRM
#: column and uses the unsuffixed pair alone.
POST_SUFFIX = "_post"

_Band = tuple[float, float, str, str]


def pd_band_col(cols: set[str], framework: str) -> str | None:
    """The PD column the ORIGIN limb of the row axis bands on.

    Basel 3.1's axis is stated "PD RANGE (PRE-INPUT FLOOR)" (PS1/26 Annex II
    section 3.3.5.2) so it prefers the raw estimate; CRR's names no carve-out
    and takes the floored PD. Shared by C 08.03 and C 08.05.
    """
    if framework == "BASEL_3_1":
        return pick(cols, "pd", "pd_floored")
    return pick(cols, "pd_floored", "pd")


def pd_band_col_post(cols: set[str], framework: str) -> str | None:
    """The PD column the POST-CRM limb bands on: the PD that risk-weighted it.

    Each regime takes the post-CRM carrier matching its own axis basis, because
    substitution changes WHOSE PD is banded, not which basis the axis is stated
    on. The fallback is :func:`pd_band_col` itself rather than a parallel
    candidate ladder, and that is the degradation contract: a frame sealing no
    post-CRM carrier bands both limbs on the same column and reproduces the
    single-basis output exactly. C 08.05 has no post-CRM column and never calls
    this.
    """
    carrier = (
        "reporting_pd_post_crm_pre_floor" if framework == "BASEL_3_1" else "reporting_pd_post_crm"
    )
    return carrier if carrier in cols else pd_band_col(cols, framework)


def banded_rows(
    class_df: pl.DataFrame, alloc_pd_col: str, framework: str
) -> tuple[list[tuple[str, str, str]], pl.DataFrame]:
    """Assign the fixed PD scale to ``class_df``.

    Returns the populated ``(row_ref, label, term_column)`` rows in published
    template order — plus a trailing 9999 "Unassigned" row when any PD falls
    outside the scale — and the frame with both label columns added.

    Rows stay sparse (only populated bands emit). A populated leaf always
    populates its parent, so a parent never emits without at least one child.
    """
    ranges = get_c08_03_pd_ranges(framework)
    leaves = [band for band in ranges if band[2] not in C08_03_PD_PARENT_REFS]
    parents = [band for band in ranges if band[2] in C08_03_PD_PARENT_REFS]
    banded = class_df.with_columns(
        _band_label_expr(leaves, alloc_pd_col).alias(PD_LEAF_COL),
        _band_label_expr(parents, alloc_pd_col).alias(PD_PARENT_COL),
    )
    present = {
        PD_LEAF_COL: set(banded[PD_LEAF_COL].to_list()),
        PD_PARENT_COL: set(banded[PD_PARENT_COL].to_list()),
    }
    rows: list[tuple[str, str, str]] = []
    for _lower, _upper, ref, label in ranges:
        column = PD_PARENT_COL if ref in C08_03_PD_PARENT_REFS else PD_LEAF_COL
        if label in present[column]:
            rows.append((ref, label, column))
    if UNASSIGNED in present[PD_LEAF_COL]:
        rows.append(("9999", UNASSIGNED, PD_LEAF_COL))
    return rows, banded


def banded_rows_by_basis(
    class_df: pl.DataFrame,
    origin_pd_col: str,
    post_pd_col: str,
    framework: str,
    *,
    origin_flag: str,
    post_flag: str,
) -> tuple[list[tuple[str, str, str, str]], pl.DataFrame]:
    """Assign the fixed PD scale TWICE — once per basis — to ``class_df``.

    The two-basis sheet axis (``kernel/bases.py``) on the ROW axis. C 08.03's
    pre-CRM columns report a leg against its obligor's PD band while its
    post-CRM columns report the same leg against the band of the PD actually
    used to risk-weight it, so one leg can occupy two different rows depending
    on which column is asking. Four label columns carry that: the origin pair
    (``c08_pd_range`` / ``c08_pd_parent``) and the post pair (both with
    ``POST_SUFFIX``).

    Returns the populated ``(row_ref, label, origin_term_column,
    post_term_column)`` rows in published template order — plus a trailing 9999
    "Unassigned" row — and the frame with all four label columns added.

    A row emits when EITHER basis populates it, and each basis is counted only
    over the legs actually ON it (``origin_flag`` / ``post_flag``), so a leg
    that merely ARRIVED on this sheet no longer forces an empty origin row into
    the axis. Passing the same column for both bases reproduces
    ``banded_rows``'s single-basis output exactly, which is what makes the split
    number-neutral on a book that never substitutes.
    """
    ranges = get_c08_03_pd_ranges(framework)
    leaves = [band for band in ranges if band[2] not in C08_03_PD_PARENT_REFS]
    parents = [band for band in ranges if band[2] in C08_03_PD_PARENT_REFS]
    banded = class_df.with_columns(
        _band_label_expr(leaves, origin_pd_col).alias(PD_LEAF_COL),
        _band_label_expr(parents, origin_pd_col).alias(PD_PARENT_COL),
        _band_label_expr(leaves, post_pd_col).alias(PD_LEAF_COL + POST_SUFFIX),
        _band_label_expr(parents, post_pd_col).alias(PD_PARENT_COL + POST_SUFFIX),
    )
    present = _labels_present(banded, origin_flag, suffix="") | _labels_present(
        banded, post_flag, suffix=POST_SUFFIX
    )
    rows: list[tuple[str, str, str, str]] = []
    for _lower, _upper, ref, label in ranges:
        column = PD_PARENT_COL if ref in C08_03_PD_PARENT_REFS else PD_LEAF_COL
        if (column, label) in present:
            rows.append((ref, label, column, column + POST_SUFFIX))
    if (PD_LEAF_COL, UNASSIGNED) in present:
        rows.append(("9999", UNASSIGNED, PD_LEAF_COL, PD_LEAF_COL + POST_SUFFIX))
    return rows, banded


def _labels_present(banded: pl.DataFrame, flag: str, *, suffix: str) -> set[tuple[str, str]]:
    """The ``(unsuffixed_column, label)`` pairs one basis populates.

    Keyed on the UNSUFFIXED column so the origin and post limbs union into one
    set: the two bases populate the same published rows, just from different
    PD columns. An absent flag column admits every leg, which keeps a synthetic
    frame that seals no basis flags on the single-basis behaviour.
    """
    rows = banded.filter(pl.col(flag)) if flag in banded.columns else banded
    return {
        (column, label)
        for column in (PD_LEAF_COL, PD_PARENT_COL)
        for label in rows[column + suffix].to_list()
    }


def _band_label_expr(bands: Sequence[_Band], alloc_pd_col: str) -> pl.Expr:
    """A label expression over half-open ``[lower, upper)`` bands.

    Falls through to "Unassigned" outside every band, which is also where a null
    PD lands.
    """
    expr: pl.Expr = pl.lit(UNASSIGNED)
    for lower, upper, _ref, label in reversed(bands):
        expr = (
            pl.when((pl.col(alloc_pd_col) >= lower) & (pl.col(alloc_pd_col) < upper))
            .then(pl.lit(label))
            .otherwise(expr)
        )
    return expr
