"""Small C 08.06 sheet-routing, empty-row and risk-weight (col 0070) policies.

Col 0070 under CRR is Art. 153(5) Table 1 printed onto the template. Annex II
(p.115) reads: "This is a fixed column for information purposes. It shall not be
altered." Table 1 gives a weight per category x maturity cell and none for a
total, so a CRR Total row reports no col 0070. The CR10 disclosure of the same
grid does the same (``pillar3/cr10.py``: "Total rows null"). The filing adapter
does not evaluate the column either (``filing/bindings.py``).

References:
- Regulation (EU) 2021/451, Annex II, C 08.06 (col 0070: PDF p.115)
- CRR Art. 153(5) Table 1
- PRA PS1/26 Annex I/II, OF 08.06
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.reporting.cellspec import CellSpec, Formula, RowPredicate, WeightedAvg
from rwa_calc.reporting.corep.postpass import c08_06_zero_row

if TYPE_CHECKING:
    from collections.abc import Mapping

_POST_BASIS_REFS: tuple[str, ...] = ("0020", "0040", "0050", "0070", "0080")


def c08_06_sl_type_sheet(
    data: pl.DataFrame, sl_key: str, cols: set[str], framework: str
) -> pl.DataFrame:
    """Route one SL type, keeping Basel 3.1 IPRE and HVCRE disjoint.

    CRR is unchanged: its IPRE sheet ABSORBS HVCRE (there is no separate HVCRE
    sheet), so both ``sl_type`` values land there.

    THE B31 PARTITION IS A NUMBER-CHANGING FIX, not a refactor. The retired
    routing sent the HVCRE sheet ``(sl_type == "hvcre") | is_hvcre`` while the
    IPRE sheet took every ``sl_type == "ipre"`` row unconditionally, so an IPRE
    row carrying the flag — the canonical shape, since HVCRE is a REFINEMENT of
    IPRE rather than a sibling ``sl_type`` — was reported on BOTH sheets and its
    exposure double-counted across the template. It also let the flag drag a
    project/object/commodities-finance row onto the HVCRE sheet, which the flag
    does not mean. The two limbs below now partition IPRE on the flag, so
    ``ipre + hvcre`` sums to the IPRE book exactly once
    (``tests/unit/test_corep_c08_06.py::TestC0806B31Features``).
    """
    has_hvcre = "is_hvcre" in cols
    if sl_key == "ipre" and framework != "BASEL_3_1" and has_hvcre:
        return data.filter(pl.col("sl_type").is_in(["ipre", "hvcre"]))
    if sl_key == "ipre" and framework == "BASEL_3_1" and has_hvcre:
        return data.filter(
            (pl.col("sl_type") == "ipre") & pl.col("is_hvcre").fill_null(False).not_()
        )
    if sl_key == "hvcre" and framework == "BASEL_3_1" and has_hvcre:
        return data.filter(
            (pl.col("sl_type") == "hvcre")
            | ((pl.col("sl_type") == "ipre") & pl.col("is_hvcre").fill_null(False))
        )
    return data.filter(pl.col("sl_type") == sl_key)


def c08_06_empty_row_override(
    column_refs: tuple[str, ...], rw_display: str, *, origin_populated: bool
) -> dict[str, float | None]:
    """Zero an empty post-basis row without erasing populated origin cells."""
    zeroes = c08_06_zero_row(column_refs, rw_display)
    if not origin_populated:
        return zeroes
    return {ref: zeroes[ref] for ref in _POST_BASIS_REFS if ref in zeroes}


def c08_06_risk_weight_cell(
    label: str, framework: str, ead_col: str, predicate: RowPredicate
) -> CellSpec:
    """Col 0070 (RISK WEIGHT) on one row whose subset is not empty.

    A category row binds the exposure-weighted risk weight of its legs. Under CRR
    that is the row's Table 1 weight wherever the engine's lookup and the row key
    a leg on the same ``slotting_category`` and ``is_short_maturity`` (measured on
    every registered portfolio). A CRR Total row binds a constant blank: Table 1
    has no weight for a total, and the column "shall not be altered" (Annex II
    p.115). Basel 3.1 is unchanged here. PS1/26 Annex II OF 08.06 has no column
    0070, and that layout gap is a separate item.
    (An EMPTY category row is not bound at all: the zero-fill writes its fixed
    display weight, ``c08_06.py::_c08_06_empty_refs``.)
    """
    if not _reports_risk_weight(label, framework):
        return CellSpec(Formula(refs=(), fn=_blank))
    return CellSpec(
        WeightedAvg("risk_weight", weight=ead_col), predicate=predicate, empty_cell="null"
    )


def c08_06_zero_ead_fixes(
    subset: pl.DataFrame, label: str, framework: str
) -> dict[str, float | None]:
    """The fixes for a row whose legs carry no exposure value.

    Col 0040 clamps to 0.0. With no exposure to weight there is no average, so a
    row that reports col 0070 takes its first leg's risk weight (on a CRR
    category row, the row's Table 1 weight). A CRR Total row takes nothing:
    it reports no col 0070 (``c08_06_risk_weight_cell``), and the reported frame
    must agree with the spec the drill-down reads.
    """
    fixes: dict[str, float | None] = {"0040": 0.0}
    if subset.height == 0 or "risk_weight" not in subset.columns:
        return fixes
    if not _reports_risk_weight(label, framework):
        return fixes
    rw_vals = subset["risk_weight"].drop_nulls()
    fixes["0070"] = float(rw_vals[0]) if len(rw_vals) > 0 else None
    return fixes


def _reports_risk_weight(label: str, framework: str) -> bool:
    """Whether a C 08.06 row reports col 0070: every row except a CRR Total."""
    return label != "Total" or framework == "BASEL_3_1"


def _blank(_cells: Mapping[str, float | None], _prior_available: bool) -> None:
    """A cell the template defines as empty."""
    return None
