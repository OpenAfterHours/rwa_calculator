"""Small C 08.06 sheet-routing and empty-row policies.

References:
- Regulation (EU) 2021/451, Annex II, C 08.06
- PRA PS1/26 Annex I/II, OF 08.06
"""

from __future__ import annotations

import polars as pl

from rwa_calc.reporting.corep.postpass import c08_06_zero_row

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
