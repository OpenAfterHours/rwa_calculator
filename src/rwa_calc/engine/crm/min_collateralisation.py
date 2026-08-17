"""
Art. 230 minimum-collateralisation (C*) threshold and its diagnostic (CRM022).

Pipeline position:
    _apply_collateral_unified (threshold zeroing, via
        ``below_min_collateralisation_expr``)
        -> CRMProcessor crm_exit edge
        -> record_below_min_collateralisation (CRM022)

Key responsibilities:
- Own the single definition of the CRR Art. 230(2) Table 5 C* drop condition
- Name the F-IRB exposures whose eligible non-financial collateral it dropped

WHY THIS IS WORTH NAMING. CRR Art. 230(2) Table 5 sets a minimum required
collateralisation level C* of 30% of the exposure for real-estate and other-physical
collateral. Below it the exposure is treated as **fully unsecured**: the whole
category leaves the Art. 231 sequential-fill waterfall and LGD reverts to LGDU
(45% senior corporate under Art. 161(1)(a)). That is correct capital, and it was the
one collateral outcome the engine reached in complete silence — the preparer saw a
populated COREP C 08.01/02 col 0190, an LGD at the supervisory unsecured value, and
nothing joining the two. A supported query about exactly that pairing is what
prompted this check.

WHY THE WARNING IS NOT EMITTED AT THE THRESHOLD SITE. The gate reads
``collateral_re_value`` / ``collateral_other_physical_value``, which only exist after
the multi-level collateral joins in ``collateral.py``. Collecting them there
re-executed that whole plan: +1.1s per 200k exposures, ~45% of the CRM stage, and paid
even on an all-SA book where the warning cannot fire. Reading the frame after the
``crm_exit`` materialisation instead makes the aggregate a projection over in-memory
data at no measurable cost — the same reasoning that already places the
``collateral_allocation`` / ``crm_audit`` projections after that edge.

Kept out of ``collateral.py`` deliberately, following
``collateral_type_check.py``: that module sits at the engine module-size ceiling
tracked by ``scripts/arch_check.py``, and the C* definition has no dependency on the
allocation machinery there.

References:
    CRR Art. 230(2) Table 5: C* minimum collateralisation, C** over-collateralisation
    CRR Art. 231: the sequential-fill waterfall the dropped amount would have fed
    CRR Art. 223(4): E is the CCF=100% basis (``ead_for_crm``)
    CRR Art. 161(1)(a): the senior unsecured LGD the exposure reverts to
    PRA PS1/26 Art. 230(1): replaces the step function and removes C*/C** entirely
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.contracts.errors import ERROR_BELOW_MIN_COLLATERALISATION, crm_warning
from rwa_calc.domain.enums import ApproachType
from rwa_calc.rulebook import RulepackV0
from rwa_calc.rulebook.compile import lookup_float_map

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.contracts.errors import CalculationError
    from rwa_calc.rulebook.resolve import ResolvedRulepack

logger = logging.getLogger(__name__)

#: The two categories CRR Art. 230(2) Table 5 gives a C* to, as ``WATERFALL_ORDER``
#: suffix -> (``min_collateralisation_thresholds`` pack key, C_i carrier, CRM022 label).
#: One map, read by both the threshold site in ``collateral.py`` and the diagnostic
#: below, so the warning cannot come to describe a different set of categories than
#: the zeroing acts on. Financial, covered bond and receivables carry no C*.
MIN_COLLATERALISATION_CATEGORIES: dict[str, tuple[str, str, str]] = {
    "re": ("real_estate", "collateral_re_value", "real estate"),
    "op": ("other_physical", "collateral_other_physical_value", "other physical"),
}


def below_min_collateralisation_expr(value_col: str, threshold: float) -> pl.Expr:
    """``C < C* x E`` — the CRR Art. 230(2) Table 5 drop condition for one category.

    Sole definition of the C* arithmetic, read by both the zeroing in
    ``collateral.py::_apply_collateral_unified`` and the CRM022 diagnostic below, so
    the warning cannot describe a different population than the one actually dropped.
    E is ``ead_for_crm``, the CCF=100% basis per Art. 223(4).
    """
    return pl.col(value_col) < threshold * pl.col("ead_for_crm")


@cites("CRR Art. 230")
@cites("PS1/26 Art. 230")
def record_below_min_collateralisation(
    exposures: pl.LazyFrame,
    config: CalculationConfig,
    errors: list[CalculationError],
    *,
    pack: ResolvedRulepack | None = None,
) -> None:
    """Append one rolled-up CRM022 warning per collateral category that C* dropped.

    Must be called on a materialised frame (after the ``crm_exit`` edge) — see the
    module docstring for the measured reason — and only where collateral was applied,
    so the ``collateral_*_value`` carriers the gates read are present by construction.

    Rolled up per category rather than per row (the CRM018 idiom): a book of
    small-property SME lending trips this on thousands of rows at once, and per-row
    emission floods the error channel.

    Three scope conditions, each excluding a distinct false positive:

    - **F-IRB only.** C* gates the Foundation LGD* formula; an A-IRB row keeps its own
      estimate whether or not the threshold binds. (CRR is the only regime reaching
      here, and under CRR A-IRB never falls back to the formula, so F-IRB is exactly
      the affected population.)
    - **Positive C_i.** That is what makes the outcome a DROP rather than an absence of
      collateral, which needs no explaining.
    - **Art. 199-gated C_i.** The carrier is already zeroed for an unattested pledge,
      so CRM014 owns that cause and this cannot double-report one drop as two.

    No-op under Basel 3.1: PS1/26 Art. 230(1) removes C*/C**, which the
    ``firb_min_collateralisation_threshold_applies`` Feature records.
    """
    resolved = pack if pack is not None else RulepackV0.from_config(config).pack
    if not resolved.feature("firb_min_collateralisation_threshold_applies"):
        return
    thresholds = lookup_float_map(resolved.lookup("min_collateralisation_thresholds"))
    gates = [
        (threshold, label, _drop_gate(value_col, threshold))
        for threshold, value_col, label in (
            (thresholds.get(key, 0.0), value_col, label)
            for key, value_col, label in MIN_COLLATERALISATION_CATEGORIES.values()
        )
        if threshold > 0
    ]
    if not gates:
        return

    aggregates: list[pl.Expr] = []
    for index, (_threshold, _label, gate) in enumerate(gates):
        aggregates.append(gate.sum().alias(f"_n_{index}"))
        aggregates.append(
            # First five references only: enough for a preparer to find the rows,
            # bounded so one warning cannot carry a whole book's worth of ids.
            pl.col("exposure_reference").filter(gate).head(5).implode().alias(f"_refs_{index}")
        )
    summary = exposures.select(aggregates).collect()
    if summary.height == 0:
        return

    row = summary.row(0, named=True)
    for index, (threshold, label, _gate) in enumerate(gates):
        count = int(row[f"_n_{index}"] or 0)
        if count <= 0:
            continue
        refs = [r for r in (row[f"_refs_{index}"] or []) if r is not None]
        shown = ", ".join(f"'{r}'" for r in refs)
        more = f" (and {count - len(refs)} more)" if count > len(refs) else ""
        logger.debug("Art. 230 C* dropped %s collateral on %d F-IRB exposure(s)", label, count)
        errors.append(
            crm_warning(
                ERROR_BELOW_MIN_COLLATERALISATION,
                f"{count} F-IRB exposure(s) hold eligible {label} collateral worth less "
                f"than the Art. 230 minimum collateralisation level C* of "
                f"{threshold * 100:.0f}% of the exposure value, so that collateral is "
                f"dropped from the Art. 231 waterfall and the exposure is treated as "
                f"fully unsecured — LGD reverts to the unsecured supervisory value. "
                f"Affected: {shown}{more}.",
                exposure_reference=refs[0] if refs else None,
                regulatory_reference="CRR Art. 230(2) Table 5",
            )
        )


def _drop_gate(value_col: str, threshold: float) -> pl.Expr:
    """The CRM022 population for one category: an F-IRB row whose eligible C_i is
    positive but below C*."""
    return (
        (pl.col("approach") == ApproachType.FIRB.value)
        & (pl.col("ead_for_crm") > 0)
        & (pl.col(value_col) > 0)
        & below_min_collateralisation_expr(value_col, threshold)
    )
