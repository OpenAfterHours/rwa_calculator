"""
SA-CCR integer count constants + the wrong-way-risk LGD override.

Pipeline position:
    Consumed by ``engine/ccr/`` modules under the SA-CCR approach (CRR Part
    Three Title II Chapter 6 Section 3).

Key responsibilities:
- Hold the SA-CCR margin-period-of-risk (MPOR) integer day counts and the
  trade / dispute thresholds (CRR Art. 285) plus the 250-business-day year
  basis. These are integer counts and stay in the data layer. Every regulatory
  *scalar* (supervisory factors, correlations, maturity / PFE / duration /
  option-volatility / alpha constants) now lives in the rulepack
  (packs/{common,b31}.py) — see the pointer comment at the foot of this module.

Regulatory references:
- CRR Art. 285(2)-(3): MPOR floors — 5 BD repo/SFT, 10 BD standard OTC, 20 BD
  large or illiquid netting sets; >5000 trades triggers the 20-BD floor.
- CRR Art. 285(4): >2 disputes in the prior two quarters doubles the MPOR.
- CRR Art. 291(5)(c): specific wrong-way-risk LGD = 100% override.
- PRA PS1/26 Counterparty Credit Risk (CRR) Part: UK-onshored equivalents.
"""

from __future__ import annotations

from decimal import Decimal

# =============================================================================
# MATURITY-FACTOR / MPOR INTEGER COUNTS (CRR Art. 285(2)-(4))
# =============================================================================
# The maturity-factor scalars (Art. 279c) live in packs/common.py
# (mf_unmargined_cap_years / mf_unmargined_denom_years / mf_margined_scalar);
# the MPOR floor day counts + thresholds below are integer counts and stay here.

MF_MARGINED_FLOOR_DAYS_REPO_SFT: int = 5
MF_MARGINED_FLOOR_DAYS_OTC: int = 10
MF_MARGINED_FLOOR_DAYS_LARGE_OR_ILLIQUID: int = 20

# CRR Art. 285(3)(a): >5000 trades in netting set triggers 20-BD MPOR floor.
MF_MARGINED_LARGE_NETTING_SET_TRADE_COUNT: int = 5000

# CRR Art. 285(4): more than two disputes in the prior two quarters doubles
# the MPOR base period.
MF_MARGINED_DISPUTE_THRESHOLD: int = 2
MF_MARGINED_DISPUTE_MULTIPLIER: int = 2

# BCBS CRE52.40 footnote: 250-business-day year convention (consumed by
# engine/ccr/maturity_factor.py for the margined MPOR sqrt term).
SA_CCR_BUSINESS_DAYS_PER_YEAR: int = 250


# =============================================================================
# WRONG-WAY RISK LGD OVERRIDE (CRR Art. 291(5)(c))
#
# Specific wrong-way risk: when the trade-level connection of Art. 291(1)(b) is
# present, the synthetic single-trade netting set carved out by
# ``engine/ccr/wwr.py::apply_wwr_gate`` carries an LGD = 100% override feeding
# downstream IRB consumption (Art. 153) — replacing the bank's own LGD estimate.
# =============================================================================

CCR_WWR_SPECIFIC_LGD_OVERRIDE: Decimal = Decimal("1.0")


# =============================================================================
# REGULATORY SCALARS MOVED TO THE RULEPACK
#
# - Supervisory factors + sub-class factor tables (Art. 280 Table 1),
#   asset-class correlations (Art. 280a/b/c), and IR cross-bucket correlations
#   (Art. 277a) -> packs/common.py (sa_ccr_supervisory_factor* /
#   sa_ccr_correlation* / sa_ccr_ir_bucket_correlation* /
#   sa_ccr_supervisory_factors_* LookupTables); resolved in engine/ccr/pfe.py.
# - PFE multiplier floor F + denominator coefficient (Art. 278(3)) -> common
#   (pfe_multiplier_floor_f / pfe_aggregate_denom_coeff).
# - Supervisory duration rate + start floor (Art. 279b), maturity-factor
#   scalars (Art. 279c), option volatilities + CDO tranche delta (Art. 279a),
#   supervisory alpha + carve-out (Art. 274(2)) -> common.
# - Transitional alpha add-on phase fractions (PRA PS1/26 Art. 274(2A)) ->
#   packs/b31.py (sa_ccr_transitional_addon_phase); resolved in
#   engine/ccr/pipeline_adapter.py.
# =============================================================================
