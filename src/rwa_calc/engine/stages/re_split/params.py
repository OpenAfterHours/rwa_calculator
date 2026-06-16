"""
Real-estate loan-split parameters (CRR Art. 125/126, Basel 3.1 Art. 124F/H).

Pipeline position:
    Consumed by ``engine/stages/re_split/splitter.py`` to physically split a
    property-collateralised non-RE exposure into a secured RESIDENTIAL_MORTGAGE
    / COMMERCIAL_MORTGAGE row and an uncollateralised residual row.

Key responsibilities:
- Resolve the regime-specific secured-LTV cap (the preferential-RW LTV ceiling)
  from the rulepack and expose it, with the prior-charge-reduction flag, as a
  small frozen ``SplitParameters`` record per property type. The cap values live
  in the rulepack (``re_split_{rre,cre}_secured_ltv_cap`` in packs/{crr,b31}.py);
  this module only derives the float-typed records the splitter consumes.

References:
- CRR Art. 125: Residential mortgage 35% on portion up to 80% LTV.
- CRR Art. 126: Commercial real estate 50% on portion up to 50% LTV.
- PRA PS1/26 Art. 124F: B3.1 RRE loan-splitting — 20% on portion up to 55% of
  property value (less prior charges per Art. 124F(2)).
- PRA PS1/26 Art. 124H(1)-(2): B3.1 CRE loan-splitting — 60% on portion up to
  55% of property value.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from rwa_calc.rulebook.compile import scalar_value
from rwa_calc.rulebook.resolve import resolve

_CRR_PACK = resolve("crr", date(2026, 1, 1))
_B31_PACK = resolve("b31", date(2027, 1, 1))


@dataclass(frozen=True)
class SplitParameters:
    """Regime + property-type specific inputs for the loan-split mechanism.

    Attributes:
        secured_ltv_cap: Maximum LTV for the preferential secured RW
            (e.g. 0.80 for CRR RRE, 0.55 for B3.1 RRE).
        uses_prior_charge_reduction: When True, the effective cap is
            ``max(0, secured_ltv_cap - prior_charge_ltv)`` per Art. 124F(2).
            CRR has no analogous reduction; junior charges are handled via
            collateral eligibility instead.
    """

    secured_ltv_cap: float
    uses_prior_charge_reduction: bool = False


# CRR Art. 125/126 — secured-LTV caps from the rulepack (RRE 80%, CRE 50%).
RE_SPLIT_PARAMS_CRR_RESIDENTIAL = SplitParameters(
    secured_ltv_cap=scalar_value(_CRR_PACK.scalar_param("re_split_rre_secured_ltv_cap")),
)
RE_SPLIT_PARAMS_CRR_COMMERCIAL = SplitParameters(
    secured_ltv_cap=scalar_value(_CRR_PACK.scalar_param("re_split_cre_secured_ltv_cap")),
)

# PRA PS1/26 Art. 124F/124H — B3.1 caps (RRE/CRE 55%) with prior-charge reduction.
RE_SPLIT_PARAMS_B31_RESIDENTIAL = SplitParameters(
    secured_ltv_cap=scalar_value(_B31_PACK.scalar_param("re_split_rre_secured_ltv_cap")),
    uses_prior_charge_reduction=True,
)
RE_SPLIT_PARAMS_B31_COMMERCIAL = SplitParameters(
    secured_ltv_cap=scalar_value(_B31_PACK.scalar_param("re_split_cre_secured_ltv_cap")),
    uses_prior_charge_reduction=True,
)


def re_split_parameters(*, is_basel_3_1: bool) -> dict[str, SplitParameters]:
    """Return the regime-specific split parameter map.

    Args:
        is_basel_3_1: Selects the PRA PS1/26 Art. 124F/H values when True;
            otherwise returns the CRR Art. 125/126 values.

    Returns:
        Mapping of property type ("residential" / "commercial") to the
        corresponding ``SplitParameters``.
    """
    if is_basel_3_1:
        return {
            "residential": RE_SPLIT_PARAMS_B31_RESIDENTIAL,
            "commercial": RE_SPLIT_PARAMS_B31_COMMERCIAL,
        }
    return {
        "residential": RE_SPLIT_PARAMS_CRR_RESIDENTIAL,
        "commercial": RE_SPLIT_PARAMS_CRR_COMMERCIAL,
    }
