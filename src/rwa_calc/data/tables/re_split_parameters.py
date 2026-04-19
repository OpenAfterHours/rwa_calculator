"""
Real estate loan-splitting parameters (CRR Art. 125/126, Basel 3.1 Art. 124F/H).

Pipeline position:
    Consumed by ``engine/re_splitter.py`` to physically split a property-
    collateralised non-RE exposure into a secured RESIDENTIAL_MORTGAGE /
    COMMERCIAL_MORTGAGE row and an uncollateralised residual row in the
    original counterparty class.

Key responsibilities:
- Single source of truth for the regime-specific secured-LTV cap and
  secured risk weight that drive the row split.
- Framework-aware lookup so the splitter can dispatch on
  ``config.is_basel_3_1`` without re-declaring 0.20 / 0.35 / 0.50 /
  0.55 / 0.60 / 0.80 in engine code (enforced by
  ``scripts/arch_check.py`` check 5).

References:
- CRR Art. 125: Residential mortgage 35% on portion up to 80% LTV.
- CRR Art. 126: Commercial real estate 50% on portion up to 50% LTV
  when rental income covers >= 1.5x interest costs.
- PRA PS1/26 Art. 124F: B3.1 RRE loan-splitting — 20% on portion up
  to 55% of property value (less prior charges per Art. 124F(2)).
- PRA PS1/26 Art. 124H(1)-(2): B3.1 CRE loan-splitting for natural
  persons / SMEs — 60% on portion up to 55% of property value.
- PRA PS1/26 Art. 124H(3): B3.1 CRE for other counterparties — no
  physical split; ``max(60%, min(cp_rw, Art. 124I RW))`` applied to
  the whole exposure (handled by ``b31_commercial_rw_expr``).
- PRA PS1/26 Art. 124L: Counterparty-type table for the residual RW
  on RRE splits (75% / 85% / social housing floor / counterparty RW).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class SplitParameters:
    """Regime + property-type specific inputs for the loan-split mechanism.

    Attributes:
        secured_ltv_cap: Maximum LTV for the preferential secured RW
            (e.g. 0.80 for CRR RRE, 0.55 for B3.1 RRE).
        secured_rw: Risk weight applied to the secured portion
            (e.g. 0.35 for CRR RRE, 0.20 for B3.1 RRE).
        uses_prior_charge_reduction: When True, the effective cap is
            ``max(0, secured_ltv_cap - prior_charge_ltv)`` per Art. 124F(2).
            CRR has no analogous reduction; junior charges are handled
            via collateral eligibility instead.
        target_class: SA exposure class label assigned to the secured row.
        whole_only_when_not_npsme: B3.1 CRE Art. 124H(3) carve-out — when
            True and the counterparty is neither a natural person nor an
            SME, no physical split is performed; the whole exposure is
            reclassified to ``COMMERCIAL_MORTGAGE`` so the existing
            ``b31_commercial_rw_expr`` Art. 124H(3) branch applies.
        requires_cre_rental_coverage: CRR CRE Art. 126(2)(d) only.
            When True, the split applies only when the rental-income
            coverage test (>= 1.5x interest costs) is satisfied.
    """

    secured_ltv_cap: Decimal
    secured_rw: Decimal
    target_class: str
    uses_prior_charge_reduction: bool = False
    whole_only_when_not_npsme: bool = False
    requires_cre_rental_coverage: bool = False


# CRR Art. 125 — Residential mortgage loan-splitting
RE_SPLIT_PARAMS_CRR_RESIDENTIAL = SplitParameters(
    secured_ltv_cap=Decimal("0.80"),
    secured_rw=Decimal("0.35"),
    target_class="RESIDENTIAL_MORTGAGE",
)

# CRR Art. 126 — Commercial real estate (rental coverage required)
RE_SPLIT_PARAMS_CRR_COMMERCIAL = SplitParameters(
    secured_ltv_cap=Decimal("0.50"),
    secured_rw=Decimal("0.50"),
    target_class="COMMERCIAL_MORTGAGE",
    requires_cre_rental_coverage=True,
)

# PRA PS1/26 Art. 124F — B3.1 residential RE (general / non-income-producing)
RE_SPLIT_PARAMS_B31_RESIDENTIAL = SplitParameters(
    secured_ltv_cap=Decimal("0.55"),
    secured_rw=Decimal("0.20"),
    target_class="RESIDENTIAL_MORTGAGE",
    uses_prior_charge_reduction=True,
)

# PRA PS1/26 Art. 124H(1)-(2) and Art. 124H(3) — B3.1 commercial RE.
# whole_only_when_not_npsme routes corporate (non-NP, non-SME) counterparties
# through Art. 124H(3) with a single COMMERCIAL_MORTGAGE row.
RE_SPLIT_PARAMS_B31_COMMERCIAL = SplitParameters(
    secured_ltv_cap=Decimal("0.55"),
    secured_rw=Decimal("0.60"),
    target_class="COMMERCIAL_MORTGAGE",
    uses_prior_charge_reduction=True,
    whole_only_when_not_npsme=True,
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
