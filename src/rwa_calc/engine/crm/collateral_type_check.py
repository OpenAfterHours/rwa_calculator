"""
Collateral-type recognition check (CRM021).

Pipeline position:
    CRMProcessor collateral step -> record_unrecognised_collateral_type
        -> apply_collateral

Key responsibilities:
- Name every collateral row whose ``collateral_type`` matches no known category

WHY THIS IS A DEFECT WORTH NAMING. ``collateral_category_expr``
(``engine/crm/expressions.py``) classifies each row into one of the COREP
categories and falls through to ``"other"`` for anything it does not recognise.
``WATERFALL_ORDER`` keys on the SAME six type sets, so a row that falls through
is recognised at no supervisory LGD in the Art. 231 waterfall, contributes to no
``collateral_*_value`` carrier, and therefore appears in no CRM reporting column
— while still CHANGING RWA. Today all of that is silent: spelling real-estate
collateral ``residential_real_estate`` instead of ``real_estate`` moved a Basel
3.1 retail-mortgage fixture from 39,848 to 71,534 with no error, no warning and
no trace in any published column. The cause is almost always one mis-mapped
source string, so the warning names the offending value as well as the row.

Kept out of ``collateral.py`` deliberately: that module sits at the engine
module-size ceiling tracked by ``scripts/arch_check.py`` check 11, and this
check has no dependency on the allocation machinery there.

References:
    CRR Art. 230-231: collateral category -> supervisory LGD waterfall
    PRA PS1/26 Art. 230-231: retained equivalents
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from rwa_calc.contracts.errors import ERROR_UNRECOGNISED_COLLATERAL_TYPE, crm_warning
from rwa_calc.engine.crm.expressions import unrecognised_collateral_type_expr

if TYPE_CHECKING:
    import polars as pl

    from rwa_calc.contracts.errors import CalculationError

logger = logging.getLogger(__name__)


def record_unrecognised_collateral_type(
    collateral: pl.LazyFrame,
    errors: list[CalculationError],
) -> None:
    """Append one CRM021 warning per collateral row with an unknown type.

    Targeted collect of the offending rows only — the accepted data-quality
    emission idiom (P1.264). Per-row rather than rolled up because the value is
    what makes the defect fixable, and because a portfolio with a broken type
    mapping is a feed defect to correct, not a steady state to tolerate.

    A NULL ``collateral_type`` does not warn: ``unrecognised_collateral_type_expr``
    yields null for it and the filter drops it, matching the project's
    null-permissive convention (absence is not an asserted defect).
    """
    gated = (
        collateral.filter(unrecognised_collateral_type_expr())
        .select("collateral_reference", "collateral_type")
        .collect()
    )
    if gated.height == 0:
        return
    logger.debug("CRM021: %d collateral row(s) carry an unrecognised type", gated.height)
    for row in gated.iter_rows(named=True):
        errors.append(
            crm_warning(
                ERROR_UNRECOGNISED_COLLATERAL_TYPE,
                f"Collateral '{row.get('collateral_reference')}' has collateral_type "
                f"'{row.get('collateral_type')}', which matches no recognised collateral "
                f"category; it is treated as unclassified 'other', so it is recognised at "
                f"no supervisory LGD in the Art. 231 waterfall and appears in no CRM "
                f"reporting column. Check the source mapping against the documented "
                f"collateral types.",
                regulatory_reference="CRR/PS1-26 Art. 230-231",
            )
        )
