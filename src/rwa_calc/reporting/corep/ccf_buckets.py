"""
The conversion-factor buckets of the off-balance-sheet breakdowns — one home.

Pipeline position:
    sealed aggregator-exit ledger (``ccf``, ``ccf_modelled``, ``ead_modelled``,
    ``is_revolving``, ``reporting_approach_origin``)
        -> here (which bucket a leg's conversion factor falls in)
        -> corep/c08_01_rows.py (OF 08.01 rows 0031, 0032, 0001, 0033, 0034, 0035)

Key responsibilities:
- Name the applied-conversion-factor carrier ladder (``CCF_CARRIERS``).
- State the value-to-bucket rule once (``ccf_bucket_expr``): a leg is in a
  bucket when its applied conversion factor, rounded to four places, IS that
  bucket's factor.
- Map the PS1/26 Art. 111(1) Table A1 factors onto the OF 08.01 breakdown rows,
  name the own-estimate row, and decide each IRB leg's row
  (``of08_01_ccf_row_expr``).

OF 07.00 (``corep/c07.py``, columns 0160-0190) still declares its own carrier
ladder and bucket expression, the same rule; it is pointed at ``CCF_CARRIERS``
and ``ccf_bucket_expr`` here once the parallel rewrite of that module merges.

THE OF 08.01 ROWS. PS1/26 Annex II p.116, rows "0031, 0032, 0001, 0033, 0035
BREAKDOWN OF OFF-BALANCE SHEET ITEMS BY CONVERSION FACTORS": "For exposures
subject to the slotting approach, the FIRB approach, or the AIRB approach where
neither conversion factors nor EADs are estimated, institutions shall report
values in rows that correspond to the applicable conversion factors in Article
111 of the Credit Risk: Standardised Approach (CRR) Part ... For exposures
subject to the AIRB approach for which conversion factors are estimated, or
where EADs are estimated directly, institutions shall report values in row
0035." The PRA001 v4.1.1 taxonomy publishes six rows, NOT in numeric order:
0031 10%, 0032 20%, 0001 40%, 0033 50%, 0034 100%, 0035 "Own estimate" (each a
member of ``eba_dim:CFO``; ``tests/contracts/test_of08_01_published_rows.py``
holds this module to the pack).

THE OWN-ESTIMATE ROW WINS OVER THE VALUE MATCH. An A-IRB leg is reported in row
0035 when it carries an own estimate of EAD (Art. 166D(3), ``ead_modelled``), or
when it is a revolving commitment with an own estimate of conversion factor
(Art. 166D(1)(a), ``ccf_modelled``) applied. The precedence is load-bearing: an
own estimate floored at half of a 40% item is 0.20 and would otherwise be filed
in the 20% row. The engine's eligibility test (revolving AND a Table A1 factor
below 100%) is not sealed per leg, so "the own estimate was applied" is read as
"applied factor below 100%": an own estimate of exactly 100% is therefore filed
in row 0034 with identical figures. Sealing the engine's own flag makes it
exact. Each limb is read only where its columns exist, so a frame that carries
neither, or carries them empty (a legacy-ledger projection maps no own estimate),
files every leg by its value.

A leg whose factor matches no bucket and is not an own estimate is in no row
(``None``); ``corep/c08_01_rows.warn_if_unbucketed`` reports any money that
leaves the breakdown that way.

References:
- PRA PS1/26 Art. 111(1) Table A1 (conversion factors 10% / 20% / 40% / 50% /
  100%); Art. 166C(1); Art. 166D(1)(a) and (3)
- PRA PS1/26 Annex II §3.3.3, OF 08.01 rows 0031, 0032, 0001, 0033, 0034, 0035
  (p.116)
- Bank of England Banking Taxonomy v4.1.1, module PRA001, table ``OF08.01.01.01``
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import polars as pl

from rwa_calc.reporting.corep.irb_sheets import AIRB
from rwa_calc.reporting.kernel import pick

if TYPE_CHECKING:
    from collections.abc import Mapping

#: Applied-conversion-factor carriers, in preference order. ``ccf`` is what the
#: aggregator exit seals; ``ccf_applied`` is the synthetic COREP / Pillar 3
#: unit-frame spelling (LESSONS B1: a bucket on a name no run produces reports
#: nothing, forever).
CCF_CARRIERS: Final[tuple[str, ...]] = ("ccf", "ccf_applied")

#: PS1/26 Art. 111(1) Table A1 conversion factor -> the OF 08.01 row it is
#: reported in (Annex II p.116; the taxonomy's own row codes).
OF08_01_ROW_BY_CCF: Final[Mapping[float, str]] = {
    0.1: "0031",
    0.2: "0032",
    0.4: "0001",
    0.5: "0033",
    1.0: "0034",
}
#: The row for an A-IRB own estimate of conversion factor or of EAD.
OWN_ESTIMATE_ROW: Final = "0035"
#: The six breakdown rows of OF 08.01 row 0030, in published order.
OF08_01_CCF_ROWS: Final[tuple[str, ...]] = (*OF08_01_ROW_BY_CCF.values(), OWN_ESTIMATE_ROW)

#: The decimal places a factor is compared at: what the engine computes is a
#: product of cited factors, so a value one ulp off a bucket is still that bucket.
_PLACES: Final = 4

_ORIGIN_APPROACH: Final = "reporting_approach_origin"
_OWN_EAD: Final = "ead_modelled"
_OWN_CCF: Final = "ccf_modelled"
_REVOLVING: Final = "is_revolving"
_FULL_CONVERSION: Final = 1.0


def ccf_bucket_expr(ccf_col: str, refs: Mapping[float, str]) -> pl.Expr:
    """The ref of the bucket whose factor ``ccf_col`` holds; null when none does.

    ``refs`` maps each bucket's conversion factor to the ref the caller reports
    it under (a column of OF 07.00, a row of OF 08.01). The factor is compared
    rounded to ``_PLACES`` decimal places.
    """
    factor = pl.col(ccf_col).cast(pl.Float64, strict=False).round(_PLACES)
    bucket: pl.Expr = pl.lit(None, dtype=pl.String)
    for value, ref in refs.items():
        bucket = pl.when(factor == round(value, _PLACES)).then(pl.lit(ref)).otherwise(bucket)
    return bucket


def of08_01_ccf_row_expr(cols: set[str]) -> pl.Expr | None:
    """Each leg's OF 08.01 conversion-factor row: ``OWN_ESTIMATE_ROW`` for an
    A-IRB own estimate, else the Table A1 row of its applied factor, else null.

    ``None`` when the frame carries no conversion-factor carrier at all, so the
    caller derives nothing and the rows key a column that matches no leg.
    Precedence and the one inexact case: module docstring.
    """
    ccf_col = pick(cols, *CCF_CARRIERS)
    if ccf_col is None:
        return None
    by_value = ccf_bucket_expr(ccf_col, OF08_01_ROW_BY_CCF)
    own = _own_estimate(cols, pl.col(ccf_col).cast(pl.Float64, strict=False).round(_PLACES))
    return pl.when(own).then(pl.lit(OWN_ESTIMATE_ROW)).otherwise(by_value)


def _own_estimate(cols: set[str], factor: pl.Expr) -> pl.Expr:
    """Is the leg an A-IRB exposure whose exposure value rests on an own
    estimate — of EAD (Art. 166D(3)) or, on a revolving commitment, of the
    conversion factor applied (Art. 166D(1)(a))? Each limb only where its
    columns exist."""
    if _ORIGIN_APPROACH not in cols:
        return pl.lit(value=False)
    limbs: list[pl.Expr] = []
    if _OWN_EAD in cols:
        limbs.append(pl.col(_OWN_EAD).is_not_null())
    if {_OWN_CCF, _REVOLVING} <= cols:
        limbs.append(
            pl.col(_REVOLVING).fill_null(value=False)
            & pl.col(_OWN_CCF).is_not_null()
            & (factor != _FULL_CONVERSION).fill_null(value=False)
        )
    if not limbs:
        return pl.lit(value=False)
    is_airb = (pl.col(_ORIGIN_APPROACH) == AIRB).fill_null(value=False)
    return is_airb & pl.any_horizontal(limbs).fill_null(value=False)
